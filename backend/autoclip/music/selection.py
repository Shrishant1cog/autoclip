"""Choosing a track for a clip.

The rule the whole module is built around: **AI proposes, deterministic code
decides.** A model is given the measured metadata of the candidate tracks and
the shape of the clip, and it answers with a choice and a reason. The answer
is then checked against facts the model cannot argue with — does the track
exist, is it licensed for use, does it fit the clip — and if any of those
fail, the deterministic scorer picks instead. A model's opinion never
overrides a fact.

The metadata sent to the model is *structured*: BPM, energy, mood, rhythm,
duration, loudness. No audio is ever uploaded, and no file path is sent.

A manual choice always wins. If the user picked a track, that is the answer,
and no model is consulted.
"""

from __future__ import annotations

import json
import logging
import re
from dataclasses import dataclass, field
from typing import Any, Protocol

from . import store
from .analysis import Analysis
from .licensing import evaluate

log = logging.getLogger(__name__)

__all__ = [
    "CallBudget",
    "ClipContext",
    "MusicSelection",
    "Proposer",
    "build_proposal_context",
    "default_budget",
    "parse_proposal",
    "select_track",
    "score_track",
]


class Proposer(Protocol):
    """Something that can propose a track.

    The caller supplies this; the module never reaches for a provider itself,
    which keeps the AI path testable and keeps the call budget enforceable at
    the call site.
    """

    def __call__(self, context: dict[str, Any]) -> str: ...


@dataclass
class ClipContext:
    """What the clip needs from its music."""

    clip_id: str = ""
    duration_s: float = 0.0
    #: The clip's own mood, as decided upstream.
    mood: str = ""
    #: How intense the clip is, 0–1.
    intensity: float = 0.5
    #: How much of the clip is speech, 0–1.
    speech_density: float = 0.5
    #: How many scene changes the clip contains.
    scene_changes: int = 0
    #: How intense the gameplay is, 0–1.
    gameplay_intensity: float = 0.5

    def to_dict(self) -> dict[str, Any]:
        return {
            "clip_id": self.clip_id,
            "duration_s": round(self.duration_s, 2),
            "mood": self.mood,
            "intensity": round(self.intensity, 3),
            "speech_density": round(self.speech_density, 3),
            "scene_changes": self.scene_changes,
            "gameplay_intensity": round(self.gameplay_intensity, 3),
        }


@dataclass
class MusicSelection:
    """The chosen track and why."""

    track_id: str
    track_name: str
    #: "user" (a manual choice), "ai" (a model's proposal that validated) or
    #: "deterministic" (the scorer's own answer).
    source: str
    reason: str = ""
    score: float = 0.0
    warnings: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "track_id": self.track_id,
            "track_name": self.track_name,
            "source": self.source,
            "reason": self.reason,
            "score": round(self.score, 4),
            "warnings": list(self.warnings),
        }


@dataclass
class CallBudget:
    """A hard cap on how many AI calls a job may make.

    The approved budget is one music call per eligible clip, capped by the
    clip count — ten clips means ten calls, and no more, whatever the model
    asks for.
    """

    max_calls: int
    used: int = 0

    @property
    def remaining(self) -> int:
        return max(0, self.max_calls - self.used)

    def take(self) -> bool:
        """Reserve one call. Returns False when the budget is spent."""
        if self.used >= self.max_calls:
            return False
        self.used += 1
        return True

    def to_dict(self) -> dict[str, Any]:
        return {
            "max_calls": self.max_calls,
            "used": self.used,
            "remaining": self.remaining,
        }


# --------------------------------------------------------------------------
# Scoring
# --------------------------------------------------------------------------


def _closeness(a: float, b: float, tolerance: float) -> float:
    """1.0 when two values match, 0.0 when they are ``tolerance`` apart."""
    if tolerance <= 0:
        return 1.0 if a == b else 0.0
    return max(0.0, 1.0 - abs(a - b) / tolerance)


def _target_bpm(intensity: float) -> float:
    """The tempo that suits a clip of this intensity."""
    return 70.0 + intensity * 80.0


def score_track(context: ClipContext, analysis: Analysis) -> float:
    """How well a track suits a clip, from 0 to 1.

    The weights are the product's opinion about music, written down:

    * energy should sit near the clip's intensity;
    * a talking clip wants calmer music, because the voice has to stay clear;
    * a busy clip wants a steady pulse, so the edits have something to land on;
    * the tempo should sit near the tempo the intensity implies;
    * a track that fits inside the clip is better than one that has to loop.
    """
    intensity = max(0.0, min(1.0, context.intensity))
    speech = max(0.0, min(1.0, context.speech_density))

    energy_match = _closeness(analysis.energy, intensity, 0.6)
    # A lot of speech pushes the wanted energy down.
    wanted_energy = intensity * (1.0 - 0.45 * speech)
    energy_target = _closeness(analysis.energy, wanted_energy, 0.6)
    tempo = _closeness(analysis.bpm, _target_bpm(intensity), 60.0)

    # A steady beat helps when the clip cuts often; a loose one is fine when
    # it does not.
    busyness = min(1.0, context.scene_changes / 8.0)
    rhythm = analysis.beat_regularity * (0.4 + 0.6 * busyness)

    if context.duration_s > 0 and analysis.duration_s > 0:
        if analysis.duration_s >= context.duration_s:
            length = 1.0
        else:
            length = max(0.35, analysis.duration_s / context.duration_s)
    else:
        length = 0.6

    mood = 0.0
    if context.mood and analysis.mood:
        mood = 1.0 if context.mood.casefold() == analysis.mood.casefold() else 0.0

    score = (
        0.30 * energy_target
        + 0.20 * energy_match
        + 0.20 * tempo
        + 0.15 * rhythm
        + 0.10 * length
        + 0.05 * mood
    )
    return round(max(0.0, min(1.0, score)), 4)


# --------------------------------------------------------------------------
# The AI path
# --------------------------------------------------------------------------


def build_proposal_context(
    context: ClipContext, candidates: list[store.MusicTrack]
) -> dict[str, Any]:
    """The structured payload the model sees.

    Measurements only — no file paths, no audio, no personal data. The model
    cannot request a file it was not told about.
    """
    return {
        "clip": context.to_dict(),
        "tracks": [
            {
                "id": track.id,
                "name": track.name,
                "title": track.title,
                "artist": track.artist,
                "tags": track.tag_list,
                "duration_s": round(track.analysis.duration_s or track.duration_s, 2),
                "bpm": track.analysis.bpm,
                "bpm_confidence": track.analysis.bpm_confidence,
                "energy": track.analysis.energy,
                "mood": track.analysis.mood,
                "beat_regularity": track.analysis.beat_regularity,
                "groove_strength": track.analysis.groove_strength,
                "loudness_lufs": track.analysis.loudness_lufs,
            }
            for track in candidates
        ],
    }


def parse_proposal(raw: str) -> tuple[str, str]:
    """Read a model's answer.

    Returns ``(track_id, reason)``. The model is asked for one JSON object,
    but a bare track id is accepted too, because a model that answers with
    prose around the id is still making a legible choice.
    """
    text = raw.strip()
    if not text:
        return ("", "")

    try:
        data = json.loads(text)
    except ValueError:
        match = re.search(r"[A-Za-z0-9_]{4,64}", text)
        return (match.group(0) if match else "", text.strip()[:400])

    if isinstance(data, dict):
        track_id = str(data.get("track_id") or data.get("id") or "")
        reason = str(data.get("reason") or data.get("why") or "")
        return (track_id.strip(), reason.strip()[:400])

    if isinstance(data, list) and data:
        first = data[0]
        if isinstance(first, dict):
            return (
                str(first.get("track_id") or first.get("id") or "").strip(),
                str(first.get("reason") or "").strip()[:400],
            )

    return ("", "")


def select_track(
    context: ClipContext,
    *,
    candidates: list[store.MusicTrack] | None = None,
    proposer: Proposer | None = None,
    user_choice: str = "",
    budget: CallBudget | None = None,
) -> MusicSelection | None:
    """Choose a track for a clip.

    The order is deliberate:

    1. A manual choice wins, and no model is consulted.
    2. A model's proposal is used only if it names a candidate that exists
       **and** may legally be used.
    3. Otherwise the deterministic scorer picks.

    Returns ``None`` when there is nothing to choose from.
    """
    if user_choice:
        chosen = store.get_track(user_choice)
        if chosen is not None:
            return MusicSelection(
                track_id=chosen.id,
                track_name=chosen.name,
                source="user",
                reason="Chosen by you.",
                score=1.0,
            )

    pool = candidates if candidates is not None else store.list_tracks()
    usable: list[store.MusicTrack] = []
    for track in pool:
        if track.excluded:
            continue
        record = store.get_license(track.id)
        if not evaluate(record).allowed:
            # A track that may not be exported is not a candidate, whatever the
            # model says about it.
            continue
        usable.append(track)

    if not usable:
        return None

    if proposer is not None:
        if budget is None or budget.take():
            try:
                raw = proposer(build_proposal_context(context, usable))
            except Exception as exc:  # noqa: BLE001 - a model failure is not a crash
                log.warning("Music proposal failed: %s", exc)
            else:
                track_id, reason = parse_proposal(raw)
                match = next((track for track in usable if track.id == track_id), None)
                if match is not None:
                    verdict = evaluate(store.get_license(match.id))
                    return MusicSelection(
                        track_id=match.id,
                        track_name=match.name,
                        source="ai",
                        reason=reason or "Chosen by the AI model.",
                        score=score_track(context, match.analysis),
                        warnings=list(verdict.warnings),
                    )
                log.info(
                    "The music proposal named %r, which is not an available track; "
                    "falling back to the deterministic choice.",
                    track_id,
                )
        elif budget is not None:
            log.warning("Music selection budget spent; choosing deterministically.")

    best = max(usable, key=lambda track: score_track(context, track.analysis))
    return MusicSelection(
        track_id=best.id,
        track_name=best.name,
        source="deterministic",
        reason=(
            f"{best.analysis.mood or 'unclassified'} at {best.analysis.bpm or 0:.0f} BPM, "
            f"energy {best.analysis.energy:.2f}."
        ),
        score=score_track(context, best.analysis),
        warnings=list(evaluate(store.get_license(best.id)).warnings),
    )


def default_budget(max_clips: int) -> CallBudget:
    """The approved budget: one music call per eligible clip."""
    return CallBudget(max_calls=max(0, int(max_clips)))
