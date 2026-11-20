"""Database access for per-source layouts.

Two things are kept for each source video:

* **What was detected.** The rectangle the detector found, its confidence,
  and why the detector decided what it decided. This is a record, so the
  settings page can say what it is working from instead of showing a
  picture of a face and no explanation.
* **What the user chose.** The manual layout. An empty variant means there
  is no override and the automatic planner decides.

Nothing here identifies anybody. A rectangle is a region of pixels and a
confidence is a number; there is no face template and no name.
"""

from __future__ import annotations

import time
from dataclasses import dataclass
from typing import Any

from ...db import connection

__all__ = [
    "SourceLayout",
    "clear_layout_override",
    "get_source_layout",
    "record_detection",
    "set_layout_override",
]


def _now() -> str:
    return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())


@dataclass
class SourceLayout:
    """What is known about one source's layout."""

    source_id: str
    #: The manual choice. Empty means "no override".
    variant: str = ""
    rect_x: float = 0.0
    rect_y: float = 0.0
    rect_width: float = 0.0
    rect_height: float = 0.0
    position: str = ""
    scale: float = 0.0
    #: What the detector found.
    detected_x: float = 0.0
    detected_y: float = 0.0
    detected_width: float = 0.0
    detected_height: float = 0.0
    detected_confidence: float = 0.0
    detected_face_width: float = 0.0
    detected_reason: str = ""
    detected_at: str = ""
    updated_at: str = ""

    @property
    def has_override(self) -> bool:
        return bool(self.variant)

    @property
    def has_detection(self) -> bool:
        return self.detected_width > 0 and self.detected_height > 0

    def to_dict(self) -> dict[str, Any]:
        return {
            "source_id": self.source_id,
            "variant": self.variant,
            "rect_x": round(self.rect_x, 2),
            "rect_y": round(self.rect_y, 2),
            "rect_width": round(self.rect_width, 2),
            "rect_height": round(self.rect_height, 2),
            "position": self.position,
            "scale": round(self.scale, 4),
            "detected_x": round(self.detected_x, 2),
            "detected_y": round(self.detected_y, 2),
            "detected_width": round(self.detected_width, 2),
            "detected_height": round(self.detected_height, 2),
            "detected_confidence": round(self.detected_confidence, 4),
            "detected_face_width": round(self.detected_face_width, 2),
            "detected_reason": self.detected_reason,
            "detected_at": self.detected_at,
            "updated_at": self.updated_at,
        }


def _to_layout(source_id: str, row: Any) -> SourceLayout:
    """Build a SourceLayout from a database row."""
    return SourceLayout(
        source_id=source_id,
        variant=str(row["variant"] or ""),
        rect_x=float(row["rect_x"] or 0.0),
        rect_y=float(row["rect_y"] or 0.0),
        rect_width=float(row["rect_width"] or 0.0),
        rect_height=float(row["rect_height"] or 0.0),
        position=str(row["position"] or ""),
        scale=float(row["scale"] or 0.0),
        detected_x=float(row["detected_x"] or 0.0),
        detected_y=float(row["detected_y"] or 0.0),
        detected_width=float(row["detected_width"] or 0.0),
        detected_height=float(row["detected_height"] or 0.0),
        detected_confidence=float(row["detected_confidence"] or 0.0),
        detected_face_width=float(row["detected_face_width"] or 0.0),
        detected_reason=str(row["detected_reason"] or ""),
        detected_at=str(row["detected_at"] or ""),
        updated_at=str(row["updated_at"] or ""),
    )


def get_source_layout(source_id: str) -> SourceLayout | None:
    """The stored layout for a source, or None when there is no row."""
    with connection() as conn:
        row = conn.execute(
            "SELECT * FROM source_layouts WHERE source_id = ?",
            (source_id,),
        ).fetchone()
    if row is None:
        return None
    return _to_layout(source_id, row)


def record_detection(
    source_id: str,
    *,
    rect: dict[str, float] | None,
    confidence: float,
    face_width: float,
    reason: str,
) -> SourceLayout:
    """Record what the detector found for a source.

    The manual override is left alone: detection never overwrites what the
    user chose.
    """
    now = _now()
    rect = rect or {}
    with connection() as conn:
        conn.execute(
            """
            INSERT INTO source_layouts (
                source_id, detected_x, detected_y, detected_width, detected_height,
                detected_confidence, detected_face_width, detected_reason,
                detected_at, updated_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(source_id) DO UPDATE SET
                detected_x = excluded.detected_x,
                detected_y = excluded.detected_y,
                detected_width = excluded.detected_width,
                detected_height = excluded.detected_height,
                detected_confidence = excluded.detected_confidence,
                detected_face_width = excluded.detected_face_width,
                detected_reason = excluded.detected_reason,
                detected_at = excluded.detected_at,
                updated_at = excluded.updated_at
            """,
            (
                source_id,
                float(rect.get("x", 0.0)),
                float(rect.get("y", 0.0)),
                float(rect.get("width", 0.0)),
                float(rect.get("height", 0.0)),
                float(confidence),
                float(face_width),
                reason,
                now,
                now,
            ),
        )
    layout = get_source_layout(source_id)
    return layout or SourceLayout(source_id=source_id, updated_at=now)


def set_layout_override(
    source_id: str,
    *,
    variant: str,
    rect_x: float = 0.0,
    rect_y: float = 0.0,
    rect_width: float = 0.0,
    rect_height: float = 0.0,
    position: str = "",
    scale: float = 0.0,
) -> SourceLayout:
    """Save the user's own choice for a source."""
    now = _now()
    with connection() as conn:
        conn.execute(
            """
            INSERT INTO source_layouts (
                source_id, variant, rect_x, rect_y, rect_width, rect_height,
                position, scale, updated_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(source_id) DO UPDATE SET
                variant = excluded.variant,
                rect_x = excluded.rect_x,
                rect_y = excluded.rect_y,
                rect_width = excluded.rect_width,
                rect_height = excluded.rect_height,
                position = excluded.position,
                scale = excluded.scale,
                updated_at = excluded.updated_at
            """,
            (
                source_id,
                variant,
                float(rect_x),
                float(rect_y),
                float(rect_width),
                float(rect_height),
                position,
                float(scale),
                now,
            ),
        )
    layout = get_source_layout(source_id)
    return layout or SourceLayout(source_id=source_id, updated_at=now)


def clear_layout_override(source_id: str) -> SourceLayout | None:
    """Forget the user's choice, so the automatic planner decides again.

    What was detected is kept: the user changed their mind about the
    layout, not about the video.
    """
    with connection() as conn:
        conn.execute(
            """
            UPDATE source_layouts SET
                variant = '', rect_x = 0, rect_y = 0,
                rect_width = 0, rect_height = 0,
                position = '', scale = 0, updated_at = ?
            WHERE source_id = ?
            """,
            (_now(), source_id),
        )
    return get_source_layout(source_id)
