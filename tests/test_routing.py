"""Phase 5 â€” classification and routing rule tests (no network)."""

from __future__ import annotations

import pytest
from autoclip.routing import classifier
from autoclip.youtube import accounts as accounts_store


@pytest.fixture
def channels(initialised_db: int) -> tuple[dict, dict]:
    a1 = accounts_store.create_account(label="acc1")
    a2 = accounts_store.create_account(label="acc2")
    gaming = accounts_store.add_channel(a1["id"], {"id": "UC_game", "title": "Gaming"})
    main = accounts_store.add_channel(a2["id"], {"id": "UC_main", "title": "Main"})
    return gaming, main


@pytest.fixture
def clips(initialised_db: int) -> dict[str, str]:
    """Real clip rows so FK constraints hold."""
    from autoclip.db import store
    from autoclip.db.models import Clip, Job, Source, new_id

    source = store.create_source(
        Source(id=new_id(), type="youtube", url="https://youtu.be/x", path="/tmp/x.mp4")
    )
    job = store.create_job(Job(id=new_id(), source_id=source.id, provider=""))
    batch = [
        Clip(id=new_id(), job_id=job.id, start_s=float(i) * 10, end_s=float(i) * 10 + 5, rank=i)
        for i in range(6)
    ]
    saved = store.replace_clips(job.id, batch)
    keys = ("clip1", "clipX", "clipY", "clipZ", "clipW", "clipN")
    return dict(zip(keys, (c.id for c in saved), strict=True))


# --------------------------------------------------------------------------
# Migration
# --------------------------------------------------------------------------


def test_migration_v6_creates_tables(initialised_db: int) -> None:
    with classifier.connection() as conn:
        version = conn.execute("PRAGMA user_version").fetchone()[0]
        tables = {
            r[0]
            for r in conn.execute("SELECT name FROM sqlite_master WHERE type='table'").fetchall()
        }
    assert version >= 6
    assert {"content_classifications", "routing_rules"} <= tables


# --------------------------------------------------------------------------
# Rules CRUD
# --------------------------------------------------------------------------


def test_rule_crud_and_priority_order(channels) -> None:
    gaming, main = channels
    r1 = classifier.add_rule("gaming", gaming["id"], priority=10)
    r2 = classifier.add_rule("podcast", main["id"], priority=5)

    rules = classifier.list_rules()
    # Priority 5 sorts first.
    assert [r["id"] for r in rules] == [r2["id"], r1["id"]]

    updated = classifier.update_rule(r1["id"], priority=1)
    assert updated is not None and updated["priority"] == 1
    assert classifier.list_rules()[0]["id"] == r1["id"]

    classifier.delete_rule(r2["id"])
    assert classifier.get_rule(r2["id"]) is None


def test_keywords_are_lowercased(channels) -> None:
    gaming, _ = channels
    rule = classifier.add_rule("GAMING", gaming["id"])
    assert rule["match_keyword"] == "gaming"


# --------------------------------------------------------------------------
# Classification persistence
# --------------------------------------------------------------------------


def test_classification_roundtrip(initialised_db: int, clips: dict[str, str]) -> None:
    result = {
        "category": "gaming",
        "confidence": 0.9,
        "provider": "gemini",
        "reason": "game commentary",
    }
    classifier.save_classification(clips["clip1"], result)
    got = classifier.classification_for(clips["clip1"])
    assert got is not None
    assert got["category"] == "gaming"
    assert got["confidence"] == 0.9

    # A second classification wins.
    classifier.save_classification(clips["clip1"], {**result, "category": "podcast"})
    assert classifier.classification_for(clips["clip1"])["category"] == "podcast"  # type: ignore[index]


def test_classification_for_missing_clip(initialised_db: int) -> None:
    assert classifier.classification_for("nope") is None


# --------------------------------------------------------------------------
# Routing decision
# --------------------------------------------------------------------------


def test_rule_match_routes_to_target_channel(channels, clips) -> None:
    gaming, _ = channels
    classifier.add_rule("gaming", gaming["id"], priority=1)
    classifier.save_classification(
        clips["clipX"],
        {
            "category": "gaming",
            "confidence": 0.9,
            "provider": "test",
            "reason": "",
        },
    )
    target = classifier.resolve_target_channel(clips["clipX"])
    assert target is not None
    assert target["channel_id"] == "UC_game"


def test_no_match_falls_back_to_default(channels, clips) -> None:
    gaming, main = channels
    # main is the second account's only channel -> its default
    classifier.add_rule("gaming", gaming["id"])
    classifier.save_classification(
        clips["clipY"],
        {
            "category": "cooking",
            "confidence": 0.9,
            "provider": "test",
            "reason": "",
        },
    )
    target = classifier.resolve_target_channel(clips["clipY"])
    assert target is not None
    # No rule matched cooking â†’ the global default (first channel created).
    assert target["channel_id"] in {"UC_game", "UC_main"}


def test_disabled_rules_are_ignored(channels, clips) -> None:
    gaming, _ = channels
    classifier.add_rule("gaming", gaming["id"], enabled=False)
    classifier.save_classification(
        clips["clipZ"],
        {
            "category": "gaming",
            "confidence": 0.9,
            "provider": "test",
            "reason": "",
        },
    )
    target = classifier.resolve_target_channel(clips["clipZ"])
    assert target is not None
    # The disabled rule was skipped; the fallback default channel answered.
    assert target["is_default"] is True


def test_first_matching_rule_by_priority_wins(channels, clips) -> None:
    gaming, main = channels
    classifier.add_rule("gaming", main["id"], priority=10)
    classifier.add_rule("gaming", gaming["id"], priority=1)
    classifier.save_classification(
        clips["clipW"],
        {
            "category": "gaming",
            "confidence": 0.9,
            "provider": "test",
            "reason": "",
        },
    )
    target = classifier.resolve_target_channel(clips["clipW"])
    assert target is not None
    assert target["channel_id"] == "UC_game"


def test_no_rules_routes_to_default(channels, clips) -> None:
    _gaming, _main = channels
    target = classifier.resolve_target_channel(clips["clipN"])
    assert target is not None
    assert target["is_default"] is True


def test_no_channels_returns_none(initialised_db: int) -> None:
    assert classifier.resolve_target_channel("clip_none") is None


# --------------------------------------------------------------------------
# Classifier sync wrapper (provider path mocked)
# --------------------------------------------------------------------------


def test_classify_transcript_empty_returns_none(initialised_db: int) -> None:
    assert classifier.classify_transcript_sync("   ") is None


def test_classify_transcript_with_fake_provider(
    initialised_db: int, monkeypatch: pytest.MonkeyPatch, fake_keyring: object
) -> None:
    from autoclip.providers import resolver as res

    class _Fake:
        model = "fake"

        async def generate_text(self, system: str, user: str, *, temperature: float = 0.4) -> str:
            return '{"category": "podcast", "confidence": 0.8, "reason": "chat"}'

    def build(preset, settings, **kwargs):
        return _Fake()

    monkeypatch.setattr(res, "build_preset_provider", build)
    result = classifier.classify_transcript_sync("hello world", "clip")
    assert result is not None
    assert result["category"] == "podcast"
    assert result["provider"]
