"""Finding the webcam's own frame in a picture.

A face says somebody is on screen. It does not say where the webcam's own
frame is, and the difference matters: a crop built from the face alone
spills outside the webcam and shows a strip of gameplay above and below it.

These tests build the pictures rather than filming them, so that each rule
is checked on its own:

* the edges are found where the picture really has a step;
* a bright patch in the scene is not mistaken for the edge of the webcam,
  however bright it is — what counts is how much of the edge shows the step;
* a webcam that runs off the top of the picture is reported as running off
  it, not as having an edge there;
* when no edge can be found at all, the face-based estimate is kept.
"""

from __future__ import annotations

import numpy as np
import pytest
from autoclip.pipeline.reframe.webcam import Rect
from autoclip.pipeline.reframe.webcambox import (
    MIN_HORIZONTAL_COVERAGE,
    estimate_cam_box,
    face_box_region,
)

WIDTH = 960
HEIGHT = 540

BACKGROUND = 50
WEBCAM = 190
FACE = 230

#: The webcam's own frame: it runs off the top of the picture, as a streamer's
#: camera usually does.
BOX_LEFT = 560
BOX_RIGHT = 860
BOX_BOTTOM = 210

#: The face inside it.
FACE_RECT = Rect(x=655.0, y=25.0, width=90.0, height=110.0)


def _picture(
    *,
    panel: tuple[int, int, int, int] | None = None,
    panel_brightness: int = 250,
) -> np.ndarray:
    """A picture with a webcam in it, and nothing else.

    ``panel`` is a bright rectangle in the scene, given as
    ``(left, top, right, bottom)``. It stands in for the bright panel of a
    game menu: a strong step that is not the edge of the webcam.
    """
    frame = np.full((HEIGHT, WIDTH), BACKGROUND, dtype=np.float32)

    frame[0:BOX_BOTTOM, BOX_LEFT:BOX_RIGHT] = WEBCAM
    face = FACE_RECT
    frame[int(face.y) : int(face.bottom), int(face.x) : int(face.right)] = FACE

    if panel is not None:
        left, top, right, bottom = panel
        frame[top:bottom, left:right] = panel_brightness

    return frame


class TestTheEdgesAreFound:
    def test_the_box_is_found_where_the_picture_has_a_step(self) -> None:
        estimate = estimate_cam_box(_picture(), FACE_RECT, source_width=WIDTH, source_height=HEIGHT)

        assert estimate is not None
        assert estimate.rect.x == pytest.approx(BOX_LEFT, abs=2)
        assert estimate.rect.right == pytest.approx(BOX_RIGHT, abs=2)
        assert estimate.rect.bottom == pytest.approx(BOX_BOTTOM, abs=2)

    def test_the_edges_that_were_seen_are_recorded(self) -> None:
        estimate = estimate_cam_box(_picture(), FACE_RECT, source_width=WIDTH, source_height=HEIGHT)

        assert estimate is not None
        left, top, right, bottom = estimate.edges_found
        assert left is True
        assert right is True
        assert bottom is True
        # The webcam runs off the top of the picture, so there is no step
        # there to find.
        assert top is False

    def test_a_webcam_that_runs_off_the_top_starts_at_the_top(self) -> None:
        estimate = estimate_cam_box(_picture(), FACE_RECT, source_width=WIDTH, source_height=HEIGHT)

        assert estimate is not None
        assert estimate.rect.y == pytest.approx(0.0, abs=2)


class TestTheSceneIsNotMistakenForTheWebcam:
    def test_the_scene_is_not_mistaken_for_the_webcam(self) -> None:
        """A bright patch is not an edge, however bright it is.

        The panel below is stronger than the webcam's own edge, and it covers
        most of the webcam's width. What it does not do is show the step
        along all of it — and that is what tells the two apart.
        """
        panel = (BOX_LEFT, BOX_BOTTOM + 30, BOX_LEFT + 252, BOX_BOTTOM + 120)

        estimate = estimate_cam_box(
            _picture(panel=panel),
            FACE_RECT,
            source_width=WIDTH,
            source_height=HEIGHT,
        )

        assert estimate is not None
        assert estimate.rect.bottom == pytest.approx(BOX_BOTTOM, abs=2)

    def test_the_panel_would_have_won_on_brightness_alone(self) -> None:
        """The rule that saves the frame is the coverage, not the contrast.

        Without this the test above would pass for the wrong reason: the
        panel's step has to be strong enough that brightness alone would
        have picked it.
        """
        panel = (BOX_LEFT, BOX_BOTTOM + 30, BOX_LEFT + 252, BOX_BOTTOM + 120)
        picture = _picture(panel=panel, panel_brightness=250)

        inside = picture[BOX_BOTTOM + 30 : BOX_BOTTOM + 33, BOX_LEFT:BOX_RIGHT].mean(axis=0)
        outside = picture[BOX_BOTTOM + 27 : BOX_BOTTOM + 30, BOX_LEFT:BOX_RIGHT].mean(axis=0)
        steps = np.abs(inside - outside)

        contrast = float(steps.mean())
        coverage = float((steps >= contrast * 0.25).mean())

        # Stronger than the webcam's own edge of 140...
        assert contrast > 140.0
        # ...but it does not show the step along the whole edge.
        assert coverage < MIN_HORIZONTAL_COVERAGE
        # And brightness times coverage would have chosen the panel.
        assert contrast * coverage > 140.0


class TestTheFallback:
    def test_a_picture_with_no_edges_keeps_the_face_estimate(self) -> None:
        """Nothing to measure means the face-based estimate is the answer."""
        picture = np.full((HEIGHT, WIDTH), BACKGROUND, dtype=np.float32)
        face = FACE_RECT
        picture[int(face.y) : int(face.bottom), int(face.x) : int(face.right)] = FACE

        estimate = estimate_cam_box(picture, FACE_RECT, source_width=WIDTH, source_height=HEIGHT)

        assert estimate is not None
        assert estimate.edges_found == (False, False, False, False)

        expected = face_box_region(FACE_RECT)
        assert estimate.rect.x == pytest.approx(expected.x, abs=1)
        assert estimate.rect.width == pytest.approx(expected.width, abs=1)

    def test_the_face_is_always_inside_the_estimate(self) -> None:
        picture = np.full((HEIGHT, WIDTH), BACKGROUND, dtype=np.float32)
        face = FACE_RECT
        picture[int(face.y) : int(face.bottom), int(face.x) : int(face.right)] = FACE

        estimate = estimate_cam_box(picture, FACE_RECT, source_width=WIDTH, source_height=HEIGHT)

        assert estimate is not None
        assert estimate.rect.x <= face.x
        assert estimate.rect.right >= face.right
        assert estimate.rect.y <= face.y
        assert estimate.rect.bottom >= face.bottom
