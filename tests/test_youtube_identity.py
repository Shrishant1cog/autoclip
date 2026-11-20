"""The Google accounts, the channels they own, and the credential behind them.

These tests cover the parts of the YouTube connection that have to hold
when there is more than one Google account:

* a sign-in is filed under the account it started for,
* the channel Google reports is the destination that is stored,
* one revoked credential never takes the other accounts down,
* and the legacy single-account settings keep working.

They are here rather than in ``test_youtube.py`` because that file is
about the upload itself; this one is about identity.
"""

from __future__ import annotations

import json
from collections.abc import Iterator
from pathlib import Path
from typing import Any

import pytest
from autoclip import app as app_module
from autoclip import config
from autoclip.app import create_app
from autoclip.youtube import accounts as accounts_store
from autoclip.youtube import oauth
from fastapi.testclient import TestClient


class FakeKeyring:
    def __init__(self) -> None:
        self.store: dict[tuple[str, str], str] = {}

    def get_password(self, service: str, key: str) -> str | None:
        return self.store.get((service, key))

    def set_password(self, service: str, key: str, value: str) -> None:
        self.store[(service, key)] = value

    def delete_password(self, service: str, key: str) -> None:
        self.store.pop((service, key), None)


class FakeResponse:
    def __init__(self, status: int, body: dict[str, Any] | None = None) -> None:
        self.status_code = status
        self._body = body or {}

    def json(self) -> dict[str, Any]:
        return self._body


@pytest.fixture
def client(autoclip_home: Path, monkeypatch: pytest.MonkeyPatch) -> Iterator[TestClient]:
    monkeypatch.setenv(app_module.ENV_NO_WORKER, "1")
    with TestClient(create_app()) as test_client:
        yield test_client


def _configure(monkeypatch: pytest.MonkeyPatch) -> config.Settings:
    kr = FakeKeyring()
    monkeypatch.setattr(config, "_keyring", lambda: kr)
    settings = config.load()
    settings.youtube.client_id = "client-id.apps.googleusercontent.com"
    config.save(settings)
    config.set_secret(config.YOUTUBE_CLIENT_SECRET_KEY, "secret-value", settings)
    return settings


def _google(monkeypatch: pytest.MonkeyPatch, *, channel_id: str = "UCfirst") -> None:
    """Make Google's token and channel endpoints answer."""

    def fake_post(url: str, **kwargs: Any) -> FakeResponse:
        if url == oauth.TOKEN_URL:
            return FakeResponse(
                200,
                {
                    "access_token": "access-token",
                    "refresh_token": "refresh-token",
                    "expires_in": 3600,
                },
            )
        if url == oauth.REVOKE_URL:
            return FakeResponse(200, {})
        raise AssertionError(f"unexpected POST to {url}")

    def fake_get(url: str, **kwargs: Any) -> FakeResponse:
        if url == oauth.CHANNELS_URL:
            return FakeResponse(
                200,
                {
                    "items": [
                        {
                            "id": channel_id,
                            "snippet": {"title": f"Channel {channel_id}"},
                        }
                    ]
                },
            )
        raise AssertionError(f"unexpected GET to {url}")

    monkeypatch.setattr(oauth.httpx, "post", fake_post)
    monkeypatch.setattr(oauth.httpx, "get", fake_get)


# --------------------------------------------------------------------------
# The sign-in belongs to an account
# --------------------------------------------------------------------------


def test_a_new_sign_in_creates_an_account_of_its_own(
    initialised_db: int, monkeypatch: pytest.MonkeyPatch
) -> None:
    settings = _configure(monkeypatch)

    oauth.build_auth_url(settings, label="Second account")

    accounts = accounts_store.list_accounts()
    assert len(accounts) == 1
    assert accounts[0]["label"] == "Second account"


def test_a_sign_in_remembers_the_account_it_started_for(
    initialised_db: int, monkeypatch: pytest.MonkeyPatch
) -> None:
    settings = _configure(monkeypatch)
    account = accounts_store.create_account(label="Existing")

    oauth.build_auth_url(settings, account_id=account["id"])

    # The account is not duplicated: a sign-in for a known account is a
    # sign-in *for* that account.
    assert [a["id"] for a in accounts_store.list_accounts()] == [account["id"]]


def test_a_sign_in_for_an_unknown_account_is_refused(
    initialised_db: int, monkeypatch: pytest.MonkeyPatch
) -> None:
    settings = _configure(monkeypatch)

    with pytest.raises(oauth.OAuthError):
        oauth.build_auth_url(settings, account_id="not-a-real-account")


def test_completing_the_sign_in_files_the_token_under_that_account(
    initialised_db: int, monkeypatch: pytest.MonkeyPatch
) -> None:
    settings = _configure(monkeypatch)
    _google(monkeypatch)

    url = oauth.build_auth_url(settings, label="Work")
    state = url.split("state=")[1].split("&")[0]
    oauth.complete_auth("code", state, settings)

    account = accounts_store.default_account()
    assert account is not None
    assert accounts_store.refresh_token_for(account["id"], settings) == "refresh-token"


def test_completing_the_sign_in_records_the_destination_google_reported(
    initialised_db: int, monkeypatch: pytest.MonkeyPatch
) -> None:
    settings = _configure(monkeypatch)
    _google(monkeypatch, channel_id="UCdestination")

    url = oauth.build_auth_url(settings, label="Work")
    state = url.split("state=")[1].split("&")[0]
    oauth.complete_auth("code", state, settings)

    channels = accounts_store.list_channels()
    assert len(channels) == 1
    # The channel id comes from Google, not from the settings file.
    assert channels[0]["channel_id"] == "UCdestination"
    assert channels[0]["account_id"] == accounts_store.default_account()["id"]


def test_a_second_account_does_not_take_over_the_first_destination(
    initialised_db: int, monkeypatch: pytest.MonkeyPatch
) -> None:
    settings = _configure(monkeypatch)
    _google(monkeypatch, channel_id="UCfirst")

    url = oauth.build_auth_url(settings, label="First")
    state = url.split("state=")[1].split("&")[0]
    oauth.complete_auth("code", state, settings)
    assert settings.youtube.channel_id == "UCfirst"

    # The second account signs in to a different channel.
    _google(monkeypatch, channel_id="UCsecond")
    url = oauth.build_auth_url(settings, label="Second")
    state = url.split("state=")[1].split("&")[0]
    oauth.complete_auth("code", state, settings)

    # The legacy settings still name the first channel: the second account
    # must not silently redirect the first one's uploads.
    assert settings.youtube.channel_id == "UCfirst"
    assert {c["channel_id"] for c in accounts_store.list_channels()} == {
        "UCfirst",
        "UCsecond",
    }


def test_the_legacy_entry_belongs_to_the_oldest_account_only(
    initialised_db: int, monkeypatch: pytest.MonkeyPatch
) -> None:
    settings = _configure(monkeypatch)
    _google(monkeypatch, channel_id="UCfirst")

    url = oauth.build_auth_url(settings, label="First")
    state = url.split("state=")[1].split("&")[0]
    oauth.complete_auth("code", state, settings)

    second = accounts_store.create_account(label="Second")

    # The oldest account's own entry is there, and so is the legacy one.
    assert accounts_store.refresh_token_for(accounts_store.default_account()["id"], settings)
    # The second account has never been connected, so it must not inherit
    # the first account's credential.
    assert accounts_store.refresh_token_for(second["id"], settings) is None


# --------------------------------------------------------------------------
# One broken credential does not break the others
# --------------------------------------------------------------------------


def test_a_revoked_credential_marks_only_its_own_account(
    initialised_db: int, monkeypatch: pytest.MonkeyPatch
) -> None:
    settings = _configure(monkeypatch)
    _google(monkeypatch, channel_id="UCfirst")

    url = oauth.build_auth_url(settings, label="First")
    state = url.split("state=")[1].split("&")[0]
    oauth.complete_auth("code", state, settings)
    first = accounts_store.default_account()

    _google(monkeypatch, channel_id="UCsecond")
    url = oauth.build_auth_url(settings, label="Second")
    state = url.split("state=")[1].split("&")[0]
    oauth.complete_auth("code", state, settings)
    second = [a for a in accounts_store.list_accounts() if a["id"] != first["id"]][0]

    def revoke(url: str, **kwargs: Any) -> FakeResponse:
        if url == oauth.TOKEN_URL:
            return FakeResponse(
                400, {"error": "invalid_grant", "error_description": "Token has been revoked."}
            )
        return FakeResponse(200, {})

    monkeypatch.setattr(oauth.httpx, "post", revoke)

    # Drop the cached access token so the refresh is actually attempted.
    oauth._tokens_by_account.pop(second["id"], None)

    with pytest.raises(oauth.InvalidGrantError):
        oauth.access_token(settings, account_id=second["id"])

    # Only the second account is marked. The first one still publishes.
    assert accounts_store.get_account(second["id"])["needs_reconnect"] is True
    assert accounts_store.get_account(second["id"])["last_error"]
    assert accounts_store.get_account(first["id"])["needs_reconnect"] is False


def test_an_account_that_is_reconnected_forgets_the_old_failure(
    initialised_db: int, monkeypatch: pytest.MonkeyPatch
) -> None:
    settings = _configure(monkeypatch)
    _google(monkeypatch, channel_id="UCfirst")

    account = accounts_store.create_account(label="Work")
    accounts_store.mark_needs_reconnect(account["id"], "Token has been revoked.")

    url = oauth.build_auth_url(settings, account_id=account["id"])
    state = url.split("state=")[1].split("&")[0]
    oauth.complete_auth("code", state, settings)

    fresh = accounts_store.get_account(account["id"])
    assert fresh["needs_reconnect"] is False
    assert fresh["last_error"] == ""


def test_disconnecting_one_account_leaves_the_others_connected(
    initialised_db: int, monkeypatch: pytest.MonkeyPatch
) -> None:
    settings = _configure(monkeypatch)
    _google(monkeypatch, channel_id="UCfirst")

    url = oauth.build_auth_url(settings, label="First")
    state = url.split("state=")[1].split("&")[0]
    oauth.complete_auth("code", state, settings)
    first = accounts_store.default_account()

    _google(monkeypatch, channel_id="UCsecond")
    url = oauth.build_auth_url(settings, label="Second")
    state = url.split("state=")[1].split("&")[0]
    oauth.complete_auth("code", state, settings)
    second = [a for a in accounts_store.list_accounts() if a["id"] != first["id"]][0]

    oauth.disconnect(settings, account_id=second["id"])

    assert accounts_store.refresh_token_for(second["id"], settings) is None
    assert accounts_store.refresh_token_for(first["id"], settings) == "refresh-token"
    assert oauth.is_connected(settings) is True


# --------------------------------------------------------------------------
# The API
# --------------------------------------------------------------------------


def test_connecting_a_named_account_returns_a_consent_url(
    client: TestClient, initialised_db: int, monkeypatch: pytest.MonkeyPatch
) -> None:
    _configure(monkeypatch)
    account = accounts_store.create_account(label="Work")

    response = client.post(f"/api/youtube/accounts/{account['id']}/connect")

    assert response.status_code == 200
    assert "accounts.google.com" in response.json()["auth_url"]


def test_connecting_an_unknown_account_is_a_404(
    client: TestClient, initialised_db: int, monkeypatch: pytest.MonkeyPatch
) -> None:
    _configure(monkeypatch)

    response = client.post("/api/youtube/accounts/not-a-real-account/connect")

    assert response.status_code == 404


def test_the_account_list_reports_a_broken_connection(
    client: TestClient, initialised_db: int, monkeypatch: pytest.MonkeyPatch
) -> None:
    _configure(monkeypatch)
    account = accounts_store.create_account(label="Work")
    accounts_store.mark_needs_reconnect(account["id"], "Token has been revoked.")

    body = client.get("/api/youtube/accounts").json()

    assert len(body) == 1
    assert body[0]["needs_reconnect"] is True
    assert body[0]["last_error"] == "Token has been revoked."


def test_the_privacy_setting_is_not_changed_by_connecting(
    client: TestClient, initialised_db: int, monkeypatch: pytest.MonkeyPatch
) -> None:
    settings = _configure(monkeypatch)
    settings.youtube.privacy = "unlisted"
    config.save(settings)
    _google(monkeypatch)

    url = client.post("/api/youtube/connect", json={"label": "Work"}).json()["auth_url"]
    state = url.split("state=")[1].split("&")[0]
    oauth.complete_auth("code", state, settings)

    # Connecting a channel is not a reason to change how it publishes.
    assert config.load().youtube.privacy == "unlisted"


def test_the_transfer_log_never_holds_a_token(
    initialised_db: int, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The refresh token must not reach the database or the settings file."""
    from autoclip import paths

    settings = _configure(monkeypatch)
    _google(monkeypatch)

    url = oauth.build_auth_url(settings, label="Work")
    state = url.split("state=")[1].split("&")[0]
    oauth.complete_auth("code", state, settings)

    raw = paths.config_path().read_text(encoding="utf-8")
    assert "refresh-token" not in raw
    assert "access-token" not in raw


def test_the_stored_channel_record_keeps_the_publishing_policy(
    initialised_db: int, monkeypatch: pytest.MonkeyPatch
) -> None:
    settings = _configure(monkeypatch)
    settings.youtube.privacy = "unlisted"
    config.save(settings)
    _google(monkeypatch)

    url = oauth.build_auth_url(settings, label="Work")
    state = url.split("state=")[1].split("&")[0]
    oauth.complete_auth("code", state, settings)

    channels = accounts_store.list_channels()
    assert channels[0]["privacy"] == "unlisted"
    # And the row is a plain record — no secret anywhere in it.
    assert "refresh-token" not in json.dumps(channels)
