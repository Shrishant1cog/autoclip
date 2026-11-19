"""Clip validation (Phase 9).

Every export is checked before it can be published. Two layers:

* **Bounds** — the clip's time range and word range must make sense against
  the transcript (positive duration, inside the transcript, sane length).
* **Media** — the rendered file must actually exist, probe, contain the video
  and audio streams we expect, and last roughly as long as the cut.

The point is to catch a broken render *before* it reaches a channel. A failure
never fabricates a replacement: the clip is marked ``invalid``, the reasons are
stored, and auto-publish skips it.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from pathlib import Path

from . import ffmpeg
from .transcript import Transcript

log = logging.getLogger(__name__)

#: How far the rendered duration may drift from the cut before it is suspect.
#: Encoders pad by up to a frame or two; resampling adds a little more.
DURATION_TOLERANCE_S = 0.75

#: A file smaller than this is almost certainly a broken render.
MIN_FILE_BYTES = 4_096

#: Peak level below this counts as silent audio (-50 dBFS).
SILENCE_PEAK_DB = -50.0


@dataclass
class Check:
    name: str
    ok: bool
    detail: str = ""


@dataclass
class ValidationReport:
    ok: bool
    checks: list[Check] = field(default_factory=list)
    duration_s: float = 0.0
    width: int = 0
    height: int = 0

    def failures(self) -> list[str]:
        return [f"{c.name}: {c.detail}" for c in self.checks if not c.ok]

    def to_dict(self) -> dict[str, object]:
        return {
            "ok": self.ok,
            "checks": [{"name": c.name, "ok": c.ok, "detail": c.detail} for c in self.checks],
            "duration_s": self.duration_s,
            "width": self.width,
            "height": self.height,
        }


def validate_bounds(
    *,
    start_s: float,
    end_s: float,
    start_word: int,
    end_word: int,
    transcript: Transcript,
    min_duration_s: float,
    max_duration_s: float,
) -> list[Check]:
    """Sane time/word range checks against the transcript."""
    checks: list[Check] = []
    duration = end_s - start_s

    checks.append(
        Check(
            "duration_positive",
            duration > 0,
            f"start={start_s:.3f}s end={end_s:.3f}s",
        )
    )
    checks.append(
        Check(
            "duration_min",
            duration >= min_duration_s - 1e-6,
            f"{duration:.2f}s < minimum {min_duration_s:.2f}s",
        )
    )
    checks.append(
        Check(
            "duration_max",
            duration <= max_duration_s + 1e-6,
            f"{duration:.2f}s > maximum {max_duration_s:.2f}s",
        )
    )

    word_count = len(transcript.words)
    checks.append(
        Check(
            "word_range",
            0 <= start_word <= end_word < max(word_count, 1),
            f"words {start_word}-{end_word}, transcript has {word_count}",
        )
    )
    checks.append(
        Check(
            "start_in_source",
            start_s >= 0,
            f"start={start_s:.3f}s",
        )
    )
    checks.append(
        Check(
            "end_in_source",
            end_s <= transcript.duration + 0.5 if transcript.duration else True,
            f"end={end_s:.3f}s vs transcript {transcript.duration:.3f}s",
        )
    )
    return checks


def validate_media(
    path: Path,
    *,
    expected_duration_s: float,
    expected_size: tuple[int, int] | None = None,
    require_audio: bool = True,
    duration_tolerance_s: float = DURATION_TOLERANCE_S,
) -> ValidationReport:
    """Probe a rendered file and confirm it is what the cut promised."""
    checks: list[Check] = []

    exists = path.is_file()
    size = path.stat().st_size if exists else 0
    checks.append(Check("file_exists", exists, str(path)))
    checks.append(
        Check("file_size", size >= MIN_FILE_BYTES, f"{size} bytes (min {MIN_FILE_BYTES})")
    )

    if not exists:
        return ValidationReport(ok=False, checks=checks)

    try:
        info = ffmpeg.probe(path)
    except ffmpeg.FFmpegError as exc:
        checks.append(Check("probe", False, str(exc)))
        return ValidationReport(ok=False, checks=checks)
    checks.append(
        Check(
            "probe",
            True,
            f"{info.width or 0}x{info.height or 0}, {info.duration_s:.2f}s",
        )
    )
    checks.append(Check("has_video", info.has_video, "no video stream"))
    checks.append(
        Check(
            "has_audio",
            info.has_audio or not require_audio,
            "no audio stream",
        )
    )

    if expected_size is not None and info.has_video:
        width, height = expected_size
        checks.append(
            Check(
                "resolution",
                (info.width, info.height) == (width, height),
                f"{info.width}x{info.height}, expected {width}x{height}",
            )
        )

    drift = abs(info.duration_s - expected_duration_s)
    checks.append(
        Check(
            "duration",
            drift <= duration_tolerance_s,
            f"{info.duration_s:.2f}s vs expected {expected_duration_s:.2f}s "
            f"(tolerance {duration_tolerance_s:.2f}s)",
        )
    )

    if info.has_audio:
        peak = _peak_db(path)
        checks.append(
            Check(
                "audio_not_silent",
                peak is None or peak > SILENCE_PEAK_DB,
                f"peak {peak:.1f} dBFS" if peak is not None else "peak unmeasured",
            )
        )

    ok = all(c.ok for c in checks)
    if not ok:
        log.warning(
            "Validation failed for %s: %s",
            path.name,
            "; ".join(f"{c.name} ({c.detail})" for c in checks if not c.ok),
        )
    return ValidationReport(
        ok=ok,
        checks=checks,
        duration_s=info.duration_s,
        width=info.width,
        height=info.height,
    )


def _peak_db(path: Path) -> float | None:
    """Peak level of the whole file, via ffmpeg's volumedetect.

    Returns ``None`` when the measurement itself fails — an unmeasurable level
    should not fail a clip that otherwise passed, since the audio stream was
    already confirmed present.
    """
    try:
        result = ffmpeg.volumedetect(path)
    except ffmpeg.FFmpegError:
        log.debug("volumedetect failed for %s", path, exc_info=True)
        return None
    return result


__all__ = [
    "Check",
    "DURATION_TOLERANCE_S",
    "MIN_FILE_BYTES",
    "ValidationReport",
    "validate_bounds",
    "validate_media",
]
