"""What shape a track is, in words a person can filter by.

Tempo and energy are numbers, and a person browsing a library thinks in
words: *"I want something short"*, *"something steady under the talking"*,
*"something that won't fight the edits"*. This module turns the
measurements into those words.

Every format is a **measurement**, not a guess. The thresholds are written
down here, and the same numbers produce the same words every time.

A track carries more than one format. A short, sparse, steady loop is
three things at once, and filtering by any one of them should find it.
"""

from __future__ import annotations

from dataclasses import dataclass

from .analysis import Analysis

__all__ = [
    "FORMATS",
    "Format",
    "classify",
    "describe",
]


@dataclass(frozen=True)
class Format:
    """One named shape a track can have."""

    value: str
    title: str
    description: str
    #: The measurement the name comes from, in plain words.
    measured: str


#: The formats a track can carry, in the order the settings screen lists
#: them.
FORMATS: tuple[Format, ...] = (
    Format(
        value="short",
        title="Short",
        description="Under half a minute — a sting rather than a bed.",
        measured="duration under 30 s",
    ),
    Format(
        value="long",
        title="Long",
        description="A minute or more, so it can sit under a whole clip.",
        measured="duration of 60 s or more",
    ),
    Format(
        value="steady",
        title="Steady",
        description="An even pulse, which gives the edits something to land on.",
        measured="beat regularity of 0.55 or more",
    ),
    Format(
        value="loose",
        title="Loose",
        description="No strong pulse — better under a calm clip than a fast one.",
        measured="beat regularity below 0.35",
    ),
    Format(
        value="sparse",
        title="Sparse",
        description="Quiet and thin, so speech stays clear.",
        measured="energy below 0.35",
    ),
    Format(
        value="driving",
        title="Driving",
        description="Strong and forward — it will carry an action clip.",
        measured="energy of 0.65 or more",
    ),
    Format(
        value="percussive",
        title="Percussive",
        description="Mostly drums, which suits a busy gameplay moment.",
        measured="percussive ratio of 0.45 or more",
    ),
    Format(
        value="harmonic",
        title="Harmonic",
        description="Mostly pitched instruments, which sits under talking.",
        measured="harmonic ratio of 0.55 or more",
    ),
    Format(
        value="wide",
        title="Wide",
        description="A broad stereo image — full and open.",
        measured="stereo width of 0.5 or more",
    ),
    Format(
        value="clipping",
        title="Clipping",
        description="The file itself distorts at peaks. Avoid it.",
        measured="more than 0.1% of samples at full scale",
    ),
)


def classify(analysis: Analysis) -> list[str]:
    """The formats a track carries.

    The list is sorted by the order the formats are declared in, so the
    settings screen and the API agree on what "the first format" means.
    """
    if analysis is None:
        return []

    tags: set[str] = set()

    if analysis.duration_s > 0:
        if analysis.duration_s < 30.0:
            tags.add("short")
        if analysis.duration_s >= 60.0:
            tags.add("long")

    if analysis.beat_regularity >= 0.55:
        tags.add("steady")
    elif analysis.beat_regularity < 0.35:
        tags.add("loose")

    if analysis.energy < 0.35:
        tags.add("sparse")
    if analysis.energy >= 0.65:
        tags.add("driving")

    if analysis.percussive_ratio >= 0.45:
        tags.add("percussive")
    if analysis.harmonic_ratio >= 0.55:
        tags.add("harmonic")

    if analysis.stereo_width >= 0.5:
        tags.add("wide")

    if analysis.clipping_ratio > 0.001:
        tags.add("clipping")

    order = {fmt.value: index for index, fmt in enumerate(FORMATS)}
    return sorted(tags, key=lambda value: order.get(value, 999))


def describe(value: str) -> Format | None:
    """The format with this name, if there is one."""
    for fmt in FORMATS:
        if fmt.value == value:
            return fmt
    return None
