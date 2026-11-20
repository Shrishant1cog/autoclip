"""Choosing the music for each clip, inside the pipeline.

The rules, in order:

1. **The user's own choice wins** — the clip's, then the source's, then the
   global one. No model is consulted, and no call is spent.
2. **A model may propose a track**, but only one that exists and may
   legally be used, and only within the job's budget.
3. **Otherwise the deterministic scorer picks**, from the measurements.

The model's call goes through the egress gateway under the
``music_selection`` operation, so the user can see that their music
metadata went out and withdraw it. What is sent is *measurements* — tempo,
energy, mood, loudness, duration. Never the audio, and never a file path.
"""

from __future__ import annotations

import logging
from typing import Any

from ..db.models import Clip
from ..music import preferences as music_preferences
from ..music import selection as music_selection
from ..music.selection import ClipContext, MusicSelection
from ..providers.base import ProviderConsentRequired
from ..security import consent
from .speech_timeline import SpeechTimeline

log = logging.getLogger(__name__)

__all__ = [
    "ClipContext",
    "MusicSelection",
    "infer_mood",
    "select_for_clips",
    "speech_density",
]

#: The moods the music analysis uses. A clip's mood is one of these, so
#: the scorer can compare it with a track's mood.
MOODS = ("calm", "dark", "mellow", "warm", "energetic", "driving", "tense", "uplifting")

#: Scene changes per minute at which a clip counts as busy.
BUSY_CUTS_PER_MINUTE = 8.0


def speech_density(timeline: SpeechTimeline | None, start_s: float, end_s: float) -> float:
    """How much of a clip is speech, from 0 to 1.

    Measured from the shared timeline, so this is the same speech the
    ducking ducks for.
    """
    duration = max(0.0, end_s - start_s)
    if duration <= 0 or timeline is None:
        return 0.0
    covered = 0.0
    for interval in timeline.relative_slice(start_s, end_s):
        covered += max(0.0, (interval.end_ms - interval.start_ms) / 1000.0)
    return min(1.0, covered / duration)


def infer_mood(*, speech: float, cuts_per_minute: float) -> str:
    """The clip's mood, from two measurements.

    A fixed rule set, so the same clip always gets the same label and the
    user can see why: a clip that is mostly talking wants calm music, a
    busy one wants something with a pulse, and a quiet, slow one wants
    neither.
    """
    busy = cuts_per_minute >= BUSY_CUTS_PER_MINUTE
    talking = speech >= 0.55

    if busy and talking:
        return "warm"
    if busy:
        return "energetic"
    if talking:
        return "mellow"
    if cuts_per_minute >= 3.0:
        return "warm"
    return "calm"


def _intensity(*, speech: float, cuts_per_minute: float) -> float:
    """How intense a clip is, from 0 to 1.

    Speech and scene changes are the two signals that are actually
    measured. Nothing here is a guess about how exciting the video is.
    """
    busy = min(1.0, cuts_per_minute / BUSY_CUTS_PER_MINUTE)
    return round(min(1.0, 0.55 * busy + 0.45 * speech), 3)


async def select_for_clips(
    clips: list[Clip],
    *,
    provider: Any = None,
    budget: Any = None,
    timeline: SpeechTimeline | None = None,
    scene_changes: dict[str, int] | None = None,
    source_id: str = "",
    candidates: list[Any] | None = None,
) -> dict[str, MusicSelection | None]:
    """Choose a track for every clip.

    Returns one entry per clip. ``None`` means no music for that clip —
    either the user turned it off, or there was nothing in the library that
    may legally be used.

    A clip whose choice is the user's own never spends a call. A clip that
    the model has an opinion about spends one, and only while the budget
    lasts.
    """
    cuts = scene_changes or {}
    choices: dict[str, MusicSelection | None] = {}

    proposer = None
    if provider is not None:
        proposer = _make_proposer(provider)

    music_budget = _music_budget(budget)

    for clip in clips:
        track_id, scope = music_preferences.resolve_preference(
            clip_id=clip.id,
            source_id=source_id,
        )

        if track_id == music_preferences.NO_MUSIC:
            log.info("Clip %s has the music turned off by the user's choice.", clip.id)
            choices[clip.id] = None
            continue

        duration = max(0.0, clip.end_s - clip.start_s)
        speech = speech_density(timeline, clip.start_s, clip.end_s)
        clip_cuts = int(cuts.get(clip.id, 0))
        cuts_per_minute = (clip_cuts / duration * 60.0) if duration > 0 else 0.0

        context = ClipContext(
            clip_id=clip.id,
            duration_s=duration,
            mood=infer_mood(speech=speech, cuts_per_minute=cuts_per_minute),
            intensity=_intensity(speech=speech, cuts_per_minute=cuts_per_minute),
            speech_density=speech,
            scene_changes=clip_cuts,
            gameplay_intensity=min(1.0, cuts_per_minute / BUSY_CUTS_PER_MINUTE),
        )

        try:
            selection = await music_selection.select_track_async(
                context,
                candidates=candidates,
                proposer=proposer,
                user_choice=track_id,
                budget=music_budget,
                fatal=(ProviderConsentRequired,),
            )
        except ProviderConsentRequired:
            # The user withdrew consent for the music call. That is an
            # answer, not a failure: the remaining clips are chosen
            # deterministically, and no other provider is tried. Asking
            # once per clip would spend the budget on refusals and fill
            # the transfer log with the same answer repeated.
            proposer = None
            log.info(
                "The AI music selection was refused by the privacy settings; "
                "the remaining clips are chosen from the measurements."
            )
            selection = await music_selection.select_track_async(
                context,
                candidates=candidates,
                proposer=None,
                user_choice=track_id,
                budget=music_budget,
            )

        if selection is None:
            log.info("No usable track was found for clip %s; exporting without music.", clip.id)
        elif selection.source == "user":
            log.info(
                "Clip %s uses the track the user chose (%s, from the %s scope).",
                clip.id,
                selection.track_name,
                scope,
            )
        choices[clip.id] = selection

    return choices


def _music_budget(budget: Any) -> Any:
    """The music allowance of the job's budget.

    The job budget keeps the three categories apart, so the music calls
    are taken from the music line and cannot eat the planning call.
    """
    if budget is None:
        return None
    music = getattr(budget, "music", None)
    if music is not None:
        return music
    # A plain per-category budget is accepted too, so the module works
    # with the older one-call-per-clip budget.
    return budget


def _make_proposer(provider: Any) -> Any:
    """A proposer that calls the provider through the egress gateway.

    The call is made under the ``music_selection`` operation, so it is
    recorded in the transfer log and can be withdrawn by the user.
    """

    async def propose(context: dict[str, Any]) -> str:
        import json

        return await provider.generate_text(
            _MUSIC_SYSTEM_PROMPT,
            json.dumps(context, indent=2, ensure_ascii=False),
            temperature=0.2,
            operation=consent.Operation.MUSIC_SELECTION,
            data_summary=(
                "The measured metadata of your music tracks — tempo, energy, mood, "
                "loudness. Never the audio, and never a file path."
            ),
        )

    return propose


_MUSIC_SYSTEM_PROMPT = """\
You are choosing a music track for a short clip.

You are given the clip's measurements and the measured metadata of the
tracks in the user's library. You are NOT given any audio.

Answer with ONE JSON object and nothing else:

{"track_id": "the exact id of one track you were given", "reason": "one sentence"}

Rules:

* Use only a track id you were given. Never invent one.
* If none of the tracks suit the clip, answer {"track_id": "", "reason": "..."}.
* The reason must be about the measurements — tempo, energy, mood — not
  about what the track "feels" like.
"""
