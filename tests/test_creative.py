"""M3 — the structured creative plan.

The rule the whole layer is built around: **AI proposes, deterministic code
decides.** These tests check the three halves of that rule:

* the **plan** is validated against facts the model cannot argue with — a
  caption style AutoClip does not have is not a caption style, and a
  track that is not in the library is not a track;
* the **allowance** is one call and one repair, and then the deterministic
  plan, with the reasons recorded;
* a **refusal** is an answer rather than a failure, and it is recorded as
  one.

The music choice — the preference, the shapes and the per-clip selection —
has its own file, `tests/test_music_selection.py`.
"""

from __future__ import annotations

import json
from typing import Any

import pytest
from autoclip.budget import JobBudget
from autoclip.db.models import Clip
from autoclip.pipeline import creative
from autoclip.providers.base import ProviderConsentRequired
from autoclip.security import consent

# --------------------------------------------------------------------------
# Helpers
# --------------------------------------------------------------------------


def _clip(clip_id: str = "c1", *, start_s: float = 0.0, end_s: float = 30.0) -> Clip:
    return Clip(
        id=clip_id,
        job_id="job1",
        start_s=start_s,
        end_s=end_s,
        rank=1,
        title=f"Clip {clip_id}",
        hook="A hook.",
        reason="Because.",
    )


def _clips() -> list[Clip]:
    return [_clip("c1"), _clip("c2"), _clip("c3")]


def _plan_json(**overrides: Any) -> str:
    payload: dict[str, Any] = {
        "clips": [
            {
                "clip_id": "c1",
                "layout": "corner",
                "crop": "auto",
                "caption_strategy": "bold_pop",
                "music_track_id": "",
                "ducking_db": -12.0,
                "transition": "cut",
                "reason": "It is busy.",
            }
        ],
        "export_ratio": "9:16",
        "notes": ["one line"],
    }
    payload.update(overrides)
    return json.dumps(payload)


class FakeProvider:
    """A provider that answers with whatever it is given, in order."""

    def __init__(self, *answers: str | Exception) -> None:
        self.answers = list(answers)
        self.calls: list[dict[str, Any]] = []

    async def generate_text(
        self,
        system: str,
        user: str,
        *,
        temperature: float = 0.4,
        operation: str = "",
        data_summary: str = "",
    ) -> str:
        self.calls.append(
            {
                "system": system,
                "user": user,
                "temperature": temperature,
                "operation": operation,
                "data_summary": data_summary,
            }
        )
        if not self.answers:
            raise AssertionError("the provider was called more times than expected")
        answer = self.answers.pop(0)
        if isinstance(answer, Exception):
            raise answer
        return answer


def _budget(max_clips: int = 3) -> JobBudget:
    return JobBudget.for_job("job1", max_clips=max_clips)


# --------------------------------------------------------------------------
# The plan is validated
# --------------------------------------------------------------------------


def test_a_valid_plan_is_accepted() -> None:
    plan = creative.parse_plan(_plan_json(), clip_ids=["c1", "c2"], track_ids=[])

    assert plan.source == "ai"
    assert len(plan.clips) == 1
    direction = plan.direction_for("c1")
    assert direction is not None
    assert direction.layout == "corner"
    assert direction.caption_strategy == "bold_pop"
    assert direction.ducking_db == -12.0


def test_a_plan_wrapped_in_prose_and_fences_is_accepted() -> None:
    """A fence is not worth spending the call over."""
    raw = f"Here is the plan:\n```json\n{_plan_json()}\n```\nHope that helps."

    plan = creative.parse_plan(raw, clip_ids=["c1"], track_ids=[])

    assert plan.source == "ai"


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("layout", "hologram"),
        ("crop", "telepathy"),
        ("caption_strategy", "neon_bubble"),
        ("transition", "explode"),
    ],
)
def test_an_unknown_choice_is_rejected(field: str, value: str) -> None:
    """A model that names something AutoClip cannot build is refused."""
    payload = json.loads(_plan_json())
    payload["clips"][0][field] = value

    with pytest.raises(creative.PlanRejected) as caught:
        creative.parse_plan(json.dumps(payload), clip_ids=["c1"], track_ids=[])

    assert field in str(caught.value)


def test_an_unknown_track_id_is_rejected() -> None:
    payload = json.loads(_plan_json())
    payload["clips"][0]["music_track_id"] = "made-up-track"

    with pytest.raises(creative.PlanRejected) as caught:
        creative.parse_plan(json.dumps(payload), clip_ids=["c1"], track_ids=["real-track"])

    assert "made-up-track" in str(caught.value)


def test_an_unknown_clip_id_is_rejected() -> None:
    with pytest.raises(creative.PlanRejected) as caught:
        creative.parse_plan(_plan_json(), clip_ids=["c2"], track_ids=[])

    assert "c1" in str(caught.value)


def test_a_duplicate_clip_id_is_rejected() -> None:
    payload = json.loads(_plan_json())
    payload["clips"].append(dict(payload["clips"][0]))

    with pytest.raises(creative.PlanRejected) as caught:
        creative.parse_plan(json.dumps(payload), clip_ids=["c1"], track_ids=[])

    assert "twice" in str(caught.value)


@pytest.mark.parametrize("ducking", [-40.0, 5.0, -1000.0])
def test_a_ducking_value_outside_the_range_is_rejected(ducking: float) -> None:
    payload = json.loads(_plan_json())
    payload["clips"][0]["ducking_db"] = ducking

    with pytest.raises(creative.PlanRejected) as caught:
        creative.parse_plan(json.dumps(payload), clip_ids=["c1"], track_ids=[])

    assert "ducking_db" in str(caught.value)


@pytest.mark.parametrize("ducking", [-30.0, -12.5, 0.0])
def test_a_ducking_value_inside_the_range_is_accepted(ducking: float) -> None:
    payload = json.loads(_plan_json())
    payload["clips"][0]["ducking_db"] = ducking

    plan = creative.parse_plan(json.dumps(payload), clip_ids=["c1"], track_ids=[])

    direction = plan.direction_for("c1")
    assert direction is not None
    assert direction.ducking_db == ducking


def test_an_answer_that_is_not_json_is_rejected() -> None:
    with pytest.raises(creative.PlanRejected):
        creative.parse_plan(
            "I think the corner layout would work well.", clip_ids=["c1"], track_ids=[]
        )


def test_an_answer_with_no_clips_is_rejected() -> None:
    with pytest.raises(creative.PlanRejected):
        creative.parse_plan(json.dumps({"clips": []}), clip_ids=["c1"], track_ids=[])


def test_an_unknown_export_ratio_is_rejected() -> None:
    payload = json.loads(_plan_json())
    payload["export_ratio"] = "21:9"

    with pytest.raises(creative.PlanRejected) as caught:
        creative.parse_plan(json.dumps(payload), clip_ids=["c1"], track_ids=[])

    assert "export_ratio" in str(caught.value)


def test_every_problem_is_reported_at_once() -> None:
    """The repair prompt is more useful when it lists everything."""
    payload = json.loads(_plan_json())
    payload["clips"][0]["layout"] = "hologram"
    payload["clips"][0]["transition"] = "explode"
    payload["export_ratio"] = "21:9"

    with pytest.raises(creative.PlanRejected) as caught:
        creative.parse_plan(json.dumps(payload), clip_ids=["c1"], track_ids=[])

    assert len(caught.value.problems) == 3


# --------------------------------------------------------------------------
# One call, one repair, then the deterministic plan
# --------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_a_valid_answer_costs_one_call() -> None:
    provider = FakeProvider(_plan_json())
    budget = _budget()

    plan = await creative.plan_creative(provider, budget, clips=_clips())

    assert plan.source == "ai"
    assert len(provider.calls) == 1
    assert budget.plan.used == 1
    assert budget.repair.used == 0


@pytest.mark.asyncio
async def test_the_call_is_made_under_the_creative_planning_operation() -> None:
    provider = FakeProvider(_plan_json())

    await creative.plan_creative(provider, _budget(), clips=_clips())

    assert provider.calls[0]["operation"] == consent.Operation.CREATIVE_PLANNING


@pytest.mark.asyncio
async def test_the_context_carries_no_transcript_and_no_file_path() -> None:
    """What leaves the machine is measurements and clip metadata."""
    provider = FakeProvider(_plan_json())
    clip = _clip("c1")
    clip.reason = "The player shouted about the boss."

    await creative.plan_creative(provider, _budget(), clips=[clip])

    sent = provider.calls[0]["user"]
    assert "The player shouted about the boss." in sent
    assert "C:\\" not in sent
    assert ".mp4" not in sent


@pytest.mark.asyncio
async def test_a_bad_answer_is_repaired_once() -> None:
    provider = FakeProvider("not json at all", _plan_json())
    budget = _budget()

    plan = await creative.plan_creative(provider, budget, clips=_clips())

    assert plan.source == "ai"
    assert len(provider.calls) == 2
    assert budget.plan.used == 1
    assert budget.repair.used == 1


@pytest.mark.asyncio
async def test_the_repair_prompt_carries_the_validation_problems() -> None:
    provider = FakeProvider("not json at all", _plan_json())

    await creative.plan_creative(provider, _budget(), clips=_clips())

    repair = provider.calls[1]["user"]
    assert "Validation problems" in repair
    assert "not JSON" in repair or "JSON" in repair


@pytest.mark.asyncio
async def test_a_bad_answer_and_a_bad_repair_fall_back_with_the_reasons() -> None:
    provider = FakeProvider("not json at all", "still not json")
    budget = _budget()

    plan = await creative.plan_creative(provider, budget, clips=_clips())

    assert plan.source == "fallback"
    assert plan.problems
    assert len(provider.calls) == 2
    assert budget.plan.used == 1
    assert budget.repair.used == 1


@pytest.mark.asyncio
async def test_a_provider_failure_falls_back_without_a_repair() -> None:
    """A failed call is not a schema violation; there is nothing to repair."""
    provider = FakeProvider(RuntimeError("the provider is down"))
    budget = _budget()

    plan = await creative.plan_creative(provider, budget, clips=_clips())

    assert plan.source == "fallback"
    assert len(provider.calls) == 1
    assert budget.repair.used == 0


@pytest.mark.asyncio
async def test_a_refusal_is_not_repaired_and_not_retried() -> None:
    """A withdrawn consent is an answer, not a broken model."""
    provider = FakeProvider(ProviderConsentRequired("the user withdrew consent"))

    with pytest.raises(ProviderConsentRequired):
        await creative.plan_creative(provider, _budget(), clips=_clips())

    assert len(provider.calls) == 1


@pytest.mark.asyncio
async def test_the_fallback_plan_covers_every_clip() -> None:
    provider = FakeProvider("not json")

    plan = await creative.plan_creative(provider, _budget(), clips=_clips())

    assert {direction.clip_id for direction in plan.clips} == {"c1", "c2", "c3"}
    assert all(direction.layout == "auto" for direction in plan.clips)


@pytest.mark.asyncio
async def test_no_clips_means_no_call() -> None:
    provider = FakeProvider(_plan_json())
    budget = _budget()

    plan = await creative.plan_creative(provider, budget, clips=[])

    assert plan.source == "fallback"
    assert provider.calls == []
    assert budget.plan.used == 0


@pytest.mark.asyncio
async def test_an_empty_budget_falls_back_without_a_call() -> None:
    provider = FakeProvider(_plan_json())
    budget = _budget()
    budget.take_plan()

    plan = await creative.plan_creative(provider, budget, clips=_clips())

    assert plan.source == "fallback"
    assert provider.calls == []
    assert "budget" in plan.problems[0]


# --------------------------------------------------------------------------
# The consent operations
# --------------------------------------------------------------------------


def test_the_new_operations_are_in_the_vocabulary() -> None:
    assert consent.Operation.CREATIVE_PLANNING in consent.Operation.all()
    assert consent.Operation.MUSIC_SELECTION in consent.Operation.all()


def test_the_new_operations_say_what_they_send() -> None:
    descriptions = consent.all_operations()

    planning = descriptions[consent.Operation.CREATIVE_PLANNING]
    assert planning["data"]
    assert planning["why"]

    music = descriptions[consent.Operation.MUSIC_SELECTION]
    assert "metadata" in music["data"]
    assert "Never the audio" in music["data"]


def test_the_new_operations_can_be_withdrawn(initialised_db: int) -> None:
    consent.grant(consent.Operation.CREATIVE_PLANNING, "public")
    consent.grant(consent.Operation.MUSIC_SELECTION, "public")
    assert consent.has_consent(consent.Operation.CREATIVE_PLANNING, "public")
    assert consent.has_consent(consent.Operation.MUSIC_SELECTION, "public")

    consent.revoke(consent.Operation.CREATIVE_PLANNING, "public")
    consent.revoke(consent.Operation.MUSIC_SELECTION, "public")
    assert not consent.has_consent(consent.Operation.CREATIVE_PLANNING, "public")
    assert not consent.has_consent(consent.Operation.MUSIC_SELECTION, "public")
