"""The job state machine's terminal-state bookkeeping.

A job that has reached a terminal state — done, failed, cancelled — has to
say so consistently. A finish time older than the change that produced it,
or missing entirely, makes the history lie; and a cancel request that
outlives the cancellation makes the retry impossible.

These are the three ways that went wrong. Each was found by reading the real
database after a live run, not by a test failing:

* a retry left the previous attempt's finish time behind, so a queued job
  still claimed it had already finished;
* cancelling a queued job never stamped a finish time, so the job looked
  like it was still in flight;
* the queue's cancel flag was only cleared when a runner finished, so a job
  cancelled while it sat in the queue could never run again — the retry was
  cancelled the instant the worker picked it up.
"""

from __future__ import annotations

import asyncio
from collections.abc import Iterator
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest
from autoclip import db
from autoclip.db import store
from autoclip.db.models import Job, Source, new_id
from fastapi.testclient import TestClient

# --------------------------------------------------------------------------
# Fixtures
# --------------------------------------------------------------------------


@pytest.fixture
def client(autoclip_home: Path, monkeypatch: pytest.MonkeyPatch) -> Iterator[TestClient]:
    from autoclip import app as app_module
    from autoclip.app import create_app

    # The background worker stays off: these tests are about the state the
    # API writes, and a worker picking the job up would race the assertions.
    monkeypatch.setenv(app_module.ENV_NO_WORKER, "1")
    with TestClient(create_app()) as test_client:
        yield test_client


@pytest.fixture
def source() -> Source:
    return store.create_source(
        Source(
            id=new_id(),
            type="upload",
            path="C:/media/video.mp4",
            title="Test source",
            duration_s=600.0,
        )
    )


def _failed_job(source: Source) -> Job:
    """A job that failed, with the timestamps that failure left behind."""
    return store.create_job(
        Job(
            id=new_id(),
            source_id=source.id,
            status="failed",
            error="boom",
            started_at="2026-01-01T10:00:00+00:00",
            finished_at="2026-01-01T10:01:00+00:00",
        )
    )


def _moment(value: str) -> datetime:
    return datetime.fromisoformat(value)


# --------------------------------------------------------------------------
# Retry
# --------------------------------------------------------------------------


class TestRetry:
    def test_a_retry_clears_the_previous_attempt_s_finish_time(
        self, client: TestClient, source: Source
    ) -> None:
        job = _failed_job(source)

        response = client.post(f"/api/jobs/{job.id}/retry")

        assert response.status_code == 200
        body = response.json()
        assert body["status"] == "queued"
        # The old finish time belonged to the old attempt. Left behind, it
        # made a queued job claim it had finished before this run began.
        assert body["finished_at"] is None
        assert body["started_at"] is None
        assert body["error"] is None
        assert body["progress"] == 0.0

    def test_a_retry_clears_the_cancel_request_the_cancellation_left(
        self, client: TestClient, source: Source
    ) -> None:
        from autoclip.jobs.queue import queue

        job_id = client.post("/api/jobs", json={"source_id": source.id}).json()["id"]
        assert client.post(f"/api/jobs/{job_id}/cancel").status_code == 200
        assert queue.is_cancelled(job_id) is True

        assert client.post(f"/api/jobs/{job_id}/retry").status_code == 200

        # The flag belonged to the cancellation, not to the retry.
        assert queue.is_cancelled(job_id) is False


# --------------------------------------------------------------------------
# Cancel
# --------------------------------------------------------------------------


class TestCancel:
    def test_cancelling_a_queued_job_stamps_a_finish_time(
        self, client: TestClient, source: Source
    ) -> None:
        job_id = client.post("/api/jobs", json={"source_id": source.id}).json()["id"]

        response = client.post(f"/api/jobs/{job_id}/cancel")

        assert response.status_code == 200
        body = response.json()
        assert body["status"] == "cancelled"
        # The job is finished; the row has to say when it finished.
        assert body["finished_at"] is not None

    def test_a_cancelled_job_s_finish_time_is_the_cancellation(
        self, client: TestClient, source: Source
    ) -> None:
        job_id = client.post("/api/jobs", json={"source_id": source.id}).json()["id"]

        assert client.post(f"/api/jobs/{job_id}/cancel").status_code == 200

        row = store.get_job(job_id)
        assert row is not None
        assert row.finished_at is not None
        finished = _moment(row.finished_at)
        assert finished >= _moment(row.created_at)
        assert finished <= datetime.now(UTC) + timedelta(seconds=5)


# --------------------------------------------------------------------------
# The sequence the real database actually went through
# --------------------------------------------------------------------------


def test_failing_then_retrying_then_cancelling_leaves_a_consistent_row(
    client: TestClient, source: Source
) -> None:
    """Fail, retry, cancel — the exact sequence that produced a stale row.

    The retry requeued the job; the cancellation then stopped it while it
    was still waiting behind another job. The row kept the *failure's*
    finish time, so it claimed the job had finished an hour before it was
    actually cancelled.
    """
    job = _failed_job(source)
    failed_at = job.finished_at
    assert failed_at is not None

    assert client.post(f"/api/jobs/{job.id}/retry").status_code == 200
    assert client.post(f"/api/jobs/{job.id}/cancel").status_code == 200

    row = store.get_job(job.id)
    assert row is not None
    assert row.status == "cancelled"
    assert row.error is None
    assert row.finished_at is not None
    # The finish time belongs to this cancellation, not to the failure
    # that preceded it.
    assert _moment(row.finished_at) > _moment(failed_at)


def test_a_job_cancelled_while_queued_can_run_after_the_retry(
    client: TestClient,
    source: Source,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The user-visible form of the bug: the retry could never run.

    Cancelling a job that is still queued leaves the queue's cancel flag
    set, and nothing clears it — the job never had a runner to clear it. The
    retry put the job back in the queue, where the worker cancelled it the
    instant it started, over and over.
    """
    from autoclip.jobs import queue as queue_module

    job_id = client.post("/api/jobs", json={"source_id": source.id}).json()["id"]
    assert client.post(f"/api/jobs/{job_id}/cancel").status_code == 200
    assert client.post(f"/api/jobs/{job_id}/retry").status_code == 200

    seen: list[bool] = []

    def fake_run_blocking(runner):
        # What the runner checks before every stage.
        seen.append(queue_module.queue.is_cancelled(job_id))
        store.update_job(
            job_id,
            status="done",
            progress=1.0,
            finished_at="2026-01-01T12:00:00+00:00",
        )
        return []

    monkeypatch.setattr(queue_module, "_run_blocking", fake_run_blocking)

    job = store.get_job(job_id)
    assert job is not None
    asyncio.run(queue_module.queue._run_one(job))

    assert seen == [False], "the job was cancelled the moment it started"
    reloaded = store.get_job(job_id)
    assert reloaded is not None
    assert reloaded.status == "done"


# --------------------------------------------------------------------------
# A cancellation is not a failure
# --------------------------------------------------------------------------


class _CancelledEngine:
    """A speech engine that stopped because the job was cancelled."""

    name = "fake"

    def transcribe(self, audio, settings, **kwargs):
        from autoclip.speech import SpeechCancelled

        raise SpeechCancelled("Transcription cancelled.")


def test_the_local_engine_reports_a_cancellation_as_a_cancellation(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The user stopping the job is not an engine failure."""
    from autoclip.config import TranscriptionSettings
    from autoclip.speech import base as speech_base
    from autoclip.speech import local as local_module

    def boom(*args: object, **kwargs: object) -> None:
        raise local_module.local_transcribe.TranscriptionError("Transcription cancelled.")

    monkeypatch.setattr(local_module.local_transcribe, "transcribe", boom)

    engine = local_module.LocalWhisperSTT()
    with pytest.raises(speech_base.SpeechCancelled):
        engine.transcribe(
            Path("audio.wav"),
            TranscriptionSettings(),
            cancelled=lambda: True,
        )


def test_a_cancelled_transcription_is_not_a_failed_job(
    initialised_db: int,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Cancelling mid-transcription must leave the job cancelled, not failed."""
    from autoclip.config import Settings
    from autoclip.pipeline import runner as runner_module

    runner = runner_module.PipelineRunner(
        Job(id="job-cancel", source_id="src-cancel"),
        Source(id="src-cancel", type="upload", path="C:/videos/source.mp4"),
        settings=Settings(),
    )
    monkeypatch.setattr(
        runner_module.speech,
        "resolve_engine",
        lambda _settings: (_CancelledEngine(), None),
    )

    with pytest.raises(runner_module.JobCancelled):
        runner._stage_transcribe(Path("audio.wav"))


def test_a_cancelled_transcription_never_falls_back_to_another_engine(
    initialised_db: int,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The fallback would start a second transcription for a stopped job."""
    from autoclip.config import Settings
    from autoclip.pipeline import runner as runner_module

    runner = runner_module.PipelineRunner(
        Job(id="job-cancel", source_id="src-cancel"),
        Source(id="src-cancel", type="upload", path="C:/videos/source.mp4"),
        settings=Settings(),
    )
    monkeypatch.setattr(
        runner_module.speech,
        "resolve_engine",
        lambda _settings: (_CancelledEngine(), None),
    )

    def boom(*args: object, **kwargs: object) -> None:
        raise AssertionError("the fallback must not run for a cancelled job")

    monkeypatch.setattr(runner_module.LocalWhisperSTT, "transcribe", boom)

    with pytest.raises(runner_module.JobCancelled):
        runner._stage_transcribe(Path("audio.wav"))


# --------------------------------------------------------------------------
# The queue's own failure path
# --------------------------------------------------------------------------


def test_a_job_whose_source_vanished_fails_with_a_finish_time(initialised_db: int) -> None:
    """A failure the queue reports itself still has to stamp the finish time."""
    from autoclip.jobs import queue as queue_module

    source = store.create_source(
        Source(id=new_id(), type="upload", path="C:/videos/source.mp4", title="A Video")
    )
    job = store.create_job(Job(id=new_id(), source_id=source.id, status="queued"))

    # The source is removed with the foreign-key check off. Normally the
    # cascade would take the job with it, but the queue still has to cope
    # with a job whose source is not there.
    with db.connection() as conn:
        conn.execute("PRAGMA foreign_keys = OFF")
        conn.execute("DELETE FROM sources WHERE id = ?", (source.id,))
        conn.execute("PRAGMA foreign_keys = ON")

    asyncio.run(queue_module.queue._run_one(job))

    row = store.get_job(job.id)
    assert row is not None
    assert row.status == "failed"
    assert row.error == "Source not found."
    assert row.finished_at is not None


# --------------------------------------------------------------------------
# The repair migration
# --------------------------------------------------------------------------


def test_the_repair_migration_fixes_the_rows_an_older_build_left_wrong(
    autoclip_home: Path,
) -> None:
    """The rows the old code wrote wrong are corrected, not left to lie."""
    from autoclip.db import schema

    # Build the database at the version before the repair.
    conn = db.connect()
    try:
        for index in range(12):
            with conn:
                schema.MIGRATIONS[index](conn)
                conn.execute(f"PRAGMA user_version = {index + 1}")
    finally:
        conn.close()

    source = store.create_source(
        Source(id=new_id(), type="upload", path="C:/videos/source.mp4", title="A Video")
    )
    stale = store.create_job(
        Job(
            id=new_id(),
            source_id=source.id,
            status="cancelled",
            updated_at="2026-01-01T12:00:00+00:00",
            finished_at="2026-01-01T11:00:00+00:00",
        )
    )
    missing = store.create_job(
        Job(
            id=new_id(),
            source_id=source.id,
            status="cancelled",
            updated_at="2026-01-01T12:00:00+00:00",
        )
    )
    waiting = store.create_job(
        Job(
            id=new_id(),
            source_id=source.id,
            status="queued",
            updated_at="2026-01-01T12:00:00+00:00",
            finished_at="2026-01-01T11:00:00+00:00",
        )
    )

    assert db.init() == db.SCHEMA_VERSION

    repaired = store.get_job(stale.id)
    assert repaired is not None
    assert repaired.finished_at == "2026-01-01T12:00:00+00:00"

    filled = store.get_job(missing.id)
    assert filled is not None
    assert filled.finished_at == "2026-01-01T12:00:00+00:00"

    cleared = store.get_job(waiting.id)
    assert cleared is not None
    assert cleared.finished_at is None


def test_the_repair_migration_fixes_a_cancelled_transcription_reported_as_a_failure(
    autoclip_home: Path,
) -> None:
    """A job the user stopped was not a job that failed."""
    from autoclip.db import schema

    conn = db.connect()
    try:
        for index in range(13):
            with conn:
                schema.MIGRATIONS[index](conn)
                conn.execute(f"PRAGMA user_version = {index + 1}")
    finally:
        conn.close()

    source = store.create_source(
        Source(id=new_id(), type="upload", path="C:/videos/source.mp4", title="A Video")
    )
    stopped = store.create_job(
        Job(
            id=new_id(),
            source_id=source.id,
            status="failed",
            error="Transcription cancelled.",
            updated_at="2026-01-01T12:00:00+00:00",
            finished_at="2026-01-01T12:00:00+00:00",
        )
    )
    genuinely_failed = store.create_job(
        Job(
            id=new_id(),
            source_id=source.id,
            status="failed",
            error="No clips were found.",
            updated_at="2026-01-01T12:00:00+00:00",
            finished_at="2026-01-01T12:00:00+00:00",
        )
    )

    assert db.init() == db.SCHEMA_VERSION

    repaired = store.get_job(stopped.id)
    assert repaired is not None
    assert repaired.status == "cancelled"

    # A job that failed for a real reason keeps its status.
    untouched = store.get_job(genuinely_failed.id)
    assert untouched is not None
    assert untouched.status == "failed"
    assert untouched.error == "No clips were found."
