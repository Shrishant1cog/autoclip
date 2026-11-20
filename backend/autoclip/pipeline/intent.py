"""Story and gameplay intent — a configurable bias, not a fixed split.

A user might want the clip that explains something, or the clip that shows
something happening. Both are legitimate, and the balance between them is
the user's to set.

Three things make this honest rather than decorative:

* **No arbitrary split.** Nothing here requires half the clips to be
  story and half to be action. The setting is a *bias* in the ranking,
  and a video with no action in it produces no action clips — it does
  not produce filler.

* **The signals are measured.** Story is the speech density, read from
  the same shared timeline the music ducking reads. Action is the rate of
  scene changes, read from the same shot list the reframer uses. Neither
  is a guess.

* **The default changes nothing.** With the default setting the
  adjustment is exactly zero for every clip, so a user who never touches
  the setting gets the behaviour they had before.

The model's own score is never thrown away. It judges the hook and the
payoff, which cannot be measured from a signal. The adjustment is a
small, bounded tilt on top of it — at most fifteen points either way.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass

log = logging.getLogger(__name__)

__all__ = [
    "ClipCharacter",
    "STORY_BIAS",
    "adjust_score",
    "character_of",
    "effective_density",
    "style_instruction",
]

#: The most the balance may move a clip's score, either way.
STORY_BIAS = 15

#: The density that means "no preference" — the default.
DEFAULT_STORY_DENSITY = 0.5

#: Scene changes per minute at which a clip counts as fully action.
ACTION_CUTS_PER_MINUTE = 8.0

#: The densities the coarse style switch selects.
STORY_DENSITY = 0.75
ACTION_DENSITY = 0.25


@dataclass(frozen=True)
class ClipCharacter:
    """What a clip is made of, in two measured numbers."""

    #: How much of the clip is speech, from 0 to 1.
    story: float
    #: How much the clip is moving, from 0 to 1.
    action: float
    #: The clip's own balance: how much of its character is story.
    balance: float

    def to_dict(self) -> dict[str, float]:
        return {
            "story": round(self.story, 3),
            "action": round(self.action, 3),
            "balance": round(self.balance, 3),
        }


def _clamp(value: float, low: float = 0.0, high: float = 1.0) -> float:
    return max(low, min(high, value))


def character_of(
    *,
    speech_density: float,
    cuts_per_minute: float,
) -> ClipCharacter:
    """Measure what a clip is made of.

    ``speech_density`` is the fraction of the clip covered by speech, and
    ``cuts_per_minute`` is the rate of scene changes. Both are
    measurements; neither is a judgement.
    """
    story = _clamp(speech_density)
    action = _clamp(cuts_per_minute / ACTION_CUTS_PER_MINUTE)

    total = story + action
    if total <= 0:
        # Nothing measured — a silent clip with no cuts. It has no
        # character to be biased towards or away from.
        return ClipCharacter(story=story, action=action, balance=DEFAULT_STORY_DENSITY)

    return ClipCharacter(story=story, action=action, balance=story / total)


def effective_density(*, story_density: float, highlight_style: str) -> float:
    """The balance that actually applies.

    The coarse style switch overrides the fine setting when it is not
    "auto": choosing "story" is a deliberate statement that the fine
    slider is not what the user meant this time.
    """
    style = (highlight_style or "auto").strip().lower()
    if style == "story":
        return STORY_DENSITY
    if style == "action":
        return ACTION_DENSITY
    return _clamp(story_density)


def adjust_score(
    base: int,
    *,
    speech_density: float,
    cuts_per_minute: float,
    story_density: float,
    highlight_style: str = "auto",
) -> tuple[int, ClipCharacter]:
    """Tilt a clip's score towards the balance the user asked for.

    Returns the adjusted score and the character that was measured, so
    the adjustment can be explained rather than merely applied.

    The tilt is zero for every clip when the balance is the default, and
    never exceeds :data:`STORY_BIAS` either way.
    """
    character = character_of(
        speech_density=speech_density,
        cuts_per_minute=cuts_per_minute,
    )

    wanted = effective_density(
        story_density=story_density,
        highlight_style=highlight_style,
    )
    preference = wanted - DEFAULT_STORY_DENSITY
    if abs(preference) < 1e-9:
        # The default setting changes nothing.
        return base, character

    # The clip's own balance, measured from the same midpoint. A clip
    # that is more story than the midpoint gains when a story-heavy
    # balance is asked for, and loses when an action-heavy one is.
    offset = character.balance - DEFAULT_STORY_DENSITY
    adjustment = round(preference * offset * 4 * STORY_BIAS)

    adjusted = max(0, min(100, base + adjustment))
    return adjusted, character


def style_instruction(*, story_density: float, highlight_style: str) -> str:
    """The line that tells the model which moments to look for.

    The model sees the transcript, not the signals, so the preference
    has to be said in words. The wording names the two kinds of moment
    rather than a number, because the model cannot count scene changes.
    """
    style = (highlight_style or "auto").strip().lower()
    wanted = effective_density(
        story_density=story_density,
        highlight_style=highlight_style,
    )

    if style == "story":
        return (
            "This video's highlights should be STORY moments: a line that explains "
            "something, a decision that is made, a point that lands. Prefer the "
            "moment a viewer would quote over the moment that looks exciting."
        )
    if style == "action":
        return (
            "This video's highlights should be ACTION moments: the thing happening, "
            "the reaction, the turn of the match. Prefer the moment a viewer would "
            "re-watch over the moment that explains something."
        )

    if wanted > 0.6:
        return (
            "Favour story moments: the ones where something is explained, decided, "
            "or realised. Action moments are still welcome, but a quiet, clear "
            "moment beats a loud one."
        )
    if wanted < 0.4:
        return (
            "Favour action moments: the ones where something happens and the "
            "energy rises. Story moments are still welcome, but a moment that "
            "moves beats a moment that explains."
        )
    return ""
