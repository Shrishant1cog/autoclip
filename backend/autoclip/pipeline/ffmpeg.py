"""ffmpeg and ffprobe wrappers.

Two things here are easy to get wrong and expensive to debug, so they're
centralised:

**Filtergraph path escaping.** ``ass=filename=C:\\x\\y.ass`` is not valid — the
drive-letter colon is read as an option separator, and backslashes as escapes.
Every path that reaches a filtergraph must go through
:func:`escape_filter_path`. This is the single most common Windows-only failure
in ffmpeg-based tools.

**Progress reporting.** ``-progress pipe:1`` emits machine-readable key=value
lines; parsing those beats scraping the human-readable stderr banner, which
changes between ffmpeg versions.
"""

from __future__ import annotations

import json
import logging
import os
import re
import shutil
import subprocess
import time
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from pathlib import Path

from .. import resources
from ..security.urlpolicy import ffmpeg_protocol_whitelist

log = logging.getLogger(__name__)

ProgressCallback = Callable[[float], None]

#: Windows refuses a command line longer than this. The limit belongs to
#: CreateProcess, not to ffmpeg, and the error it raises — "the filename or
#: extension is too long" — names the wrong thing: it is usually the filter
#: graph that is too long.
WINDOWS_COMMAND_LINE_LIMIT = 32_767


class FFmpegError(RuntimeError):
    """An ffmpeg or ffprobe invocation failed."""

    def __init__(self, message: str, *, command: Sequence[str], stderr: str = "") -> None:
        super().__init__(message)
        self.command = list(command)
        self.stderr = stderr

    def __str__(self) -> str:
        base = super().__str__()
        tail = self.stderr.strip().splitlines()[-12:]
        if tail:
            return base + "\n" + "\n".join(tail)
        return base


@dataclass
class StreamInfo:
    codec: str
    #: Audio only.
    sample_rate: int | None = None
    channels: int | None = None


@dataclass
class MediaInfo:
    path: Path
    duration_s: float
    has_video: bool
    has_audio: bool
    width: int | None = None
    height: int | None = None
    fps: float | None = None
    video_codec: str | None = None
    audio_codec: str | None = None
    title: str | None = None

    @property
    def aspect_ratio(self) -> float | None:
        if not self.width or not self.height:
            return None
        return self.width / self.height

    @property
    def is_vertical(self) -> bool:
        ar = self.aspect_ratio
        return ar is not None and ar < 1.0


def ffmpeg_path() -> str:
    exe = shutil.which("ffmpeg")
    if not exe:
        raise FFmpegError(
            "ffmpeg was not found on PATH. Run `autoclip doctor` for install instructions.",
            command=["ffmpeg"],
        )
    return exe


def ffprobe_path() -> str:
    exe = shutil.which("ffprobe")
    if not exe:
        raise FFmpegError(
            "ffprobe was not found on PATH. Run `autoclip doctor` for install instructions.",
            command=["ffprobe"],
        )
    return exe


# --------------------------------------------------------------------------
# Filtergraph escaping
# --------------------------------------------------------------------------

#: Characters that terminate or restructure a filtergraph if left unescaped.
_FILTER_SPECIALS = "\\'[],;:"


def escape_filter_path(path: Path | str) -> str:
    r"""Escape a filesystem path for use inside an ffmpeg filtergraph option.

    Filter option values pass through *two* unescaping rounds — once when the
    filtergraph is split into filters and options, once when a filter parses its
    own arguments — so each special character needs two backslashes. A single
    backslash produces the classic ``No option name near '/Users/...'`` error,
    because the drive-letter colon survives the first round and is then read as
    an option separator.

    Prefer :func:`relative_filter_workspace` for paths the user controls.
    Quoting and escaping interact badly around apostrophes, and a relative name
    has no special characters to escape in the first place.

    Preconditions:
        path is a filesystem path, not an already-escaped filtergraph fragment.
    """
    text = str(path).replace("\\", "/")
    out: list[str] = []
    for char in text:
        if char in _FILTER_SPECIALS:
            out.append("\\\\" + char)
        else:
            out.append(char)
    return "".join(out)


def escape_filter_value(value: str) -> str:
    """Escape a non-path filter option value (font names, style overrides)."""
    out: list[str] = []
    for char in value:
        if char in _FILTER_SPECIALS:
            out.append("\\" + char)
        else:
            out.append(char)
    return "".join(out)


# --------------------------------------------------------------------------
# Probing
# --------------------------------------------------------------------------


def run_captured(command: Sequence[str]) -> subprocess.CompletedProcess[str]:
    """Run a command with the ffmpeg gate held, capturing its output.

    Every external media process goes through here so the process-wide
    concurrency limit actually applies to ffprobe as well as ffmpeg. Without
    it, a validation probe can start a third decoder while two encodes are
    already running.
    """
    with resources.ffmpeg_gate.slot():
        return subprocess.run(
            command,
            capture_output=True,
            text=True,
            check=False,
            encoding="utf-8",
            errors="replace",
        )


def protocol_args() -> list[str]:
    """The FFmpeg options that restrict what it may open.

    FFmpeg's default protocol set includes ``http``, ``https``, ``tcp``,
    ``udp``, ``rtmp`` and friends. AutoClip only ever reads local files and
    pipes, so those are removed: a playlist or manifest that reached FFmpeg
    through any future path cannot make it fetch a remote resource.
    """
    return ["-protocol_whitelist", ffmpeg_protocol_whitelist()]


def probe(path: Path) -> MediaInfo:
    """Inspect a media file with ffprobe.

    Raises :class:`FFmpegError` if the file is unreadable or not media.
    """
    command = [
        ffprobe_path(),
        "-v",
        "error",
        *protocol_args(),
        "-print_format",
        "json",
        "-show_format",
        "-show_streams",
        str(path),
    ]
    proc = run_captured(command)
    if proc.returncode != 0:
        raise FFmpegError(f"Could not read {path.name}.", command=command, stderr=proc.stderr or "")

    try:
        data = json.loads(proc.stdout)
    except json.JSONDecodeError as exc:
        raise FFmpegError(
            f"ffprobe returned unreadable output for {path.name}.", command=command
        ) from exc

    streams = data.get("streams", [])
    fmt = data.get("format", {})

    video = next((s for s in streams if s.get("codec_type") == "video"), None)
    audio = next((s for s in streams if s.get("codec_type") == "audio"), None)

    # Cover art in an audio file shows up as a video stream; a still image is
    # not something we can reframe, so don't count it as video.
    if video is not None and video.get("disposition", {}).get("attached_pic"):
        video = None

    info = MediaInfo(
        path=path,
        duration_s=float(fmt.get("duration") or 0.0),
        has_video=video is not None,
        has_audio=audio is not None,
        title=(fmt.get("tags") or {}).get("title"),
    )

    if video is not None:
        info.width = _as_int(video.get("width"))
        info.height = _as_int(video.get("height"))
        info.fps = _parse_fps(video.get("avg_frame_rate") or video.get("r_frame_rate"))
        info.video_codec = video.get("codec_name")
    if audio is not None:
        info.audio_codec = audio.get("codec_name")

    return info


def volumedetect(path: Path) -> float | None:
    """Peak audio level in dBFS, or ``None`` when ffmpeg reports none.

    Used by clip validation to catch a render whose audio silently dropped out.
    Raises :class:`FFmpegError` only if ffmpeg itself cannot run.
    """
    command = [
        ffmpeg_path(),
        "-hide_banner",
        "-nostats",
        *protocol_args(),
        "-i",
        str(path),
        "-map",
        "0:a:0",
        "-af",
        "volumedetect",
        "-f",
        "null",
        "-",
    ]
    proc = run_captured(command)
    stderr = proc.stderr or ""
    if proc.returncode != 0 and "does not contain any stream" in stderr:
        raise FFmpegError(
            f"{path.name} has no audio stream to measure.", command=command, stderr=stderr
        )
    if proc.returncode != 0:
        raise FFmpegError(
            f"Could not measure audio in {path.name}.", command=command, stderr=stderr
        )

    match = re.search(r"max_volume:\s*(-?(?:inf|\d+(?:\.\d+)?))\s*dB", stderr)
    if not match:
        return None
    value = match.group(1)
    if value in {"-inf", "-Infinity", "inf"}:
        return float("-inf")
    return float(value)


def _as_int(value: object) -> int | None:
    try:
        return int(value)  # type: ignore[arg-type]
    except (TypeError, ValueError):
        return None


def clipping_ratio(path: Path) -> float | None:
    """The fraction of audio samples that reached full scale.

    Clipping is a real, measurable fault: a sample at full scale has
    already been cut off, so the sound is distorted. ``None`` means the
    measurement could not be made — an unmeasurable file is not the same
    as a clean one, and the two are never conflated.

    The count comes from ffmpeg's ``astats`` filter. Older ffmpeg builds
    print ``Number of clipped samples`` directly; newer ones do not, so
    the same answer is worked out from the peak level and the number of
    samples sitting at that peak: when the peak is at full scale, the
    samples at the peak *are* the clipped ones.
    """
    command = [
        ffmpeg_path(),
        "-hide_banner",
        "-nostats",
        *protocol_args(),
        "-i",
        str(path),
        "-map",
        "0:a:0",
        "-af",
        "astats=metadata=0:reset=0",
        "-f",
        "null",
        "-",
    ]
    try:
        proc = run_captured(command)
    except FFmpegError:
        return None

    stderr = proc.stderr or ""
    if "does not contain any stream" in stderr:
        return None

    total = _last_stat(stderr, "Number of samples")
    if not total or total <= 0:
        return None

    # Older ffmpeg prints the clipped count directly.
    clipped = _last_stat(stderr, "Number of clipped samples")
    if clipped is not None:
        return round(clipped / total, 6)

    channels = _channel_peaks(stderr)
    if not channels:
        return None

    # Each channel holds the same number of samples, so the overall
    # total splits evenly between them.
    per_channel = total / len(channels)
    if per_channel <= 0:
        return None

    worst = 0.0
    for peak_db, peak_count in channels:
        # Anything within 0.05 dB of full scale has been clipped.
        if peak_db is None or peak_count is None:
            continue
        if peak_db < -0.05:
            continue
        worst = max(worst, peak_count / per_channel)
    return round(worst, 6)


def _channel_peaks(stderr: str) -> list[tuple[float | None, float | None]]:
    """Each audio channel's peak level and the count of samples at it.

    ffmpeg prints one block per channel and then an "Overall" block. Only
    the per-channel blocks are wanted here: the overall peak is the
    loudest channel's, and the overall count adds up channels that peak
    at different levels, so combining them would overstate the clipping.
    """
    blocks: list[tuple[float | None, float | None]] = []
    current: dict[str, float] | None = None

    for line in stderr.splitlines():
        if "Channel:" in line:
            if current is not None:
                blocks.append((current.get("peak"), current.get("count")))
            current = {}
            continue
        if current is None:
            continue
        if "Overall" in line:
            blocks.append((current.get("peak"), current.get("count")))
            current = None
            continue
        if "Peak level dB:" in line:
            value = _stat_value(line)
            if value is not None:
                current["peak"] = value
        elif "Abs Peak count:" in line:
            value = _stat_value(line)
            if value is not None:
                current["count"] = value

    if current is not None:
        blocks.append((current.get("peak"), current.get("count")))

    return blocks


def _stat_value(line: str) -> float | None:
    """The number after the colon on an ffmpeg statistics line."""
    match = re.search(r":\s*(-?(?:inf|\d+(?:\.\d+)?))", line)
    if not match:
        return None
    raw = match.group(1)
    if raw in {"-inf", "inf", "-Infinity", "Infinity"}:
        return None
    try:
        return float(raw)
    except ValueError:
        return None


def _last_stat(stderr: str, label: str) -> float | None:
    """The last value ffmpeg's astats printed for one label."""
    values: list[float] = []
    for line in stderr.splitlines():
        if label not in line:
            continue
        value = _stat_value(line)
        if value is not None:
            values.append(value)
    return values[-1] if values else None


def black_intervals(path: Path, *, min_duration_s: float = 0.2) -> list[tuple[float, float]]:
    """The black stretches in a file, as ``(start_s, end_s)`` pairs.

    Measured with ffmpeg's ``blackdetect`` filter. A clip that opens on
    a black frame is a real fault; a clip that fades to black at the very
    end usually is not, so the caller decides what to do with the list.
    """
    command = [
        ffmpeg_path(),
        "-hide_banner",
        "-nostats",
        *protocol_args(),
        "-i",
        str(path),
        "-vf",
        f"blackdetect=d={min_duration_s}:pic_th=0.98",
        "-an",
        "-f",
        "null",
        "-",
    ]
    try:
        proc = run_captured(command)
    except FFmpegError:
        return []

    intervals: list[tuple[float, float]] = []
    for line in (proc.stderr or "").splitlines():
        if "black_start" not in line:
            continue
        start = re.search(r"black_start:([0-9.]+)", line)
        end = re.search(r"black_end:([0-9.]+)", line)
        if start is None:
            continue
        intervals.append(
            (
                float(start.group(1)),
                float(end.group(1)) if end is not None else float("inf"),
            )
        )
    return intervals


def frame_durations(path: Path, *, limit: int = 900) -> list[float]:
    """The gaps between consecutive frames, in seconds.

    A constant frame rate produces a constant gap. The spread of these
    gaps is what "frame-rate consistency" means, and it is measured
    rather than assumed from the container's nominal rate.
    """
    command = [
        ffprobe_path(),
        "-v",
        "error",
        *protocol_args(),
        "-select_streams",
        "v:0",
        "-show_entries",
        "frame=pts_time",
        "-read_intervals",
        f"%+{max(1, limit)}",
        "-of",
        "csv=p=0",
        str(path),
    ]
    try:
        proc = run_captured(command)
    except FFmpegError:
        return []

    stamps: list[float] = []
    for line in (proc.stdout or "").splitlines():
        line = line.strip().strip(",")
        if not line or line == "N/A":
            continue
        try:
            stamps.append(float(line))
        except ValueError:
            continue

    stamps.sort()
    return [round(b - a, 6) for a, b in zip(stamps, stamps[1:], strict=False) if b > a]


def _parse_fps(rate: str | None) -> float | None:
    """Convert ffprobe's ``"30000/1001"`` rational frame rate to a float."""
    if not rate:
        return None
    try:
        if "/" in rate:
            num, den = rate.split("/", 1)
            denominator = float(den)
            return float(num) / denominator if denominator else None
        return float(rate)
    except (ValueError, ZeroDivisionError):
        return None


# --------------------------------------------------------------------------
# Running
# --------------------------------------------------------------------------


def relative_filter_workspace(subtitle_path: Path, fonts_dir: Path) -> tuple[Path, str, str]:
    """Stage subtitles and fonts so a filtergraph can reference them by bare name.

    Returns ``(working_directory, subtitle_name, fonts_name)``. Running ffmpeg
    from that directory lets the ``ass`` filter take ``filename=captions.ass``
    and ``fontsdir=fonts`` — names with no colons, separators, quotes, or
    spaces, which removes the whole escaping problem rather than trying to
    out-escape it.

    Paths passed as ordinary argv arguments (inputs, outputs) never need any of
    this; only filtergraph option values do.

    Preconditions:
        subtitle_path exists; fonts_dir exists and holds the bundled fonts.
    """
    import shutil

    workspace = subtitle_path.parent
    staged_subtitles = workspace / "captions.ass"
    if subtitle_path.resolve() != staged_subtitles.resolve():
        shutil.copyfile(subtitle_path, staged_subtitles)

    staged_fonts = workspace / "fonts"
    if fonts_dir.exists():
        staged_fonts.mkdir(exist_ok=True)
        for font in fonts_dir.iterdir():
            if font.is_file() and font.suffix.lower() in (".ttf", ".otf", ".ttc"):
                target = staged_fonts / font.name
                if not target.exists():
                    shutil.copyfile(font, target)

    return workspace, staged_subtitles.name, staged_fonts.name


def command_line_length(command: Sequence[str]) -> int:
    """The length of a command line, as the operating system counts it.

    Every argument is followed by a space, which is what CreateProcess sees
    when it refuses a command that is too long.
    """
    return sum(len(str(argument)) + 1 for argument in command)


def command_line_limit() -> int | None:
    """The longest command line this platform accepts, or None if it has no limit.

    Windows is the only platform with one worth knowing about: CreateProcess
    refuses anything longer than :data:`WINDOWS_COMMAND_LINE_LIMIT`
    characters. POSIX systems take the argument vector as it is.
    """
    return WINDOWS_COMMAND_LINE_LIMIT if os.name == "nt" else None


def check_command_line_length(command: Sequence[str], *, limit: int | None = None) -> None:
    """Refuse a command line the platform cannot run, and say why.

    A filtergraph can grow without bound — one more crop segment, one more
    stretch of speech — and Windows will not run a command line longer than
    :data:`WINDOWS_COMMAND_LINE_LIMIT` characters. The operating system's own
    error says "the filename or extension is too long", which points at the
    wrong thing entirely, so the check happens here where the message can
    name the real cause.

    ``limit`` overrides the platform's limit; it is there so the check can be
    exercised on every platform.
    """
    if limit is None:
        limit = command_line_limit()
    if limit is None:
        return

    length = command_line_length(command)
    if length <= limit:
        return

    platform = "Windows" if os.name == "nt" else "this platform"
    raise FFmpegError(
        f"The ffmpeg command is too long for {platform}: {length:,} characters, "
        f"and the limit is {limit:,}. The clip has more segments or stretches "
        "of speech than one command line can carry.",
        command=command,
    )


def run(
    args: Sequence[str],
    *,
    total_duration_s: float | None = None,
    on_progress: ProgressCallback | None = None,
    cancelled: Callable[[], bool] | None = None,
    cwd: Path | None = None,
    threads: int = 0,
    usage: resources.Usage | None = None,
) -> float:
    """Run ffmpeg, optionally reporting progress as a 0..1 fraction.

    ``args`` excludes the executable name and the flags this function supplies
    (``-hide_banner``, ``-y``, ``-nostdin``, and the progress plumbing).

    ``threads`` caps the decoder and filter threads. ffmpeg otherwise spawns
    one worker per core, which oversubscribes the machine as soon as a second
    ffmpeg is running.

    Returns the wall-clock seconds the process took. ``usage``, when given,
    accumulates the same numbers so a job can report what it actually spent.

    Preconditions:
        total_duration_s is the expected output duration when on_progress is set;
        without it progress cannot be computed and the callback is never invoked.
    """
    command = [
        ffmpeg_path(),
        "-hide_banner",
        "-nostdin",
        "-y",
        "-loglevel",
        "error",
        *protocol_args(),
    ]
    if threads and threads > 0:
        # Placed before -i, so these apply to the decoder and the filtergraph.
        command += ["-threads", str(threads), "-filter_threads", str(threads)]
    if on_progress and total_duration_s:
        command += ["-progress", "pipe:1", "-nostats"]
    command += list(args)

    log.debug("ffmpeg %s", " ".join(command[1:]))

    check_command_line_length(command)

    started = time.monotonic()
    try:
        with resources.ffmpeg_gate.slot():
            proc = subprocess.Popen(
                command,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
                encoding="utf-8",
                errors="replace",
                cwd=str(cwd) if cwd else None,
            )

            try:
                if on_progress and total_duration_s and proc.stdout is not None:
                    _pump_progress(proc, total_duration_s, on_progress, cancelled)
                elif cancelled is not None:
                    _wait_cancellable(proc, cancelled)

                stdout, stderr = proc.communicate()
            except BaseException:
                proc.kill()
                proc.wait()
                raise

        if proc.returncode != 0:
            raise FFmpegError(
                f"ffmpeg exited with code {proc.returncode}.",
                command=command,
                stderr=stderr or "",
            )

        if on_progress:
            on_progress(1.0)
    finally:
        elapsed = time.monotonic() - started
        if usage is not None:
            usage.ffmpeg_runs += 1
            usage.ffmpeg_seconds += elapsed

    return elapsed


class Cancelled(RuntimeError):
    """Raised when a cancellation predicate returns True mid-render."""


def _pump_progress(
    proc: subprocess.Popen[str],
    total_duration_s: float,
    on_progress: ProgressCallback,
    cancelled: Callable[[], bool] | None,
) -> None:
    assert proc.stdout is not None
    for line in proc.stdout:
        if cancelled is not None and cancelled():
            proc.kill()
            raise Cancelled("Render cancelled.")

        key, _, value = line.strip().partition("=")
        # out_time_us is microseconds; older builds emit out_time_ms which is
        # *also* microseconds despite the name. Handle both identically.
        if key in ("out_time_us", "out_time_ms"):
            try:
                elapsed = int(value) / 1_000_000
            except ValueError:
                continue
            on_progress(max(0.0, min(1.0, elapsed / total_duration_s)))
        elif key == "progress" and value == "end":
            on_progress(1.0)


def _wait_cancellable(proc: subprocess.Popen[str], cancelled: Callable[[], bool]) -> None:
    while True:
        try:
            proc.wait(timeout=0.5)
            return
        except subprocess.TimeoutExpired:
            if cancelled():
                proc.kill()
                raise Cancelled("Render cancelled.") from None
