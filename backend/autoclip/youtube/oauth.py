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


class InvalidGrantError(OAuthError):
    """Google says the stored credential is no longer valid.

    This is not a transient failure: the refresh token has been revoked,
    expired, or the owner changed their password. Retrying it will fail
    the same way, so the account is marked as needing a new sign-in and
    the other accounts carry on.
    """


@dataclass
class _Pending:
    verifier: str
    redirect_uri: str
    created_at: float
    #: The Google account this sign-in is for. The token is filed under
    #: this account's own keyring entry, so a sign-in that comes back for
    #: the wrong account cannot land on the wrong channel.
    account_id: str = ""
    #: The label to give the account if it has to be created.
    account_label: str = ""


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
    if (
        is_configured(settings)
        and settings.youtube.channel_id
        and config.get_secret(config.YOUTUBE_REFRESH_TOKEN_KEY, settings)
    ):
        return True
    # A newer-style connection: at least one account holds a token. The
    # legacy entry is deliberately not consulted here — it belongs to the
    # oldest account, and that account's own entry is the one that counts.
    try:
        from . import accounts as accounts_store

        for account in accounts_store.list_accounts():
            if account.get("needs_reconnect"):
                continue
            if accounts_store.refresh_token_for(account["id"], settings):
                return True
    except Exception:  # noqa: BLE001 - a broken store must not crash the app
        log.debug("Could not read the connected accounts.", exc_info=True)
    return False


# --------------------------------------------------------------------------
# Authorization code flow
# --------------------------------------------------------------------------


def _pkce_pair() -> tuple[str, str]:
    verifier = secrets.token_urlsafe(64)
    digest = hashlib.sha256(verifier.encode("ascii")).digest()
    challenge = base64.urlsafe_b64encode(digest).rstrip(b"=").decode("ascii")
    return verifier, challenge


def build_auth_url(
    settings: config.Settings | None = None,
    *,
    account_id: str = "",
    label: str = "",
) -> str:
    """Return the Google consent URL and remember the pending state/verifier.

    ``account_id`` says which connected account this sign-in is for. When
    it is empty, a new account slot is created for the sign-in, so every
    account — including the second one — has a row of its own and its
    token is filed under that row.
    """
    settings = settings or config.load()
    client_id = settings.youtube.client_id
    client_secret = config.get_secret(config.YOUTUBE_CLIENT_SECRET_KEY, settings)
    if not client_id or not client_secret:
        raise OAuthError("Add the Google OAuth client ID and secret in Settings before connecting.")

    from . import accounts as accounts_store

    if account_id:
        account = accounts_store.get_account(account_id)
        if account is None:
            raise OAuthError("That Google account no longer exists. Add it again.")
    else:
        account = accounts_store.create_account(
            label=label or "Google account", client_id=client_id
        )
        account_id = account["id"]

    state = secrets.token_urlsafe(24)
    verifier, challenge = _pkce_pair()
    redirect_uri = settings.youtube.redirect_uri

    _pending[state] = _Pending(
        verifier=verifier,
        redirect_uri=redirect_uri,
        created_at=time.monotonic(),
        account_id=account_id,
        account_label=label,
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
    """Exchange an authorization code, fetch the channel, and save the token.

    The token is filed under the account the sign-in started for, and the
    channel Google reports becomes that account's channel record. The
    destination identity therefore comes from Google and is stored, not
    guessed from the settings file.
    """
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

    from . import accounts as accounts_store

    account_id = pending.account_id
    account = accounts_store.get_account(account_id) if account_id else None
    if account is None:
        account = accounts_store.create_account(
            label=pending.account_label or "Google account", client_id=client_id
        )
        account_id = account["id"]

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

    channel = fetch_channel(access_token)

    # The account now holds a working credential, so any earlier failure
    # is over.
    accounts_store.clear_needs_reconnect(account_id)
    accounts_store.store_refresh_token(account_id, refresh_token, settings)
    accounts_store.upsert_channel(
        account_id,
        channel,
        privacy=settings.youtube.privacy,
        category_id=settings.youtube.category_id,
        auto_upload=settings.youtube.auto_upload,
        made_for_kids=settings.youtube.made_for_kids,
    )
    accounts_store.update_account(account_id, connected_at=utcnow())

    if accounts_store.is_first_account(account_id):
        # The oldest account is the one the pre-multi-account code paths
        # mean by "the connected channel", so the legacy settings and the
        # legacy keyring entry are kept in step with it. A second account
        # deliberately leaves them alone: it must not take over the
        # destination the first account already publishes to.
        config.set_secret(config.YOUTUBE_REFRESH_TOKEN_KEY, refresh_token, settings)
        settings.youtube.channel_id = channel["id"]
        settings.youtube.channel_title = channel["title"]
        settings.youtube.channel_url = channel["url"]
        settings.youtube.connected_at = utcnow()
        config.save(settings)

    _cache_token_for(account_id, access_token, int(tokens.get("expires_in", 3600)))
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


def _cache_token_for(account_id: str, access_token: str, expires_in: int) -> None:
    """Cache an access token against the account it belongs to."""
    if not account_id:
        _cache_token(access_token, expires_in)
        return
    _tokens_by_account[account_id] = {
        "access_token": access_token,
        "expires_at": time.monotonic() + max(expires_in - 60, 30),
    }


def _forget_cached_token(account_id: str) -> None:
    """Drop a cached access token so the next call tries the credential again."""
    if account_id:
        _tokens_by_account.pop(account_id, None)
        return
    _token_cache["access_token"] = ""
    _token_cache["expires_at"] = 0.0


def access_token(settings: config.Settings | None = None, account_id: str | None = None) -> str:
    """Return a valid access token, refreshing it when necessary.

    With ``account_id`` the token belongs to that connected Google account;
    without it the legacy single-account token is used.

    A credential Google has revoked raises :class:`InvalidGrantError` and
    marks **only** that account as needing a new sign-in. The other
    accounts keep working: one revoked token is not a reason to stop
    publishing everywhere.
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
        try:
            token, expires_in = _refresh(refresh_token, settings)
        except InvalidGrantError as exc:
            _forget_cached_token(account_id)
            _mark_needs_reconnect(account_id, str(exc))
            raise
        _cache_token_for(account_id, token, expires_in)
        return token

    if _token_cache["access_token"] and time.monotonic() < _token_cache["expires_at"]:
        return _token_cache["access_token"]

    refresh_token = config.get_secret(config.YOUTUBE_REFRESH_TOKEN_KEY, settings)
    if not refresh_token:
        raise OAuthError("No YouTube channel is connected. Press Connect YouTube channel.")

    try:
        token, expires_in = _refresh(refresh_token, settings)
    except InvalidGrantError:
        _forget_cached_token("")
        raise
    _cache_token(token, expires_in)
    return token


def _mark_needs_reconnect(account_id: str, reason: str) -> None:
    """Record a broken credential against one account, and only that one."""
    try:
        from . import accounts as accounts_store

        accounts_store.mark_needs_reconnect(account_id, reason)
    except Exception:  # noqa: BLE001 - the flag is a convenience, not the fix
        log.debug("Could not mark account %s as needing a reconnect.", account_id, exc_info=True)


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
        message = _google_message(response)
        if _is_invalid_grant(response):
            raise InvalidGrantError(message)
        raise OAuthError(message)
    return response.json()


def _is_invalid_grant(response: httpx.Response) -> bool:
    """True when Google rejected the *credential* rather than the request.

    ``invalid_grant`` means the refresh token has been revoked, expired,
    or was issued to a different client. It is permanent: retrying it
    fails the same way, so the account is marked rather than retried.
    """
    try:
        body = response.json()
    except ValueError:
        return False
    error = body.get("error")
    if error == "invalid_grant":
        return True
    return isinstance(error, str) and "invalid_grant" in error


def disconnect(settings: config.Settings | None = None, *, account_id: str = "") -> None:
    """Forget a channel and revoke its refresh token at Google.

    With ``account_id`` only that account is disconnected. Without it,
    the legacy connection is disconnected — which is the oldest account,
    so the other accounts are left alone.
    """
    settings = settings or config.load()
    from . import accounts as accounts_store

    if account_id:
        refresh_token = accounts_store.refresh_token_for(account_id, settings)
        if refresh_token:
            _revoke(refresh_token)
        accounts_store.forget_refresh_token(account_id, settings)
        _forget_cached_token(account_id)
        accounts_store.clear_needs_reconnect(account_id)
        if accounts_store.is_first_account(account_id):
            config.delete_secret(config.YOUTUBE_REFRESH_TOKEN_KEY, settings)
            settings.youtube.channel_id = ""
            settings.youtube.channel_title = ""
            settings.youtube.channel_url = ""
            settings.youtube.connected_at = ""
            config.save(settings)
        return

    refresh_token = config.get_secret(config.YOUTUBE_REFRESH_TOKEN_KEY, settings)
    if refresh_token:
        _revoke(refresh_token)
    config.delete_secret(config.YOUTUBE_REFRESH_TOKEN_KEY, settings)
    settings.youtube.channel_id = ""
    settings.youtube.channel_title = ""
    settings.youtube.channel_url = ""
    settings.youtube.connected_at = ""
    config.save(settings)
    _token_cache["access_token"] = ""
    _token_cache["expires_at"] = 0.0

    # The legacy entry was the oldest account's token; drop that account's
    # own copy too, so the account does not look connected.
    try:
        first = accounts_store.default_account()
    except Exception:  # noqa: BLE001
        first = None
    if first is not None:
        accounts_store.forget_refresh_token(first["id"], settings)
        accounts_store.clear_needs_reconnect(first["id"])
        _forget_cached_token(first["id"])


def _revoke(refresh_token: str) -> None:
    """Ask Google to invalidate a refresh token. Best effort."""
    try:
        httpx.post(REVOKE_URL, data={"token": refresh_token}, timeout=15.0)
    except httpx.HTTPError as exc:  # revoking is best effort
        log.warning("Could not revoke the YouTube token: %s", exc)


def _google_message(response: httpx.Response) -> str:
    try:
        body = response.json()
    except ValueError:
        return f"Google returned HTTP {response.status_code}."
    description = body.get("error_description") or body.get("error") or ""
    if isinstance(description, dict):
        description = description.get("message", "")
    return f"Google rejected the sign-in: {description or response.status_code}"
