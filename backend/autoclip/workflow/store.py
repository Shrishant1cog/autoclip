"""Persistence for workflows and their execution history."""

from __future__ import annotations

import json
import logging
from typing import Any

from ..db.models import new_id, utcnow
from ..db.store import connection

log = logging.getLogger(__name__)


def create_workflow(
    name: str, definition: dict[str, Any], description: str = "", *, active: bool = False
) -> dict[str, Any]:
    workflow_id = new_id()
    now = utcnow()
    with connection() as conn:
        conn.execute(
            """
            INSERT INTO workflows (id, name, description, definition, version, active,
                                   created_at, updated_at)
            VALUES (?, ?, ?, ?, 1, ?, ?, ?)
            """,
            (
                workflow_id,
                name,
                description,
                json.dumps(definition),
                int(active),
                now,
                now,
            ),
        )
    return get_workflow(workflow_id)  # type: ignore[return-value]


def get_workflow(workflow_id: str) -> dict[str, Any] | None:
    with connection() as conn:
        row = conn.execute(
            "SELECT id, name, description, definition, version, active, created_at, updated_at"
            " FROM workflows WHERE id = ?",
            (workflow_id,),
        ).fetchone()
    if row is None:
        return None
    return {
        "id": row[0],
        "name": row[1],
        "description": row[2],
        "definition": json.loads(row[3]),
        "version": row[4],
        "active": bool(row[5]),
        "created_at": row[6],
        "updated_at": row[7],
    }


def list_workflows() -> list[dict[str, Any]]:
    with connection() as conn:
        rows = conn.execute(
            "SELECT id, name, description, definition, version, active, created_at, updated_at"
            " FROM workflows ORDER BY created_at"
        ).fetchall()
    return [
        {
            "id": r[0],
            "name": r[1],
            "description": r[2],
            "definition": json.loads(r[3]),
            "version": r[4],
            "active": bool(r[5]),
            "created_at": r[6],
            "updated_at": r[7],
        }
        for r in rows
    ]


def save_workflow(
    workflow_id: str, definition: dict[str, Any], *, name: str | None = None
) -> dict[str, Any] | None:
    """Save as a new version of the workflow; the previous version is retained."""
    current = get_workflow(workflow_id)
    if current is None:
        return None
    with connection() as conn:
        conn.execute("UPDATE workflows SET active = 0 WHERE id = ?", (workflow_id,))
        new_row = (
            new_id(),
            name or current["name"],
            current["description"],
            json.dumps(definition),
            current["version"] + 1,
            1,
            current["created_at"],
            utcnow(),
        )
        conn.execute(
            """
            INSERT INTO workflows (id, name, description, definition, version, active,
                                   created_at, updated_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """,
            new_row,
        )
        # Retire the old row by pointing its name aside (history is kept).
        conn.execute(
            "UPDATE workflows SET active = 0, updated_at = ? WHERE id = ?",
            (utcnow(), workflow_id),
        )
        # The new row keeps the same *logical* id slot only via name; callers
        # should treat the returned id as the active version id.
        new_id_value = new_row[0]
    return get_workflow(new_id_value)


def start_run(workflow_id: str, job_id: str | None, trigger: str = "manual") -> str:
    run_id = new_id()
    with connection() as conn:
        conn.execute(
            """
            INSERT INTO workflow_runs (id, workflow_id, job_id, status, trigger, started_at)
            VALUES (?, ?, ?, 'running', ?, ?)
            """,
            (run_id, workflow_id, job_id, trigger, utcnow()),
        )
    return run_id


def finish_run(run_id: str, status: str, error: str | None = None) -> None:
    with connection() as conn:
        conn.execute(
            "UPDATE workflow_runs SET status = ?, error = ?, finished_at = ? WHERE id = ?",
            (status, error, utcnow(), run_id),
        )


def record_node_run(
    run_id: str,
    node_id: str,
    node_type: str,
    status: str,
    *,
    attempt: int = 1,
    input_payload: Any = None,
    output_payload: Any = None,
    error: str | None = None,
    started_at: str | None = None,
    finished_at: str | None = None,
) -> None:
    with connection() as conn:
        conn.execute(
            """
            INSERT INTO workflow_node_runs (
                id, run_id, node_id, node_type, status, attempt,
                input_json, output_json, error, started_at, finished_at
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                new_id(),
                run_id,
                node_id,
                node_type,
                status,
                attempt,
                json.dumps(input_payload) if input_payload is not None else None,
                json.dumps(output_payload, default=str) if output_payload is not None else None,
                error,
                started_at,
                finished_at,
            ),
        )


def list_runs(workflow_id: str | None = None, limit: int = 50) -> list[dict[str, Any]]:
    query = (
        "SELECT r.id, r.workflow_id, r.job_id, r.status, r.trigger, r.started_at,"
        " r.finished_at, r.error, w.name"
        " FROM workflow_runs r JOIN workflows w ON w.id = r.workflow_id"
    )
    params: tuple[Any, ...] = ()
    if workflow_id:
        query += " WHERE r.workflow_id = ?"
        params = (workflow_id,)
    query += " ORDER BY r.started_at DESC LIMIT ?"
    params += (limit,)
    with connection() as conn:
        rows = conn.execute(query, params).fetchall()
    return [
        {
            "id": r[0],
            "workflow_id": r[1],
            "job_id": r[2],
            "status": r[3],
            "trigger": r[4],
            "started_at": r[5],
            "finished_at": r[6],
            "error": r[7],
            "workflow_name": r[8],
        }
        for r in rows
    ]


def list_node_runs(run_id: str) -> list[dict[str, Any]]:
    with connection() as conn:
        rows = conn.execute(
            "SELECT node_id, node_type, status, attempt, input_json, output_json, error,"
            " started_at, finished_at"
            " FROM workflow_node_runs WHERE run_id = ? ORDER BY started_at",
            (run_id,),
        ).fetchall()
    return [
        {
            "node_id": r[0],
            "node_type": r[1],
            "status": r[2],
            "attempt": r[3],
            "input": json.loads(r[4]) if r[4] else None,
            "output": json.loads(r[5]) if r[5] else None,
            "error": r[6],
            "started_at": r[7],
            "finished_at": r[8],
        }
        for r in rows
    ]
