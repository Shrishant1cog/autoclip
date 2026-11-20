"""Database access for the creative plan.

One row per job: the plan the model proposed, the part that was accepted,
and the reasons any of it was rejected.

The whole plan is kept, including the problems. A plan that silently fell
back to the deterministic one would read exactly like a plan the model
agreed with, and the user would have no way to tell.
"""

from __future__ import annotations

import json
import time
from typing import Any

from ..db import connection

__all__ = ["load", "save"]


def _now() -> str:
    return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())


def save(job_id: str, plan: Any) -> None:
    """Write the plan down."""
    payload = plan.to_dict() if hasattr(plan, "to_dict") else dict(plan or {})
    problems = payload.get("problems") or []
    with connection() as conn:
        conn.execute(
            """
            INSERT INTO creative_plans (job_id, source, payload, problems, created_at)
            VALUES (?, ?, ?, ?, ?)
            ON CONFLICT(job_id) DO UPDATE SET
                source = excluded.source,
                payload = excluded.payload,
                problems = excluded.problems,
                created_at = excluded.created_at
            """,
            (
                job_id,
                str(payload.get("source") or "fallback"),
                json.dumps(payload, ensure_ascii=False),
                json.dumps(problems),
                _now(),
            ),
        )


def load(job_id: str) -> dict[str, Any] | None:
    """The plan for a job, or ``None`` when it has none."""
    try:
        with connection() as conn:
            row = conn.execute(
                "SELECT * FROM creative_plans WHERE job_id = ?", (job_id,)
            ).fetchone()
    except Exception:  # noqa: BLE001 - an unmigrated database has no table yet
        return None
    if row is None:
        return None

    try:
        payload = json.loads(row["payload"])
    except (TypeError, ValueError):
        payload = {}
    if not isinstance(payload, dict):
        payload = {}

    payload.setdefault("source", str(row["source"] or "fallback"))
    try:
        problems = json.loads(row["problems"])
    except (TypeError, ValueError):
        problems = []
    payload.setdefault("problems", problems if isinstance(problems, list) else [])
    return payload
