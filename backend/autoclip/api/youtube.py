"""YouTube connection, automation toggles, and upload status."""

from __future__ import annotations

import asyncio
import html
import logging

from fastapi import APIRouter, HTTPException, Query
from fastapi.responses import HTMLResponse

from .. import config
from ..db import store
from ..youtube import oauth, policy, quota, uploads
from ..youtube.queue import upload_queue
from .schemas import (
    UploadEditIn,
    UploadOut,
    YouTubeAudienceIn,
    YouTubeAutoIn,
    YouTubeConnectIn,
    YouTubeConnectOut,
    YouTubeDisconnectIn,
    YouTubePrivacyIn,
    YouTubeStatusOut,
)

log = logging.getLogger(__name__)

router = APIRouter(prefix="/api/youtube", tags=["youtube"])


def _status(settings: config.Settings) -> YouTubeStatusOut:
    return YouTubeStatusOut(
        configured=oauth.is_configured(settings),
        connected=oauth.is_connected(settings),
        auto_upload=settings.youtube.auto_upload,
        client_id=settings.youtube.client_id,
        redirect_uri=settings.youtube.redirect_uri,
        privacy=settings.youtube.privacy,
        made_for_kids=settings.youtube.made_for_kids,
        channel_id=settings.youtube.channel_id,
        channel_title=settings.youtube.channel_title,
        channel_url=settings.youtube.channel_url,
        connected_at=settings.youtube.connected_at,
    )


@router.get("/status", response_model=YouTubeStatusOut)
async def status() -> YouTubeStatusOut:
    return _status(config.load())


@router.post("/connect", response_model=YouTubeConnectOut)
async def connect(payload: YouTubeConnectIn | None = None) -> YouTubeConnectOut:
    """Start the Google sign-in and hand the browser the consent URL.

    ``account_id`` says which connected account this sign-in is for; an
    empty one creates a new account slot. Either way the token that comes
    back is filed under that account, so a second account keeps its own
    credential.
    """
    payload = payload or YouTubeConnectIn()
    try:
        url = oauth.build_auth_url(
            config.load(),
            account_id=payload.account_id,
            label=payload.label,
        )
    except oauth.OAuthError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return YouTubeConnectOut(auth_url=url)


@router.get("/callback", response_class=HTMLResponse)
async def callback(
    code: str | None = Query(default=None),
    state: str | None = Query(default=None),
    error: str | None = Query(default=None),
) -> HTMLResponse:
    """Google's redirect target. Renders a small page that closes the popup."""
    if error:
        return _page(False, f"Google reported: {error}")
    if not code or not state:
        return _page(False, "Google did not return an authorization code.")

    try:
        channel = oauth.complete_auth(code, state)
    except oauth.OAuthError as exc:
        log.warning("YouTube sign-in failed: %s", exc)
        return _page(False, str(exc))

    return _page(True, f"Connected to {channel.get('title') or 'your channel'}.")


@router.post("/disconnect", response_model=YouTubeStatusOut)
async def disconnect(payload: YouTubeDisconnectIn | None = None) -> YouTubeStatusOut:
    """Disconnect one account, or the legacy connection.

    Disconnecting one account leaves the others connected: a channel that
    is no longer wanted must not take the other channels down with it.
    """
    payload = payload or YouTubeDisconnectIn()
    settings = config.load()
    await asyncio.to_thread(oauth.disconnect, settings, account_id=payload.account_id)
    return _status(settings)


@router.post("/auto-upload", response_model=YouTubeStatusOut)
async def set_auto_upload(payload: YouTubeAutoIn) -> YouTubeStatusOut:
    """Turn automatic upload-on-export on or off."""
    settings = config.load()
    if payload.enabled and not oauth.is_connected(settings):
        raise HTTPException(
            status_code=400,
            detail="Connect a YouTube channel before turning automation on.",
        )
    settings.youtube.auto_upload = payload.enabled
    config.save(settings)
    return _status(settings)


@router.post("/privacy", response_model=YouTubeStatusOut)
async def set_privacy(payload: YouTubePrivacyIn) -> YouTubeStatusOut:
    settings = config.load()
    settings.youtube.privacy = payload.privacy
    config.save(settings)
    return _status(settings)


@router.post("/audience", response_model=YouTubeStatusOut)
async def set_audience(payload: YouTubeAudienceIn) -> YouTubeStatusOut:
    """Record the audience declaration for the global setting.

    Three states, and the empty one is not the same as "no": it means
    the owner has not decided, and an upload is refused until they do.
    """
    settings = config.load()
    settings.youtube.made_for_kids = payload.made_for_kids
    config.save(settings)
    return _status(settings)


@router.get("/uploads", response_model=list[UploadOut])
def list_uploads(clip_id: str = Query(min_length=1)) -> list[UploadOut]:
    return [UploadOut.of(u) for u in store.list_uploads_for_clip(clip_id)]


@router.get("/uploads/{upload_id}", response_model=UploadOut)
def get_upload(upload_id: str) -> UploadOut:
    """One upload, with the policy it was — and is — publishing under."""
    upload = store.get_upload(upload_id)
    if upload is None:
        raise HTTPException(status_code=404, detail="Upload not found.")
    return UploadOut.of(upload)


@router.put("/uploads/{upload_id}", response_model=UploadOut)
async def edit_upload(upload_id: str, payload: UploadEditIn) -> UploadOut:
    """Change what a queued upload will say and how it will be seen.

    This is the owner's chance to correct the metadata and the policy
    *before* the file leaves the machine. An upload that has already run
    cannot be edited here — changing what YouTube published is a
    different thing, and pretending otherwise would be a lie.
    """
    upload = store.get_upload(upload_id)
    if upload is None:
        raise HTTPException(status_code=404, detail="Upload not found.")
    if upload.status == "done":
        raise HTTPException(
            status_code=409,
            detail="This upload has already run. Change it on YouTube instead.",
        )

    fields: dict[str, object] = {}
    if payload.title is not None:
        fields["title"] = payload.title
    if payload.description is not None:
        fields["description"] = payload.description
    if payload.tags is not None:
        fields["tags"] = payload.tags
    if payload.privacy is not None:
        fields["privacy"] = payload.privacy
    if payload.made_for_kids is not None:
        fields["made_for_kids"] = payload.made_for_kids

    if fields:
        await asyncio.to_thread(store.update_upload, upload_id, **fields)  # type: ignore[arg-type]
    updated = store.get_upload(upload_id)
    assert updated is not None
    return UploadOut.of(updated)


@router.get("/policy")
def get_policy(channel_row_id: str = Query(default="")) -> dict:
    """Describe the publishing policy for a destination.

    Unlike the other endpoints this one never refuses: it reports what
    *would* happen, including the audience declaration being unanswered,
    so the page can say what is still missing.
    """
    return policy.describe(channel_row_id)


@router.get("/quota")
def get_quota() -> dict:
    """How much of YouTube's daily API quota is left.

    An upload costs 1600 units and the default daily quota is 10 000,
    so this is the number that says whether another upload can go out
    today.
    """
    return quota.read().to_dict()


@router.post("/uploads/{upload_id}/retry", response_model=UploadOut)
async def retry_upload(upload_id: str) -> UploadOut:
    upload = await asyncio.to_thread(uploads.retry_upload, upload_id)
    if upload is None:
        raise HTTPException(status_code=404, detail="Upload not found.")
    if upload.status == "done":
        raise HTTPException(status_code=409, detail="This clip is already on YouTube.")
    upload_queue.notify()
    return UploadOut.of(upload)


def _page(ok: bool, message: str) -> HTMLResponse:
    """A self-contained completion page; it closes itself when opened as a popup."""
    title = "YouTube connected" if ok else "YouTube connection failed"
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
  // The opener polls /api/youtube/status, so closing immediately is harmless.
  setTimeout(function () {{ window.close() }}, 1200);
</script>
</body></html>"""
    return HTMLResponse(body, status_code=200 if ok else 400)
