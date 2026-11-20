"""Phase 10 — multi-channel publishing fan-out."""

from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

import pytest
from autoclip import config
from autoclip.config import Settings
from autoclip.db import store
from autoclip.db.models import Clip, Export, Job, Source, YouTubeUpload, new_id
from autoclip.routing import classifier
from autoclip.youtube import accounts as accounts_store
from autoclip.youtube import duplicates, metadata, oauth, uploader, uploads

# --------------------------------------------------------------------------
# Migration
# --------------------------------------------------------------------------


def test_migration_v9_adds_fan_out_columns(initialised_db: int) -> None:
    with store.connection() as conn:
        version = conn.execute("PRAGMA user_version").fetchone()[0]
        upload_cols = {r[1] for r in conn.execute("PRAGMA table_info(youtube_uploads)")}
        channel_cols = {r[1] for r in conn.execute("PRAGMA table_info(youtube_channels)")}
        rule_cols = {r[1] for r in conn.execute("PRAGMA table_info(routing_rules)")}
    assert version >= 9
    assert "channel_row_id" in upload_cols
    assert "title_suffix" in channel_cols
    assert "extra_channel_ids_json" in rule_cols


# --------------------------------------------------------------------------
# Helpers
# --------------------------------------------------------------------------


def _seed_clip() -> tuple[Source, Job, Clip]:
    source = Source(
        id=new_id(), type="upload", path="C:/videos/source.mp4", title="source", duration_s=120.0
    )
    store.create_source(source)
    job = Job(id=new_id(), source_id=source.id, status="done")
    store.create_job(job)
    clip = Clip(id=new_id(), job_id=job.id, start_s=1.0, end_s=20.0, rank=1)
    store.replace_clips(job.id, [clip])
    return source, job, clip


def _account_with_channels(*, suffix: str = "") -> tuple[dict, dict, dict]:
    account = accounts_store.create_account(label="main", email="main@example.com")
    primary = accounts_store.add_channel(
        account["id"],
        {"id": "UC_primary", "title": "Primary", "url": ""},
        auto_upload=True,
        title_suffix=suffix,
        made_for_kids="false",
    )
    extra = accounts_store.add_channel(
        account["id"],
        {"id": "UC_extra", "title": "Extra", "url": ""},
        auto_upload=True,
        made_for_kids="false",
    )
    return account, primary, extra


def _settings() -> Settings:
    settings = Settings()
    settings.youtube.auto_upload = True
    settings.youtube.privacy = "public"
    settings.youtube.category_id = "24"
    return settings


# --------------------------------------------------------------------------
# Fan-out targets
# --------------------------------------------------------------------------


def test_disabled_channel_is_excluded_from_fan_out(initialised_db: int) -> None:
    _, _, clip = _seed_clip()
    account, primary, extra = _account_with_channels()
    accounts_store.update_channel(extra["id"], auto_upload=False)
    classifier.save_classification(
        clip.id,
        {"category": "gaming", "confidence": 0.9, "provider": "test", "reason": ""},
    )
    classifier.add_rule("gaming", primary["id"], extra_channel_ids=[extra["id"]])

    targets = classifier.resolve_target_channels(clip.id)
    assert [t["id"] for t in targets] == [primary["id"]]


def test_rule_with_extra_channels_fans_out(initialised_db: int) -> None:
    _, _, clip = _seed_clip()
    account, primary, extra = _account_with_channels()
    export = Export(id=new_id(), clip_id=clip.id, path="C:/out.mp4")
    store.create_export(export)
    classifier.save_classification(
        clip.id,
        {"category": "gaming", "confidence": 0.9, "provider": "test", "reason": ""},
    )
    classifier.add_rule("gaming", primary["id"], extra_channel_ids=[extra["id"]])

    settings = _settings()
    rows = _enqueue_with_connection(export.id, settings)

    assert len(rows) == 2
    assert {row.channel_row_id for row in rows} == {primary["id"], extra["id"]}
    assert len({row.id for row in rows}) == 2
    # Re-enqueueing is idempotent per channel.
    assert len(_enqueue_with_connection(export.id, settings)) == 2


def test_no_channel_profiles_keeps_legacy_single_upload(initialised_db: int) -> None:
    _, _, clip = _seed_clip()
    export = Export(id=new_id(), clip_id=clip.id, path="C:/out.mp4")
    store.create_export(export)

    rows = _enqueue_with_connection(export.id, _settings())
    assert len(rows) == 1
    assert rows[0].channel_row_id == ""


def _enqueue_with_connection(export_id: str, settings: Settings) -> list[YouTubeUpload]:
    original = oauth.is_connected
    oauth.is_connected = lambda _settings=None: True  # type: ignore[assignment]
    try:
        return uploads.enqueue_export_all(export_id, settings)
    finally:
        oauth.is_connected = original  # type: ignore[assignment]


# --------------------------------------------------------------------------
# Account-scoped tokens
# --------------------------------------------------------------------------


def test_access_token_uses_the_account_refresh_token(
    initialised_db: int, monkeypatch: pytest.MonkeyPatch
) -> None:
    oauth._tokens_by_account.clear()
    calls: list[tuple[str, str]] = []
    monkeypatch.setattr(
        accounts_store,
        "refresh_token_for",
        lambda account_id, settings=None: {
            "acct-a": "refresh-a",
            "acct-b": "refresh-b",
        }[account_id],
    )

    def fake_post(payload):
        calls.append((payload["refresh_token"], payload["client_secret"]))
        return {"access_token": f"access-{payload['refresh_token']}", "expires_in": 3600}

    monkeypatch.setattr(oauth, "_post_token", fake_post)

    settings = config.load()
    settings.youtube.client_id = "client"
    monkeypatch.setattr(config, "get_secret", lambda key, settings=None: "secret")

    assert oauth.access_token(settings, account_id="acct-a") == "access-refresh-a"
    assert oauth.access_token(settings, account_id="acct-b") == "access-refresh-b"
    # Cached: a second call does not refresh again.
    assert oauth.access_token(settings, account_id="acct-a") == "access-refresh-a"
    assert [c[0] for c in calls] == ["refresh-a", "refresh-b"]


# --------------------------------------------------------------------------
# Duplicate scoping
# --------------------------------------------------------------------------


def test_duplicates_are_scoped_per_channel(initialised_db: int) -> None:
    _, _, clip = _seed_clip()
    export = Export(id=new_id(), clip_id=clip.id, path="C:/out.mp4")
    store.create_export(export)
    done = store.create_upload(
        YouTubeUpload(
            id=new_id(),
            export_id=export.id,
            clip_id=clip.id,
            channel_row_id="channel-a",
            status="done",
            video_id="vid-a",
        )
    )
    other_export = Export(id=new_id(), clip_id=clip.id, path="C:/out2.mp4")
    store.create_export(other_export)
    same_channel = store.create_upload(
        YouTubeUpload(
            id=new_id(),
            export_id=other_export.id,
            clip_id=clip.id,
            channel_row_id="channel-a",
            status="pending",
        )
    )
    other_channel = store.create_upload(
        YouTubeUpload(
            id=new_id(),
            export_id=other_export.id,
            clip_id=clip.id,
            channel_row_id="channel-b",
            status="pending",
        )
    )

    assert duplicates.conflict_for(same_channel) is not None
    assert duplicates.conflict_for(other_channel) is None
    assert done.id != other_channel.id


def test_legacy_row_and_its_channel_profile_are_one_destination(
    initialised_db: int,
) -> None:
    """The legacy row and the imported profile are the same YouTube channel.

    A re-export of an already-published clip must not publish a second copy,
    even though one row stores the legacy '' and the other names the channel
    profile.
    """
    _, _, clip = _seed_clip()
    account, primary, _extra = _account_with_channels()

    settings = config.load()
    settings.youtube.channel_id = primary["channel_id"]
    config.save(settings)

    legacy_export = Export(id=new_id(), clip_id=clip.id, path="C:/out.mp4")
    store.create_export(legacy_export)
    store.create_upload(
        YouTubeUpload(
            id=new_id(),
            export_id=legacy_export.id,
            clip_id=clip.id,
            channel_row_id="",
            status="done",
            video_id="vid-legacy",
        )
    )

    new_export = Export(id=new_id(), clip_id=clip.id, path="C:/out2.mp4")
    store.create_export(new_export)
    pending = store.create_upload(
        YouTubeUpload(
            id=new_id(),
            export_id=new_export.id,
            clip_id=clip.id,
            channel_row_id=primary["id"],
            status="pending",
        )
    )

    assert account["id"]
    assert duplicates.destination_channel_id("") == primary["channel_id"]
    assert duplicates.destination_channel_id(primary["id"]) == primary["channel_id"]
    assert duplicates.conflict_for(pending) is not None


# --------------------------------------------------------------------------
# Channel-aware worker
# --------------------------------------------------------------------------


def test_retry_keeps_the_rows_own_privacy(initialised_db: int) -> None:
    """A retry must not re-read the channel's current privacy.

    The row records the privacy the owner was shown when the upload was
    queued. A retry used to overwrite it with the channel's *current*
    privacy, which meant a clip could go out under a privacy nobody
    chose for it — a silent change, which is exactly what the publishing
    policy forbids.
    """
    _, _, clip = _seed_clip()
    account, channel, _ = _account_with_channels()
    export = Export(id=new_id(), clip_id=clip.id, path="C:/out.mp4")
    store.create_export(export)
    row = store.create_upload(
        YouTubeUpload(
            id=new_id(),
            export_id=export.id,
            clip_id=clip.id,
            channel_row_id=channel["id"],
            status="failed",
            error="boom",
            privacy="unlisted",
        )
    )
    accounts_store.update_channel(channel["id"], privacy="public")

    settings = _settings()
    settings.youtube.privacy = "public"
    retried = uploads.retry_upload(row.id, settings)

    assert retried is not None and retried.status == "pending"
    # The row's own privacy survives the retry.
    assert retried.privacy == "unlisted"


async def test_process_upload_uses_the_row_channel_and_suffix(
    initialised_db: int, monkeypatch: pytest.MonkeyPatch
) -> None:
    _, _, clip = _seed_clip()
    account, channel, _ = _account_with_channels(suffix="#Shorts")
    export = Export(id=new_id(), clip_id=clip.id, path="C:/out.mp4")
    store.create_export(export)
    row = store.create_upload(
        YouTubeUpload(
            id=new_id(),
            export_id=export.id,
            clip_id=clip.id,
            channel_row_id=channel["id"],
            privacy="unlisted",
        )
    )

    clip_obj = SimpleNamespace(
        id=clip.id,
        job_id=clip.job_id,
        title="Steak",
        hook="",
        reason="",
        start_word=0,
        end_word=3,
        duration_s=40.0,
    )
    monkeypatch.setattr(uploads.store, "get_export", lambda _: export)
    monkeypatch.setattr(uploads.store, "get_clip", lambda _: clip_obj)
    monkeypatch.setattr(uploads.store, "get_transcript", lambda _: None)
    monkeypatch.setattr(uploads.store, "list_all_uploads", lambda: [])
    monkeypatch.setattr(Path, "is_file", lambda self: True)
    monkeypatch.setattr(uploads.store, "update_upload", lambda *a, **k: None)
    monkeypatch.setattr(uploads, "_thumbnail_for", lambda *a, **k: None)

    async def fake_metadata(provider, **kwargs):
        return metadata.ClipMetadata(title="AI title", description="", tags=[])

    monkeypatch.setattr(metadata, "generate_metadata", fake_metadata)

    captured: dict = {}

    def fake_upload(settings, **kwargs):
        captured.update(kwargs)
        return "vid-1"

    monkeypatch.setattr(uploader, "upload_video", fake_upload)

    await uploads.process_upload(row, config.load())

    assert captured["account_id"] == account["id"]
    assert captured["privacy"] == "unlisted"
    assert captured["metadata"].title == "AI title #Shorts"


def test_channel_title_suffix_round_trips(initialised_db: int) -> None:
    _, channel, _ = _account_with_channels()
    updated = accounts_store.update_channel(channel["id"], title_suffix=" | Clips")
    assert updated is not None and updated["title_suffix"] == " | Clips"
    assert accounts_store.get_channel(channel["id"])["title_suffix"] == " | Clips"
