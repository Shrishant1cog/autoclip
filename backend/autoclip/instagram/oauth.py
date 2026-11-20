"""Signing in to the Instagram Platform, and the three ways Meta does it.

Meta supports three API setups, and they differ in more than a hostname
(see ``docs/INSTAGRAM-API-EVALUATION.md`` §9.1.1):

============  ==========================  ==========================  ==========
Setup         Host                        Token                       Resumable
============  ==========================  ==========================  ==========
``unified``   ``graph.facebook.com``      Business Integration System  **yes**
                                         User access token
``facebook``  ``graph.facebook.com``      Facebook Page access token   **yes**
``instagram`` ``graph.instagram.com``     Instagram User access token  **no**
============  ==========================  ==========================  ==========

The differences matter to the code, not just to the documentation:

* the **authorisation URL** is a different domain for the Instagram setup,
* the **token exchange** is a different endpoint and a different verb,
* the **account discovery** is a different endpoint in every setup, and
* the **resumable upload** — the only official way to send a local file —
  does not exist on the Instagram setup.

An access token is a secret and lives in the **OS keyring**, per account.
Nothing secret is written to SQLite or to a log line.
"""

from __future__ import annotations

import logging
import secrets
import time
from dataclasses import dataclass
from typing import Any
from urllib.parse import urlencode

import httpx

from .. import config
from ..db.models import utcnow
from ..security import consent
from ..security.egress import Transfer, gateway
from ..security.urlpolicy import UrlRejected
from . import accounts as accounts_store

log = logging.getLogger(__name__)

#: The Facebook Login for Business dialog. This one has no version in the
#: path: Meta's own documented URL for a configuration-based login is
#: ``https://www.facebook.com/dialog/oauth?...``.
FACEBOOK_DIALOG_URL = "https://www.facebook.com/dialog/oauth"

#: Business Login for Instagram's authorisation window.
INSTAGRAM_AUTHORIZE_URL = "https://www.instagram.com/oauth/authorize"

#: Where a Business Login for Instagram code is exchanged for a token.
INSTAGRAM_TOKEN_URL = "https://api.instagram.com/oauth/access_token"

#: Where a short-lived Instagram User token becomes a long-lived one.
INSTAGRAM_LONG_LIVED_URL = "https://graph.instagram.com/access_token"

#: A pending sign-in older than this is treated as abandoned.
_STATE_TTL_S = 15 * 60


@dataclass(frozen=True)
class Setup:
    """One of Meta's three API setups."""

    name: str
    #: The Graph host the publishing calls go to.
    host: str
    #: The permissions AutoClip asks for — and nothing more.
    scopes: tuple[str, ...]
    #: Whether a local file can be uploaded through the resumable protocol.
    resumable_upload: bool
    #: Whether the setup needs a Facebook Login for Business configuration.
    requires_config_id: bool
    label: str


SETUPS: dict[str, Setup] = {
    "unified": Setup(
        name="unified",
        host="graph.facebook.com",
        scopes=("instagram_basic", "instagram_content_publish"),
        resumable_upload=True,
        requires_config_id=True,
        label="Instagram API with Unified Login",
    ),
    "facebook": Setup(
        name="facebook",
        host="graph.facebook.com",
        scopes=("instagram_basic", "instagram_content_publish", "pages_read_engagement"),
        resumable_upload=True,
        requires_config_id=True,
        label="Instagram API with Facebook Login",
    ),
    "instagram": Setup(
        name="instagram",
        host="graph.instagram.com",
        scopes=("instagram_business_basic", "instagram_business_content_publish"),
        resumable_upload=False,
        requires_config_id=False,
        label="Instagram API with Instagram Login",
    ),
}


def setup_for(login_type: str) -> Setup:
    """The setup for a login type, defaulting to the recommended one."""
    return SETUPS.get(login_type, SETUPS["unified"])


class OAuthError(RuntimeError):
    """The Instagram sign-in could not be completed."""


@dataclass
class _Pending:
    verifier: str
    redirect_uri: str
    created_at: float
    #: The account this sign-in is for. The token is filed under this
    #: account's own keyring entry, so a sign-in that comes back for the
    #: wrong account cannot land on the wrong profile.
    account_id: str = ""
    label: str = ""
    login_type: str = "unified"


#: Authorisation attempts keyed by state. One user on one machine, so a
#: plain dict is enough; entries are removed on use and expire on TTL.
_pending: dict[str, _Pending] = {}

#: Page access tokens, cached per account. They are derived from the stored
#: Facebook User token and expire with it.
_page_tokens: dict[str, tuple[str, float]] = {}


# --------------------------------------------------------------------------
# Configuration checks
# --------------------------------------------------------------------------


def is_configured(settings: config.Settings | None = None) -> bool:
    """True when the app id, the app secret and the setup's own bits exist."""
    settings = settings or config.load()
    setup = setup_for(settings.instagram.login_type)
    if not settings.instagram.app_id:
        return False
    if not config.get_secret(config.INSTAGRAM_APP_SECRET_KEY, settings):
        return False
    return not (setup.requires_config_id and not settings.instagram.config_id)


def is_connected(settings: config.Settings | None = None) -> bool:
    """True when at least one account holds a usable token."""
    settings = settings or config.load()
    if not is_configured(settings):
        return False
    for account in accounts_store.list_accounts():
        if account.needs_reconnect:
            continue
        if accounts_store.token_for(account.id, settings):
            return True
    return False


# --------------------------------------------------------------------------
# Authorisation code flow
# --------------------------------------------------------------------------


def build_auth_url(
    settings: config.Settings | None = None,
    *,
    account_id: str = "",
    label: str = "",
) -> str:
    """Return Meta's consent URL and remember the pending state.

    ``account_id`` says which connected account this sign-in is for. When
    it is empty, a new account slot is created for the sign-in, so every
    account — including the second one — has a row of its own and its
    token is filed under that row.
    """
    settings = settings or config.load()
    setup = setup_for(settings.instagram.login_type)
    app_id = settings.instagram.app_id
    app_secret = config.get_secret(config.INSTAGRAM_APP_SECRET_KEY, settings)
    if not app_id or not app_secret:
        raise OAuthError("Add the Meta app ID and app secret in Settings before connecting.")
    if setup.requires_config_id and not settings.instagram.config_id:
        raise OAuthError(
            "This setup needs a Facebook Login for Business configuration id. "
            "Add it in Settings, or switch to a setup that does not."
        )

    if account_id:
        account = accounts_store.get_account(account_id)
        if account is None:
            raise OAuthError("That Instagram account no longer exists. Add it again.")
    else:
        account = accounts_store.create_account(
            label=label or "Instagram account",
            login_type=setup.name,
            config_id=settings.instagram.config_id,
        )
        account_id = account.id

    state = secrets.token_urlsafe(24)
    redirect_uri = settings.instagram.redirect_uri
    _pending[state] = _Pending(
        verifier=secrets.token_urlsafe(32),
        redirect_uri=redirect_uri,
        created_at=time.monotonic(),
        account_id=account_id,
        label=label,
        login_type=setup.name,
    )
    _prune_pending()

    if setup.name == "instagram":
        params = {
            "client_id": app_id,
            "redirect_uri": redirect_uri,
            "response_type": "code",
            "scope": ",".join(setup.scopes),
            "state": state,
            # The Facebook Login option is hidden: this setup authenticates
            # the Instagram account itself.
            "enable_fb_login": "false",
        }
        return f"{INSTAGRAM_AUTHORIZE_URL}?{urlencode(params)}"

    params = {
        "client_id": app_id,
        "config_id": settings.instagram.config_id,
        "redirect_uri": redirect_uri,
        "response_type": "code",
        "display": "popup",
        "prompt": "login",
        "state": state,
    }
    return f"{FACEBOOK_DIALOG_URL}?{urlencode(params)}"


def _prune_pending() -> None:
    now = time.monotonic()
    for state in [s for s, p in _pending.items() if now - p.created_at > _STATE_TTL_S]:
        _pending.pop(state, None)


def complete_auth(code: str, state: str, settings: config.Settings | None = None) -> dict[str, str]:
    """Exchange an authorisation code, find the account, and save the token.

    The token is filed under the account the sign-in started for, and the
    Instagram account Meta reports becomes that account's record. The
    destination identity therefore comes from Meta and is stored, not
    guessed from the settings file.
    """
    settings = settings or config.load()
    pending = _pending.pop(state, None)
    if pending is None:
        raise OAuthError("That sign-in link has expired or was already used. Press Connect again.")
    if time.monotonic() - pending.created_at > _STATE_TTL_S:
        raise OAuthError("The sign-in took too long. Press Connect again.")

    setup = setup_for(pending.login_type)
    app_id = settings.instagram.app_id
    app_secret = config.get_secret(config.INSTAGRAM_APP_SECRET_KEY, settings)
    if not app_id or not app_secret:
        raise OAuthError("The Meta app credentials are missing from Settings.")

    # Instagram appends "#_" to the redirect URI. It is not part of the code.
    code = code.strip().removesuffix("#_")

    if setup.name == "instagram":
        token, ig_user_id, username, name = _exchange_instagram_code(
            code=code,
            redirect_uri=pending.redirect_uri,
            app_id=app_id,
            app_secret=app_secret,
            settings=settings,
        )
        page_id = ""
        business_id = ""
    else:
        token = _exchange_facebook_code(
            code=code,
            app_id=app_id,
            app_secret=app_secret,
            settings=settings,
        )
        ig_user_id, username, name, page_id, business_id = _discover_facebook_accounts(
            token=token,
            setup=setup,
            settings=settings,
        )

    if not ig_user_id:
        raise OAuthError(
            "Meta did not report an Instagram account for this sign-in. "
            "Check that the app asks for the Instagram content permissions."
        )

    account_id = pending.account_id
    account = accounts_store.get_account(account_id) if account_id else None
    if account is None:
        account = accounts_store.create_account(
            label=pending.label or username or "Instagram account",
            login_type=setup.name,
        )
        account_id = account.id

    # The account now holds a working credential, so any earlier failure
    # is over.
    accounts_store.clear_needs_reconnect(account_id)
    accounts_store.store_token(account_id, token, settings)
    accounts_store.update_account(
        account_id,
        ig_user_id=ig_user_id,
        username=username,
        name=name,
        label=account.label or username or "Instagram account",
        login_type=setup.name,
        page_id=page_id,
        business_id=business_id,
        config_id=settings.instagram.config_id,
        connected_at=utcnow(),
    )

    if setup.name == "instagram":
        # The long-lived token is the one that is worth keeping.
        long_lived = _long_lived_instagram_token(token, app_id, app_secret, settings)
        if long_lived:
            accounts_store.store_token(account_id, long_lived, settings)

    return {
        "id": ig_user_id,
        "username": username,
        "name": name,
        "account_row_id": account_id,
        "title": username or name or ig_user_id,
    }


def _exchange_instagram_code(
    *,
    code: str,
    redirect_uri: str,
    app_id: str,
    app_secret: str,
    settings: config.Settings,
) -> tuple[str, str, str, str]:
    """Business Login for Instagram: code → short-lived token → long-lived."""
    payload = {
        "client_id": app_id,
        "client_secret": app_secret,
        "grant_type": "authorization_code",
        "redirect_uri": redirect_uri,
        "code": code,
    }
    body = _post_form(INSTAGRAM_TOKEN_URL, payload, "Instagram")
    access_token = str(body.get("access_token") or "")
    if not access_token:
        raise OAuthError("Instagram did not return an access token.")

    ig_user_id = str(body.get("user_id") or "")
    username = ""
    name = ""
    try:
        profile = _graph_get(
            setup_for("instagram"),
            settings,
            path="me",
            params={"fields": "id,username,name"},
            token=access_token,
        )
        ig_user_id = ig_user_id or str(profile.get("id") or "")
        username = str(profile.get("username") or "")
        name = str(profile.get("name") or "")
    except OAuthError:
        # The token is already good; a failed profile lookup only costs the
        # nice-to-have fields.
        log.debug("Could not read the Instagram profile.", exc_info=True)
    return access_token, ig_user_id, username, name


def _long_lived_instagram_token(
    short_token: str, app_id: str, app_secret: str, settings: config.Settings
) -> str:
    """Exchange a short-lived Instagram User token for a 60-day one."""
    try:
        body = _graph_get_raw(
            setup_for("instagram"),
            settings,
            path="access_token",
            params={
                "grant_type": "fb_exchange_token",
                "client_id": app_id,
                "client_secret": app_secret,
                "fb_exchange_token": short_token,
            },
            base_host="graph.instagram.com",
        )
    except OAuthError:
        log.warning("Could not exchange the Instagram token for a long-lived one.")
        return ""
    return str(body.get("access_token") or "")


def _exchange_facebook_code(
    *, code: str, app_id: str, app_secret: str, settings: config.Settings
) -> str:
    """Facebook Login for Business: code → Business Integration System token."""
    body = _graph_get_raw(
        setup_for("unified"),
        settings,
        path="oauth/access_token",
        params={
            "client_id": app_id,
            "client_secret": app_secret,
            "code": code,
        },
        base_host="graph.facebook.com",
    )
    access_token = str(body.get("access_token") or "")
    if not access_token:
        raise OAuthError("Meta did not return an access token.")
    return access_token


def _discover_facebook_accounts(
    *,
    token: str,
    setup: Setup,
    settings: config.Settings,
) -> tuple[str, str, str, str, str]:
    """Find the Instagram account Meta assigned to this app.

    The Unified Login setup lists the accounts the business shared through
    ``/me/assigned_instagram_accounts``. The Page-linked setup lists the
    Pages through ``/me/accounts``, and each Page carries the Instagram
    account linked to it.
    """
    business_id = ""
    ig_user_id = ""
    username = ""
    name = ""
    page_id = ""

    if setup.name == "facebook":
        try:
            pages = _graph_get(
                setup,
                settings,
                path="me/accounts",
                params={"fields": "name,access_token,instagram_business_account"},
                token=token,
            )
        except OAuthError:
            pages = {}
        for page in pages.get("data") or []:
            ig = page.get("instagram_business_account") or {}
            if not ig.get("id"):
                continue
            page_id = str(page.get("id") or "")
            ig_user_id = str(ig.get("id") or "")
            username = str(ig.get("username") or "")
            name = str(page.get("name") or "")
            break
        if not ig_user_id:
            raise OAuthError(
                "None of the Facebook Pages this account can use has an Instagram "
                "professional account linked to it."
            )
        return ig_user_id, username, name, page_id, business_id

    # Unified Login: the business id comes with the token, and the Instagram
    # accounts are the ones the business shared.
    try:
        me = _graph_get(
            setup, settings, path="me", params={"fields": "client_business_id"}, token=token
        )
        business_id = str(me.get("client_business_id") or "")
    except OAuthError:
        log.debug("Could not read the client business id.", exc_info=True)

    try:
        assigned = _graph_get(
            setup,
            settings,
            path="me/assigned_instagram_accounts",
            params={"fields": "id,username,name"},
            token=token,
        )
    except OAuthError:
        assigned = {}
    accounts = assigned.get("data") or []
    if not accounts:
        raise OAuthError(
            "No Instagram professional account was shared with this app. "
            "Open AutoClip's Facebook Login for Business configuration and "
            "select the Instagram account to share."
        )
    first = accounts[0]
    ig_user_id = str(first.get("id") or "")
    username = str(first.get("username") or "")
    name = str(first.get("name") or "")
    return ig_user_id, username, name, page_id, business_id


# --------------------------------------------------------------------------
# Tokens
# --------------------------------------------------------------------------


def access_token(settings: config.Settings | None = None, account_id: str | None = None) -> str:
    """Return a token to use for the Graph calls.

    On the Page-linked setup the stored credential is a Facebook User
    token, and the Page access token is derived from it. The Page token is
    cached in memory for an hour, because it is fetched on demand and is
    not worth a round trip per request.
    """
    settings = settings or config.load()
    account = (
        accounts_store.get_account(account_id) if account_id else accounts_store.default_account()
    )
    if account is None:
        raise OAuthError("No Instagram account is connected. Press Connect in Settings.")

    token = accounts_store.token_for(account.id, settings)
    if not token:
        raise OAuthError("That Instagram account has no stored credential. Connect it again.")

    if account.login_type != "facebook":
        return token

    cached = _page_tokens.get(account.id)
    if cached and time.monotonic() < cached[1]:
        return cached[0]

    setup = setup_for("facebook")
    try:
        pages = _graph_get(
            setup,
            settings,
            path="me/accounts",
            params={"fields": "id,access_token"},
            token=token,
        )
    except OAuthError as exc:
        raise exc
    for page in pages.get("data") or []:
        if str(page.get("id") or "") != account.page_id:
            continue
        page_token = str(page.get("access_token") or "")
        if page_token:
            _page_tokens[account.id] = (page_token, time.monotonic() + 3600)
            return page_token
    raise OAuthError(
        "The Facebook Page this account is linked to could not be read. Connect the account again."
    )


def forget_cached_tokens(account_id: str = "") -> None:
    """Drop cached tokens so the next call tries the credential again."""
    if account_id:
        _page_tokens.pop(account_id, None)


def disconnect(settings: config.Settings | None = None, *, account_id: str = "") -> None:
    """Forget an account's credential.

    With ``account_id`` only that account is disconnected. Without it, the
    oldest account — the one the legacy settings refer to — is disconnected
    and the others are left alone.
    """
    settings = settings or config.load()
    if not account_id:
        account = accounts_store.default_account()
        account_id = account.id if account is not None else ""
    if not account_id:
        return

    accounts_store.forget_token(account_id, settings)
    accounts_store.clear_needs_reconnect(account_id)
    forget_cached_tokens(account_id)


# --------------------------------------------------------------------------
# HTTP
# --------------------------------------------------------------------------


def _transfer(url: str, summary: str) -> Transfer:
    return Transfer(
        operation=consent.Operation.PUBLISHING,
        url=url,
        data_summary=summary,
        provider="instagram",
        requires_consent=False,
    )


def _post_form(url: str, payload: dict[str, str], provider: str) -> dict[str, Any]:
    transfer = _transfer(url, "The Meta sign-in code, exchanged for an access token.")
    try:
        gateway.authorize(transfer)
    except UrlRejected as exc:
        raise OAuthError(f"Meta was refused as a destination: {exc}") from exc
    try:
        response = httpx.post(url, data=payload, timeout=30.0)
    except httpx.HTTPError as exc:
        gateway.record(transfer, "failed", detail=str(exc))
        raise OAuthError(f"Could not reach {provider}: {exc}") from exc
    if response.status_code >= 400:
        gateway.record(transfer, "failed", detail=f"HTTP {response.status_code}")
        raise OAuthError(_meta_message(response))
    gateway.record(transfer, "ok")
    try:
        return response.json()
    except ValueError as exc:
        raise OAuthError(f"{provider} returned unreadable output.") from exc


def _graph_get_raw(
    setup: Setup,
    settings: config.Settings,
    *,
    path: str,
    params: dict[str, str],
    base_host: str = "",
) -> dict[str, Any]:
    """A GET against a Graph host, with the version in the path."""
    host = base_host or setup.host
    url = f"https://{host}/{settings.instagram.api_version}/{path.lstrip('/')}"
    transfer = _transfer(url, "The Instagram account identity and its credential.")
    try:
        gateway.authorize(transfer)
    except UrlRejected as exc:
        raise OAuthError(f"Meta was refused as a destination: {exc}") from exc
    try:
        response = httpx.get(url, params=params, timeout=30.0)
    except httpx.HTTPError as exc:
        gateway.record(transfer, "failed", detail=str(exc))
        raise OAuthError(f"Could not reach Meta: {exc}") from exc
    if response.status_code >= 400:
        gateway.record(transfer, "failed", detail=f"HTTP {response.status_code}")
        raise OAuthError(_meta_message(response))
    gateway.record(transfer, "ok")
    try:
        return response.json()
    except ValueError as exc:
        raise OAuthError("Meta returned unreadable output.") from exc


def _graph_get(
    setup: Setup,
    settings: config.Settings,
    *,
    path: str,
    params: dict[str, str],
    token: str,
) -> dict[str, Any]:
    query = dict(params)
    query["access_token"] = token
    return _graph_get_raw(setup, settings, path=path, params=query)


def _meta_message(response: httpx.Response) -> str:
    try:
        body = response.json()
    except ValueError:
        return f"Meta returned HTTP {response.status_code}."
    error = body.get("error")
    if isinstance(error, dict):
        message = error.get("error_user_msg") or error.get("message") or ""
        if message:
            return str(message)
    if isinstance(error, str) and error:
        return f"Meta rejected the sign-in: {error}"
    return f"Meta returned HTTP {response.status_code}."
