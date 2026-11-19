"""External processing: what AutoClip may send, and what it has sent.

This is the Settings screen's privacy section. It answers three questions the
user is entitled to answers:

1. *What leaves this machine?* — one row per operation, saying what data it
   sends and why.
2. *Did I allow it?* — the stored decision for each destination class, with
   the reason and when it was decided.
3. *What actually went out?* — the transfer log, newest first.

No credential ever appears here. The log records a description of the data,
the destination and the outcome — never the content itself.
"""

from __future__ import annotations

import logging
from typing import Any

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from ..security import consent
from ..security.urlpolicy import UrlClass

log = logging.getLogger(__name__)

router = APIRouter(prefix="/api/privacy", tags=["privacy"])

#: The classes a decision can be made for. Loopback is always allowed, so it
#: is not offered as a choice — offering it would suggest it can be denied.
CHOICES = ("public", "private")


class ConsentIn(BaseModel):
    """A decision to record."""

    operation: str
    destination_class: str
    granted: bool
    note: str = Field(default="", max_length=400)


class ConsentOut(BaseModel):
    """One operation and its decisions."""

    operation: str
    title: str
    data: str
    why: str
    decisions: list[dict[str, Any]]


class TransferOut(BaseModel):
    """One recorded transfer."""

    occurred_at: str
    operation: str
    provider: str
    destination: str
    destination_class: str
    data_summary: str
    outcome: str
    detail: str
    duration_ms: int


def _operations() -> list[ConsentOut]:
    descriptions = consent.all_operations()
    stored = {(d.operation, d.destination_class): d for d in consent.list_decisions()}
    out: list[ConsentOut] = []
    for name in consent.Operation.all():
        meta = descriptions.get(name, {})
        decisions = []
        for destination_class in CHOICES:
            decision = stored.get((name, destination_class))
            decisions.append(
                {
                    "destination_class": destination_class,
                    "granted": bool(decision.granted) if decision else False,
                    "source": decision.source if decision else "",
                    "decided_at": decision.decided_at if decision else "",
                    "note": decision.note if decision else "",
                }
            )
        out.append(
            ConsentOut(
                operation=name,
                title=meta.get("title", name),
                data=meta.get("data", ""),
                why=meta.get("why", ""),
                decisions=decisions,
            )
        )
    return out


@router.get("/consents", response_model=list[ConsentOut])
async def list_consents() -> list[ConsentOut]:
    """Every external operation and the user's decision for it."""
    return _operations()


@router.put("/consents", response_model=list[ConsentOut])
async def put_consent(payload: ConsentIn) -> list[ConsentOut]:
    """Record (or withdraw) a decision.

    Loopback is not a choice: it is the same machine and is always allowed.
    """
    if payload.operation not in consent.Operation.all():
        raise HTTPException(400, f"Unknown operation {payload.operation!r}.")
    if payload.destination_class not in CHOICES:
        raise HTTPException(
            400,
            f"Unknown destination class {payload.destination_class!r}. Use 'public' or 'private'.",
        )
    if payload.destination_class == UrlClass.LOOPBACK.value:
        raise HTTPException(400, "Loopback destinations do not need a decision.")

    if payload.granted:
        consent.grant(
            payload.operation,
            payload.destination_class,
            source="user",
            note=payload.note or "Allowed in Settings.",
        )
    else:
        consent.revoke(
            payload.operation,
            payload.destination_class,
            note=payload.note or "Withdrawn in Settings.",
        )
    return _operations()


@router.get("/transfers", response_model=list[TransferOut])
async def list_transfers(limit: int = 100) -> list[TransferOut]:
    """The transfer log, newest first."""
    from ..db import connection

    limit = max(1, min(limit, 500))
    try:
        with connection() as conn:
            rows = conn.execute(
                "SELECT occurred_at, operation, provider, destination, destination_class, "
                "data_summary, outcome, detail, duration_ms FROM egress_log "
                "ORDER BY id DESC LIMIT ?",
                (limit,),
            ).fetchall()
    except Exception as exc:  # noqa: BLE001 - an unmigrated database has no log yet
        log.debug("Could not read the egress log: %s", exc)
        return []

    return [
        TransferOut(
            occurred_at=row["occurred_at"],
            operation=row["operation"],
            provider=row["provider"],
            destination=row["destination"],
            destination_class=row["destination_class"],
            data_summary=row["data_summary"],
            outcome=row["outcome"],
            detail=row["detail"],
            duration_ms=row["duration_ms"],
        )
        for row in rows
    ]


__all__ = ["router"]
