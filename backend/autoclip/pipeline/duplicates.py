"""One definition of "the same clip", used by the pipeline and the diagnostic.

The pipeline drops a candidate that repeats a moment another clip already
covers, and the diagnostic reports the pairs that survived. When the two
disagree — when the pipeline keeps a pair the diagnostic calls duplicates —
the user gets two clips of the same footage and a report that says so.

A real run produced two such pairs. The shorter clip of each pair sat
*inside* the longer one, and the pipeline's overlap test could not see it:
that test measures how much two clips have in common against how much they
could have had in common, and a clip inside another has almost none of the
first and all of the second.

So both use the rule below: two clips are duplicates when the overlap covers
at least half of the shorter one.
"""

from __future__ import annotations

from collections.abc import Iterable
from typing import Any

__all__ = ["OVERLAP_LIMIT", "duplicate_pairs", "overlap_fraction"]

#: Two clips overlap by more than this fraction of the shorter one and they
#: are duplicates.
OVERLAP_LIMIT = 0.5


def overlap_fraction(
    first_start: float,
    first_end: float,
    second_start: float,
    second_end: float,
) -> float:
    """How much of the shorter clip falls inside the longer one.

    The fraction is of the *shorter* clip, because a 20-second clip that is
    entirely inside a 60-second one is a duplicate in every sense that
    matters to a viewer.
    """
    overlap = min(first_end, second_end) - max(first_start, second_start)
    if overlap <= 0:
        return 0.0
    shorter = min(first_end - first_start, second_end - second_start)
    if shorter <= 0:
        return 0.0
    return overlap / shorter


def duplicate_pairs(clips: Iterable[Any]) -> list[tuple[str, str, float]]:
    """The pairs of clips that overlap too much to be different clips.

    Returns ``(id_a, id_b, overlap_fraction)`` for each pair.
    """
    pairs: list[tuple[str, str, float]] = []
    ordered = sorted(clips, key=lambda clip: clip.start_s)
    for index, first in enumerate(ordered):
        for second in ordered[index + 1 :]:
            if second.start_s >= first.end_s:
                break
            fraction = overlap_fraction(first.start_s, first.end_s, second.start_s, second.end_s)
            if fraction >= OVERLAP_LIMIT:
                pairs.append((first.id, second.id, round(fraction, 3)))
    return pairs
