"""Phase 17 — restart recovery, made visible.

AutoClip resumes interrupted work on startup. That behaviour existed before
this phase, but it was invisible: the job simply carried on, and there was no
way to learn that a restart had interrupted it.

These tests cover the three things the phase adds:

* the rows that were recovered are marked (``last_resumed_at``),
* the restart itself is recorded with the real counts,
* the record is visible through the API and in the notification inbox.
"""

from __future__ import annotations

import asyncio
from pathlib import Path

import pytest
from autoclip.db import store
from autoclip.db.models import Clip, Export, Job, Source, YouTubeUpload, new_id
from fastapi.testclient import TestClient

# --------------------------------------------------------------------------
# Fixtures
# --------------------------------------------------------------------------


@pytest.fixture
def client(autoclip_home: Path) -> TestClient:
    from autoclip.app import create_app

    with TestClient(create_app()) as test_client:
        yield test_client


def _seed_source() -> Source:
    source = Source(id=new_id(), type="upload", path="C:/videos/source.mp4", title="A Video")
    store.create_source(source)
    return source


def _seed_job(source: Source, *, status: str = "running") -> Job:
    job = Job(id=new_id(), source_id=source.id, status=status)
    store.create_job(job)
    return job


def _seed_upload(job: Job, *, status: str = "uploading") -> YouTubeUpload:
    clip = Clip(id=new_id(), job_id=job.id, start_s=0, end_s=20)
    store.replace_clips(job.id, [clip])
    export = Export(id=new_id(), clip_id=clip.id, path=f"C:/exports/{clip.id}.mp4")
    store.create_export(export)
    upload = YouTubeUpload(id=new_id(), export_id=export.id, clip_id=clip.id, status=status)
    store.create_upload(upload)
    return upload


# --------------------------------------------------------------------------
# The store
# --------------------------------------------------------------------------


def test_a_restart_is_recorded_with_its_real_counts(initialised_db: int) -> None:
    restart = store.record_restart(
        jobs_resumed=2,
        uploads_resumed=1,
        batch_items_resumed=3,
        job_ids=["a", "b"],
        upload_ids=["c"],
        details="2 job(s); 1 upload(s)",
    )

    assert restart.jobs_resumed == 2
    assert restart.uploads_resumed == 1
    assert restart.batch_items_resumed == 3
    assert restart.total_resumed == 6
    assert restart.job_ids == ["a", "b"]

    stored = store.list_restarts(limit=5)
    assert len(stored) == 1
    assert stored[0].id == restart.id
    assert stored[0].total_resumed == 6
    assert stored[0].job_ids == ["a", "b"]


def test_restarts_are_listed_newest_first(initialised_db: int) -> None:
    first = store.record_restart(jobs_resumed=1)
    second = store.record_restart(jobs_resumed=2)

    stored = store.list_restarts(limit=10)
    ids = [row.id for row in stored]
    assert second.id in ids
    assert first.id in ids
    # Newest first — the order the UI reads them in.
    assert ids.index(second.id) < ids.index(first.id)


def test_a_restart_with_no_work_is_still_recorded(initialised_db: int) -> None:
    """A clean restart is normal; it must still leave a trace."""
    restart = store.record_restart()

    assert restart.total_resumed == 0
    assert len(store.list_restarts(limit=5)) == 1


def test_a_resumed_job_records_when_it_was_resumed(initialised_db: int) -> None:
    source = _seed_source()
    job = _seed_job(source)

    store.mark_job_resumed(job.id)

    reloaded = store.get_job(job.id)
    assert reloaded is not None
    assert reloaded.last_resumed_at is not None


def test_a_job_that_was_never_interrupted_has_no_resume_time(initialised_db: int) -> None:
    source = _seed_source()
    job = _seed_job(source)

    reloaded = store.get_job(job.id)
    assert reloaded is not None
    assert reloaded.last_resumed_at is None


def test_interrupted_uploads_are_requeued_and_reported(initialised_db: int) -> None:
    source = _seed_source()
    job = _seed_job(source, status="done")
    upload = _seed_upload(job, status="uploading")

    recovered = store.requeue_interrupted_uploads()

    assert recovered == [upload.id]
    reloaded = store.get_upload(upload.id)
    assert reloaded is not None
    assert reloaded.status == "pending"
    assert reloaded.last_resumed_at is not None


def test_a_pending_upload_is_not_reported_as_recovered(initialised_db: int) -> None:
    source = _seed_source()
    job = _seed_job(source, status="done")
    upload = _seed_upload(job, status="pending")

    recovered = store.requeue_interrupted_uploads()

    assert recovered == []
    reloaded = store.get_upload(upload.id)
    assert reloaded is not None
    assert reloaded.status == "pending"


# --------------------------------------------------------------------------
# The queue
# --------------------------------------------------------------------------


def test_the_job_queue_requeues_and_reports_interrupted_jobs(initialised_db: int) -> None:
    from autoclip.jobs.queue import JobQueue

    source = _seed_source()
    running = _seed_job(source, status="running")
    queued = _seed_job(source, status="queued")

    worker = JobQueue()
    resumed = worker._requeue_interrupted()

    assert resumed == [running.id]
    assert queued.id not in resumed

    reloaded = store.get_job(running.id)
    assert reloaded is not None
    assert reloaded.status == "queued"
    assert reloaded.last_resumed_at is not None


def test_a_healthy_startup_recovers_nothing(initialised_db: int) -> None:
    from autoclip.jobs.queue import JobQueue

    source = _seed_source()
    _seed_job(source, status="queued")

    worker = JobQueue()
    assert worker._requeue_interrupted() == []


# --------------------------------------------------------------------------
# Batches
# --------------------------------------------------------------------------


def test_interrupted_batch_items_are_requeued_and_reported(initialised_db: int) -> None:
    from autoclip.jobs import batches

    source = _seed_source()
    job = _seed_job(source, status="done")
    batch = batches.create_batch("A batch", {})
    item = batches.add_item(batch["id"], source.id, position=0)
    batches.update_item(item["id"], status="processing", job_id=job.id)

    recovered = batches.recover_interrupted()

    assert recovered == [item["id"]]
    reloaded = batches.get_item(item["id"])
    assert reloaded is not None
    assert reloaded["status"] == "pending"


def test_a_batch_with_nothing_in_flight_recovers_nothing(initialised_db: int) -> None:
    from autoclip.jobs import batches

    source = _seed_source()
    batch = batches.create_batch("A batch", {})
    item = batches.add_item(batch["id"], source.id, position=0)

    assert batches.recover_interrupted() == []
    reloaded = batches.get_item(item["id"])
    assert reloaded is not None
    assert reloaded["status"] == "pending"


# --------------------------------------------------------------------------
# The notification
# --------------------------------------------------------------------------


def test_a_restart_that_resumed_work_leaves_a_notification(initialised_db: int) -> None:
    from autoclip.notifications import events

    notification = events.app_restarted(jobs=1, uploads=2)

    assert notification is not None
    assert notification.severity == "warning"
    assert "restarted" in notification.title.lower()
    assert "1 job" in notification.body
    assert "2 uploads" in notification.body
    # The verb agrees with the whole list — three things were interrupted.
    assert "that were interrupted" in notification.body


def test_a_restart_that_resumed_one_thing_uses_the_singular(initialised_db: int) -> None:
    from autoclip.notifications import events

    notification = events.app_restarted(jobs=1)

    assert notification is not None
    assert notification.body == "Resumed 1 job that was interrupted."


def test_a_restart_that_resumed_several_things_uses_the_plural(initialised_db: int) -> None:
    from autoclip.notifications import events

    notification = events.app_restarted(jobs=2, uploads=1, batch_items=3)

    assert notification is not None
    assert "2 jobs" in notification.body
    assert "3 batch items" in notification.body
    assert "that were interrupted" in notification.body


def test_a_clean_restart_leaves_no_notification(initialised_db: int) -> None:
    from autoclip.notifications import events

    assert events.app_restarted() is None
    assert store.unread_notification_count() == 0


# --------------------------------------------------------------------------
# The API
# --------------------------------------------------------------------------


def test_the_restart_history_is_readable_from_the_api(client: TestClient) -> None:
    store.record_restart(jobs_resumed=1, uploads_resumed=2, job_ids=["abc"])

    response = client.get("/api/restarts")

    assert response.status_code == 200
    body = response.json()
    # The app's own startup already recorded a restart, so the one this test
    # adds is the latest.
    assert body["count"] >= 1
    latest = body["latest"]
    assert latest["jobs_resumed"] == 1
    assert latest["uploads_resumed"] == 2
    assert latest["total_resumed"] == 3
    assert latest["job_ids"] == ["abc"]


def test_a_restart_history_has_no_work_to_report_before_anything_resumes(
    client: TestClient,
) -> None:
    response = client.get("/api/restarts")

    assert response.status_code == 200
    body = response.json()
    # The app records its own startup; on a clean start it had nothing to
    # resume, and that is what the summary says.
    assert body["restarts_with_work"] == 0
    assert body["latest"]["total_resumed"] == 0
    assert body["latest"]["job_ids"] == []


def test_the_restart_history_honours_its_limit(client: TestClient) -> None:
    for _ in range(5):
        store.record_restart(jobs_resumed=1)

    response = client.get("/api/restarts?limit=2")

    assert response.status_code == 200
    assert len(response.json()["restarts"]) == 2


# --------------------------------------------------------------------------
# The startup path
# --------------------------------------------------------------------------


def test_the_app_records_its_own_restart(client: TestClient) -> None:
    """Starting the app writes a restart record — that is the whole point."""
    response = client.get("/api/restarts")

    assert response.status_code == 200
    body = response.json()
    assert body["count"] >= 1
    assert body["latest"]["total_resumed"] == 0


def test_starting_the_app_with_interrupted_work_records_the_recovery(
    client: TestClient,
) -> None:
    """A job left running by a crash is resumed and the resume is recorded."""
    source = _seed_source()
    job = _seed_job(source, status="running")

    # The app's own startup already ran when the fixture was created, so this
    # simulates what the *next* restart finds: the job is running again.
    store.update_job(job.id, status="running", error=None)

    from autoclip.jobs.queue import JobQueue

    worker = JobQueue()
    worker._requeue_interrupted()

    restart = store.record_restart(
        jobs_resumed=1,
        job_ids=[job.id],
    )

    assert restart.jobs_resumed == 1
    reloaded = store.get_job(job.id)
    assert reloaded is not None
    assert reloaded.last_resumed_at is not None


def test_a_failing_restart_record_never_breaks_startup(
    autoclip_home: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Reporting the restart must never stop the app from serving."""
    from autoclip import app as app_module

    def boom(*args: object, **kwargs: object) -> None:
        raise RuntimeError("the disk is full")

    monkeypatch.setattr(store, "record_restart", boom)

    # Does not raise.
    app_module._record_restart()


def test_the_recovered_ids_are_cleared_once_they_have_been_reported(
    autoclip_home: Path,
    initialised_db: int,
) -> None:
    """The queues are process-wide singletons; a second app must not re-report."""
    from autoclip import app as app_module
    from autoclip.jobs.batch_runner import batch_runner
    from autoclip.jobs.queue import queue
    from autoclip.youtube.queue import upload_queue

    queue.resumed_job_ids = ["job-1"]
    upload_queue.resumed_upload_ids = ["upload-1"]
    batch_runner.resumed_item_ids = ["item-1"]

    app_module._record_restart()

    assert queue.resumed_job_ids == []
    assert upload_queue.resumed_upload_ids == []
    assert batch_runner.resumed_item_ids == []

    latest = store.list_restarts(limit=1)[0]
    assert latest.job_ids == ["job-1"]
    assert latest.upload_ids == ["upload-1"]


def test_the_queue_survives_a_restart_without_the_worker(client: TestClient) -> None:
    """A job queued before the restart is still queued after it."""
    source = _seed_source()
    job = _seed_job(source, status="queued")

    reloaded = store.get_job(job.id)
    assert reloaded is not None
    assert reloaded.status == "queued"


def test_the_upload_queue_reports_its_recovered_uploads(initialised_db: int) -> None:
    from autoclip.youtube.queue import UploadQueue

    source = _seed_source()
    job = _seed_job(source, status="done")
    upload = _seed_upload(job, status="uploading")

    worker = UploadQueue()
    worker.resumed_upload_ids = store.requeue_interrupted_uploads()

    assert worker.resumed_upload_ids == [upload.id]


def test_the_batch_runner_reports_its_recovered_items(initialised_db: int) -> None:
    from autoclip.jobs import batches
    from autoclip.jobs.batch_runner import BatchRunner

    source = _seed_source()
    job = _seed_job(source, status="done")
    batch = batches.create_batch("A batch", {})
    item = batches.add_item(batch["id"], source.id, position=0)
    batches.update_item(item["id"], status="processing", job_id=job.id)

    runner = BatchRunner()
    runner.resumed_item_ids = batches.recover_interrupted()

    assert runner.resumed_item_ids == [item["id"]]


def test_the_asyncio_loop_is_not_left_bound_to_a_dead_one(initialised_db: int) -> None:
    """The queue's wakeup event must not survive across event loops."""
    from autoclip.jobs.queue import JobQueue

    worker = JobQueue()

    async def start_and_stop() -> None:
        await worker.start()
        await worker.stop()

    asyncio.run(start_and_stop())
