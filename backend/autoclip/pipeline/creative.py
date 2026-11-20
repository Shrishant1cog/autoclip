"""The structured creative plan.

One call per job. The model proposes; deterministic code decides.

The plan is a JSON object with a fixed shape. Every field is checked
before it is used, and anything that does not check out is rejected —
not patched, not half-applied. A model that names a caption style AutoClip
does not have does not get to have a caption style.

When the model fails — a refusal, malformed JSON, a schema violation — the
plan falls back to the deterministic one, and says so. The render still
happens; it just happens without the model's opinion.

The plan never contains a file path, a transcript, or anything else the
user did not expect to leave the machine. It carries clip ids, titles,
timings and the *measured* metadata of the candidate tracks.
"""

from __future__ import annotations

import json
import logging
import re
from dataclasses import dataclass, field
from typing import Any

from ..db.models import Clip
from ..providers.base import ProviderConsentRequired
from ..security import consent
from .captions import PRESETS as CAPTION_PRESETS

log = logging.getLogger(__name__)

__all__ = [
    "ClipDirection",
    "CreativePlan",
    "PlanRejected",
    "build_context",
    "fallback_plan",
    "parse_plan",
    "plan_creative",
    "validate_plan",
]

#: The layouts the planner knows.
LAYOUTS = ("auto", "above", "corner", "gameplay_only")

#: The crop strategies the reframe stage knows.
CROPS = ("auto", "speaker", "wide", "static")

#: The transitions the export stage knows.
TRANSITIONS = ("cut", "crossfade", "none")

#: The output ratios the export stage knows.
RATIOS = ("9:16", "1:1", "16:9")

#: The deepest the bed may be ducked, in dB. Quieter than this and the
#: music is not there any more.
MIN_DUCKING_DB = -30.0

#: The loudest the bed may be ducked. Zero means "do not duck".
MAX_DUCKING_DB = 0.0


class PlanRejected(ValueError):
    """The model's answer did not match the schema.

    The message is the list of problems, because it goes straight back to
    the model as the repair prompt.
    """

    def __init__(self, problems: list[str]) -> None:
        super().__init__("; ".join(problems) if problems else "the plan was rejected")
        self.problems = problems


@dataclass
class ClipDirection:
    """What the plan says about one clip."""

    clip_id: str
    layout: str = "auto"
    crop: str = "auto"
    caption_strategy: str = ""
    music_track_id: str = ""
    ducking_db: float = 0.0
    transition: str = "cut"
    #: The model's reason, kept so the user can read why it chose this.
    reason: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "clip_id": self.clip_id,
            "layout": self.layout,
            "crop": self.crop,
            "caption_strategy": self.caption_strategy,
            "music_track_id": self.music_track_id,
            "ducking_db": round(self.ducking_db, 2),
            "transition": self.transition,
            "reason": self.reason,
        }


@dataclass
class CreativePlan:
    """The whole plan: one direction per clip, plus the job-wide choices."""

    clips: list[ClipDirection] = field(default_factory=list)
    export_ratio: str = ""
    export_settings: dict[str, Any] = field(default_factory=dict)
    notes: list[str] = field(default_factory=list)
    #: "ai" when the model's answer validated, "fallback" when the
    #: deterministic plan was used instead.
    source: str = "fallback"
    #: What was wrong with the model's answer, if it was. Empty when the
    #: answer was fine.
    problems: list[str] = field(default_factory=list)
    #: Whether the plan's music suggestion was checked against the library's
    #: licence records.
    music_verified: bool = False

    def direction_for(self, clip_id: str) -> ClipDirection | None:
        for direction in self.clips:
            if direction.clip_id == clip_id:
                return direction
        return None

    def to_dict(self) -> dict[str, Any]:
        return {
            "clips": [direction.to_dict() for direction in self.clips],
            "export_ratio": self.export_ratio,
            "export_settings": dict(self.export_settings),
            "notes": list(self.notes),
            "source": self.source,
            "problems": list(self.problems),
            "music_verified": self.music_verified,
        }


# --------------------------------------------------------------------------
# The context the model sees
# --------------------------------------------------------------------------


def build_context(
    clips: list[Clip],
    *,
    tracks: list[dict[str, Any]] | None = None,
    detected_layout: str = "",
    layout_confidence: float = 0.0,
    speech_density: dict[str, float] | None = None,
    scene_changes: dict[str, int] | None = None,
    default_ratio: str = "9:16",
) -> dict[str, Any]:
    """The structured payload the model sees.

    Measurements and clip metadata only. No transcript, no file path, no
    audio, and nothing that identifies anybody — the webcam region is
    described by its confidence and nothing else.
    """
    density = speech_density or {}
    cuts = scene_changes or {}

    return {
        "clips": [
            {
                "clip_id": clip.id,
                "title": clip.title,
                "hook": clip.hook,
                "reason": clip.reason,
                "start_s": round(clip.start_s, 2),
                "end_s": round(clip.end_s, 2),
                "duration_s": round(max(0.0, clip.end_s - clip.start_s), 2),
                "speech_density": round(density.get(clip.id, 0.0), 3),
                "scene_changes": int(cuts.get(clip.id, 0)),
            }
            for clip in clips
        ],
        "layout": {
            "detected": detected_layout,
            "confidence": round(layout_confidence, 3),
            "options": list(LAYOUTS),
        },
        "music": tracks or [],
        "caption_styles": sorted(CAPTION_PRESETS),
        "crop_options": list(CROPS),
        "transition_options": list(TRANSITIONS),
        "default_ratio": default_ratio,
    }


SYSTEM_PROMPT = """\
You are planning how a short vertical clip should be edited.

You are given the clips that were found, the layout that was detected (if
any), and the measured metadata of the music in the user's library.

Answer with ONE JSON object and nothing else. No prose, no markdown fences.

The object has this shape:

{
  "clips": [
    {
      "clip_id": "the exact id you were given",
      "layout": "auto | above | corner | gameplay_only",
      "crop": "auto | speaker | wide | static",
      "caption_strategy": "one of the caption styles you were given",
      "music_track_id": "the exact id of a track you were given, or an empty string",
      "ducking_db": -12.0,
      "transition": "cut | crossfade | none",
      "reason": "one sentence saying why"
    }
  ],
  "export_ratio": "9:16 | 1:1 | 16:9",
  "notes": ["one short line per clip, in the same order"]
}

Rules:

* Use only the clip ids and track ids you were given. Never invent one.
* "auto" means "let AutoClip decide" — use it when you have no strong
  reason.
* ducking_db is how far the music drops under speech, in decibels. It is
  between -30 and 0. Zero means no ducking.
* If a clip is mostly talking, choose a calm track and a gentle ducking
  value. If it is an action moment, choose a driving track and a deeper
  duck so the voice stays clear.
* Never name a track that is not in the list you were given.
"""


# --------------------------------------------------------------------------
# Parsing and validation
# --------------------------------------------------------------------------


def _as_float(value: Any, default: float = 0.0) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def _extract_json(raw: str) -> dict[str, Any]:
    """Pull the JSON object out of a reply.

    Models wrap their answers in prose and fences more often than they
    should, and rejecting the whole plan over a fence would waste the call.
    """
    text = raw.strip()
    if not text:
        raise PlanRejected(["the model returned nothing"])

    try:
        data = json.loads(text)
    except ValueError:
        match = re.search(r"\{.*\}", text, re.DOTALL)
        if not match:
            raise PlanRejected(["the model's answer was not JSON"]) from None
        try:
            data = json.loads(match.group(0))
        except ValueError as exc:
            raise PlanRejected([f"the model's answer was not valid JSON: {exc}"]) from None

    if not isinstance(data, dict):
        raise PlanRejected(["the model's answer was not a JSON object"])
    return data


def validate_plan(
    data: dict[str, Any],
    *,
    clip_ids: list[str],
    track_ids: list[str],
) -> CreativePlan:
    """Check the model's answer against the facts, and build the plan.

    A problem is collected rather than raised at the first sign of one, so
    the repair prompt can tell the model everything that is wrong at once.
    """
    problems: list[str] = []

    raw_clips = data.get("clips")
    if not isinstance(raw_clips, list):
        raise PlanRejected(["the plan has no 'clips' list"])
    if not raw_clips:
        raise PlanRejected(["the plan's 'clips' list is empty"])

    known_clips = set(clip_ids)
    known_tracks = set(track_ids)
    directions: list[ClipDirection] = []
    seen: set[str] = set()

    for index, item in enumerate(raw_clips):
        if not isinstance(item, dict):
            problems.append(f"clip {index} was not an object")
            continue

        clip_id = str(item.get("clip_id") or "").strip()
        if not clip_id:
            problems.append(f"clip {index} had no clip_id")
            continue
        if clip_id not in known_clips:
            problems.append(f"clip_id {clip_id!r} is not one of the clips")
            continue
        if clip_id in seen:
            problems.append(f"clip_id {clip_id!r} appears twice")
            continue
        seen.add(clip_id)

        layout = str(item.get("layout") or "auto").strip()
        if layout not in LAYOUTS:
            problems.append(f"clip {clip_id}: layout {layout!r} is not one of {list(LAYOUTS)}")
            layout = "auto"

        crop = str(item.get("crop") or "auto").strip()
        if crop not in CROPS:
            problems.append(f"clip {clip_id}: crop {crop!r} is not one of {list(CROPS)}")
            crop = "auto"

        caption = str(item.get("caption_strategy") or "").strip()
        if caption and caption not in CAPTION_PRESETS:
            problems.append(
                f"clip {clip_id}: caption_strategy {caption!r} is not a style AutoClip has"
            )
            caption = ""

        track_id = str(item.get("music_track_id") or "").strip()
        if track_id and track_id not in known_tracks:
            problems.append(f"clip {clip_id}: music_track_id {track_id!r} is not in the library")
            track_id = ""

        transition = str(item.get("transition") or "cut").strip()
        if transition not in TRANSITIONS:
            problems.append(
                f"clip {clip_id}: transition {transition!r} is not one of {list(TRANSITIONS)}"
            )
            transition = "cut"

        ducking = _as_float(item.get("ducking_db"), 0.0)
        if not (MIN_DUCKING_DB <= ducking <= MAX_DUCKING_DB):
            problems.append(
                f"clip {clip_id}: ducking_db {ducking} is outside "
                f"{MIN_DUCKING_DB}..{MAX_DUCKING_DB}"
            )
            ducking = max(MIN_DUCKING_DB, min(MAX_DUCKING_DB, ducking))

        directions.append(
            ClipDirection(
                clip_id=clip_id,
                layout=layout,
                crop=crop,
                caption_strategy=caption,
                music_track_id=track_id,
                ducking_db=ducking,
                transition=transition,
                reason=str(item.get("reason") or "").strip()[:400],
            )
        )

    ratio = str(data.get("export_ratio") or "").strip()
    if ratio and ratio not in RATIOS:
        problems.append(f"export_ratio {ratio!r} is not one of {list(RATIOS)}")
        ratio = ""

    notes_raw = data.get("notes")
    notes: list[str] = []
    if isinstance(notes_raw, list):
        notes = [str(note).strip()[:400] for note in notes_raw if str(note).strip()]
    elif notes_raw:
        problems.append("'notes' was not a list")

    if problems:
        raise PlanRejected(problems)

    return CreativePlan(
        clips=directions,
        export_ratio=ratio,
        notes=notes,
        source="ai",
    )


def parse_plan(
    raw: str,
    *,
    clip_ids: list[str],
    track_ids: list[str],
) -> CreativePlan:
    """Read the model's answer and check it."""
    return validate_plan(_extract_json(raw), clip_ids=clip_ids, track_ids=track_ids)


# --------------------------------------------------------------------------
# The deterministic fallback
# --------------------------------------------------------------------------


def fallback_plan(
    clips: list[Clip],
    *,
    default_ratio: str = "9:16",
    reason: str = "",
) -> CreativePlan:
    """The plan used when the model's answer cannot be trusted.

    It is not a poor plan — it is the *absence* of a plan, expressed in
    the same shape. Every clip gets the automatic decisions, which are
    the ones the deterministic code would have made anyway.

    The reason belongs in ``problems``, not in ``notes``: it is why the
    plan fell back, and the notes are the model's own lines about the
    clips. Putting it in both would show the same sentence twice.
    """
    return CreativePlan(
        clips=[
            ClipDirection(
                clip_id=clip.id,
                layout="auto",
                crop="auto",
                caption_strategy="",
                music_track_id="",
                ducking_db=0.0,
                transition="cut",
                reason="",
            )
            for clip in clips
        ],
        export_ratio=default_ratio,
        notes=[],
        source="fallback",
        problems=[reason] if reason else [],
    )


# --------------------------------------------------------------------------
# The call
# --------------------------------------------------------------------------


async def plan_creative(
    provider: Any,
    budget: Any,
    *,
    clips: list[Clip],
    tracks: list[dict[str, Any]] | None = None,
    detected_layout: str = "",
    layout_confidence: float = 0.0,
    speech_density: dict[str, float] | None = None,
    scene_changes: dict[str, int] | None = None,
    default_ratio: str = "9:16",
) -> CreativePlan:
    """Ask the model for a plan, and fall back when it cannot be trusted.

    The budget allows one planning call and one repair. If the first
    answer does not check out, the problems are sent back and the model
    gets one more chance. If that fails too, the deterministic plan is
    used and the reasons are recorded on it.
    """
    if not clips:
        return fallback_plan(clips, default_ratio=default_ratio, reason="there were no clips")

    context = build_context(
        clips,
        tracks=tracks,
        detected_layout=detected_layout,
        layout_confidence=layout_confidence,
        speech_density=speech_density,
        scene_changes=scene_changes,
        default_ratio=default_ratio,
    )
    user = json.dumps(context, indent=2, ensure_ascii=False)

    clip_ids = [clip.id for clip in clips]
    track_ids = [str(track.get("id") or "") for track in (tracks or [])]

    if not budget.take_plan("the creative-planning budget was already spent"):
        return fallback_plan(
            clips, default_ratio=default_ratio, reason="the creative-planning budget was spent"
        )

    try:
        raw = await provider.generate_text(
            SYSTEM_PROMPT,
            user,
            temperature=0.3,
            operation=consent.Operation.CREATIVE_PLANNING,
            data_summary=(
                "Your clip titles, boundaries, the detected layout and the measured "
                "metadata of your music."
            ),
        )
    except ProviderConsentRequired:
        # The user withdrew consent for this operation. That is an answer,
        # not a failure, and it is not retried against another provider.
        raise
    except Exception as exc:  # noqa: BLE001 - a model failure is not a crash
        log.warning("The creative-planning call failed: %s", exc)
        return fallback_plan(
            clips, default_ratio=default_ratio, reason=f"the planning call failed: {exc}"
        )

    try:
        return parse_plan(raw, clip_ids=clip_ids, track_ids=track_ids)
    except PlanRejected as rejected:
        problems = rejected.problems
        log.warning(
            "The creative plan did not match the schema (%s); trying the repair retry.",
            "; ".join(problems),
        )

    if not budget.take_repair("the repair retry was already spent"):
        return fallback_plan(
            clips,
            default_ratio=default_ratio,
            reason="the plan did not match the schema and the repair retry was not available",
        )

    repair = (
        f"{user}\n\n"
        "Your previous response did not match the required schema.\n"
        f"Validation problems:\n- " + "\n- ".join(problems) + "\n\n"
        "Answer again with ONLY the corrected JSON object. No prose, no markdown fences."
    )
    try:
        raw = await provider.generate_text(
            SYSTEM_PROMPT,
            repair,
            temperature=0.2,
            operation=consent.Operation.CREATIVE_PLANNING,
            data_summary=(
                "Your clip titles, boundaries, the detected layout and the measured "
                "metadata of your music."
            ),
        )
    except ProviderConsentRequired:
        raise
    except Exception as exc:  # noqa: BLE001
        log.warning("The creative-planning repair failed: %s", exc)
        return fallback_plan(
            clips, default_ratio=default_ratio, reason=f"the planning repair failed: {exc}"
        )

    try:
        return parse_plan(raw, clip_ids=clip_ids, track_ids=track_ids)
    except PlanRejected as rejected:
        return fallback_plan(
            clips,
            default_ratio=default_ratio,
            reason=(
                "the plan did not match the schema after the repair retry: "
                + "; ".join(rejected.problems)
            ),
        )
