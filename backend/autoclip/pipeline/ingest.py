"""Ingestion — YouTube URLs and local file uploads become source records.

Both paths converge on a validated :class:`~autoclip.db.models.Source` with a
file on disk and probed metadata.

A note on YouTube: as of 2026 most anonymous downloads hit a bot check, and
proof-of-origin tokens no longer clear it reliably — browser cookies do. So
:class:`IngestError` distinguishes that specific failure and tells the user how
to fix it, rather than surfacing a raw yt-dlp traceback.
"""

from __future__ import annotations

import json
import logging
import os
import re
import shutil
import subprocess
import sys
import time
from collections.abc import Callable
from pathlib import Path

from .. import paths
from ..config import IngestSettings
from ..db.models import Source, new_id
from ..security import consent
from ..security.egress import Transfer, gateway
from ..security.urlpolicy import UrlRejected, yt_dlp_hardening_args
from . import ffmpeg

log = logging.getLogger(__name__)

#: Container and audio formats we accept for upload.
VIDEO_SUFFIXES = {".mp4", ".mov", ".mkv", ".webm", ".avi", ".m4v"}
AUDIO_SUFFIXES = {".mp3", ".wav", ".m4a", ".aac", ".flac", ".ogg", ".opus"}
ACCEPTED_SUFFIXES = VIDEO_SUFFIXES | AUDIO_SUFFIXES

_YOUTUBE_HOSTS = ("youtube.com", "youtu.be", "www.youtube.com", "m.youtube.com")

#: yt-dlp error fragments that mean "YouTube wants proof you're a human".
_BOT_CHECK_MARKERS = (
    "sign in to confirm",
    "confirm you're not a bot",
    "confirm you are not a bot",
    "this content isn't available",
    "player response",
)

#: A yt-dlp progress line, e.g. ``[download]  42.3% of 393.24MiB ...``.
_DOWNLOAD_PROGRESS = re.compile(r"\[download\]\s+(\d+(?:\.\d+)?)%")

#: Restart a download that yt-dlp gave up on. Partial files are kept between
#: attempts, so each restart resumes rather than downloading from zero.
_DOWNLOAD_ATTEMPTS = 5

#: Seconds between restarts. DNS and CDN hiccups usually clear in this window;
#: yt-dlp's own retries are immediate, so they all fail together without this.
_DOWNLOAD_RETRY_DELAY_S = 20.0


class IngestError(RuntimeError):
    """Ingestion failed in a way worth explaining to the user."""

    def __init__(self, message: str, *, hint: str = "") -> None:
        super().__init__(message)
        self.hint = hint

    def __str__(self) -> str:
        base = super().__str__()
        return f"{base}\n\n{self.hint}" if self.hint else base


def is_youtube_url(url: str) -> bool:
    from urllib.parse import urlparse

    try:
        host = (urlparse(url).hostname or "").lower()
    except ValueError:
        return False
    return host in _YOUTUBE_HOSTS


def slugify(text: str, *, max_length: int = 60) -> str:
    """Turn a title into a filesystem- and URL-safe slug."""
    slug = re.sub(r"[^\w\s-]", "", text, flags=re.UNICODE).strip().lower()
    slug = re.sub(r"[\s_-]+", "-", slug).strip("-")
    return slug[:max_length] or "clip"


# --------------------------------------------------------------------------
# YouTube
# --------------------------------------------------------------------------


def new_youtube_source(url: str) -> Source:
    """Create the pending source row used while YouTube downloads in the background."""
    return Source(
        id=new_id(),
        type="youtube",
        url=url,
        path="",
        title=url,
        has_audio=True,
        has_video=True,
    )


def download_target_dir(source_id: str, settings: IngestSettings) -> Path:
    """Return the folder where a source's complete download is stored.

    ``ingest.download_dir`` points downloads at a chosen folder (for example a
    project's ``materials/input``); every link gets its own subdirectory so two
    videos never overwrite each other. When unset, downloads stay under
    ``<root>/raw/<source_id>``.
    """
    base = Path(settings.download_dir).expanduser() if settings.download_dir else paths.raw_dir()
    return base / source_id


def download_youtube(
    source: Source,
    settings: IngestSettings | None = None,
    *,
    on_progress: Callable[[float], None] | None = None,
) -> Source:
    """Download the source's video/audio into the source's raw directory.

    The complete video is written to ``<root>/raw/<source_id>/`` first and only
    then handed to the rest of the pipeline (audio extraction, transcription,
    highlights, reframe, export). Keeping the full file there means a later
    retry resumes from the video instead of downloading it again.

    The web flow creates a pending source before queueing the job. This function
    fills that source in once yt-dlp finishes, then the existing pipeline
    continues with preparation and transcription.

    Preconditions:
        source is a YouTube source with a URL; the URL points at content the user
        owns or has the rights to process.
    """
    if source.type != "youtube" or not source.url:
        raise IngestError("A YouTube source needs a URL before it can be downloaded.")

    settings = settings or IngestSettings()
    target_dir = download_target_dir(source.id, settings)
    target_dir.mkdir(parents=True, exist_ok=True)

    # The URL is about to be handed to yt-dlp, which will contact it and
    # whatever hosts it redirects to. Classify it first, refuse the addresses
    # that are never legitimate download targets, and record the transfer.
    transfer = Transfer(
        operation=consent.Operation.MEDIA_DOWNLOAD,
        url=source.url,
        data_summary="A page and its media are fetched from the URL you supplied.",
        provider="yt-dlp",
        requires_consent=False,
    )
    try:
        permit = gateway.authorize(transfer)
    except UrlRejected as exc:
        gateway.record(transfer, "failed", detail=f"Refused by the URL policy: {exc}")
        raise IngestError(f"That URL will not be downloaded: {exc}") from exc
    if permit.destination_class == "private":
        gateway.record(transfer, "failed", detail="Private network address refused.")
        raise IngestError(
            "That URL points at a private network address, which AutoClip will not "
            "download from. Use a public address, or run the download yourself and "
            "upload the file."
        )

    command = _download_command(source.url, target_dir, settings)

    log.info("Downloading YouTube source %s with yt-dlp.", source.id)
    output: list[str] = []
    started = time.perf_counter()

    for attempt in range(1, _DOWNLOAD_ATTEMPTS + 1):
        try:
            process = subprocess.Popen(
                command,
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                text=True,
                encoding="utf-8",
                errors="replace",
            )
        except OSError as exc:
            gateway.record(transfer, "failed", detail="yt-dlp could not be started.")
            raise IngestError(
                "Could not start yt-dlp.",
                hint="Install or repair yt-dlp, then retry the job.",
            ) from exc

        assert process.stdout is not None
        for line in process.stdout:
            output.append(line.rstrip())
            if len(output) > 200:
                del output[:50]
            if on_progress and (match := _DOWNLOAD_PROGRESS.search(line)):
                on_progress(min(1.0, float(match.group(1)) / 100.0))

        return_code = process.wait()
        if return_code == 0:
            break

        detail = "\n".join(output[-30:]) or f"yt-dlp exited with code {return_code}."
        if attempt == _DOWNLOAD_ATTEMPTS:
            # Leave the .part file in place so a later retry resumes from here.
            error = _translate_ytdlp_error(RuntimeError(detail), settings)
            gateway.record(transfer, "failed", detail=str(error))
            raise error

        log.warning(
            "yt-dlp attempt %d/%d for source %s failed; resuming in %.0fs.",
            attempt,
            _DOWNLOAD_ATTEMPTS,
            source.id,
            _DOWNLOAD_RETRY_DELAY_S,
        )
        time.sleep(_DOWNLOAD_RETRY_DELAY_S)

    try:
        downloaded = _find_downloaded_file(target_dir)
        if downloaded is None:
            raise IngestError("yt-dlp reported success but produced no media file.")

        info = _probe_and_validate(downloaded)
        metadata = _read_youtube_metadata(target_dir)
    except Exception as exc:
        gateway.record(transfer, "failed", detail=f"{type(exc).__name__}: {exc}")
        shutil.rmtree(target_dir, ignore_errors=True)
        raise

    # The download is the largest thing AutoClip ever sends out, and the
    # transfer log is where the user looks to see what left the machine. It
    # has to be written here, by the caller, because yt-dlp made the request.
    gateway.record(
        transfer,
        "ok",
        duration_ms=int((time.perf_counter() - started) * 1000),
    )

    source.path = str(downloaded)
    source.filename = downloaded.name
    source.title = metadata.get("title") or source.title or downloaded.stem
    source.channel = metadata.get("uploader") or metadata.get("channel")
    source.duration_s = info.duration_s or float(metadata.get("duration") or 0.0)
    source.width = info.width
    source.height = info.height
    source.fps = info.fps
    source.has_audio = info.has_audio
    source.has_video = info.has_video

    if on_progress:
        on_progress(1.0)

    return source


def ingest_youtube(
    url: str,
    settings: IngestSettings | None = None,
    *,
    on_progress: Callable[[float], None] | None = None,
) -> Source:
    """Download a YouTube video and return a completed source record.

    Retained for the synchronous CLI path; the web app creates the pending
    source first and lets the background pipeline call :func:`download_youtube`.
    """
    return download_youtube(
        new_youtube_source(url),
        settings,
        on_progress=on_progress,
    )


def _download_command(url: str, target_dir: Path, settings: IngestSettings) -> list[str]:
    """Build the yt-dlp command line used for one download.

    The format selector comes from ``ingest.ytdlp_format`` rather than being
    hard-coded, so the size of a download is the user's decision. The default
    caps the video at 1080p: the best available stream of a long video is
    routinely several gigabytes larger than the pipeline needs, and a 1440p60
    stream of a four-hour recording is a multi-gigabyte download of material
    that is thrown away as soon as it is cut into clips.
    """
    command = [
        *_ytdlp_command(),
        "--newline",
        "--no-playlist",
        "--write-info-json",
        # Keep trying through transient CDN/DNS failures. The default retry
        # delay is zero, which makes all retries fail instantly during a short
        # resolver outage, so space them out.
        "--retries",
        "50",
        "--fragment-retries",
        "50",
        "--retry-sleep",
        "5",
        "--socket-timeout",
        "30",
        "--format",
        settings.ytdlp_format,
        "--output",
        str(target_dir / "source.%(ext)s"),
        *yt_dlp_hardening_args(),
    ]
    if settings.cookies_from_browser:
        command += ["--cookies-from-browser", settings.cookies_from_browser]
    if settings.prefer_youtube_captions:
        command += [
            "--write-auto-subs",
            "--sub-langs",
            "en.*",
            "--sub-format",
            "json3",
        ]
    command.append(url)
    return command


def _ytdlp_command() -> list[str]:
    """Find yt-dlp, preferring the executable installed beside this Python."""
    executable = shutil.which("yt-dlp")
    if executable:
        return [executable]

    script_name = "yt-dlp.exe" if os.name == "nt" else "yt-dlp"
    beside_python = Path(sys.executable).with_name(script_name)
    if beside_python.is_file():
        return [str(beside_python)]

    return [sys.executable, "-m", "yt_dlp"]


def _read_youtube_metadata(directory: Path) -> dict:
    """Load the metadata sidecar yt-dlp writes beside the downloaded media."""
    candidates = sorted(directory.glob("*.info.json"), key=lambda path: path.stat().st_size)
    for path in reversed(candidates):
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            log.warning("Could not read yt-dlp metadata from %s.", path)
            continue
        if isinstance(data, dict):
            return data
    return {}


def _translate_ytdlp_error(exc: Exception, settings: IngestSettings) -> IngestError:
    """Turn a yt-dlp failure into something the user can act on."""
    message = str(exc).lower()

    if any(marker in message for marker in _BOT_CHECK_MARKERS):
        if settings.cookies_from_browser:
            hint = (
                f"Cookies are already being read from {settings.cookies_from_browser}, but "
                "YouTube still refused. Make sure you are signed in to YouTube in that "
                "browser and that the browser is fully closed — it locks its cookie "
                "database while running."
            )
        else:
            hint = (
                "YouTube is asking for proof you're not a bot. Set a browser to pull "
                "cookies from — in Settings, or via config.json's "
                '`ingest.cookies_from_browser` (e.g. "chrome", "firefox", "edge"). '
                "You must be signed in to YouTube in that browser, and it must be closed "
                "while AutoClip downloads."
            )
        return IngestError("YouTube blocked this download with a bot check.", hint=hint)

    if "private video" in message or "members-only" in message:
        return IngestError(
            "This video is private or members-only.",
            hint="AutoClip only downloads content you can access and have the rights to use.",
        )
    if "unavailable" in message or "removed" in message:
        return IngestError("This video is unavailable or has been removed.")
    if "drm" in message:
        return IngestError(
            "This content is DRM-protected.",
            hint="AutoClip does not and will not circumvent DRM.",
        )

    return IngestError(
        "yt-dlp could not download this video.",
        hint=(
            "YouTube changes frequently and yt-dlp is updated often. Try "
            "`autoclip update-ytdlp` to pull the latest version.\n\n"
            f"Original error: {exc}"
        ),
    )


def _find_downloaded_file(directory: Path) -> Path | None:
    """Return the largest media file in a directory, ignoring sidecars."""
    candidates = [
        p for p in directory.iterdir() if p.is_file() and p.suffix.lower() in ACCEPTED_SUFFIXES
    ]
    if not candidates:
        return None
    return max(candidates, key=lambda p: p.stat().st_size)


# --------------------------------------------------------------------------
# Upload
# --------------------------------------------------------------------------


def ingest_file(path: Path, *, move: bool = False, title: str | None = None) -> Source:
    """Register a local file as a source, copying it into AutoClip's media store.

    Copying rather than referencing in place means a job stays reproducible even
    if the user moves or deletes the original.

    Preconditions:
        path exists and is a readable media file.
    """
    path = Path(path)
    if not path.exists():
        raise IngestError(f"{path} does not exist.")
    if not path.is_file():
        raise IngestError(f"{path} is not a file.")

    suffix = path.suffix.lower()
    if suffix not in ACCEPTED_SUFFIXES:
        accepted = ", ".join(sorted(ACCEPTED_SUFFIXES))
        raise IngestError(
            f"{suffix or 'This file'} is not a supported format.",
            hint=f"Accepted formats: {accepted}",
        )

    source_id = new_id()
    target_dir = paths.source_media_dir(source_id)
    target_dir.mkdir(parents=True, exist_ok=True)
    target = target_dir / f"source{suffix}"

    try:
        if move:
            shutil.move(str(path), target)
        else:
            shutil.copy2(path, target)
    except OSError as exc:
        shutil.rmtree(target_dir, ignore_errors=True)
        raise IngestError(f"Could not store {path.name}: {exc}") from exc

    try:
        info = _probe_and_validate(target)
    except Exception:
        shutil.rmtree(target_dir, ignore_errors=True)
        raise

    return Source(
        id=source_id,
        type="upload",
        path=str(target),
        filename=path.name,
        title=title or info.title or path.stem,
        duration_s=info.duration_s,
        width=info.width,
        height=info.height,
        fps=info.fps,
        has_audio=info.has_audio,
        has_video=info.has_video,
    )


def _probe_and_validate(path: Path) -> ffmpeg.MediaInfo:
    """Probe a media file and reject anything the pipeline can't process."""
    try:
        info = ffmpeg.probe(path)
    except ffmpeg.FFmpegError as exc:
        raise IngestError(f"{path.name} could not be read as media.", hint=str(exc)) from exc

    if not info.has_audio:
        raise IngestError(
            f"{path.name} has no audio track.",
            hint=(
                "AutoClip finds clips by transcribing speech, so a file with no audio "
                "has nothing to work from."
            ),
        )
    if info.duration_s <= 0:
        raise IngestError(
            f"{path.name} reports zero duration.",
            hint="The file may be corrupt or still being written.",
        )

    return info
