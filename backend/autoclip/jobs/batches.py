"""Persistent batch queues.

A batch is an ordered list of sources processed one job at a time by the
existing job queue. State is fully persistent: restarts resume at the first
non-finished item, failures mark their item and move on, and pause/cancel
work between items (never mid-job — the running job finishes).
"""

from __future__ import annotations

import json
import logging
from typing import Any

from ..db.models import new_id, utcnow
from ..db.store import connection

log = logging.getLogger(__name__)


# --------------------------------------------------------------------------
# CRUD
# --------------------------------------------------------------------------


def create_batch(name: str = "", settings: dict[str, Any] | None = None) -> dict[str, Any]:
    batch_id = new_id()
    now = utcnow()
    with connection() as conn:
        conn.execute(
            "INSERT INTO batches (id, name, status, settings_json, created_at, updated_at)"
            " VALUES (?, ?, 'queued', ?, ?, ?)",
            (batch_id, name, json.dumps(settings or {}), now, now),
        )
    result = get_batch(batch_id)
    assert result is not None
    return result


def get_batch(batch_id: str) -> dict[str, Any] | None:
    with connection() as conn:
        row = conn.execute(
            "SELECT id, name, status, settings_json, created_at, updated_at"
            " FROM batches WHERE id = ?",
            (batch_id,),
        ).fetchone()
    if row is None:
        return None
    return {
        "id": row[0],
        "name": row[1],
        "status": row[2],
        "settings": json.loads(row[3]),
        "created_at": row[4],
        "updated_at": row[5],
    }


def list_batches(limit: int = 50) -> list[dict[str, Any]]:
    with connection() as conn:
        rows = conn.execute(
            "SELECT id, name, status, settings_json, created_at, updated_at"
            " FROM batches ORDER BY created_at DESC LIMIT ?",
            (limit,),
        ).fetchall()
    return [
        {
            "id": r[0],
            "name": r[1],
            "status": r[2],
            "settings": json.loads(r[3]),
            "created_at": r[4],
            "updated_at": r[5],
        }
        for r in rows
    ]


def set_batch_status(batch_id: str, status: str) -> None:
    with connection() as conn:
        conn.execute(
            "UPDATE batches SET status = ?, updated_at = ? WHERE id = ?",
            (status, utcnow(), batch_id),
        )


def delete_batch(batch_id: str) -> None:
    with connection() as conn:
        conn.execute("DELETE FROM batches WHERE id = ?", (batch_id,))


# --------------------------------------------------------------------------
# Items
# --------------------------------------------------------------------------


def add_item(batch_id: str, source_id: str, *, position: int | None = None) -> dict[str, Any]:
    if position is None:
        with connection() as conn:
            row = conn.execute(
                "SELECT COALESCE(MAX(position), -1) + 1 FROM batch_items WHERE batch_id = ?",
                (batch_id,),
            ).fetchone()
        position = int(row[0])
    now = utcnow()
    item_id = new_id()
    with connection() as conn:
        conn.execute(
            "INSERT INTO batch_items (id, batch_id, source_id, position, status,"
            " created_at, updated_at) VALUES (?, ?, ?, ?, 'pending', ?, ?)",
            (item_id, batch_id, source_id, position, now, now),
        )
    result = get_item(item_id)
    assert result is not None
    return result


def get_item(item_id: str) -> dict[str, Any] | None:
    with connection() as conn:
        row = conn.execute(
            "SELECT id, batch_id, source_id, job_id, position, status, error,"
            " created_at, updated_at FROM batch_items WHERE id = ?",
            (item_id,),
        ).fetchone()
    return _item_row(row) if row else None


def _item_row(r: tuple[Any, ...]) -> dict[str, Any]:
    return {
        "id": r[0],
        "batch_id": r[1],
        "source_id": r[2],
        "job_id": r[3],
        "position": r[4],
        "status": r[5],
        "error": r[6],
        "created_at": r[7],
        "updated_at": r[8],
    }


def list_items(batch_id: str) -> list[dict[str, Any]]:
    with connection() as conn:
        rows = conn.execute(
            "SELECT id, batch_id, source_id, job_id, position, status, error,"
            " created_at, updated_at FROM batch_items WHERE batch_id = ?"
            " ORDER BY position",
            (batch_id,),
        ).fetchall()
    return [_item_row(r) for r in rows]


def update_item(item_id: str, **fields: Any) -> dict[str, Any] | None:
    allowed = {"status", "job_id", "error", "position"}
    updates = {k: v for k, v in fields.items() if k in allowed}
    if not updates:
        return get_item(item_id)
    sets = ", ".join(f"{k} = ?" for k in updates)
    with connection() as conn:
        conn.execute(
            f"UPDATE batch_items SET {sets}, updated_at = ? WHERE id = ?",  # noqa: S608
            (*updates.values(), utcnow(), item_id),
        )
    return get_item(item_id)


def next_pending_item(batch_id: str) -> dict[str, Any] | None:
    with connection() as conn:
        row = conn.execute(
            "SELECT id FROM batch_items WHERE batch_id = ? AND status = 'pending'"
            " ORDER BY position LIMIT 1",
            (batch_id,),
        ).fetchone()
    return get_item(row[0]) if row else None


def batch_progress(batch_id: str) -> dict[str, int]:
    with connection() as conn:
        rows = conn.execute(
            "SELECT status, COUNT(*) FROM batch_items WHERE batch_id = ? GROUP BY status",
            (batch_id,),
        ).fetchall()
    counts = {r[0]: r[1] for r in rows}
    total = sum(counts.values())
    return {
        "total": total,
        "pending": counts.get("pending", 0),
        "processing": counts.get("processing", 0),
        "done": counts.get("done", 0),
        "failed": counts.get("failed", 0),
        "skipped": counts.get("skipped", 0),
        "cancelled": counts.get("cancelled", 0),
    }


def recover_interrupted() -> int:
    """On startup: reset items left 'processing' back to 'pending'. Returns count."""
    with connection() as conn:
        cursor = conn.execute(
            "UPDATE batch_items SET status = 'pending', updated_at = ?"
            " WHERE status = 'processing'",
            (utcnow(),),
        )
        return cursor.rowcount
