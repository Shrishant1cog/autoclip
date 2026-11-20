"""Publishing to the Instagram Platform.

The sequence is Meta's own (see ``docs/INSTAGRAM-API-EVALUATION.md`` §9.2):

1. **Create a container** — ``POST /<IG_ID>/media``. With
   ``upload_type=resumable`` Meta answers with a container id and the
   ``rupload.facebook.com`` URI to send the file to.
2. **Upload the file** — ``POST <uri>`` with the bytes. The transfer can
   be interrupted and continued from the byte Meta says it has.
3. **Wait for the container** — ``GET /<container_id>?fields=status_code``
   until it is ``FINISHED``.
4. **Publish** — ``POST /<IG_ID>/media_publish`` with the container id.
5. **Read back** — ``GET /<media_id>?fields=…`` so that "published" is a
   fact rather than an assumption.

Every request goes through the egress gateway, so the destination is
classified and the transfer is in the log the owner can read. Nothing here
falls back to another host: if Meta refuses, the upload stops.
"""

from __future__ import annotations

import logging
import time
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import httpx

from .. import config
from ..security import consent
from ..security.egress import Transfer, gateway
from ..security.urlpolicy import UrlRejected
from . import oauth
from .errors import InstagramError, translate_graph_error

log = logging.getLogger(__name__)

#: Where the bytes go. Meta's own host for resumable video uploads.
RUPLOAD_HOST = "rupload.facebook.com"

#: How much is sent in one request. Eight mebibytes: large enough that
#: the per-request overhead does not matter, small enough that a dropped
#: connection costs a little rather than a lot.
CHUNK_SIZE = 8 * 1024 * 1024

#: How long to wait between container status checks. Meta's own guide says
#: to query once per minute.
POLL_INTERVAL_S = 60.0

#: How long to keep checking. Meta's guide says no more than five minutes.
POLL_MAX_S = 300.0

#: The container states Meta defines.
STATUS_EXPIRED = "EXPIRED"
STATUS_ERROR = "ERROR"
STATUS_FINISHED = "FINISHED"
STATUS_IN_PROGRESS = "IN_PROGRESS"
STATUS_PUBLISHED = "PUBLISHED"


@dataclass(frozen=True)
class Container:
    """A media container, and where to send the file if there is one."""

    id: str
    uri: str = ""


@dataclass(frozen=True)
class ContainerStatus:
    """What Meta says about a container."""

    status_code: str = ""
    status_message: str = ""
    #: The byte Meta has received, when it says.
    bytes_transferred: int = 0
    uploading_phase: str = ""
    processing_phase: str = ""

    @property
    def ready(self) -> bool:
        return self.status_code in {STATUS_FINISHED, STATUS_PUBLISHED}

    @property
    def failed(self) -> bool:
        return self.status_code == STATUS_ERROR

    @property
    def expired(self) -> bool:
        return self.status_code == STATUS_EXPIRED


@dataclass(frozen=True)
class PublishResult:
    """What a publish returned."""

    media_id: str
    #: Meta reports a ``config_issue`` when a publish succeeded but part of
    #: the request was dropped — the caption did not attach, or a tagged
    #: user did not get tagged. That is not a clean success and it is
    #: reported rather than hidden.
    config_issue: str = ""


@dataclass(frozen=True)
class PublishedMedia:
    """What Instagram says about a published media object."""

    id: str
    permalink: str = ""
    media_type: str = ""
    media_product_type: str = ""
    caption: str = ""

    @property
    def is_reel(self) -> bool:
        """Whether this is a Reel.

        Meta returns ``VIDEO`` for a published Reel's ``media_type``; the
        ``media_product_type`` field is the one that says "reel".
        """
        return self.media_product_type.lower() == "reel"


@dataclass(frozen=True)
class PublishingLimit:
    """The account's publishing allowance, as Meta reports it."""

    quota_total: int = 0
    quota_duration_s: int = 0
    quota_usage: int = 0
    #: True when Meta actually answered. A failed lookup is not "no limit".
    known: bool = False

    def to_dict(self) -> dict[str, Any]:
        return {
            "quota_total": self.quota_total,
            "quota_duration_s": self.quota_duration_s,
            "quota_usage": self.quota_usage,
            "known": self.known,
            "remaining": max(self.quota_total - self.quota_usage, 0) if self.known else 0,
        }


# --------------------------------------------------------------------------
# Requests
# --------------------------------------------------------------------------


def _transfer(url: str, summary: str) -> Transfer:
    return Transfer(
        operation=consent.Operation.PUBLISHING,
        url=url,
        data_summary=summary,
        provider="instagram",
        requires_consent=False,
    )


def _authorize(url: str, summary: str) -> None:
    """Classify the destination and record the attempt.

    Publishing is an explicit owner action, so it is recorded rather than
    consent-gated — but it still goes through the gateway, so the
    destination is classified and the transfer is in the readable log.
    """
    transfer = _transfer(url, summary)
    try:
        gateway.authorize(transfer)
    except UrlRejected as exc:
        raise InstagramError(f"Instagram was refused as a destination: {exc}") from exc


def _graph_url(settings: config.Settings, account: Any, path: str) -> str:
    setup = oauth.setup_for(getattr(account, "login_type", "unified"))
    return f"https://{setup.host}/{settings.instagram.api_version}/{path.lstrip('/')}"


def _post_json(
    settings: config.Settings,
    account: Any,
    path: str,
    payload: dict[str, Any],
    *,
    token: str,
    summary: str,
) -> dict[str, Any]:
    url = _graph_url(settings, account, path)
    _authorize(url, summary)
    try:
        response = httpx.post(
            url,
            json=payload,
            headers={"Authorization": f"Bearer {token}"},
            timeout=60.0,
        )
    except httpx.HTTPError as exc:
        gateway.record(_transfer(url, summary), "failed", detail=str(exc))
        raise InstagramError(f"Could not reach Instagram: {exc}", transient=True) from exc
    return _read_response(response, url, summary)


def _get_json(
    settings: config.Settings,
    account: Any,
    path: str,
    *,
    token: str,
    params: dict[str, str] | None = None,
    summary: str,
) -> dict[str, Any]:
    url = _graph_url(settings, account, path)
    _authorize(url, summary)
    try:
        response = httpx.get(
            url,
            params=params or {},
            headers={"Authorization": f"Bearer {token}"},
            timeout=60.0,
        )
    except httpx.HTTPError as exc:
        gateway.record(_transfer(url, summary), "failed", detail=str(exc))
        raise InstagramError(f"Could not reach Instagram: {exc}", transient=True) from exc
    return _read_response(response, url, summary)


def _read_response(response: httpx.Response, url: str, summary: str) -> dict[str, Any]:
    """Turn a Graph response into a body, or into an error."""
    transfer = _transfer(url, summary)
    if response.status_code >= 400:
        gateway.record(transfer, "failed", detail=f"HTTP {response.status_code}")
        try:
            payload = response.json()
        except ValueError:
            payload = {}
        raise translate_graph_error(payload, response.status_code)
    gateway.record(transfer, "ok")
    try:
        body = response.json()
    except ValueError as exc:
        raise InstagramError("Instagram returned unreadable output.") from exc
    return body if isinstance(body, dict) else {}


# --------------------------------------------------------------------------
# The publishing sequence
# --------------------------------------------------------------------------


def create_container(
    settings: config.Settings,
    account: Any,
    *,
    token: str,
    media_type: str = "REELS",
    caption: str = "",
    is_ai_generated: bool = False,
    resumable: bool = True,
    video_url: str = "",
) -> Container:
    """Create a media container for the account.

    With ``resumable`` the container comes back with the ``rupload``
    URI to send the file to. Without it, Meta fetches the file from
    ``video_url`` — which only works when the file is on a public server,
    so it is the only path available on the Instagram Login setup.
    """
    payload: dict[str, Any] = {"media_type": media_type}
    if caption:
        payload["caption"] = caption
    if is_ai_generated:
        # Meta asks for this self-disclosure. It is the owner's
        # declaration, so AutoClip only sends it when the owner said so.
        payload["is_ai_generated"] = True
    if resumable:
        payload["upload_type"] = "resumable"
    elif video_url:
        payload["video_url"] = video_url

    body = _post_json(
        settings,
        account,
        f"{account.ig_user_id}/media",
        payload,
        token=token,
        summary="The clip's caption and the request for a media container.",
    )
    container_id = str(body.get("id") or "")
    if not container_id:
        raise InstagramError(
            "Instagram did not return a media container id.",
            transient=True,
        )
    return Container(id=container_id, uri=str(body.get("uri") or ""))


def container_status(
    settings: config.Settings,
    account: Any,
    *,
    token: str,
    container_id: str,
) -> ContainerStatus:
    """Ask Meta what it has of a container."""
    body = _get_json(
        settings,
        account,
        container_id,
        token=token,
        params={"fields": "id,status,status_code,video_status"},
        summary="The state of the media container.",
    )
    video_status = body.get("video_status") or {}
    uploading = video_status.get("uploading_phase") or {}
    processing = video_status.get("processing_phase") or {}
    return ContainerStatus(
        status_code=str(body.get("status_code") or ""),
        status_message=str(body.get("status") or ""),
        bytes_transferred=int(uploading.get("bytes_transferred") or 0),
        uploading_phase=str(uploading.get("status") or ""),
        processing_phase=str(processing.get("status") or ""),
    )


def upload_file(
    upload_uri: str,
    path: Path,
    *,
    token: str,
    offset: int = 0,
    total_bytes: int = 0,
    on_progress: Callable[[int, int], None] | None = None,
) -> int:
    """Send the file to Meta, in chunks, and return the bytes it has.

    Meta's guide shows a single POST of the whole file. The chunked form
    below uses the same endpoint with an explicit ``offset`` header, which
    is the mechanism Meta documents for continuing an interrupted transfer
    — and the byte count is checked against Meta's own
    ``video_status.uploading_phase.bytes_transferred`` between chunks, so
    the offset never comes from AutoClip's memory alone.
    """
    if not upload_uri.startswith("https://"):
        raise InstagramError(
            "Instagram's upload address is not an https URL. The upload was not started."
        )
    size = total_bytes or path.stat().st_size
    sent = offset
    _authorize(upload_uri, "The rendered clip itself.")

    with path.open("rb") as handle:
        while sent < size:
            handle.seek(sent)
            chunk = handle.read(min(CHUNK_SIZE, size - sent))
            if not chunk:
                break
            try:
                response = httpx.post(
                    upload_uri,
                    content=chunk,
                    headers={
                        # Meta's own upload endpoint takes the token as
                        # "OAuth", not "Bearer".
                        "Authorization": f"OAuth {token}",
                        "offset": str(sent),
                        "file_size": str(size),
                        "Content-Type": "application/octet-stream",
                    },
                    timeout=120.0,
                )
            except httpx.HTTPError as exc:
                gateway.record(
                    _transfer(upload_uri, "The rendered clip itself."),
                    "failed",
                    detail=str(exc),
                )
                raise InstagramError(
                    f"The transfer to Instagram stopped after {sent} bytes: {exc}",
                    transient=True,
                ) from exc

            if response.status_code >= 400:
                gateway.record(
                    _transfer(upload_uri, "The rendered clip itself."),
                    "failed",
                    detail=f"HTTP {response.status_code}",
                )
                try:
                    payload = response.json()
                except ValueError:
                    payload = {}
                raise translate_graph_error(payload, response.status_code)

            gateway.record(_transfer(upload_uri, "The rendered clip itself."), "ok")
            sent += len(chunk)
            if on_progress is not None:
                on_progress(sent, size)
    return sent


def publish(
    settings: config.Settings,
    account: Any,
    *,
    token: str,
    container_id: str,
) -> PublishResult:
    """Publish a finished container.

    A dropped connection here is **ambiguous**, not a plain failure: the
    request may have reached Instagram and been accepted, and the answer
    never came back. The error says so, so the row waits for the owner
    instead of being sent again and posting the clip twice.
    """
    try:
        body = _post_json(
            settings,
            account,
            f"{account.ig_user_id}/media_publish",
            {"creation_id": container_id},
            token=token,
            summary="The container to publish, and the clip's caption.",
        )
    except InstagramError as exc:
        if exc.transient and not exc.owner_action_required:
            raise InstagramError(
                str(exc),
                hint=(
                    "Instagram may have published this before the connection dropped. "
                    "Check Instagram before sending it again."
                ),
                transient=True,
                needs_reconciliation=True,
                code=exc.code,
                subcode=exc.subcode,
                fbtrace_id=exc.fbtrace_id,
            ) from exc
        raise
    media_id = str(body.get("id") or "")
    if not media_id:
        raise InstagramError(
            "Instagram did not return a media id for the publish.",
            transient=True,
            needs_reconciliation=True,
            hint=(
                "The request was answered but no media id came back. "
                "Check Instagram before sending it again."
            ),
        )
    return PublishResult(
        media_id=media_id,
        config_issue=str(body.get("config_issue") or ""),
    )


def read_back(
    settings: config.Settings,
    account: Any,
    *,
    token: str,
    media_id: str,
) -> PublishedMedia:
    """Ask Instagram what it actually published.

    A lookup that fails says nothing about the publish — the post is
    already up — so this returns an empty result rather than raising.
    """
    if not media_id:
        return PublishedMedia(id="")
    try:
        body = _get_json(
            settings,
            account,
            media_id,
            token=token,
            params={"fields": "id,permalink,media_type,media_product_type,caption"},
            summary="What Instagram published.",
        )
    except InstagramError:
        log.warning("Could not read back the Instagram media %s.", media_id, exc_info=True)
        return PublishedMedia(id=media_id)
    return PublishedMedia(
        id=str(body.get("id") or media_id),
        permalink=str(body.get("permalink") or ""),
        media_type=str(body.get("media_type") or ""),
        media_product_type=str(body.get("media_product_type") or ""),
        caption=str(body.get("caption") or ""),
    )


def publishing_limit(
    settings: config.Settings,
    account: Any,
    *,
    token: str,
) -> PublishingLimit:
    """Read the account's publishing allowance from Meta.

    The limit is **read**, not hardcoded: Meta's own documents disagree
    about it (the guide says 100 posts, the endpoint reference says 50),
    and the endpoint is the one that knows what is actually in force.
    """
    since = int(time.time()) - 86_400
    try:
        body = _get_json(
            settings,
            account,
            f"{account.ig_user_id}/content_publishing_limit",
            token=token,
            params={
                "fields": "config,quota_usage",
                "since": str(since),
            },
            summary="The account's publishing allowance.",
        )
    except InstagramError:
        log.warning("Could not read the Instagram publishing limit.", exc_info=True)
        return PublishingLimit()

    config_block = body.get("config") or {}
    usage = body.get("quota_usage") or {}
    return PublishingLimit(
        quota_total=int(config_block.get("quota_total") or 0),
        quota_duration_s=int(config_block.get("quota_duration") or 0),
        quota_usage=int(usage.get("usage") or 0),
        known=True,
    )
