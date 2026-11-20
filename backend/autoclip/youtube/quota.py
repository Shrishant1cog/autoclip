"""How much of YouTube's daily API quota is left, and what it was spent on.

A YouTube upload costs 1600 units. The default project quota is 10 000
units a day, which is **six uploads**. A retry that fails in a way that
sends the whole file again can therefore eat the day's quota in a
handful of attempts, and the seventh upload fails with
``quotaExceeded`` for a reason the owner cannot see.

So the cost is written down before the call is made:

* the units are reserved against the day **before** the transfer,
* a reservation that would exceed the daily limit is refused with a
  message that says when the quota comes back,
* and the day's usage is visible, so the owner can see what happened.

The numbers are YouTube's published ones, and they are recorded as
constants rather than guessed at runtime: an estimate that claims to be
exact would be a lie.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import UTC, date, datetime

from ..db.store import connection

log = logging.getLogger(__name__)

__all__ = [
    "DAILY_LIMIT",
    "QuotaExceeded",
    "QuotaLedger",
    "READ_UNITS",
    "UPLOAD_UNITS",
    "today",
]

#: What one upload costs, in quota units.
UPLOAD_UNITS = 1600

#: What one read-back costs. A list call is cheap but it is not free.
READ_UNITS = 1

#: The default daily quota for a new YouTube API project.
DAILY_LIMIT = 10000


class QuotaExceeded(RuntimeError):
    """The day's quota would be exceeded by this call."""

    def __init__(self, needed: int, used: int, limit: int) -> None:
        super().__init__(
            f"This upload needs {needed} quota units and only {max(limit - used, 0)} are "
            f"left today. YouTube's quota comes back at midnight in your own time zone."
        )
        self.needed = needed
        self.used = used
        self.limit = limit


def today() -> str:
    """Today's date, in the format the ledger keys on."""
    return date.today().isoformat()


@dataclass(frozen=True)
class QuotaLedger:
    """One day's usage."""

    day: str
    units_used: int = 0
    uploads_started: int = 0
    uploads_finished: int = 0
    limit: int = DAILY_LIMIT

    def remaining(self) -> int:
        return max(self.limit - self.units_used, 0)

    def to_dict(self) -> dict[str, object]:
        return {
            "day": self.day,
            "units_used": self.units_used,
            "uploads_started": self.uploads_started,
            "uploads_finished": self.uploads_finished,
            "limit": self.limit,
            "remaining": self.remaining(),
        }


def _row_to_ledger(row) -> QuotaLedger:  # noqa: ANN001 - a sqlite3.Row
    return QuotaLedger(
        day=row["day"],
        units_used=int(row["units_used"]),
        uploads_started=int(row["uploads_started"]),
        uploads_finished=int(row["uploads_finished"]),
    )


def read(day: str | None = None, limit: int = DAILY_LIMIT) -> QuotaLedger:
    """The ledger for a day, or for today."""
    day = day or today()
    with connection() as conn:
        row = conn.execute(
            "SELECT day, units_used, uploads_started, uploads_finished"
            " FROM youtube_quota WHERE day = ?",
            (day,),
        ).fetchone()
    if row is None:
        return QuotaLedger(day=day, limit=limit)
    ledger = _row_to_ledger(row)
    return QuotaLedger(
        day=ledger.day,
        units_used=ledger.units_used,
        uploads_started=ledger.uploads_started,
        uploads_finished=ledger.uploads_finished,
        limit=limit,
    )


def reserve(units: int = UPLOAD_UNITS, *, limit: int = DAILY_LIMIT) -> QuotaLedger:
    """Reserve quota units for a call, and refuse when there are not enough.

    The reservation is written before the call is made, so a call that
    dies halfway still shows up in the day's usage. An estimate that
    only counted the calls that succeeded would under-report exactly the
    case where the owner most needs to know.
    """
    day = today()
    with connection() as conn:
        row = conn.execute(
            "SELECT day, units_used, uploads_started, uploads_finished"
            " FROM youtube_quota WHERE day = ?",
            (day,),
        ).fetchone()
        used = int(row["units_used"]) if row is not None else 0
        if used + units > limit:
            raise QuotaExceeded(units, used, limit)
        started = int(row["uploads_started"]) if row is not None else 0
        finished = int(row["uploads_finished"]) if row is not None else 0
        conn.execute(
            """
            INSERT INTO youtube_quota
                (day, units_used, uploads_started, uploads_finished, updated_at)
            VALUES (?, ?, ?, ?, ?)
            ON CONFLICT(day) DO UPDATE SET
                units_used = excluded.units_used,
                uploads_started = excluded.uploads_started,
                uploads_finished = excluded.uploads_finished,
                updated_at = excluded.updated_at
            """,
            (day, used + units, started + (1 if units == UPLOAD_UNITS else 0), finished, utcnow()),
        )
    return read(day, limit)


def record_upload_finished(*, limit: int = DAILY_LIMIT) -> QuotaLedger:
    """Note that an upload completed. The units were already reserved."""
    day = today()
    with connection() as conn:
        row = conn.execute(
            "SELECT units_used, uploads_started, uploads_finished FROM youtube_quota WHERE day = ?",
            (day,),
        ).fetchone()
        used = int(row["units_used"]) if row is not None else 0
        started = int(row["uploads_started"]) if row is not None else 0
        finished = int(row["uploads_finished"]) if row is not None else 0
        conn.execute(
            """
            INSERT INTO youtube_quota
                (day, units_used, uploads_started, uploads_finished, updated_at)
            VALUES (?, ?, ?, ?, ?)
            ON CONFLICT(day) DO UPDATE SET
                uploads_finished = excluded.uploads_finished,
                updated_at = excluded.updated_at
            """,
            (day, used, started, finished + 1, utcnow()),
        )
    return read(day, limit)


def record_read(units: int = READ_UNITS, *, limit: int = DAILY_LIMIT) -> QuotaLedger:
    """Note the cost of a read-back."""
    day = today()
    with connection() as conn:
        row = conn.execute("SELECT units_used FROM youtube_quota WHERE day = ?", (day,)).fetchone()
        used = int(row["units_used"]) if row is not None else 0
        conn.execute(
            """
            INSERT INTO youtube_quota
                (day, units_used, uploads_started, uploads_finished, updated_at)
            VALUES (?, ?, 0, 0, ?)
            ON CONFLICT(day) DO UPDATE SET
                units_used = excluded.units_used,
                updated_at = excluded.updated_at
            """,
            (day, used + units, utcnow()),
        )
    return read(day, limit)


def utcnow() -> str:
    """The current time, in the format the ledger stores."""
    return datetime.now(UTC).isoformat(timespec="seconds")
