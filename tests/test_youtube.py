"""YouTube metadata, OAuth, upload delivery, and the API surface."""

from __future__ import annotations

from collections.abc import Iterator
from pathlib import Path
from types import SimpleNamespace
from urllib.parse import parse_qs, urlparse

import pytest
from autoclip import app as app_module
from autoclip import config
from autoclip.app import create_app
from autoclip.db.models import YouTubeUpload, new_id
from autoclip.pipeline.transcript import Word
from autoclip.youtube import metadata, oauth, uploader, uploads
from fastapi.testclient import TestClient


class FakeKeyring:
    def __init__(self) -> None:
        self.store: dict[tuple[str, str], str] = {}

    def get_password(self, service: str, key: str) -> str | None:
        return self.store.get((service, key))

    def set_password(self, service: str, key: str, value: str) -> None:
        self.store[(service, key)] = value

    def delete_password(self, service: str, key: str) -> None:
        self.store.pop((service, key), None)


@pytest.fixture
def client(autoclip_home: Path, monkeypatch: pytest.MonkeyPatch) -> Iterator[TestClient]:
    monkeypatch.setenv(app_module.ENV_NO_WORKER, "1")
    with TestClient(create_app()) as test_client:
        yield test_client


def _words() -> list[Word]:
    text = "The trick is to preheat the pan before the steak ever touches it"
    words: list[Word] = []
    for index, token in enumerate(text.split()):
        words.append(Word(text=token, start=index * 0.4, end=index * 0.4 + 0.35))
    return words


# --------------------------------------------------------------------------
# Metadata
# --------------------------------------------------------------------------


def test_metadata_clamps_title_and_adds_shorts() -> None:
    payload = {
        "title": "A " * 80,
        "description": "A quick steak trick.",
        "tags": ["#Steak", "COOKING", "Steak"],
    }

    result = metadata.sanitize_metadata(payload, title="Steak", words=_words(), duration_s=45.0)

    assert len(result.title) <= metadata.TITLE_LIMIT
    assert "steak" in result.tags
    assert "shorts" in result.tags
    assert result.tags.count("steak") == 1
    assert "#shorts" in result.description.lower()


def test_metadata_falls_back_field_by_field() -> None:
    result = metadata.sanitize_metadata({}, title="", words=_words(), duration_s=30.0)

    assert result.title
    assert result.tags
    assert result.description


def test_metadata_tags_respect_the_character_budget() -> None:
    payload = {"tags": [f"tag-{index}-" + "x" * 25 for index in range(40)]}
    result = metadata.sanitize_metadata(payload, title="T", words=_words(), duration_s=400.0)

    assert sum(len(tag) + 2 for tag in result.tags) <= metadata.TAGS_CHAR_BUDGET + 2
    assert "shorts" not in result.tags


# --------------------------------------------------------------------------
# OAuth
# --------------------------------------------------------------------------


def _configure(monkeypatch: pytest.MonkeyPatch) -> config.Settings:
    kr = FakeKeyring()
    monkeypatch.setattr(config, "_keyring", lambda: kr)
    settings = config.load()
    settings.youtube.client_id = "client-id.apps.googleusercontent.com"
    settings.youtube.redirect_uri = "http://localhost:8000/api/youtube/callback"
    config.save(settings)
    config.set_secret(config.YOUTUBE_CLIENT_SECRET_KEY, "secret-value", settings)
    return settings


def test_auth_url_uses_pkce_and_registered_redirect(
    initialised_db: int, monkeypatch: pytest.MonkeyPatch
) -> None:
    settings = _configure(monkeypatch)
    url = oauth.build_auth_url(settings)
    parsed = urlparse(url)
    params = parse_qs(parsed.query)

    assert parsed.netloc == "accounts.google.com"
    assert params["redirect_uri"] == [settings.youtube.redirect_uri]
    assert params["code_challenge_method"] == ["S256"]
    assert params["access_type"] == ["offline"]
    assert "youtube.upload" in params["scope"][0]
    assert params["state"][0]


def test_auth_url_requires_credentials(
    initialised_db: int, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(config, "_keyring", lambda: FakeKeyring())
    with pytest.raises(oauth.OAuthError):
        oauth.build_auth_url(config.load())


def test_complete_auth_rejects_unknown_state(
    initialised_db: int, monkeypatch: pytest.MonkeyPatch
) -> None:
    settings = _configure(monkeypatch)
    with pytest.raises(oauth.OAuthError):
        oauth.complete_auth("code", "not-a-real-state", settings)


# --------------------------------------------------------------------------
# Enqueue gating
# --------------------------------------------------------------------------


def test_enqueue_skips_when_automation_is_off(monkeypatch: pytest.MonkeyPatch) -> None:
    settings = config.load()
    settings.youtube.auto_upload = False
    monkeypatch.setattr(oauth, "is_connected", lambda _=None: True)

    assert uploads.enqueue_export("export-id", settings) is None


def test_enqueue_skips_when_no_channel(monkeypatch: pytest.MonkeyPatch) -> None:
    settings = config.load()
    settings.youtube.auto_upload = True
    monkeypatch.setattr(oauth, "is_connected", lambda _=None: False)

    assert uploads.enqueue_export("export-id", settings) is None


def test_enqueue_creates_a_pending_row(monkeypatch: pytest.MonkeyPatch) -> None:
    settings = config.load()
    settings.youtube.auto_upload = True
    settings.youtube.privacy = "unlisted"
    monkeypatch.setattr(oauth, "is_connected", lambda _=None: True)
    monkeypatch.setattr(
        uploads.store, "get_export", lambda export_id: SimpleNamespace(id=export_id, clip_id="clip")
    )

    created: list[YouTubeUpload] = []
    monkeypatch.setattr(uploads.store, "create_upload", lambda row: created.append(row) or row)

    row = uploads.enqueue_export("export-1", settings)

    assert row is not None and row is created[0]
    assert row.export_id == "export-1"
    assert row.status == "pending"
    assert row.privacy == "unlisted"


# --------------------------------------------------------------------------
# Upload delivery
# --------------------------------------------------------------------------


class _Response:
    def __init__(self, status: int, *, body: dict | None = None, headers: dict | None = None):
        self.status_code = status
        self._body = body or {}
        self.headers = headers or {}

    def json(self) -> dict:
        return self._body


def test_upload_video_posts_metadata_then_the_file(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    file = tmp_path / "clip.mp4"
    file.write_bytes(b"video-bytes")
    settings = config.load()
    monkeypatch.setattr(oauth, "access_token", lambda _=None, account_id=None: "token")

    calls: dict[str, dict] = {}

    def fake_post(url, **kwargs):
        calls["post"] = kwargs
        return _Response(200, headers={"location": "https://upload.example/session"})

    def fake_put(url, **kwargs):
        calls["put"] = {"url": url}
        return _Response(200, body={"id": "abc123"})

    monkeypatch.setattr(uploader.httpx, "post", fake_post)
    monkeypatch.setattr(uploader.httpx, "put", fake_put)

    result = uploader.upload_video(
        settings,
        path=file,
        metadata=metadata.ClipMetadata(title="Title", description="Desc", tags=["a"]),
        privacy="public",
        language="en",
    )

    assert result == "abc123"
    assert calls["post"]["json"]["status"]["privacyStatus"] == "public"
    assert calls["put"]["url"] == "https://upload.example/session"


async def test_process_upload_reuses_generated_metadata(monkeypatch: pytest.MonkeyPatch) -> None:
    row = YouTubeUpload(id=new_id(), export_id="export-1", clip_id="clip-1", privacy="public")
    export = SimpleNamespace(id="export-1", clip_id="clip-1", path="clip.mp4")
    clip = SimpleNamespace(
        job_id="job-1",
        title="Steak",
        hook="",
        reason="",
        start_word=0,
        end_word=3,
        duration_s=40.0,
    )

    monkeypatch.setattr(uploads.store, "get_export", lambda _: export)
    monkeypatch.setattr(uploads.store, "get_clip", lambda _: clip)
    monkeypatch.setattr(uploads.store, "get_transcript", lambda _: None)
    monkeypatch.setattr(uploads.store, "list_all_uploads", lambda: [])
    monkeypatch.setattr(Path, "is_file", lambda self: True)

    updates: list[dict] = []
    monkeypatch.setattr(
        uploads.store,
        "update_upload",
        lambda upload_id, **kwargs: updates.append({upload_id: kwargs}),
    )

    async def fake_metadata(provider, **kwargs):
        return metadata.ClipMetadata(title="AI title", description="AI description", tags=["ai"])

    monkeypatch.setattr(metadata, "generate_metadata", fake_metadata)

    captured: dict = {}

    def fake_upload(settings, **kwargs):
        captured.update(kwargs)
        return "vid-1"

    monkeypatch.setattr(uploader, "upload_video", fake_upload)

    video_id = await uploads.process_upload(row, config.load())

    assert video_id == "vid-1"
    assert captured["metadata"].title == "AI title"
    assert updates and updates[0][row.id]["title"] == "AI title"


# --------------------------------------------------------------------------
# API
# --------------------------------------------------------------------------


def test_status_reports_an_unconfigured_channel(client: TestClient) -> None:
    body = client.get("/api/youtube/status").json()

    assert body["connected"] is False
    assert body["auto_upload"] is False
    assert "privacy" in body


def test_auto_upload_requires_a_connection(client: TestClient) -> None:
    response = client.post("/api/youtube/auto-upload", json={"enabled": True})

    assert response.status_code == 400
    assert "Connect" in response.json()["detail"]


def test_connect_without_credentials_is_a_clear_400(client: TestClient) -> None:
    response = client.post("/api/youtube/connect")

    assert response.status_code == 400


def test_retry_unknown_upload_is_404(client: TestClient) -> None:
    assert client.post("/api/youtube/uploads/missing/retry").status_code == 404


def test_settings_include_youtube_and_secret_presence(client: TestClient, fake_keyring) -> None:
    body = client.get("/api/settings").json()

    assert "youtube" in body
    assert body["youtube_secret_present"] is False
    assert body["youtube"]["privacy"] in {"private", "unlisted", "public"}


def test_youtube_client_secret_is_an_accepted_secret(client: TestClient, fake_keyring) -> None:
    response = client.put(
        "/api/settings/secrets",
        json={"key": config.YOUTUBE_CLIENT_SECRET_KEY, "value": "abc"},
    )

    assert response.status_code == 204
    assert config.get_secret(config.YOUTUBE_CLIENT_SECRET_KEY) == "abc"


def test_callback_without_code_renders_a_failure_page(client: TestClient) -> None:
    response = client.get("/api/youtube/callback")

    assert response.status_code == 400
    assert "failed" in response.text.lower()
