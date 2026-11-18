"""Phase 14 — the notification centre."""

from __future__ import annotations

import pytest
from autoclip.db import store
from autoclip.db.models import Clip, Export, Job, Source, YouTubeUpload, new_id
from autoclip.notifications import events
from fastapi.testclient import TestClient

# --------------------------------------------------------------------------
# Helpers
# --------------------------------------------------------------------------


def _seed_source(title: str = "A Video") -> Source:
    source = Source(id=new_id(), type="upload", path="C:/videos/source.mp4", title=title)
    store.create_source(source)
    return source


def _seed_job(source: Source, *, status: str = "done", error: str | None = None) -> Job:
    job = Job(id=new_id(), source_id=source.id, status=status, error=error)
    store.create_job(job)
    return job


def _seed_clip(job: Job, *, title: str = "A Clip") -> Clip:
    clip = Clip(
        id=new_id(), job_id=job.id, start_s=0.0, end_s=20.0, rank=1, title=title, status="exported"
    )
    store.replace_clips(job.id, [clip])
    return clip


# --------------------------------------------------------------------------
# Events
# --------------------------------------------------------------------------


def test_notify_stores_a_row(autoclip_home, initialised_db: int) -> None:
    notification = events.notify(
        "test",
        severity="success",
        title="It happened",
        body="Really.",
        link="/clips",
        entity_id="abc",
    )

    assert notification is not None
    rows = store.list_notifications()
    assert len(rows) == 1
    assert rows[0].kind == "test"
    assert rows[0].severity == "success"
    assert rows[0].title == "It happened"
    assert rows[0].read is False


def test_job_done_notification_reports_the_real_count(
    autoclip_home, initialised_db: int
) -> None:
    source = _seed_source("My Video")
    job = _seed_job(source)
    _seed_clip(job, title="One")
    _seed_clip(job, title="Two")

    events.job_done(job.id, "My Video", 2)

    row = store.list_notifications()[0]
    assert row.kind == "job_done"
    assert row.severity == "success"
    assert "My Video" in row.title
    assert "Found 2 clips" in row.body
    assert row.link == f"/jobs/{job.id}/clips"


def test_job_failed_notification_carries_the_error(
    autoclip_home, initialised_db: int
) -> None:
    source = _seed_source("Broken")
    job = _seed_job(source, status="failed", error="ffmpeg exited with code 1")

    events.job_failed(job.id, "Broken", "ffmpeg exited with code 1")

    row = store.list_notifications()[0]
    assert row.kind == "job_failed"
    assert row.severity == "error"
    assert "ffmpeg exited with code 1" in row.body


def test_clip_exported_notifications(autoclip_home, initialised_db: int) -> None:
    source = _seed_source()
    job = _seed_job(source)
    clip = _seed_clip(job, title="Great clip")

    events.clip_exported(clip.id, "Great clip", ok=True, failures=[])
    events.clip_exported(clip.id, "Bad clip", ok=False, failures=["resolution", "duration"])

    rows = store.list_notifications()
    by_kind = {row.kind: row for row in rows}
    assert by_kind["clip_exported"].severity == "success"
    assert by_kind["clip_invalid"].severity == "warning"
    assert "resolution; duration" in by_kind["clip_invalid"].body
    assert "not published" in by_kind["clip_invalid"].body


def test_upload_notifications(autoclip_home, initialised_db: int) -> None:
    events.upload_done("u1", "Published clip", "abc123", "My Channel")
    events.upload_failed("u2", "Failed clip", "quotaExceeded")
    events.upload_skipped("u3", "Skipped clip", "Already published")

    rows = {row.kind: row for row in store.list_notifications()}
    assert rows["upload_done"].severity == "success"
    assert "My Channel" in rows["upload_done"].body
    assert "youtu.be/abc123" in rows["upload_done"].body
    assert rows["upload_failed"].severity == "error"
    assert "quotaExceeded" in rows["upload_failed"].body
    assert rows["upload_skipped"].severity == "info"


def test_batch_done_notification(autoclip_home, initialised_db: int) -> None:
    events.batch_done("b1", "Nightly batch", 4, 1)

    row = store.list_notifications()[0]
    assert row.kind == "batch_done"
    assert row.severity == "warning"
    assert "4 finished" in row.body
    assert "1 failed" in row.body


def test_a_broken_notify_does_not_raise(autoclip_home, monkeypatch: pytest.MonkeyPatch) -> None:
    """A notification failure must never break the work it describes."""
    monkeypatch.setattr(
        store, "create_notification", lambda *_args, **_kwargs: (_ for _ in ()).throw(
            RuntimeError("disk full")
        )
    )

    assert events.notify("test", title="Nope") is None


def test_inbox_is_pruned(autoclip_home, initialised_db: int) -> None:
    for index in range(events.MAX_NOTIFICATIONS + 20):
        events.notify("test", title=f"n{index}")

    rows = store.list_notifications(limit=1000)
    assert len(rows) <= events.MAX_NOTIFICATIONS


def test_upload_notification_uses_the_generated_title(
    autoclip_home, initialised_db: int
) -> None:
    """The title is written after the worker's snapshot was read."""
    from autoclip.youtube import queue as queue_module

    source = _seed_source()
    job = _seed_job(source)
    clip = _seed_clip(job, title="A Clip")

    export = Export(id=new_id(), clip_id=clip.id, path="C:/out.mp4")
    store.create_export(export)
    upload = store.create_upload(
        YouTubeUpload(id=new_id(), export_id=export.id, clip_id=clip.id, status="pending")
    )

    # The worker's snapshot has no title yet; the row does.
    snapshot = store.get_upload(upload.id)
    assert snapshot.title == ""
    store.update_upload(upload.id, title="The generated title")

    queue_module._notify(snapshot, "done", "vid-123")

    row = store.list_notifications()[0]
    assert "The generated title" in row.title
    assert "youtu.be/vid-123" in row.body


def test_skipped_upload_notification_falls_back_to_the_clip_title(
    autoclip_home, initialised_db: int
) -> None:
    """A skipped upload never generates metadata, so the clip title is used."""
    from autoclip.youtube import queue as queue_module

    source = _seed_source()
    job = _seed_job(source)
    clip = _seed_clip(job, title="The clip's own title")
    export = Export(id=new_id(), clip_id=clip.id, path="C:/out.mp4")
    store.create_export(export)
    upload = store.create_upload(
        YouTubeUpload(id=new_id(), export_id=export.id, clip_id=clip.id, status="pending")
    )

    queue_module._notify(store.get_upload(upload.id), "skipped", "already published")

    row = store.list_notifications()[0]
    assert "The clip's own title" in row.title
    assert "already published" in row.body


# --------------------------------------------------------------------------
# Store operations
# --------------------------------------------------------------------------


def test_unread_count_and_marking(autoclip_home, initialised_db: int) -> None:
    first = events.notify("test", title="One")
    events.notify("test", title="Two")

    assert store.unread_notification_count() == 2

    assert store.mark_notification_read(first.id) is True
    assert store.unread_notification_count() == 1
    assert store.mark_notification_read("missing") is False

    assert store.mark_all_notifications_read() == 1
    assert store.unread_notification_count() == 0


def test_clear_read_keeps_unread(autoclip_home, initialised_db: int) -> None:
    read = events.notify("test", title="Read")
    events.notify("test", title="Unread")
    store.mark_notification_read(read.id)

    removed = store.clear_read_notifications()

    assert removed == 1
    rows = store.list_notifications()
    assert len(rows) == 1
    assert rows[0].title == "Unread"


def test_delete_notification(autoclip_home, initialised_db: int) -> None:
    notification = events.notify("test", title="Bye")

    assert store.delete_notification(notification.id) is True
    assert store.delete_notification(notification.id) is False
    assert store.list_notifications() == []


# --------------------------------------------------------------------------
# HTTP API
# --------------------------------------------------------------------------


def test_notifications_api(autoclip_home, initialised_db: int) -> None:
    from autoclip.app import create_app

    first = events.notify("test", severity="success", title="One", link="/clips")
    events.notify("test", severity="error", title="Two")

    with TestClient(create_app()) as client:
        listing = client.get("/api/notifications").json()
        assert len(listing) == 2
        assert listing[0]["title"] == "Two"  # newest first
        assert listing[0]["severity"] == "error"

        count = client.get("/api/notifications/unread-count").json()
        assert count["unread"] == 2

        marked = client.post(f"/api/notifications/{first.id}/read")
        assert marked.status_code == 200
        assert client.get("/api/notifications/unread-count").json()["unread"] == 1

        assert client.post("/api/notifications/missing/read").status_code == 404

        unread = client.get("/api/notifications?unread_only=true").json()
        assert len(unread) == 1

        assert client.post("/api/notifications/read-all").json()["marked"] == 1
        assert client.get("/api/notifications/unread-count").json()["unread"] == 0

        assert client.delete(f"/api/notifications/{first.id}").status_code == 200
        assert client.delete(f"/api/notifications/{first.id}").status_code == 404

        events.notify("test", title="Three")
        assert client.post("/api/notifications/clear").json()["removed"] >= 1


def test_job_runner_records_a_notification(
    autoclip_home, initialised_db: int, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A finished job leaves a notification behind."""
    from autoclip.pipeline import runner as runner_module

    source = _seed_source("Runner Video")
    job = _seed_job(source, status="running")

    class FakeRunner(runner_module.PipelineRunner):
        def __init__(self):  # noqa: D107 - test double
            self.job = job

    fake = FakeRunner()
    monkeypatch.setattr(
        runner_module.PipelineRunner,
        "_stage_prepare",
        lambda self: None,
    )
    monkeypatch.setattr(
        runner_module.PipelineRunner,
        "_stage_transcribe",
        lambda self, audio: None,
    )
    monkeypatch.setattr(
        runner_module.PipelineRunner,
        "_load_or_detect_silences",
        lambda self, audio: [],
    )

    async def fake_highlights(self, transcript, silences):
        clip = Clip(
            id=new_id(),
            job_id=job.id,
            start_s=0.0,
            end_s=20.0,
            rank=1,
            title="Found clip",
            status="candidate",
        )
        store.replace_clips(job.id, [clip])
        return [clip]

    def fake_reframe(self, clips, transcript):
        return {}

    monkeypatch.setattr(
        runner_module.PipelineRunner, "_stage_highlights", fake_highlights
    )
    monkeypatch.setattr(runner_module.PipelineRunner, "_stage_reframe", fake_reframe)
    monkeypatch.setattr(
        runner_module.PipelineRunner, "_stage_captions", lambda self, clips, transcript: None
    )
    monkeypatch.setattr(
        runner_module.PipelineRunner,
        "_stage_export",
        lambda self, clips, transcript, crop_paths: None,
    )

    import asyncio

    asyncio.run(fake.run())

    rows = store.list_notifications()
    assert rows
    assert rows[0].kind == "job_done"
    assert "Runner Video" in rows[0].title
    assert "Found 1 clip" in rows[0].body
