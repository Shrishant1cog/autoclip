"""Resumable uploads: chunks, sessions, progress, quota and backoff.

The upload used to be one PUT of the whole file, so a dropped
connection cost the entire file and the next attempt started from zero.
These tests cover the machinery that stops that happening:

* the file is sent in chunks, with the right byte ranges,
* the session is kept, so an interrupted upload continues,
* the progress reported is the real byte count,
* the day's quota is written down before the call is made, and
* a failing upload backs off instead of hammering the API.
"""

from __future__ import annotations

import json
from collections.abc import Iterator
from pathlib import Path
from typing import Any

import pytest
from autoclip import app as app_module
from autoclip import config
from autoclip.app import create_app
from autoclip.db import store
from autoclip.db.models import Clip, Export, Job, Source, YouTubeUpload, new_id
from autoclip.youtube import backoff, quota, resumable, uploader
from autoclip.youtube.resumable import CHUNK_SIZE, ResumableError
from fastapi.testclient import TestClient

# --------------------------------------------------------------------------
# Fixtures
# --------------------------------------------------------------------------


@pytest.fixture
def client(autoclip_home: Path, monkeypatch: pytest.MonkeyPatch) -> Iterator[TestClient]:
    monkeypatch.setenv(app_module.ENV_NO_WORKER, "1")
    with TestClient(create_app()) as test_client:
        yield test_client


# --------------------------------------------------------------------------
# The chunks
# --------------------------------------------------------------------------


def test_a_small_file_is_one_chunk() -> None:
    assert resumable.chunk_ranges(100) == [(0, 99)]


def test_a_file_exactly_one_chunk_long_is_one_chunk() -> None:
    assert resumable.chunk_ranges(CHUNK_SIZE) == [(0, CHUNK_SIZE - 1)]


def test_the_chunks_cover_the_whole_file_without_gaps() -> None:
    total = CHUNK_SIZE * 2 + 1234
    ranges = resumable.chunk_ranges(total)

    assert ranges[0][0] == 0
    assert ranges[-1][1] == total - 1
    for (_, end), (start, _) in zip(ranges, ranges[1:], strict=False):
        assert start == end + 1


def test_an_empty_file_has_no_chunks() -> None:
    assert resumable.chunk_ranges(0) == []


# --------------------------------------------------------------------------
# The session
# --------------------------------------------------------------------------


class _Response:
    def __init__(self, status: int, body: dict | None = None, headers: dict | None = None) -> None:
        self.status_code = status
        self._body = body or {}
        self.headers = headers or {}
        self.text = ""

    def json(self) -> dict:
        return self._body


def test_creating_a_session_sends_the_declaration(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    bodies: list[dict] = []

    def fake_post(url: str, **kwargs: Any) -> _Response:
        bodies.append(kwargs["json"])
        return _Response(
            200, headers={"location": "https://upload.example/session", "x-goog-expires": "604800"}
        )

    monkeypatch.setattr(resumable.httpx, "post", fake_post)

    session = resumable.create_session(
        url="https://upload.example/videos",
        token="token",
        metadata=uploader.ClipMetadata(title="T", description="D", tags=["a"]),
        privacy="unlisted",
        made_for_kids=True,
        total_bytes=1234,
    )

    assert session.url == "https://upload.example/session"
    assert session.total_bytes == 1234
    assert bodies[0]["status"]["privacyStatus"] == "unlisted"
    assert bodies[0]["status"]["selfDeclaredMadeForKids"] is True


def test_a_session_without_a_url_is_an_error(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(resumable.httpx, "post", lambda url, **kwargs: _Response(200))

    with pytest.raises(ResumableError):
        resumable.create_session(
            url="https://upload.example/videos",
            token="token",
            metadata=uploader.ClipMetadata(title="T", description="", tags=[]),
            privacy="private",
            made_for_kids=False,
        )


def test_the_probe_reads_the_range_header(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        resumable.httpx,
        "put",
        lambda url, **kwargs: _Response(308, headers={"range": "bytes=0-1048575"}),
    )

    assert resumable.probe(session_url="s", token="t", total_bytes=2097152) == 1048576


def test_the_probe_of_an_empty_session_is_zero(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(resumable.httpx, "put", lambda url, **kwargs: _Response(308))

    assert resumable.probe(session_url="s", token="t", total_bytes=100) == 0


# --------------------------------------------------------------------------
# The transfer
# --------------------------------------------------------------------------


def test_the_file_is_sent_in_chunks(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    file = tmp_path / "clip.mp4"
    file.write_bytes(b"x" * (CHUNK_SIZE + 100))

    sent: list[dict] = []

    def fake_put(url: str, **kwargs: Any) -> _Response:
        sent.append(kwargs["headers"])
        if len(sent) == 1:
            return _Response(308)
        return _Response(200, body={"id": "vid-1"})

    monkeypatch.setattr(resumable.httpx, "put", fake_put)

    body = resumable.upload_file(
        session=resumable.UploadSession(url="s"),
        path=file,
        token="token",
    )

    assert body["id"] == "vid-1"
    assert len(sent) == 2
    assert sent[0]["Content-Range"] == f"bytes 0-{CHUNK_SIZE - 1}/{CHUNK_SIZE + 100}"
    assert sent[1]["Content-Range"] == f"bytes {CHUNK_SIZE}-{CHUNK_SIZE + 99}/{CHUNK_SIZE + 100}"


def test_the_progress_is_the_real_byte_count(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    file = tmp_path / "clip.mp4"
    file.write_bytes(b"x" * (CHUNK_SIZE + 100))

    calls: list[int] = []

    def fake_put(url: str, **kwargs: Any) -> _Response:
        if len(calls) == 1:
            return _Response(308)
        return _Response(200, body={"id": "vid-1"})

    monkeypatch.setattr(resumable.httpx, "put", fake_put)

    resumable.upload_file(
        session=resumable.UploadSession(url="s"),
        path=file,
        token="token",
        progress=lambda sent, total: calls.append(sent),
    )

    assert calls == [0, CHUNK_SIZE, CHUNK_SIZE + 100]


def test_the_upload_continues_from_the_offset(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A resumed upload sends only what YouTube is missing."""
    file = tmp_path / "clip.mp4"
    file.write_bytes(b"x" * (CHUNK_SIZE + 100))

    sent: list[dict] = []

    def fake_put(url: str, **kwargs: Any) -> _Response:
        sent.append(kwargs["headers"])
        return _Response(200, body={"id": "vid-1"})

    monkeypatch.setattr(resumable.httpx, "put", fake_put)

    resumable.upload_file(
        session=resumable.UploadSession(url="s"),
        path=file,
        token="token",
        start_offset=CHUNK_SIZE,
    )

    assert len(sent) == 1
    assert sent[0]["Content-Range"] == f"bytes {CHUNK_SIZE}-{CHUNK_SIZE + 99}/{CHUNK_SIZE + 100}"


def test_a_refused_chunk_names_the_byte_it_stopped_at(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    file = tmp_path / "clip.mp4"
    file.write_bytes(b"x" * 100)

    monkeypatch.setattr(
        resumable.httpx,
        "put",
        lambda url, **kwargs: _Response(400, body={"error": {"message": "bad chunk"}}),
    )

    with pytest.raises(ResumableError) as caught:
        resumable.upload_file(session=resumable.UploadSession(url="s"), path=file, token="token")

    assert "byte 0" in str(caught.value)
    assert "bad chunk" in str(caught.value)


def test_an_empty_file_is_refused(tmp_path: Path) -> None:
    file = tmp_path / "clip.mp4"
    file.write_bytes(b"")

    with pytest.raises(ResumableError):
        resumable.upload_file(session=resumable.UploadSession(url="s"), path=file, token="token")


# --------------------------------------------------------------------------
# The state that survives a restart
# --------------------------------------------------------------------------


def test_the_session_is_stored_on_the_row(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """A session that is not stored cannot be resumed."""
    file = tmp_path / "clip.mp4"
    file.write_bytes(b"x" * 100)

    monkeypatch.setattr(
        resumable.httpx,
        "post",
        lambda url, **kwargs: _Response(200, headers={"location": "https://upload.example/s"}),
    )
    monkeypatch.setattr(
        resumable.httpx,
        "put",
        lambda url, **kwargs: _Response(200, body={"id": "vid-1"}),
    )
    monkeypatch.setattr(uploader.oauth, "access_token", lambda _=None, account_id=None: "token")

    sessions: list[tuple[str, str]] = []
    uploader.upload_video(
        config.load(),
        path=file,
        metadata=uploader.ClipMetadata(title="T", description="", tags=[]),
        privacy="private",
        made_for_kids=False,
        on_session=lambda url, expiry: sessions.append((url, expiry)),
    )

    assert sessions == [("https://upload.example/s", "")]


def test_a_stored_session_is_probed_before_the_file_is_sent(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    file = tmp_path / "clip.mp4"
    file.write_bytes(b"x" * 100)

    probed: list[dict] = []
    sent: list[dict] = []

    def fake_put(url: str, **kwargs: Any) -> _Response:
        if kwargs["headers"].get("Content-Range", "").endswith("*/100"):
            probed.append(kwargs["headers"])
            return _Response(308, headers={"range": "bytes=0-49"})
        sent.append(kwargs["headers"])
        return _Response(200, body={"id": "vid-1"})

    monkeypatch.setattr(resumable.httpx, "put", fake_put)
    monkeypatch.setattr(uploader.oauth, "access_token", lambda _=None, account_id=None: "token")

    uploader.upload_video(
        config.load(),
        path=file,
        metadata=uploader.ClipMetadata(title="T", description="", tags=[]),
        privacy="private",
        made_for_kids=False,
        session_url="https://upload.example/stored",
        bytes_sent=0,
    )

    assert probed, "the stored session should have been probed"
    # Only the missing half was sent.
    assert sent[0]["Content-Range"] == "bytes 50-99/100"


def test_an_expired_session_starts_a_new_one(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A session that has expired cannot be continued, so it is replaced."""
    file = tmp_path / "clip.mp4"
    file.write_bytes(b"x" * 100)

    posted: list[dict] = []
    sent: list[dict] = []

    def fake_post(url: str, **kwargs: Any) -> _Response:
        posted.append(kwargs)
        return _Response(200, headers={"location": "https://upload.example/new"})

    def fake_put(url: str, **kwargs: Any) -> _Response:
        sent.append(kwargs["headers"])
        return _Response(200, body={"id": "vid-1"})

    monkeypatch.setattr(resumable.httpx, "post", fake_post)
    monkeypatch.setattr(resumable.httpx, "put", fake_put)
    monkeypatch.setattr(uploader.oauth, "access_token", lambda _=None, account_id=None: "token")

    sessions: list[tuple[str, str]] = []
    uploader.upload_video(
        config.load(),
        path=file,
        metadata=uploader.ClipMetadata(title="T", description="", tags=[]),
        privacy="private",
        made_for_kids=False,
        session_url="https://upload.example/old",
        bytes_sent=50,
        session_expires_at="2000-01-01T00:00:00+00:00",
        on_session=lambda url, expiry: sessions.append((url, expiry)),
    )

    # A new session was opened and the whole file was sent again.
    assert sessions == [("https://upload.example/new", "")]
    assert posted, "a new session should have been requested"
    assert sent[0]["Content-Range"] == "bytes 0-99/100"


def test_a_session_that_is_gone_starts_a_new_one(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """YouTube saying 404 means the session has expired, not a blip."""
    file = tmp_path / "clip.mp4"
    file.write_bytes(b"x" * 100)

    def fake_post(url: str, **kwargs: Any) -> _Response:
        return _Response(200, headers={"location": "https://upload.example/new"})

    def fake_put(url: str, **kwargs: Any) -> _Response:
        if kwargs["headers"].get("Content-Range", "").endswith("*/100"):
            return _Response(404)
        return _Response(200, body={"id": "vid-1"})

    monkeypatch.setattr(resumable.httpx, "post", fake_post)
    monkeypatch.setattr(resumable.httpx, "put", fake_put)
    monkeypatch.setattr(uploader.oauth, "access_token", lambda _=None, account_id=None: "token")

    sessions: list[tuple[str, str]] = []
    uploader.upload_video(
        config.load(),
        path=file,
        metadata=uploader.ClipMetadata(title="T", description="", tags=[]),
        privacy="private",
        made_for_kids=False,
        session_url="https://upload.example/old",
        bytes_sent=0,
        on_session=lambda url, expiry: sessions.append((url, expiry)),
    )

    assert sessions == [("https://upload.example/new", "")]


def test_a_session_url_must_be_secure(monkeypatch: pytest.MonkeyPatch) -> None:
    """A session URL that is not HTTPS would send the file in the clear."""
    monkeypatch.setattr(
        resumable.httpx,
        "post",
        lambda url, **kwargs: _Response(200, headers={"location": "http://upload.example/s"}),
    )

    with pytest.raises(ResumableError) as caught:
        resumable.create_session(
            url="https://upload.example/videos",
            token="token",
            metadata=uploader.ClipMetadata(title="T", description="", tags=[]),
            privacy="private",
            made_for_kids=False,
        )

    assert "secure" in str(caught.value)


# --------------------------------------------------------------------------
# The quota
# --------------------------------------------------------------------------


def test_the_quota_is_written_down_before_the_call(initialised_db: int) -> None:
    ledger = quota.reserve(quota.UPLOAD_UNITS)

    assert ledger.units_used == quota.UPLOAD_UNITS
    assert ledger.uploads_started == 1
    assert ledger.remaining() == quota.DAILY_LIMIT - quota.UPLOAD_UNITS


def test_the_quota_refuses_an_upload_that_would_not_fit(initialised_db: int) -> None:
    quota.reserve(quota.UPLOAD_UNITS * 6)

    with pytest.raises(quota.QuotaExceeded) as caught:
        quota.reserve(quota.UPLOAD_UNITS)

    assert caught.value.needed == quota.UPLOAD_UNITS
    assert caught.value.used == quota.UPLOAD_UNITS * 6


def test_a_refused_reservation_does_not_count(initialised_db: int) -> None:
    quota.reserve(quota.UPLOAD_UNITS * 6)

    with pytest.raises(quota.QuotaExceeded):
        quota.reserve(quota.UPLOAD_UNITS)

    # The refused call did not make the day's usage worse.
    assert quota.read().units_used == quota.UPLOAD_UNITS * 6


def test_a_finished_upload_is_counted(initialised_db: int) -> None:
    quota.reserve(quota.UPLOAD_UNITS)
    ledger = quota.record_upload_finished()

    assert ledger.uploads_finished == 1
    assert ledger.uploads_started == 1


def test_the_read_back_costs_a_unit(initialised_db: int) -> None:
    ledger = quota.record_read()

    assert ledger.units_used == quota.READ_UNITS


# --------------------------------------------------------------------------
# The backoff
# --------------------------------------------------------------------------


def test_the_delay_grows_with_the_attempts() -> None:
    first = backoff.next_delay_s(1, jitter=False)
    second = backoff.next_delay_s(2, jitter=False)
    third = backoff.next_delay_s(3, jitter=False)

    assert first == 30.0
    assert second == 60.0
    assert third == 120.0


def test_the_delay_is_capped() -> None:
    assert backoff.next_delay_s(30, jitter=False) == backoff.MAX_DELAY_S


def test_the_delay_has_a_little_jitter() -> None:
    """Two uploads that failed together should not come back together."""
    delays = {backoff.next_delay_s(3) for _ in range(20)}

    assert len(delays) > 1


def test_a_row_that_is_not_due_is_skipped(initialised_db: int) -> None:
    source = Source(id=new_id(), type="upload", path="C:/s.mp4", title="s", duration_s=1.0)
    store.create_source(source)
    job = Job(id=new_id(), source_id=source.id, status="done")
    store.create_job(job)
    clip = Clip(id=new_id(), job_id=job.id, start_s=0.0, end_s=1.0, rank=1)
    store.replace_clips(job.id, [clip])
    export = Export(id=new_id(), clip_id=clip.id, path="C:/out.mp4")
    store.create_export(export)

    waiting = store.create_upload(
        YouTubeUpload(
            id=new_id(),
            export_id=export.id,
            clip_id=clip.id,
            status="pending",
            next_attempt_at="2099-01-01T00:00:00+00:00",
        )
    )
    due = store.create_upload(
        YouTubeUpload(
            id=new_id(),
            export_id=export.id,
            clip_id=clip.id,
            channel_row_id="other",
            status="pending",
        )
    )

    picked = store.next_pending_upload()

    assert picked is not None
    assert picked.id == due.id
    assert picked.id != waiting.id


def test_the_worker_backs_off_after_a_transient_failure(
    initialised_db: int, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A dropped connection is retried later, not in a tight loop."""
    import asyncio

    from autoclip.youtube import queue as queue_module

    source = Source(id=new_id(), type="upload", path="C:/s.mp4", title="s", duration_s=1.0)
    store.create_source(source)
    job = Job(id=new_id(), source_id=source.id, status="done")
    store.create_job(job)
    clip = Clip(id=new_id(), job_id=job.id, start_s=0.0, end_s=1.0, rank=1)
    store.replace_clips(job.id, [clip])
    export = Export(id=new_id(), clip_id=clip.id, path="C:/out.mp4")
    store.create_export(export)
    row = store.create_upload(
        YouTubeUpload(id=new_id(), export_id=export.id, clip_id=clip.id, status="pending")
    )

    async def boom(upload, settings=None):  # noqa: ANN001
        raise uploader.YouTubeError("the connection dropped", transient=True)

    monkeypatch.setattr(queue_module.uploads, "process_upload", boom)

    asyncio.run(queue_module.UploadQueue()._run(row.id))

    fresh = store.get_upload(row.id)
    assert fresh is not None
    # The row went back to pending with a time in the future, not failed.
    assert fresh.status == "pending"
    assert fresh.attempts == 1
    assert fresh.next_attempt_at
    assert fresh.error == "the connection dropped"


def test_a_permanent_failure_is_not_retried(
    initialised_db: int, monkeypatch: pytest.MonkeyPatch
) -> None:
    import asyncio

    from autoclip.youtube import queue as queue_module

    source = Source(id=new_id(), type="upload", path="C:/s.mp4", title="s", duration_s=1.0)
    store.create_source(source)
    job = Job(id=new_id(), source_id=source.id, status="done")
    store.create_job(job)
    clip = Clip(id=new_id(), job_id=job.id, start_s=0.0, end_s=1.0, rank=1)
    store.replace_clips(job.id, [clip])
    export = Export(id=new_id(), clip_id=clip.id, path="C:/out.mp4")
    store.create_export(export)
    row = store.create_upload(
        YouTubeUpload(id=new_id(), export_id=export.id, clip_id=clip.id, status="pending")
    )

    async def boom(upload, settings=None):  # noqa: ANN001
        raise uploader.YouTubeError("the file is malformed")

    monkeypatch.setattr(queue_module.uploads, "process_upload", boom)

    asyncio.run(queue_module.UploadQueue()._run(row.id))

    fresh = store.get_upload(row.id)
    assert fresh is not None
    assert fresh.status == "failed"
    assert fresh.next_attempt_at == ""


# --------------------------------------------------------------------------
# The API
# --------------------------------------------------------------------------


def test_the_upload_endpoint_reports_the_progress(client, initialised_db: int) -> None:
    source = Source(id=new_id(), type="upload", path="C:/s.mp4", title="s", duration_s=1.0)
    store.create_source(source)
    job = Job(id=new_id(), source_id=source.id, status="done")
    store.create_job(job)
    clip = Clip(id=new_id(), job_id=job.id, start_s=0.0, end_s=1.0, rank=1)
    store.replace_clips(job.id, [clip])
    export = Export(id=new_id(), clip_id=clip.id, path="C:/out.mp4")
    store.create_export(export)
    row = store.create_upload(
        YouTubeUpload(id=new_id(), export_id=export.id, clip_id=clip.id, status="uploading")
    )
    store.update_upload(row.id, bytes_sent=250, total_bytes=1000)

    body = client.get(f"/api/youtube/uploads/{row.id}").json()

    assert body["bytes_sent"] == 250
    assert body["total_bytes"] == 1000
    assert body["progress_percent"] == 25


def test_the_quota_endpoint_reports_the_day(client, initialised_db: int) -> None:
    quota.reserve(quota.UPLOAD_UNITS)

    body = client.get("/api/youtube/quota").json()

    assert body["units_used"] == quota.UPLOAD_UNITS
    assert body["remaining"] == quota.DAILY_LIMIT - quota.UPLOAD_UNITS
    assert "refresh" not in json.dumps(body).lower()
