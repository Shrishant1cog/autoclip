"""The publishing policy: where a clip goes, who it is for, and how it is seen.

These tests cover the decisions that must not be made by accident:

* the audience declaration is the owner's, and an unanswered one stops
  the upload rather than being guessed,
* the privacy asked for is recorded and never changed by a retry,
* one account's policy never leaks into another's,
* and what YouTube actually did is read back, so "published" is never
  claimed for a video that came back private.
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
from autoclip.youtube import accounts as accounts_store
from autoclip.youtube import policy, uploader, uploads
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
        id=new_id(), type="upload", path="C:/source.mp4", title="source", duration_s=120.0
    )
    store.create_source(source)
    job = Job(id=new_id(), source_id=source.id, status="done")
    store.create_job(job)
    clip = Clip(id=new_id(), job_id=job.id, start_s=1.0, end_s=20.0, rank=1)
    store.replace_clips(job.id, [clip])
    return source, job, clip


def _channel(label: str = "Primary", *, made_for_kids: str = "false", **kwargs: Any) -> dict:
    account = accounts_store.create_account(label=label)
    return accounts_store.add_channel(
        account["id"],
        {"id": f"UC_{label}", "title": label, "url": ""},
        made_for_kids=made_for_kids,
        **kwargs,
    )


def _upload_row(channel: dict, **kwargs: Any) -> YouTubeUpload:
    _, _, clip = _seed_clip()
    export = Export(id=new_id(), clip_id=clip.id, path="C:/out.mp4")
    store.create_export(export)
    return store.create_upload(
        YouTubeUpload(
            id=new_id(),
            export_id=export.id,
            clip_id=clip.id,
            channel_row_id=channel["id"],
            **kwargs,
        )
    )


# --------------------------------------------------------------------------
# The audience declaration is the owner's
# --------------------------------------------------------------------------


def test_an_unanswered_audience_stops_the_upload(initialised_db: int) -> None:
    channel = _channel(made_for_kids="")
    settings = config.Settings()

    with pytest.raises(policy.AudienceUndecided) as caught:
        policy.resolve(channel, settings)

    # The refusal says what to do about it, not just that it failed.
    assert "not been answered" in str(caught.value)
    assert "Channels page" in str(caught.value)


def test_the_audience_is_read_as_three_states_and_not_two(initialised_db: int) -> None:
    """'Not decided' and 'no' are different answers, and only one blocks."""
    settings = config.Settings()

    assert policy.resolve(None, settings, require_audience=False).made_for_kids_state == ""

    settings.youtube.made_for_kids = "false"
    assert policy.resolve(None, settings).made_for_kids_state == "false"
    assert policy.resolve(None, settings).made_for_kids is False

    settings.youtube.made_for_kids = "true"
    assert policy.resolve(None, settings).made_for_kids_state == "true"
    assert policy.resolve(None, settings).made_for_kids is True


def test_the_channel_answer_is_used_for_its_own_uploads(initialised_db: int) -> None:
    channel = _channel(made_for_kids="true")
    settings = config.Settings()

    resolved = policy.resolve(channel, settings)

    assert resolved.made_for_kids is True
    assert resolved.destination_channel_id == "UC_Primary"


def test_one_upload_answer_beats_the_channel_answer(initialised_db: int) -> None:
    """An answer about one upload is more specific than one about a channel."""
    channel = _channel(made_for_kids="true")
    settings = config.Settings()

    resolved = policy.resolve(channel, settings, audience_override="false")

    assert resolved.made_for_kids is False
    assert resolved.made_for_kids_state == "false"


def test_the_upload_sends_the_declaration_rather_than_a_default(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The declaration is sent as given, not hard-coded to "no"."""
    file = tmp_path / "clip.mp4"
    file.write_bytes(b"video-bytes")
    settings = config.load()
    monkeypatch.setattr(uploader.oauth, "access_token", lambda _=None, account_id=None: "token")

    bodies: list[dict] = []

    class _Response:
        status_code = 200
        headers = {"location": "https://upload.example/session"}

        def json(self) -> dict:
            return {"id": "abc123"}

    def fake_post(url: str, **kwargs: Any) -> _Response:
        bodies.append(kwargs["json"])
        return _Response()

    monkeypatch.setattr(uploader.httpx, "post", fake_post)
    monkeypatch.setattr(uploader.httpx, "put", lambda url, **kwargs: _Response())

    uploader.upload_video(
        settings,
        path=file,
        metadata=uploader.ClipMetadata(title="T", description="", tags=[]),
        privacy="public",
        made_for_kids=True,
    )

    assert bodies[0]["status"]["selfDeclaredMadeForKids"] is True


# --------------------------------------------------------------------------
# The privacy is never changed silently
# --------------------------------------------------------------------------


def test_a_new_channel_starts_private(initialised_db: int) -> None:
    """The original default was public, which published on the owner's behalf."""
    channel = _channel()

    assert channel["privacy"] == "private"


def test_a_fresh_install_starts_private(initialised_db: int) -> None:
    assert config.Settings().youtube.privacy == "private"


def test_a_stored_privacy_is_left_alone(initialised_db: int) -> None:
    """Changing the default does not change what the owner already chose."""
    settings = config.Settings()
    settings.youtube.privacy = "public"
    config.save(settings)

    assert config.load().youtube.privacy == "public"


def test_the_requested_privacy_is_recorded_before_the_transfer(
    initialised_db: int, monkeypatch: pytest.MonkeyPatch
) -> None:
    channel = _channel(made_for_kids="false")
    row = _upload_row(channel, privacy="unlisted", title="Title", description="Description")

    monkeypatch.setattr(Path, "is_file", lambda self: True)
    monkeypatch.setattr(uploads, "_thumbnail_for", lambda *a, **k: None)

    recorded: list[dict] = []
    monkeypatch.setattr(
        uploads.store,
        "update_upload",
        lambda upload_id, **kwargs: recorded.append(kwargs),
    )

    def fake_upload(settings, **kwargs):  # noqa: ANN001
        # The row is already written by the time the transfer starts.
        assert any(item.get("requested_privacy") == "unlisted" for item in recorded)
        return "vid-1"

    monkeypatch.setattr(uploader, "upload_video", fake_upload)

    import asyncio

    asyncio.run(uploads.process_upload(row, config.load()))

    assert any(item.get("made_for_kids") == "false" for item in recorded)
    assert any(item.get("destination_channel_id") == "UC_Primary" for item in recorded)


def test_a_retry_does_not_change_the_privacy(initialised_db: int) -> None:
    """The row's own privacy survives the retry."""
    channel = _channel(made_for_kids="false")
    row = _upload_row(channel, privacy="unlisted", status="failed")

    accounts_store.update_channel(channel["id"], privacy="public")
    settings = config.Settings()
    settings.youtube.privacy = "public"

    retried = uploads.retry_upload(row.id, settings)

    assert retried is not None
    assert retried.privacy == "unlisted"


def test_the_upload_does_not_change_the_global_privacy(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Uploading to a private channel must not make the global setting private."""
    file = tmp_path / "clip.mp4"
    file.write_bytes(b"video-bytes")
    settings = config.load()
    settings.youtube.privacy = "public"
    monkeypatch.setattr(uploader.oauth, "access_token", lambda _=None, account_id=None: "token")

    class _Response:
        status_code = 200
        headers = {"location": "https://upload.example/session"}

        def json(self) -> dict:
            return {"id": "abc123"}

    monkeypatch.setattr(uploader.httpx, "post", lambda url, **kwargs: _Response())
    monkeypatch.setattr(uploader.httpx, "put", lambda url, **kwargs: _Response())

    uploader.upload_video(
        settings,
        path=file,
        metadata=uploader.ClipMetadata(title="T", description="", tags=[]),
        privacy="private",
        made_for_kids=False,
    )

    assert settings.youtube.privacy == "public"


# --------------------------------------------------------------------------
# One account's policy never leaks into another's
# --------------------------------------------------------------------------


def test_a_second_account_does_not_inherit_the_first_policy(initialised_db: int) -> None:
    first = _channel("First", made_for_kids="true")
    second = _channel("Second", made_for_kids="false")

    settings = config.Settings()

    assert policy.resolve(first, settings).made_for_kids is True
    assert policy.resolve(second, settings).made_for_kids is False
    assert policy.resolve(first, settings).destination_channel_id == "UC_First"
    assert policy.resolve(second, settings).destination_channel_id == "UC_Second"


def test_the_global_answer_does_not_override_a_channel_answer(initialised_db: int) -> None:
    channel = _channel(made_for_kids="false")
    settings = config.Settings()
    settings.youtube.made_for_kids = "true"

    assert policy.resolve(channel, settings).made_for_kids is False


# --------------------------------------------------------------------------
# What YouTube actually did
# --------------------------------------------------------------------------


def test_the_read_back_reports_the_actual_privacy(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(uploader.oauth, "access_token", lambda _=None, account_id=None: "token")

    class _Response:
        status_code = 200

        def json(self) -> dict:
            return {
                "items": [
                    {
                        "status": {"privacyStatus": "private"},
                        "snippet": {"channelId": "UC_Primary", "title": "Title"},
                    }
                ]
            }

    monkeypatch.setattr(uploader.httpx, "get", lambda url, **kwargs: _Response())

    outcome = uploader.read_back(config.load(), video_id="vid-1")

    assert outcome.found is True
    assert outcome.actual_privacy == "private"
    assert outcome.channel_id == "UC_Primary"


def test_an_uploaded_but_private_video_is_not_reported_as_published(
    initialised_db: int, monkeypatch: pytest.MonkeyPatch
) -> None:
    """YouTube forces a public video private on an un-audited API project."""
    from autoclip.api.schemas import UploadOut

    row = _upload_row(_channel(made_for_kids="false"), privacy="public", status="done")
    store.update_upload(
        row.id,
        video_id="vid-1",
        requested_privacy="public",
        actual_privacy="private",
        destination_channel_id="UC_Primary",
    )

    fresh = store.get_upload(row.id)
    assert fresh is not None
    out = UploadOut.of(fresh)

    assert out.published_but_not_as_asked is True
    assert out.actual_privacy == "private"
    assert out.requested_privacy == "public"


def test_the_destination_is_compared_with_what_youtube_reports(
    initialised_db: int, monkeypatch: pytest.MonkeyPatch
) -> None:
    channel = _channel(made_for_kids="false")
    row = _upload_row(channel, privacy="public", title="Title", description="Description")

    monkeypatch.setattr(Path, "is_file", lambda self: True)
    monkeypatch.setattr(uploads, "_thumbnail_for", lambda *a, **k: None)
    monkeypatch.setattr(uploader, "upload_video", lambda settings, **kwargs: "vid-1")

    class _Response:
        status_code = 200

        def json(self) -> dict:
            return {
                "items": [
                    {
                        "status": {"privacyStatus": "public"},
                        "snippet": {"channelId": "UC_Primary"},
                    }
                ]
            }

    monkeypatch.setattr(uploader.oauth, "access_token", lambda _=None, account_id=None: "token")
    monkeypatch.setattr(uploader.httpx, "get", lambda url, **kwargs: _Response())

    import asyncio

    asyncio.run(uploads.process_upload(row, config.load()))

    fresh = store.get_upload(row.id)
    assert fresh is not None
    assert fresh.destination_channel_id == "UC_Primary"
    assert fresh.actual_privacy == "public"


def test_a_read_back_failure_does_not_fail_the_upload(
    initialised_db: int, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The upload happened; not being able to confirm it is not a failure."""
    channel = _channel(made_for_kids="false")
    row = _upload_row(channel, privacy="public", title="Title", description="Description")

    monkeypatch.setattr(Path, "is_file", lambda self: True)
    monkeypatch.setattr(uploads, "_thumbnail_for", lambda *a, **k: None)
    monkeypatch.setattr(uploader, "upload_video", lambda settings, **kwargs: "vid-1")

    def boom(url: str, **kwargs: Any):
        raise uploader.httpx.HTTPError("network down")

    monkeypatch.setattr(uploader.oauth, "access_token", lambda _=None, account_id=None: "token")
    monkeypatch.setattr(uploader.httpx, "get", boom)

    import asyncio

    video_id = asyncio.run(uploads.process_upload(row, config.load()))

    assert video_id == "vid-1"
    fresh = store.get_upload(row.id)
    assert fresh is not None
    # The actual privacy stays unknown rather than being invented.
    assert fresh.actual_privacy == ""


# --------------------------------------------------------------------------
# The API
# --------------------------------------------------------------------------


def test_the_policy_endpoint_reports_an_unanswered_audience(
    client: TestClient, initialised_db: int
) -> None:
    channel = _channel(made_for_kids="")

    body = client.get("/api/youtube/policy", params={"channel_row_id": channel["id"]}).json()

    assert body["audience_decided"] is False
    assert body["made_for_kids_state"] == ""
    assert [option["value"] for option in body["audience_options"]] == ["", "false", "true"]


def test_the_policy_endpoint_names_the_destination(client: TestClient, initialised_db: int) -> None:
    channel = _channel(made_for_kids="false")

    body = client.get("/api/youtube/policy", params={"channel_row_id": channel["id"]}).json()

    assert body["destination_channel_id"] == "UC_Primary"
    assert body["made_for_kids"] is False


def test_the_audience_can_be_answered_for_a_channel(
    client: TestClient, initialised_db: int
) -> None:
    channel = _channel(made_for_kids="")

    response = client.put(
        f"/api/youtube/accounts/channels/{channel['id']}",
        json={"made_for_kids": "false"},
    )

    assert response.status_code == 200
    assert response.json()["made_for_kids"] == "false"


def test_an_invalid_audience_is_refused(client: TestClient, initialised_db: int) -> None:
    channel = _channel(made_for_kids="false")

    response = client.put(
        f"/api/youtube/accounts/channels/{channel['id']}",
        json={"made_for_kids": "maybe"},
    )

    assert response.status_code == 422


def test_an_upload_can_be_edited_before_it_runs(client: TestClient, initialised_db: int) -> None:
    channel = _channel(made_for_kids="false")
    row = _upload_row(channel)

    response = client.put(
        f"/api/youtube/uploads/{row.id}",
        json={
            "title": "A better title",
            "privacy": "unlisted",
            "made_for_kids": "true",
        },
    )

    assert response.status_code == 200
    body = response.json()
    assert body["title"] == "A better title"
    assert body["privacy"] == "unlisted"
    assert body["made_for_kids"] == "true"


def test_an_upload_that_has_run_cannot_be_edited(client: TestClient, initialised_db: int) -> None:
    channel = _channel(made_for_kids="false")
    row = _upload_row(channel, status="done")

    response = client.put(f"/api/youtube/uploads/{row.id}", json={"title": "Too late"})

    assert response.status_code == 409


def test_an_unknown_upload_is_a_404(client: TestClient, initialised_db: int) -> None:
    assert client.get("/api/youtube/uploads/missing").status_code == 404
    assert client.put("/api/youtube/uploads/missing", json={"title": "x"}).status_code == 404


def test_the_status_endpoint_reports_the_audience(client: TestClient, initialised_db: int) -> None:
    body = client.get("/api/youtube/status").json()

    assert body["made_for_kids"] == ""
    assert body["privacy"] == "private"


def test_the_global_audience_can_be_answered(client: TestClient, initialised_db: int) -> None:
    response = client.post("/api/youtube/audience", json={"made_for_kids": "false"})

    assert response.status_code == 200
    assert response.json()["made_for_kids"] == "false"
    assert config.load().youtube.made_for_kids == "false"


# --------------------------------------------------------------------------
# Nothing sensitive leaks
# --------------------------------------------------------------------------


def test_the_upload_row_holds_no_secret(client: TestClient, initialised_db: int) -> None:
    channel = _channel(made_for_kids="false")
    row = _upload_row(channel)

    body = client.get(f"/api/youtube/uploads/{row.id}").json()

    assert "refresh" not in json.dumps(body).lower()
