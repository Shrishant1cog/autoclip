"""Turning a finished export into an Instagram post.

Two entry points:

``enqueue_export`` runs at the end of every successful export. It is a
no-op unless the owner turned automation on and has an account connected,
so exporting while the toggle is off never queues work.

``process_upload`` is called by the worker. It runs the publishing sequence
in the order Meta documents it, records every completed step on the row,
and stops at the first thing it cannot do.

**Duplicate prevention.** Instagram has no idempotency key — there is no
header AutoClip can send that says "this is the same post as last time".
The guarantee is therefore made locally, in the same way it is for
YouTube: the worker refuses to send a clip that is already published to
the same account. The refusal happens *before* the network call, so a
double enqueue costs nothing and posts nothing.
"""

from __future__ import annotations

import asyncio
import logging
from pathlib import Path
from typing import Any

from .. import config
from ..db import store
from ..db.models import InstagramUpload, new_id, utcnow
from . import accounts as accounts_store
from . import media as media_module
from . import oauth, publisher
from .errors import InstagramError

log = logging.getLogger(__name__)


class DuplicateUploadError(InstagramError):
    """This row would post a clip that is already on Instagram."""


class MediaRejected(InstagramError):
    """The file does not meet Instagram's documented requirements."""


def caption_for(clip: Any) -> str:
    """The caption AutoClip proposes for a clip.

    The clip's title, and its hook on a second line when the hook says
    something the title does not. The clip's **score** is not used: it is
    the model's own suggestion, not something the owner would want read
    out on their account.
    """
    title = str(getattr(clip, "title", "") or "").strip()
    hook = str(getattr(clip, "hook", "") or "").strip()
    if title and hook and hook.lower() != title.lower():
        return f"{title}\n\n{hook}"
    return title or hook


def enqueue(
    export_id: str,
    *,
    clip_id: str = "",
    account_row_id: str = "",
    caption: str = "",
    media_type: str = "REELS",
    is_ai_generated: bool = False,
) -> InstagramUpload:
    """Create an upload row for an export.

    A row for the same export and account already exists — the unique
    index makes a double enqueue a no-op rather than a second post.
    """
    export = store.get_export(export_id)
    if export is None:
        raise InstagramError(f"The export {export_id} no longer exists.")
    clip_id = clip_id or export.clip_id
    if not caption:
        clip = store.get_clip(clip_id)
        caption = caption_for(clip) if clip is not None else ""

    # The caption is checked here, not only at publish time, so a caption
    # that breaks a documented limit is refused while the owner can still
    # change it.
    problems = media_module.validate_caption(caption)
    if problems:
        raise MediaRejected(
            "The caption does not meet Instagram's limits: " + "; ".join(problems),
            hint="Nothing was sent to Instagram.",
        )

    return store.create_instagram_upload(
        InstagramUpload(
            id=new_id(),
            export_id=export_id,
            clip_id=clip_id,
            account_row_id=account_row_id,
            caption=caption,
            media_type=media_type,
            is_ai_generated=is_ai_generated,
        )
    )


def enqueue_export(
    export_id: str, settings: config.Settings | None = None
) -> InstagramUpload | None:
    """Queue an Instagram post for ``export_id`` when automation is on.

    Never raises: an upload problem must not fail a pipeline that has
    already produced a perfectly good file.
    """
    try:
        settings = settings or config.load()
        if not settings.instagram.auto_upload:
            return None
        if not oauth.is_connected(settings):
            return None

        export = store.get_export(export_id)
        if export is None:
            log.warning("Cannot enqueue an Instagram post: export %s is missing.", export_id)
            return None

        clip = store.get_clip(export.clip_id)
        if clip is not None and clip.status == "invalid":
            # A clip that failed validation is never published.
            log.warning("Not queueing an Instagram post for invalid clip %s.", clip.id)
            return None

        account = accounts_store.default_account()
        if account is None:
            return None

        row = enqueue(export_id, account_row_id=account.id)
        log.info("Queued Instagram upload %s for export %s.", row.id, export_id)
        return row
    except Exception:  # noqa: BLE001
        log.exception("Could not queue an Instagram upload for export %s.", export_id)
        return None


def duplicate_reason(upload: InstagramUpload) -> str:
    """Why this row would be a duplicate, or an empty string.

    The check is local and it is deliberately conservative: only a row
    that has actually **published** counts. A row that failed is not a
    duplicate — it is work that has not been done.
    """
    for other in store.list_all_instagram_uploads():
        if other.id == upload.id:
            continue
        if other.status != "done":
            continue
        if other.account_row_id != upload.account_row_id:
            continue
        if other.clip_id == upload.clip_id:
            return f"This clip is already on Instagram (post {other.media_id})."
        if other.export_id == upload.export_id:
            return f"This export is already on Instagram (post {other.media_id})."
    return ""


async def process_upload(upload: InstagramUpload, settings: config.Settings | None = None) -> str:
    """Publish one export to Instagram and return the media id.

    Raises :class:`InstagramError` for the worker to record against the
    row. The row is updated as the work progresses, so a transfer that
    stops can be continued rather than started again.
    """
    settings = settings or config.load()

    account = accounts_store.account_for_upload(upload.account_row_id)
    if account is None:
        raise InstagramError(
            "No Instagram account is connected. Connect one in Settings.",
            needs_reconnect=True,
        )
    if account.needs_reconnect:
        raise InstagramError(
            f"Instagram needs {account.username or 'this account'} to be connected again.",
            needs_reconnect=True,
        )

    export = store.get_export(upload.export_id)
    if export is None:
        raise InstagramError(f"The export {upload.export_id} no longer exists.")
    path = Path(export.path)

    # -- duplicates --------------------------------------------------------
    reason = duplicate_reason(upload)
    if reason:
        raise DuplicateUploadError(reason)

    # -- the file ----------------------------------------------------------
    if not path.is_file():
        raise InstagramError(f"The exported file is missing: {path}")

    report = media_module.validate_reel(path)
    if not report.ok:
        raise MediaRejected(
            "The file does not meet Instagram's requirements: " + "; ".join(report.problems),
            hint="Nothing was sent to Instagram.",
        )

    caption = upload.caption
    caption_problems = media_module.validate_caption(caption)
    if caption_problems:
        raise MediaRejected(
            "The caption does not meet Instagram's limits: " + "; ".join(caption_problems),
            hint="Nothing was sent to Instagram.",
        )

    setup = oauth.setup_for(account.login_type)
    if not setup.resumable_upload:
        # The resumable upload protocol is the only official way to send a
        # local file, and it does not exist on this setup. AutoClip does
        # not invent a host for the file and does not introduce cloud
        # storage: the file stays on the machine and the upload is
        # refused with the reason.
        raise MediaRejected(
            f"The {setup.label} setup has no official way to upload a local file.",
            hint=(
                "Meta documents the resumable upload protocol only for apps using "
                "Facebook Login for Business. AutoClip will not upload the file "
                "somewhere else to work around this. Switch to the Unified Login "
                "setup, or publish from a public URL yourself."
            ),
        )

    token = oauth.access_token(settings, account.id)
    size = path.stat().st_size

    # -- the container -----------------------------------------------------
    container_id = upload.container_id
    upload_uri = upload.upload_uri
    if not container_id:
        container = publisher.create_container(
            settings,
            account,
            token=token,
            media_type=upload.media_type,
            caption=caption,
            is_ai_generated=upload.is_ai_generated,
            resumable=True,
        )
        container_id = container.id
        upload_uri = container.uri
        store.update_instagram_upload(
            upload.id,
            container_id=container_id,
            upload_uri=upload_uri,
            total_bytes=size,
        )
        upload.container_id = container_id
        upload.upload_uri = upload_uri
    else:
        # A container from an earlier attempt. Ask Meta how much of the
        # file it has rather than trusting the stored figure.
        try:
            status = publisher.container_status(
                settings, account, token=token, container_id=container_id
            )
        except InstagramError:
            status = publisher.ContainerStatus()
        if status.expired:
            # A container lives 24 hours. After that a new one is needed,
            # and the file is sent again.
            log.info("The Instagram container %s expired; creating a new one.", container_id)
            container = publisher.create_container(
                settings,
                account,
                token=token,
                media_type=upload.media_type,
                caption=caption,
                is_ai_generated=upload.is_ai_generated,
                resumable=True,
            )
            container_id = container.id
            upload_uri = container.uri
            store.update_instagram_upload(
                upload.id,
                container_id=container_id,
                upload_uri=upload_uri,
                bytes_sent=0,
            )
            upload.container_id = container_id
            upload.upload_uri = upload_uri
        else:
            offset = max(status.bytes_transferred, upload.bytes_sent)
            if offset:
                log.info("Continuing the Instagram upload %s from byte %s.", upload.id, offset)
                store.update_instagram_upload(upload.id, bytes_sent=offset)
                upload.bytes_sent = offset

    # -- the transfer ------------------------------------------------------
    def progress(sent: int, total: int) -> None:
        store.update_instagram_upload(upload.id, bytes_sent=sent, total_bytes=total)

    sent = publisher.upload_file(
        upload_uri,
        path,
        token=token,
        offset=upload.bytes_sent,
        total_bytes=size,
        on_progress=progress,
    )
    store.update_instagram_upload(upload.id, bytes_sent=sent, total_bytes=size)

    # -- waiting for Meta --------------------------------------------------
    await _wait_for_container(settings, account, token=token, container_id=container_id)

    # -- the publish -------------------------------------------------------
    result = publisher.publish(settings, account, token=token, container_id=container_id)

    # -- the read-back -----------------------------------------------------
    published = publisher.read_back(settings, account, token=token, media_id=result.media_id)

    detail = ""
    if result.config_issue:
        detail = (
            f"Instagram published the post but reported {result.config_issue}, "
            "so part of the request was dropped."
        )
    store.update_instagram_upload(
        upload.id,
        status="done",
        media_id=result.media_id,
        permalink=published.permalink,
        published_at=utcnow(),
        publish_detail=detail,
        bytes_sent=sent,
        total_bytes=size,
        clear_error=True,
        next_attempt_at="",
    )
    log.info("Instagram upload %s published as %s.", upload.id, result.media_id)
    return result.media_id


async def _wait_for_container(
    settings: config.Settings,
    account: Any,
    *,
    token: str,
    container_id: str,
) -> None:
    """Wait for Meta to finish processing the container.

    Meta's guide says to query the status once per minute, for no more
    than five minutes. This follows that: it is the documented cadence,
    and it is a rolling window rather than an open-ended wait.
    """
    waited = 0.0
    while waited < publisher.POLL_MAX_S:
        status = publisher.container_status(
            settings, account, token=token, container_id=container_id
        )
        if status.ready:
            return
        if status.failed:
            raise InstagramError(
                "Instagram could not process the media.",
                hint=status.status_message or "The container is in an error state.",
                transient=True,
            )
        if status.expired:
            raise InstagramError(
                "The Instagram container expired before it was ready.",
                hint="A new container will be created and the file sent again.",
                transient=True,
            )
        await asyncio.sleep(publisher.POLL_INTERVAL_S)
        waited += publisher.POLL_INTERVAL_S

    raise InstagramError(
        "Instagram was still processing the media after five minutes.",
        hint="It will be checked again rather than published blind.",
        transient=True,
    )


def retry_upload(upload_id: str) -> InstagramUpload | None:
    """Put a failed upload back in the queue.

    The row keeps its own caption and its own account: a retry publishes
    the same thing to the same place, not something new.
    """
    upload = store.get_instagram_upload(upload_id)
    if upload is None:
        return None
    if upload.status == "done":
        return upload
    fields: dict[str, Any] = {
        "status": "pending",
        "error": None,
        "next_attempt_at": "",
        "attempts": 0,
    }
    if upload.status == "needs_reconciliation":
        fields["reconcile_status"] = "owner_retried"
        fields["reconcile_detail"] = (
            "The owner checked Instagram and asked for this post to be sent again."
        )
        fields["reconciled_at"] = utcnow()
        fields["container_id"] = ""
        fields["upload_uri"] = ""
        fields["bytes_sent"] = 0
    store.update_instagram_upload(upload_id, **fields)
    return store.get_instagram_upload(upload_id)
