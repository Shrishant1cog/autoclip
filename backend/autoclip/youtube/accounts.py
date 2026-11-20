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
            "SELECT id, label, email, client_id, connected_at, created_at,"
            " needs_reconnect, last_error"
            " FROM google_accounts ORDER BY created_at, rowid"
        ).fetchall()
    return [_account_row(r) for r in rows]


def _account_row(r: tuple[Any, ...]) -> dict[str, Any]:
    return {
        "id": r[0],
        "label": r[1],
        "email": r[2],
        "client_id": r[3],
        "connected_at": r[4],
        "created_at": r[5],
        #: True when Google has refused to refresh this account's credential
        #: and the owner has to connect it again.
        "needs_reconnect": bool(r[6]),
        #: Why the connection broke, in plain words.
        "last_error": r[7],
    }


def get_account(account_id: str) -> dict[str, Any] | None:
    with connection() as conn:
        row = conn.execute(
            "SELECT id, label, email, client_id, connected_at, created_at,"
            " needs_reconnect, last_error"
            " FROM google_accounts WHERE id = ?",
            (account_id,),
        ).fetchone()
    if row is None:
        return None
    return _account_row(row)


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


def mark_needs_reconnect(account_id: str, reason: str) -> None:
    """Record that Google has refused this account's credential.

    The flag is per-account on purpose. One Google account whose refresh
    token has been revoked must not stop the other accounts from
    publishing, so only this row is marked and the reason is kept.
    """
    with connection() as conn:
        conn.execute(
            "UPDATE google_accounts SET needs_reconnect = 1, last_error = ? WHERE id = ?",
            (reason, account_id),
        )


def clear_needs_reconnect(account_id: str) -> None:
    """Forget a previous failure — the account has been connected again."""
    with connection() as conn:
        conn.execute(
            "UPDATE google_accounts SET needs_reconnect = 0, last_error = '' WHERE id = ?",
            (account_id,),
        )


def store_refresh_token(
    account_id: str, token: str, settings: config.Settings | None = None
) -> None:
    """Keep an account's refresh token in the keyring, under its own entry."""
    config.set_secret(_refresh_entry(account_id), token, settings)


def forget_refresh_token(account_id: str, settings: config.Settings | None = None) -> None:
    """Remove an account's refresh token from the keyring."""
    config.delete_secret(_refresh_entry(account_id), settings)


def is_first_account(account_id: str) -> bool:
    """True when this is the oldest account.

    The oldest account is the one the pre-multi-account code paths mean
    when they say "the connected channel", so it is the one that keeps
    the legacy settings and the legacy keyring entry in step.

    The order is the row's insertion order, not its timestamp. Two
    accounts connected in the same second share a timestamp, and the
    timestamp alone would make "the oldest" a coin toss.
    """
    with connection() as conn:
        row = conn.execute("SELECT id FROM google_accounts ORDER BY rowid LIMIT 1").fetchone()
    return bool(row) and row[0] == account_id


def delete_account(account_id: str) -> None:
    """Remove the account, its channels, and its refresh token."""
    with connection() as conn:
        conn.execute("DELETE FROM google_accounts WHERE id = ?", (account_id,))
    config.delete_secret(_refresh_entry(account_id))


def default_account() -> dict[str, Any] | None:
    """The first-created account, mirroring the legacy single-account setup."""
    with connection() as conn:
        row = conn.execute("SELECT id FROM google_accounts ORDER BY rowid LIMIT 1").fetchone()
    return get_account(row[0]) if row else None


# --------------------------------------------------------------------------
# Channels
# --------------------------------------------------------------------------


def list_channels(account_id: str | None = None) -> list[dict[str, Any]]:
    query = (
        "SELECT id, account_id, channel_id, title, url, is_default, privacy,"
        " category_id, auto_upload, title_suffix, created_at, updated_at, made_for_kids"
        " FROM youtube_channels"
    )
    params: tuple[Any, ...] = ()
    if account_id:
        query += " WHERE account_id = ?"
        params = (account_id,)
    query += " ORDER BY is_default DESC, created_at, rowid"
    with connection() as conn:
        rows = conn.execute(query, params).fetchall()
    return [_channel_row(r) for r in rows]


def get_channel(channel_row_id: str) -> dict[str, Any] | None:
    with connection() as conn:
        row = conn.execute(
            "SELECT id, account_id, channel_id, title, url, is_default, privacy,"
            " category_id, auto_upload, title_suffix, created_at, updated_at, made_for_kids"
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
        #: The audience declaration for this channel: '' (not decided),
        #: 'false' or 'true'.
        "made_for_kids": r[12] if len(r) > 12 else "",
    }


def add_channel(
    account_id: str,
    channel: dict[str, str],
    *,
    is_default: bool | None = None,
    privacy: str = "private",
    category_id: str = "24",
    auto_upload: bool = False,
    title_suffix: str = "",
    made_for_kids: str = "",
) -> dict[str, Any]:
    """Register a channel under an account. First channel becomes default.

    A new channel starts **private**. The original default was public,
    which meant a freshly connected channel could publish to the world
    the moment automatic upload was switched on. The audience declaration
    starts unanswered: it is a legal declaration, and AutoClip does not
    make it on the owner's behalf.
    """
    row_id = new_id()
    if is_default is None:
        is_default = not list_channels(account_id)
    now = utcnow()
    with connection() as conn:
        if is_default:
            conn.execute(
                "UPDATE youtube_channels SET is_default = 0 WHERE account_id = ?", (account_id,)
            )
        conn.execute(
            "INSERT INTO youtube_channels (id, account_id, channel_id, title, url,"
            " is_default, privacy, category_id, auto_upload, title_suffix, created_at,"
            " updated_at, made_for_kids)"
            " VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (
                row_id,
                account_id,
                channel["id"],
                channel.get("title", ""),
                channel.get("url", ""),
                int(is_default),
                privacy,
                category_id,
                int(auto_upload),
                title_suffix,
                now,
                now,
                made_for_kids,
            ),
        )
    result = get_channel(row_id)
    assert result is not None
    return result


def upsert_channel(
    account_id: str,
    channel: dict[str, str],
    *,
    privacy: str = "private",
    category_id: str = "24",
    auto_upload: bool = False,
    made_for_kids: str = "",
) -> dict[str, Any]:
    """Register the channel Google just signed in to, or refresh its record.

    The destination identity lives here, not in the settings file: a
    channel row is what an upload names, so the upload can be proved to
    have gone to the channel the user chose.

    A channel that is already registered under this account is updated in
    place. Its own policy — privacy, category, automatic publishing — is
    left exactly as it was, because a second sign-in is not a reason to
    change how the channel publishes.
    """
    channel_id = channel.get("id", "")
    with connection() as conn:
        row = conn.execute(
            "SELECT id FROM youtube_channels WHERE account_id = ? AND channel_id = ?",
            (account_id, channel_id),
        ).fetchone()

    if row is not None:
        with connection() as conn:
            conn.execute(
                "UPDATE youtube_channels SET title = ?, url = ?, updated_at = ? WHERE id = ?",
                (
                    channel.get("title", ""),
                    channel.get("url", ""),
                    utcnow(),
                    row[0],
                ),
            )
        result = get_channel(row[0])
        assert result is not None
        return result

    return add_channel(
        account_id,
        channel,
        is_default=None,
        privacy=privacy,
        category_id=category_id,
        auto_upload=auto_upload,
        made_for_kids=made_for_kids,
    )


def update_channel(channel_row_id: str, **fields: Any) -> dict[str, Any] | None:
    allowed = {
        "privacy",
        "category_id",
        "auto_upload",
        "is_default",
        "title",
        "title_suffix",
        "made_for_kids",
    }
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
            row = conn.execute("SELECT id FROM youtube_channels WHERE is_default = 1").fetchone()
    return get_channel(row[0]) if row else None


def refresh_token_for(account_id: str, settings: config.Settings | None = None) -> str | None:
    """Refresh token for an account: its own entry, then the legacy one.

    The legacy fallback belongs to the **oldest** account only. It used to
    belong to whichever account asked, which meant a second account that
    had never been connected looked as though it held a token — and could
    publish to the first account's channel.
    """
    token = config.get_secret(_refresh_entry(account_id), settings)
    if token:
        return token
    if is_first_account(account_id):
        return legacy_refresh_token(settings)
    return None


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
        made_for_kids=settings.youtube.made_for_kids,
    )
    log.info("Migrated the legacy YouTube connection to multi-account storage.")


def _connect_version(conn: sqlite3.Connection) -> int:  # pragma: no cover - test helper
    return int(conn.execute("PRAGMA user_version").fetchone()[0])


__all__ = [
    "add_channel",
    "claim_legacy_token",
    "clear_needs_reconnect",
    "create_account",
    "default_account",
    "default_channel",
    "delete_account",
    "delete_channel",
    "ensure_legacy_migrated",
    "forget_refresh_token",
    "get_account",
    "get_channel",
    "is_first_account",
    "legacy_refresh_token",
    "list_accounts",
    "list_channels",
    "mark_needs_reconnect",
    "refresh_token_for",
    "store_refresh_token",
    "update_account",
    "update_channel",
    "upsert_channel",
]
