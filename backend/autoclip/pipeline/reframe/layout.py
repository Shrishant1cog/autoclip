"""Choosing and placing the vertical streamer layout.

Four things decide what a clip looks like, and they are decided in this order:

1. **What the user asked for.** A manual layout is the answer, full stop. No
   automatic decision is consulted, and none is recorded as if it had been.
2. **Whether there is a webcam at all.** A region that was not found, or was
   found with low confidence, gets a plain gameplay crop. There is no
   half-detected webcam.
3. **What fits.** The face has to be readable in the output. A webcam too
   small to fill a strip without turning into a blur goes to a corner at a
   size that can be read, or it is left out.
4. **When the layout may change.** A layout that changes every half second is
   unwatchable, so a change may not happen within :data:`MIN_DWELL_S` of the
   last one.

The streamer preset puts the webcam in a strip above the gameplay, taking
about 40% of the height and the gameplay about 60%. That is a starting
preference, not a law: the planner will move the webcam to a corner, or leave
it out, when the geometry says the stacked version would cost more than it
gives.

Nothing here pauses the video. The speech timeline only changes how much room
the webcam is given, never how long the clip is.
"""

from __future__ import annotations

import logging
from dataclasses import asdict, dataclass, field, replace
from enum import StrEnum
from typing import Any

from .webcam import Rect, WebcamPath, WebcamSpan, WebcamTrack, build_webcam_path

log = logging.getLogger(__name__)

__all__ = [
    "LayoutConfig",
    "LayoutPath",
    "LayoutSegment",
    "LayoutSlot",
    "LayoutVariant",
    "ManualLayout",
    "apply_dwell",
    "plan_layout",
    "transition_frequency",
]


class LayoutVariant(StrEnum):
    """How the webcam and the gameplay sit together."""

    #: Gameplay only. The webcam was not found, or was not worth including.
    GAMEPLAY_ONLY = "gameplay_only"
    #: A webcam strip across the top, gameplay underneath. The preset.
    ABOVE = "above"
    #: The webcam in a corner, over the gameplay.
    CORNER = "corner"


#: The shortest time a layout may stay put before it is allowed to change.
#: A layout that changes every half second is unwatchable.
MIN_DWELL_S = 1.5

#: A face is never scaled up more than this. Past this the face is a blur,
#: and a blur is worse than a smaller webcam.
MAX_FACE_SCALE = 3.0

#: A face narrower than this in the output is not a face — it is a smudge.
#: This is the rule that decides whether a webcam can be used at all, and it
#: is measured in the pixels the viewer actually gets.
MIN_FACE_WIDTH_PX = 48

#: How much bigger the webcam gets while someone is speaking. The speech
#: timeline decides this; it never changes the length of the clip.
EMPHASIS_GAIN = 0.08

#: A webcam that fills less than this much of the strip's width is too
#: small to be worth a strip of its own. It goes to a corner instead,
#: where it sits over the gameplay rather than in a band of its own with
#: empty space either side of it.
MIN_STRIP_FILL_FRACTION = 0.5


def _even(value: float) -> int:
    """Round down to an even number of pixels, never below two."""
    number = int(value)
    if number % 2:
        number -= 1
    return max(2, number)


@dataclass(frozen=True)
class LayoutSlot:
    """Where a piece of the composition sits, in output pixels."""

    x: int
    y: int
    width: int
    height: int

    @property
    def aspect(self) -> float:
        return self.width / self.height if self.height else 0.0

    def to_dict(self) -> dict[str, int]:
        return dict(asdict(self))


@dataclass(frozen=True)
class ManualLayout:
    """What the user chose. It beats every automatic decision.

    ``rect`` is the webcam region in source pixels. Leaving it empty means
    "use the one that was detected".
    """

    variant: LayoutVariant = LayoutVariant.ABOVE
    rect: Rect | None = None
    #: How much of the output the webcam takes, as a fraction of its height
    #: for the stacked variant and of its width for the corner variant.
    scale: float | None = None
    #: Which corner, for the corner variant.
    position: str = "top-right"

    def to_dict(self) -> dict[str, Any]:
        return {
            "variant": self.variant.value,
            "rect": self.rect.to_dict() if self.rect else None,
            "scale": self.scale,
            "position": self.position,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> ManualLayout:
        raw_rect = data.get("rect")
        rect = Rect.from_dict(raw_rect) if isinstance(raw_rect, dict) else None
        try:
            variant = LayoutVariant(str(data.get("variant", LayoutVariant.ABOVE)))
        except ValueError:
            variant = LayoutVariant.ABOVE
        scale = data.get("scale")
        return cls(
            variant=variant,
            rect=rect,
            scale=float(scale) if isinstance(scale, (int, float)) else None,
            position=str(data.get("position", "top-right")),
        )


@dataclass
class LayoutConfig:
    """The knobs the planner uses. The defaults are the preset."""

    output_width: int = 1080
    output_height: int = 1920
    #: The webcam's share of the output height in the stacked variant. 0.40
    #: puts the webcam at 40% and the gameplay at 60%.
    webcam_height_frac: float = 0.40
    #: The webcam's share of the output width in the corner variant.
    corner_width_frac: float = 0.38
    #: The smallest a webcam may be before it is left out entirely.
    min_corner_width_px: int = 120
    #: How long a layout must hold before it may change.
    min_dwell_s: float = MIN_DWELL_S
    #: The narrowest a face may be in the output.
    min_face_width_px: int = MIN_FACE_WIDTH_PX
    #: The most a face may be scaled up.
    max_face_scale: float = MAX_FACE_SCALE
    #: How much bigger the webcam gets while someone is speaking.
    emphasis_gain: float = EMPHASIS_GAIN
    #: Below this confidence the webcam is not used at all.
    min_confidence: float = 0.35


@dataclass
class LayoutSegment:
    """One stretch of the clip with one layout."""

    start_s: float
    end_s: float
    variant: LayoutVariant
    #: Where the gameplay goes in the output.
    gameplay_slot: LayoutSlot
    #: Where the webcam is drawn, if there is one. This may be smaller than
    #: the strip it sits in, when the source cannot fill the strip.
    webcam_slot: LayoutSlot | None = None
    #: The band of the output reserved for the webcam. For the corner
    #: variant this is the same as ``webcam_slot``; for the stacked variant
    #: it is the full-width strip, so the renderer knows what to fill.
    webcam_strip: LayoutSlot | None = None
    #: Which part of the source the gameplay comes from.
    gameplay_source: Rect | None = None
    #: Which part of the source the webcam comes from.
    webcam_source: Rect | None = None
    #: The webcam's own region in the source, in source pixels. The gameplay
    #: crop is kept away from it, so the webcam is never shown twice.
    webcam_region: Rect | None = None
    #: Where the webcam's own frame was, over time. This is what makes the
    #: crop follow the box when the streamer changes the layout.
    webcam_path: WebcamPath | None = None
    #: The speech intervals inside this stretch, in clip-relative seconds.
    #: These come from the shared speech timeline — the same one the music
    #: ducking uses.
    speech_spans: list[tuple[float, float]] = field(default_factory=list)
    #: How much bigger the webcam is drawn while someone is speaking.
    emphasis_gain: float = EMPHASIS_GAIN
    #: Why this layout was chosen, in plain words.
    reason: str = ""

    @property
    def duration_s(self) -> float:
        return self.end_s - self.start_s

    @property
    def emphasised(self) -> bool:
        """True when someone was speaking during this stretch."""
        return bool(self.speech_spans)

    def emphasis_scale(self, t: float) -> float:
        """How much bigger the webcam is drawn at time ``t``.

        This is the only thing the speech timeline changes about a layout.
        The clip is never paused, and the gameplay never moves.
        """
        if self.webcam_slot is None:
            return 1.0
        for start, end in self.speech_spans:
            if start <= t < end:
                return 1.0 + self.emphasis_gain
        return 1.0

    def to_dict(self) -> dict[str, Any]:
        return {
            "start_s": round(self.start_s, 3),
            "end_s": round(self.end_s, 3),
            "variant": self.variant.value,
            "gameplay_slot": self.gameplay_slot.to_dict(),
            "webcam_slot": self.webcam_slot.to_dict() if self.webcam_slot else None,
            "webcam_strip": self.webcam_strip.to_dict() if self.webcam_strip else None,
            "gameplay_source": self.gameplay_source.to_dict() if self.gameplay_source else None,
            "webcam_source": self.webcam_source.to_dict() if self.webcam_source else None,
            "webcam_region": self.webcam_region.to_dict() if self.webcam_region else None,
            "webcam_path": self.webcam_path.to_dict() if self.webcam_path else None,
            "speech_spans": [[round(s, 3), round(e, 3)] for s, e in self.speech_spans],
            "emphasised": self.emphasised,
            "emphasis_gain": self.emphasis_gain,
            "reason": self.reason,
        }


@dataclass
class LayoutPath:
    """The full layout plan for one clip."""

    source_width: int
    source_height: int
    output_width: int
    output_height: int
    segments: list[LayoutSegment] = field(default_factory=list)
    #: True when the plan came from a manual choice.
    manual: bool = False
    #: The confidence of the webcam region this plan used.
    webcam_confidence: float = 0.0
    #: Why the plan looks the way it does.
    reason: str = ""

    @property
    def duration_s(self) -> float:
        return self.segments[-1].end_s if self.segments else 0.0

    @property
    def has_webcam(self) -> bool:
        return any(segment.variant is not LayoutVariant.GAMEPLAY_ONLY for segment in self.segments)

    def to_dict(self) -> dict[str, Any]:
        return {
            "source_width": self.source_width,
            "source_height": self.source_height,
            "output_width": self.output_width,
            "output_height": self.output_height,
            "manual": self.manual,
            "webcam_confidence": round(self.webcam_confidence, 4),
            "reason": self.reason,
            "segments": [segment.to_dict() for segment in self.segments],
        }


@dataclass(frozen=True)
class _Placement:
    """The geometry of one arrangement of webcam and gameplay."""

    variant: LayoutVariant
    gameplay_slot: LayoutSlot
    gameplay_source: Rect
    source_width: int
    source_height: int
    #: The webcam region in source pixels, so a gameplay-only stretch can
    #: still crop around it.
    webcam_region: Rect | None = None
    webcam_slot: LayoutSlot | None = None
    webcam_strip: LayoutSlot | None = None
    webcam_source: Rect | None = None


# --------------------------------------------------------------------------
# Geometry
# --------------------------------------------------------------------------


def _overlaps(a: Rect, b: Rect) -> bool:
    return a.intersection_area(b) > 0.0


def _crop_for_slot(
    source_w: int,
    source_h: int,
    slot_w: int,
    slot_h: int,
    *,
    avoid: Rect | None = None,
) -> Rect | None:
    """The piece of the source that fills a slot.

    The crop is as large as the source allows at the slot's aspect ratio, so
    nothing is scaled up unnecessarily. When a webcam region must be avoided,
    the window slides to the nearest position that does not overlap it; if no
    such position exists, there is no crop and the caller falls back.
    """
    if slot_w <= 0 or slot_h <= 0 or source_w <= 0 or source_h <= 0:
        return None

    target = slot_w / slot_h
    source_ratio = source_w / source_h

    if source_ratio >= target:
        crop_h = source_h
        crop_w = round(source_h * target)
    else:
        crop_w = source_w
        crop_h = round(source_w / target)

    crop_w = min(source_w, _even(crop_w))
    crop_h = min(source_h, _even(crop_h))
    if crop_w <= 0 or crop_h <= 0:
        return None

    max_x = source_w - crop_w
    centre = max_x / 2

    if avoid is None or avoid.area <= 0:
        return Rect(x=centre, y=(source_h - crop_h) / 2, width=crop_w, height=crop_h)

    candidates = [
        x for x in (centre, 0.0, float(max_x)) if not _overlaps(Rect(x, 0.0, crop_w, crop_h), avoid)
    ]
    if candidates:
        # The one closest to the middle of the frame, so the crop stays fair
        # to both sides of the gameplay.
        best = min(candidates, key=lambda x: abs(x - centre))
        return Rect(x=best, y=(source_h - crop_h) / 2, width=crop_w, height=crop_h)

    # No standard position works. Slide the window as far as it will go.
    slid = _slide_away(source_w, crop_w, avoid)
    if slid is None:
        return None
    return Rect(x=slid, y=(source_h - crop_h) / 2, width=crop_w, height=crop_h)


def _slide_away(source_w: int, crop_w: int, avoid: Rect) -> float | None:
    """Find an x where a crop of ``crop_w`` does not overlap ``avoid``."""
    max_x = source_w - crop_w
    if max_x < 0:
        return None

    # The window goes entirely to one side of the region.
    right_of = avoid.right
    left_of = avoid.x - crop_w

    options = [x for x in (right_of, left_of) if 0 <= x <= max_x]
    if not options:
        return None

    # Prefer the side that keeps more of the frame's centre in view.
    centre = max_x / 2
    return min(options, key=lambda x: abs(x - centre))


def _stack_slots(out_w: int, out_h: int, webcam_frac: float) -> tuple[LayoutSlot, LayoutSlot]:
    """The webcam strip and the gameplay area below it.

    The webcam takes ``webcam_frac`` of the height and the gameplay the rest.
    That is the 40/60 preset: a preference, not a rule, because the caller
    can ask for a different fraction.
    """
    frac = min(max(webcam_frac, 0.0), 0.85)

    cam_h = _even(out_h * frac)
    gameplay_h = _even(out_h - cam_h)

    return (
        LayoutSlot(x=0, y=0, width=out_w, height=cam_h),
        LayoutSlot(x=0, y=cam_h, width=out_w, height=gameplay_h),
    )


def _source_rect_for_slot(slot: LayoutSlot, source: Rect) -> Rect:
    """The piece of the source that fills a slot, keeping the slot's aspect."""
    target = slot.aspect
    if target <= 0:
        return source

    crop_w: float
    crop_h: float
    if source.width / source.height >= target:
        crop_h = source.height
        crop_w = round(source.height * target)
    else:
        crop_w = source.width
        crop_h = round(source.width / target)

    crop_w = min(source.width, _even(crop_w))
    crop_h = min(source.height, _even(crop_h))
    if crop_w <= 0 or crop_h <= 0:
        return source
    return Rect(
        x=source.x + (source.width - crop_w) / 2,
        y=source.y + (source.height - crop_h) / 2,
        width=crop_w,
        height=crop_h,
    )


def _webcam_crop(slot: LayoutSlot, region: Rect, face_width: float) -> tuple[Rect, float] | None:
    """The piece of the webcam region that fills a slot, and the scale.

    ``None`` when the region cannot fill the slot without clipping the face.
    """
    source = _source_rect_for_slot(slot, region)
    if source.width <= 0 or source.height <= 0:
        return None
    if face_width > 0 and source.width < face_width:
        # The crop would cut the face in half.
        return None
    scale = slot.width / source.width
    return source, scale


def _corner_slot(
    out_w: int,
    out_h: int,
    webcam: Rect,
    *,
    position: str,
    width_frac: float,
    face_width: float,
    config: LayoutConfig,
    require_legible: bool,
) -> LayoutSlot | None:
    """A webcam in a corner, at the largest size the source can actually fill.

    The slot matches the region's own shape, so the face is not stretched.
    The slot shrinks until the face is not scaled up past the limit — past
    that the face is a blur, and a blur is worse than a smaller webcam.
    """
    if webcam.width <= 0 or webcam.height <= 0:
        return None

    slot_w = _even(out_w * min(max(width_frac, 0.05), 1.0))
    if slot_w / webcam.width > config.max_face_scale:
        slot_w = _even(webcam.width * config.max_face_scale)
    if slot_w < 2:
        return None

    slot_h = _even(slot_w * webcam.height / webcam.width)
    if slot_h < 2:
        return None

    if require_legible:
        source = _source_rect_for_slot(LayoutSlot(0, 0, slot_w, slot_h), webcam)
        scale = slot_w / source.width if source.width > 0 else 0.0
        # A face that is too narrow to read is not worth putting on screen.
        if face_width * scale < config.min_face_width_px:
            return None
        if slot_w < config.min_corner_width_px:
            return None

    margin = max(8, round(out_w * 0.03))
    x = margin
    y = margin
    if "right" in position:
        x = out_w - slot_w - margin
    if "bottom" in position:
        y = out_h - slot_h - margin

    if x < 0 or y < 0 or x + slot_w > out_w or y + slot_h > out_h:
        return None
    return LayoutSlot(x=x, y=y, width=slot_w, height=slot_h)


# --------------------------------------------------------------------------
# Placements
# --------------------------------------------------------------------------


def _fit_in_strip(
    strip: LayoutSlot,
    region: Rect,
    *,
    max_face_scale: float,
) -> tuple[int, int] | None:
    """The largest piece of the webcam that fits inside the strip.

    The webcam keeps its own shape — a streamer is not squashed — and it is
    never scaled up so far that the face turns into a blur. The result is
    therefore bounded twice: by the strip it has to fit in, and by how much
    the face may be blown up.

    ``None`` when the region cannot fill even a small part of the strip.
    """
    if region.width <= 0 or region.height <= 0:
        return None

    scale = min(
        max_face_scale,
        strip.width / region.width,
        strip.height / region.height,
    )
    width = _even(region.width * scale)
    height = _even(region.height * scale)
    if width <= 0 or height <= 0:
        return None
    if width > strip.width or height > strip.height:
        return None
    return width, height


def _stacked_placement(
    region: Rect,
    face_width: float,
    source_width: int,
    source_height: int,
    config: LayoutConfig,
    *,
    webcam_frac: float | None = None,
    allow_partial: bool = False,
    min_fill_fraction: float = 0.0,
) -> _Placement | None:
    """The webcam strip above the gameplay, if the geometry allows it.

    With ``allow_partial`` the webcam may be smaller than the strip it sits
    in — the strip is then filled around it. That is the manual path: the
    user asked for the strip, so the strip is what they get, and the face is
    never blown up past the limit to fill it.

    ``min_fill_fraction`` is the share of the strip's width the webcam has
    to reach to be worth a strip of its own. Below it the caller falls back
    to a corner.
    """
    frac = config.webcam_height_frac if webcam_frac is None else webcam_frac
    strip, gameplay_slot = _stack_slots(config.output_width, config.output_height, frac)

    gameplay_source = _crop_for_slot(
        source_width,
        source_height,
        gameplay_slot.width,
        gameplay_slot.height,
        avoid=region,
    )
    if gameplay_source is None:
        # The gameplay crop cannot avoid the webcam. That is not fatal: the
        # webcam is drawn over the top, and the gameplay keeps the frame.
        gameplay_source = _crop_for_slot(
            source_width,
            source_height,
            gameplay_slot.width,
            gameplay_slot.height,
        )
    if gameplay_source is None:
        return None

    cropped = _webcam_crop(strip, region, face_width)
    if cropped is None:
        return None
    webcam_source, scale = cropped

    if scale <= config.max_face_scale:
        webcam_slot = strip
    elif allow_partial:
        fitted = _fit_in_strip(strip, region, max_face_scale=config.max_face_scale)
        if fitted is None:
            return None
        width, height = fitted
        if width < strip.width * min_fill_fraction:
            # The webcam would sit in the strip like a postage stamp.
            return None
        webcam_slot = LayoutSlot(
            x=max(0, (strip.width - width) // 2),
            y=max(0, (strip.height - height) // 2),
            width=width,
            height=height,
        )
        webcam_source = _source_rect_for_slot(webcam_slot, region)
    else:
        return None

    return _Placement(
        variant=LayoutVariant.ABOVE,
        gameplay_slot=gameplay_slot,
        gameplay_source=gameplay_source,
        source_width=source_width,
        source_height=source_height,
        webcam_region=region,
        webcam_slot=webcam_slot,
        webcam_strip=strip,
        webcam_source=webcam_source,
    )


def _corner_placement(
    region: Rect,
    face_width: float,
    source_width: int,
    source_height: int,
    config: LayoutConfig,
    *,
    position: str = "top-right",
    width_frac: float | None = None,
    require_legible: bool = True,
) -> _Placement | None:
    """The webcam in a corner, at a size the source can actually fill."""
    slot = _corner_slot(
        config.output_width,
        config.output_height,
        region,
        position=position,
        width_frac=config.corner_width_frac if width_frac is None else width_frac,
        face_width=face_width,
        config=config,
        require_legible=require_legible,
    )
    if slot is None:
        return None

    gameplay_slot = LayoutSlot(x=0, y=0, width=config.output_width, height=config.output_height)
    gameplay_source = _crop_for_slot(
        source_width,
        source_height,
        gameplay_slot.width,
        gameplay_slot.height,
    )
    if gameplay_source is None:
        return None

    return _Placement(
        variant=LayoutVariant.CORNER,
        gameplay_slot=gameplay_slot,
        gameplay_source=gameplay_source,
        source_width=source_width,
        source_height=source_height,
        webcam_region=region,
        webcam_slot=slot,
        webcam_strip=slot,
        webcam_source=_source_rect_for_slot(slot, region),
    )


def _gameplay_only(
    duration_s: float,
    source_width: int,
    source_height: int,
    out_w: int,
    out_h: int,
) -> list[LayoutSegment]:
    """A plain crop, with no webcam anywhere."""
    source = _crop_for_slot(source_width, source_height, out_w, out_h)
    if source is None:
        source = Rect(x=0, y=0, width=source_width, height=source_height)
    return [
        LayoutSegment(
            start_s=0.0,
            end_s=max(duration_s, 0.0),
            variant=LayoutVariant.GAMEPLAY_ONLY,
            gameplay_slot=LayoutSlot(x=0, y=0, width=out_w, height=out_h),
            gameplay_source=source,
            reason="No webcam was used.",
        )
    ]


# --------------------------------------------------------------------------
# Planning
# --------------------------------------------------------------------------


def plan_layout(
    *,
    source_width: int,
    source_height: int,
    config: LayoutConfig | None = None,
    webcam: WebcamTrack | None = None,
    manual: ManualLayout | None = None,
    #: The shared speech timeline, in clip-relative seconds. Used for
    #: emphasis only — it never changes the length of the clip.
    speech_spans: list[tuple[float, float]] | None = None,
    duration_s: float = 0.0,
) -> LayoutPath:
    """Plan the composition for one clip.

    The order is deliberate: a manual choice first, then the webcam, then the
    geometry, then the timing. Nothing later in the list can overrule
    something earlier in it.
    """
    config = config or LayoutConfig()
    out_w, out_h = config.output_width, config.output_height
    spans = list(speech_spans or [])

    path = LayoutPath(
        source_width=source_width,
        source_height=source_height,
        output_width=out_w,
        output_height=out_h,
    )

    if manual is not None:
        path.manual = True
        path.reason = "You chose this layout."
        path.webcam_confidence = webcam.confidence if webcam is not None else 0.0
        path.segments = _manual_segments(
            manual,
            source_width=source_width,
            source_height=source_height,
            config=config,
            webcam=webcam,
            speech_spans=spans,
            duration_s=duration_s,
        )
        return path

    if webcam is None or webcam.rect is None:
        path.reason = "No webcam was found, so the clip is gameplay only."
        path.segments = _gameplay_only(duration_s, source_width, source_height, out_w, out_h)
        return path

    region = webcam.rect
    confidence = webcam.confidence
    if confidence < config.min_confidence:
        path.reason = (
            f"The webcam was found with only {confidence:.0%} confidence, "
            "so the clip is gameplay only."
        )
        path.segments = _gameplay_only(duration_s, source_width, source_height, out_w, out_h)
        return path

    path.webcam_confidence = confidence
    face_width = webcam.face_width

    # The region that is shown is the webcam's own frame when it was seen
    # in the picture, and the region around the face when it was not.
    region = webcam.region

    placement = _stacked_placement(
        region,
        face_width,
        source_width,
        source_height,
        config,
        allow_partial=True,
        min_fill_fraction=MIN_STRIP_FILL_FRACTION,
    )
    if placement is not None:
        path.reason = (
            "The webcam is above the gameplay, taking "
            f"{config.webcam_height_frac:.0%} of the height."
        )
    else:
        placement = _corner_placement(region, face_width, source_width, source_height, config)
        if placement is not None:
            path.reason = (
                "The webcam is in the corner at a size you can read, because it would "
                "have been too small to fill a strip without turning into a blur."
            )

    if placement is None:
        path.reason = (
            "The webcam was too small to lay out without blurring it, so the clip is gameplay only."
        )
        path.segments = _gameplay_only(duration_s, source_width, source_height, out_w, out_h)
        return path

    path.segments = _segments_from_spans(
        webcam.spans,
        placement=placement,
        duration_s=duration_s,
        speech_spans=spans,
        config=config,
        reason=path.reason,
        webcam_path=_webcam_path(webcam, source_width, source_height),
    )
    path.segments = apply_dwell(path.segments, min_dwell_s=config.min_dwell_s)
    return path


def _webcam_path(
    webcam: WebcamTrack,
    source_width: int,
    source_height: int,
) -> WebcamPath | None:
    """The path of the webcam's own frame, when it was measured."""
    return build_webcam_path(
        webcam.boxes,
        source_width=source_width,
        source_height=source_height,
    )


def _segments_from_spans(
    spans: list[WebcamSpan],
    *,
    placement: _Placement,
    duration_s: float,
    speech_spans: list[tuple[float, float]],
    config: LayoutConfig,
    reason: str,
    webcam_path: WebcamPath | None = None,
) -> list[LayoutSegment]:
    """One segment per stretch, according to whether the webcam was seen.

    "We could not see the webcam here" is not "there was no webcam here", so
    a stretch without a face falls back to gameplay only rather than being
    quietly dropped.
    """
    usable = list(spans)
    if not usable:
        usable = [WebcamSpan(0.0, duration_s, True, 0.0)]

    segments: list[LayoutSegment] = []
    for span in usable:
        start = max(0.0, span.start_s)
        end = span.end_s
        if duration_s > 0:
            end = min(end, duration_s)
        if end <= start:
            continue

        if span.present:
            segments.append(
                _segment(
                    start,
                    end,
                    placement,
                    speech_spans=speech_spans,
                    config=config,
                    reason=reason,
                    webcam_path=webcam_path,
                )
            )
        else:
            segments.append(
                _gameplay_segment(
                    start,
                    end,
                    placement=placement,
                    reason=span.reason or "The webcam was not visible here.",
                )
            )

    if not segments:
        # Nothing was visible at all. The gameplay fills the frame.
        source = _crop_for_slot(
            placement.source_width,
            placement.source_height,
            config.output_width,
            config.output_height,
        )
        segments = [
            LayoutSegment(
                start_s=0.0,
                end_s=max(duration_s, 0.0),
                variant=LayoutVariant.GAMEPLAY_ONLY,
                gameplay_slot=LayoutSlot(
                    x=0,
                    y=0,
                    width=config.output_width,
                    height=config.output_height,
                ),
                gameplay_source=source,
                reason="The webcam was not visible anywhere in this clip.",
            )
        ]
    return segments


def _segment(
    start_s: float,
    end_s: float,
    placement: _Placement,
    *,
    speech_spans: list[tuple[float, float]],
    config: LayoutConfig,
    reason: str,
    webcam_path: WebcamPath | None = None,
) -> LayoutSegment:
    """A stretch with the webcam in it."""
    return LayoutSegment(
        start_s=start_s,
        end_s=end_s,
        variant=placement.variant,
        gameplay_slot=placement.gameplay_slot,
        webcam_slot=placement.webcam_slot,
        webcam_strip=placement.webcam_strip,
        gameplay_source=placement.gameplay_source,
        webcam_source=placement.webcam_source,
        webcam_region=placement.webcam_region,
        webcam_path=webcam_path,
        speech_spans=_clip_spans(speech_spans, start_s, end_s),
        emphasis_gain=config.emphasis_gain,
        reason=reason,
    )


def _gameplay_segment(
    start_s: float,
    end_s: float,
    *,
    placement: _Placement,
    reason: str,
) -> LayoutSegment:
    """A stretch without the webcam: the gameplay fills the whole frame.

    The crop is recomputed here, because the gameplay area of a stacked
    layout is only sixty per cent of the frame. When the webcam is not on
    screen there is no reason to leave the top of the frame empty.
    """
    out_w = placement.gameplay_slot.width
    out_h = placement.gameplay_slot.height
    source = _crop_for_slot(
        placement.source_width,
        placement.source_height,
        out_w,
        out_h,
        avoid=placement.webcam_region,
    )
    if source is None:
        source = _crop_for_slot(
            placement.source_width,
            placement.source_height,
            out_w,
            out_h,
        )
    if source is None:
        source = Rect(x=0, y=0, width=placement.source_width, height=placement.source_height)

    return LayoutSegment(
        start_s=start_s,
        end_s=end_s,
        variant=LayoutVariant.GAMEPLAY_ONLY,
        gameplay_slot=LayoutSlot(x=0, y=0, width=out_w, height=out_h),
        gameplay_source=source,
        reason=reason,
    )


def _clip_spans(
    spans: list[tuple[float, float]], start_s: float, end_s: float
) -> list[tuple[float, float]]:
    """The speech intervals that fall inside a stretch."""
    clipped: list[tuple[float, float]] = []
    for start, end in spans:
        if end <= start_s or start >= end_s:
            continue
        clipped.append((max(start, start_s), min(end, end_s)))
    return clipped


def _manual_segments(
    manual: ManualLayout,
    *,
    source_width: int,
    source_height: int,
    config: LayoutConfig,
    webcam: WebcamTrack | None,
    speech_spans: list[tuple[float, float]],
    duration_s: float,
) -> list[LayoutSegment]:
    """Build the plan the user asked for, and nothing else."""
    out_w, out_h = config.output_width, config.output_height
    region = manual.rect or (webcam.rect if webcam is not None else None)

    if manual.variant is LayoutVariant.GAMEPLAY_ONLY or region is None:
        return _gameplay_only(duration_s, source_width, source_height, out_w, out_h)

    face_width = webcam.face_width if webcam is not None else 0.0
    webcam_path = _webcam_path(webcam, source_width, source_height) if webcam is not None else None

    if manual.variant is LayoutVariant.CORNER:
        placement = _corner_placement(
            region,
            face_width,
            source_width,
            source_height,
            config,
            position=manual.position,
            width_frac=manual.scale,
            require_legible=False,
        )
    else:
        placement = _stacked_placement(
            region,
            face_width,
            source_width,
            source_height,
            config,
            webcam_frac=manual.scale,
            allow_partial=True,
        )

    if placement is None:
        return _gameplay_only(duration_s, source_width, source_height, out_w, out_h)

    return [
        _segment(
            0.0,
            max(duration_s, 0.0),
            placement,
            speech_spans=speech_spans,
            config=config,
            reason="You chose this layout.",
            webcam_path=webcam_path,
        )
    ]


# --------------------------------------------------------------------------
# Dwell
# --------------------------------------------------------------------------


def apply_dwell(
    segments: list[LayoutSegment], *, min_dwell_s: float = MIN_DWELL_S
) -> list[LayoutSegment]:
    """Hold a layout until it has been held long enough to change.

    A change that comes too soon is pushed back to the earliest moment it is
    allowed. Nothing is ever cut short: the clip's start and end do not move.
    The input is not modified.
    """
    if not segments:
        return []

    ordered = sorted(segments, key=lambda segment: segment.start_s)
    result = [replace(ordered[0])]
    last_change = ordered[0].start_s

    for segment in ordered[1:]:
        previous = result[-1]
        if segment.variant == previous.variant:
            result[-1] = replace(previous, end_s=segment.end_s)
            continue

        earliest = last_change + min_dwell_s
        if segment.start_s < earliest:
            # Too soon. Hold the old layout until it is allowed to change.
            hold_until = min(earliest, segment.end_s)
            result[-1] = replace(previous, end_s=max(previous.end_s, hold_until))
            if earliest >= segment.end_s:
                continue
            result.append(replace(segment, start_s=earliest))
            last_change = earliest
        else:
            result.append(replace(segment))
            last_change = segment.start_s

    return result


def transition_frequency(segments: list[LayoutSegment]) -> float:
    """How many layout changes happen per minute.

    This is measured, never capped. The number is a diagnostic: it says how
    often the layout moved, so an unwatchable clip is visible as a number
    rather than as an opinion.
    """
    if len(segments) < 2:
        return 0.0
    duration = segments[-1].end_s - segments[0].start_s
    if duration <= 0:
        return 0.0
    changes = 0
    for previous, current in zip(segments, segments[1:], strict=False):
        if current.variant is not previous.variant:
            changes += 1
    return changes / duration * 60.0
