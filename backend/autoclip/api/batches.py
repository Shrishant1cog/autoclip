"""Batch queue API (Phase 6)."""

from __future__ import annotations

import logging
from typing import Any

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from ..db import store
from ..jobs import batches
from ..jobs.batch_runner import batch_runner

log = logging.getLogger(__name__)

router = APIRouter(prefix="/api/batches", tags=["batches"])


class BatchIn(BaseModel):
    name: str = ""
    settings: dict[str, Any] = {}


class BatchSourceIn(BaseModel):
    source_ids: list[str]


@router.get("")
async def list_all(limit: int = 50) -> list[dict]:
    """All batches with item progress."""
    out = []
    for batch in batches.list_batches(limit):
        progress = batches.batch_progress(batch["id"])
        out.append({**batch, "progress": progress})
    return out


@router.post("", status_code=201)
async def create(payload: BatchIn) -> dict:
    batch = batches.create_batch(payload.name, payload.settings)
    return {**batch, "progress": batches.batch_progress(batch["id"])}


@router.get("/{batch_id}")
async def detail(batch_id: str) -> dict:
    batch = batches.get_batch(batch_id)
    if batch is None:
        raise HTTPException(status_code=404, detail="Batch not found.")
    items = batches.list_items(batch_id)
    # Attach source titles for the UI.
    for item in items:
        source = store.get_source(item["source_id"])
        item["source_title"] = source.title if source else ""
    return {**batch, "items": items, "progress": batches.batch_progress(batch_id)}


@router.delete("/{batch_id}", status_code=204)
async def delete(batch_id: str) -> None:
    batch_runner.cancel(batch_id)
    batches.delete_batch(batch_id)


@router.post("/{batch_id}/sources", status_code=201)
async def add_sources(batch_id: str, payload: BatchSourceIn) -> dict:
    if batches.get_batch(batch_id) is None:
        raise HTTPException(status_code=404, detail="Batch not found.")
    added = []
    missing = []
    for source_id in payload.source_ids:
        if store.get_source(source_id) is None:
            missing.append(source_id)
            continue
        added.append(batches.add_item(batch_id, source_id))
    if missing:
        raise HTTPException(status_code=400, detail=f"Unknown sources: {', '.join(missing)}")
    return {"added": len(added), "items": added}


@router.post("/{batch_id}/launch")
async def launch(batch_id: str) -> dict:
    batch = batches.get_batch(batch_id)
    if batch is None:
        raise HTTPException(status_code=404, detail="Batch not found.")
    batch_runner.launch(batch_id)
    return batches.get_batch(batch_id) or {}


@router.post("/{batch_id}/pause")
async def pause(batch_id: str) -> dict:
    batch_runner.pause(batch_id)
    batch = batches.get_batch(batch_id)
    if batch is None:
        raise HTTPException(status_code=404, detail="Batch not found.")
    return batch


@router.post("/{batch_id}/cancel")
async def cancel(batch_id: str) -> dict:
    batch = batches.get_batch(batch_id)
    if batch is None:
        raise HTTPException(status_code=404, detail="Batch not found.")
    batch_runner.cancel(batch_id)
    return batches.get_batch(batch_id) or {}


@router.post("/{batch_id}/retry-failed")
async def retry_failed(batch_id: str) -> dict:
    batch = batches.get_batch(batch_id)
    if batch is None:
        raise HTTPException(status_code=404, detail="Batch not found.")
    count = batch_runner.retry_failed(batch_id)
    return {"requeued": count, **(batches.get_batch(batch_id) or {})}
