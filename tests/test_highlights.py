"""One job must not produce the same clip twice.

The pipeline drops a candidate that repeats a moment another clip already
covers, and the diagnostic reports the pairs that survived. When the two
disagree — when the pipeline keeps a pair the diagnostic calls duplicates —
the user gets two clips of the same footage and a report that says so.

A real run produced two such pairs. The shorter clip of each pair sat
*inside* the longer one, and the pipeline's overlap test could not see it:
that test compares the *word ranges* of the candidates, and a word range
says very little about the time a clip covers. The shorter clip of the first
pair covered fourteen words; the longer one covered a hundred and four, of
which those fourteen were a part — a common share of a fifth, well under
the threshold. In time, though, the shorter clip was wholly inside the
longer one: the same clip, twice.

So the pipeline now compares the clips in time, and it uses the same rule
the diagnostic uses.
"""

from __future__ import annotations

from autoclip.db.models import Clip
from autoclip.pipeline import diagnostics, highlights


def _clip(
    start_s: float,
    end_s: float,
    score: int,
    *,
    start_word: int,
    end_word: int,
    title: str = "A clip",
) -> Clip:
    return Clip(
        id=f"clip-{start_s}-{end_s}",
        job_id="job-1",
        start_s=start_s,
        end_s=end_s,
        start_word=start_word,
        end_word=end_word,
        score=score,
        title=title,
    )


class TestDuplicateClips:
    def test_a_clip_contained_in_another_is_dropped(self) -> None:
        """The higher-scoring clip of the pair survives.

        These are the two clips of a real run: a 23.8-second clip and a
        47-second clip that contained it entirely. Their word ranges share
        only a fifth of their words, so the word-range test could not see
        that they were the same clip.
        """
        shorter = _clip(533.852, 557.610, 79, start_word=1014, end_word=1028)
        longer = _clip(514.150, 561.180, 75, start_word=941, end_word=1045)

        kept = highlights._dedupe_clips([shorter, longer])

        assert [clip.id for clip in kept] == [shorter.id]

    def test_a_second_contained_pair_of_a_real_run_is_dropped(self) -> None:
        shorter = _clip(107.970, 131.250, 50, start_word=269, end_word=290)
        longer = _clip(100.410, 140.470, 60, start_word=244, end_word=329)

        kept = highlights._dedupe_clips([longer, shorter])

        assert [clip.id for clip in kept] == [longer.id]

    def test_clips_that_only_touch_are_kept(self) -> None:
        first = _clip(0.0, 30.0, 90, start_word=0, end_word=10)
        second = _clip(30.0, 60.0, 80, start_word=11, end_word=20)

        kept = highlights._dedupe_clips([first, second])

        assert len(kept) == 2

    def test_clips_that_share_a_little_are_kept(self) -> None:
        # 10 seconds of a 40-second clip is a quarter of it: not the same clip.
        first = _clip(0.0, 40.0, 90, start_word=0, end_word=40)
        second = _clip(30.0, 70.0, 80, start_word=30, end_word=70)

        kept = highlights._dedupe_clips([first, second])

        assert len(kept) == 2

    def test_nothing_the_pipeline_keeps_is_called_a_duplicate(self) -> None:
        """The pipeline and the diagnostic have one definition of duplicate."""
        clips = [
            _clip(533.852, 557.610, 79, start_word=1014, end_word=1028),
            _clip(514.150, 561.180, 75, start_word=941, end_word=1045),
            _clip(100.410, 140.470, 60, start_word=244, end_word=329),
            _clip(107.970, 131.250, 50, start_word=269, end_word=290),
            _clip(2.060, 26.670, 40, start_word=0, end_word=58),
        ]

        kept = highlights._dedupe_clips(clips)

        assert diagnostics.duplicate_clips(kept) == []
