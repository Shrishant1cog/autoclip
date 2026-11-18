"""Multi-account / multi-channel YouTube manager tests (Phase 4)."""

from __future__ import annotations

import pytest
from autoclip import config
from autoclip.youtube import accounts as store


@pytest.fixture
def migrated_legacy(fake_keyring: object, initialised_db: int) -> config.Settings:
    """A legacy single-account connection imported as the default row."""
    settings = config.Settings()
    settings.youtube.client_id = "cid.apps.googleusercontent.com"
    settings.youtube.channel_id = "UC_legacy"
    settings.youtube.channel_title = "Legacy channel"
    settings.youtube.channel_url = "https://www.youtube.com/channel/UC_legacy"
    config.save(settings)
    config.set_secret(config.YOUTUBE_REFRESH_TOKEN_KEY, "refresh-legacy", settings)
    store.ensure_legacy_migrated(settings)
    return settings


# --------------------------------------------------------------------------
# Migration v5
# --------------------------------------------------------------------------


def test_migration_v5_creates_account_tables(initialised_db: int) -> None:
    with store.connection() as conn:
        version = conn.execute("PRAGMA user_version").fetchone()[0]
        tables = {
            r[0]
            for r in conn.execute("SELECT name FROM sqlite_master WHERE type='table'").fetchall()
        }
    assert version >= 5
    assert {"google_accounts", "youtube_channels"} <= tables


# --------------------------------------------------------------------------
# Legacy import
# --------------------------------------------------------------------------


def test_legacy_connection_is_migrated_once(migrated_legacy: config.Settings) -> None:
    accounts = store.list_accounts()
    assert len(accounts) == 1
    account = accounts[0]
    assert account["client_id"] == "cid.apps.googleusercontent.com"

    channels = store.list_channels(account["id"])
    assert len(channels) == 1
    channel = channels[0]
    assert channel["channel_id"] == "UC_legacy"
    assert channel["is_default"] is True
    # The refresh token was claimed under the account's own entry.
    assert store.refresh_token_for(account["id"]) == "refresh-legacy"

    # Idempotent: running it again does not duplicate.
    store.ensure_legacy_migrated(migrated_legacy)
    assert len(store.list_accounts()) == 1


def test_no_legacy_connection_means_no_rows(initialised_db: int) -> None:
    store.ensure_legacy_migrated()
    assert store.list_accounts() == []


def test_new_style_accounts_block_reimport(migrated_legacy: config.Settings) -> None:
    store.create_account(label="second", email="a@b.c")
    store.ensure_legacy_migrated(migrated_legacy)
    assert len(store.list_accounts()) == 2


# --------------------------------------------------------------------------
# Accounts CRUD
# --------------------------------------------------------------------------


def test_account_crud(initialised_db: int, fake_keyring: object) -> None:
    account = store.create_account(label="Main", email="me@example.com")
    assert account["label"] == "Main"

    updated = store.update_account(account["id"], label="Renamed")
    assert updated is not None and updated["label"] == "Renamed"

    config.set_secret(store._refresh_entry(account["id"]), "tok")
    assert store.refresh_token_for(account["id"]) == "tok"

    store.delete_account(account["id"])
    assert store.get_account(account["id"]) is None
    assert store.refresh_token_for(account["id"]) is None


def test_multiple_accounts_are_independent(initialised_db: int) -> None:
    a1 = store.create_account(label="one")
    a2 = store.create_account(label="two")
    assert a1["id"] != a2["id"]
    config.set_secret(store._refresh_entry(a1["id"]), "tok-1")
    config.set_secret(store._refresh_entry(a2["id"]), "tok-2")
    assert store.refresh_token_for(a1["id"]) == "tok-1"
    assert store.refresh_token_for(a2["id"]) == "tok-2"


def test_default_account_is_first_created(initialised_db: int) -> None:
    first = store.create_account(label="first")
    store.create_account(label="second")
    assert store.default_account() is not None
    assert store.default_account()["id"] == first["id"]


# --------------------------------------------------------------------------
# Channels
# --------------------------------------------------------------------------


def test_first_channel_is_default_and_switches(initialised_db: int) -> None:
    account = store.create_account()
    c1 = store.add_channel(account["id"], {"id": "UC1", "title": "One"})
    assert c1["is_default"] is True

    c2 = store.add_channel(account["id"], {"id": "UC2", "title": "Two"})
    assert c2["is_default"] is False

    store.update_channel(c2["id"], is_default=True)
    assert store.get_channel(c1["id"])["is_default"] is False  # type: ignore[index]
    assert store.get_channel(c2["id"])["is_default"] is True  # type: ignore[index]


def test_channel_profile_defaults(initialised_db: int) -> None:
    account = store.create_account()
    channel = store.add_channel(
        account["id"], {"id": "UC_gaming"}, privacy="unlisted", category_id="20",
        auto_upload=True,
    )
    assert channel["privacy"] == "unlisted"
    assert channel["category_id"] == "20"
    assert channel["auto_upload"] is True

    updated = store.update_channel(channel["id"], privacy="public", auto_upload=False)
    assert updated is not None
    assert updated["privacy"] == "public"
    assert updated["auto_upload"] is False


def test_duplicate_channel_per_account_rejected(initialised_db: int) -> None:
    import sqlite3

    account = store.create_account()
    store.add_channel(account["id"], {"id": "UC_same"})
    with pytest.raises(sqlite3.IntegrityError):
        store.add_channel(account["id"], {"id": "UC_same"})


def test_same_channel_id_on_different_accounts_ok(initialised_db: int) -> None:
    a1 = store.create_account(label="a")
    a2 = store.create_account(label="b")
    store.add_channel(a1["id"], {"id": "UC_x"})
    store.add_channel(a2["id"], {"id": "UC_x"})
    assert len(store.list_channels(a1["id"])) == 1
    assert len(store.list_channels(a2["id"])) == 1


def test_deleting_account_cascades_channels(initialised_db: int) -> None:
    account = store.create_account()
    store.add_channel(account["id"], {"id": "UC1"})
    store.delete_account(account["id"])
    assert store.list_channels(account["id"]) == []


def test_default_channel_scope(initialised_db: int) -> None:
    a1 = store.create_account(label="a")
    a2 = store.create_account(label="b")
    store.add_channel(a1["id"], {"id": "UC1"})
    store.add_channel(a2["id"], {"id": "UC2"})
    assert store.default_channel(a2["id"])["channel_id"] == "UC2"  # type: ignore[index]
    assert store.default_channel()["channel_id"] in {"UC1", "UC2"}  # type: ignore[index]
