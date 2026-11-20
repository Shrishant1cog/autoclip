"""The music choice: the preference, the shapes and the per-clip selection.

Three things are tested here, and they are three different questions:

* **What did the user ask for?** The preference lives at three scopes, and
  the most specific one wins. An unset scope falls through; the sentinel
  ``__none__`` turns the music off.
* **What can be filtered by?** The shapes a track has are derived from the
  measurements, never stored, so a shape cannot drift away from the number
  it came from.
* **What did the pipeline decide?** One music call per eligible clip, made
  under its own consent operation, and never at the expense of the
  planning call.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest
from autoclip.budget import CallBudget, JobBudget
from autoclip.db.models import Clip
from autoclip.music import formats as music_formats
from autoclip.music import library as music_library
from autoclip.music import preferences as music_preferences
from autoclip.music import selection as music_selection
from autoclip.music import store as music_store
from autoclip.music.analysis import Analysis
from autoclip.music.licensing import LicenseRecord, LicenseState
from autoclip.pipeline import music_selection as pipeline_music_selection
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


def _confirm(track_id: str, state: str = LicenseState.USER_CONFIRMED) -> None:
    music_store.set_license(
        LicenseRecord(track_id=track_id, state=state, source="test", evidence="A fixture.")
    )


def _track(tmp_path: Path, name: str, analysis: Analysis) -> str:
    folder = tmp_path / "music"
    folder.mkdir(exist_ok=True)
    path = folder / name
    path.write_bytes(b"audio")
    track = music_store.upsert_track(path)
    music_store.analyse_track(track.id, analysis)
    _confirm(track.id)
    return track.id


def _analyses() -> list[Analysis]:
    return [
        Analysis(duration_s=45.0, bpm=90.0, energy=0.2, mood="calm", beat_regularity=0.2),
        Analysis(duration_s=45.0, bpm=150.0, energy=0.9, mood="energetic", beat_regularity=0.8),
    ]


# --------------------------------------------------------------------------
# The music choice
# --------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_the_users_choice_wins_and_costs_no_call(tmp_path: Path, initialised_db: int) -> None:
    _track(tmp_path, "calm.mp3", _analyses()[0])
    second = _track(tmp_path, "loud.mp3", _analyses()[1])

    provider = FakeProvider()
    budget = _budget()
    selections = await pipeline_music_selection.select_for_clips(
        [_clip("c1")],
        provider=provider,
        budget=budget,
        source_id="src1",
        candidates=list(music_store.list_tracks()),
    )
    # With no stored preference the model is asked, so the choice is made
    # without a preference here.
    assert selections["c1"] is not None

    music_preferences.set_preference(music_preferences.SCOPE_SOURCE, "src1", second)
    budget = _budget()
    selections = await pipeline_music_selection.select_for_clips(
        [_clip("c1")],
        provider=FakeProvider(),
        budget=budget,
        source_id="src1",
        candidates=list(music_store.list_tracks()),
    )

    assert selections["c1"] is not None
    assert selections["c1"].track_id == second
    assert selections["c1"].source == "user"
    assert budget.music.used == 0


@pytest.mark.asyncio
async def test_no_music_is_honoured(tmp_path: Path, initialised_db: int) -> None:
    _track(tmp_path, "calm.mp3", _analyses()[0])
    music_preferences.set_preference(music_preferences.SCOPE_GLOBAL, "", music_preferences.NO_MUSIC)

    selections = await pipeline_music_selection.select_for_clips(
        [_clip("c1")],
        provider=FakeProvider(json.dumps({"track_id": "", "reason": "none fits"})),
        budget=_budget(),
        source_id="src1",
        candidates=list(music_store.list_tracks()),
    )

    assert selections["c1"] is None


@pytest.mark.asyncio
async def test_the_music_call_is_made_under_its_own_operation(
    tmp_path: Path, initialised_db: int
) -> None:
    _track(tmp_path, "calm.mp3", _analyses()[0])
    provider = FakeProvider(json.dumps({"track_id": "", "reason": "none fits"}))

    await pipeline_music_selection.select_for_clips(
        [_clip("c1")],
        provider=provider,
        budget=_budget(),
        source_id="src1",
        candidates=list(music_store.list_tracks()),
    )

    assert provider.calls[0]["operation"] == consent.Operation.MUSIC_SELECTION


@pytest.mark.asyncio
async def test_the_music_call_sends_measurements_and_no_audio(
    tmp_path: Path, initialised_db: int
) -> None:
    _track(tmp_path, "calm.mp3", _analyses()[0])
    provider = FakeProvider(json.dumps({"track_id": "", "reason": "none fits"}))

    await pipeline_music_selection.select_for_clips(
        [_clip("c1")],
        provider=provider,
        budget=_budget(),
        source_id="src1",
        candidates=list(music_store.list_tracks()),
    )

    sent = provider.calls[0]["user"]
    assert "bpm" in sent
    assert "energy" in sent
    assert str(tmp_path) not in sent


@pytest.mark.asyncio
async def test_a_spent_music_budget_falls_back_to_the_measurements(
    tmp_path: Path, initialised_db: int
) -> None:
    _track(tmp_path, "calm.mp3", _analyses()[0])
    second = _track(tmp_path, "loud.mp3", _analyses()[1])
    provider = FakeProvider(json.dumps({"track_id": second, "reason": "It fits."}))
    budget = _budget(max_clips=1)
    budget.take_music()  # the allowance is gone

    selections = await pipeline_music_selection.select_for_clips(
        [_clip("c1")],
        provider=provider,
        budget=budget,
        source_id="src1",
        candidates=list(music_store.list_tracks()),
    )

    assert selections["c1"] is not None
    assert selections["c1"].source == "deterministic"
    assert provider.calls == []


@pytest.mark.asyncio
async def test_a_refused_music_call_stops_the_asking(tmp_path: Path, initialised_db: int) -> None:
    """One refusal is enough; the rest are chosen from the measurements.

    Asking once per clip would spend the budget on refusals and fill the
    transfer log with the same answer repeated.
    """
    _track(tmp_path, "calm.mp3", _analyses()[0])
    provider = FakeProvider(ProviderConsentRequired("the user withdrew consent"))
    budget = _budget()

    selections = await pipeline_music_selection.select_for_clips(
        [_clip("c1"), _clip("c2"), _clip("c3")],
        provider=provider,
        budget=budget,
        source_id="src1",
        candidates=list(music_store.list_tracks()),
    )

    assert len(provider.calls) == 1
    assert all(selection is not None for selection in selections.values())
    assert all(
        selection.source == "deterministic" for selection in selections.values() if selection
    )


@pytest.mark.asyncio
async def test_a_track_that_may_not_be_exported_is_not_a_candidate(
    tmp_path: Path, initialised_db: int
) -> None:
    _track(tmp_path, "calm.mp3", _analyses()[0])
    blocked = _track(tmp_path, "loud.mp3", _analyses()[1])
    music_store.set_license(
        LicenseRecord(track_id=blocked, state=LicenseState.INCOMPATIBLE, source="test")
    )
    provider = FakeProvider(json.dumps({"track_id": blocked, "reason": "It fits."}))

    selections = await pipeline_music_selection.select_for_clips(
        [_clip("c1")],
        provider=provider,
        budget=_budget(),
        source_id="src1",
        candidates=list(music_store.list_tracks()),
    )

    assert selections["c1"] is not None
    assert selections["c1"].track_id != blocked
    assert blocked not in provider.calls[0]["user"]


# --------------------------------------------------------------------------
# The preferences
# --------------------------------------------------------------------------


def test_the_most_specific_scope_wins(initialised_db: int) -> None:
    music_preferences.set_preference(music_preferences.SCOPE_GLOBAL, "", "global-track")
    music_preferences.set_preference(music_preferences.SCOPE_SOURCE, "src1", "source-track")
    music_preferences.set_preference(music_preferences.SCOPE_CLIP, "c1", "clip-track")

    assert music_preferences.resolve_preference(clip_id="c1", source_id="src1") == (
        "clip-track",
        "clip",
    )
    assert music_preferences.resolve_preference(clip_id="c2", source_id="src1") == (
        "source-track",
        "source",
    )
    assert music_preferences.resolve_preference(clip_id="c2", source_id="src2") == (
        "global-track",
        "global",
    )


def test_no_preference_anywhere_is_an_empty_answer(initialised_db: int) -> None:
    assert music_preferences.resolve_preference(clip_id="c1", source_id="src1") == ("", "")


def test_an_empty_track_id_means_no_preference_here(initialised_db: int) -> None:
    """An unset scope falls back; it does not turn the music off."""
    music_preferences.set_preference(music_preferences.SCOPE_GLOBAL, "", "global-track")
    music_preferences.set_preference(music_preferences.SCOPE_SOURCE, "src1", "")

    assert music_preferences.resolve_preference(clip_id="c1", source_id="src1") == (
        "global-track",
        "global",
    )


def test_clearing_a_scope_keeps_the_others(initialised_db: int) -> None:
    music_preferences.set_preference(music_preferences.SCOPE_GLOBAL, "", "global-track")
    music_preferences.set_preference(music_preferences.SCOPE_SOURCE, "src1", "source-track")

    music_preferences.clear_preference(music_preferences.SCOPE_SOURCE, "src1")

    assert music_preferences.resolve_preference(clip_id="c1", source_id="src1") == (
        "global-track",
        "global",
    )


def test_no_music_is_a_different_answer_from_unset(initialised_db: int) -> None:
    music_preferences.set_preference(music_preferences.SCOPE_GLOBAL, "", music_preferences.NO_MUSIC)

    assert music_preferences.resolve_preference(clip_id="c1", source_id="src1") == (
        music_preferences.NO_MUSIC,
        "global",
    )


def test_an_unknown_scope_is_refused(initialised_db: int) -> None:
    with pytest.raises(ValueError):
        music_preferences.set_preference("galaxy", "x", "track")


# --------------------------------------------------------------------------
# The formats and the filters
# --------------------------------------------------------------------------


def test_the_formats_come_from_the_measurements() -> None:
    analysis = Analysis(
        duration_s=20.0,
        energy=0.8,
        beat_regularity=0.7,
        percussive_ratio=0.6,
        harmonic_ratio=0.1,
        stereo_width=0.6,
        clipping_ratio=0.002,
    )

    tags = music_formats.classify(analysis)

    assert "short" in tags
    assert "steady" in tags
    assert "driving" in tags
    assert "percussive" in tags
    assert "wide" in tags
    assert "clipping" in tags
    assert "long" not in tags
    assert "sparse" not in tags


def test_a_long_loose_track_is_tagged_as_such() -> None:
    analysis = Analysis(duration_s=90.0, energy=0.2, beat_regularity=0.1)

    tags = music_formats.classify(analysis)

    assert "long" in tags
    assert "loose" in tags
    assert "sparse" in tags
    assert "short" not in tags


def test_every_format_says_where_it_comes_from() -> None:
    for fmt in music_formats.FORMATS:
        assert fmt.measured
        assert fmt.description
        assert music_formats.describe(fmt.value) is fmt


def test_the_library_filters_on_energy(tmp_path: Path, initialised_db: int) -> None:
    _track(tmp_path, "calm.mp3", _analyses()[0])
    _track(tmp_path, "loud.mp3", _analyses()[1])

    quiet = music_library.search(min_energy=0.0, max_energy=0.5)
    loud = music_library.search(min_energy=0.6)

    assert [entry.track.name for entry in quiet] == ["calm.mp3"]
    assert [entry.track.name for entry in loud] == ["loud.mp3"]


def test_the_library_filters_on_format(tmp_path: Path, initialised_db: int) -> None:
    _track(tmp_path, "calm.mp3", _analyses()[0])
    _track(tmp_path, "loud.mp3", _analyses()[1])

    driving = music_library.search(music_format="driving")

    assert [entry.track.name for entry in driving] == ["loud.mp3"]


def test_the_track_payload_carries_its_formats(tmp_path: Path, initialised_db: int) -> None:
    _track(tmp_path, "loud.mp3", _analyses()[1])

    entry = music_library.list_tracks()[0]
    payload = entry.to_dict()

    assert "driving" in payload["formats"]


# --------------------------------------------------------------------------
# The music scorer's own rules
# --------------------------------------------------------------------------


def test_the_shared_budget_is_the_one_the_music_module_uses() -> None:
    """One budget type, not two that drifted apart."""
    assert music_selection.CallBudget is CallBudget
