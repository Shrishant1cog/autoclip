"""Restart history (Phase 17).

AutoClip resumes interrupted work on startup — a job that was mid-render, an
upload that was mid-flight, a batch item that was processing. That behaviour
was correct but invisible: the job simply carried on, and there was no way to
learn that a restart had interrupted it (or that it had to begin a stage
again because the interruption happened in the middle of one).

This endpoint makes the restart visible. The counts are the real numbers of
rows that were recovered — not an estimate of how much work was lost.
"""

from __future__ import annotations

import asyncio
import logging

from fastapi import APIRouter

from ..db import store

log = logging.getLogger(__name__)

router = APIRouter(prefix="/api/restarts", tags=["restarts"])


def _restart_row(restart: store.AppRestart) -> dict[str, object]:
    """One restart, in the shape the UI reads."""
    return {
        "id": restart.id,
        "started_at": restart.started_at,
        "jobs_resumed": restart.jobs_resumed,
        "uploads_resumed": restart.uploads_resumed,
        "batch_items_resumed": restart.batch_items_resumed,
        "total_resumed": restart.total_resumed,
        "job_ids": restart.job_ids,
        "upload_ids": restart.upload_ids,
        "details": restart.details,
    }


@router.get("")
async def list_restarts(limit: int = 20) -> dict:
    """The restart history, newest first, plus a summary of the latest one."""
    rows = await asyncio.to_thread(store.list_restarts, limit)

    restarts = [_restart_row(row) for row in rows]
    latest = restarts[0] if restarts else None

    return {
        "restarts": restarts,
        "latest": latest,
        "count": len(restarts),
        # How many restarts actually had work to resume — a restart with
        # nothing in flight is the normal case and is not worth flagging.
        "restarts_with_work": sum(1 for row in restarts if row["total_resumed"]),
    }
