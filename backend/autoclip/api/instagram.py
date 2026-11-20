"""Instagram connection, eligibility, and publish status."""

from __future__ import annotations

import asyncio
import html
import logging

from fastapi import APIRouter, HTTPException, Query
from fastapi.responses import HTMLResponse

from .. import config
from ..db import store
from ..instagram import accounts as accounts_store
from ..instagram import media as media_module
from ..instagram import oauth, publisher, uploads
from ..instagram.errors import InstagramError
from ..instagram.queue import instagram_upload_queue
from .schemas import (
    InstagramAccountOut,
    InstagramAutoIn,
    InstagramConnectIn,
    InstagramConnectOut,
    InstagramDisconnectIn,
    InstagramEnqueueIn,
    InstagramStatusOut,
    InstagramUploadConfirmIn,
    InstagramUploadEditIn,
    InstagramUploadOut,
)

log = logging.getLogger(__name__)

router = APIRouter(prefix="/api/instagram", tags=["instagram"])


def _status(settings: config.Settings) -> InstagramStatusOut:
    account = accounts_store.default_account()
    return InstagramStatusOut(
        configured=oauth.is_configured(settings),
        connected=oauth.is_connected(settings),
        auto_upload=settings.instagram.auto_upload,
        app_id=settings.instagram.app_id,
        redirect_uri=settings.instagram.redirect_uri,
        login_type=settings.instagram.login_type,
        api_version=settings.instagram.api_version,
        config_id=settings.instagram.config_id,
        ig_user_id=account.ig_user_id if account else settings.instagram.ig_user_id,
        username=account.username if account else settings.instagram.username,
        connected_at=account.connected_at if account else settings.instagram.connected_at,
        professional=bool(account.professional) if account else False,
    )


@router.get("/status", response_model=InstagramStatusOut)
async def status() -> InstagramStatusOut:
    return _status(config.load())


@router.post("/connect", response_model=InstagramConnectOut)
async def connect(payload: InstagramConnectIn | None = None) -> InstagramConnectOut:
    """Start the Meta sign-in and hand the browser the consent URL.

    ``account_id`` says which connected account this sign-in is for; an
    empty one creates a new account slot. Either way the token that comes
    back is filed under that account, so a second account keeps its own
    credential.
    """
    payload = payload or InstagramConnectIn()
    try:
        url = oauth.build_auth_url(
            config.load(),
            account_id=payload.account_id,
            label=payload.label,
        )
    except oauth.OAuthError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return InstagramConnectOut(auth_url=url)


@router.get("/callback", response_class=HTMLResponse)
async def callback(
    code: str | None = Query(default=None),
    state: str | None = Query(default=None),
    error: str | None = Query(default=None),
) -> HTMLResponse:
    """Meta's redirect target. Renders a small page that closes the popup."""
    if error:
        return _page(False, f"Meta reported: {error}")
    if not code or not state:
        return _page(False, "Meta did not return an authorization code.")

    try:
        account = oauth.complete_auth(code, state)
    except oauth.OAuthError as exc:
        log.warning("Instagram sign-in failed: %s", exc)
        return _page(False, str(exc))

    return _page(True, f"Connected to {account.get('title') or 'your account'}.")


@router.post("/disconnect", response_model=InstagramStatusOut)
async def disconnect(payload: InstagramDisconnectIn | None = None) -> InstagramStatusOut:
    """Disconnect one account, or the oldest one.

    Disconnecting one account leaves the others connected: an account that
    is no longer wanted must not take the other accounts down with it.
    """
    payload = payload or InstagramDisconnectIn()
    settings = config.load()
    await asyncio.to_thread(oauth.disconnect, settings, account_id=payload.account_id)
    return _status(settings)


@router.post("/auto-upload", response_model=InstagramStatusOut)
async def set_auto_upload(payload: InstagramAutoIn) -> InstagramStatusOut:
    """Turn automatic post-on-export on or off."""
    settings = config.load()
    if payload.enabled and not oauth.is_connected(settings):
        raise HTTPException(
            status_code=400,
            detail="Connect an Instagram account before turning automation on.",
        )
    settings.instagram.auto_upload = payload.enabled
    config.save(settings)
    return _status(settings)


@router.get("/accounts", response_model=list[InstagramAccountOut])
def list_accounts() -> list[InstagramAccountOut]:
    """Every account, and whether a credential is held for it.

    The token itself is never sent to the browser — only the fact that
    one exists.
    """
    settings = config.load()
    out: list[InstagramAccountOut] = []
    for account in accounts_store.list_accounts():
        out.append(
            InstagramAccountOut(
                id=account.id,
                ig_user_id=account.ig_user_id,
                username=account.username,
                name=account.name,
                label=account.label,
                login_type=account.login_type,
                page_id=account.page_id,
                business_id=account.business_id,
                professional=account.professional,
                needs_reconnect=account.needs_reconnect,
                last_error=account.last_error,
                created_at=account.created_at,
                updated_at=account.updated_at,
                connected_at=account.connected_at,
                has_token=bool(accounts_store.token_for(account.id, settings)),
            )
        )
    return out


@router.get("/eligibility")
async def eligibility() -> dict:
    """What can and cannot be published, and what is still unverified.

    This endpoint never refuses. It reports what Meta documents, what
    AutoClip observed, and what is **unverified** — so the page can say
    what is still missing instead of showing a blank refusal.
    """
    settings = config.load()
    setup = oauth.setup_for(settings.instagram.login_type)
    account = accounts_store.default_account()

    requirements = [
        "The account must be an Instagram professional account (Business or Creator).",
        "A Page that requires Page Publishing Authorization must have PPA completed.",
        "A Page that requires two-factor authentication needs it completed too.",
        "Advanced Access — which needs App Review and Business Verification — is "
        "required only for accounts AutoClip does not own.",
    ]

    observations: list[str] = []
    unverified: list[str] = []
    limit: dict = publisher.PublishingLimit().to_dict()

    if account is None:
        unverified.append("No Instagram account is connected.")
    else:
        if account.needs_reconnect:
            observations.append(
                f"Instagram needs {account.username or 'this account'} to be connected again."
            )
        if not account.professional:
            unverified.append(
                "Whether the account is a professional account. The Graph API does not "
                "report this with the publishing permissions alone, so AutoClip does not "
                "claim it. Meta refuses the publish if it is not."
            )
        try:
            token = await asyncio.to_thread(oauth.access_token, settings, account.id)
            live = await asyncio.to_thread(
                publisher.publishing_limit, settings, account, token=token
            )
            limit = live.to_dict()
            if not live.known:
                unverified.append("The publishing limit could not be read from Meta right now.")
        except (oauth.OAuthError, InstagramError) as exc:
            unverified.append(f"The publishing limit could not be read: {exc}")

    return {
        "login_type": setup.name,
        "setup_label": setup.label,
        "host": setup.host,
        "scopes": list(setup.scopes),
        "resumable_upload": setup.resumable_upload,
        "local_file_supported": setup.resumable_upload,
        "requirements": requirements,
        "observations": observations,
        "unverified": unverified,
        "publishing_limit": limit,
    }


@router.get("/limit")
async def limit() -> dict:
    """The account's publishing allowance, as Meta reports it.

    The number is read from Meta rather than hardcoded: Meta's own
    documents disagree about it, and the endpoint knows what is in force.
    """
    settings = config.load()
    account = accounts_store.default_account()
    if account is None:
        raise HTTPException(status_code=404, detail="No Instagram account is connected.")
    try:
        token = await asyncio.to_thread(oauth.access_token, settings, account.id)
        live = await asyncio.to_thread(publisher.publishing_limit, settings, account, token=token)
    except (oauth.OAuthError, InstagramError) as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc
    return live.to_dict()


@router.get("/uploads", response_model=list[InstagramUploadOut])
def list_uploads(clip_id: str = Query(min_length=1)) -> list[InstagramUploadOut]:
    return [InstagramUploadOut.of(u) for u in store.list_instagram_uploads_for_clip(clip_id)]


@router.get("/uploads/{upload_id}", response_model=InstagramUploadOut)
def get_upload(upload_id: str) -> InstagramUploadOut:
    """One post attempt, with the state it reached."""
    upload = store.get_instagram_upload(upload_id)
    if upload is None:
        raise HTTPException(status_code=404, detail="Upload not found.")
    return InstagramUploadOut.of(upload)


@router.put("/uploads/{upload_id}", response_model=InstagramUploadOut)
async def edit_upload(upload_id: str, payload: InstagramUploadEditIn) -> InstagramUploadOut:
    """Change what a queued post will say.

    This is the owner's chance to correct the caption *before* the file
    leaves the machine. A post that has already run cannot be edited here
    — changing what Instagram published is a different thing, and
    pretending otherwise would be a lie.
    """
    upload = store.get_instagram_upload(upload_id)
    if upload is None:
        raise HTTPException(status_code=404, detail="Upload not found.")
    if upload.status == "done":
        raise HTTPException(
            status_code=409,
            detail="This post is already on Instagram. Change it in the Instagram app instead.",
        )

    fields: dict[str, object] = {}
    if payload.caption is not None:
        problems = media_module.validate_caption(payload.caption)
        if problems:
            raise HTTPException(status_code=400, detail="; ".join(problems))
        fields["caption"] = payload.caption
    if payload.is_ai_generated is not None:
        fields["is_ai_generated"] = payload.is_ai_generated

    if fields:
        await asyncio.to_thread(store.update_instagram_upload, upload_id, **fields)  # type: ignore[arg-type]
    updated = store.get_instagram_upload(upload_id)
    assert updated is not None
    return InstagramUploadOut.of(updated)


@router.post("/uploads", response_model=InstagramUploadOut, status_code=201)
async def enqueue(payload: InstagramEnqueueIn) -> InstagramUploadOut:
    """Queue one export for Instagram.

    The account is named explicitly. AutoClip never guesses which
    Instagram account a clip should go to.
    """
    account_row_id = payload.account_row_id
    if not account_row_id:
        account = accounts_store.default_account()
        if account is None:
            raise HTTPException(
                status_code=400,
                detail="Connect an Instagram account before publishing.",
            )
        account_row_id = account.id
    else:
        account = accounts_store.get_account(account_row_id)
        if account is None:
            raise HTTPException(status_code=404, detail="Instagram account not found.")

    try:
        row = await asyncio.to_thread(
            uploads.enqueue,
            payload.export_id,
            account_row_id=account_row_id,
            caption=payload.caption,
            is_ai_generated=payload.is_ai_generated,
        )
    except InstagramError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    instagram_upload_queue.notify()
    return InstagramUploadOut.of(row)


@router.put("/uploads/{upload_id}/confirm", response_model=InstagramUploadOut)
async def confirm_upload(upload_id: str, payload: InstagramUploadConfirmIn) -> InstagramUploadOut:
    """Record a post the owner found on Instagram.

    The owner looked at Instagram's own page and saw the post, but
    AutoClip does not take that on trust: the media id is read back from
    Instagram first, and a media id Instagram does not recognise is
    refused with a 409 rather than recorded.
    """
    upload = store.get_instagram_upload(upload_id)
    if upload is None:
        raise HTTPException(status_code=404, detail="Upload not found.")
    try:
        row = await asyncio.to_thread(
            uploads.confirm_upload,
            upload_id,
            payload.media_id,
        )
    except InstagramError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    if row is None:
        raise HTTPException(status_code=404, detail="Upload not found.")
    return InstagramUploadOut.of(row)


@router.post("/uploads/{upload_id}/retry", response_model=InstagramUploadOut)
async def retry_upload(upload_id: str) -> InstagramUploadOut:
    """Put a failed post back in the queue."""
    upload = await asyncio.to_thread(uploads.retry_upload, upload_id)
    if upload is None:
        raise HTTPException(status_code=404, detail="Upload not found.")
    if upload.status == "done":
        raise HTTPException(status_code=409, detail="This clip is already on Instagram.")
    instagram_upload_queue.notify()
    return InstagramUploadOut.of(upload)


@router.get("/validate")
def validate_export(export_id: str = Query(min_length=1)) -> dict:
    """Measure an export against Instagram's documented limits.

    Nothing is sent. This is the check the publish will make, so the
    owner can see it before the file leaves the machine.
    """
    export = store.get_export(export_id)
    if export is None:
        raise HTTPException(status_code=404, detail="Export not found.")
    from pathlib import Path

    try:
        report = media_module.validate_reel(Path(export.path))
    except media_module.MediaInvalid as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return report.to_dict()


def _page(ok: bool, message: str) -> HTMLResponse:
    """A self-contained completion page; it closes itself when opened as a popup."""
    title = "Instagram connected" if ok else "Instagram connection failed"
    colour = "#22c55e" if ok else "#ef4444"
    body = f"""<!doctype html>
<html lang="en"><head><meta charset="utf-8"><title>{title}</title>
<style>
 body {{ font-family: system-ui, sans-serif; background:#0b0b0f; color:#e5e7eb;
        display:grid; place-items:center; height:100vh; margin:0; }}
 .card {{ max-width:32rem; padding:2rem; border:1px solid #27272a; border-radius:12px;
          background:#111114; text-align:center; }}
 h1 {{ font-size:1.1rem; margin:0 0 .75rem; color:{colour}; }}
 p {{ margin:0 0 1rem; line-height:1.5; color:#a1a1aa; word-break:break-word; }}
 button {{ background:#2563eb; color:white; border:0; border-radius:8px;
           padding:.5rem 1rem; font:inherit; cursor:pointer; }}
</style></head><body><div class="card">
<h1>{html.escape(title)}</h1>
<p>{html.escape(message)}</p>
<button onclick="window.close()">Close this window</button>
</div>
<script>
  // The opener polls /api/instagram/status, so closing immediately is harmless.
  setTimeout(function () {{ window.close() }}, 1200);
</script>
</body></html>"""
    return HTMLResponse(body, status_code=200 if ok else 400)
