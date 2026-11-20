"""The six-field routing explanation.

A routing decision answers one question: which channel does this clip
go to, and why? The answer has six parts, and every one of them is
recorded:

* **category** — what the clip was classified as,
* **channel** — where it is going,
* **reason** — the sentence that explains it,
* **rule** — the user's rule that decided it, if any,
* **confidence** — how sure the classification was,
* **fallback** — whether this was the default rather than a rule.

The point is that the owner can read a decision back. A clip that went
somewhere unexpected should not need a database query to explain
itself: the decision says which keyword matched, which rule fired, how
confident the classifier was, and whether the route was a fallback.

A decision is *recorded* when it is made — when the fan-out for a
publish is decided — and it is also *computed* on demand, so the
interface can show what would happen before anything is published.

The confidence is the classifier's own number: the figure the model
reported when it read the transcript. It is not a quality score, and
there is no other score anywhere in here.
"""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass, replace
from typing import Any

from ..db.models import new_id, utcnow
from ..db.store import connection
from ..youtube import accounts as accounts_store

log = logging.getLogger(__name__)

__all__ = [
    "RoutingDecision",
    "decide",
    "decide_all",
    "latest_for",
    "recent",
    "record",
    "record_all",
    "resolve",
]


@dataclass(frozen=True)
class RoutingDecision:
    """One routing decision, and the six fields that explain it.

    The six fields are ``category``, ``channel`` (the three channel
    columns), ``reason``, ``rule`` (the three rule columns plus the
    display label), ``confidence`` and ``fallback``. The rest is
    supporting detail: which channels the same rule fans out to, when
    the decision was recorded, and whether the destination's own
    auto-upload is on.
    """

    #: The clip the decision is about.
    clip_id: str = ""
    #: The category the clip was classified as. Empty when it has not
    #: been classified at all.
    category: str = ""
    #: The channel *row* this clip goes to (``youtube_channels.id``).
    channel_row_id: str = ""
    #: The YouTube channel id behind that row.
    channel_id: str = ""
    #: The channel's title, for the person reading it.
    channel_title: str = ""
    #: The sentence that explains the decision.
    reason: str = ""
    #: The rule that decided it. Empty when no rule did.
    rule_id: str = ""
    #: The rule's own name, when the owner gave it one.
    rule_name: str = ""
    #: The keyword the rule matched on.
    rule_keyword: str = ""
    #: The classifier's confidence in the category, 0–1. The model's own
    #: reported figure, not an invented quality number.
    confidence: float = 0.0
    #: True when the decision did not come from a rule.
    fallback: bool = False
    #: Why it was a fallback: "no rule matched", "no classification".
    fallback_reason: str = ""
    #: The other channel rows the same rule sends the clip to.
    extra_channel_ids: tuple[str, ...] = ()
    #: Whether the destination's own auto-upload is on. A channel with
    #: auto-upload off is never published to by surprise.
    auto_upload: bool = True
    #: When the decision was recorded.
    created_at: str = ""

    @property
    def rule(self) -> str:
        """The rule, as a person reads it."""
        return self.rule_name or self.rule_keyword

    def to_dict(self) -> dict[str, Any]:
        return {
            "clip_id": self.clip_id,
            "category": self.category,
            "channel_row_id": self.channel_row_id,
            "channel_id": self.channel_id,
            "channel_title": self.channel_title,
            "reason": self.reason,
            "rule_id": self.rule_id,
            "rule": self.rule,
            "rule_name": self.rule_name,
            "rule_keyword": self.rule_keyword,
            "confidence": self.confidence,
            "fallback": self.fallback,
            "fallback_reason": self.fallback_reason,
            "extra_channel_ids": list(self.extra_channel_ids),
            "auto_upload": self.auto_upload,
            "created_at": self.created_at,
        }

    @classmethod
    def from_row(cls, row: Any) -> RoutingDecision:
        return cls(
            clip_id=row[0],
            category=row[1],
            channel_row_id=row[2],
            channel_id=row[3],
            channel_title=row[4],
            reason=row[5],
            rule_id=row[6],
            rule_name=row[7],
            rule_keyword=row[8],
            confidence=float(row[9] or 0.0),
            fallback=bool(row[10]),
            fallback_reason=row[11],
            extra_channel_ids=tuple(json.loads(row[12] or "[]")),
            auto_upload=bool(row[13]),
            created_at=row[14],
        )


#: The columns as they are written, with the row id first.
_INSERT_COLUMNS = (
    "id, clip_id, category, channel_row_id, channel_id, channel_title, reason,"
    " rule_id, rule_name, rule_keyword, confidence, fallback, fallback_reason,"
    " extra_channel_ids_json, auto_upload, created_at"
)

#: The columns as they are read back, in the order :meth:`RoutingDecision.from_row`
#: expects them.
_READ_COLUMNS = (
    "clip_id, category, channel_row_id, channel_id, channel_title, reason,"
    " rule_id, rule_name, rule_keyword, confidence, fallback, fallback_reason,"
    " extra_channel_ids_json, auto_upload, created_at"
)


# --------------------------------------------------------------------------
# Working out the decision
# --------------------------------------------------------------------------


@dataclass(frozen=True)
class _Resolution:
    """The raw ingredients of a decision, before it is phrased."""

    classification: dict[str, Any] | None
    rule: dict[str, Any] | None
    primary: dict[str, Any] | None
    extras: tuple[dict[str, Any], ...]
    #: The channels the clip is actually sent to, primary first.
    ordered: tuple[dict[str, Any], ...]


def _resolve(clip_id: str) -> _Resolution:
    """Work out where this clip goes, and why.

    The user's rule comes first: the first enabled rule whose keyword
    appears in the clip's category decides the destination. When no rule
    does, the default channel is used — and that is a *fallback*,
    recorded as such rather than presented as if a rule had chosen it.

    A rule that points at a channel which no longer exists cannot fire,
    so the next rule is tried.
    """
    # Imported here rather than at the top of the module: the classifier
    # is the one that calls into this module, and a module-level import
    # in both directions is a cycle.
    from . import classifier

    classification = classifier.classification_for(clip_id)
    category = str((classification or {}).get("category", "") or "")
    hay = category.lower()

    rule: dict[str, Any] | None = None
    primary: dict[str, Any] | None = None
    extras: list[dict[str, Any]] = []
    for candidate in classifier.list_rules(enabled_only=True):
        if candidate["match_keyword"] not in hay:
            continue
        channel = accounts_store.get_channel(candidate["target_channel_id"])
        if channel is None:
            log.info(
                "Routing rule %r points at a channel that no longer exists; skipping it.",
                candidate["match_keyword"],
            )
            continue
        rule = candidate
        primary = channel
        for extra_id in candidate.get("extra_channel_ids") or []:
            extra = accounts_store.get_channel(extra_id)
            if extra is not None:
                extras.append(extra)
        break

    if rule is None:
        primary = accounts_store.default_channel()

    if primary is not None and rule is not None:
        log.info(
            "Routing clip %s to %s via rule %r.",
            clip_id,
            primary["channel_id"],
            rule["match_keyword"],
        )

    return _Resolution(
        classification=classification,
        rule=rule,
        primary=primary,
        extras=tuple(extras),
        ordered=tuple(_ordered([primary, *extras])),
    )


def _ordered(channels: list[dict[str, Any] | None]) -> list[dict[str, Any]]:
    """The channels a clip is really sent to, primary first.

    Two profiles can point at the same underlying YouTube channel, and
    publishing twice to one channel would be a duplicate upload, so
    duplicates collapse. A channel whose own auto-upload is off is left
    out, so a subscriber-only channel is never published to by surprise.
    """
    ordered: list[dict[str, Any]] = []
    seen: set[str] = set()
    for channel in channels:
        if channel is None:
            continue
        identity = f"{channel['account_id']}:{channel['channel_id'] or channel['id']}"
        if identity in seen:
            continue
        seen.add(identity)
        if not channel.get("auto_upload"):
            log.info(
                "Channel %s has auto-upload off; leaving it out of the fan-out.",
                channel["channel_id"],
            )
            continue
        ordered.append(channel)
    return ordered


def _explain(
    *,
    category: str,
    confidence: float,
    classifier_reason: str,
    rule: dict[str, Any] | None,
    has_channel: bool,
) -> tuple[str, str]:
    """The sentence that explains the decision, and why it was a fallback."""
    if rule is not None:
        label = str(rule.get("name") or rule.get("match_keyword") or "a rule")
        sentence = f"The rule “{label}” matched the category “{category}”"
        fallback_reason = ""
    elif category:
        sentence = f"No rule matched the category “{category}”"
        fallback_reason = "no rule matched"
    else:
        sentence = "This clip has not been classified, so no rule could match it"
        fallback_reason = "no classification"

    if category:
        sentence += f" (confidence {confidence:.2f})"
    sentence += "."

    if classifier_reason:
        sentence += f" The classifier said: “{classifier_reason}”."

    if not has_channel:
        sentence += " There is no channel to send it to."
    elif rule is None:
        sentence += " It went to the default channel."

    return sentence, fallback_reason


def _build(
    clip_id: str,
    resolution: _Resolution,
    channel: dict[str, Any] | None,
    *,
    extra_ids: tuple[str, ...] = (),
) -> RoutingDecision:
    """Phrase a resolution into a decision."""
    classification = resolution.classification or {}
    category = str(classification.get("category", "") or "")
    confidence = float(classification.get("confidence", 0.0) or 0.0)
    classifier_reason = str(classification.get("reason", "") or "")
    rule = resolution.rule

    reason, fallback_reason = _explain(
        category=category,
        confidence=confidence,
        classifier_reason=classifier_reason,
        rule=rule,
        has_channel=channel is not None,
    )

    return RoutingDecision(
        clip_id=clip_id,
        category=category,
        channel_row_id=str((channel or {}).get("id", "") or ""),
        channel_id=str((channel or {}).get("channel_id", "") or ""),
        channel_title=str((channel or {}).get("title", "") or ""),
        reason=reason,
        rule_id=str((rule or {}).get("id", "") or ""),
        rule_name=str((rule or {}).get("name", "") or ""),
        rule_keyword=str((rule or {}).get("match_keyword", "") or ""),
        confidence=confidence,
        fallback=rule is None,
        fallback_reason=fallback_reason,
        extra_channel_ids=extra_ids,
        auto_upload=bool((channel or {}).get("auto_upload", False)),
        created_at=utcnow(),
    )


def resolve(clip_id: str) -> tuple[RoutingDecision, list[RoutingDecision]]:
    """The primary decision and the fan-out, from one pass over the rules.

    The two callers want the same answer: the interface wants the
    primary (where does this clip go, and why) and the publisher wants
    the fan-out (every channel it is sent to). Working them out
    together keeps one resolution from disagreeing with the other.
    """
    resolution = _resolve(clip_id)
    primary_id = str((resolution.primary or {}).get("id", "") or "")
    extra_ids = tuple(
        str(channel["id"]) for channel in resolution.ordered if str(channel["id"]) != primary_id
    )
    primary = _build(clip_id, resolution, resolution.primary, extra_ids=extra_ids)
    fanout = [_build(clip_id, resolution, channel) for channel in resolution.ordered]
    return primary, fanout


def decide(clip_id: str) -> RoutingDecision:
    """The decision for this clip, with the six fields that explain it.

    This is the *primary* destination — the one a rule chose, or the
    default when no rule did. It is always a decision: a clip with no
    classification and no channels gets one that says so, rather than
    nothing at all.

    It matches :func:`classifier.resolve_target_channel` exactly, and
    exists so the explanation and the destination can never drift apart.
    """
    primary, _ = resolve(clip_id)
    return primary


def decide_all(clip_id: str) -> list[RoutingDecision]:
    """Every decision in the fan-out — one per channel the clip goes to.

    The first is the primary destination; the rest come from the same
    rule's fan-out list. A channel whose own auto-upload is off is left
    out, so a subscriber-only channel is never published to by
    surprise, and the same channel is never named twice.

    It matches :func:`classifier.resolve_target_channels` exactly.
    """
    _, fanout = resolve(clip_id)
    return fanout


# --------------------------------------------------------------------------
# Recording the decision
# --------------------------------------------------------------------------


def record(decision: RoutingDecision) -> RoutingDecision:
    """Store one decision so it can be read back later.

    The decision is stored whole, so the record of what was decided does
    not depend on the rules still looking the same way afterwards. A
    rule that is edited tomorrow leaves yesterday's decision readable.
    """
    now = utcnow()
    with connection() as conn:
        conn.execute(
            f"INSERT INTO routing_decisions ({_INSERT_COLUMNS})"  # noqa: S608
            " VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (
                new_id(),
                decision.clip_id,
                decision.category,
                decision.channel_row_id,
                decision.channel_id,
                decision.channel_title,
                decision.reason,
                decision.rule_id,
                decision.rule_name,
                decision.rule_keyword,
                decision.confidence,
                int(decision.fallback),
                decision.fallback_reason,
                json.dumps(list(decision.extra_channel_ids)),
                int(decision.auto_upload),
                now,
            ),
        )
    return replace(decision, created_at=now)


def record_all(decisions: list[RoutingDecision]) -> list[RoutingDecision]:
    """Store a fan-out of decisions."""
    return [record(decision) for decision in decisions]


def latest_for(clip_id: str, limit: int = 20) -> list[RoutingDecision]:
    """The decisions recorded for this clip, newest first."""
    with connection() as conn:
        rows = conn.execute(
            f"SELECT {_READ_COLUMNS} FROM routing_decisions WHERE clip_id = ?"  # noqa: S608
            " ORDER BY created_at DESC, rowid DESC LIMIT ?",
            (clip_id, limit),
        ).fetchall()
    return [RoutingDecision.from_row(row) for row in rows]


def recent(limit: int = 20) -> list[RoutingDecision]:
    """The decisions recorded across all clips, newest first."""
    with connection() as conn:
        rows = conn.execute(
            f"SELECT {_READ_COLUMNS} FROM routing_decisions"  # noqa: S608
            " ORDER BY created_at DESC, rowid DESC LIMIT ?",
            (limit,),
        ).fetchall()
    return [RoutingDecision.from_row(row) for row in rows]
