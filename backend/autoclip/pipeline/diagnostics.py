"""Objective quality diagnostics.

**Measurements, not opinions.** Every entry here says what was measured,
what the measurement came out as, and — when something is wrong — what to
do about it in words a person can act on.

There is deliberately **no score**. A number that said "this clip is 87%
good" would be invented: the measurements below are real, but there is no
honest way to fold them into one number, and a fake one would be worse
than none. The same goes for predicting virality — nothing in this file
can, and nothing in this file pretends to.

Each check is independent. A clip can fail one and pass the rest, and
the report says which — a list of measurements, not a verdict.

The measurements split into two kinds:

* **On the rendered file** — clipping, resolution, frame-rate
  consistency, black frames, whether the export is valid at all.
* **On the plan** — caption timing, crop safety, whether this clip
  duplicates another, whether the audio is missing, whether the duration
  is what it should be.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from . import captions, ffmpeg
from .reframe.croppath import CropPath, FaceRect
from .transcript import Word

log = logging.getLogger(__name__)

__all__ = [
    "MEASUREMENTS",
    "PLAN_MEASUREMENTS",
    "Diagnostic",
    "DiagnosticsReport",
    "diagnose_clip",
    "duplicate_clips",
]

#: More than this fraction of samples at full scale counts as clipping.
CLIPPING_LIMIT = 0.001

#: The frame-rate gaps may differ from the median by this much before the
#: clip is called inconsistent. Encoders and containers routinely vary a
#: little; a variable frame rate varies a lot.
FRAME_RATE_TOLERANCE = 0.02

#: A black stretch longer than this counts as a black frame.
BLACK_MIN_S = 0.2

#: Two clips overlap by more than this fraction of the shorter one and
#: they are duplicates.
OVERLAP_LIMIT = 0.5

#: How far a crop keyframe may sit from a face observation and still be
#: compared with it. The crop planner samples faces several times a second,
#: so half a second is loose enough for a smoothed keyframe and tight enough
#: that a face from a different moment is never mistaken for the one in the
#: shot.
FACE_MATCH_TOLERANCE_S = 0.5

#: Every measurement this module makes, in the order the specification
#: lists them. The list is the contract: a measurement that is not here
#: is not being made, and one that is here is always reported — even
#: when it could not be measured, in which case it says so.
MEASUREMENTS: tuple[str, ...] = (
    "audio_clipping",
    "caption_timing",
    "crop_safety",
    "resolution",
    "frame_rate_consistency",
    "black_frames",
    "export_validity",
    "duplicate_clips",
    "missing_audio",
    "duration",
)

#: The measurements that can be made without the rendered file, because
#: they are about the plan rather than the render.
PLAN_MEASUREMENTS: tuple[str, ...] = (
    "caption_timing",
    "crop_safety",
    "duplicate_clips",
)


@dataclass
class Diagnostic:
    """One measurement.

    ``ok`` is the verdict on that one measurement. ``measured`` is the
    number behind it, so the user can see the evidence rather than a
    bare pass or fail.
    """

    name: str
    title: str
    ok: bool
    measured: str = ""
    #: The problem, in a sentence. Empty when the measurement is fine.
    detail: str = ""
    #: False when the measurement itself could not be made. An
    #: unmeasurable thing is not the same as a correct one, and the two
    #: are never conflated.
    available: bool = True

    def to_dict(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "title": self.title,
            "ok": self.ok,
            "measured": self.measured,
            "detail": self.detail,
            "available": self.available,
        }


@dataclass
class DiagnosticsReport:
    """Every measurement for one clip."""

    diagnostics: list[Diagnostic] = field(default_factory=list)

    @property
    def ok(self) -> bool:
        """True when every measurement passed.

        A measurement that could not be made does not make the report
        fail, and it does not make it pass either: it is listed as
        unavailable so the user knows it was never checked.
        """
        return all(d.ok for d in self.diagnostics if d.available)

    def failures(self) -> list[Diagnostic]:
        return [d for d in self.diagnostics if d.available and not d.ok]

    def to_dict(self) -> dict[str, Any]:
        return {
            "ok": self.ok,
            "diagnostics": [d.to_dict() for d in self.diagnostics],
        }


# --------------------------------------------------------------------------
# The measurements on the rendered file
# --------------------------------------------------------------------------


def _clipping(path: Path) -> Diagnostic:
    ratio = ffmpeg.clipping_ratio(path)
    if ratio is None:
        return Diagnostic(
            "audio_clipping",
            "Audio clipping",
            ok=True,
            measured="not measured",
            available=False,
        )
    percent = ratio * 100.0
    ok = ratio <= CLIPPING_LIMIT
    return Diagnostic(
        "audio_clipping",
        "Audio clipping",
        ok=ok,
        measured=f"{percent:.3f}% of samples at full scale",
        detail=(
            ""
            if ok
            else (
                f"{percent:.3f}% of the samples are at full scale, which means the "
                "sound is being cut off. Lower the music or the voice-over level."
            )
        ),
    )


def _resolution(path: Path, expected: tuple[int, int] | None) -> Diagnostic:
    try:
        info = ffmpeg.probe(path)
    except ffmpeg.FFmpegError as exc:
        return Diagnostic(
            "resolution",
            "Video resolution",
            ok=False,
            measured="not measured",
            detail=f"The file could not be read: {exc}",
            available=False,
        )

    if not info.has_video or not info.width or not info.height:
        return Diagnostic(
            "resolution",
            "Video resolution",
            ok=False,
            measured="no video stream",
            detail="The exported file has no video in it.",
        )

    actual = (info.width, info.height)
    if expected is None:
        return Diagnostic(
            "resolution",
            "Video resolution",
            ok=True,
            measured=f"{actual[0]}x{actual[1]}",
        )

    ok = actual == expected
    return Diagnostic(
        "resolution",
        "Video resolution",
        ok=ok,
        measured=f"{actual[0]}x{actual[1]}",
        detail=(
            ""
            if ok
            else (
                f"The export is {actual[0]}x{actual[1]}, but "
                f"{expected[0]}x{expected[1]} was asked for."
            )
        ),
    )


def _frame_rate(path: Path) -> Diagnostic:
    durations = ffmpeg.frame_durations(path)
    if len(durations) < 3:
        return Diagnostic(
            "frame_rate_consistency",
            "Frame-rate consistency",
            ok=True,
            measured="not measured",
            available=False,
        )

    ordered = sorted(durations)
    middle = len(ordered) // 2
    median = ordered[middle]
    if median <= 0:
        return Diagnostic(
            "frame_rate_consistency",
            "Frame-rate consistency",
            ok=True,
            measured="not measured",
            available=False,
        )

    spread = (ordered[-1] - ordered[0]) / median
    fps = 1.0 / median
    ok = spread <= FRAME_RATE_TOLERANCE
    return Diagnostic(
        "frame_rate_consistency",
        "Frame-rate consistency",
        ok=ok,
        measured=f"{fps:.2f} fps, spread {spread * 100:.1f}%",
        detail=(
            ""
            if ok
            else (
                "The gaps between frames vary by more than "
                f"{FRAME_RATE_TOLERANCE * 100:.0f}%. A variable frame rate makes "
                "the playback stutter on some devices."
            )
        ),
    )


def _black_frames(path: Path) -> Diagnostic:
    intervals = ffmpeg.black_intervals(path, min_duration_s=BLACK_MIN_S)
    total = sum(end - start for start, end in intervals if end != float("inf"))
    if not intervals:
        return Diagnostic(
            "black_frames",
            "Black frames",
            ok=True,
            measured="none found",
        )
    return Diagnostic(
        "black_frames",
        "Black frames",
        ok=False,
        measured=f"{len(intervals)} black stretch(es), {total:.2f}s",
        detail=(
            "The clip goes black for "
            f"{total:.2f} seconds. That is usually a fade or a gap in the source."
        ),
    )


def _export_validity(path: Path) -> Diagnostic:
    exists = path.is_file()
    if not exists:
        return Diagnostic(
            "export_validity",
            "Export validity",
            ok=False,
            measured="missing",
            detail="The exported file is not there.",
        )

    try:
        info = ffmpeg.probe(path)
    except ffmpeg.FFmpegError as exc:
        return Diagnostic(
            "export_validity",
            "Export validity",
            ok=False,
            measured="unreadable",
            detail=f"The exported file could not be read: {exc}",
        )

    size = path.stat().st_size
    ok = info.has_video and size > 0
    return Diagnostic(
        "export_validity",
        "Export validity",
        ok=ok,
        measured=f"{size} bytes, {info.duration_s:.2f}s",
        detail="" if ok else "The exported file could not be played.",
    )


def _duration(path: Path, expected_s: float, tolerance_s: float) -> Diagnostic:
    try:
        info = ffmpeg.probe(path)
    except ffmpeg.FFmpegError:
        return Diagnostic(
            "duration",
            "Clip duration",
            ok=True,
            measured="not measured",
            available=False,
        )

    drift = abs(info.duration_s - expected_s)
    ok = drift <= tolerance_s
    return Diagnostic(
        "duration",
        "Clip duration",
        ok=ok,
        measured=f"{info.duration_s:.2f}s, expected {expected_s:.2f}s",
        detail=(
            "" if ok else (f"The clip is {drift:.2f}s longer or shorter than the cut it came from.")
        ),
    )


def _missing_audio(path: Path, required: bool) -> Diagnostic:
    try:
        info = ffmpeg.probe(path)
    except ffmpeg.FFmpegError:
        return Diagnostic(
            "missing_audio",
            "Audio present",
            ok=True,
            measured="not measured",
            available=False,
        )

    if info.has_audio:
        return Diagnostic(
            "missing_audio",
            "Audio present",
            ok=True,
            measured=f"present ({info.audio_codec or 'unknown codec'})",
        )

    if not required:
        return Diagnostic(
            "missing_audio",
            "Audio present",
            ok=True,
            measured="no audio stream, and none was needed",
        )

    return Diagnostic(
        "missing_audio",
        "Audio present",
        ok=False,
        measured="no audio stream",
        detail="The clip is silent. Either the source has no sound, or the mix dropped it.",
    )


# --------------------------------------------------------------------------
# The measurements on the plan
# --------------------------------------------------------------------------


def _caption_timing(
    words: list[Word],
    start_s: float,
    end_s: float,
    caption_style: str = captions.DEFAULT_STYLE,
) -> Diagnostic:
    """How well the captions line up with the words they are captions of.

    Measured two ways: words that fall outside the clip, and captions that
    overlap the next one.

    How long a caption is held is not a fault here — the renderer bounds it
    (``captions.MAX_CAPTION_S``), so the longest caption is reported as a
    measurement rather than counted as a problem. It is measured on the
    caption as the viewer sees it, not on the recogniser's timing: a word the
    recogniser stretched across seconds of silence produces a short caption,
    and the measurement has to agree with what was burned into the export.
    """
    if not words:
        return Diagnostic(
            "caption_timing",
            "Caption timing",
            ok=True,
            measured="no words to caption",
        )

    outside = [w for w in words if w.start < start_s - 1e-6 or w.end > end_s + 1e-6]
    overlaps = 0
    for previous, current in zip(words, words[1:], strict=False):
        if current.start < previous.end - 1e-6:
            overlaps += 1

    style = captions.get_style(caption_style)
    spans = captions.caption_spans(words, style)
    longest = max((stop - begin for begin, stop in spans), default=0.0)

    problems = []
    if outside:
        problems.append(f"{len(outside)} word(s) fall outside the clip")
    if overlaps:
        problems.append(f"{overlaps} caption(s) overlap the next one")

    return Diagnostic(
        "caption_timing",
        "Caption timing",
        ok=not problems,
        measured=(f"{len(words)} words, {overlaps} overlap(s), longest caption {longest:.2f}s"),
        detail="; ".join(problems),
    )


def _subject_face_at(faces: list[FaceRect], t: float) -> FaceRect | None:
    """The largest face seen within half a second of ``t``.

    The largest face is the subject: when several are on screen the crop is
    planned around the one that matters, and a smaller face at the edge of
    the frame may legitimately be cut.
    """
    near = [face for face in faces if abs(face.t - t) <= FACE_MATCH_TOLERANCE_S]
    if not near:
        return None
    return max(near, key=lambda face: face.width * face.height)


def _crop_safety(
    crop_path: CropPath | None,
    source_size: tuple[int, int] | None,
) -> Diagnostic:
    """Whether the crop stays inside the frame, and keeps the face.

    Two things are checked: the crop window never leaves the source, and
    it does not cut through a face that was detected. Both are facts
    about numbers, not judgements about the picture.

    The face is the one the crop plan was built around, at the moment the
    crop is at. A rectangle measured somewhere else — a webcam region found
    once for the whole source, say — says nothing about this crop, and
    comparing the two reports failures that never happened.
    """
    if crop_path is None:
        return Diagnostic(
            "crop_safety",
            "Crop safety",
            ok=True,
            measured="no crop",
        )

    width = crop_path.source_width
    height = crop_path.source_height
    if source_size is not None and (width, height) != source_size:
        return Diagnostic(
            "crop_safety",
            "Crop safety",
            ok=False,
            measured=f"source {width}x{height}, expected {source_size[0]}x{source_size[1]}",
            detail="The crop was planned against a different frame size than the source has.",
        )

    problems: list[str] = []
    measured = f"{len(crop_path.segments)} segment(s)"
    if crop_path.faces:
        measured += f", {len(crop_path.faces)} face(s) tracked"
    else:
        measured += ", no face tracked"

    for segment in crop_path.segments:
        if segment.width <= 0 or segment.height <= 0:
            problems.append("a segment has no size")
            continue
        if segment.width > width or segment.height > height:
            problems.append("a segment is larger than the source")
        for keyframe in segment.keyframes:
            if keyframe.x < 0 or keyframe.y < 0:
                problems.append("the crop leaves the frame")
                break
            if keyframe.x + segment.width > width + 1:
                problems.append("the crop leaves the frame on the right")
                break
            if keyframe.y + segment.height > height + 1:
                problems.append("the crop leaves the frame at the bottom")
                break

    for segment in crop_path.segments:
        for keyframe in segment.keyframes:
            face = _subject_face_at(crop_path.faces, keyframe.t)
            if face is None:
                continue
            crop_right = keyframe.x + segment.width
            crop_bottom = keyframe.y + segment.height
            face_right = face.x + face.width
            face_bottom = face.y + face.height
            overlaps = (
                keyframe.x < face_right
                and crop_right > face.x
                and keyframe.y < face_bottom
                and crop_bottom > face.y
            )
            contains = (
                keyframe.x <= face.x
                and keyframe.y <= face.y
                and crop_right >= face_right
                and crop_bottom >= face_bottom
            )
            if overlaps and not contains:
                problems.append("the crop cuts through the detected face")
                break
        if problems:
            break

    return Diagnostic(
        "crop_safety",
        "Crop safety",
        ok=not problems,
        measured=measured,
        detail="; ".join(dict.fromkeys(problems)),
    )


def duplicate_clips(clips: list[Any]) -> list[tuple[str, str, float]]:
    """The pairs of clips that overlap too much to be different clips.

    Returns ``(id_a, id_b, overlap_fraction)`` for each pair. The
    fraction is of the *shorter* clip, because a 20-second clip that is
    entirely inside a 60-second one is a duplicate in every sense that
    matters to a viewer.
    """
    pairs: list[tuple[str, str, float]] = []
    ordered = sorted(clips, key=lambda clip: clip.start_s)
    for index, first in enumerate(ordered):
        for second in ordered[index + 1 :]:
            if second.start_s >= first.end_s:
                break
            overlap = min(first.end_s, second.end_s) - max(first.start_s, second.start_s)
            if overlap <= 0:
                continue
            shorter = min(
                first.end_s - first.start_s,
                second.end_s - second.start_s,
            )
            if shorter <= 0:
                continue
            fraction = overlap / shorter
            if fraction >= OVERLAP_LIMIT:
                pairs.append((first.id, second.id, round(fraction, 3)))
    return pairs


def _duplicate(clips: list[Any], clip_id: str) -> Diagnostic:
    pairs = duplicate_clips(clips)
    mine = [pair for pair in pairs if clip_id in pair[:2]]
    if not mine:
        return Diagnostic(
            "duplicate_clips",
            "Duplicate clips",
            ok=True,
            measured="none",
        )
    worst = max(mine, key=lambda pair: pair[2])
    return Diagnostic(
        "duplicate_clips",
        "Duplicate clips",
        ok=False,
        measured=f"{len(mine)} overlapping pair(s)",
        detail=(
            "This clip overlaps another one by "
            f"{worst[2] * 100:.0f}%. They will look like the same clip."
        ),
    )


# --------------------------------------------------------------------------
# The report
# --------------------------------------------------------------------------


def diagnose_clip(
    path: Path | None,
    *,
    clip_id: str = "",
    clips: list[Any] | None = None,
    words: list[Word] | None = None,
    start_s: float = 0.0,
    end_s: float = 0.0,
    expected_size: tuple[int, int] | None = None,
    source_size: tuple[int, int] | None = None,
    crop_path: CropPath | None = None,
    require_audio: bool = True,
    duration_tolerance_s: float = 0.75,
    caption_style: str = captions.DEFAULT_STYLE,
) -> DiagnosticsReport:
    """Measure one clip and report what was found.

    Nothing here raises: a diagnostic that cannot be measured says so
    and moves on, because a missing measurement is not a broken render.

    There is no ``face_rect`` argument, and that is deliberate. A face
    rectangle only says anything about a crop if it was measured for the
    same clip, at the same moment, in the same coordinates — so the crop
    plan carries its own faces and the check uses those.
    """
    diagnostics: list[Diagnostic] = []

    diagnostics.append(_caption_timing(words or [], start_s, end_s, caption_style))
    diagnostics.append(_crop_safety(crop_path, source_size))
    diagnostics.append(_duplicate(clips or [], clip_id))

    if path is None or not path.is_file():
        diagnostics.append(
            Diagnostic(
                "export_validity",
                "Export validity",
                ok=False,
                measured="missing",
                detail="The exported file is not there, so the rest could not be measured.",
            )
        )
        return DiagnosticsReport(diagnostics=diagnostics)

    diagnostics.append(_export_validity(path))
    diagnostics.append(_duration(path, max(0.0, end_s - start_s), duration_tolerance_s))
    diagnostics.append(_resolution(path, expected_size))
    diagnostics.append(_frame_rate(path))
    diagnostics.append(_black_frames(path))
    diagnostics.append(_missing_audio(path, require_audio))
    diagnostics.append(_clipping(path))

    return DiagnosticsReport(diagnostics=diagnostics)
