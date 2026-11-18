"""Classification & routing API (Phase 5)."""

from __future__ import annotations

import logging

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from ..db import store as db_store
from ..routing import classifier

log = logging.getLogger(__name__)

router = APIRouter(prefix="/api/routing", tags=["routing"])


class RuleIn(BaseModel):
    name: str = ""
    match_keyword: str
    target_channel_id: str
    priority: int = 100
    enabled: bool = True


class RuleUpdateIn(BaseModel):
    name: str | None = None
    match_keyword: str | None = None
    target_channel_id: str | None = None
    priority: int | None = None
    enabled: bool | None = None


@router.get("/categories")
async def categories() -> list[str]:
    return classifier.CATEGORIES


@router.get("/rules")
async def rules() -> list[dict]:
    return classifier.list_rules()


@router.post("/rules", status_code=201)
async def add_rule(payload: RuleIn) -> dict:
    if not payload.match_keyword.strip():
        raise HTTPException(status_code=400, detail="match_keyword cannot be empty.")
    # The target must be a real channel row.
    from ..youtube import accounts as accounts_store

    if accounts_store.get_channel(payload.target_channel_id) is None:
        raise HTTPException(status_code=404, detail="Target channel not found.")
    return classifier.add_rule(
        payload.match_keyword.strip(),
        payload.target_channel_id,
        name=payload.name,
        priority=payload.priority,
        enabled=payload.enabled,
    )


@router.put("/rules/{rule_id}")
async def update_rule(rule_id: str, payload: RuleUpdateIn) -> dict:
    fields = {k: v for k, v in payload.model_dump().items() if v is not None}
    updated = classifier.update_rule(rule_id, **fields)
    if updated is None:
        raise HTTPException(status_code=404, detail="Rule not found.")
    return updated


@router.delete("/rules/{rule_id}", status_code=204)
async def delete_rule(rule_id: str) -> None:
    classifier.delete_rule(rule_id)


@router.post("/rules/{rule_id}/toggle")
async def toggle_rule(rule_id: str) -> dict:
    rule = classifier.get_rule(rule_id)
    if rule is None:
        raise HTTPException(status_code=404, detail="Rule not found.")
    return classifier.update_rule(rule_id, enabled=not rule["enabled"]) or {}


@router.get("/clips/{clip_id}/classification")
async def clip_classification(clip_id: str) -> dict:
    result = classifier.classification_for(clip_id)
    if result is None:
        raise HTTPException(status_code=404, detail="This clip has not been classified yet.")
    return result


@router.post("/clips/{clip_id}/classify")
async def classify_clip(clip_id: str) -> dict:
    """Classify a clip now and persist the result."""
    from pathlib import Path

    from ..pipeline.transcript import Transcript

    clip = db_store.get_clip(clip_id)
    if clip is None:
        raise HTTPException(status_code=404, detail="Clip not found.")
    transcript_record = db_store.get_transcript(clip.job_id)
    text = ""
    if transcript_record is not None:
        try:
            transcript = Transcript.load(Path(transcript_record.json_path))
            text = transcript.text_between(clip.start_word, clip.end_word)
        except (OSError, ValueError):
            text = ""
    result = classifier.classify_transcript_sync(text, clip.title)
    if result is None:
        raise HTTPException(status_code=502, detail="Classification failed; no provider answered.")
    classifier.save_classification(clip_id, result)
    return {"clip_id": clip_id, **result}


@router.get("/clips/{clip_id}/target")
async def clip_target(clip_id: str) -> dict:
    """Which channel this clip would be routed to right now."""
    target = classifier.resolve_target_channel(clip_id)
    if target is None:
        raise HTTPException(status_code=404, detail="No channels are configured.")
    return target
