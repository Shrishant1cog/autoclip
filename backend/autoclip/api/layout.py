"""Webcam layouts: what was detected, and what the user chose.

This is the Settings screen's layout section, plus the endpoint that re-runs
detection on demand. It answers three questions:

1. *Was a webcam found?* — the region, its confidence, and the reason.
2. *What does the planner do with it?* — the variants on offer, and which
   one is in force.
3. *Can the user change it?* — yes, and the choice survives a re-render.

Nothing here identifies anybody. The rectangle is a region of pixels and the
confidence is a number; there is no face template and no name.
"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Any

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from ..db import store
from ..pipeline.reframe import layout_store
from ..pipeline.reframe.layout import LayoutVariant
from ..pipeline.reframe.webcam import detect_webcam

log = logging.getLogger(__name__)

router = APIRouter(prefix="/api/layout", tags=["layout"])

#: The layouts a user can pick.
VARIANTS = tuple(variant.value for variant in LayoutVariant)

#: The corners the webcam can sit in.
POSITIONS = ("top-left", "top-right", "bottom-left", "bottom-right")


class LayoutOverrideIn(BaseModel):
    """The user's own choice for one source."""

    source_id: str = Field(min_length=1, max_length=64)
    #: Empty means "no override" — the automatic planner decides.
    variant: str = ""
    rect_x: float = 0.0
    rect_y: float = 0.0
    rect_width: float = 0.0
    rect_height: float = 0.0
    position: str = ""
    scale: float = 0.0


class LayoutOut(BaseModel):
    """Everything known about one source's layout."""

    source_id: str
    #: What the detector found.
    detected: bool = False
    detected_x: float = 0.0
    detected_y: float = 0.0
    detected_width: float = 0.0
    detected_height: float = 0.0
    detected_confidence: float = 0.0
    detected_face_width: float = 0.0
    detected_reason: str = ""
    detected_at: str = ""
    #: The user's own choice.
    variant: str = ""
    rect_x: float = 0.0
    rect_y: float = 0.0
    rect_width: float = 0.0
    rect_height: float = 0.0
    position: str = ""
    scale: float = 0.0
    updated_at: str = ""


class DetectOut(BaseModel):
    """The result of a detection run."""

    source_id: str
    found: bool
    confidence: float = 0.0
    rect: dict[str, float] = Field(default_factory=dict)
    reason: str = ""
    sample_fps: float = 0.0
    sampling_reason: str = ""
    shots: int = 0
    cuts_per_minute: float = 0.0
    observations: int = 0


def _source_or_404(source_id: str):
    source = store.get_source(source_id)
    if source is None:
        raise HTTPException(404, f"No source with id {source_id!r}.")
    return source


def _layout_out(source_id: str) -> LayoutOut:
    stored = layout_store.get_source_layout(source_id)
    if stored is None:
        return LayoutOut(source_id=source_id)

    return LayoutOut(
        source_id=source_id,
        detected=stored.has_detection,
        detected_x=stored.detected_x,
        detected_y=stored.detected_y,
        detected_width=stored.detected_width,
        detected_height=stored.detected_height,
        detected_confidence=stored.detected_confidence,
        detected_face_width=stored.detected_face_width,
        detected_reason=stored.detected_reason,
        detected_at=stored.detected_at,
        variant=stored.variant,
        rect_x=stored.rect_x,
        rect_y=stored.rect_y,
        rect_width=stored.rect_width,
        rect_height=stored.rect_height,
        position=stored.position,
        scale=stored.scale,
        updated_at=stored.updated_at,
    )


@router.get("/sources", response_model=list[LayoutOut])
async def list_layouts() -> list[LayoutOut]:
    """Every source that has a layout record."""
    from ..db import connection

    try:
        with connection() as conn:
            rows = conn.execute(
                "SELECT source_id FROM source_layouts ORDER BY updated_at DESC"
            ).fetchall()
    except Exception:  # noqa: BLE001 - an unmigrated database has no table yet
        return []
    return [_layout_out(str(row["source_id"])) for row in rows]


@router.get("/sources/{source_id}", response_model=LayoutOut)
async def get_layout(source_id: str) -> LayoutOut:
    """What is known about one source's layout."""
    _source_or_404(source_id)
    return _layout_out(source_id)


@router.put("/sources/{source_id}", response_model=LayoutOut)
async def put_layout(source_id: str, payload: LayoutOverrideIn) -> LayoutOut:
    """Save the user's own choice for a source.

    An empty variant clears the override and hands the decision back to the
    automatic planner. A manual layout always wins over the automatic one,
    so it is stored rather than merged with what the detector found.
    """
    _source_or_404(source_id)

    if payload.source_id and payload.source_id != source_id:
        raise HTTPException(400, "The source id in the body does not match the path.")

    variant = payload.variant.strip()
    if variant and variant not in VARIANTS:
        raise HTTPException(
            400,
            f"Unknown layout {variant!r}. Use one of: {', '.join(VARIANTS)}.",
        )

    position = payload.position.strip()
    if position and position not in POSITIONS:
        raise HTTPException(
            400,
            f"Unknown position {position!r}. Use one of: {', '.join(POSITIONS)}.",
        )

    if payload.rect_width < 0 or payload.rect_height < 0:
        raise HTTPException(400, "A rectangle cannot have a negative size.")

    if not variant:
        layout_store.clear_layout_override(source_id)
        return _layout_out(source_id)

    layout_store.set_layout_override(
        source_id,
        variant=variant,
        rect_x=payload.rect_x,
        rect_y=payload.rect_y,
        rect_width=payload.rect_width,
        rect_height=payload.rect_height,
        position=position,
        scale=payload.scale,
    )
    return _layout_out(source_id)


@router.delete("/sources/{source_id}", response_model=LayoutOut)
async def delete_layout(source_id: str) -> LayoutOut:
    """Forget the user's choice, so the automatic planner decides again.

    What was detected is kept: the user changed their mind about the
    layout, not about the video.
    """
    _source_or_404(source_id)
    layout_store.clear_layout_override(source_id)
    return _layout_out(source_id)


@router.post("/sources/{source_id}/detect", response_model=DetectOut)
async def detect(source_id: str) -> DetectOut:
    """Look for a webcam in the source again.

    Detection normally runs as part of the pipeline. This endpoint is for
    when the user wants to see it before the job runs, or wants to look
    again after changing something.
    """
    source = _source_or_404(source_id)
    path = Path(source.path or "")
    if not source.has_video or not path.is_file():
        raise HTTPException(400, "This source has no video file to look at.")

    from ..pipeline import ffmpeg

    info = ffmpeg.probe(path)
    if not info.has_video or not info.width or not info.height:
        raise HTTPException(400, "This source has no video stream to look at.")

    report = detect_webcam(path, width=info.width, height=info.height)

    reason = report.unavailable_reason
    confidence = 0.0
    rect: dict[str, float] = {}
    if report.track is not None:
        rect = report.track.rect.to_dict()
        confidence = report.track.confidence
        reason = report.track.reason or report.sampling_reason
        try:
            layout_store.record_detection(
                source_id,
                rect=rect,
                confidence=confidence,
                face_width=report.track.face_width,
                reason=reason,
            )
        except Exception as exc:  # noqa: BLE001 - a record is not worth failing over
            log.warning("Could not record the webcam detection: %s", exc)
    else:
        try:
            layout_store.record_detection(
                source_id,
                rect=None,
                confidence=0.0,
                face_width=0.0,
                reason=reason,
            )
        except Exception as exc:  # noqa: BLE001
            log.warning("Could not record the webcam detection: %s", exc)

    return DetectOut(
        source_id=source_id,
        found=report.track is not None,
        confidence=confidence,
        rect=rect,
        reason=reason,
        sample_fps=report.sample_fps,
        sampling_reason=report.sampling_reason,
        shots=report.shots,
        cuts_per_minute=report.cuts_per_minute,
        observations=report.observations,
    )


@router.get("/variants")
async def list_variants() -> dict[str, Any]:
    """The layouts on offer, and what each one means."""
    return {
        "variants": [
            {
                "value": LayoutVariant.GAMEPLAY_ONLY.value,
                "title": "Gameplay only",
                "description": "No webcam is shown. The gameplay fills the frame.",
            },
            {
                "value": LayoutVariant.ABOVE.value,
                "title": "Webcam above",
                "description": (
                    "The webcam sits in a strip across the top and the gameplay "
                    "fills the rest. The strip takes about forty per cent of the "
                    "height by default."
                ),
            },
            {
                "value": LayoutVariant.CORNER.value,
                "title": "Webcam in the corner",
                "description": (
                    "The webcam is drawn over the gameplay in one corner, at a "
                    "size the source can actually fill."
                ),
            },
        ],
        "positions": list(POSITIONS),
    }
