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
from . import oauth, uploads

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

    # -- lifecycle ---------------------------------------------------------

    async def start(self) -> None:
        store.requeue_interrupted_uploads()
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
        store.update_upload(upload_id, status="uploading", clear_error=True)
        upload.status = "uploading"
        try:
            video_id = await uploads.process_upload(upload, settings)
        except uploads.DuplicateUploadError as exc:
            log.info("YouTube upload %s skipped: %s", upload_id, exc)
            store.update_upload(upload_id, status="skipped", error=_message(exc))
        except Exception as exc:  # one bad upload must not stop the queue
            log.warning("YouTube upload %s failed: %s", upload_id, exc)
            store.update_upload(upload_id, status="failed", error=_message(exc))
        else:
            store.update_upload(upload_id, status="done", video_id=video_id, clear_error=True)
            log.info("YouTube upload %s finished as %s.", upload_id, video_id)
        finally:
            self._current = None


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
