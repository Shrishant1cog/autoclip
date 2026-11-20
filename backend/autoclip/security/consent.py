"""External-transfer consent and the log of what actually left the machine.

Two things live here, and they are deliberately the same kind of object:

* a **consent decision** — "the user allows transcript text to go to a public
  destination for highlight detection";
* a **transfer record** — "at 14:03, a transcript window went to a public
  destination for highlight detection, and the call succeeded".

Keeping them together means the user can always answer the only question that
matters about privacy: *what left this machine, and did I allow it?*

The consent model is deliberately narrow. A decision is scoped to an
**operation** (transcription, voiceover, highlight detection, …) and a
**destination class** (loopback, private, public). It is not scoped to a host,
because the useful question is "may transcript text leave the machine at all",
and the class is what determines the risk: a private address reaches a device
on the user's own network, a public address reaches a third party.

Two classes never need a decision. ``loopback`` is the same machine and is
allowed by default (with a warning, because a tunnel can forward it). Every
other class needs a granted decision.

Re-classification is automatic. A consent decision names a class, not a host,
so changing a provider's ``base_url`` from a public host to a private one
immediately stops matching the public decision and the transfer is refused
until the private class is granted.
"""

from __future__ import annotations

import sqlite3
import time
from dataclasses import dataclass, field
from typing import Protocol

from ..db import connection

__all__ = [
    "ConsentDecision",
    "ConsentStore",
    "MemoryConsentStore",
    "SqliteConsentStore",
    "TransferRecord",
    "all_operations",
    "grant",
    "has_consent",
    "list_decisions",
    "log_transfer",
    "revoke",
]


class Operation:
    """The transfer operations AutoClip performs.

    These are the vocabulary the consent decisions are written in. They are
    stable strings because they end up in the database and in the UI.
    """

    #: Extracted audio is sent to an external speech-to-text service.
    TRANSCRIPTION = "transcription"
    #: Generated narration text is sent to an external text-to-speech service.
    VOICEOVER = "voiceover"
    #: Transcript text and standing instructions are sent to an LLM provider.
    HIGHLIGHTS = "highlights"
    #: A structured creative plan is requested from an LLM provider.
    CREATIVE_PLANNING = "creative_planning"
    #: The measured metadata of candidate music tracks is sent to an LLM
    #: provider so it can propose a track. No audio and no file path is ever
    #: sent.
    MUSIC_SELECTION = "music_selection"
    #: A rendered clip and its metadata are sent to a publishing API.
    PUBLISHING = "publishing"
    #: yt-dlp fetches a page and its media from a user-supplied URL.
    MEDIA_DOWNLOAD = "media_download"
    #: A model file is downloaded from a model host.
    MODEL_DOWNLOAD = "model_download"
    #: A public trending chart is read from the YouTube API.
    TRENDS = "trends"

    @classmethod
    def all(cls) -> tuple[str, ...]:
        return (
            cls.TRANSCRIPTION,
            cls.VOICEOVER,
            cls.HIGHLIGHTS,
            cls.CREATIVE_PLANNING,
            cls.MUSIC_SELECTION,
            cls.PUBLISHING,
            cls.MEDIA_DOWNLOAD,
            cls.MODEL_DOWNLOAD,
            cls.TRENDS,
        )


#: Human-readable explanation of what each operation sends. The Settings
#: screen shows this text, so it has to say what leaves the machine, not what
#: the function is called.
OPERATION_DESCRIPTIONS: dict[str, dict[str, str]] = {
    Operation.TRANSCRIPTION: {
        "title": "External transcription",
        "data": "The extracted audio of your source video.",
        "why": "The external speech-to-text service needs the audio to produce a transcript.",
    },
    Operation.VOICEOVER: {
        "title": "External voiceover",
        "data": "The narration text written for each clip.",
        "why": "The external voice service needs the text to synthesize a voiceover.",
    },
    Operation.HIGHLIGHTS: {
        "title": "AI highlight detection",
        "data": "Transcript windows and your standing instructions (improve.txt).",
        "why": "The language model needs the text to propose clips and explain why.",
    },
    Operation.CREATIVE_PLANNING: {
        "title": "AI creative planning",
        "data": (
            "Your clip titles, boundaries, the layout that was detected and the "
            "measured metadata of your music."
        ),
        "why": (
            "The language model needs to see the clips to recommend a layout, a "
            "caption strategy and a music track."
        ),
    },
    Operation.MUSIC_SELECTION: {
        "title": "AI music selection",
        "data": (
            "The measured metadata of your music tracks — tempo, energy, mood, "
            "loudness. Never the audio, and never a file path."
        ),
        "why": "The language model needs the measurements to propose a track for a clip.",
    },
    Operation.PUBLISHING: {
        "title": "Publishing",
        "data": "The rendered clip, its thumbnail and its metadata.",
        "why": "The platform needs the media to publish it.",
    },
    Operation.MEDIA_DOWNLOAD: {
        "title": "Source downloads",
        "data": "No content of yours — a page and a media file are fetched from the URL you gave.",
        "why": "The downloader needs to reach the URL and the servers it redirects to.",
    },
    Operation.MODEL_DOWNLOAD: {
        "title": "Model downloads",
        "data": "No content of yours — a model file is fetched from its model host.",
        "why": "Face detection and transcription need their model weights.",
    },
    Operation.TRENDS: {
        "title": "Trending chart",
        "data": "No content of yours — a public chart is read from the YouTube API.",
        "why": "The Trends screen shows the public most-popular chart.",
    },
}


@dataclass(frozen=True)
class ConsentDecision:
    """A stored answer to "may this operation reach this class of host?"."""

    operation: str
    destination_class: str
    granted: bool
    source: str = ""
    decided_at: str = ""
    note: str = ""

    def describe(self) -> dict[str, object]:
        """A JSON-safe view for the API. Never contains a credential."""
        return {
            "operation": self.operation,
            "destination_class": self.destination_class,
            "granted": self.granted,
            "source": self.source,
            "decided_at": self.decided_at,
            "note": self.note,
            "title": OPERATION_DESCRIPTIONS.get(self.operation, {}).get("title", self.operation),
            "data": OPERATION_DESCRIPTIONS.get(self.operation, {}).get("data", ""),
            "why": OPERATION_DESCRIPTIONS.get(self.operation, {}).get("why", ""),
        }


@dataclass(frozen=True)
class TransferRecord:
    """One outbound transfer, successful or not."""

    operation: str
    destination: str
    destination_class: str
    outcome: str
    provider: str = ""
    data_summary: str = ""
    detail: str = ""
    duration_ms: int = 0
    occurred_at: str = ""


class ConsentStore(Protocol):
    """Where consent decisions live."""

    def get(self, operation: str, destination_class: str) -> ConsentDecision | None: ...

    def set(self, decision: ConsentDecision) -> None: ...

    def all(self) -> list[ConsentDecision]: ...


@dataclass
class MemoryConsentStore:
    """An in-memory store, used by tests and by the pipeline's dry runs."""

    decisions: dict[tuple[str, str], ConsentDecision] = field(default_factory=dict)

    def get(self, operation: str, destination_class: str) -> ConsentDecision | None:
        return self.decisions.get((operation, destination_class))

    def set(self, decision: ConsentDecision) -> None:
        self.decisions[(decision.operation, decision.destination_class)] = decision

    def all(self) -> list[ConsentDecision]:
        return sorted(self.decisions.values(), key=lambda d: (d.operation, d.destination_class))


class SqliteConsentStore:
    """The real store: a table in the application's own database.

    When the database has not been migrated yet — a unit test that never
    touched the schema, a first call before startup finished — the store falls
    back to memory rather than raising. A consent check must never be the
    reason a job crashes; the fallback is also what keeps an un-migrated
    database from losing a decision silently.
    """

    def __init__(self, conn=None) -> None:
        self._conn = conn

    def _connection(self):
        if self._conn is not None:
            return self._conn
        return connection()

    def get(self, operation: str, destination_class: str) -> ConsentDecision | None:
        try:
            with self._connection() as conn:
                row = conn.execute(
                    "SELECT operation, destination_class, granted, source, decided_at, note "
                    "FROM egress_consents WHERE operation = ? AND destination_class = ?",
                    (operation, destination_class),
                ).fetchone()
        except sqlite3.OperationalError:
            return _FALLBACK.get(operation, destination_class)
        if row is None:
            return _FALLBACK.get(operation, destination_class)
        return ConsentDecision(
            operation=row["operation"],
            destination_class=row["destination_class"],
            granted=bool(row["granted"]),
            source=row["source"],
            decided_at=row["decided_at"],
            note=row["note"],
        )

    def set(self, decision: ConsentDecision) -> None:
        _FALLBACK.set(decision)
        try:
            with self._connection() as conn:
                conn.execute(
                    "INSERT INTO egress_consents "
                    "(operation, destination_class, granted, source, decided_at, note) "
                    "VALUES (?, ?, ?, ?, ?, ?) "
                    "ON CONFLICT(operation, destination_class) DO UPDATE SET "
                    "granted = excluded.granted, source = excluded.source, "
                    "decided_at = excluded.decided_at, note = excluded.note",
                    (
                        decision.operation,
                        decision.destination_class,
                        1 if decision.granted else 0,
                        decision.source,
                        decision.decided_at or _now(),
                        decision.note,
                    ),
                )
        except sqlite3.OperationalError:
            # The decision is already in the in-memory fallback.
            pass

    def all(self) -> list[ConsentDecision]:
        try:
            with self._connection() as conn:
                rows = conn.execute(
                    "SELECT operation, destination_class, granted, source, decided_at, note "
                    "FROM egress_consents ORDER BY operation, destination_class"
                ).fetchall()
        except sqlite3.OperationalError:
            return _FALLBACK.all()
        decisions = [
            ConsentDecision(
                operation=row["operation"],
                destination_class=row["destination_class"],
                granted=bool(row["granted"]),
                source=row["source"],
                decided_at=row["decided_at"],
                note=row["note"],
            )
            for row in rows
        ]
        return decisions


def _now() -> str:
    return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())


#: Used when the database has not been migrated yet, so a decision is not lost.
_FALLBACK = MemoryConsentStore()


def _store() -> ConsentStore:
    return SqliteConsentStore()


def grant(
    operation: str,
    destination_class: str,
    *,
    source: str = "user",
    note: str = "",
) -> ConsentDecision:
    """Allow ``operation`` to reach ``destination_class``."""
    decision = ConsentDecision(
        operation=operation,
        destination_class=destination_class,
        granted=True,
        source=source,
        decided_at=_now(),
        note=note,
    )
    _store().set(decision)
    return decision


def revoke(operation: str, destination_class: str, *, note: str = "") -> ConsentDecision:
    """Withdraw consent for ``operation`` reaching ``destination_class``."""
    decision = ConsentDecision(
        operation=operation,
        destination_class=destination_class,
        granted=False,
        source="user",
        decided_at=_now(),
        note=note,
    )
    _store().set(decision)
    return decision


def list_decisions() -> list[ConsentDecision]:
    """Every stored decision."""
    return _store().all()


def has_consent(operation: str, destination_class: str) -> bool:
    """Whether the operation may reach that class of destination."""
    decision = _store().get(operation, destination_class)
    return bool(decision and decision.granted)


def log_transfer(record: TransferRecord) -> None:
    """Append one transfer to the log.

    Logging must never fail the operation it is describing, so a storage
    problem is swallowed — but it is also loud in the log, because a silently
    missing audit trail is worse than a noisy one.
    """
    payload = record.occurred_at or _now()
    try:
        with connection() as conn:
            conn.execute(
                "INSERT INTO egress_log "
                "(occurred_at, operation, provider, destination, destination_class, "
                " data_summary, outcome, detail, duration_ms) "
                "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (
                    payload,
                    record.operation,
                    record.provider,
                    record.destination,
                    record.destination_class,
                    record.data_summary,
                    record.outcome,
                    record.detail,
                    record.duration_ms,
                ),
            )
    except Exception as exc:  # noqa: BLE001 - an audit write must not break the app
        import logging

        logging.getLogger(__name__).warning("Could not write the egress log: %s", exc)


def all_operations() -> dict[str, dict[str, str]]:
    """Operation metadata for the Settings screen."""
    return {name: dict(meta) for name, meta in OPERATION_DESCRIPTIONS.items()}
