"""Finding the edge of the webcam box in a frame.

A face tells you somebody is on screen. It does not tell you where the
webcam's own frame is — and the difference matters, because a crop built
from the face alone spills outside the webcam and shows a strip of gameplay
above and below it.

The webcam box is a rectangle drawn over the video, so its edges are *steps*:
the pixels just inside the box and the pixels just outside it are different
scenes. This module finds those steps.

Two things make the search work on real footage.

**The edges are found in the right order.** The vertical edges are looked
for first, over the rows the face occupies. They are rare in a picture — a
vertical line of a different brightness across the height of a face is not
something a game screen does often — so they are found reliably. The
horizontal edges are then looked for over the *columns the box turned out to
occupy*, not over a narrow band around the face. That matters: the bright
panel of a game menu can have a stronger brightness step than the bottom of
the webcam, but it does not span the whole width of the webcam, so it does
not cover enough of it to be believed.

**Coverage, not brightness, decides.** A real box edge shows the step along
almost its whole length; a bright patch in the scene shows it in one place.
The score is therefore the size of the step multiplied by how much of the
edge shows it, and an edge that only shows the step along part of its
length is not an edge at all.

The search is deliberately narrow. The expected edge position is known from
the face box — a webcam shows the face with some headroom around it — and
the search looks only near that expectation. A wide search would find the
brightest edge anywhere near the face, and a streamer sits in front of a
neon sign more often than not.

Every edge is optional. When no step is found, the face-based estimate is
kept: a box that is a little too big is a much smaller fault than a box that
is wrong.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass

from .webcam import Rect

log = logging.getLogger(__name__)

__all__ = ["BoxEstimate", "estimate_cam_box", "face_box_region"]


#: How far from the expected edge the search looks, as a fraction of the
#: face's size. A webcam box is usually within one face-width of the
#: face-based estimate.
SEARCH_FACTOR = 0.9

#: The width of the band compared on each side of an edge, in pixels.
BAND_PX = 3

#: The smallest step between the two sides of an edge that counts as an
#: edge, on a 0-255 scale.
MIN_EDGE_CONTRAST = 16.0

#: How much of the step's own size a line has to show to count as showing
#: it at all. A quarter of the average step is low enough to keep the lines
#: where the two sides happen to be similar, and high enough to ignore the
#: lines where nothing happens.
COVERAGE_RATIO = 0.25

#: How much of a vertical edge has to show the step. The vertical edges are
#: looked for over the rows the face occupies, and a face is against a
#: changing background, so some of those rows show no step at all.
MIN_VERTICAL_COVERAGE = 0.55

#: How much of a horizontal edge has to show the step. The horizontal edges
#: are looked for over the whole width of the box, and a box edge shows the
#: step along all of it — a game menu's panel does not.
MIN_HORIZONTAL_COVERAGE = 0.85

#: How far from the face an edge may be, as a share of the face's size. The
#: edge of the webcam cannot be inside the face, so the search stops short
#: of it: the line where the face meets its own background is a strong step
#: too, and it is not the edge of the box.
EDGE_CLEARANCE = 0.05

#: The margins the face-based estimate uses, matching the region estimate in
#: :mod:`autoclip.pipeline.reframe.webcam`.
MARGIN_X = 0.60
MARGIN_TOP = 0.90
MARGIN_BOTTOM = 0.80

#: A box may not be smaller than the face inside it.
MIN_BOX_FACE_RATIO = 0.9

#: A box may not be wider than this multiple of the face.
MAX_BOX_FACE_RATIO = 4.0


@dataclass(frozen=True)
class BoxEstimate:
    """A webcam box, and how much of it was measured.

    ``edges_found`` says which edges were seen in the picture: left, top,
    right, bottom. The others were guessed from the face.
    """

    rect: Rect
    edges_found: tuple[bool, bool, bool, bool] = (False, False, False, False)

    @property
    def measured(self) -> int:
        """How many of the four edges came from the picture."""
        return sum(1 for found in self.edges_found if found)

    def to_dict(self) -> dict:
        return {
            "rect": self.rect.to_dict(),
            "edges_found": list(self.edges_found),
        }


def face_box_region(face: Rect) -> Rect:
    """The box the face alone suggests: the face plus headroom and shoulders.

    This is the fallback — the estimate used when the picture does not show
    where the webcam's own frame is.
    """
    width = max(1.0, face.width)
    height = max(1.0, face.height)
    return Rect(
        x=face.x - width * MARGIN_X,
        y=face.y - height * MARGIN_TOP,
        width=width * (1 + 2 * MARGIN_X),
        height=height * (1 + MARGIN_TOP + MARGIN_BOTTOM),
    )


def estimate_cam_box(
    frame,
    face: Rect,
    *,
    source_width: int,
    source_height: int,
) -> BoxEstimate | None:
    """Where the webcam's own frame is, in this frame.

    ``frame`` is a greyscale or colour image as a numpy array; ``face`` is the
    face box in the same pixel coordinates. Returns ``None`` when the frame
    cannot be read at all.

    Preconditions:
        frame is a 2-D array of at least BAND_PX * 2 in each direction.
    """
    import numpy as np

    array = np.asarray(frame)
    if array.ndim == 3:
        # A colour frame is averaged into grey. The steps that mark a box are
        # steps in brightness far more often than steps in hue.
        array = array.mean(axis=2)
    if array.ndim != 2 or array.shape[0] < BAND_PX * 2 or array.shape[1] < BAND_PX * 2:
        return None

    height, width = array.shape[:2]
    if source_width <= 0 or source_height <= 0:
        source_width, source_height = width, height

    fallback = face_box_region(face)
    left = _clamp(fallback.x, 0.0, source_width)
    top = _clamp(fallback.y, 0.0, source_height)
    right = _clamp(fallback.right, 0.0, source_width)
    bottom = _clamp(fallback.bottom, 0.0, source_height)

    reach_x = max(BAND_PX * 2, int(round(SEARCH_FACTOR * face.width)))
    reach_y = max(BAND_PX * 2, int(round(SEARCH_FACTOR * face.height)))
    clear_x = max(4, int(round(EDGE_CLEARANCE * face.width)))
    clear_y = max(4, int(round(EDGE_CLEARANCE * face.height)))

    # -- the vertical edges, over the rows the face occupies --------------
    face_rows = _span(
        array,
        axis=0,
        low=face.y - face.height * 0.25,
        high=face.bottom + face.height * 0.35,
    )

    found: list[bool] = [False, False, False, False]

    edge = _find_edge(
        array,
        axis=0,
        low=fallback.x - reach_x,
        high=face.x - clear_x,
        span=face_rows,
        min_coverage=MIN_VERTICAL_COVERAGE,
    )
    if edge is not None:
        left = _clamp(edge, 0.0, source_width)
        found[0] = True

    edge = _find_edge(
        array,
        axis=0,
        low=face.right + clear_x,
        high=fallback.right + reach_x,
        span=face_rows,
        min_coverage=MIN_VERTICAL_COVERAGE,
    )
    if edge is not None:
        right = _clamp(edge, 0.0, source_width)
        found[2] = True
    elif _runs_to_edge(array, axis=0, at=right, span=face_rows, limit=source_width):
        # No step, and the picture does not change between here and the edge
        # of the frame: the webcam runs off the side of the video.
        right = float(source_width)

    # -- the horizontal edges, over the columns the box occupies ----------
    box_columns = (int(round(left)), int(round(right)))
    if box_columns[1] - box_columns[0] < BAND_PX * 2:
        box_columns = (0, array.shape[1])

    edge = _find_edge(
        array,
        axis=1,
        low=fallback.y - reach_y,
        high=face.y - clear_y,
        span=box_columns,
        min_coverage=MIN_HORIZONTAL_COVERAGE,
    )
    if edge is not None:
        top = _clamp(edge, 0.0, source_height)
        found[1] = True

    edge = _find_edge(
        array,
        axis=1,
        low=face.bottom + clear_y,
        high=fallback.bottom + reach_y,
        span=box_columns,
        min_coverage=MIN_HORIZONTAL_COVERAGE,
    )
    if edge is not None:
        bottom = _clamp(edge, 0.0, source_height)
        found[3] = True
    elif _runs_to_edge(array, axis=1, at=bottom, span=box_columns, limit=source_height):
        bottom = float(source_height)

    rect = Rect(x=left, y=top, width=max(0.0, right - left), height=max(0.0, bottom - top))
    if not _plausible(rect, face):
        # The edges that were found do not make a box the face can be in.
        # The face-based estimate is kept instead: a box that is a little
        # too big is a much smaller fault than a box that is wrong.
        log.debug(
            "The detected webcam box %s does not fit the face %s; keeping the estimate.",
            rect.to_dict(),
            face.to_dict(),
        )
        fallback_rect = Rect(
            x=_clamp(fallback.x, 0.0, source_width),
            y=_clamp(fallback.y, 0.0, source_height),
            width=max(
                0.0,
                _clamp(fallback.right, 0.0, source_width) - _clamp(fallback.x, 0.0, source_width),
            ),
            height=max(
                0.0,
                _clamp(fallback.bottom, 0.0, source_height)
                - _clamp(fallback.y, 0.0, source_height),
            ),
        )
        if not _plausible(fallback_rect, face):
            return None
        return BoxEstimate(rect=fallback_rect, edges_found=(False, False, False, False))

    return BoxEstimate(rect=rect, edges_found=(found[0], found[1], found[2], found[3]))


def _span(array, *, axis: int, low: float, high: float) -> tuple[int, int]:
    """The rows or columns a step is measured over."""
    length = array.shape[axis]
    start = max(0, int(low))
    end = min(length, int(high))
    if end - start < BAND_PX * 2:
        start = 0
        end = length
    return start, end


def _find_edge(
    array,
    *,
    axis: int,
    low: float,
    high: float,
    span: tuple[int, int],
    min_coverage: float,
) -> float | None:
    """The strongest step between ``low`` and ``high``, or ``None``.

    ``axis`` is 0 for a vertical edge (a column position) and 1 for a
    horizontal one (a row position).

    The step is measured one line at a time: for a vertical edge, each row
    of the span is compared across the edge; for a horizontal edge, each
    column of the span is compared across it. The mean of those comparisons
    is how big the step is, and the share of them that show it is how much
    of the edge there is.
    """
    import numpy as np

    # The edge's position runs along the other axis: a vertical edge is
    # placed at a column, a horizontal one at a row.
    length = array.shape[1 - axis]
    start, end = span
    if end - start < BAND_PX * 2:
        return None

    first = max(BAND_PX, int(low))
    last = min(length - BAND_PX - 1, int(high))
    if last <= first:
        return None

    best_position: float | None = None
    best_score = 0.0

    for position in range(first, last + 1):
        if axis == 0:
            inside = array[start:end, position : position + BAND_PX]
            outside = array[start:end, position - BAND_PX : position]
            # One comparison per row of the span.
            steps = np.abs(inside.mean(axis=1) - outside.mean(axis=1))
        else:
            inside = array[position : position + BAND_PX, start:end]
            outside = array[position - BAND_PX : position, start:end]
            # One comparison per column of the span.
            steps = np.abs(inside.mean(axis=0) - outside.mean(axis=0))
        if steps.size == 0:
            continue

        contrast = float(steps.mean())
        if contrast < MIN_EDGE_CONTRAST:
            continue
        coverage = float((steps >= contrast * COVERAGE_RATIO).mean())
        if coverage < min_coverage:
            continue
        score = contrast * coverage
        if score > best_score:
            best_score = score
            best_position = float(position)

    return best_position


def _runs_to_edge(array, *, axis: int, at: float, span: tuple[int, int], limit: float) -> bool:
    """True when the picture continues unchanged from ``at`` to the edge.

    A webcam that runs off the side of the video has no step at its edge —
    the frame simply stops. The picture either changes on the way to the
    frame's edge or it does not.
    """
    import numpy as np

    start, end = span
    if end - start < BAND_PX * 2:
        return False

    first = int(at) + BAND_PX
    last = int(limit) - BAND_PX
    if last - first < BAND_PX:
        return False

    if axis == 0:
        inside = array[start:end, first : first + BAND_PX]
        outside = array[start:end, last : last + BAND_PX]
        steps = np.abs(inside.mean(axis=1) - outside.mean(axis=1))
    else:
        inside = array[first : first + BAND_PX, start:end]
        outside = array[last : last + BAND_PX, start:end]
        steps = np.abs(inside.mean(axis=0) - outside.mean(axis=0))

    if steps.size == 0:
        return False
    return float(steps.mean()) < MIN_EDGE_CONTRAST


def _plausible(rect: Rect, face: Rect) -> bool:
    """Is this box a sane thing to call a webcam?"""
    if rect.width <= 0 or rect.height <= 0:
        return False
    if rect.width < face.width * MIN_BOX_FACE_RATIO:
        return False
    if rect.height < face.height * MIN_BOX_FACE_RATIO:
        return False
    if rect.width > face.width * MAX_BOX_FACE_RATIO:
        return False
    if rect.height > face.height * MAX_BOX_FACE_RATIO:
        return False
    # The face has to be inside the box it is supposed to be in.
    if face.x < rect.x - 1 or face.right > rect.right + 1:
        return False
    return not (face.y < rect.y - 1 or face.bottom > rect.bottom + 1)


def _clamp(value: float, low: float, high: float) -> float:
    return max(low, min(value, high))
