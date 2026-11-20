"""Checking a rendered clip against Instagram's documented limits.

Meta documents the Reel specifications precisely (see
``docs/INSTAGRAM-API-EVALUATION.md`` §9.1.8), and this module measures the
file against every one of them before a byte is sent.

The point of measuring rather than assuming is that a refused publish
costs the owner a round trip and a guess. *"The file is 41.2 Mbps; the
limit is 25 Mbps"* is an answer. *"Instagram rejected your upload"* is
not.

Two checks deserve a note:

* **The moov atom at the front.** Meta requires it, and ``ffprobe`` does
  not report it. The MP4 box structure is walked directly instead — see
  :func:`scan_boxes`.
* **The video bitrate.** ``ffprobe`` does not always report a per-stream
  bitrate. When it does not, the figure is derived from the file size and
  the duration, and the report says which number it used, so nobody has to
  guess where it came from.
"""

from __future__ import annotations

import json
import logging
import struct
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from ..pipeline.ffmpeg import ffprobe_path, protocol_args, run_captured

log = logging.getLogger(__name__)

#: Meta's documented Reel specifications. Every one of these is checked.
REEL_LIMITS: dict[str, Any] = {
    "container": "MOV or MP4 (MPEG-4 Part 14)",
    "moov_at_front": True,
    "audio_codec": "AAC",
    "audio_sample_rate_hz": 48_000,
    "audio_channels": 2,
    "video_codec": ("h264", "hevc"),
    "fps_min": 23.0,
    "fps_max": 60.0,
    "max_width": 1920,
    "aspect_min": 0.01,
    "aspect_max": 10.0,
    "video_bitrate_bps": 25_000_000,
    "audio_bitrate_bps": 128_000,
    "duration_min_s": 3.0,
    "duration_max_s": 900.0,
    "max_bytes": 300 * 1024 * 1024,
}

#: Meta's documented caption limits.
CAPTION_MAX_CHARS = 2200
CAPTION_MAX_HASHTAGS = 30
CAPTION_MAX_TAGS = 20

#: Boxes whose contents are themselves boxes. The walk recurses into these
#: and nowhere else: ``mdat`` holds the media payload, and treating its
#: bytes as box headers would find nonsense.
_CONTAINER_BOXES = frozenset(
    {
        "moov",
        "trak",
        "edts",
        "mdia",
        "minf",
        "stbl",
        "udta",
        "meta",
        "moof",
        "traf",
        "mvex",
        "dinf",
        "ipro",
        "sinf",
        "schi",
    }
)


class MediaInvalid(RuntimeError):
    """The file does not meet Instagram's documented requirements."""


@dataclass(frozen=True)
class Check:
    """One measured requirement, and whether the file met it."""

    name: str
    value: str
    requirement: str
    ok: bool
    #: True when the value could not be measured, so the requirement was
    #: neither met nor broken. A missing measurement is never a pass.
    measured: bool = True

    def to_dict(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "value": self.value,
            "requirement": self.requirement,
            "ok": self.ok,
            "measured": self.measured,
        }


@dataclass
class MediaReport:
    """What was measured about a file, and what it means for Instagram."""

    path: Path
    ok: bool = True
    problems: list[str] = field(default_factory=list)
    checks: list[Check] = field(default_factory=list)
    #: Requirements that could not be checked, named rather than hidden.
    not_checked: list[str] = field(default_factory=list)
    facts: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "ok": self.ok,
            "problems": list(self.problems),
            "checks": [c.to_dict() for c in self.checks],
            "not_checked": list(self.not_checked),
            "facts": dict(self.facts),
        }

    def summary(self) -> str:
        """One sentence the owner can act on."""
        if self.ok:
            return "The file meets Instagram's documented Reel requirements."
        return "; ".join(self.problems)


# --------------------------------------------------------------------------
# The MP4 box structure
# --------------------------------------------------------------------------


def scan_boxes(path: Path, *, max_depth: int = 8) -> dict[str, Any]:
    """Walk the MP4 box structure of a file.

    Returns the box types found and whether the ``moov`` atom comes before
    the ``mdat`` atom. Meta requires the ``moov`` atom at the front — that
    is what lets a player start the video without reading the whole file
    first — and no other tool AutoClip has reports it.

    The walk never descends into ``mdat``: its contents are the media
    payload, and reading those bytes as box headers would find boxes that
    are not there.
    """
    found: list[str] = []
    order: list[str] = []
    moov_at_front: bool | None = None

    try:
        size = path.stat().st_size
        with path.open("rb") as handle:
            _walk(handle, 0, size, found, order, moov_at_front, 0, max_depth)
    except OSError:
        return {"boxes": [], "order": [], "moov_at_front": None, "has_edit_list": None}

    has_edit_list = "elst" in found
    if "moov" in order and "mdat" in order:
        moov_at_front = order.index("moov") < order.index("mdat")
    elif "moov" in order:
        moov_at_front = True
    else:
        moov_at_front = None

    return {
        "boxes": sorted(set(found)),
        "order": order,
        "moov_at_front": moov_at_front,
        "has_edit_list": has_edit_list,
    }


def _walk(
    handle: Any,
    start: int,
    end: int,
    found: list[str],
    order: list[str],
    moov_at_front: bool | None,
    depth: int,
    max_depth: int,
) -> None:
    """Read the boxes between ``start`` and ``end``, recursively."""
    offset = start
    while offset + 8 <= end:
        handle.seek(offset)
        header = handle.read(8)
        if len(header) < 8:
            return
        size32, box_type = struct.unpack(">I4s", header)
        box_type = box_type.decode("latin-1")
        header_len = 8
        if size32 == 1:
            extra = handle.read(8)
            if len(extra) < 8:
                return
            size = struct.unpack(">Q", extra)[0]
            header_len = 16
        elif size32 == 0:
            size = end - offset
        else:
            size = size32

        if size < header_len:
            return
        box_end = min(offset + size, end)

        found.append(box_type)
        order.append(box_type)

        if box_type in _CONTAINER_BOXES and depth < max_depth:
            child_start = offset + header_len
            if box_type == "meta":
                # ``meta`` is a full box: four bytes of version and flags
                # come before its children.
                child_start += 4
            _walk(handle, child_start, box_end, found, order, moov_at_front, depth + 1, max_depth)

        offset += size


# --------------------------------------------------------------------------
# Probing
# --------------------------------------------------------------------------


def probe_details(path: Path) -> dict[str, Any]:
    """Measure everything Instagram's specifications mention.

    One ``ffprobe`` call, parsed into the facts the checks need.
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
        raise MediaInvalid(f"Could not read {path.name}. It may not be a media file.")
    try:
        data = json.loads(proc.stdout)
    except json.JSONDecodeError as exc:
        raise MediaInvalid(f"ffprobe returned unreadable output for {path.name}.") from exc

    streams = data.get("streams") or []
    fmt = data.get("format") or {}
    video = next((s for s in streams if s.get("codec_type") == "video"), None)
    audio = next((s for s in streams if s.get("codec_type") == "audio"), None)

    return {
        "format_name": str(fmt.get("format_name") or ""),
        "duration_s": _as_float(fmt.get("duration")),
        "file_bitrate_bps": _as_float(fmt.get("bit_rate")),
        "size_bytes": int(path.stat().st_size),
        "video_codec": str((video or {}).get("codec_name") or ""),
        "width": _as_int((video or {}).get("width")),
        "height": _as_int((video or {}).get("height")),
        "fps": _as_float((video or {}).get("avg_frame_rate"))
        or _as_float((video or {}).get("r_frame_rate")),
        "video_bitrate_bps": _as_float((video or {}).get("bit_rate")),
        "pix_fmt": str((video or {}).get("pix_fmt") or ""),
        "audio_codec": str((audio or {}).get("codec_name") or ""),
        "audio_sample_rate_hz": _as_int((audio or {}).get("sample_rate")),
        "audio_channels": _as_int((audio or {}).get("channels")),
        "audio_bitrate_bps": _as_float((audio or {}).get("bit_rate")),
        "has_video": video is not None,
        "has_audio": audio is not None,
    }


def _as_float(value: object) -> float | None:
    if value is None:
        return None
    if isinstance(value, (int, float)):
        return float(value)
    text = str(value)
    if "/" in text:
        num, _, den = text.partition("/")
        try:
            denominator = float(den)
            return float(num) / denominator if denominator else None
        except ValueError:
            return None
    try:
        return float(text)
    except ValueError:
        return None


def _as_int(value: object) -> int | None:
    """Read an integer out of a JSON value, or ``None`` when it is not one."""
    if isinstance(value, bool):
        return None
    if isinstance(value, int):
        return value
    if isinstance(value, float):
        return int(value)
    if isinstance(value, str):
        try:
            return int(value.strip())
        except ValueError:
            return None
    return None


# --------------------------------------------------------------------------
# The checks
# --------------------------------------------------------------------------


def validate_reel(path: Path) -> MediaReport:
    """Measure a file against Instagram's documented Reel requirements.

    Raises :class:`MediaInvalid` when the file is unreadable. A file that
    simply does not qualify returns a report whose ``ok`` is false — the
    caller decides what to do with that, and the report says exactly what
    failed.
    """
    if not path.is_file():
        raise MediaInvalid(f"The exported file is missing: {path}")

    details = probe_details(path)
    boxes = scan_boxes(path)
    report = MediaReport(path=path)
    limits = REEL_LIMITS

    # -- container ---------------------------------------------------------
    format_names = {n.strip().lower() for n in details["format_name"].split(",") if n.strip()}
    is_mp4_family = bool(format_names & {"mov", "mp4", "m4a", "3gp", "3g2", "mj2"})
    report.checks.append(
        Check(
            name="container",
            value=details["format_name"] or "unknown",
            requirement=str(limits["container"]),
            ok=is_mp4_family,
        )
    )
    if not is_mp4_family:
        report.problems.append(
            f"The file is {details['format_name'] or 'not a recognised media container'}; "
            f"Instagram needs {limits['container']}."
        )

    # -- the moov atom at the front ----------------------------------------
    moov_at_front = boxes.get("moov_at_front")
    report.checks.append(
        Check(
            name="moov_at_front",
            value=("yes" if moov_at_front else "no") if moov_at_front is not None else "not found",
            requirement="the moov atom is at the front of the file",
            ok=bool(moov_at_front),
            measured=moov_at_front is not None,
        )
    )
    if moov_at_front is False:
        report.problems.append(
            "The file's moov atom is not at the front. Instagram needs it there; "
            "re-encode with the faststart flag."
        )

    # Edit lists are a documented no. The walk finds them if they are there.
    if boxes.get("has_edit_list"):
        report.problems.append(
            "The file contains an edit list. Instagram requires a file with no edit lists."
        )
    report.checks.append(
        Check(
            name="edit_list",
            value="present" if boxes.get("has_edit_list") else "none",
            requirement="no edit lists",
            ok=not boxes.get("has_edit_list"),
            measured=boxes.get("has_edit_list") is not None,
        )
    )

    # -- video codec -------------------------------------------------------
    video_codec = details["video_codec"].lower()
    report.checks.append(
        Check(
            name="video_codec",
            value=video_codec or "none",
            requirement="HEVC or H264",
            ok=video_codec in limits["video_codec"],
            measured=bool(video_codec),
        )
    )
    if video_codec and video_codec not in limits["video_codec"]:
        report.problems.append(f"The video codec is {video_codec}; Instagram needs H264 or HEVC.")

    # -- frame rate --------------------------------------------------------
    fps = details["fps"]
    if fps is None:
        report.checks.append(
            Check(
                name="frame_rate",
                value="not reported",
                requirement=f"{limits['fps_min']:.0f}-{limits['fps_max']:.0f} FPS",
                ok=True,
                measured=False,
            )
        )
        report.not_checked.append("The frame rate could not be measured.")
    else:
        fps_ok = limits["fps_min"] <= fps <= limits["fps_max"]
        report.checks.append(
            Check(
                name="frame_rate",
                value=f"{fps:.2f} FPS",
                requirement=f"{limits['fps_min']:.0f}-{limits['fps_max']:.0f} FPS",
                ok=fps_ok,
            )
        )
        if not fps_ok:
            report.problems.append(
                f"The frame rate is {fps:.2f} FPS; Instagram needs between "
                f"{limits['fps_min']:.0f} and {limits['fps_max']:.0f}."
            )

    # -- picture size ------------------------------------------------------
    width = details["width"]
    height = details["height"]
    if width is None or height is None:
        report.checks.append(
            Check(
                name="width",
                value="not reported",
                requirement=f"{limits['max_width']} columns maximum",
                ok=True,
                measured=False,
            )
        )
        report.not_checked.append("The picture size could not be measured.")
    else:
        width_ok = width <= limits["max_width"]
        report.checks.append(
            Check(
                name="width",
                value=f"{width}x{height}",
                requirement=f"{limits['max_width']} columns maximum",
                ok=width_ok,
            )
        )
        if not width_ok:
            report.problems.append(
                f"The video is {width} pixels wide; Instagram allows {limits['max_width']}."
            )

        aspect = width / height if height else 0.0
        aspect_ok = limits["aspect_min"] <= aspect <= limits["aspect_max"]
        report.checks.append(
            Check(
                name="aspect_ratio",
                value=f"{aspect:.4f}:1",
                requirement=f"{limits['aspect_min']}:1 to {limits['aspect_max']}:1",
                ok=aspect_ok,
            )
        )
        if not aspect_ok:
            report.problems.append(
                f"The aspect ratio is {aspect:.4f}:1; Instagram allows "
                f"{limits['aspect_min']}:1 to {limits['aspect_max']}:1."
            )

    # -- duration ----------------------------------------------------------
    duration = details["duration_s"]
    if duration is None:
        report.checks.append(
            Check(
                name="duration",
                value="not reported",
                requirement=(
                    f"{limits['duration_min_s']:.0f}-{limits['duration_max_s']:.0f} seconds"
                ),
                ok=True,
                measured=False,
            )
        )
        report.not_checked.append("The duration could not be measured.")
    else:
        duration_ok = limits["duration_min_s"] <= duration <= limits["duration_max_s"]
        report.checks.append(
            Check(
                name="duration",
                value=f"{duration:.2f} s",
                requirement=(
                    f"{limits['duration_min_s']:.0f}-{limits['duration_max_s']:.0f} seconds"
                ),
                ok=duration_ok,
            )
        )
        if not duration_ok:
            report.problems.append(
                f"The clip is {duration:.1f} seconds long; Instagram needs between "
                f"{limits['duration_min_s']:.0f} and {limits['duration_max_s']:.0f}."
            )

    # -- file size ---------------------------------------------------------
    size_bytes = details["size_bytes"]
    size_ok = size_bytes <= limits["max_bytes"]
    report.checks.append(
        Check(
            name="file_size",
            value=_mb(size_bytes),
            requirement=_mb(limits["max_bytes"]),
            ok=size_ok,
        )
    )
    if not size_ok:
        report.problems.append(
            f"The file is {_mb(size_bytes)}; Instagram allows {_mb(limits['max_bytes'])}."
        )

    # -- video bitrate -----------------------------------------------------
    video_bitrate, bitrate_source = _video_bitrate(details)
    if video_bitrate is None:
        report.checks.append(
            Check(
                name="video_bitrate",
                value="not measured",
                requirement=f"{limits['video_bitrate_bps'] / 1_000_000:.0f} Mbps maximum",
                ok=True,
                measured=False,
            )
        )
        report.not_checked.append("The video bitrate could not be measured.")
    else:
        bitrate_ok = video_bitrate <= limits["video_bitrate_bps"]
        report.checks.append(
            Check(
                name="video_bitrate",
                value=f"{video_bitrate / 1_000_000:.2f} Mbps ({bitrate_source})",
                requirement=f"{limits['video_bitrate_bps'] / 1_000_000:.0f} Mbps maximum",
                ok=bitrate_ok,
            )
        )
        if not bitrate_ok:
            report.problems.append(
                f"The video bitrate is {video_bitrate / 1_000_000:.2f} Mbps; "
                f"Instagram allows {limits['video_bitrate_bps'] / 1_000_000:.0f} Mbps."
            )

    # -- audio -------------------------------------------------------------
    if details["has_audio"]:
        audio_codec = details["audio_codec"].lower()
        report.checks.append(
            Check(
                name="audio_codec",
                value=audio_codec or "unknown",
                requirement=str(limits["audio_codec"]),
                ok=audio_codec == str(limits["audio_codec"]).lower(),
                measured=bool(audio_codec),
            )
        )
        if audio_codec and audio_codec != str(limits["audio_codec"]).lower():
            report.problems.append(
                f"The audio codec is {audio_codec}; Instagram needs "
                f"{str(limits['audio_codec']).upper()}."
            )

        sample_rate = details["audio_sample_rate_hz"]
        if sample_rate is not None:
            rate_ok = sample_rate <= limits["audio_sample_rate_hz"]
            report.checks.append(
                Check(
                    name="audio_sample_rate",
                    value=f"{sample_rate} Hz",
                    requirement=f"{limits['audio_sample_rate_hz']} Hz maximum",
                    ok=rate_ok,
                )
            )
            if not rate_ok:
                report.problems.append(
                    f"The audio sample rate is {sample_rate} Hz; Instagram allows "
                    f"{limits['audio_sample_rate_hz']} Hz."
                )

        channels = details["audio_channels"]
        if channels is not None:
            channels_ok = 1 <= channels <= limits["audio_channels"]
            report.checks.append(
                Check(
                    name="audio_channels",
                    value=str(channels),
                    requirement=f"{limits['audio_channels']} maximum",
                    ok=channels_ok,
                )
            )
            if not channels_ok:
                report.problems.append(
                    f"The audio has {channels} channels; Instagram allows "
                    f"{limits['audio_channels']}."
                )

        audio_bitrate = details["audio_bitrate_bps"]
        if audio_bitrate is not None:
            audio_ok = audio_bitrate <= limits["audio_bitrate_bps"]
            report.checks.append(
                Check(
                    name="audio_bitrate",
                    value=f"{audio_bitrate / 1000:.1f} kbps",
                    requirement=f"{limits['audio_bitrate_bps'] / 1000:.0f} kbps",
                    ok=audio_ok,
                )
            )
            if not audio_ok:
                report.problems.append(
                    f"The audio bitrate is {audio_bitrate / 1000:.1f} kbps; Instagram "
                    f"allows {limits['audio_bitrate_bps'] / 1000:.0f} kbps."
                )
        else:
            report.not_checked.append("The audio bitrate could not be measured.")
    else:
        report.not_checked.append("The file has no audio track.")

    report.facts = {
        "duration_s": duration,
        "width": width,
        "height": height,
        "fps": fps,
        "size_bytes": size_bytes,
        "video_codec": video_codec,
        "audio_codec": details["audio_codec"],
        "has_audio": details["has_audio"],
        "moov_at_front": moov_at_front,
        "video_bitrate_bps": video_bitrate,
        "video_bitrate_source": bitrate_source,
    }
    report.ok = not report.problems
    return report


def _video_bitrate(details: dict[str, Any]) -> tuple[float | None, str]:
    """The video bitrate, and where the figure came from.

    ``ffprobe`` reports a per-stream bitrate for some files and not for
    others. When it is missing, the figure is derived from the file size
    and the duration, less the audio bitrate, and the source is named.
    """
    reported = details.get("video_bitrate_bps")
    if reported:
        return float(reported), "reported by ffprobe"

    duration = details.get("duration_s")
    size = details.get("size_bytes")
    if not duration or not size:
        return None, ""
    overall = float(size) * 8.0 / float(duration)
    audio = details.get("audio_bitrate_bps")
    if audio:
        return max(overall - float(audio), 0.0), "derived from the file size and duration"
    return overall, "derived from the file size and duration"


def _mb(value: int) -> str:
    return f"{value / (1024 * 1024):.1f} MB"


def validate_caption(caption: str) -> list[str]:
    """The caption problems Meta documents, as readable sentences.

    Instagram allows 2,200 characters, 30 hashtags and 20 @tags. A caption
    that breaks a limit is refused before it is sent, because Meta's own
    refusal names the limit but not which one was broken.
    """
    problems: list[str] = []
    text = caption or ""
    if len(text) > CAPTION_MAX_CHARS:
        problems.append(
            f"The caption is {len(text)} characters; Instagram allows {CAPTION_MAX_CHARS}."
        )
    hashtags = _count_tags(text, "#")
    if hashtags > CAPTION_MAX_HASHTAGS:
        problems.append(
            f"The caption has {hashtags} hashtags; Instagram allows {CAPTION_MAX_HASHTAGS}."
        )
    mentions = _count_tags(text, "@")
    if mentions > CAPTION_MAX_TAGS:
        problems.append(f"The caption has {mentions} @tags; Instagram allows {CAPTION_MAX_TAGS}.")
    return problems


def _count_tags(text: str, marker: str) -> int:
    """Count the hashtags or @tags in a caption.

    A tag is the marker followed by word characters, and it does not have
    to be at the start of a word — ``"100%#done"`` carries one hashtag.
    """
    count = 0
    index = text.find(marker)
    while index != -1:
        cursor = index + len(marker)
        while cursor < len(text) and (text[cursor].isalnum() or text[cursor] == "_"):
            cursor += 1
        if cursor > index + len(marker):
            count += 1
        index = text.find(marker, cursor)
    return count
