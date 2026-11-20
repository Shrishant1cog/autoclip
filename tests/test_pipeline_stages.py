"""The pipeline's stage list and its weights.

The stage list is the pipeline's order, and the order is a promise: a job
that fails at one stage resumes from that stage and reuses the artifacts
every earlier stage left behind. A new stage therefore has to be placed
deliberately, and the weights have to keep adding up to one — the overall
progress bar is a weighted sum, and a set that does not total one would
make the bar lie.
"""

from __future__ import annotations

import pytest
from autoclip.pipeline import Stage
from autoclip.pipeline.runner import STAGE_WEIGHTS


def test_the_creative_stage_is_part_of_the_pipeline() -> None:
    assert Stage.CREATIVE in list(Stage)
    assert Stage.CREATIVE.label


def test_the_stage_weights_still_add_up_to_one() -> None:
    assert sum(STAGE_WEIGHTS.values()) == pytest.approx(1.0)


def test_the_creative_stage_has_a_weight() -> None:
    assert STAGE_WEIGHTS[Stage.CREATIVE] > 0


def test_the_creative_stage_runs_before_the_reframe() -> None:
    """The plan has to exist before anything is built from it."""
    assert list(Stage).index(Stage.CREATIVE) < list(Stage).index(Stage.REFRAME)
