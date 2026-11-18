"""Multi Google-account / multi YouTube-channel store.

Extends the original single-account OAuth without replacing it: the legacy
connection stays the default account, and new accounts are additive rows.
Refresh tokens are per-account keyring entries (``youtube_refresh#<id>``);
the legacy bare entry (``youtube_refresh_token``) belongs to the first
migrated account.
"""

from __future__ import annotations

import logging
import sqlite3
from typing import Any

from .. import config
from ..db import schema
from ..db.models import new_id, utcnow
from ..db.store import connection

log = logging.getLogger(__name__)


def _refresh_entry(account_id: str) -> str:
    """Per-account keyring entry. The legacy entry is claimed at migration."""
    return f"youtube_refresh#{account_id}"


def legacy_refresh_token(settings: config.Settings | None = None) -> str | None:
    return config.get_secret(schema.LEGACY_REFRESH_KEY, settings)


def claim_legacy_token(account_id: str, settings: config.Settings | None = None) -> bool:
    """Move the legacy refresh token under the account's own keyring entry.

    Returns True when a legacy token existed and was claimed. The legacy entry
    is kept (not deleted) so older code paths that read it keep working.
    """
    token = legacy_refresh_token(settings)
    if not token:
        return False
    config.set_secret(_refresh_entry(account_id), token, settings)
    return True


# --------------------------------------------------------------------------
# Accounts
# --------------------------------------------------------------------------


def list_accounts() -> list[dict[str, Any]]:
    with connection() as conn:
        rows = conn.execute(
            "SELECT id, label, email, client_id, connected_at, created_at"
            " FROM google_accounts ORDER BY created_at"
        ).fetchall()
    return [
        {
            "id": r[0],
            "label": r[1],
            "email": r[2],
            "client_id": r[3],
            "connected_at": r[4],
            "created_at": r[5],
        }
        for r in rows
    ]


def get_account(account_id: str) -> dict[str, Any] | None:
    with connection() as conn:
        row = conn.execute(
            "SELECT id, label, email, client_id, connected_at, created_at"
            " FROM google_accounts WHERE id = ?",
            (account_id,),
        ).fetchone()
    if row is None:
        return None
    return {
        "id": row[0],
        "label": row[1],
        "email": row[2],
        "client_id": row[3],
        "connected_at": row[4],
        "created_at": row[5],
    }


def create_account(
    label: str = "", email: str = "", client_id: str = "", *, account_id: str | None = None
) -> dict[str, Any]:
    aid = account_id or new_id()
    with connection() as conn:
        conn.execute(
            "INSERT INTO google_accounts (id, label, email, client_id, connected_at, created_at)"
            " VALUES (?, ?, ?, ?, ?, ?)",
            (aid, label, email, client_id, utcnow(), utcnow()),
        )
    account = get_account(aid)
    assert account is not None
    return account


def update_account(account_id: str, **fields: str) -> dict[str, Any] | None:
    allowed = {"label", "email", "client_id", "connected_at"}
    updates = {k: v for k, v in fields.items() if k in allowed}
    if not updates:
        return get_account(account_id)
    sets = ", ".join(f"{k} = ?" for k in updates)
    with connection() as conn:
        conn.execute(
            f"UPDATE google_accounts SET {sets} WHERE id = ?",  # noqa: S608 - whitelisted keys
            (*updates.values(), account_id),
        )
    return get_account(account_id)


def delete_account(account_id: str) -> None:
    """Remove the account, its channels, and its refresh token."""
    with connection() as conn:
        conn.execute("DELETE FROM google_accounts WHERE id = ?", (account_id,))
    config.delete_secret(_refresh_entry(account_id))


def default_account() -> dict[str, Any] | None:
    """The first-created account, mirroring the legacy single-account setup."""
    with connection() as conn:
        row = conn.execute(
            "SELECT id FROM google_accounts ORDER BY created_at LIMIT 1"
        ).fetchone()
    return get_account(row[0]) if row else None


# --------------------------------------------------------------------------
# Channels
# --------------------------------------------------------------------------


def list_channels(account_id: str | None = None) -> list[dict[str, Any]]:
    query = (
        "SELECT id, account_id, channel_id, title, url, is_default, privacy,"
        " category_id, auto_upload, title_suffix, created_at, updated_at FROM youtube_channels"
    )
    params: tuple[Any, ...] = ()
    if account_id:
        query += " WHERE account_id = ?"
        params = (account_id,)
    query += " ORDER BY is_default DESC, created_at"
    with connection() as conn:
        rows = conn.execute(query, params).fetchall()
    return [_channel_row(r) for r in rows]


def get_channel(channel_row_id: str) -> dict[str, Any] | None:
    with connection() as conn:
        row = conn.execute(
            "SELECT id, account_id, channel_id, title, url, is_default, privacy,"
            " category_id, auto_upload, title_suffix, created_at, updated_at"
            " FROM youtube_channels WHERE id = ?",
            (channel_row_id,),
        ).fetchone()
    return _channel_row(row) if row else None


def _channel_row(r: tuple[Any, ...]) -> dict[str, Any]:
    return {
        "id": r[0],
        "account_id": r[1],
        "channel_id": r[2],
        "title": r[3],
        "url": r[4],
        "is_default": bool(r[5]),
        "privacy": r[6],
        "category_id": r[7],
        "auto_upload": bool(r[8]),
        "title_suffix": r[9],
        "created_at": r[10],
        "updated_at": r[11],
    }


def add_channel(
    account_id: str,
    channel: dict[str, str],
    *,
    is_default: bool | None = None,
    privacy: str = "public",
    category_id: str = "24",
    auto_upload: bool = False,
    title_suffix: str = "",
) -> dict[str, Any]:
    """Register a channel under an account. First channel becomes default."""
    row_id = new_id()
    if is_default is None:
        is_default = not list_channels(account_id)
    now = utcnow()
    with connection() as conn:
        if is_default:
            conn.execute("UPDATE youtube_channels SET is_default = 0 WHERE account_id = ?",
                         (account_id,))
        conn.execute(
            "INSERT INTO youtube_channels (id, account_id, channel_id, title, url,"
            " is_default, privacy, category_id, auto_upload, title_suffix, created_at, updated_at)"
            " VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (row_id, account_id, channel["id"], channel.get("title", ""),
             channel.get("url", ""), int(is_default), privacy, category_id,
             int(auto_upload), title_suffix, now, now),
        )
    result = get_channel(row_id)
    assert result is not None
    return result


def update_channel(channel_row_id: str, **fields: Any) -> dict[str, Any] | None:
    allowed = {"privacy", "category_id", "auto_upload", "is_default", "title", "title_suffix"}
    updates = {k: v for k, v in fields.items() if k in allowed}
    if not updates:
        return get_channel(channel_row_id)
    channel = get_channel(channel_row_id)
    if channel is None:
        return None
    if updates.get("is_default"):
        with connection() as conn:
            conn.execute(
                "UPDATE youtube_channels SET is_default = 0 WHERE account_id = ?",
                (channel["account_id"],),
            )
    sets = ", ".join(f"{k} = ?" for k in updates)
    with connection() as conn:
        conn.execute(
            f"UPDATE youtube_channels SET {sets}, updated_at = ? WHERE id = ?",  # noqa: S608
            (*updates.values(), utcnow(), channel_row_id),
        )
    return get_channel(channel_row_id)


def delete_channel(channel_row_id: str) -> None:
    with connection() as conn:
        conn.execute("DELETE FROM youtube_channels WHERE id = ?", (channel_row_id,))


def default_channel(account_id: str | None = None) -> dict[str, Any] | None:
    with connection() as conn:
        if account_id:
            row = conn.execute(
                "SELECT id FROM youtube_channels WHERE account_id = ? AND is_default = 1",
                (account_id,),
            ).fetchone()
        else:
            row = conn.execute(
                "SELECT id FROM youtube_channels WHERE is_default = 1"
            ).fetchone()
    return get_channel(row[0]) if row else None


def refresh_token_for(account_id: str, settings: config.Settings | None = None) -> str | None:
    """Refresh token for an account: per-account entry, then legacy fallback."""
    token = config.get_secret(_refresh_entry(account_id), settings)
    if token:
        return token
    # Legacy fallback: exactly one account exists from the pre-multi era.
    return legacy_refresh_token(settings)


def ensure_legacy_migrated(settings: config.Settings | None = None) -> None:
    """Import the single-account connection as the default row, once.

    Runs on startup. If the legacy settings hold a channel but no row exists
    yet, create the account + channel and claim the legacy refresh token.
    """
    settings = settings or config.load()
    if not settings.youtube.channel_id:
        return
    if not config.get_secret(schema.LEGACY_REFRESH_KEY, settings):
        return
    if list_accounts():
        return  # already migrated or new-style accounts exist

    account = create_account(
        label="Default account",
        client_id=settings.youtube.client_id,
    )
    claim_legacy_token(account["id"], settings)
    add_channel(
        account["id"],
        {
            "id": settings.youtube.channel_id,
            "title": settings.youtube.channel_title,
            "url": settings.youtube.channel_url,
        },
        is_default=True,
        privacy=settings.youtube.privacy,
        category_id=settings.youtube.category_id,
        auto_upload=settings.youtube.auto_upload,
    )
    log.info("Migrated the legacy YouTube connection to multi-account storage.")


def _connect_version(conn: sqlite3.Connection) -> int:  # pragma: no cover - test helper
    return int(conn.execute("PRAGMA user_version").fetchone()[0])


__all__ = [
    "add_channel",
    "claim_legacy_token",
    "create_account",
    "default_account",
    "default_channel",
    "delete_account",
    "delete_channel",
    "ensure_legacy_migrated",
    "get_account",
    "get_channel",
    "legacy_refresh_token",
    "list_accounts",
    "list_channels",
    "refresh_token_for",
    "update_account",
    "update_channel",
]
