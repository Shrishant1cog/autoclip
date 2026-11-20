"""Database access for the AI call budget.

One row per job. The counters live here rather than in memory so that a
retry does not hand the job a fresh allowance — spending twice because
something went wrong is how a cost control stops being a cost control.
"""

from __future__ import annotations

import json

from ..budget import JobBudget
from ..db import connection

__all__ = ["load", "save", "list_budgets"]


def save(budget: JobBudget) -> None:
    """Write the counters down."""
    row = budget.to_row()
    overruns = row.get("overruns") or []
    with connection() as conn:
        conn.execute(
            """
            INSERT INTO job_ai_budget (
                job_id, plan_limit, plan_used,
                repair_limit, repair_used,
                music_limit, music_used,
                overruns, user_approved_overrides, updated_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(job_id) DO UPDATE SET
                plan_limit = excluded.plan_limit,
                plan_used = excluded.plan_used,
                repair_limit = excluded.repair_limit,
                repair_used = excluded.repair_used,
                music_limit = excluded.music_limit,
                music_used = excluded.music_used,
                overruns = excluded.overruns,
                user_approved_overrides = excluded.user_approved_overrides,
                updated_at = excluded.updated_at
            """,
            (
                row["job_id"],
                row["plan_limit"],
                row["plan_used"],
                row["repair_limit"],
                row["repair_used"],
                row["music_limit"],
                row["music_used"],
                json.dumps(overruns),
                row["user_approved_overrides"],
                row["updated_at"],
            ),
        )


def load(job_id: str) -> JobBudget | None:
    """The budget for a job, or ``None`` when it has never run."""
    try:
        with connection() as conn:
            row = conn.execute("SELECT * FROM job_ai_budget WHERE job_id = ?", (job_id,)).fetchone()
    except Exception:  # noqa: BLE001 - an unmigrated database has no table yet
        return None
    if row is None:
        return None
    return JobBudget.from_row(row)


def list_budgets(limit: int = 100) -> list[JobBudget]:
    """Every job's budget, newest first."""
    try:
        with connection() as conn:
            rows = conn.execute(
                "SELECT * FROM job_ai_budget ORDER BY updated_at DESC, rowid DESC LIMIT ?",
                (limit,),
            ).fetchall()
    except Exception:  # noqa: BLE001 - an unmigrated database has no table yet
        return []
    return [JobBudget.from_row(row) for row in rows]
