"""Background worker that delivers queued YouTube uploads.

Uploads run one at a time, like jobs: a single home connection cannot usefully
push two 80 MB files at once, and serialising keeps the API quota bookkeeping
simple. The queue is durable because it lives in SQLite — a crash mid-upload
leaves the row as ``uploading``, and startup turns it back into pending work.
"""

from __future__ import annotations

import asyncio
import contextlib
import logging

from .. import config
from ..db import store
from . import backoff, oauth, uploads

log = logging.getLogger(__name__)

POLL_INTERVAL_S = 5.0


def _message(error: BaseException) -> str:
    """Turn an exception into the one line shown in the UI."""
    text = str(error).strip() or error.__class__.__name__
    return text[:2000]


class UploadQueue:
    """Runs queued uploads one at a time."""

    def __init__(self) -> None:
        self._task: asyncio.Task | None = None
        self._wakeup: asyncio.Event | None = None
        self._stopping = False
        self._current: str | None = None
        #: Uploads recovered from an interrupted run (Phase 17).
        self.resumed_upload_ids: list[str] = []

    # -- lifecycle ---------------------------------------------------------

    async def start(self) -> None:
        self.resumed_upload_ids = store.requeue_interrupted_uploads()
        self._stopping = False
        self._wakeup = asyncio.Event()
        self._task = asyncio.create_task(self._worker(), name="autoclip-upload-queue")
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
            upload = await asyncio.to_thread(store.next_pending_upload)
            if upload is None:
                wakeup.clear()
                with contextlib.suppress(asyncio.TimeoutError):
                    await asyncio.wait_for(wakeup.wait(), timeout=POLL_INTERVAL_S)
                continue

            await self._run(upload.id)

    async def _run(self, upload_id: str) -> None:
        self._current = upload_id
        settings = config.load()
        upload = store.get_upload(upload_id)
        if upload is None:
            self._current = None
            return
        attempts = upload.attempts + 1
        store.update_upload(upload_id, status="uploading", clear_error=True, attempts=attempts)
        upload.status = "uploading"
        try:
            video_id = await uploads.process_upload(upload, settings)
        except uploads.DuplicateUploadError as exc:
            log.info("YouTube upload %s skipped: %s", upload_id, exc)
            message = _message(exc)
            store.update_upload(upload_id, status="skipped", error=message)
            _notify(upload, "skipped", message)
        except Exception as exc:  # one bad upload must not stop the queue
            message = _message(exc)
            transient = bool(getattr(exc, "transient", False))
            if transient and backoff.should_retry(attempts):
                # A dropped connection is worth another try, but not
                # straight away: the delay grows with each attempt so a
                # failing upload backs off instead of hammering the API.
                due = backoff.next_attempt_at(attempts)
                store.update_upload(
                    upload_id,
                    status="pending",
                    error=message,
                    next_attempt_at=due,
                )
                log.info(
                    "YouTube upload %s stopped (%s); trying again at %s.",
                    upload_id,
                    message,
                    due,
                )
            else:
                log.warning("YouTube upload %s failed: %s", upload_id, exc)
                store.update_upload(upload_id, status="failed", error=message)
                _notify(upload, "failed", message)
        else:
            store.update_upload(
                upload_id,
                status="done",
                video_id=video_id,
                clear_error=True,
                session_url="",
                bytes_sent=0,
                next_attempt_at="",
            )
            log.info("YouTube upload %s finished as %s.", upload_id, video_id)
            _notify(upload, "done", video_id)
        finally:
            self._current = None


def _channel_title(upload) -> str:
    """The destination channel's title, when the upload names one."""
    if not upload.channel_row_id:
        return ""
    try:
        from . import accounts as accounts_store

        channel = accounts_store.get_channel(upload.channel_row_id)
        return str(channel.get("title", "")) if channel else ""
    except Exception:  # noqa: BLE001
        return ""


def _notify(upload, outcome: str, detail: str = "") -> None:
    """Record an upload outcome in the notification centre. Never raises."""
    try:
        from ..notifications import events

        title = _upload_title(upload)
        if outcome == "done":
            events.upload_done(
                upload.id, title, detail, _channel_title(upload), _privacy_note(upload)
            )
        elif outcome == "skipped":
            events.upload_skipped(upload.id, title, detail)
        else:
            events.upload_failed(upload.id, title, detail)
    except Exception:  # noqa: BLE001
        log.debug("Could not record the upload notification.", exc_info=True)


def _privacy_note(upload) -> str:
    """What YouTube actually did, when it is not what was asked for.

    An un-audited Google Cloud project cannot publish a public video, so
    YouTube quietly forces it private. Saying "Published" in that case
    would be a lie: nobody can see the video.
    """
    fresh = store.get_upload(upload.id)
    if fresh is None:
        return ""
    actual = fresh.actual_privacy
    asked = fresh.requested_privacy or fresh.privacy
    if not actual or not asked or actual == asked:
        return ""
    if actual == "private":
        return "It was uploaded, but YouTube made it private."
    return f"It was uploaded, but YouTube made it {actual}."


def _upload_title(upload) -> str:
    """The name to show for an upload.

    The generated title is written to the row during metadata creation, after
    the snapshot this worker holds was read. A skipped upload never reaches
    metadata generation at all, so the clip's own title is the fallback.
    """
    fresh = store.get_upload(upload.id)
    if fresh is not None and fresh.title:
        return fresh.title
    if upload.title:
        return upload.title
    clip = store.get_clip(upload.clip_id)
    if clip is not None and clip.title:
        return clip.title
    return "Untitled clip"


#: Module-level singleton, matching the job queue's shape.
upload_queue = UploadQueue()


def status() -> dict[str, object]:
    settings = config.load()
    return {
        "connected": oauth.is_connected(settings),
        "configured": oauth.is_configured(settings),
        "auto_upload": settings.youtube.auto_upload,
        "channel_title": settings.youtube.channel_title,
        "current_upload_id": upload_queue.current_upload_id,
    }
