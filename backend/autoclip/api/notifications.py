"""Notification centre API (Phase 14).

The inbox the pipeline writes to and the user reads from. Local-first: the
rows live in the AutoClip database; nothing is sent anywhere.
"""

from __future__ import annotations

import asyncio
import logging

from fastapi import APIRouter, HTTPException, Query

from ..db import store

log = logging.getLogger(__name__)

router = APIRouter(prefix="/api/notifications", tags=["notifications"])


@router.get("")
async def list_all(
    limit: int = Query(default=50, ge=1, le=500),
    unread_only: bool = False,
) -> list[dict]:
    """Recent notifications, newest first."""
    rows = await asyncio.to_thread(store.list_notifications, limit, unread_only=unread_only)
    return [
        {
            "id": row.id,
            "kind": row.kind,
            "severity": row.severity,
            "title": row.title,
            "body": row.body,
            "link": row.link,
            "entity_id": row.entity_id,
            "read": row.read,
            "created_at": row.created_at,
        }
        for row in rows
    ]


@router.get("/unread-count")
async def unread_count() -> dict:
    """The badge count for the masthead bell."""
    unread = await asyncio.to_thread(store.unread_notification_count)
    return {"unread": unread}


@router.post("/{notification_id}/read")
async def mark_read(notification_id: str) -> dict:
    """Mark one notification read."""
    changed = await asyncio.to_thread(store.mark_notification_read, notification_id)
    if not changed:
        raise HTTPException(status_code=404, detail="Notification not found.")
    return {"read": True}


@router.post("/read-all")
async def mark_all_read() -> dict:
    """Mark every unread notification read."""
    changed = await asyncio.to_thread(store.mark_all_notifications_read)
    return {"marked": changed}


@router.delete("/{notification_id}")
async def delete_one(notification_id: str) -> dict:
    """Remove one notification."""
    changed = await asyncio.to_thread(store.delete_notification, notification_id)
    if not changed:
        raise HTTPException(status_code=404, detail="Notification not found.")
    return {"deleted": True}


@router.post("/clear")
async def clear_read() -> dict:
    """Remove every read notification, keeping the unread inbox intact."""
    removed = await asyncio.to_thread(store.clear_read_notifications)
    return {"removed": removed}
