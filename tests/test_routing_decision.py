"""The six-field routing explanation.

A routing decision has to answer one question in a way the owner can
read: which channel does this clip go to, and why? The answer is six
fields — category, channel, reason, rule, confidence and fallback —
and every one of them is stored, so the record of what was decided does
not depend on the rules still looking the same way afterwards.

These tests cover what the six fields say, that the explanation and the
destination cannot drift apart, and that the decision is recorded when
it is made.
"""

from __future__ import annotations

from collections.abc import Iterator
from pathlib import Path

import pytest
from autoclip import app as app_module
from autoclip.app import create_app
from autoclip.db import store
from autoclip.db.models import Clip, Job, Source, new_id
from autoclip.routing import classifier
from autoclip.routing import decision as decision_module
from autoclip.youtube import accounts as accounts_store
from fastapi.testclient import TestClient

# --------------------------------------------------------------------------
# Fixtures
# --------------------------------------------------------------------------


@pytest.fixture
def client(autoclip_home: Path, monkeypatch: pytest.MonkeyPatch) -> Iterator[TestClient]:
    monkeypatch.setenv(app_module.ENV_NO_WORKER, "1")
    with TestClient(create_app()) as test_client:
        yield test_client


@pytest.fixture
def channels(initialised_db: int) -> tuple[dict, dict]:
    """Two channels, each with auto-upload on so the fan-out includes them."""
    account = accounts_store.create_account(label="acc")
    gaming = accounts_store.add_channel(
        account["id"],
        {"id": "UC_game", "title": "Gaming channel"},
        auto_upload=True,
    )
    main = accounts_store.add_channel(
        account["id"],
        {"id": "UC_main", "title": "Main channel"},
        auto_upload=True,
    )
    return gaming, main


@pytest.fixture
def clip(initialised_db: int) -> str:
    """A real clip row, so the foreign keys hold."""
    source = store.create_source(
        Source(id=new_id(), type="upload", url="", path="/tmp/x.mp4", title="source")
    )
    job = store.create_job(Job(id=new_id(), source_id=source.id, provider=""))
    saved = store.replace_clips(
        job.id, [Clip(id=new_id(), job_id=job.id, start_s=0.0, end_s=5.0, rank=1)]
    )
    return saved[0].id


def _classify(clip_id: str, category: str, confidence: float = 0.9, reason: str = "") -> None:
    classifier.save_classification(
        clip_id,
        {
            "category": category,
            "confidence": confidence,
            "provider": "test",
            "reason": reason,
        },
    )


# --------------------------------------------------------------------------
# The six fields
# --------------------------------------------------------------------------


def test_a_matching_rule_fills_the_six_fields(channels: tuple[dict, dict], clip: str) -> None:
    gaming, _ = channels
    rule = classifier.add_rule("gaming", gaming["id"], name="Gameplay", priority=1)
    _classify(clip, "gaming", confidence=0.9, reason="game commentary")

    decision = decision_module.decide(clip)

    # category
    assert decision.category == "gaming"
    # channel
    assert decision.channel_row_id == gaming["id"]
    assert decision.channel_id == "UC_game"
    assert decision.channel_title == "Gaming channel"
    # reason
    assert "Gameplay" in decision.reason
    assert "gaming" in decision.reason
    # rule
    assert decision.rule_id == rule["id"]
    assert decision.rule == "Gameplay"
    assert decision.rule_keyword == "gaming"
    # confidence
    assert decision.confidence == 0.9
    # fallback
    assert decision.fallback is False
    assert decision.fallback_reason == ""


def test_the_rule_falls_back_to_its_keyword_when_it_has_no_name(
    channels: tuple[dict, dict], clip: str
) -> None:
    gaming, _ = channels
    classifier.add_rule("gaming", gaming["id"])
    _classify(clip, "gaming")

    decision = decision_module.decide(clip)

    assert decision.rule == "gaming"
    assert decision.rule_name == ""


def test_no_matching_rule_is_a_fallback(channels: tuple[dict, dict], clip: str) -> None:
    gaming, _ = channels
    classifier.add_rule("gaming", gaming["id"])
    _classify(clip, "cooking")

    decision = decision_module.decide(clip)

    assert decision.fallback is True
    assert decision.fallback_reason == "no rule matched"
    assert decision.rule_id == ""
    assert decision.rule == ""
    # The default channel answered.
    assert decision.channel_row_id != ""
    assert "default channel" in decision.reason


def test_an_unclassified_clip_says_so(channels: tuple[dict, dict], clip: str) -> None:
    decision = decision_module.decide(clip)

    assert decision.category == ""
    assert decision.confidence == 0.0
    assert decision.fallback is True
    assert decision.fallback_reason == "no classification"
    assert "not been classified" in decision.reason


def test_the_confidence_is_the_classifiers_own_number(
    channels: tuple[dict, dict], clip: str
) -> None:
    """It is the figure the model reported, not a score invented here."""
    gaming, _ = channels
    classifier.add_rule("gaming", gaming["id"])
    _classify(clip, "gaming", confidence=0.42)

    decision = decision_module.decide(clip)

    assert decision.confidence == 0.42
    assert "0.42" in decision.reason


def test_the_reason_quotes_the_classifier(channels: tuple[dict, dict], clip: str) -> None:
    gaming, _ = channels
    classifier.add_rule("gaming", gaming["id"])
    _classify(clip, "gaming", reason="a gameplay walkthrough")

    decision = decision_module.decide(clip)

    assert "a gameplay walkthrough" in decision.reason


def test_with_no_channels_at_all_the_decision_says_so(initialised_db: int, clip: str) -> None:
    decision = decision_module.decide(clip)

    assert decision.channel_row_id == ""
    assert decision.channel_id == ""
    assert "no channel to send it to" in decision.reason


# --------------------------------------------------------------------------
# The destination and the explanation cannot drift apart
# --------------------------------------------------------------------------


def test_the_decision_agrees_with_the_resolved_channel(
    channels: tuple[dict, dict], clip: str
) -> None:
    gaming, _ = channels
    classifier.add_rule("gaming", gaming["id"])
    _classify(clip, "gaming")

    target = classifier.resolve_target_channel(clip)
    decision = decision_module.decide(clip)

    assert target is not None
    assert decision.channel_row_id == target["id"]
    assert decision.channel_id == target["channel_id"]


def test_the_fanout_agrees_with_the_resolved_channels(
    channels: tuple[dict, dict], clip: str
) -> None:
    gaming, main = channels
    classifier.add_rule("gaming", gaming["id"], extra_channel_ids=[main["id"]])
    _classify(clip, "gaming")

    targets = classifier.resolve_target_channels(clip)
    decisions = decision_module.decide_all(clip)

    assert [t["id"] for t in targets] == [d.channel_row_id for d in decisions]


# --------------------------------------------------------------------------
# The rules still decide
# --------------------------------------------------------------------------


def test_a_disabled_rule_does_not_decide(channels: tuple[dict, dict], clip: str) -> None:
    gaming, _ = channels
    classifier.add_rule("gaming", gaming["id"], enabled=False)
    _classify(clip, "gaming")

    decision = decision_module.decide(clip)

    assert decision.fallback is True
    assert decision.rule_id == ""


def test_the_first_rule_by_priority_wins(channels: tuple[dict, dict], clip: str) -> None:
    gaming, main = channels
    classifier.add_rule("gaming", main["id"], priority=10)
    classifier.add_rule("gaming", gaming["id"], priority=1)
    _classify(clip, "gaming")

    decision = decision_module.decide(clip)

    assert decision.channel_id == "UC_game"


def test_a_rule_pointing_at_a_deleted_channel_is_skipped(
    channels: tuple[dict, dict], clip: str
) -> None:
    """A rule that cannot fire is not a decision."""
    gaming, main = channels
    classifier.add_rule("gaming", gaming["id"], priority=1)
    classifier.add_rule("game", main["id"], priority=2)
    _classify(clip, "gaming")
    accounts_store.delete_channel(gaming["id"])

    decision = decision_module.decide(clip)

    # The first rule's channel is gone, so it cannot fire. The second
    # rule's keyword does not match "gaming" either, so the default
    # answered — and it was a fallback, not a rule.
    assert decision.fallback is True
    assert decision.rule_id == ""


# --------------------------------------------------------------------------
# The fan-out
# --------------------------------------------------------------------------


def test_a_channel_with_auto_upload_off_is_left_out_of_the_fanout(
    channels: tuple[dict, dict], clip: str
) -> None:
    """A subscriber-only channel is never published to by surprise."""
    gaming, main = channels
    classifier.add_rule("gaming", gaming["id"], extra_channel_ids=[main["id"]])
    _classify(clip, "gaming")
    accounts_store.update_channel(main["id"], auto_upload=False)

    decisions = decision_module.decide_all(clip)

    assert [d.channel_row_id for d in decisions] == [gaming["id"]]


def test_the_primary_is_still_named_when_its_auto_upload_is_off(
    channels: tuple[dict, dict], clip: str
) -> None:
    """The route is the route; whether it publishes is a separate thing."""
    gaming, _ = channels
    classifier.add_rule("gaming", gaming["id"])
    _classify(clip, "gaming")
    accounts_store.update_channel(gaming["id"], auto_upload=False)

    decision = decision_module.decide(clip)

    assert decision.channel_row_id == gaming["id"]
    assert decision.auto_upload is False


def test_the_fanout_lists_the_extra_channels(channels: tuple[dict, dict], clip: str) -> None:
    gaming, main = channels
    classifier.add_rule("gaming", gaming["id"], extra_channel_ids=[main["id"]])
    _classify(clip, "gaming")

    decision = decision_module.decide(clip)

    assert decision.extra_channel_ids == (main["id"],)


# --------------------------------------------------------------------------
# Recording the decision
# --------------------------------------------------------------------------


def test_a_recorded_decision_can_be_read_back(channels: tuple[dict, dict], clip: str) -> None:
    gaming, _ = channels
    classifier.add_rule("gaming", gaming["id"], name="Gameplay")
    _classify(clip, "gaming", confidence=0.8)

    decision_module.record(decision_module.decide(clip))

    stored = decision_module.latest_for(clip)
    assert len(stored) == 1
    assert stored[0].category == "gaming"
    assert stored[0].channel_id == "UC_game"
    assert stored[0].rule == "Gameplay"
    assert stored[0].confidence == 0.8
    assert stored[0].fallback is False
    assert stored[0].created_at != ""


def test_the_newest_decision_comes_first(channels: tuple[dict, dict], clip: str) -> None:
    gaming, _ = channels
    classifier.add_rule("gaming", gaming["id"])
    _classify(clip, "gaming")

    decision_module.record(decision_module.decide(clip))
    decision_module.record(decision_module.decide(clip))

    stored = decision_module.latest_for(clip)
    assert len(stored) == 2


def test_a_recorded_decision_keeps_what_the_rules_said_at_the_time(
    channels: tuple[dict, dict], clip: str
) -> None:
    """Editing a rule tomorrow leaves yesterday's decision readable."""
    gaming, main = channels
    rule = classifier.add_rule("gaming", gaming["id"], name="Gameplay")
    _classify(clip, "gaming")

    decision_module.record(decision_module.decide(clip))

    classifier.update_rule(rule["id"], name="Renamed", target_channel_id=main["id"])

    stored = decision_module.latest_for(clip)
    assert stored[0].rule == "Gameplay"
    assert stored[0].channel_id == "UC_game"


def test_the_recent_list_spans_the_clips(channels: tuple[dict, dict], clip: str) -> None:
    gaming, _ = channels
    classifier.add_rule("gaming", gaming["id"])
    _classify(clip, "gaming")
    decision_module.record(decision_module.decide(clip))

    recent = decision_module.recent(10)

    assert len(recent) == 1
    assert recent[0].clip_id == clip


def test_the_decision_is_recorded_when_an_upload_is_queued(
    channels: tuple[dict, dict], clip: str
) -> None:
    """The decision that sent a clip somewhere is kept."""
    from autoclip import config
    from autoclip.db.models import Export
    from autoclip.youtube import uploads

    gaming, _ = channels
    classifier.add_rule("gaming", gaming["id"], name="Gameplay")
    _classify(clip, "gaming")

    export = Export(id=new_id(), clip_id=clip, path="/tmp/out.mp4")
    store.create_export(export)

    settings = config.load()
    settings.youtube.auto_upload = True

    # The upload is not actually sent: this is about the decision.
    with pytest.MonkeyPatch.context() as patch:
        patch.setattr(uploads.oauth, "is_connected", lambda _s: True)
        uploads.enqueue_export_all(export.id, settings)

    stored = decision_module.latest_for(clip)
    assert len(stored) == 1
    assert stored[0].rule == "Gameplay"
    assert stored[0].channel_id == "UC_game"


# --------------------------------------------------------------------------
# The API
# --------------------------------------------------------------------------


def test_the_decision_endpoint_returns_the_six_fields(
    client: TestClient, channels: tuple[dict, dict], clip: str
) -> None:
    gaming, _ = channels
    classifier.add_rule("gaming", gaming["id"], name="Gameplay")
    _classify(clip, "gaming", confidence=0.75)

    body = client.get(f"/api/routing/clips/{clip}/decision").json()

    assert body["category"] == "gaming"
    assert body["channel_id"] == "UC_game"
    assert body["rule"] == "Gameplay"
    assert body["confidence"] == 0.75
    assert body["fallback"] is False
    assert body["reason"]


def test_the_decision_endpoint_never_refuses(client: TestClient, initialised_db: int) -> None:
    """Even with nothing configured, the answer is "nothing is set up"."""
    source = store.create_source(
        Source(id=new_id(), type="upload", url="", path="/tmp/x.mp4", title="source")
    )
    job = store.create_job(Job(id=new_id(), source_id=source.id, provider=""))
    saved = store.replace_clips(
        job.id, [Clip(id=new_id(), job_id=job.id, start_s=0.0, end_s=5.0, rank=1)]
    )

    response = client.get(f"/api/routing/clips/{saved[0].id}/decision")

    assert response.status_code == 200
    assert response.json()["fallback"] is True


def test_the_decisions_endpoint_lists_what_was_recorded(
    client: TestClient, channels: tuple[dict, dict], clip: str
) -> None:
    gaming, _ = channels
    classifier.add_rule("gaming", gaming["id"], name="Gameplay")
    _classify(clip, "gaming")
    decision_module.record(decision_module.decide(clip))

    body = client.get("/api/routing/decisions").json()

    assert len(body) == 1
    assert body[0]["clip_id"] == clip
    assert body[0]["rule"] == "Gameplay"


def test_the_clip_list_carries_the_routing_decision(
    client: TestClient, channels: tuple[dict, dict], clip: str
) -> None:
    gaming, _ = channels
    classifier.add_rule("gaming", gaming["id"], name="Gameplay")
    _classify(clip, "gaming")

    body = client.get("/api/clips").json()

    assert len(body) == 1
    routing = body[0]["routing"]
    assert routing is not None
    assert routing["category"] == "gaming"
    assert routing["channel_id"] == "UC_game"
    assert routing["rule"] == "Gameplay"
    assert routing["fallback"] is False
