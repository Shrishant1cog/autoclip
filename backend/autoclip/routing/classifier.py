"""Intelligent content classification and user-defined channel routing.

A clip's transcript is classified by AI into a content category (gaming,
podcast, education, …). The user's routing rules map classification keywords
to target channel profiles. When no rule matches (or the classifier fails),
uploads go to the default channel — the pre-routing behaviour, preserved.
"""

from __future__ import annotations

import json
import logging
from typing import Any

from .. import config
from ..db.models import new_id, utcnow
from ..db.store import connection
from ..providers.base import extract_json_object
from ..providers.resolver import AllProvidersFailedError, run_with_fallback
from ..youtube import accounts as accounts_store

log = logging.getLogger(__name__)

#: Categories the classifier chooses from. Free-form extras are allowed but
#: these seed the prompt and the settings UI.
CATEGORIES = [
    "gaming",
    "podcast",
    "education",
    "entertainment",
    "sports",
    "music",
    "news",
    "technology",
    "comedy",
    "other",
]

SYSTEM_PROMPT = """You classify short video clips for channel routing.
Reply with ONE JSON object and nothing else."""

USER_TEMPLATE = """Classify this clip's content.

Transcript:
---
{transcript}
---

Clip title: {title}

Return JSON with exactly these keys:
{{
  "category": "one of: {categories}",
  "confidence": 0.0,
  "reason": "one short sentence"
}}"""


# --------------------------------------------------------------------------
# Classification
# --------------------------------------------------------------------------


def classify_transcript_sync(
    transcript: str, title: str = "", *, task: str = "classification"
) -> dict[str, Any] | None:
    """Classify via the provider fallback chain. None → unclassified.

    Synchronous wrapper: the pipeline worker runs stages in threads, and the
    async chain needs a loop. Never raises — a classification failure must not
    break a pipeline that already produced a clip.
    """
    import asyncio

    if not transcript.strip():
        return None

    prompt = USER_TEMPLATE.format(
        transcript=transcript[:4000],
        title=title or "Untitled",
        categories=", ".join(CATEGORIES),
    )
    try:
        output, provider_label = asyncio.run(
            run_with_fallback(task, SYSTEM_PROMPT, prompt, config.load())
        )
    except (AllProvidersFailedError, Exception) as exc:  # noqa: BLE001
        log.warning("Classification failed (%s); clip stays unclassified.", exc)
        return None

    try:
        payload = extract_json_object(output)
        category = str(payload.get("category", "other")).strip().lower() or "other"
        return {
            "category": category,
            "confidence": float(payload.get("confidence", 0.0)),
            "provider": provider_label,
            "reason": str(payload.get("reason", ""))[:300],
        }
    except (ValueError, TypeError) as exc:
        log.warning("Classification output was not valid JSON (%s).", exc)
        return None


def save_classification(clip_id: str, result: dict[str, Any] | None) -> dict[str, Any] | None:
    """Persist a classification result; None clears (no row is written)."""
    if result is None:
        return None
    with connection() as conn:
        conn.execute(
            "INSERT INTO content_classifications"
            " (id, clip_id, category, confidence, provider, reason, created_at)"
            " VALUES (?, ?, ?, ?, ?, ?, ?)",
            (
                new_id(),
                clip_id,
                result["category"],
                result["confidence"],
                result["provider"],
                result["reason"],
                utcnow(),
            ),
        )
    return result


def classification_for(clip_id: str) -> dict[str, Any] | None:
    """The latest classification for a clip, or None."""
    with connection() as conn:
        row = conn.execute(
            "SELECT category, confidence, provider, reason, created_at"
            " FROM content_classifications WHERE clip_id = ?"
            " ORDER BY created_at DESC LIMIT 1",
            (clip_id,),
        ).fetchone()
    if row is None:
        return None
    return {
        "clip_id": clip_id,
        "category": row[0],
        "confidence": row[1],
        "provider": row[2],
        "reason": row[3],
        "created_at": row[4],
    }


# --------------------------------------------------------------------------
# Routing rules
# --------------------------------------------------------------------------


def list_rules(*, enabled_only: bool = False) -> list[dict[str, Any]]:
    query = (
        "SELECT id, name, match_keyword, target_channel_id, priority, enabled,"
        " extra_channel_ids_json, created_at, updated_at FROM routing_rules"
    )
    if enabled_only:
        query += " WHERE enabled = 1"
    query += " ORDER BY priority, created_at"
    with connection() as conn:
        rows = conn.execute(query).fetchall()
    return [_rule_row(r) for r in rows]


def _rule_row(r: tuple[Any, ...]) -> dict[str, Any]:
    return {
        "id": r[0],
        "name": r[1],
        "match_keyword": r[2],
        "target_channel_id": r[3],
        "priority": r[4],
        "enabled": bool(r[5]),
        "extra_channel_ids": json.loads(r[6] or "[]"),
        "created_at": r[7],
        "updated_at": r[8],
    }


def get_rule(rule_id: str) -> dict[str, Any] | None:
    with connection() as conn:
        row = conn.execute(
            "SELECT id, name, match_keyword, target_channel_id, priority, enabled,"
            " extra_channel_ids_json, created_at, updated_at FROM routing_rules WHERE id = ?",
            (rule_id,),
        ).fetchone()
    return _rule_row(row) if row else None


def add_rule(
    match_keyword: str,
    target_channel_id: str,
    *,
    name: str = "",
    priority: int = 100,
    enabled: bool = True,
    extra_channel_ids: list[str] | None = None,
) -> dict[str, Any]:
    now = utcnow()
    rule_id = new_id()
    with connection() as conn:
        conn.execute(
            "INSERT INTO routing_rules (id, name, match_keyword, target_channel_id,"
            " priority, enabled, extra_channel_ids_json, created_at, updated_at)"
            " VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (
                rule_id,
                name,
                match_keyword.lower(),
                target_channel_id,
                priority,
                int(enabled),
                json.dumps(extra_channel_ids or []),
                now,
                now,
            ),
        )
    result = get_rule(rule_id)
    assert result is not None
    return result


def update_rule(rule_id: str, **fields: Any) -> dict[str, Any] | None:
    allowed = {
        "name",
        "match_keyword",
        "target_channel_id",
        "priority",
        "enabled",
        "extra_channel_ids",
    }
    updates = {k: v for k, v in fields.items() if k in allowed}
    if not updates:
        return get_rule(rule_id)
    if "match_keyword" in updates:
        updates["match_keyword"] = str(updates["match_keyword"]).lower()
    if "extra_channel_ids" in updates:
        updates["extra_channel_ids_json"] = json.dumps(updates.pop("extra_channel_ids") or [])
    sets = ", ".join(f"{k} = ?" for k in updates)
    with connection() as conn:
        conn.execute(
            f"UPDATE routing_rules SET {sets}, updated_at = ? WHERE id = ?",  # noqa: S608
            (*updates.values(), utcnow(), rule_id),
        )
    return get_rule(rule_id)


def delete_rule(rule_id: str) -> None:
    with connection() as conn:
        conn.execute("DELETE FROM routing_rules WHERE id = ?", (rule_id,))


# --------------------------------------------------------------------------
# Routing decision
# --------------------------------------------------------------------------


def resolve_target_channel(
    clip_id: str, settings: config.Settings | None = None
) -> dict[str, Any] | None:
    """Which channel row should carry this clip's upload?

    Order: first enabled routing rule whose keyword matches the clip's
    classification (or title/keywords as a fallback), else the default channel.
    Returns the full youtube_channels row or None (no channels at all).
    """
    settings = settings or config.load()
    classification = classification_for(clip_id)
    # Currently the category drives matching; clip title keywords can join the
    # haystack later without changing the rule semantics.
    haystack = classification["category"] if classification is not None else ""

    hay = haystack.lower()
    for rule in list_rules(enabled_only=True):
        if rule["match_keyword"] in hay:
            channel = accounts_store.get_channel(rule["target_channel_id"])
            if channel is not None:
                log.info(
                    "Routing clip %s to %s via rule %r.",
                    clip_id,
                    channel["channel_id"],
                    rule["match_keyword"],
                )
                return channel

    return accounts_store.default_channel()


def resolve_target_channels(
    clip_id: str, settings: config.Settings | None = None
) -> list[dict[str, Any]]:
    """Every channel this clip should publish to, primary first.

    Routing rules name a primary target plus optional extra channels; that is
    the fan-out used by auto-publishing. Channels whose own ``auto_upload`` is
    off are dropped from the fan-out, so a subscriber-only channel is not
    published to by surprise. With no channel profiles at all this returns an
    empty list, and the caller falls back to the legacy single upload.
    """
    settings = settings or config.load()
    classification = classification_for(clip_id)
    hay = (classification["category"] if classification is not None else "").lower()

    primary: dict[str, Any] | None = None
    extras: list[dict[str, Any]] = []
    for rule in list_rules(enabled_only=True):
        if rule["match_keyword"] in hay:
            channel = accounts_store.get_channel(rule["target_channel_id"])
            if channel is not None:
                log.info(
                    "Routing clip %s to %s via rule %r.",
                    clip_id,
                    channel["channel_id"],
                    rule["match_keyword"],
                )
                primary = channel
                for extra_id in rule.get("extra_channel_ids") or []:
                    extra = accounts_store.get_channel(extra_id)
                    if extra is not None:
                        extras.append(extra)
            break
    else:
        default = accounts_store.default_channel()
        if default is not None:
            primary = default

    if primary is None:
        return []

    ordered: list[dict[str, Any]] = []
    seen: set[str] = set()
    for channel in [primary, *extras]:
        # Two profiles can point at the same underlying YouTube channel (for
        # example the default profile plus a hand-added duplicate); publishing
        # twice to one channel would be a duplicate upload, so collapse them.
        identity = f"{channel['account_id']}:{channel['channel_id'] or channel['id']}"
        if identity in seen:
            continue
        seen.add(identity)
        if not channel.get("auto_upload"):
            log.info(
                "Channel %s has auto-upload off; skipping fan-out for clip %s.",
                channel["channel_id"],
                clip_id,
            )
            continue
        ordered.append(channel)
    return ordered
