"""Google OAuth for the YouTube Data API.

The flow is the standard loopback one: the browser is sent to Google with a
PKCE challenge, Google redirects back to the app's callback, and the server
exchanges the code for a refresh token. Only the refresh token is persisted
(in the OS keyring); access tokens are cached in memory until they expire.

No Google SDK is used — the three endpoints involved are plain form posts and
one GET, so httpx keeps the dependency surface small.
"""

from __future__ import annotations

import base64
import hashlib
import logging
import secrets
import time
from dataclasses import dataclass
from typing import Any
from urllib.parse import urlencode

import httpx

from .. import config
from ..db.models import utcnow

log = logging.getLogger(__name__)

AUTHORIZE_URL = "https://accounts.google.com/o/oauth2/v2/auth"
TOKEN_URL = "https://oauth2.googleapis.com/token"
REVOKE_URL = "https://oauth2.googleapis.com/revoke"
CHANNELS_URL = "https://www.googleapis.com/youtube/v3/channels"

#: Uploading plus reading the authenticated channel's identity.
SCOPES = (
    "https://www.googleapis.com/auth/youtube.upload",
    "https://www.googleapis.com/auth/youtube.readonly",
)

#: A pending sign-in older than this is treated as abandoned.
_STATE_TTL_S = 15 * 60


class OAuthError(RuntimeError):
    """The Google sign-in could not be completed."""


@dataclass
class _Pending:
    verifier: str
    redirect_uri: str
    created_at: float


#: Authorization attempts keyed by state. One user on one machine, so a plain
#: dict is enough; entries are removed on use and expire on TTL.
_pending: dict[str, _Pending] = {}

_token_cache: dict[str, Any] = {"access_token": "", "expires_at": 0.0}

#: Access tokens per connected Google account (multi-account publishing).
_tokens_by_account: dict[str, dict[str, Any]] = {}


# --------------------------------------------------------------------------
# Configuration checks
# --------------------------------------------------------------------------


def is_configured(settings: config.Settings | None = None) -> bool:
    """True when a client id and secret are both present."""
    settings = settings or config.load()
    return bool(
        settings.youtube.client_id and config.get_secret(config.YOUTUBE_CLIENT_SECRET_KEY, settings)
    )


def is_connected(settings: config.Settings | None = None) -> bool:
    """True when we hold a refresh token for a channel."""
    settings = settings or config.load()
    return bool(
        is_configured(settings)
        and settings.youtube.channel_id
        and config.get_secret(config.YOUTUBE_REFRESH_TOKEN_KEY, settings)
    )


# --------------------------------------------------------------------------
# Authorization code flow
# --------------------------------------------------------------------------


def _pkce_pair() -> tuple[str, str]:
    verifier = secrets.token_urlsafe(64)
    digest = hashlib.sha256(verifier.encode("ascii")).digest()
    challenge = base64.urlsafe_b64encode(digest).rstrip(b"=").decode("ascii")
    return verifier, challenge


def build_auth_url(settings: config.Settings | None = None) -> str:
    """Return the Google consent URL and remember the pending state/verifier."""
    settings = settings or config.load()
    client_id = settings.youtube.client_id
    client_secret = config.get_secret(config.YOUTUBE_CLIENT_SECRET_KEY, settings)
    if not client_id or not client_secret:
        raise OAuthError("Add the Google OAuth client ID and secret in Settings before connecting.")

    state = secrets.token_urlsafe(24)
    verifier, challenge = _pkce_pair()
    redirect_uri = settings.youtube.redirect_uri

    _pending[state] = _Pending(
        verifier=verifier, redirect_uri=redirect_uri, created_at=time.monotonic()
    )
    _prune_pending()

    params = {
        "client_id": client_id,
        "redirect_uri": redirect_uri,
        "response_type": "code",
        "scope": " ".join(SCOPES),
        # offline + consent guarantees a refresh token, including on re-consent.
        "access_type": "offline",
        "prompt": "consent",
        "include_granted_scopes": "true",
        "state": state,
        "code_challenge": challenge,
        "code_challenge_method": "S256",
    }
    return f"{AUTHORIZE_URL}?{urlencode(params)}"


def _prune_pending() -> None:
    now = time.monotonic()
    for state in [s for s, p in _pending.items() if now - p.created_at > _STATE_TTL_S]:
        _pending.pop(state, None)


def complete_auth(code: str, state: str, settings: config.Settings | None = None) -> dict[str, str]:
    """Exchange an authorization code, fetch the channel, and save the token."""
    settings = settings or config.load()
    pending = _pending.pop(state, None)
    if pending is None:
        raise OAuthError("That sign-in link has expired or was already used. Press Connect again.")
    if time.monotonic() - pending.created_at > _STATE_TTL_S:
        raise OAuthError("The sign-in took too long. Press Connect again.")

    client_id = settings.youtube.client_id
    client_secret = config.get_secret(config.YOUTUBE_CLIENT_SECRET_KEY, settings)
    if not client_id or not client_secret:
        raise OAuthError("The OAuth client credentials are missing from Settings.")

    tokens = _post_token(
        {
            "grant_type": "authorization_code",
            "code": code,
            "client_id": client_id,
            "client_secret": client_secret,
            "redirect_uri": pending.redirect_uri,
            "code_verifier": pending.verifier,
        }
    )
    access_token = tokens.get("access_token", "")
    refresh_token = tokens.get("refresh_token", "")
    if not access_token:
        raise OAuthError("Google did not return an access token.")
    if not refresh_token:
        raise OAuthError(
            "Google did not return a refresh token. Remove AutoClip's access at "
            "myaccount.google.com/permissions, then connect again."
        )

    _cache_token(access_token, int(tokens.get("expires_in", 3600)))
    channel = fetch_channel(access_token)

    config.set_secret(config.YOUTUBE_REFRESH_TOKEN_KEY, refresh_token, settings)
    settings.youtube.channel_id = channel["id"]
    settings.youtube.channel_title = channel["title"]
    settings.youtube.channel_url = channel["url"]
    settings.youtube.connected_at = utcnow()
    config.save(settings)

    return channel


def fetch_channel(access_token: str) -> dict[str, str]:
    """Return the signed-in account's YouTube channel identity."""
    try:
        response = httpx.get(
            CHANNELS_URL,
            params={"part": "snippet", "mine": "true"},
            headers={"Authorization": f"Bearer {access_token}"},
            timeout=30.0,
        )
    except httpx.HTTPError as exc:
        raise OAuthError(f"Could not reach YouTube: {exc}") from exc

    if response.status_code == 403:
        raise OAuthError(
            "YouTube refused the channel lookup. Make sure the YouTube Data API v3 "
            "is enabled for this Google Cloud project."
        )
    if response.status_code >= 400:
        raise OAuthError(_google_message(response))

    items = response.json().get("items", [])
    if not items:
        raise OAuthError(
            "This Google account has no YouTube channel. Create one, or sign in "
            "with the account that owns the channel."
        )

    snippet = items[0].get("snippet", {})
    channel_id = items[0]["id"]
    return {
        "id": channel_id,
        "title": snippet.get("title", ""),
        "url": f"https://www.youtube.com/channel/{channel_id}",
    }


# --------------------------------------------------------------------------
# Tokens
# --------------------------------------------------------------------------


def _cache_token(access_token: str, expires_in: int) -> None:
    # Refresh a minute early so a request never starts with a dead token.
    _token_cache["access_token"] = access_token
    _token_cache["expires_at"] = time.monotonic() + max(expires_in - 60, 30)


def access_token(
    settings: config.Settings | None = None, account_id: str | None = None
) -> str:
    """Return a valid access token, refreshing it when necessary.

    With ``account_id`` the token belongs to that connected Google account;
    without it the legacy single-account token is used.
    """
    settings = settings or config.load()
    if account_id:
        cached = _tokens_by_account.get(account_id)
        if cached and time.monotonic() < cached["expires_at"]:
            return cached["access_token"]
        from .accounts import refresh_token_for

        refresh_token = refresh_token_for(account_id, settings)
        if not refresh_token:
            raise OAuthError(
                "No stored credential for that Google account. Reconnect it in Settings."
            )
        token, expires_in = _refresh(refresh_token, settings)
        _tokens_by_account[account_id] = {
            "access_token": token,
            "expires_at": time.monotonic() + max(expires_in - 60, 30),
        }
        return token

    if _token_cache["access_token"] and time.monotonic() < _token_cache["expires_at"]:
        return _token_cache["access_token"]

    refresh_token = config.get_secret(config.YOUTUBE_REFRESH_TOKEN_KEY, settings)
    if not refresh_token:
        raise OAuthError("No YouTube channel is connected. Press Connect YouTube channel.")

    token, expires_in = _refresh(refresh_token, settings)
    _cache_token(token, expires_in)
    return token


def _refresh(refresh_token: str, settings: config.Settings) -> tuple[str, int]:
    client_id = settings.youtube.client_id
    client_secret = config.get_secret(config.YOUTUBE_CLIENT_SECRET_KEY, settings)
    if not client_id or not client_secret:
        raise OAuthError("The OAuth client credentials are missing from Settings.")

    tokens = _post_token(
        {
            "grant_type": "refresh_token",
            "refresh_token": refresh_token,
            "client_id": client_id,
            "client_secret": client_secret,
        }
    )
    token = tokens.get("access_token", "")
    if not token:
        raise OAuthError("Google did not return an access token for the saved channel.")
    return token, int(tokens.get("expires_in", 3600))


def _post_token(payload: dict[str, str]) -> dict[str, Any]:
    try:
        response = httpx.post(TOKEN_URL, data=payload, timeout=30.0)
    except httpx.HTTPError as exc:
        raise OAuthError(f"Could not reach Google's token endpoint: {exc}") from exc

    if response.status_code >= 400:
        raise OAuthError(_google_message(response))
    return response.json()


def disconnect(settings: config.Settings | None = None) -> None:
    """Forget the channel and revoke the refresh token at Google."""
    settings = settings or config.load()
    refresh_token = config.get_secret(config.YOUTUBE_REFRESH_TOKEN_KEY, settings)
    if refresh_token:
        try:
            httpx.post(REVOKE_URL, data={"token": refresh_token}, timeout=15.0)
        except httpx.HTTPError as exc:  # revoking is best effort
            log.warning("Could not revoke the YouTube token: %s", exc)

    config.delete_secret(config.YOUTUBE_REFRESH_TOKEN_KEY, settings)
    settings.youtube.channel_id = ""
    settings.youtube.channel_title = ""
    settings.youtube.channel_url = ""
    settings.youtube.connected_at = ""
    config.save(settings)
    _token_cache["access_token"] = ""
    _token_cache["expires_at"] = 0.0


def _google_message(response: httpx.Response) -> str:
    try:
        body = response.json()
    except ValueError:
        return f"Google returned HTTP {response.status_code}."
    description = body.get("error_description") or body.get("error") or ""
    if isinstance(description, dict):
        description = description.get("message", "")
    return f"Google rejected the sign-in: {description or response.status_code}"
