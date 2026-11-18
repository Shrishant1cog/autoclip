"""Learning and analytics API (Phase 11).

Read-mostly: outcome statistics plus the improve.txt feedback loop. The
feedback file is plain text on purpose — power users edit it in any editor;
the API exists so the UI can show and save it too.
"""

from __future__ import annotations

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from ..learning import analytics, improve

router = APIRouter(prefix="/api/learning", tags=["learning"])


class FeedbackIn(BaseModel):
    content: str


class ChannelNoteIn(BaseModel):
    channel_id: str
    note: str


@router.get("/summary")
async def summary() -> dict:
    """Top-line pipeline counters."""
    return analytics.pipeline_summary().to_dict()


@router.get("/score-bands")
async def score_bands() -> list[dict]:
    """Outcome counts per model score band (calibration evidence)."""
    return [band.to_dict() for band in analytics.score_band_outcomes()]


@router.get("/channels")
async def channels() -> list[dict]:
    """Upload outcomes grouped by destination channel."""
    return [row.to_dict() for row in analytics.channel_outcomes()]


@router.get("/feedback")
async def feedback() -> dict:
    """The improve.txt contents (comments included so the UI can round-trip)."""
    path = improve.ensure_template()
    try:
        content = path.read_text(encoding="utf-8")
    except OSError:
        content = improve.TEMPLATE
    return {"path": str(path), "content": content, "max_chars": improve.MAX_FEEDBACK_CHARS}


@router.put("/feedback")
async def save_feedback(payload: FeedbackIn) -> dict:
    """Replace improve.txt.

    Saving blank content restores the commented template rather than leaving a
    zero-byte file, so the file stays discoverable for the next editor.
    """
    path = improve.ensure_template()
    content = payload.content
    if len(content) > 100_000:
        raise HTTPException(status_code=413, detail="Feedback file is too large.")
    if not content.strip():
        content = improve.TEMPLATE
    try:
        path.write_text(content, encoding="utf-8")
    except OSError as exc:
        raise HTTPException(status_code=500, detail=f"Could not write {path}: {exc}") from exc
    return {"saved": True, "active_chars": len(improve.read_feedback())}


@router.get("/channel-note/{channel_id}")
async def channel_note(channel_id: str) -> dict:
    """The per-channel metadata feedback note."""
    return {
        "channel_id": channel_id,
        "note": improve.read_channel_note(channel_id),
        "path": str(improve.channel_note_path(channel_id)),
    }


@router.put("/channel-note/{channel_id}")
async def save_channel_note(channel_id: str, payload: ChannelNoteIn) -> dict:
    """Set (or clear, when empty) the per-channel note."""
    improve.write_channel_note(channel_id, payload.note)
    return {"saved": True, "note": improve.read_channel_note(channel_id)}
