"""Instagram Platform publishing.

These tests cover the parts of Meta's API that AutoClip depends on, using
Meta's own documented figures:

* the **error table** — every code Meta documents maps to the right
  decision, because a suspected-spam block and a dropped connection are
  both "the publish failed" but only one of them may be tried again;
* the **media specifications** — each documented Reel limit is measured
  against the real file, and the failing measurement is named;
* the **publishing sequence** — container, upload, status, publish,
  read-back, in Meta's order;
* the **publishing limit** — read from the API rather than hardcoded,
  because Meta's own documents disagree about it;
* **duplicate prevention** — Instagram has no idempotency key, so the
  guarantee has to be made locally;
* and **platform independence** — an Instagram failure cannot cancel a
  YouTube upload, and the reverse is also true.

Nothing here contacts Meta. Every network call is a double, and the live
path is recorded as Unverified (external) because no authorised Meta app,
token or professional account was supplied.
"""

from __future__ import annotations

import asyncio
import struct
from collections.abc import Iterator
from pathlib import Path
from typing import Any

import pytest
from autoclip import app as app_module
from autoclip import config
from autoclip.app import create_app
from autoclip.db import store
from autoclip.db.models import Clip, Export, Job, Source, new_id
from autoclip.instagram import accounts as accounts_store
from autoclip.instagram import media as media_module
from autoclip.instagram import oauth, publisher, uploads
from autoclip.instagram.errors import (
    InstagramError,
    OwnerActionRequired,
    translate_graph_error,
)
from autoclip.instagram.queue import InstagramUploadQueue
from fastapi.testclient import TestClient

# --------------------------------------------------------------------------
# Fixtures
# --------------------------------------------------------------------------


@pytest.fixture(autouse=True)
def _database(initialised_db: int) -> None:
    """Every test in this file touches the database."""
    assert initialised_db >= 27


@pytest.fixture(autouse=True)
def _clean_oauth_state() -> Iterator[None]:
    """The pending sign-ins live in a module-level dict.

    They are cleared between tests so one test's sign-in cannot be
    mistaken for another's.
    """
    oauth._pending.clear()
    oauth._page_tokens.clear()
    yield
    oauth._pending.clear()
    oauth._page_tokens.clear()


@pytest.fixture
def client(autoclip_home: Path, monkeypatch: pytest.MonkeyPatch) -> Iterator[TestClient]:
    monkeypatch.setenv(app_module.ENV_NO_WORKER, "1")
    with TestClient(create_app()) as test_client:
        yield test_client


def _settings() -> config.Settings:
    """Settings with an Instagram connection configured but no credential."""
    settings = config.Settings()
    settings.instagram.app_id = "1234567890"
    settings.instagram.config_id = "9876543210"
    settings.instagram.login_type = "unified"
    settings.instagram.api_version = "v27.0"
    return settings


def _seed_clip() -> tuple[Source, Job, Clip]:
    source = Source(
        id=new_id(), type="upload", path="C:/source.mp4", title="source", duration_s=30.0
    )
    store.create_source(source)
    job = Job(id=new_id(), source_id=source.id, status="done")
    store.create_job(job)
    clip = Clip(id=new_id(), job_id=job.id, start_s=0.0, end_s=10.0, rank=1, title="A clip")
    store.replace_clips(job.id, [clip])
    return source, job, clip


def _export_row(path: str = "C:/out.mp4") -> tuple[Source, Job, Clip, Export]:
    source, job, clip = _seed_clip()
    export = Export(id=new_id(), clip_id=clip.id, path=path)
    store.create_export(export)
    return source, job, clip, export


# --------------------------------------------------------------------------
# Meta's error table
# --------------------------------------------------------------------------


def _graph_error(code: int, subcode: int | None = None, **extra: Any) -> dict[str, Any]:
    error: dict[str, Any] = {
        "message": "Meta said no.",
        "type": "OAuthException",
        "code": code,
        "fbtrace_id": "A6LJylpZRKw2xKLFsAP-cJh",
    }
    if subcode is not None:
        error["error_subcode"] = subcode
    error.update(extra)
    return {"error": error}


@pytest.mark.parametrize(
    ("code", "subcode"),
    [
        (-1, 2207001),
        (-1, 2207032),
        (-1, 2207053),
        (-2, 2207003),
        (-2, 2207020),
        (24, 2207006),
        (24, 2207008),
        (9004, 2207052),
        (9007, 2207027),
    ],
)
def test_the_documented_transient_codes_are_worth_another_try(code: int, subcode: int) -> None:
    error = translate_graph_error(_graph_error(code, subcode), 400)

    assert error.transient is True


@pytest.mark.parametrize(
    ("code", "subcode"),
    [
        (1, 2207057),
        (100, 2207028),
        (100, 2207040),
        (352, 2207026),
        (36000, 2207004),
        (36001, 2207005),
        (36003, 2207009),
        (36004, 2207010),
    ],
)
def test_the_documented_permanent_codes_are_not_retried(code: int, subcode: int) -> None:
    error = translate_graph_error(_graph_error(code, subcode), 400)

    assert error.transient is False


def test_the_publishing_limit_waits_for_the_reset_rather_than_backing_off() -> None:
    error = translate_graph_error(_graph_error(9, 2207042), 400)

    assert error.transient is True
    assert error.retry_at != ""
    # The wait is local midnight tomorrow — the limit is a rolling window,
    # so that is never too early.
    assert error.retry_at.endswith("T00:00:00")


def test_a_restricted_account_is_the_owners_work_not_a_retry() -> None:
    error = translate_graph_error(_graph_error(25, 2207050), 400)

    assert isinstance(error, OwnerActionRequired)
    assert error.transient is False
    assert error.owner_action_required is True


def test_a_suspected_spam_block_is_not_retried_into() -> None:
    error = translate_graph_error(_graph_error(4, 2207051), 400)

    assert isinstance(error, OwnerActionRequired)
    assert error.transient is False
    assert "spam" in str(error).lower()


def test_a_rejected_token_asks_for_a_reconnect() -> None:
    error = translate_graph_error(_graph_error(190), 401)

    assert error.needs_reconnect is True
    assert error.transient is False


def test_a_permission_refusal_is_permanent() -> None:
    error = translate_graph_error(_graph_error(10), 403)

    assert error.transient is False


def test_the_media_not_ready_code_asks_for_another_poll() -> None:
    error = translate_graph_error(_graph_error(9007, 2207027), 400)

    assert error.transient is True
    assert "not ready" in str(error).lower()


def test_an_unknown_code_falls_back_to_the_http_status() -> None:
    server_error = translate_graph_error(_graph_error(123456), 503)
    client_error = translate_graph_error(_graph_error(123456), 400)

    assert server_error.transient is True
    assert client_error.transient is False


def test_a_rate_limit_is_transient() -> None:
    error = translate_graph_error(_graph_error(123456), 429)

    assert error.transient is True


def test_the_fbtrace_id_is_kept_for_support() -> None:
    error = translate_graph_error(_graph_error(25, 2207050), 400)

    assert error.fbtrace_id == "A6LJylpZRKw2xKLFsAP-cJh"
    assert "A6LJylpZRKw2xKLFsAP-cJh" in str(error)


def test_metas_own_message_is_used_when_it_gives_one() -> None:
    payload = _graph_error(25, 2207050, error_user_msg="Your account is restricted.")

    error = translate_graph_error(payload, 400)

    assert "restricted" in str(error)


# --------------------------------------------------------------------------
# The caption limits
# --------------------------------------------------------------------------


def test_a_caption_within_the_limits_passes() -> None:
    assert media_module.validate_caption("A clip about a thing. #gaming #clips") == []


def test_a_caption_over_2200_characters_is_refused() -> None:
    problems = media_module.validate_caption("x" * 2201)

    assert any("2201 characters" in p and "2200" in p for p in problems)


def test_a_caption_at_exactly_2200_characters_is_allowed() -> None:
    assert media_module.validate_caption("x" * 2200) == []


def test_more_than_thirty_hashtags_is_refused() -> None:
    caption = " ".join(f"#tag{i}" for i in range(31))

    problems = media_module.validate_caption(caption)

    assert any("31 hashtags" in p and "30" in p for p in problems)


def test_thirty_hashtags_are_allowed() -> None:
    caption = " ".join(f"#tag{i}" for i in range(30))

    assert media_module.validate_caption(caption) == []


def test_more_than_twenty_mentions_is_refused() -> None:
    caption = " ".join(f"@person{i}" for i in range(21))

    problems = media_module.validate_caption(caption)

    assert any("21 @tags" in p and "20" in p for p in problems)


def test_twenty_mentions_are_allowed() -> None:
    caption = " ".join(f"@person{i}" for i in range(20))

    assert media_module.validate_caption(caption) == []


def test_a_bare_hashtag_is_not_counted() -> None:
    assert media_module.validate_caption("Done # ") == []


def test_a_hashtag_mid_word_is_counted() -> None:
    assert media_module.validate_caption("100%#done").__len__() == 0
    # The tag itself is fine; only the count matters and it is one.
    problems = media_module.validate_caption("100%#done")
    assert problems == []


def test_the_hashtag_counter_finds_tags_that_do_not_start_a_word() -> None:
    assert media_module._count_tags("a#b#c", "#") == 2


# --------------------------------------------------------------------------
# The MP4 box structure
# --------------------------------------------------------------------------


def _box(box_type: str, payload: bytes = b"") -> bytes:
    return struct.pack(">I", 8 + len(payload)) + box_type.encode("latin-1") + payload


def _write_mp4(path: Path, *, moov_first: bool) -> None:
    """A tiny MP4-shaped file with a moov atom and an mdat atom.

    The real thing is not needed to test the walk: what matters is that
    the reader finds the atoms and notices which one comes first.
    """
    moov = _box("moov", _box("mvhd", b"\x00" * 100))
    mdat = _box("mdat", b"\x00" * 100)
    data = (moov + mdat) if moov_first else (mdat + moov)
    path.write_bytes(data)


def test_the_moov_atom_at_the_front_is_recognised(tmp_path: Path) -> None:
    path = tmp_path / "front.mp4"
    _write_mp4(path, moov_first=True)

    result = media_module.scan_boxes(path)

    assert result["moov_at_front"] is True
    assert "moov" in result["boxes"]
    assert "mdat" in result["boxes"]


def test_a_moov_atom_at_the_back_is_recognised(tmp_path: Path) -> None:
    path = tmp_path / "back.mp4"
    _write_mp4(path, moov_first=False)

    result = media_module.scan_boxes(path)

    assert result["moov_at_front"] is False


def test_an_edit_list_is_found(tmp_path: Path) -> None:
    path = tmp_path / "edit.mp4"
    path.write_bytes(_box("moov", _box("edts", _box("elst", b"\x00" * 24))))

    result = media_module.scan_boxes(path)

    assert result["has_edit_list"] is True


def test_a_file_with_no_moov_atom_reports_that_it_cannot_tell(tmp_path: Path) -> None:
    path = tmp_path / "nomov.mp4"
    path.write_bytes(_box("mdat", b"\x00" * 100))

    result = media_module.scan_boxes(path)

    assert result["moov_at_front"] is None


def test_the_walk_does_not_read_the_media_payload_as_boxes(tmp_path: Path) -> None:
    """``mdat`` holds the media bytes; reading them as box headers finds
    nonsense. The walk must stop at the box boundary."""
    path = tmp_path / "payload.mp4"
    # A payload that, read as box headers, would claim a "moov" atom.
    fake_moov = struct.pack(">I", 8) + b"moov"
    path.write_bytes(_box("moov") + _box("mdat", fake_moov + b"\x00" * 20))

    result = media_module.scan_boxes(path)

    assert result["moov_at_front"] is True
    assert result["order"].count("moov") == 1


def test_a_missing_file_is_reported_rather_than_crashing(tmp_path: Path) -> None:
    result = media_module.scan_boxes(tmp_path / "nope.mp4")

    assert result["moov_at_front"] is None


# --------------------------------------------------------------------------
# The derived bitrate
# --------------------------------------------------------------------------


def test_a_reported_bitrate_is_used_as_it_is() -> None:
    bitrate, source = media_module._video_bitrate(
        {"video_bitrate_bps": 12_000_000, "duration_s": 10.0, "size_bytes": 1000}
    )

    assert bitrate == 12_000_000
    assert "ffprobe" in source


def test_a_missing_bitrate_is_derived_from_the_size_and_duration() -> None:
    # 10 seconds, 1,000,000 bytes = 8,000,000 bits over 10 seconds =
    # 800,000 bits per second.
    bitrate, source = media_module._video_bitrate(
        {"video_bitrate_bps": None, "duration_s": 10.0, "size_bytes": 1_000_000}
    )

    assert bitrate == 800_000
    assert "derived" in source


def test_the_derived_bitrate_leaves_the_audio_out() -> None:
    bitrate, _ = media_module._video_bitrate(
        {
            "video_bitrate_bps": None,
            "duration_s": 10.0,
            "size_bytes": 1_000_000,
            "audio_bitrate_bps": 128_000,
        }
    )

    assert bitrate == 800_000 - 128_000


def test_a_bitrate_that_cannot_be_derived_is_reported_as_unmeasured() -> None:
    bitrate, source = media_module._video_bitrate(
        {"video_bitrate_bps": None, "duration_s": None, "size_bytes": 0}
    )

    assert bitrate is None
    assert source == ""


# --------------------------------------------------------------------------
# The publishing sequence
# --------------------------------------------------------------------------


class _Response:
    def __init__(self, status: int, body: dict | None = None) -> None:
        self.status_code = status
        self._body = body or {}

    def json(self) -> dict:
        return self._body


class _FakeGraph:
    """A stand-in for Meta's Graph API.

    It records every call so the test can check the *order* and the
    *shape* of the sequence, which is the thing that matters: a publish
    that creates the container before the file is uploaded is not the
    documented sequence.
    """

    def __init__(self) -> None:
        self.calls: list[tuple[str, str, dict]] = []
        self.status_code = "FINISHED"
        self.media_id = "17900000000000001"
        self.permalink = "https://www.instagram.com/reel/abc/"
        self.config_issue = ""

    def post(self, url: str, **kwargs: Any) -> _Response:
        self.calls.append(("POST", url, dict(kwargs)))
        if "/media_publish" in url:
            body: dict[str, Any] = {"id": self.media_id}
            if self.config_issue:
                body["config_issue"] = self.config_issue
            return _Response(200, body)
        if "rupload.facebook.com" in url:
            return _Response(200, {})
        return _Response(
            200,
            {
                "id": "container-1",
                "uri": "https://rupload.facebook.com/ig-api-upload/v27.0/container-1",
            },
        )

    def get(self, url: str, **kwargs: Any) -> _Response:
        self.calls.append(("GET", url, dict(kwargs)))
        if "content_publishing_limit" in url:
            return _Response(
                200,
                {
                    "config": {"quota_total": 50, "quota_duration": 86400},
                    "quota_usage": {"usage": 7},
                },
            )
        if "/media?" in url or url.endswith(f"/{self.media_id}"):
            return _Response(
                200,
                {
                    "id": self.media_id,
                    "permalink": self.permalink,
                    "media_type": "VIDEO",
                    "media_product_type": "reel",
                    "caption": "A clip",
                },
            )
        return _Response(
            200,
            {
                "id": "container-1",
                "status_code": self.status_code,
                "status": "The media finished processing.",
                "video_status": {"uploading_phase": {"status": "SUCCESS", "bytes_transferred": 0}},
            },
        )


@pytest.fixture
def fake_graph(monkeypatch: pytest.MonkeyPatch) -> _FakeGraph:
    graph = _FakeGraph()
    monkeypatch.setattr(publisher.httpx, "post", graph.post)
    monkeypatch.setattr(publisher.httpx, "get", graph.get)
    return graph


def _account(login_type: str = "unified") -> Any:
    account = accounts_store.create_account(
        label="Test", login_type=login_type, ig_user_id="17841400000000001"
    )
    accounts_store.store_token(account.id, "token-abc")
    return account


def test_a_container_is_created_before_the_file_is_uploaded(
    fake_graph: _FakeGraph,
) -> None:
    account = _account()
    settings = _settings()

    container = publisher.create_container(
        settings, account, token="token-abc", media_type="REELS", caption="A clip"
    )

    assert container.id == "container-1"
    assert container.uri.startswith("https://rupload.facebook.com/")
    # The container request asks for a resumable upload.
    _, _, kwargs = fake_graph.calls[0]
    assert kwargs["json"]["upload_type"] == "resumable"
    assert kwargs["json"]["media_type"] == "REELS"
    assert kwargs["json"]["caption"] == "A clip"


def test_the_container_request_is_sent_with_a_bearer_token(
    fake_graph: _FakeGraph,
) -> None:
    account = _account()
    settings = _settings()

    publisher.create_container(settings, account, token="token-abc")

    _, _, kwargs = fake_graph.calls[0]
    assert kwargs["headers"]["Authorization"] == "Bearer token-abc"


def test_the_ai_disclosure_is_only_sent_when_the_owner_declared_it(
    fake_graph: _FakeGraph,
) -> None:
    account = _account()
    settings = _settings()

    publisher.create_container(settings, account, token="token-abc")
    _, _, kwargs = fake_graph.calls[0]
    assert "is_ai_generated" not in kwargs["json"]

    publisher.create_container(settings, account, token="token-abc", is_ai_generated=True)
    _, _, kwargs = fake_graph.calls[1]
    assert kwargs["json"]["is_ai_generated"] is True


def test_the_file_is_sent_with_the_oauth_header_and_the_offset(
    fake_graph: _FakeGraph, tmp_path: Path
) -> None:
    path = tmp_path / "clip.mp4"
    path.write_bytes(b"x" * 100)

    sent = publisher.upload_file(
        "https://rupload.facebook.com/ig-api-upload/v27.0/container-1",
        path,
        token="token-abc",
    )

    assert sent == 100
    _, url, kwargs = fake_graph.calls[-1]
    assert url == "https://rupload.facebook.com/ig-api-upload/v27.0/container-1"
    # Meta's upload endpoint takes the token as "OAuth", not "Bearer".
    assert kwargs["headers"]["Authorization"] == "OAuth token-abc"
    assert kwargs["headers"]["offset"] == "0"
    assert kwargs["headers"]["file_size"] == "100"


def test_an_upload_that_continues_reports_the_offset_it_starts_from(
    fake_graph: _FakeGraph, tmp_path: Path
) -> None:
    path = tmp_path / "clip.mp4"
    path.write_bytes(b"x" * 100)

    publisher.upload_file(
        "https://rupload.facebook.com/ig-api-upload/v27.0/container-1",
        path,
        token="token-abc",
        offset=40,
    )

    _, _, kwargs = fake_graph.calls[-1]
    assert kwargs["headers"]["offset"] == "40"


def test_an_upload_address_that_is_not_https_is_refused(
    fake_graph: _FakeGraph, tmp_path: Path
) -> None:
    path = tmp_path / "clip.mp4"
    path.write_bytes(b"x" * 100)

    with pytest.raises(InstagramError) as excinfo:
        publisher.upload_file(
            "http://rupload.facebook.com/ig-api-upload/v27.0/container-1",
            path,
            token="token-abc",
        )

    assert "https" in str(excinfo.value)


def test_the_publish_sends_the_container_id(fake_graph: _FakeGraph) -> None:
    account = _account()
    settings = _settings()

    result = publisher.publish(settings, account, token="token-abc", container_id="container-1")

    assert result.media_id == "17900000000000001"
    _, url, kwargs = fake_graph.calls[-1]
    assert url.endswith("/17841400000000001/media_publish")
    assert kwargs["json"]["creation_id"] == "container-1"


def test_a_publish_that_dropped_part_of_the_request_is_reported(
    fake_graph: _FakeGraph,
) -> None:
    fake_graph.config_issue = "CAPTION_NOT_ATTACHED"
    account = _account()
    settings = _settings()

    result = publisher.publish(settings, account, token="token-abc", container_id="container-1")

    assert result.config_issue == "CAPTION_NOT_ATTACHED"


def test_the_read_back_reports_what_instagram_published(
    fake_graph: _FakeGraph,
) -> None:
    account = _account()
    settings = _settings()

    published = publisher.read_back(
        settings, account, token="token-abc", media_id="17900000000000001"
    )

    assert published.id == "17900000000000001"
    assert published.permalink == "https://www.instagram.com/reel/abc/"
    assert published.is_reel is True


def test_a_read_back_that_fails_does_not_fail_the_publish(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def boom(url: str, **kwargs: Any) -> _Response:
        return _Response(500, {})

    monkeypatch.setattr(publisher.httpx, "get", boom)
    account = _account()
    settings = _settings()

    published = publisher.read_back(
        settings, account, token="token-abc", media_id="17900000000000001"
    )

    assert published.id == "17900000000000001"
    assert published.permalink == ""


# --------------------------------------------------------------------------
# The publishing limit
# --------------------------------------------------------------------------


def test_the_publishing_limit_is_read_from_meta(fake_graph: _FakeGraph) -> None:
    account = _account()
    settings = _settings()

    limit = publisher.publishing_limit(settings, account, token="token-abc")

    assert limit.known is True
    assert limit.quota_total == 50
    assert limit.quota_usage == 7
    assert limit.to_dict()["remaining"] == 43


def test_the_publishing_limit_is_never_hardcoded(
    fake_graph: _FakeGraph, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Meta's own documents disagree (100 in one place, 50 in another).
    The number AutoClip uses is the one the endpoint reports."""
    account = _account()
    settings = _settings()

    def other_limit(url: str, **kwargs: Any) -> _Response:
        fake_graph.calls.append(("GET", url, dict(kwargs)))
        return _Response(
            200,
            {
                "config": {"quota_total": 137, "quota_duration": 86400},
                "quota_usage": {"usage": 0},
            },
        )

    monkeypatch.setattr(publisher.httpx, "get", other_limit)

    limit = publisher.publishing_limit(settings, account, token="token-abc")

    assert limit.quota_total == 137


def test_a_publishing_limit_that_cannot_be_read_is_not_reported_as_no_limit(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def boom(url: str, **kwargs: Any) -> _Response:
        return _Response(500, {})

    monkeypatch.setattr(publisher.httpx, "get", boom)
    account = _account()
    settings = _settings()

    limit = publisher.publishing_limit(settings, account, token="token-abc")

    assert limit.known is False
    assert limit.quota_total == 0


# --------------------------------------------------------------------------
# The eligibility refusal
# --------------------------------------------------------------------------


def test_the_instagram_login_setup_refuses_a_local_file(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Meta documents the resumable upload protocol only for apps using
    Facebook Login for Business. On the Instagram Login setup there is
    no official way to send a local file, and AutoClip refuses rather
    than inventing a host for it."""
    path = tmp_path / "clip.mp4"
    path.write_bytes(b"x" * 100)

    monkeypatch.setattr(
        media_module,
        "validate_reel",
        lambda p: media_module.MediaReport(path=p),
    )
    monkeypatch.setattr(media_module, "validate_caption", lambda c: [])

    account = _account(login_type="instagram")
    _, _, _, export = _export_row(str(path))
    row = uploads.enqueue(export.id, account_row_id=account.id)

    settings = _settings()
    settings.instagram.login_type = "instagram"

    with pytest.raises(uploads.MediaRejected) as excinfo:
        asyncio.run(uploads.process_upload(row, settings))

    message = str(excinfo.value)
    assert "Instagram Login" in message
    assert "resumable" in message.lower()
    # The refusal says what the owner can do, not just that it failed.
    assert "somewhere else" in message


def test_the_unified_setup_does_not_refuse_a_local_file(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The refusal belongs to the Instagram Login setup only. On the
    Unified Login setup the file goes straight to Meta."""
    path = tmp_path / "clip.mp4"
    path.write_bytes(b"x" * 100)

    monkeypatch.setattr(
        media_module,
        "validate_reel",
        lambda p: media_module.MediaReport(path=p),
    )
    monkeypatch.setattr(media_module, "validate_caption", lambda c: [])

    account = _account(login_type="unified")
    _, _, _, export = _export_row(str(path))
    row = uploads.enqueue(export.id, account_row_id=account.id)

    reached = False

    def reached_container(*args: Any, **kwargs: Any) -> None:
        nonlocal reached
        reached = True
        raise RuntimeError("stop here — the container was reached")

    monkeypatch.setattr(publisher, "create_container", reached_container)

    settings = _settings()

    with pytest.raises(RuntimeError, match="the container was reached"):
        asyncio.run(uploads.process_upload(row, settings))

    assert reached is True


# --------------------------------------------------------------------------
# The media validation, against a real file
# --------------------------------------------------------------------------


@pytest.mark.slow
def test_a_real_reel_that_meets_the_limits_passes(tmp_path: Path) -> None:
    import subprocess

    from autoclip.pipeline import ffmpeg

    path = tmp_path / "reel.mp4"
    subprocess.run(
        [
            ffmpeg.ffmpeg_path(),
            "-hide_banner",
            "-loglevel",
            "error",
            "-y",
            "-f",
            "lavfi",
            "-i",
            "testsrc2=size=1080x1920:rate=30:duration=5",
            "-f",
            "lavfi",
            "-i",
            "sine=frequency=440:duration=5",
            "-c:v",
            "libx264",
            "-pix_fmt",
            "yuv420p",
            "-movflags",
            "+faststart",
            "-use_editlist",
            "0",
            "-c:a",
            "aac",
            "-ar",
            "48000",
            str(path),
        ],
        check=True,
    )

    report = media_module.validate_reel(path)

    assert report.ok is True, report.problems
    assert report.problems == []
    # The checks are real measurements, and the moov atom was checked.
    names = {c.name for c in report.checks}
    assert "moov_at_front" in names
    assert "duration" in names
    assert "edit_list" in names
    assert report.facts["moov_at_front"] is True


@pytest.mark.slow
def test_a_file_that_is_too_narrow_is_refused_with_the_measurement(
    tmp_path: Path,
) -> None:
    import subprocess

    from autoclip.pipeline import ffmpeg

    path = tmp_path / "wide.mp4"
    subprocess.run(
        [
            ffmpeg.ffmpeg_path(),
            "-hide_banner",
            "-loglevel",
            "error",
            "-y",
            "-f",
            "lavfi",
            "-i",
            "testsrc2=size=2560x1440:rate=30:duration=5",
            "-c:v",
            "libx264",
            "-pix_fmt",
            "yuv420p",
            "-use_editlist",
            "0",
            str(path),
        ],
        check=True,
    )

    report = media_module.validate_reel(path)

    assert report.ok is False
    assert any("2560 pixels wide" in p for p in report.problems)
    assert any("1920" in p for p in report.problems)


@pytest.mark.slow
def test_a_clip_that_is_too_short_is_refused(tmp_path: Path) -> None:
    import subprocess

    from autoclip.pipeline import ffmpeg

    path = tmp_path / "short.mp4"
    subprocess.run(
        [
            ffmpeg.ffmpeg_path(),
            "-hide_banner",
            "-loglevel",
            "error",
            "-y",
            "-f",
            "lavfi",
            "-i",
            "testsrc2=size=1080x1920:rate=30:duration=1",
            "-c:v",
            "libx264",
            "-pix_fmt",
            "yuv420p",
            "-use_editlist",
            "0",
            str(path),
        ],
        check=True,
    )

    report = media_module.validate_reel(path)

    assert report.ok is False
    assert any("1.0 seconds" in p for p in report.problems)


@pytest.mark.slow
def test_a_file_without_the_faststart_flag_is_refused(tmp_path: Path) -> None:
    import subprocess

    from autoclip.pipeline import ffmpeg

    path = tmp_path / "nofaststart.mp4"
    subprocess.run(
        [
            ffmpeg.ffmpeg_path(),
            "-hide_banner",
            "-loglevel",
            "error",
            "-y",
            "-f",
            "lavfi",
            "-i",
            "testsrc2=size=1080x1920:rate=30:duration=5",
            "-c:v",
            "libx264",
            "-pix_fmt",
            "yuv420p",
            "-use_editlist",
            "0",
            str(path),
        ],
        check=True,
    )

    report = media_module.validate_reel(path)

    assert report.ok is False
    assert any("moov atom" in p for p in report.problems)


def test_a_missing_export_is_reported(tmp_path: Path) -> None:
    with pytest.raises(media_module.MediaInvalid):
        media_module.validate_reel(tmp_path / "nope.mp4")


# --------------------------------------------------------------------------
# Duplicate prevention
# --------------------------------------------------------------------------


def test_a_clip_that_is_already_published_is_not_published_again(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Instagram has no idempotency key, so the guarantee is made
    locally: a second export of the same clip is refused once the first
    one has been published."""
    monkeypatch.setattr(
        media_module,
        "validate_reel",
        lambda p: media_module.MediaReport(path=p),
    )
    monkeypatch.setattr(media_module, "validate_caption", lambda c: [])

    account = _account()
    _, _, clip, first_export = _export_row(str(tmp_path / "clip.mp4"))
    published = uploads.enqueue(first_export.id, account_row_id=account.id)
    store.update_instagram_upload(published.id, status="done", media_id="post-1")

    # The same clip, exported a second time.
    second_export = Export(id=new_id(), clip_id=clip.id, path=str(tmp_path / "clip2.mp4"))
    store.create_export(second_export)
    second = uploads.enqueue(second_export.id, account_row_id=account.id)

    reason = uploads.duplicate_reason(second)
    assert "already on Instagram" in reason
    assert "post-1" in reason


def test_a_double_enqueue_of_the_same_export_is_one_row(tmp_path: Path) -> None:
    account = _account()
    _, _, _, export = _export_row(str(tmp_path / "clip.mp4"))

    first = uploads.enqueue(export.id, account_row_id=account.id)
    second = uploads.enqueue(export.id, account_row_id=account.id)

    assert second.id == first.id
    assert len(store.list_instagram_uploads_for_export(export.id)) == 1


def test_a_failed_upload_is_not_a_duplicate(tmp_path: Path) -> None:
    account = _account()
    _, _, _, export = _export_row(str(tmp_path / "clip.mp4"))
    row = uploads.enqueue(export.id, account_row_id=account.id)
    store.update_instagram_upload(row.id, status="failed", error="nope")

    assert uploads.duplicate_reason(row) == ""


def test_the_same_clip_on_a_different_account_is_not_a_duplicate(
    tmp_path: Path,
) -> None:
    account_a = _account()
    account_b = accounts_store.create_account(
        label="Second", login_type="unified", ig_user_id="17841400000000002"
    )
    _, _, clip, export = _export_row(str(tmp_path / "clip.mp4"))

    first = uploads.enqueue(export.id, account_row_id=account_a.id)
    store.update_instagram_upload(first.id, status="done", media_id="post-1")

    other = store.create_instagram_upload(
        type(first)(
            id=new_id(),
            export_id=export.id,
            clip_id=clip.id,
            account_row_id=account_b.id,
        )
    )

    assert uploads.duplicate_reason(other) == ""


# --------------------------------------------------------------------------
# Platform independence
# --------------------------------------------------------------------------


def test_an_instagram_failure_does_not_cancel_a_youtube_upload(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The two platforms have separate tables and separate workers, so a
    failure in one cannot reach into the other."""
    from autoclip.db.models import YouTubeUpload

    _, _, _, export = _export_row(str(tmp_path / "clip.mp4"))

    youtube = store.create_upload(
        YouTubeUpload(id=new_id(), export_id=export.id, clip_id=export.clip_id)
    )
    instagram = uploads.enqueue(export.id, account_row_id=_account().id)

    # The Instagram upload fails permanently.
    store.update_instagram_upload(instagram.id, status="failed", error="Meta said no.")

    fresh = store.get_upload(youtube.id)
    assert fresh is not None
    assert fresh.status == "pending"
    assert fresh.error is None


def test_a_youtube_failure_does_not_cancel_an_instagram_upload(
    tmp_path: Path,
) -> None:
    from autoclip.db.models import YouTubeUpload

    _, _, _, export = _export_row(str(tmp_path / "clip.mp4"))

    youtube = store.create_upload(
        YouTubeUpload(id=new_id(), export_id=export.id, clip_id=export.clip_id)
    )
    instagram = uploads.enqueue(export.id, account_row_id=_account().id)

    store.update_upload(youtube.id, status="failed", error="YouTube said no.")

    fresh = store.get_instagram_upload(instagram.id)
    assert fresh is not None
    assert fresh.status == "pending"
    assert fresh.error is None


def test_the_instagram_queue_never_reads_the_youtube_table(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A structural check, not a promise: the Instagram worker asks its
    own store function for the next row, so a YouTube row cannot be
    picked up by accident."""
    from autoclip.db.models import YouTubeUpload

    _, _, _, export = _export_row(str(tmp_path / "clip.mp4"))
    store.create_upload(YouTubeUpload(id=new_id(), export_id=export.id, clip_id=export.clip_id))

    assert store.next_pending_instagram_upload() is None


# --------------------------------------------------------------------------
# The worker
# --------------------------------------------------------------------------


def test_the_worker_leaves_a_transient_failure_pending_for_another_try(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    account = _account()
    _, _, _, export = _export_row(str(tmp_path / "clip.mp4"))
    row = uploads.enqueue(export.id, account_row_id=account.id)

    async def fail(upload: Any, settings: Any) -> str:
        raise InstagramError("The connection dropped.", transient=True)

    monkeypatch.setattr(uploads, "process_upload", fail)

    queue = InstagramUploadQueue()
    asyncio.run(queue._run(row.id))

    fresh = store.get_instagram_upload(row.id)
    assert fresh is not None
    assert fresh.status == "pending"
    assert fresh.next_attempt_at != ""
    assert "connection dropped" in (fresh.error or "")


def test_the_worker_marks_a_permanent_failure_as_failed(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    account = _account()
    _, _, _, export = _export_row(str(tmp_path / "clip.mp4"))
    row = uploads.enqueue(export.id, account_row_id=account.id)

    async def fail(upload: Any, settings: Any) -> str:
        raise InstagramError("The caption is too long.", transient=False)

    monkeypatch.setattr(uploads, "process_upload", fail)

    queue = InstagramUploadQueue()
    asyncio.run(queue._run(row.id))

    fresh = store.get_instagram_upload(row.id)
    assert fresh is not None
    assert fresh.status == "failed"


def test_the_worker_asks_the_owner_when_only_the_owner_can_act(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    account = _account()
    _, _, _, export = _export_row(str(tmp_path / "clip.mp4"))
    row = uploads.enqueue(export.id, account_row_id=account.id)

    async def fail(upload: Any, settings: Any) -> str:
        raise OwnerActionRequired("Your account is restricted.")

    monkeypatch.setattr(uploads, "process_upload", fail)

    queue = InstagramUploadQueue()
    asyncio.run(queue._run(row.id))

    fresh = store.get_instagram_upload(row.id)
    assert fresh is not None
    assert fresh.status == "failed"
    assert "restricted" in (fresh.error or "")


def test_the_worker_does_not_retry_a_duplicate(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    account = _account()
    _, _, _, export = _export_row(str(tmp_path / "clip.mp4"))
    row = uploads.enqueue(export.id, account_row_id=account.id)
    store.update_instagram_upload(row.id, status="done", media_id="post-1")

    duplicate = store.create_instagram_upload(
        type(row)(
            id=new_id(),
            export_id=export.id,
            clip_id=row.clip_id,
            account_row_id=account.id,
        )
    )

    async def fail(upload: Any, settings: Any) -> str:
        raise uploads.DuplicateUploadError("This clip is already on Instagram.")

    monkeypatch.setattr(uploads, "process_upload", fail)

    queue = InstagramUploadQueue()
    asyncio.run(queue._run(duplicate.id))

    fresh = store.get_instagram_upload(duplicate.id)
    assert fresh is not None
    assert fresh.status == "skipped"


def test_a_publishing_limit_waits_for_the_reset_without_using_up_the_attempts(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    account = _account()
    _, _, _, export = _export_row(str(tmp_path / "clip.mp4"))
    row = uploads.enqueue(export.id, account_row_id=account.id)

    async def fail(upload: Any, settings: Any) -> str:
        raise InstagramError(
            "Instagram's publishing limit for this account has been reached.",
            transient=True,
            retry_at="2030-01-01T00:00:00",
        )

    monkeypatch.setattr(uploads, "process_upload", fail)

    queue = InstagramUploadQueue()
    asyncio.run(queue._run(row.id))

    fresh = store.get_instagram_upload(row.id)
    assert fresh is not None
    assert fresh.status == "pending"
    assert fresh.next_attempt_at == "2030-01-01T00:00:00"
    # The file never left the machine, so this does not count as an
    # attempt at publishing.
    assert fresh.attempts == 0


def test_an_interrupted_instagram_upload_is_recovered_on_startup(
    tmp_path: Path,
) -> None:
    account = _account()
    _, _, _, export = _export_row(str(tmp_path / "clip.mp4"))
    row = uploads.enqueue(export.id, account_row_id=account.id)
    store.update_instagram_upload(row.id, status="uploading", bytes_sent=1234)

    recovered = store.requeue_interrupted_instagram_uploads()

    assert row.id in recovered
    fresh = store.get_instagram_upload(row.id)
    assert fresh is not None
    assert fresh.status == "pending"
    # The byte count survives, so the transfer continues rather than
    # starting again.
    assert fresh.bytes_sent == 1234


# --------------------------------------------------------------------------
# The API
# --------------------------------------------------------------------------


def test_the_status_endpoint_reports_the_connection(client: TestClient) -> None:
    response = client.get("/api/instagram/status")

    assert response.status_code == 200
    body = response.json()
    assert body["connected"] is False
    assert body["configured"] is False
    assert body["login_type"] == "unified"
    assert body["api_version"] == "v27.0"


def test_connecting_without_credentials_is_refused(client: TestClient) -> None:
    response = client.post("/api/instagram/connect", json={})

    assert response.status_code == 400
    assert "app ID" in response.json()["detail"]


def test_connecting_with_credentials_returns_the_meta_consent_url(
    client: TestClient, fake_keyring: Any
) -> None:
    settings = config.load()
    settings.instagram.app_id = "1234567890"
    settings.instagram.config_id = "9876543210"
    config.save(settings)
    fake_keyring.set_password("autoclip", config.INSTAGRAM_APP_SECRET_KEY, "the-secret")

    response = client.post("/api/instagram/connect", json={})

    assert response.status_code == 200
    url = response.json()["auth_url"]
    assert url.startswith("https://www.facebook.com/dialog/oauth?")
    assert "config_id=9876543210" in url
    assert "client_id=1234567890" in url


def test_the_instagram_login_setup_uses_the_instagram_authorisation_url(
    client: TestClient, fake_keyring: Any
) -> None:
    settings = config.load()
    settings.instagram.app_id = "1234567890"
    settings.instagram.login_type = "instagram"
    config.save(settings)
    fake_keyring.set_password("autoclip", config.INSTAGRAM_APP_SECRET_KEY, "the-secret")

    response = client.post("/api/instagram/connect", json={})

    assert response.status_code == 200
    url = response.json()["auth_url"]
    assert url.startswith("https://www.instagram.com/oauth/authorize?")
    assert "instagram_business_content_publish" in url
    assert "enable_fb_login=false" in url


def test_the_eligibility_endpoint_never_refuses(client: TestClient) -> None:
    response = client.get("/api/instagram/eligibility")

    assert response.status_code == 200
    body = response.json()
    assert body["resumable_upload"] is True
    assert body["local_file_supported"] is True
    # Nothing is connected, so the report says so rather than pretending.
    assert any("No Instagram account" in u for u in body["unverified"])
    # The documented requirements are named.
    assert any("professional account" in r for r in body["requirements"])


def test_the_eligibility_endpoint_reports_the_instagram_setup_limit(
    client: TestClient,
) -> None:
    settings = config.load()
    settings.instagram.login_type = "instagram"
    config.save(settings)

    body = client.get("/api/instagram/eligibility").json()

    assert body["resumable_upload"] is False
    assert body["local_file_supported"] is False


def test_the_accounts_endpoint_never_returns_a_token(client: TestClient) -> None:
    account = accounts_store.create_account(label="Test", ig_user_id="17841")
    accounts_store.store_token(account.id, "secret-token")

    response = client.get("/api/instagram/accounts")

    assert response.status_code == 200
    body = response.json()
    assert body[0]["has_token"] is True
    assert "secret-token" not in response.text


def test_an_upload_can_be_queued_by_export_id(client: TestClient) -> None:
    account = accounts_store.create_account(label="Test", ig_user_id="17841")
    _, _, _, export = _export_row()

    response = client.post(
        "/api/instagram/uploads",
        json={"export_id": export.id, "account_row_id": account.id, "caption": "Hello"},
    )

    assert response.status_code == 201
    body = response.json()
    assert body["caption"] == "Hello"
    assert body["status"] == "pending"


def test_queueing_without_an_account_is_refused(client: TestClient) -> None:
    _, _, _, export = _export_row()

    response = client.post("/api/instagram/uploads", json={"export_id": export.id})

    assert response.status_code == 400
    assert "Connect an Instagram account" in response.json()["detail"]


def test_a_caption_that_breaks_the_limits_is_refused_before_the_file_leaves(
    client: TestClient,
) -> None:
    account = accounts_store.create_account(label="Test", ig_user_id="17841")
    _, _, _, export = _export_row()

    response = client.post(
        "/api/instagram/uploads",
        json={"export_id": export.id, "account_row_id": account.id, "caption": "x" * 2201},
    )

    assert response.status_code == 400
    assert "2200" in response.json()["detail"]


def test_a_queued_post_can_have_its_caption_changed(client: TestClient) -> None:
    account = accounts_store.create_account(label="Test", ig_user_id="17841")
    _, _, _, export = _export_row()
    row = uploads.enqueue(export.id, account_row_id=account.id)

    response = client.put(f"/api/instagram/uploads/{row.id}", json={"caption": "A better caption"})

    assert response.status_code == 200
    assert response.json()["caption"] == "A better caption"


def test_a_published_post_cannot_have_its_caption_changed_here(
    client: TestClient,
) -> None:
    account = accounts_store.create_account(label="Test", ig_user_id="17841")
    _, _, _, export = _export_row()
    row = uploads.enqueue(export.id, account_row_id=account.id)
    store.update_instagram_upload(row.id, status="done", media_id="post-1")

    response = client.put(f"/api/instagram/uploads/{row.id}", json={"caption": "Something else"})

    assert response.status_code == 409
    assert "already on Instagram" in response.json()["detail"]


def test_the_ai_declaration_is_the_owners_to_make(client: TestClient) -> None:
    account = accounts_store.create_account(label="Test", ig_user_id="17841")
    _, _, _, export = _export_row()
    row = uploads.enqueue(export.id, account_row_id=account.id)

    response = client.put(f"/api/instagram/uploads/{row.id}", json={"is_ai_generated": True})

    assert response.status_code == 200
    assert response.json()["is_ai_generated"] is True


def test_a_failed_post_can_be_retried(client: TestClient) -> None:
    account = accounts_store.create_account(label="Test", ig_user_id="17841")
    _, _, _, export = _export_row()
    row = uploads.enqueue(export.id, account_row_id=account.id)
    store.update_instagram_upload(row.id, status="failed", error="nope")

    response = client.post(f"/api/instagram/uploads/{row.id}/retry")

    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "pending"
    assert body["error"] is None


def test_a_published_post_cannot_be_retried(client: TestClient) -> None:
    account = accounts_store.create_account(label="Test", ig_user_id="17841")
    _, _, _, export = _export_row()
    row = uploads.enqueue(export.id, account_row_id=account.id)
    store.update_instagram_upload(row.id, status="done", media_id="post-1")

    response = client.post(f"/api/instagram/uploads/{row.id}/retry")

    assert response.status_code == 409


def test_the_validate_endpoint_reports_a_file_it_cannot_read(
    client: TestClient, tmp_path: Path
) -> None:
    path = tmp_path / "clip.mp4"
    path.write_bytes(b"not a media file")
    _, _, _, export = _export_row(str(path))

    response = client.get(f"/api/instagram/validate?export_id={export.id}")

    assert response.status_code == 400
    assert "media file" in response.json()["detail"]


def test_the_validate_endpoint_reports_a_missing_file(client: TestClient, tmp_path: Path) -> None:
    _, _, _, export = _export_row(str(tmp_path / "gone.mp4"))

    response = client.get(f"/api/instagram/validate?export_id={export.id}")

    assert response.status_code == 400
    assert "missing" in response.json()["detail"]


@pytest.mark.slow
def test_the_validate_endpoint_measures_a_real_file_without_sending_anything(
    client: TestClient, tmp_path: Path
) -> None:
    import subprocess

    from autoclip.pipeline import ffmpeg

    path = tmp_path / "reel.mp4"
    subprocess.run(
        [
            ffmpeg.ffmpeg_path(),
            "-hide_banner",
            "-loglevel",
            "error",
            "-y",
            "-f",
            "lavfi",
            "-i",
            "testsrc2=size=1080x1920:rate=30:duration=5",
            "-c:v",
            "libx264",
            "-pix_fmt",
            "yuv420p",
            "-movflags",
            "+faststart",
            "-use_editlist",
            "0",
            str(path),
        ],
        check=True,
    )
    _, _, _, export = _export_row(str(path))

    response = client.get(f"/api/instagram/validate?export_id={export.id}")

    assert response.status_code == 200
    body = response.json()
    assert body["ok"] is True
    assert {c["name"] for c in body["checks"]} >= {"moov_at_front", "edit_list"}


def test_the_validate_endpoint_reports_an_unknown_export(client: TestClient) -> None:
    response = client.get("/api/instagram/validate?export_id=nope")

    assert response.status_code == 404


def test_automation_cannot_be_turned_on_without_an_account(
    client: TestClient,
) -> None:
    response = client.post("/api/instagram/auto-upload", json={"enabled": True})

    assert response.status_code == 400
    assert "Connect an Instagram account" in response.json()["detail"]


def test_automation_can_be_turned_on_when_an_account_is_connected(
    client: TestClient, fake_keyring: Any
) -> None:
    account = accounts_store.create_account(label="Test", ig_user_id="17841")
    accounts_store.store_token(account.id, "token")
    settings = config.load()
    settings.instagram.app_id = "1234567890"
    settings.instagram.config_id = "9876543210"
    config.save(settings)
    fake_keyring.set_password("autoclip", config.INSTAGRAM_APP_SECRET_KEY, "the-secret")

    response = client.post("/api/instagram/auto-upload", json={"enabled": True})

    assert response.status_code == 200
    assert response.json()["auto_upload"] is True


def test_disconnecting_one_account_leaves_the_others_connected(
    client: TestClient, fake_keyring: Any
) -> None:
    settings = config.load()
    settings.instagram.app_id = "1234567890"
    settings.instagram.config_id = "9876543210"
    config.save(settings)
    fake_keyring.set_password("autoclip", config.INSTAGRAM_APP_SECRET_KEY, "the-secret")

    first = accounts_store.create_account(label="First", ig_user_id="17841")
    second = accounts_store.create_account(label="Second", ig_user_id="17842")
    accounts_store.store_token(first.id, "token-1")
    accounts_store.store_token(second.id, "token-2")

    response = client.post("/api/instagram/disconnect", json={"account_id": first.id})

    assert response.status_code == 200
    assert response.json()["connected"] is True
    remaining = accounts_store.token_for(second.id)
    assert remaining == "token-2"


# --------------------------------------------------------------------------
# The accounts
# --------------------------------------------------------------------------


def test_connecting_the_same_instagram_account_twice_reuses_the_row(
    fake_keyring: Any,
) -> None:
    first = accounts_store.create_account(label="First", ig_user_id="17841400000000001")
    second = accounts_store.create_account(label="Second", ig_user_id="17841400000000001")

    assert second.id == first.id


def test_two_different_accounts_keep_their_own_credentials(fake_keyring: Any) -> None:
    first = accounts_store.create_account(label="First", ig_user_id="17841400000000001")
    second = accounts_store.create_account(label="Second", ig_user_id="17841400000000002")
    accounts_store.store_token(first.id, "token-1")
    accounts_store.store_token(second.id, "token-2")

    assert accounts_store.token_for(first.id) == "token-1"
    assert accounts_store.token_for(second.id) == "token-2"


def test_a_broken_credential_marks_only_its_own_account(fake_keyring: Any) -> None:
    first = accounts_store.create_account(label="First", ig_user_id="17841400000000001")
    second = accounts_store.create_account(label="Second", ig_user_id="17841400000000002")

    accounts_store.mark_needs_reconnect(first.id, "Meta rejected the token.")

    assert accounts_store.get_account(first.id).needs_reconnect is True
    assert accounts_store.get_account(second.id).needs_reconnect is False


def test_the_token_is_filed_under_the_account_own_keyring_entry(
    fake_keyring: Any,
) -> None:
    account = accounts_store.create_account(label="First", ig_user_id="17841400000000001")

    accounts_store.store_token(account.id, "token-1")

    assert accounts_store.token_entry(account.id) == f"instagram_token#{account.id}"
    assert accounts_store.token_for(account.id) == "token-1"


def test_the_oldest_account_is_the_default_one(fake_keyring: Any) -> None:
    first = accounts_store.create_account(label="First", ig_user_id="17841400000000001")
    accounts_store.create_account(label="Second", ig_user_id="17841400000000002")

    assert accounts_store.default_account().id == first.id


# --------------------------------------------------------------------------
# The OAuth URLs
# --------------------------------------------------------------------------


def test_the_unified_authorisation_url_asks_for_no_version(fake_keyring: Any) -> None:
    settings = _settings()
    fake_keyring.set_password("autoclip", config.INSTAGRAM_APP_SECRET_KEY, "the-secret")

    url = oauth.build_auth_url(settings)

    # Meta's documented Facebook Login for Business URL has no version
    # in the path.
    assert url.startswith("https://www.facebook.com/dialog/oauth?")
    assert "/v" not in url.split("?")[0]


def test_the_authorisation_url_is_bound_to_the_account(fake_keyring: Any) -> None:
    settings = _settings()
    fake_keyring.set_password("autoclip", config.INSTAGRAM_APP_SECRET_KEY, "the-secret")
    account = accounts_store.create_account(label="First", ig_user_id="17841")

    oauth.build_auth_url(settings, account_id=account.id)

    pending = list(oauth._pending.values())
    assert len(pending) == 1
    assert pending[0].account_id == account.id


def test_a_state_can_only_be_used_once(fake_keyring: Any, monkeypatch: pytest.MonkeyPatch) -> None:
    settings = _settings()
    fake_keyring.set_password("autoclip", config.INSTAGRAM_APP_SECRET_KEY, "the-secret")

    monkeypatch.setattr(oauth, "_exchange_facebook_code", lambda **kwargs: "token-abc")
    monkeypatch.setattr(
        oauth,
        "_discover_facebook_accounts",
        lambda **kwargs: ("17841400000000001", "player", "Player", "", "biz-1"),
    )

    url = oauth.build_auth_url(settings)
    state = url.split("state=")[1].split("&")[0]

    result = oauth.complete_auth("code", state, settings)

    assert result["id"] == "17841400000000001"
    assert result["username"] == "player"

    with pytest.raises(oauth.OAuthError):
        oauth.complete_auth("code", state, settings)


def test_an_unknown_state_is_refused(fake_keyring: Any) -> None:
    with pytest.raises(oauth.OAuthError):
        oauth.complete_auth("code", "not-a-real-state", _settings())


def test_the_instagram_setup_has_no_resumable_upload() -> None:
    assert oauth.setup_for("instagram").resumable_upload is False
    assert oauth.setup_for("unified").resumable_upload is True
    assert oauth.setup_for("facebook").resumable_upload is True


def test_each_setup_asks_only_for_what_it_publishes_with() -> None:
    assert oauth.setup_for("unified").scopes == (
        "instagram_basic",
        "instagram_content_publish",
    )
    assert oauth.setup_for("facebook").scopes == (
        "instagram_basic",
        "instagram_content_publish",
        "pages_read_engagement",
    )
    assert oauth.setup_for("instagram").scopes == (
        "instagram_business_basic",
        "instagram_business_content_publish",
    )


# --------------------------------------------------------------------------
# The ambiguous result
# --------------------------------------------------------------------------


def test_a_publish_that_lost_its_answer_is_not_sent_again(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The request may have reached Instagram.

    A row in this state is neither failed nor retried: sending it again
    could post the clip twice. It waits for the owner.
    """
    account = _account()
    _, _, _, export = _export_row(str(tmp_path / "clip.mp4"))
    row = uploads.enqueue(export.id, account_row_id=account.id)

    async def fail(upload: Any, settings: Any) -> str:
        raise InstagramError(
            "Could not reach Instagram: the connection dropped.",
            transient=True,
            needs_reconciliation=True,
        )

    monkeypatch.setattr(uploads, "process_upload", fail)

    queue = InstagramUploadQueue()
    asyncio.run(queue._run(row.id))

    fresh = store.get_instagram_upload(row.id)
    assert fresh is not None
    assert fresh.status == "needs_reconciliation"
    # Not pending either: the backoff would have sent it again.
    assert fresh.next_attempt_at == ""


def test_the_owner_can_confirm_a_post_instagram_already_has(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, fake_keyring: Any
) -> None:
    """The owner looked at Instagram's page and saw the post."""
    account = _account()
    accounts_store.store_token(account.id, "token")
    _, _, _, export = _export_row(str(tmp_path / "clip.mp4"))
    row = uploads.enqueue(export.id, account_row_id=account.id)
    store.update_instagram_upload(row.id, status="needs_reconciliation", error="no answer")

    monkeypatch.setattr(
        publisher,
        "read_back",
        lambda *a, **k: publisher.PublishedMedia(
            id="post-1", permalink="https://www.instagram.com/p/post-1/"
        ),
    )

    fresh = uploads.confirm_upload(row.id, "post-1")

    assert fresh is not None
    assert fresh.status == "done"
    assert fresh.media_id == "post-1"
    assert fresh.permalink == "https://www.instagram.com/p/post-1/"
    assert fresh.reconcile_status == "owner_confirmed"


def test_a_media_id_instagram_does_not_know_is_refused(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, fake_keyring: Any
) -> None:
    """The owner's word is checked. A wrong id cannot mark a post published."""
    account = _account()
    accounts_store.store_token(account.id, "token")
    _, _, _, export = _export_row(str(tmp_path / "clip.mp4"))
    row = uploads.enqueue(export.id, account_row_id=account.id)
    store.update_instagram_upload(row.id, status="needs_reconciliation", error="no answer")

    monkeypatch.setattr(
        publisher,
        "read_back",
        lambda *a, **k: publisher.PublishedMedia(id=""),
    )

    with pytest.raises(InstagramError) as caught:
        uploads.confirm_upload(row.id, "made-up")

    assert "does not recognise" in str(caught.value)
    fresh = store.get_instagram_upload(row.id)
    assert fresh is not None
    assert fresh.status == "needs_reconciliation"


def test_the_confirm_endpoint_refuses_a_media_id_instagram_does_not_know(
    client: TestClient, monkeypatch: pytest.MonkeyPatch, fake_keyring: Any
) -> None:
    account = accounts_store.create_account(label="Test", ig_user_id="17841")
    accounts_store.store_token(account.id, "token")
    _, _, _, export = _export_row()
    row = uploads.enqueue(export.id, account_row_id=account.id)
    store.update_instagram_upload(row.id, status="needs_reconciliation", error="no answer")

    monkeypatch.setattr(
        publisher,
        "read_back",
        lambda *a, **k: publisher.PublishedMedia(id=""),
    )

    response = client.put(
        f"/api/instagram/uploads/{row.id}/confirm",
        json={"media_id": "made-up"},
    )

    assert response.status_code == 409
    assert "does not recognise" in response.json()["detail"]


def test_the_confirm_endpoint_records_a_post_instagram_already_has(
    client: TestClient, monkeypatch: pytest.MonkeyPatch, fake_keyring: Any
) -> None:
    account = accounts_store.create_account(label="Test", ig_user_id="17841")
    accounts_store.store_token(account.id, "token")
    _, _, _, export = _export_row()
    row = uploads.enqueue(export.id, account_row_id=account.id)
    store.update_instagram_upload(row.id, status="needs_reconciliation", error="no answer")

    monkeypatch.setattr(
        publisher,
        "read_back",
        lambda *a, **k: publisher.PublishedMedia(
            id="post-1", permalink="https://www.instagram.com/p/post-1/"
        ),
    )

    response = client.put(
        f"/api/instagram/uploads/{row.id}/confirm",
        json={"media_id": "post-1"},
    )

    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "done"
    assert body["media_id"] == "post-1"
    assert body["permalink"] == "https://www.instagram.com/p/post-1/"


def test_a_publish_that_lost_its_answer_is_flagged_as_ambiguous(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A dropped connection during the publish is not a plain failure."""
    account = _account()

    def drop(*args: Any, **kwargs: Any) -> dict[str, Any]:
        raise InstagramError("Could not reach Instagram: timeout.", transient=True)

    monkeypatch.setattr(publisher, "_post_json", drop)

    with pytest.raises(InstagramError) as caught:
        publisher.publish(
            config.Settings(),
            account,
            token="token",
            container_id="container-1",
        )

    assert caught.value.needs_reconciliation is True
    assert caught.value.transient is True


def test_a_graph_refusal_during_the_publish_is_not_ambiguous(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Meta said no. That is a definite answer, so it is not a lost answer."""
    account = _account()

    def refuse(*args: Any, **kwargs: Any) -> dict[str, Any]:
        raise OwnerActionRequired("Your account is restricted.")

    monkeypatch.setattr(publisher, "_post_json", refuse)

    with pytest.raises(InstagramError) as caught:
        publisher.publish(
            config.Settings(),
            account,
            token="token",
            container_id="container-1",
        )

    assert caught.value.needs_reconciliation is False
    assert caught.value.owner_action_required is True


# --------------------------------------------------------------------------
# The settings and the clip list
# --------------------------------------------------------------------------


def test_the_settings_carry_the_instagram_connection(client: TestClient) -> None:
    """The screen needs the app id and the login type to show what is set."""
    settings = config.load()
    settings.instagram.app_id = "1234567890"
    settings.instagram.login_type = "facebook"
    config.save(settings)

    body = client.get("/api/settings").json()

    assert body["instagram"]["app_id"] == "1234567890"
    assert body["instagram"]["login_type"] == "facebook"
    assert body["instagram"]["api_version"] == "v27.0"


def test_the_settings_report_the_app_secret_without_its_value(
    client: TestClient, fake_keyring: Any
) -> None:
    fake_keyring.set_password("autoclip", config.INSTAGRAM_APP_SECRET_KEY, "the-secret")

    body = client.get("/api/settings").json()

    assert body["instagram_secret_present"] is True
    assert "the-secret" not in client.get("/api/settings").text


def test_the_app_secret_can_be_stored(client: TestClient) -> None:
    response = client.put(
        "/api/settings/secrets",
        json={"key": config.INSTAGRAM_APP_SECRET_KEY, "value": "the-secret"},
    )

    assert response.status_code == 204


def test_automation_cannot_be_turned_on_through_the_settings_without_an_account(
    client: TestClient,
) -> None:
    """The settings page must not be a way around the connection check."""
    response = client.put("/api/settings", json={"instagram": {"auto_upload": True}})

    assert response.status_code == 400
    assert "Connect an Instagram account" in response.json()["detail"]


def test_a_clip_carries_its_instagram_posts(client: TestClient) -> None:
    """The clip list shows the Instagram state, so the rows have to be there."""
    account = accounts_store.create_account(label="Test", ig_user_id="17841")
    _, _, clip, export = _export_row()
    row = uploads.enqueue(export.id, account_row_id=account.id, caption="Hello")

    body = client.get(f"/api/clips/{clip.id}").json()

    export_out = next(e for e in body["exports"] if e["id"] == export.id)
    assert [u["id"] for u in export_out["instagram_uploads"]] == [row.id]
    assert export_out["instagram_uploads"][0]["caption"] == "Hello"


def test_a_clip_without_instagram_posts_has_an_empty_list(client: TestClient) -> None:
    """YouTube rows and Instagram rows are separate; neither leaks into the other."""
    _, _, clip, _ = _export_row()

    body = client.get(f"/api/clips/{clip.id}").json()

    export_out = body["exports"][0]
    assert export_out["instagram_uploads"] == []
    assert export_out["uploads"] == []
