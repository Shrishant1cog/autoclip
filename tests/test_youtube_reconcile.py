"""Reconciling an upload that may have succeeded anyway.

An upload can succeed and the answer can be lost: the last chunk
arrives, YouTube creates the video, and the connection drops before the
response is read. The row says "failed" while YouTube has the video.

These tests cover what must and must not happen then:

* a session that says the upload is finished is a **confirmation**,
  and nothing is sent again,
* a title match on the channel is **evidence**, and it never marks the
  upload published on its own,
* an upload that cannot be settled waits for the owner instead of
  being retried into a duplicate,
* and the owner has a way out: confirm it, or send it again.
"""

from __future__ import annotations

import asyncio
from collections.abc import Iterator
from pathlib import Path
from typing import Any

import pytest
from autoclip import app as app_module
from autoclip import config
from autoclip.app import create_app
from autoclip.db import store
from autoclip.db.models import Clip, Export, Job, Source, YouTubeUpload, new_id
from autoclip.youtube import accounts as accounts_store
from autoclip.youtube import reconcile, uploader, uploads
from fastapi.testclient import TestClient

# --------------------------------------------------------------------------
# Fixtures
# --------------------------------------------------------------------------


@pytest.fixture
def client(autoclip_home: Path, monkeypatch: pytest.MonkeyPatch) -> Iterator[TestClient]:
    monkeypatch.setenv(app_module.ENV_NO_WORKER, "1")
    with TestClient(create_app()) as test_client:
        yield test_client


def _seed_clip() -> tuple[Source, Job, Clip]:
    source = Source(
        id=new_id(), type="upload", path="C:/source.mp4", title="source", duration_s=30.0
    )
    store.create_source(source)
    job = Job(id=new_id(), source_id=source.id, status="done")
    store.create_job(job)
    clip = Clip(id=new_id(), job_id=job.id, start_s=0.0, end_s=10.0, rank=1)
    store.replace_clips(job.id, [clip])
    return source, job, clip


def _channel(label: str = "Primary", **kwargs: Any) -> dict:
    account = accounts_store.create_account(label=label)
    return accounts_store.add_channel(
        account["id"],
        {"id": f"UC_{label}", "title": label, "url": ""},
        made_for_kids="false",
        **kwargs,
    )


def _upload_row(channel: dict | None = None, **kwargs: Any) -> YouTubeUpload:
    _, _, clip = _seed_clip()
    export = Export(id=new_id(), clip_id=clip.id, path="C:/out.mp4")
    store.create_export(export)
    return store.create_upload(
        YouTubeUpload(
            id=new_id(),
            export_id=export.id,
            clip_id=clip.id,
            channel_row_id=(channel or {}).get("id", ""),
            **kwargs,
        )
    )


# --------------------------------------------------------------------------
# The session is YouTube's own record, so it confirms
# --------------------------------------------------------------------------


class _Response:
    def __init__(self, status: int, body: dict | None = None, headers: dict | None = None) -> None:
        self.status_code = status
        self._body = body or {}
        self.headers = headers or {}
        self.text = ""

    def json(self) -> dict:
        return self._body

    def raise_for_status(self) -> None:
        if self.status_code >= 400:
            raise reconcile.httpx.HTTPError(f"HTTP {self.status_code}")


def test_a_finished_session_confirms_the_upload(
    initialised_db: int, monkeypatch: pytest.MonkeyPatch
) -> None:
    row = _upload_row(
        title="A clip",
        session_url="https://upload.example/s",
        total_bytes=100,
    )

    monkeypatch.setattr(
        reconcile.oauth,
        "access_token",
        lambda _=None, account_id=None: "token",
    )
    monkeypatch.setattr(
        reconcile.resumable.httpx,
        "put",
        lambda url, **kwargs: _Response(
            200, body={"id": "vid-1", "status": {"privacyStatus": "private"}}
        ),
    )

    outcome = reconcile.reconcile(row, config.load(), channel_id="UC_Primary")

    assert outcome.status == reconcile.CONFIRMED
    assert outcome.confirmed is True
    assert outcome.video_id == "vid-1"
    assert outcome.actual_privacy == "private"
    assert outcome.method == "session"


def test_an_unfinished_session_says_the_upload_did_not_happen(
    initialised_db: int, monkeypatch: pytest.MonkeyPatch
) -> None:
    row = _upload_row(session_url="https://upload.example/s", total_bytes=100)

    monkeypatch.setattr(
        reconcile.oauth,
        "access_token",
        lambda _=None, account_id=None: "token",
    )
    monkeypatch.setattr(
        reconcile.resumable.httpx,
        "put",
        lambda url, **kwargs: _Response(308, headers={"range": "bytes=0-49"}),
    )

    outcome = reconcile.reconcile(row, config.load(), channel_id="UC_Primary")

    assert outcome.status == reconcile.NOT_UPLOADED
    assert outcome.needs_owner is False
    assert "50 of 100" in outcome.detail


def test_a_gone_session_falls_through_to_the_channel(
    initialised_db: int, monkeypatch: pytest.MonkeyPatch
) -> None:
    row = _upload_row(title="A clip", session_url="https://upload.example/s")

    monkeypatch.setattr(
        reconcile.oauth,
        "access_token",
        lambda _=None, account_id=None: "token",
    )
    monkeypatch.setattr(
        reconcile.resumable.httpx,
        "put",
        lambda url, **kwargs: _Response(404),
    )
    monkeypatch.setattr(
        reconcile,
        "_via_channel",
        lambda *a, **k: reconcile.Reconciliation(
            status=reconcile.EVIDENCE, video_id="vid-9", method="channel"
        ),
    )

    outcome = reconcile.reconcile(row, config.load(), channel_id="UC_Primary")

    assert outcome.method == "channel"
    assert outcome.status == reconcile.EVIDENCE


# --------------------------------------------------------------------------
# A title match is evidence, not proof
# --------------------------------------------------------------------------


def _channel_lookup(
    monkeypatch: pytest.MonkeyPatch,
    uploads_list: list[dict[str, Any]],
    playlist_id: str = "UU_Primary",
) -> None:
    monkeypatch.setattr(
        reconcile.oauth,
        "access_token",
        lambda _=None, account_id=None: "token",
    )

    def fake_get(url: str, **kwargs: Any) -> _Response:
        if "channels" in url:
            return _Response(
                200,
                body={
                    "items": [{"contentDetails": {"relatedPlaylists": {"uploads": playlist_id}}}]
                },
            )
        return _Response(
            200,
            body={
                "items": [
                    {
                        "snippet": {
                            "title": item["title"],
                            "publishedAt": item.get("published_at", "2099-01-01T00:00:00+00:00"),
                            "resourceId": {"videoId": item["video_id"]},
                        }
                    }
                    for item in uploads_list
                ]
            },
        )

    monkeypatch.setattr(reconcile.httpx, "get", fake_get)


def test_a_matching_title_is_only_evidence(
    initialised_db: int, monkeypatch: pytest.MonkeyPatch
) -> None:
    row = _upload_row(title="A clip")
    _channel_lookup(monkeypatch, [{"title": "A clip", "video_id": "vid-2"}])

    outcome = reconcile.reconcile(row, config.load(), channel_id="UC_Primary")

    assert outcome.status == reconcile.EVIDENCE
    assert outcome.confirmed is False
    assert outcome.needs_owner is True
    assert "evidence, not proof" in outcome.detail


def test_several_matching_titles_are_still_only_evidence(
    initialised_db: int, monkeypatch: pytest.MonkeyPatch
) -> None:
    row = _upload_row(title="A clip")
    _channel_lookup(
        monkeypatch,
        [
            {"title": "A clip", "video_id": "vid-2"},
            {"title": "A clip", "video_id": "vid-3"},
        ],
    )

    outcome = reconcile.reconcile(row, config.load(), channel_id="UC_Primary")

    assert outcome.status == reconcile.EVIDENCE
    assert len(outcome.candidates) == 2
    assert "2 videos" in outcome.detail


def test_a_different_title_is_not_a_candidate(
    initialised_db: int, monkeypatch: pytest.MonkeyPatch
) -> None:
    row = _upload_row(title="A clip")
    _channel_lookup(monkeypatch, [{"title": "Something else", "video_id": "vid-2"}])

    outcome = reconcile.reconcile(row, config.load(), channel_id="UC_Primary")

    assert outcome.status == reconcile.NOT_UPLOADED


def test_a_video_from_before_the_upload_is_not_a_candidate(
    initialised_db: int, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A clip with the same title from last week is not this upload."""
    row = _upload_row(title="A clip")
    _channel_lookup(
        monkeypatch,
        [{"title": "A clip", "video_id": "vid-2", "published_at": "2000-01-01T00:00:00+00:00"}],
    )

    outcome = reconcile.reconcile(row, config.load(), channel_id="UC_Primary")

    assert outcome.status == reconcile.NOT_UPLOADED


def test_the_channel_suffix_is_part_of_the_expected_title(
    initialised_db: int, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The suffix is added to the title just before the upload."""
    row = _upload_row(title="A clip")
    _channel_lookup(monkeypatch, [{"title": "A clip Official", "video_id": "vid-2"}])

    outcome = reconcile.reconcile(
        row, config.load(), channel_id="UC_Primary", title_suffix="Official"
    )

    assert outcome.status == reconcile.EVIDENCE


def test_a_failed_lookup_does_not_claim_the_upload_did_not_happen(
    initialised_db: int, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A lookup that failed says nothing about the upload."""
    row = _upload_row(title="A clip")

    monkeypatch.setattr(
        reconcile.oauth,
        "access_token",
        lambda _=None, account_id=None: "token",
    )

    def boom(url: str, **kwargs: Any) -> _Response:
        raise reconcile.httpx.HTTPError("network down")

    monkeypatch.setattr(reconcile.httpx, "get", boom)

    outcome = reconcile.reconcile(row, config.load(), channel_id="UC_Primary")

    assert outcome.status == reconcile.UNKNOWN
    assert outcome.needs_owner is True


def test_no_channel_means_the_upload_cannot_be_checked(
    initialised_db: int, monkeypatch: pytest.MonkeyPatch
) -> None:
    row = _upload_row(title="A clip")
    monkeypatch.setattr(
        reconcile.oauth,
        "access_token",
        lambda _=None, account_id=None: "token",
    )

    outcome = reconcile.reconcile(row, config.load(), channel_id="")

    assert outcome.status == reconcile.UNKNOWN
    assert outcome.needs_owner is True


# --------------------------------------------------------------------------
# The worker settles it before sending anything again
# --------------------------------------------------------------------------


def test_a_confirmed_upload_is_not_sent_again(
    initialised_db: int, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """The file that already reached YouTube is not uploaded a second time."""
    channel = _channel()
    row = _upload_row(
        channel,
        title="A clip",
        description="A description",
        session_url="https://upload.example/s",
        attempts=1,
    )

    sent: list[dict] = []

    def fake_upload(settings, **kwargs):  # noqa: ANN001
        sent.append(kwargs)
        return "vid-new"

    monkeypatch.setattr(uploader, "upload_video", fake_upload)
    monkeypatch.setattr(
        reconcile.oauth,
        "access_token",
        lambda _=None, account_id=None: "token",
    )
    monkeypatch.setattr(
        reconcile.resumable.httpx,
        "put",
        lambda url, **kwargs: _Response(200, body={"id": "vid-1"}),
    )
    monkeypatch.setattr(Path, "is_file", lambda self: True)

    video_id = asyncio.run(uploads.process_upload(row, config.load()))

    assert video_id == "vid-1"
    assert sent == [], "the file must not be sent again"

    fresh = store.get_upload(row.id)
    assert fresh is not None
    assert fresh.video_id == "vid-1"
    assert fresh.reconcile_status == reconcile.CONFIRMED


def test_an_unsettled_upload_waits_for_the_owner(
    initialised_db: int, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Evidence is not confirmation, so the upload is not sent again."""
    channel = _channel()
    row = _upload_row(
        channel,
        title="A clip",
        description="A description",
        session_url="https://upload.example/s",
        attempts=1,
    )

    sent: list[dict] = []
    monkeypatch.setattr(uploader, "upload_video", lambda settings, **kwargs: sent.append(kwargs))
    monkeypatch.setattr(
        reconcile.oauth,
        "access_token",
        lambda _=None, account_id=None: "token",
    )
    # The session is gone, so the channel is asked instead.
    monkeypatch.setattr(
        reconcile.resumable.httpx,
        "put",
        lambda url, **kwargs: _Response(404),
    )
    _channel_lookup(monkeypatch, [{"title": "A clip", "video_id": "vid-2"}])
    monkeypatch.setattr(Path, "is_file", lambda self: True)

    with pytest.raises(uploader.YouTubeError) as caught:
        asyncio.run(uploads.process_upload(row, config.load()))

    assert caught.value.needs_reconciliation is True
    assert sent == [], "the file must not be sent again"

    fresh = store.get_upload(row.id)
    assert fresh is not None
    assert fresh.reconcile_status == reconcile.EVIDENCE


def test_a_live_session_says_the_upload_did_not_happen_without_asking_the_channel(
    initialised_db: int, monkeypatch: pytest.MonkeyPatch
) -> None:
    """YouTube's own word about the transfer needs no second opinion."""
    channel = _channel()
    row = _upload_row(
        channel,
        title="A clip",
        description="A description",
        session_url="https://upload.example/s",
        attempts=1,
        total_bytes=100,
    )

    asked: list[str] = []

    def spy(url: str, **kwargs: Any) -> _Response:
        asked.append(url)
        return _Response(200, body={"items": []})

    monkeypatch.setattr(reconcile.httpx, "get", spy)
    monkeypatch.setattr(
        reconcile.oauth,
        "access_token",
        lambda _=None, account_id=None: "token",
    )
    monkeypatch.setattr(
        reconcile.resumable.httpx,
        "put",
        lambda url, **kwargs: _Response(308, headers={"range": "bytes=0-49"}),
    )
    monkeypatch.setattr(Path, "is_file", lambda self: True)

    def fake_upload(settings, **kwargs):  # noqa: ANN001
        return "vid-new"

    monkeypatch.setattr(uploader, "upload_video", fake_upload)

    video_id = asyncio.run(uploads.process_upload(row, config.load()))

    assert video_id == "vid-new"
    assert not [url for url in asked if "channels" in url or "playlistItems" in url], (
        "the session already answered, so the channel need not be asked"
    )


def test_the_queue_leaves_an_unsettled_upload_alone(
    initialised_db: int, monkeypatch: pytest.MonkeyPatch
) -> None:
    """It is not marked failed and it is not retried on its own."""
    from autoclip.youtube import queue as queue_module

    row = _upload_row(status="pending")

    async def boom(upload, settings=None):  # noqa: ANN001
        raise uploader.YouTubeError(
            "It is not clear whether this upload reached YouTube.",
            needs_reconciliation=True,
        )

    monkeypatch.setattr(queue_module.uploads, "process_upload", boom)

    asyncio.run(queue_module.UploadQueue()._run(row.id))

    fresh = store.get_upload(row.id)
    assert fresh is not None
    assert fresh.status == "needs_reconciliation"
    assert fresh.next_attempt_at == ""


# --------------------------------------------------------------------------
# The owner has a way out
# --------------------------------------------------------------------------


def test_the_owner_can_confirm_a_video_that_is_there(
    initialised_db: int, monkeypatch: pytest.MonkeyPatch
) -> None:
    channel = _channel()
    row = _upload_row(channel, status="needs_reconciliation")

    monkeypatch.setattr(uploader.oauth, "access_token", lambda _=None, account_id=None: "token")
    monkeypatch.setattr(
        uploader.httpx,
        "get",
        lambda url, **kwargs: _Response(
            200,
            body={
                "items": [
                    {
                        "status": {"privacyStatus": "public"},
                        "snippet": {"channelId": "UC_Primary", "title": "A clip"},
                    }
                ]
            },
        ),
    )

    fresh = uploads.confirm_upload(row.id, "vid-42", config.load())

    assert fresh is not None
    assert fresh.status == "done"
    assert fresh.video_id == "vid-42"
    assert fresh.actual_privacy == "public"
    assert fresh.reconcile_status == "confirmed_by_owner"


def test_confirming_a_video_that_is_not_there_is_refused(
    initialised_db: int, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The owner's word is checked against YouTube."""
    channel = _channel()
    row = _upload_row(channel, status="needs_reconciliation")

    monkeypatch.setattr(uploader.oauth, "access_token", lambda _=None, account_id=None: "token")
    monkeypatch.setattr(
        uploader.httpx, "get", lambda url, **kwargs: _Response(200, body={"items": []})
    )

    with pytest.raises(uploader.YouTubeError):
        uploads.confirm_upload(row.id, "vid-42", config.load())

    fresh = store.get_upload(row.id)
    assert fresh is not None
    assert fresh.status == "needs_reconciliation"
    assert fresh.video_id is None


def test_the_owner_can_send_it_again_after_checking(
    initialised_db: int,
) -> None:
    """A retry of an unsettled row records that the owner decided."""
    row = _upload_row(status="needs_reconciliation", session_url="https://upload.example/s")

    retried = uploads.retry_upload(row.id, config.load())

    assert retried is not None
    assert retried.status == "pending"
    assert retried.reconcile_status == "owner_retried"
    assert retried.session_url == ""
    assert retried.bytes_sent == 0


def test_an_owner_retry_is_not_reconciled_again(
    initialised_db: int, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The owner has settled it; AutoClip does not look again."""
    channel = _channel()
    row = _upload_row(
        channel,
        title="A clip",
        description="A description",
        session_url="https://upload.example/s",
        attempts=1,
        reconcile_status="owner_retried",
    )

    looked: list[str] = []

    def spy(*args: Any, **kwargs: Any) -> reconcile.Reconciliation:
        looked.append("called")
        return reconcile.Reconciliation(status=reconcile.EVIDENCE, video_id="vid-2")

    monkeypatch.setattr(reconcile, "reconcile", spy)
    monkeypatch.setattr(Path, "is_file", lambda self: True)

    def fake_upload(settings, **kwargs):  # noqa: ANN001
        return "vid-new"

    monkeypatch.setattr(uploader, "upload_video", fake_upload)

    video_id = asyncio.run(uploads.process_upload(row, config.load()))

    assert video_id == "vid-new"
    assert looked == [], "the owner has already settled this"


# --------------------------------------------------------------------------
# The API
# --------------------------------------------------------------------------


def test_the_upload_endpoint_reports_the_reconciliation(
    client: TestClient, initialised_db: int
) -> None:
    row = _upload_row(status="needs_reconciliation")
    store.update_upload(
        row.id,
        reconcile_status="evidence",
        reconcile_detail="There is a video with the same title.",
        reconciled_at="2026-01-01T00:00:00+00:00",
    )

    body = client.get(f"/api/youtube/uploads/{row.id}").json()

    assert body["needs_reconciliation"] is True
    assert body["reconcile_status"] == "evidence"
    assert "same title" in body["reconcile_detail"]


def test_the_confirm_endpoint_records_a_verified_video(
    client: TestClient, initialised_db: int, monkeypatch: pytest.MonkeyPatch
) -> None:
    channel = _channel()
    row = _upload_row(channel, status="needs_reconciliation")

    monkeypatch.setattr(uploader.oauth, "access_token", lambda _=None, account_id=None: "token")
    monkeypatch.setattr(
        uploader.httpx,
        "get",
        lambda url, **kwargs: _Response(
            200,
            body={
                "items": [
                    {
                        "status": {"privacyStatus": "unlisted"},
                        "snippet": {"channelId": "UC_Primary"},
                    }
                ]
            },
        ),
    )

    response = client.put(f"/api/youtube/uploads/{row.id}/confirm", json={"video_id": "vid-42"})

    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "done"
    assert body["video_id"] == "vid-42"
    assert body["actual_privacy"] == "unlisted"


def test_the_confirm_endpoint_refuses_an_unverifiable_video(
    client: TestClient, initialised_db: int, monkeypatch: pytest.MonkeyPatch
) -> None:
    channel = _channel()
    row = _upload_row(channel, status="needs_reconciliation")

    monkeypatch.setattr(uploader.oauth, "access_token", lambda _=None, account_id=None: "token")
    monkeypatch.setattr(
        uploader.httpx, "get", lambda url, **kwargs: _Response(200, body={"items": []})
    )

    response = client.put(f"/api/youtube/uploads/{row.id}/confirm", json={"video_id": "vid-42"})

    assert response.status_code == 409
    fresh = store.get_upload(row.id)
    assert fresh is not None
    assert fresh.status == "needs_reconciliation"


def test_the_confirm_endpoint_needs_a_video_id(client: TestClient, initialised_db: int) -> None:
    row = _upload_row(status="needs_reconciliation")

    response = client.put(f"/api/youtube/uploads/{row.id}/confirm", json={"video_id": ""})

    assert response.status_code == 400


def test_an_unknown_upload_is_a_404(client: TestClient, initialised_db: int) -> None:
    response = client.put("/api/youtube/uploads/missing/confirm", json={"video_id": "x"})
    assert response.status_code == 404
