"""The Instagram accounts this install publishes to.

One row per account, one keyring entry per account. The token is filed
under ``instagram_token#<account_id>``, so a credential that Meta stops
accepting affects exactly one account and the others carry on — the same
rule the YouTube accounts follow, for the same reason.

The account is stored by the id Meta reports. AutoClip does not infer the
destination from a username, and it does not guess which account a sign-in
was for: the sign-in is bound to the account it was started for.
"""

from __future__ import annotations

import logging
from typing import Any

from .. import config
from ..db.models import InstagramAccount, new_id, utcnow
from ..db.store import (
    create_instagram_account,
    default_instagram_account,
    get_instagram_account,
    list_instagram_accounts,
    update_instagram_account,
)

log = logging.getLogger(__name__)


def token_entry(account_id: str) -> str:
    """The keyring entry that holds one account's access token."""
    return f"instagram_token#{account_id}"


def create_account(
    *,
    label: str = "",
    login_type: str = "unified",
    ig_user_id: str = "",
    username: str = "",
    name: str = "",
    page_id: str = "",
    business_id: str = "",
    config_id: str = "",
) -> InstagramAccount:
    """Create an account slot, or return the one that already exists.

    Connecting the same Instagram account twice reuses its row: two rows
    for one account would file the token twice and show the owner two
    accounts that are really one.
    """
    account = InstagramAccount(
        id=new_id(),
        ig_user_id=ig_user_id,
        username=username,
        name=name,
        label=label or username or "Instagram account",
        login_type=login_type,
        page_id=page_id,
        business_id=business_id,
        config_id=config_id,
        connected_at=utcnow(),
    )
    return create_instagram_account(account)


def get_account(account_id: str) -> InstagramAccount | None:
    return get_instagram_account(account_id)


def list_accounts() -> list[InstagramAccount]:
    """Every account, oldest first."""
    return list_instagram_accounts()


def default_account() -> InstagramAccount | None:
    """The oldest account — the one the legacy settings refer to."""
    return default_instagram_account()


def update_account(account_id: str, **fields: Any) -> None:
    update_instagram_account(account_id, **fields)


def store_token(account_id: str, token: str, settings: config.Settings | None = None) -> bool:
    """File an account's access token in the OS keyring."""
    if not account_id:
        return False
    return config.set_secret(token_entry(account_id), token, settings)


def token_for(account_id: str, settings: config.Settings | None = None) -> str:
    """The account's access token, or an empty string when it has none."""
    if not account_id:
        return ""
    return config.get_secret(token_entry(account_id), settings) or ""


def forget_token(account_id: str, settings: config.Settings | None = None) -> None:
    """Remove an account's access token from the keyring."""
    if account_id:
        config.delete_secret(token_entry(account_id), settings)


def mark_needs_reconnect(account_id: str, reason: str) -> None:
    """Record a broken credential against one account, and only that one.

    A token Meta stopped accepting says nothing about the other accounts,
    and taking the whole publisher down for one bad credential would be a
    worse failure than the one it fixes.
    """
    if not account_id:
        return
    update_instagram_account(account_id, needs_reconnect=True, last_error=reason[:500])


def clear_needs_reconnect(account_id: str) -> None:
    """The credential works again; the warning goes away."""
    if not account_id:
        return
    update_instagram_account(account_id, needs_reconnect=False, last_error="")


def account_for_upload(account_row_id: str) -> InstagramAccount | None:
    """The account an upload row names, falling back to the oldest one.

    The fallback exists for the legacy path, where an upload row was
    created before there was an account table. An upload that names an
    account always uses that one — the destination is never guessed.
    """
    if account_row_id:
        return get_instagram_account(account_row_id)
    return default_instagram_account()
