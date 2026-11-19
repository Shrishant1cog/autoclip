"""Batch runner — drives batch items through the existing job queue.

The runner is event-driven, not polling: each finished job publishes a
progress event; the runner reacts, records the item's outcome, and enqueues
the next pending item. Batch pause/cancel act between items — the currently
running job always completes (it belongs to the job queue's semantics).
"""

from __future__ import annotations

import asyncio
import contextlib
import logging

from .. import config
from ..db import store
from ..db.models import Job, new_id
from . import batches
from .queue import queue

log = logging.getLogger(__name__)


class BatchRunner:
    """Watches job completions and advances batches item by item."""

    def __init__(self) -> None:
        self._active: dict[str, str] = {}  # batch_id -> item_id being processed
        self._wakeup: asyncio.Event | None = None
        self._task: asyncio.Task | None = None
        self._stopping = False
        #: Batch items recovered from an interrupted run (Phase 17).
        self.resumed_item_ids: list[str] = []

    def start(self) -> None:
        self._stopping = False
        self._wakeup = asyncio.Event()
        self.resumed_item_ids = batches.recover_interrupted()
        self._task = asyncio.create_task(self._loop(), name="autoclip-batch-runner")

    async def stop(self) -> None:
        self._stopping = True
        if self._wakeup is not None:
            self._wakeup.set()
        if self._task is not None:
            self._task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await self._task
            self._task = None
        self._wakeup = None

    # -- public control ------------------------------------------------------

    def launch(self, batch_id: str) -> None:
        """Kick (or resume) a batch. Safe to call repeatedly."""
        if self._wakeup is None:
            return
        batch = batches.get_batch(batch_id)
        if batch is None or batch["status"] in ("done", "cancelled"):
            return
        batches.set_batch_status(batch_id, "running")
        self._wakeup.set()

    def pause(self, batch_id: str) -> None:
        """Pause after the current item's job finishes."""
        batch = batches.get_batch(batch_id)
        if batch is not None and batch["status"] == "running":
            batches.set_batch_status(batch_id, "paused")

    def cancel(self, batch_id: str) -> None:
        """Cancel pending items; the running job (if any) is left to finish."""
        batch = batches.get_batch(batch_id)
        if batch is None:
            return
        for item in batches.list_items(batch_id):
            if item["status"] in ("pending", "processing"):
                batches.update_item(item["id"], status="cancelled")
        batches.set_batch_status(batch_id, "cancelled")
        self._active.pop(batch_id, None)

    def retry_failed(self, batch_id: str) -> int:
        """Requeue failed items as pending. Returns how many were requeued."""
        count = 0
        for item in batches.list_items(batch_id):
            if item["status"] == "failed":
                batches.update_item(item["id"], status="pending", error=None)
                count += 1
        if count:
            self.launch(batch_id)
        return count

    # -- event loop ------------------------------------------------------------

    async def _loop(self) -> None:
        wakeup = self._wakeup
        assert wakeup is not None
        while not self._stopping:
            wakeup.clear()
            progressed = await asyncio.to_thread(self._advance_all)
            if not progressed:
                with contextlib.suppress(TimeoutError):
                    await asyncio.wait_for(wakeup.wait(), timeout=30.0)

    def _advance_all(self) -> bool:
        """Advance every running batch by one item. True if any work was done."""
        did_work = False
        for batch in batches.list_batches(limit=500):
            if batch["status"] != "running":
                continue
            if self._advance_one(batch["id"]):
                did_work = True
        return did_work

    def _advance_one(self, batch_id: str) -> bool:
        # An item already processing for this batch: check whether its job ended.
        active_item_id = self._active.get(batch_id)
        if active_item_id is not None:
            item = batches.get_item(active_item_id)
            if item is None:
                self._active.pop(batch_id, None)
            elif item["job_id"] is not None:
                job = store.get_job(item["job_id"])
                if job is not None and job.status in ("done", "failed", "cancelled"):
                    self._finish_item(batch_id, item, job.status)
                    self._active.pop(batch_id, None)
                else:
                    return True  # still running; keep the batch marked active
            else:
                self._active.pop(batch_id, None)

        item = batches.next_pending_item(batch_id)
        if item is None:
            self._complete_batch(batch_id)
            return False

        batches.update_item(item["id"], status="processing")
        self._active[batch_id] = item["id"]
        try:
            job_id = self._enqueue_job(batch_id, item)
        except Exception as exc:  # noqa: BLE001 - one bad source must not stall the batch
            log.warning("Batch %s item %s could not enqueue: %s", batch_id, item["id"], exc)
            batches.update_item(item["id"], status="failed", error=str(exc)[:300])
            self._active.pop(batch_id, None)
            return True

        if job_id is None:
            batches.update_item(item["id"], status="failed", error="Job creation failed.")
            self._active.pop(batch_id, None)
        else:
            batches.update_item(item["id"], job_id=job_id)
        return True

    def _finish_item(self, batch_id: str, item: dict, job_status: str) -> None:
        if job_status == "done":
            batches.update_item(item["id"], status="done", error=None)
        elif job_status == "cancelled":
            batches.update_item(item["id"], status="cancelled", error="Job was cancelled.")
        else:
            job = store.get_job(item["job_id"] or "")
            error = (job.error if job else "") or "Job failed."
            batches.update_item(item["id"], status="failed", error=error[:300])

    def _complete_batch(self, batch_id: str) -> None:
        progress = batches.batch_progress(batch_id)
        if progress["failed"] and not progress["pending"] and not progress["processing"]:
            batches.set_batch_status(batch_id, "failed")
        else:
            batches.set_batch_status(batch_id, "done")
        log.info("Batch %s complete: %s", batch_id, progress)
        self._notify_complete(batch_id, progress)

    def _notify_complete(self, batch_id: str, progress: dict[str, int]) -> None:
        """Tell the user the batch finished. Never raises."""
        try:
            from ..notifications import events

            batch = batches.get_batch(batch_id) or {}
            name = batch.get("name") or "Untitled batch"
            events.batch_done(
                batch_id,
                name,
                progress.get("done", 0),
                progress.get("failed", 0),
            )
        except Exception:  # noqa: BLE001
            log.debug("Could not record the batch notification.", exc_info=True)

    def _enqueue_job(self, batch_id: str, item: dict) -> str | None:
        source = store.get_source(item["source_id"])
        if source is None:
            return None
        batch = batches.get_batch(batch_id)
        settings = config.load()
        overrides = (batch or {}).get("settings") or {}
        if overrides:
            merged = settings.model_copy(deep=True)
            for key, value in overrides.items():
                if hasattr(merged.clips, key):
                    setattr(merged.clips, key, value)
                elif hasattr(merged, key):
                    setattr(merged, key, value)
            settings = merged
        job = Job(
            id=new_id(),
            source_id=source.id,
            provider=settings.active_provider,
            settings=settings.model_dump(mode="json"),
        )
        store.create_job(job)
        queue.notify()
        return job.id


#: Module-level singleton, matching the job/upload queue shape.
batch_runner = BatchRunner()
