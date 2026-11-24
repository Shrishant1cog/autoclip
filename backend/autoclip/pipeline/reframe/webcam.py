"""Webcam region detection and tracking.

A webcam overlay is a rectangle somewhere in the frame that keeps showing the
same person while the gameplay behind it changes. That is the whole idea, and
this module is built around it:

* **A face is not a webcam.** A face says someone is on screen. A webcam says
  a particular rectangle keeps holding that person, in the same place, across
  cuts. The two are reported separately, and the region carries a confidence.
* **Nothing identifies anybody.** No template is built, no embedding is
  stored, no identity crosses a frame boundary. The output is a rectangle and
  a number.
* **A detector that finds nothing is a normal outcome.** The caller falls
  back to a plain crop. The module never raises because a face was missing.

The confidence is built from four things that a real webcam overlay has and a
person in the scene usually does not:

``support``
    How much of the clip the region actually holds a face.
``stability``
    How little the face moves inside the region.
``cut_stability``
    How little the face moves when the gameplay cuts. This is the sharpest
    signal: an overlay does not move when the shot changes, because the
    overlay is not part of the shot.
``persistence``
    How many separate shots the region survives.

A face in the gameplay — a character, a streamer on camera in the game world,
a person on a webcam that moves with the scene — scores poorly on
``cut_stability`` and is rejected. The thresholds are documented constants so
a user can see exactly what was decided and why.
"""

from __future__ import annotations

import json
import logging
import statistics
from dataclasses import asdict, dataclass, field, replace
from pathlib import Path
from typing import Any

from .faces import FACE_TILE_PX, FaceObservation, sample_faces
from .scenes import Shot, detect_shots

log = logging.getLogger(__name__)

__all__ = [
    "Rect",
    "FacePoint",
    "WebcamBox",
    "WebcamCandidate",
    "WebcamKeyframe",
    "WebcamPath",
    "WebcamReport",
    "WebcamSpan",
    "WebcamTrack",
    "MAX_WEBCAM_PATH_KEYFRAMES",
    "adaptive_sample_fps",
    "build_webcam_path",
    "detect_webcam",
    "estimate_webcam_rect",
    "track_webcam",
]

# --------------------------------------------------------------------------
# Adaptive sampling
# --------------------------------------------------------------------------

#: The floor. Below this a slow clip is sampled too thinly to see a face that
#: appears and disappears.
MIN_SAMPLE_FPS = 2.0

#: The sampling rate for calm footage — one shot per second or fewer.
BASE_SAMPLE_FPS = 5.0

#: The ceiling. Beyond this the detector costs more than it is worth and the
#: crop path is smoothed anyway.
MAX_SAMPLE_FPS = 15.0

#: Every shot gets at least this many samples. A shot seen once is a shot the
#: detector cannot make a decision about.
MIN_SAMPLES_PER_SHOT = 2

#: The report's format. A saved report written by another version says
#: nothing reliable about the current detector — it may have failed, and the
#: older format could not say so — so it is detected again rather than reused.
REPORT_VERSION = 2

#: Cap on the keyframes in the webcam's own path. The path becomes an ffmpeg
#: expression, and an expression with hundreds of nested conditionals is
#: evaluated at every frame of the clip — and, on Windows, can push the
#: command line past the operating system's own length limit. The measured
#: boxes arrive at the detector's sample rate, so a long clip produces
#: hundreds of them; the path only has to say where the frame *was*, not
#: where it was in every one of the fifteen samples a second that were
#: looked at. The same budget the gameplay crop path uses.
MAX_WEBCAM_PATH_KEYFRAMES = 48

#: Movement below this many pixels is dropped while thinning the path.
WEBCAM_PATH_EPSILON_PX = 1.0

#: Cuts per minute above which the footage is treated as fast-cut and the
#: sampling rate goes up. Below it, the base rate is enough.
CUTS_PER_MINUTE_FOR_DENSITY = 4.0

# --------------------------------------------------------------------------
# Clustering
# --------------------------------------------------------------------------

#: Two faces belong to the same region when their centres are within this
#: fraction of the frame diagonal.
CLUSTER_RADIUS_FRAC = 0.18

#: A face wider than this fraction of the frame diagonal is the camera being
#: pointed at a face, not a webcam overlay. It is rejected as a candidate.
MAX_FACE_FRAC_OF_DIAGONAL = 0.55

# --------------------------------------------------------------------------
# Confidence
# --------------------------------------------------------------------------

#: Below this the region is not reported as a webcam at all. The caller uses
#: the safe fallback and says so.
MIN_CONFIDENCE = 0.35

#: How much each measure contributes to the confidence.
WEIGHT_SUPPORT = 0.30
WEIGHT_STABILITY = 0.25
WEIGHT_CUT_STABILITY = 0.30
WEIGHT_PERSISTENCE = 0.15

# --------------------------------------------------------------------------
# The region around a face
# --------------------------------------------------------------------------

#: The region is the face plus headroom and shoulders, because a webcam box
#: shows more than a face. These are fractions of the face box.
MARGIN_X = 0.60
MARGIN_TOP = 0.90
MARGIN_BOTTOM = 0.80

#: A region smaller than this (as a fraction of the frame) is too small to be
#: worth laying out; the caller falls back.
MIN_REGION_FRAC = 0.02


@dataclass(frozen=True)
class Rect:
    """A rectangle in source-pixel coordinates."""

    x: float
    y: float
    width: float
    height: float

    @property
    def area(self) -> float:
        return max(0.0, self.width) * max(0.0, self.height)

    @property
    def cx(self) -> float:
        return self.x + self.width / 2

    @property
    def cy(self) -> float:
        return self.y + self.height / 2

    @property
    def right(self) -> float:
        return self.x + self.width

    @property
    def bottom(self) -> float:
        return self.y + self.height

    def contains_point(self, x: float, y: float) -> bool:
        return self.x <= x <= self.right and self.y <= y <= self.bottom

    def intersection_area(self, other: Rect) -> float:
        width = max(0.0, min(self.right, other.right) - max(self.x, other.x))
        height = max(0.0, min(self.bottom, other.bottom) - max(self.y, other.y))
        return width * height

    def iou(self, other: Rect) -> float:
        intersection = self.intersection_area(other)
        if intersection <= 0:
            return 0.0
        union = self.area + other.area - intersection
        return intersection / union if union else 0.0

    def to_dict(self) -> dict[str, float]:
        return {k: round(float(v), 2) for k, v in asdict(self).items()}

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> Rect:
        return cls(
            x=float(data.get("x", 0.0)),
            y=float(data.get("y", 0.0)),
            width=float(data.get("width", 0.0)),
            height=float(data.get("height", 0.0)),
        )


@dataclass(frozen=True)
class FacePoint:
    """Where the face was, at one moment, in source pixels.

    The crop follows the face inside the webcam's own frame, so the crop
    stays on the streamer rather than on the middle of the box.
    """

    t: float
    cx: float
    cy: float
    width: float

    def to_dict(self) -> dict[str, Any]:
        return {
            "t": round(self.t, 3),
            "cx": round(self.cx, 2),
            "cy": round(self.cy, 2),
            "width": round(self.width, 2),
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> FacePoint:
        return cls(
            t=float(data.get("t", 0.0)),
            cx=float(data.get("cx", 0.0)),
            cy=float(data.get("cy", 0.0)),
            width=float(data.get("width", 0.0)),
        )


@dataclass(frozen=True)
class WebcamBox:
    """Where the webcam's own frame was, at one moment.

    A webcam overlay is not always the same size: the streamer changes the
    layout, the source is a screen recording, the box is scaled by the
    player. A single rectangle for the whole clip is therefore wrong for
    part of it. This is one measurement of the box, with the time it was
    taken.
    """

    #: When the box was measured, in the track's own time base.
    t: float
    #: The box, in source pixels.
    rect: Rect
    #: How many of the four edges were seen in the picture rather than
    #: guessed from the face: left, top, right, bottom.
    edges_found: tuple[bool, bool, bool, bool] = (False, False, False, False)

    @property
    def measured(self) -> int:
        """How many of the four edges came from the picture."""
        return sum(1 for found in self.edges_found if found)

    def to_dict(self) -> dict[str, Any]:
        return {
            "t": round(self.t, 3),
            "rect": self.rect.to_dict(),
            "edges_found": list(self.edges_found),
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> WebcamBox:
        raw_rect = data.get("rect")
        rect = Rect.from_dict(raw_rect) if isinstance(raw_rect, dict) else Rect(0, 0, 0, 0)
        raw_edges = data.get("edges_found")
        edges = raw_edges if isinstance(raw_edges, list) else []
        flags = [bool(flag) for flag in edges[:4]]
        while len(flags) < 4:
            flags.append(False)
        found = (flags[0], flags[1], flags[2], flags[3])
        return cls(t=float(data.get("t", 0.0)), rect=rect, edges_found=found)


@dataclass(frozen=True)
class WebcamKeyframe:
    """Where the middle of the webcam's own frame was, at one moment."""

    t: float
    cx: float
    cy: float

    def to_dict(self) -> dict[str, Any]:
        return {
            "t": round(self.t, 3),
            "cx": round(self.cx, 2),
            "cy": round(self.cy, 2),
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> WebcamKeyframe:
        return cls(
            t=float(data.get("t", 0.0)),
            cx=float(data.get("cx", 0.0)),
            cy=float(data.get("cy", 0.0)),
        )


@dataclass
class WebcamPath:
    """The webcam's own frame, followed over time.

    The frame is not one rectangle: the streamer changes the layout, the
    source is scaled by the player, the box grows and shrinks. The path
    says where the middle of the box was at each moment, and how big the
    box was over the clip.

    The size is the median of the measurements rather than a per-frame
    value, because a filter graph cannot change the size of its output
    halfway through: the crop follows the box, and the size it is drawn at
    is the one the box had for most of the clip.
    """

    source_width: int
    source_height: int
    width: float
    height: float
    keyframes: list[WebcamKeyframe] = field(default_factory=list)

    @property
    def duration_s(self) -> float:
        return self.keyframes[-1].t if self.keyframes else 0.0

    def to_dict(self) -> dict[str, Any]:
        return {
            "source_width": self.source_width,
            "source_height": self.source_height,
            "width": round(self.width, 2),
            "height": round(self.height, 2),
            "keyframes": [keyframe.to_dict() for keyframe in self.keyframes],
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> WebcamPath:
        raw = data.get("keyframes")
        items = raw if isinstance(raw, list) else []
        return cls(
            source_width=int(data.get("source_width", 0)),
            source_height=int(data.get("source_height", 0)),
            width=float(data.get("width", 0.0)),
            height=float(data.get("height", 0.0)),
            keyframes=[WebcamKeyframe.from_dict(item) for item in items if isinstance(item, dict)],
        )


@dataclass
class WebcamCandidate:
    """A possible webcam region, with the evidence for it."""

    rect: Rect
    confidence: float
    #: How much of the clip the region held a face.
    support: float
    #: How little the face moved inside the region.
    stability: float
    #: How little the face moved when the gameplay cut.
    cut_stability: float
    #: How many separate shots the region survived.
    persistence: float
    #: How many face observations were seen inside the region.
    observations: int
    #: The median face width inside the region, in source pixels. This is what
    #: decides whether the webcam can be shown at all: a face that is thirty
    #: pixels wide is a smudge however carefully it is laid out.
    face_width: float = 0.0
    #: Which shots the region was seen in.
    shots: list[int] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "rect": self.rect.to_dict(),
            "confidence": round(self.confidence, 4),
            "support": round(self.support, 4),
            "stability": round(self.stability, 4),
            "cut_stability": round(self.cut_stability, 4),
            "persistence": round(self.persistence, 4),
            "observations": self.observations,
            "face_width": round(self.face_width, 2),
            "shots": list(self.shots),
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> WebcamCandidate:
        raw_rect = data.get("rect")
        rect = Rect.from_dict(raw_rect) if isinstance(raw_rect, dict) else Rect(0, 0, 0, 0)
        raw_shots = data.get("shots")
        shots = raw_shots if isinstance(raw_shots, list) else []
        return cls(
            rect=rect,
            confidence=float(data.get("confidence", 0.0)),
            support=float(data.get("support", 0.0)),
            stability=float(data.get("stability", 0.0)),
            cut_stability=float(data.get("cut_stability", 0.0)),
            persistence=float(data.get("persistence", 0.0)),
            observations=int(data.get("observations", 0)),
            face_width=float(data.get("face_width", 0.0)),
            shots=[int(index) for index in shots],
        )


@dataclass
class WebcamSpan:
    """A stretch of the clip and whether the region held a face in it."""

    start_s: float
    end_s: float
    present: bool
    confidence: float
    reason: str = ""

    @property
    def duration_s(self) -> float:
        return self.end_s - self.start_s

    def to_dict(self) -> dict[str, Any]:
        return {
            "start_s": round(self.start_s, 3),
            "end_s": round(self.end_s, 3),
            "present": self.present,
            "confidence": round(self.confidence, 4),
            "reason": self.reason,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> WebcamSpan:
        return cls(
            start_s=float(data.get("start_s", 0.0)),
            end_s=float(data.get("end_s", 0.0)),
            present=bool(data.get("present", False)),
            confidence=float(data.get("confidence", 0.0)),
            reason=str(data.get("reason", "")),
        )


@dataclass
class WebcamTrack:
    """A webcam region followed across the clip."""

    rect: Rect
    confidence: float
    start_s: float
    end_s: float
    spans: list[WebcamSpan] = field(default_factory=list)
    #: True when the region was not seen for part of the clip.
    uncertain: bool = False
    #: Why the track is uncertain, in plain words.
    reason: str = ""
    #: The median face width inside the region, in source pixels.
    face_width: float = 0.0
    #: Where the webcam's own frame was, over time. Empty when the box
    #: could not be measured in the picture, in which case the region is
    #: used as it is.
    boxes: list[WebcamBox] = field(default_factory=list)
    #: Where the face was, over time — in source pixels, in the track's time
    #: base. The crop follows the face inside the box.
    faces: list[FacePoint] = field(default_factory=list)

    @property
    def duration_s(self) -> float:
        return self.end_s - self.start_s

    @property
    def region(self) -> Rect:
        """The rectangle that should be shown to the viewer.

        When the webcam's own frame was seen in the picture, that frame is
        the region: it is the true edge of the webcam, and a crop built
        from the face alone spills outside it. When it was not seen, the
        region around the face is the best guess there is.
        """
        if not self.boxes:
            return self.rect
        return _median_box(self.boxes)

    def to_dict(self) -> dict[str, Any]:
        return {
            "rect": self.rect.to_dict(),
            "confidence": round(self.confidence, 4),
            "start_s": round(self.start_s, 3),
            "end_s": round(self.end_s, 3),
            "uncertain": self.uncertain,
            "reason": self.reason,
            "face_width": round(self.face_width, 2),
            "boxes": [box.to_dict() for box in self.boxes],
            "faces": [face.to_dict() for face in self.faces],
            "spans": [span.to_dict() for span in self.spans],
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> WebcamTrack:
        raw_rect = data.get("rect")
        rect = Rect.from_dict(raw_rect) if isinstance(raw_rect, dict) else Rect(0, 0, 0, 0)
        raw_spans = data.get("spans")
        items = raw_spans if isinstance(raw_spans, list) else []
        raw_boxes = data.get("boxes")
        box_items = raw_boxes if isinstance(raw_boxes, list) else []
        raw_faces = data.get("faces")
        face_items = raw_faces if isinstance(raw_faces, list) else []
        return cls(
            rect=rect,
            confidence=float(data.get("confidence", 0.0)),
            start_s=float(data.get("start_s", 0.0)),
            end_s=float(data.get("end_s", 0.0)),
            spans=[WebcamSpan.from_dict(item) for item in items if isinstance(item, dict)],
            uncertain=bool(data.get("uncertain", False)),
            reason=str(data.get("reason", "")),
            face_width=float(data.get("face_width", 0.0)),
            boxes=[WebcamBox.from_dict(item) for item in box_items if isinstance(item, dict)],
            faces=[FacePoint.from_dict(item) for item in face_items if isinstance(item, dict)],
        )

    def slice(self, start_s: float, end_s: float) -> WebcamTrack:
        """The part of the track inside a time range, measured from its start.

        A clip's clock starts at the clip, so the spans are rebased here
        rather than in every caller that forgets it. The region itself does
        not move — an overlay stays where it is — so it is carried over
        unchanged.
        """
        offset = start_s
        spans: list[WebcamSpan] = []
        for span in self.spans:
            begin = max(span.start_s, start_s)
            finish = min(span.end_s, end_s)
            if finish <= begin:
                continue
            spans.append(
                WebcamSpan(
                    start_s=begin - offset,
                    end_s=finish - offset,
                    present=span.present,
                    confidence=span.confidence,
                    reason=span.reason,
                )
            )

        duration = max(0.0, end_s - start_s)
        missing_s = sum(span.duration_s for span in spans if not span.present)
        uncertain = any(not span.present for span in spans)
        if not spans:
            reason = "the webcam was not seen anywhere in this clip"
        elif missing_s <= 0:
            reason = ""
        elif missing_s >= duration * 0.5:
            reason = "the region held a face for less than half the clip"
        else:
            reason = f"the region held no face for {missing_s:.1f}s"

        return WebcamTrack(
            rect=self.rect,
            confidence=self.confidence,
            start_s=0.0,
            end_s=duration,
            spans=spans,
            uncertain=uncertain,
            reason=reason,
            face_width=self.face_width,
            boxes=[
                replace(box, t=box.t - offset) for box in self.boxes if start_s <= box.t < end_s
            ],
            faces=[
                replace(face, t=face.t - offset) for face in self.faces if start_s <= face.t < end_s
            ],
        )


@dataclass
class WebcamReport:
    """Everything the detector found, and how it decided."""

    #: The report's own format. A saved report written by another version
    #: says nothing reliable about the current detector, so it is not reused.
    version: int = REPORT_VERSION
    #: The best region, if one was confident enough to use.
    track: WebcamTrack | None = None
    #: Every region considered, best first.
    candidates: list[WebcamCandidate] = field(default_factory=list)
    #: The sampling rate that was used, and why.
    sample_fps: float = BASE_SAMPLE_FPS
    sampling_reason: str = ""
    #: The shots the detector saw, and how many cuts that was.
    shots: int = 0
    cuts_per_minute: float = 0.0
    #: How many face observations were made.
    observations: int = 0
    #: Set when detection could not run at all.
    unavailable_reason: str = ""
    #: Set when the detection *failed* rather than finding nothing.
    #:
    #: "There is no webcam in this footage" is an answer, and a saved one is
    #: worth keeping. "The detector could not run" is not an answer: it is
    #: the absence of one, and it may well be over next time. The two are
    #: kept apart so that a failure is tried again and a negative is not.
    failed: bool = False
    #: The frame size the report was made against, in source pixels.
    source_width: int = 0
    source_height: int = 0
    #: The stretches of the source that were actually looked at, in the
    #: source's own clock. Empty when the whole source was used.
    windows: list[tuple[float, float]] = field(default_factory=list)

    @property
    def found(self) -> bool:
        return self.track is not None

    def to_dict(self) -> dict[str, Any]:
        return {
            "version": self.version,
            "found": self.found,
            "track": self.track.to_dict() if self.track else None,
            "candidates": [candidate.to_dict() for candidate in self.candidates],
            "sample_fps": round(self.sample_fps, 3),
            "sampling_reason": self.sampling_reason,
            "shots": self.shots,
            "cuts_per_minute": round(self.cuts_per_minute, 3),
            "observations": self.observations,
            "unavailable_reason": self.unavailable_reason,
            "failed": self.failed,
            "source_width": self.source_width,
            "source_height": self.source_height,
            "windows": [[round(low, 3), round(high, 3)] for low, high in self.windows],
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> WebcamReport:
        raw_track = data.get("track")
        raw_candidates = data.get("candidates")
        candidates = raw_candidates if isinstance(raw_candidates, list) else []
        raw_windows = data.get("windows")
        windows = [
            (float(item[0]), float(item[1]))
            for item in (raw_windows if isinstance(raw_windows, list) else [])
            if isinstance(item, (list, tuple)) and len(item) == 2
        ]
        return cls(
            version=int(data.get("version", 0)),
            track=WebcamTrack.from_dict(raw_track) if isinstance(raw_track, dict) else None,
            candidates=[
                WebcamCandidate.from_dict(item) for item in candidates if isinstance(item, dict)
            ],
            sample_fps=float(data.get("sample_fps", BASE_SAMPLE_FPS)),
            sampling_reason=str(data.get("sampling_reason", "")),
            shots=int(data.get("shots", 0)),
            cuts_per_minute=float(data.get("cuts_per_minute", 0.0)),
            observations=int(data.get("observations", 0)),
            unavailable_reason=str(data.get("unavailable_reason", "")),
            failed=bool(data.get("failed", False)),
            source_width=int(data.get("source_width", 0)),
            source_height=int(data.get("source_height", 0)),
            windows=windows,
        )

    def save(self, path: Path) -> None:
        """Write the report down, so the run record survives a restart."""
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(self.to_dict(), indent=2), encoding="utf-8")

    @classmethod
    def load(cls, path: Path) -> WebcamReport:
        """Read a report back. A missing or broken file is an empty report."""
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return cls(unavailable_reason="the saved report could not be read", failed=True)
        if not isinstance(data, dict):
            return cls(unavailable_reason="the saved report could not be read", failed=True)
        return cls.from_dict(data)


# --------------------------------------------------------------------------
# Adaptive sampling
# --------------------------------------------------------------------------


def adaptive_sample_fps(shots: list[Shot], duration_s: float) -> tuple[float, str]:
    """Choose a sampling rate from how fast the footage cuts.

    The old rule was a flat five frames a second. That is too sparse for a
    montage and wasteful for a static talking head. The rate here rises with
    the cut rate and is also lifted until every shot has been seen at least
    :data:`MIN_SAMPLES_PER_SHOT` times.

    Returns the rate and a sentence saying why, so the choice ends up in the
    run record instead of being invisible.
    """
    if duration_s <= 0:
        return BASE_SAMPLE_FPS, "the clip has no duration, so the base rate was used"

    cut_count = max(0, len(shots) - 1)
    cuts_per_minute = cut_count / duration_s * 60.0

    fps = BASE_SAMPLE_FPS
    reasons: list[str] = []

    if cuts_per_minute > CUTS_PER_MINUTE_FOR_DENSITY:
        # Fast-cut footage: sample harder, linearly up to the ceiling.
        excess = (cuts_per_minute - CUTS_PER_MINUTE_FOR_DENSITY) / CUTS_PER_MINUTE_FOR_DENSITY
        fps = BASE_SAMPLE_FPS + (MAX_SAMPLE_FPS - BASE_SAMPLE_FPS) * min(1.0, excess)
        reasons.append(
            f"{cut_count} cuts in {duration_s:.1f}s ({cuts_per_minute:.1f}/min) is fast-cut"
        )

    # Every shot deserves more than one look.
    needed = len(shots) * MIN_SAMPLES_PER_SHOT / duration_s
    if needed > fps:
        reasons.append(f"{len(shots)} shots need at least {MIN_SAMPLES_PER_SHOT} samples each")
        fps = needed

    fps = max(MIN_SAMPLE_FPS, min(MAX_SAMPLE_FPS, fps))
    if not reasons:
        reasons.append(
            f"{cut_count} cuts in {duration_s:.1f}s ({cuts_per_minute:.1f}/min) is calm footage"
        )
    return round(fps, 3), "; ".join(reasons)


# --------------------------------------------------------------------------
# Detection
# --------------------------------------------------------------------------


def _probe_duration(video: Path) -> float:
    """How long the video is, in seconds. Zero when it cannot be read."""
    from .. import ffmpeg

    try:
        return float(ffmpeg.probe(video).duration_s)
    except Exception as exc:  # noqa: BLE001 - an unreadable video is a report
        log.warning("Could not read the length of %s: %s", video.name, exc)
        return 0.0


def _probe_size(video: Path) -> tuple[int, int]:
    """The frame size of the video. Zeros when it cannot be read."""
    from .. import ffmpeg

    try:
        info = ffmpeg.probe(video)
    except Exception as exc:  # noqa: BLE001 - an unreadable video is a report
        log.warning("Could not read the frame size of %s: %s", video.name, exc)
        return (0, 0)
    return (info.width or 0, info.height or 0)


def detect_webcam(
    video: Path,
    *,
    start_s: float = 0.0,
    end_s: float | None = None,
    width: int = 0,
    height: int = 0,
    shots: list[Shot] | None = None,
    tile_px: int = FACE_TILE_PX,
    max_sample_fps: float = MAX_SAMPLE_FPS,
    windows: list[tuple[float, float]] | None = None,
) -> WebcamReport:
    """Find the webcam region in a piece of footage.

    The function never raises for a detection problem: an unreadable video,
    a missing model and a video with no faces all come back as a report that
    says the region was not found. The caller has a safe fallback for each.

    With no ``end_s`` the whole video is used, and its length and frame size
    are measured rather than assumed — so ``detect_webcam(path)`` works on
    its own.

    ``windows`` looks only at the stretches given, in the source's own
    clock. A source that is an hour long and a set of clips that use five
    minutes of it do not need the detector to walk the other fifty-five:
    the webcam is the same wherever it is found, and the boxes are measured
    where the clips actually are.

    The face is looked for in tiles rather than in the whole frame: a
    webcam overlay's face is small, and MediaPipe misses a small face in a
    large frame. The tiles make the detector's job the same size as the face
    it is looking for.
    """
    if windows:
        spans = [(float(low), float(high)) for low, high in windows if high > low]
        duration = sum(high - low for low, high in spans)
    else:
        if end_s is None:
            end_s = _probe_duration(video)
        duration = max(0.0, end_s - start_s)
        spans = [(start_s, end_s)]

    if duration <= 0:
        return WebcamReport(unavailable_reason="the clip has no duration")

    if not width or not height:
        probed_width, probed_height = _probe_size(video)
        width = width or probed_width
        height = height or probed_height

    if shots is None:
        shots = detect_shots(video, start_s=start_s, end_s=end_s, windows=windows)
    if not shots:
        shots = [Shot(0.0, duration)]

    sample_fps, reason = adaptive_sample_fps(shots, duration)
    if sample_fps > max_sample_fps:
        sample_fps = max_sample_fps
        reason = f"{reason}; capped at {max_sample_fps:.0f} frames a second"
    cut_count = max(0, len(shots) - 1)

    report = WebcamReport(
        sample_fps=sample_fps,
        sampling_reason=reason,
        shots=len(shots),
        cuts_per_minute=cut_count / duration * 60.0,
        source_width=width,
        source_height=height,
    )

    if not width or not height:
        report.unavailable_reason = "the frame size was not known"
        return report

    measured: list[WebcamBox] = []
    face_points: list[FacePoint] = []

    def _measure(t: float, frame, observations: list[FaceObservation]) -> None:
        """Measure the webcam's own frame, once per sampled picture."""
        if frame is None:
            return
        for observation in observations:
            face = Rect(
                x=observation.left,
                y=observation.top,
                width=observation.width,
                height=observation.height,
            )
            estimate = _estimate_box(frame, face, width=width, height=height)
            if estimate is None:
                continue
            measured.append(
                WebcamBox(
                    t=t,
                    rect=estimate.rect,
                    edges_found=estimate.edges_found,
                )
            )
            face_points.append(
                FacePoint(
                    t=t,
                    cx=observation.cx,
                    cy=observation.cy,
                    width=observation.width,
                )
            )

    try:
        observations = sample_faces(
            video,
            start_s=start_s,
            end_s=end_s,
            sample_fps=sample_fps,
            tile_px=tile_px,
            frame_sink=_measure,
            windows=windows,
        )
    except Exception as exc:  # noqa: BLE001 - a detector failure is a report, not a crash
        log.warning("Webcam detection could not run on %s: %s", video.name, exc)
        report.unavailable_reason = str(exc)
        # The detector could not look. That is not the same answer as "there
        # is no webcam here", and it must not be kept as one.
        report.failed = True
        return report

    report.observations = len(observations)
    if not observations:
        report.unavailable_reason = "no faces were found"
        return report

    candidates = _candidates(
        observations,
        shots=shots,
        width=width,
        height=height,
        duration_s=duration,
        sample_fps=sample_fps,
    )
    report.candidates = candidates

    if not candidates or candidates[0].confidence < MIN_CONFIDENCE:
        return report

    track = track_webcam(
        candidates[0],
        observations=observations,
        shots=shots,
        width=width,
        height=height,
        covered_s=duration,
    )
    track.boxes = _boxes_for(track.rect, measured)
    track.faces = _faces_for(track.rect, face_points)
    report.track = track
    return report


def _estimate_box(frame, face: Rect, *, width: int, height: int):
    """The webcam's own frame in one picture, or ``None``."""
    try:
        from .webcambox import estimate_cam_box
    except ImportError:  # pragma: no cover - the module is part of the package
        return None
    try:
        return estimate_cam_box(frame, face, source_width=width, source_height=height)
    except Exception as exc:  # noqa: BLE001 - a measurement failure is a fallback
        log.debug("Could not measure the webcam box: %s", exc)
        return None


def _boxes_for(region: Rect, measured: list[WebcamBox]) -> list[WebcamBox]:
    """The measured boxes that belong to this region."""
    return [box for box in measured if region.contains_point(box.rect.cx, box.rect.cy)]


def _faces_for(region: Rect, points: list[FacePoint]) -> list[FacePoint]:
    """The face measurements that belong to this region."""
    return [point for point in points if region.contains_point(point.cx, point.cy)]


def _median(values: list[float]) -> float:
    """The middle value, or zero when there is none."""
    if not values:
        return 0.0
    return float(statistics.median(values))


def _median_box(boxes: list[WebcamBox]) -> Rect:
    """The middle of the measured boxes.

    Each side is taken on its own, because a box that was measured badly
    on one side should not drag the other three with it.
    """
    return Rect(
        x=_median([box.rect.x for box in boxes]),
        y=_median([box.rect.y for box in boxes]),
        width=_median([box.rect.width for box in boxes]),
        height=_median([box.rect.height for box in boxes]),
    )


def _smooth(values: list[float], window: int = 5) -> list[float]:
    """A median filter over a window of neighbours.

    One bad measurement — a frame where the edge search found the wrong
    line — would otherwise be believed for as long as the clip lasts.
    """
    if window < 3 or len(values) < 3:
        return list(values)
    half = window // 2
    smoothed: list[float] = []
    for index in range(len(values)):
        low = max(0, index - half)
        high = min(len(values), index + half + 1)
        smoothed.append(_median(values[low:high]))
    return smoothed


def build_webcam_path(
    boxes: list[WebcamBox],
    *,
    source_width: int,
    source_height: int,
) -> WebcamPath | None:
    """The path of the webcam's own frame, from the measured boxes.

    ``None`` when no box was measured: the caller then uses the plain
    region, which is the face plus its headroom.
    """
    if not boxes:
        return None

    ordered = sorted(boxes, key=lambda box: box.t)
    times = [box.t for box in ordered]
    centres_x = _smooth([box.rect.cx for box in ordered])
    centres_y = _smooth([box.rect.cy for box in ordered])

    keyframes = _thin_keyframes(
        [
            WebcamKeyframe(t=t, cx=cx, cy=cy)
            for t, cx, cy in zip(times, centres_x, centres_y, strict=True)
        ]
    )

    size = _median_box(ordered)
    return WebcamPath(
        source_width=source_width,
        source_height=source_height,
        width=size.width,
        height=size.height,
        keyframes=keyframes,
    )


def _thin_keyframes(
    keyframes: list[WebcamKeyframe],
    *,
    limit: int = MAX_WEBCAM_PATH_KEYFRAMES,
) -> list[WebcamKeyframe]:
    """Reduce the path to at most ``limit`` keyframes.

    Keyframes whose position is within :data:`WEBCAM_PATH_EPSILON_PX` of the
    straight line between their neighbours are dropped first — they say
    nothing the neighbours do not already say. If that is not enough, the
    path is thinned uniformly. The endpoints are always kept, so the path
    still covers the whole clip.
    """
    if len(keyframes) <= 2:
        return list(keyframes)

    kept: list[WebcamKeyframe] = [keyframes[0]]
    for previous, current, following in zip(keyframes, keyframes[1:], keyframes[2:], strict=False):
        span = following.t - previous.t
        if span <= 0:
            continue
        ratio = (current.t - previous.t) / span
        predicted_x = previous.cx + (following.cx - previous.cx) * ratio
        predicted_y = previous.cy + (following.cy - previous.cy) * ratio
        if (
            abs(current.cx - predicted_x) > WEBCAM_PATH_EPSILON_PX
            or abs(current.cy - predicted_y) > WEBCAM_PATH_EPSILON_PX
        ):
            kept.append(current)
    kept.append(keyframes[-1])

    if len(kept) <= limit:
        return kept

    step = len(kept) / (limit - 1)
    thinned = [kept[min(len(kept) - 1, round(index * step))] for index in range(limit - 1)]
    thinned.append(kept[-1])

    deduped: list[WebcamKeyframe] = []
    for frame in thinned:
        if not deduped or frame.t > deduped[-1].t:
            deduped.append(frame)
    return deduped


def _clusters(observations: list[FaceObservation], radius: float) -> list[list[FaceObservation]]:
    """Group faces that sit in the same part of the frame.

    A webcam overlay puts the same face in the same place frame after frame,
    so position is the only thing that needs to cluster. Time is not used:
    a face that leaves and comes back is still the same region.
    """
    clusters: list[list[FaceObservation]] = []
    for observation in observations:
        placed = False
        for cluster in clusters:
            centre_x = statistics.fmean(o.cx for o in cluster)
            centre_y = statistics.fmean(o.cy for o in cluster)
            distance = ((observation.cx - centre_x) ** 2 + (observation.cy - centre_y) ** 2) ** 0.5
            if distance <= radius:
                cluster.append(observation)
                placed = True
                break
        if not placed:
            clusters.append([observation])

    # A cluster with a single observation is a glimpse, not a region.
    return [cluster for cluster in clusters if len(cluster) >= 2]


def _candidates(
    observations: list[FaceObservation],
    *,
    shots: list[Shot],
    width: int,
    height: int,
    duration_s: float,
    sample_fps: float,
) -> list[WebcamCandidate]:
    """Score every region the faces suggest, best first."""
    diagonal = (width**2 + height**2) ** 0.5
    radius = diagonal * CLUSTER_RADIUS_FRAC
    expected_samples = max(1.0, duration_s * sample_fps)

    candidates: list[WebcamCandidate] = []
    for cluster in _clusters(observations, radius):
        rect = estimate_webcam_rect(cluster, width=width, height=height)
        if rect is None:
            continue

        support = min(1.0, len(cluster) / expected_samples)
        stability = _stability(cluster, radius)
        cut_stability = _cut_stability(cluster, shots, radius)
        persistence = _persistence(cluster, shots)

        confidence = (
            WEIGHT_SUPPORT * support
            + WEIGHT_STABILITY * stability
            + WEIGHT_CUT_STABILITY * cut_stability
            + WEIGHT_PERSISTENCE * persistence
        )

        seen_shots = sorted({_shot_index(shots, o.t) for o in cluster})
        candidates.append(
            WebcamCandidate(
                rect=rect,
                confidence=round(confidence, 4),
                support=round(support, 4),
                stability=round(stability, 4),
                cut_stability=round(cut_stability, 4),
                persistence=round(persistence, 4),
                observations=len(cluster),
                face_width=round(statistics.median(o.width for o in cluster), 2),
                shots=seen_shots,
            )
        )

    candidates.sort(key=lambda c: c.confidence, reverse=True)
    return candidates


def _stability(cluster: list[FaceObservation], radius: float) -> float:
    """How little the face moves inside its own region."""
    centre_x = statistics.fmean(o.cx for o in cluster)
    centre_y = statistics.fmean(o.cy for o in cluster)
    spread = statistics.fmean(
        ((o.cx - centre_x) ** 2 + (o.cy - centre_y) ** 2) ** 0.5 for o in cluster
    )
    if radius <= 0:
        return 0.0
    return max(0.0, 1.0 - spread / radius)


def _cut_stability(cluster: list[FaceObservation], shots: list[Shot], radius: float) -> float:
    """How little the face moves when the gameplay cuts.

    This is the measure that separates an overlay from a person in the scene.
    An overlay does not move when the shot changes. A person does.
    """
    if len(shots) < 2 or radius <= 0:
        # Nothing to compare against. Claim nothing rather than claiming
        # stability that was never measured.
        return 0.5

    by_shot: dict[int, list[FaceObservation]] = {}
    for observation in cluster:
        by_shot.setdefault(_shot_index(shots, observation.t), []).append(observation)

    jumps: list[float] = []
    for index in sorted(by_shot):
        following = index + 1
        if following not in by_shot:
            continue
        before = by_shot[index]
        after = by_shot[following]
        last_x = statistics.fmean(o.cx for o in before[-3:])
        last_y = statistics.fmean(o.cy for o in before[-3:])
        first_x = statistics.fmean(o.cx for o in after[:3])
        first_y = statistics.fmean(o.cy for o in after[:3])
        jumps.append(((last_x - first_x) ** 2 + (last_y - first_y) ** 2) ** 0.5)

    if not jumps:
        return 0.5

    mean_jump = statistics.fmean(jumps)
    return max(0.0, 1.0 - min(1.0, mean_jump / radius))


def _persistence(cluster: list[FaceObservation], shots: list[Shot]) -> float:
    """How many separate shots the region survived."""
    if not shots:
        return 0.0
    seen = {_shot_index(shots, o.t) for o in cluster}
    return len(seen) / len(shots)


def _shot_index(shots: list[Shot], t: float) -> int:
    for index, shot in enumerate(shots):
        if shot.contains(t):
            return index
    return len(shots) - 1 if shots else 0


def estimate_webcam_rect(cluster: list[FaceObservation], *, width: int, height: int) -> Rect | None:
    """The region a face suggests, in source pixels.

    The face box is widened to include headroom and shoulders, because a
    webcam shows more than a face, and then clamped to the frame. The median
    is used rather than the mean so one bad detection cannot drag the region.
    """
    if not cluster:
        return None

    left = statistics.median(o.left for o in cluster)
    right = statistics.median(o.right for o in cluster)
    top = statistics.median(o.top for o in cluster)
    bottom = statistics.median(o.bottom for o in cluster)

    face_width = max(1.0, right - left)
    face_height = max(1.0, bottom - top)

    x = left - face_width * MARGIN_X
    y = top - face_height * MARGIN_TOP
    region_width = face_width * (1 + 2 * MARGIN_X)
    region_height = face_height * (1 + MARGIN_TOP + MARGIN_BOTTOM)

    x = max(0.0, x)
    y = max(0.0, y)
    region_width = min(region_width, width - x)
    region_height = min(region_height, height - y)

    if region_width <= 0 or region_height <= 0:
        return None
    if region_width * region_height < (width * height) * MIN_REGION_FRAC:
        return None

    return Rect(x=x, y=y, width=region_width, height=region_height)


# --------------------------------------------------------------------------
# Tracking
# --------------------------------------------------------------------------


def track_webcam(
    candidate: WebcamCandidate,
    *,
    observations: list[FaceObservation],
    shots: list[Shot],
    width: int,
    height: int,
    covered_s: float | None = None,
) -> WebcamTrack:
    """Follow a region across the clip, and say where it was not seen.

    The region itself does not move: an overlay stays where it is. What
    changes is whether a face is inside it. A stretch without a face is
    reported as a span with ``present=False`` rather than being quietly
    dropped, because "we could not see the webcam here" is a different fact
    from "there was no webcam here".

    ``covered_s`` is how much of the clip was actually looked at. It is
    the sum of the windows when the detector skipped the gaps between them,
    and it is what the "how much was missing" judgement is made against.
    """
    rect = candidate.rect
    duration = shots[-1].end_s if shots else 0.0
    looked_at = duration if covered_s is None else covered_s

    spans: list[WebcamSpan] = []
    for shot in shots:
        inside = [o for o in observations if shot.contains(o.t) and rect.contains_point(o.cx, o.cy)]
        if inside:
            spans.append(
                WebcamSpan(
                    start_s=shot.start_s,
                    end_s=shot.end_s,
                    present=True,
                    confidence=candidate.confidence,
                )
            )
        else:
            spans.append(
                WebcamSpan(
                    start_s=shot.start_s,
                    end_s=shot.end_s,
                    present=False,
                    confidence=0.0,
                    reason="no face was seen inside the region",
                )
            )

    missing = [span for span in spans if not span.present]
    missing_s = sum(span.duration_s for span in missing)
    uncertain = bool(missing)

    if not missing:
        reason = ""
    elif missing_s >= looked_at * 0.5:
        reason = "the region held a face for less than half the clip"
    else:
        reason = f"the region held no face for {missing_s:.1f}s"

    confidence = candidate.confidence
    if uncertain and looked_at > 0:
        confidence *= max(0.0, 1.0 - missing_s / looked_at)

    return WebcamTrack(
        rect=rect,
        confidence=round(confidence, 4),
        start_s=shots[0].start_s if shots else 0.0,
        end_s=duration,
        spans=spans,
        uncertain=uncertain,
        reason=reason,
        face_width=candidate.face_width,
    )
