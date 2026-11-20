"""The background worker that publishes to Instagram.

**This is a separate queue from the YouTube one, and that is the point.**
The spec requires platform publishing to be independent: a clip that
Instagram refuses must not stop a YouTube upload, and a YouTube quota
that runs out must not stop an Instagram post. That independence is
structural rather than a promise:

* the rows live in their own table (``instagram_uploads``),
* the worker reads and writes only that table,
* and a failure here is caught, recorded against the Instagram row, and
  never propagates into the YouTube queue.

The queue is durable because it lives in SQLite. A crash mid-publish
leaves the row as ``uploading``, and startup turns it back into pending
work — and the container and the byte count are still on the row, so the
transfer continues rather than starting again.
"""

from __future__ import annotations

import asyncio
import contextlib
import logging
from typing import Any

from .. import config
from ..db import store
from ..db.models import UploadStatus
from ..youtube.backoff import next_attempt_at, should_retry
from . import uploads
from .errors import OwnerActionRequired

log = logging.getLogger(__name__)

POLL_INTERVAL_S = 5.0


def _message(error: BaseException) -> str:
    """Turn an exception into the one line shown in the UI."""
    text = str(error).strip() or error.__class__.__name__
    return text[:2000]


class InstagramUploadQueue:
    """Runs queued Instagram posts one at a time."""

    def __init__(self) -> None:
        self._task: asyncio.Task | None = None
        self._wakeup: asyncio.Event | None = None
        self._stopping = False
        self._current: str | None = None
        #: Posts recovered from an interrupted run.
        self.resumed_upload_ids: list[str] = []

    # -- lifecycle ---------------------------------------------------------

    async def start(self) -> None:
        self.resumed_upload_ids = store.requeue_interrupted_instagram_uploads()
        self._stopping = False
        self._wakeup = asyncio.Event()
        self._task = asyncio.create_task(self._worker(), name="autoclip-instagram-queue")
        self.notify()

    async def stop(self) -> None:
        self._stopping = True
        self.notify()
        if self._task is not None:
            self._task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await self._task
            self._task = None
        self._wakeup = None

    def notify(self) -> None:
        """Wake the worker after enqueuing. A no-op without a worker."""
        if self._wakeup is not None:
            self._wakeup.set()

    @property
    def current_upload_id(self) -> str | None:
        return self._current

    # -- worker ------------------------------------------------------------

    async def _worker(self) -> None:
        wakeup = self._wakeup
        assert wakeup is not None

        while not self._stopping:
            upload = await asyncio.to_thread(store.next_pending_instagram_upload)
            if upload is None:
                wakeup.clear()
                with contextlib.suppress(asyncio.TimeoutError):
                    await asyncio.wait_for(wakeup.wait(), timeout=POLL_INTERVAL_S)
                continue

            await self._run(upload.id)

    async def _run(self, upload_id: str) -> None:
        self._current = upload_id
        settings = config.load()
        upload = store.get_instagram_upload(upload_id)
        if upload is None:
            self._current = None
            return
        attempts = upload.attempts + 1
        store.update_instagram_upload(
            upload_id, status="uploading", clear_error=True, attempts=attempts
        )
        upload.status = "uploading"
        try:
            media_id = await uploads.process_upload(upload, settings)
        except uploads.DuplicateUploadError as exc:
            log.info("Instagram upload %s skipped: %s", upload_id, exc)
            message = _message(exc)
            store.update_instagram_upload(upload_id, status="skipped", error=message)
            _notify(upload, "skipped", message)
        except Exception as exc:  # one bad post must not stop the queue
            message = _message(exc)
            transient = bool(getattr(exc, "transient", False))
            retry_at = str(getattr(exc, "retry_at", "") or "")
            # An unsettled publish is checked *before* the transient
            # branch. The request may have reached Instagram, so sending
            # it again could post the clip twice — and a backoff would
            # do exactly that.
            unsettled = bool(getattr(exc, "needs_reconciliation", False))
            if unsettled:
                unsettled_status: UploadStatus = "needs_reconciliation"
                log.warning("Instagram upload %s %s: %s", upload_id, unsettled_status, exc)
                store.update_instagram_upload(upload_id, status=unsettled_status, error=message)
                _notify(
                    upload,
                    "failed",
                    message,
                    owner_action_required=isinstance(exc, OwnerActionRequired),
                )
            elif transient and (retry_at or should_retry(attempts)):
                # A dropped connection is worth another try, but not
                # straight away. A known reset time beats the backoff's
                # guess: the publishing limit comes back when it comes back.
                due = retry_at or next_attempt_at(attempts)
                fields: dict[str, Any] = {
                    "status": "pending",
                    "error": message,
                    "next_attempt_at": due,
                }
                if retry_at:
                    # The file never left the machine: the publishing limit
                    # was reached before the call. That is not an attempt at
                    # publishing, and counting it would use up the row's own
                    # retry allowance for a limit that has nothing to do
                    # with it.
                    fields["attempts"] = max(attempts - 1, 0)
                store.update_instagram_upload(upload_id, **fields)
                log.info(
                    "Instagram upload %s stopped (%s); trying again at %s.",
                    upload_id,
                    message,
                    due,
                )
            else:
                # A publish that cannot be settled is not a failure and not
                # a retry: it waits for the owner, because sending it again
                # could post the clip twice.
                status: UploadStatus = "failed"
                log.warning("Instagram upload %s %s: %s", upload_id, status, exc)
                store.update_instagram_upload(upload_id, status=status, error=message)
                _notify(
                    upload,
                    "failed",
                    message,
                    owner_action_required=isinstance(exc, OwnerActionRequired),
                )
        else:
            store.update_instagram_upload(
                upload_id,
                status="done",
                media_id=media_id,
                clear_error=True,
                next_attempt_at="",
            )
            log.info("Instagram upload %s finished as %s.", upload_id, media_id)
            _notify(upload, "done", media_id)
        finally:
            self._current = None


def _account_title(upload: Any) -> str:
    """The account the post goes to, when the row names one."""
    from . import accounts as accounts_store

    if not upload.account_row_id:
        return ""
    try:
        account = accounts_store.get_account(upload.account_row_id)
        return str(account.username or account.name) if account else ""
    except Exception:  # noqa: BLE001
        return ""


def _upload_title(upload: Any) -> str:
    """The name to show for a post."""
    fresh = store.get_instagram_upload(upload.id)
    if fresh is not None and fresh.caption:
        return fresh.caption.splitlines()[0]
    clip = store.get_clip(upload.clip_id)
    if clip is not None and clip.title:
        return clip.title
    return "Untitled clip"


def _notify(upload: Any, outcome: str, detail: str = "", **extra: Any) -> None:
    """Record an outcome in the notification centre. Never raises."""
    try:
        from ..notifications import events

        title = _upload_title(upload)
        if outcome == "done":
            events.instagram_upload_done(upload.id, title, detail, _account_title(upload))
        elif outcome == "skipped":
            events.instagram_upload_skipped(upload.id, title, detail)
        else:
            events.instagram_upload_failed(upload.id, title, detail, **extra)
    except Exception:  # noqa: BLE001
        log.debug("Could not record the Instagram notification.", exc_info=True)


#: Module-level singleton, matching the job queue's shape.
instagram_upload_queue = InstagramUploadQueue()


def status() -> dict[str, object]:
    """A small snapshot for the settings page."""
    settings = config.load()
    from . import oauth

    return {
        "connected": oauth.is_connected(settings),
        "configured": oauth.is_configured(settings),
        "auto_upload": settings.instagram.auto_upload,
        "current_upload_id": instagram_upload_queue.current_upload_id,
    }
