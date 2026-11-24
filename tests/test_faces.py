"""How the face sampler looks at a frame, and in what order.

Three faults on a real 1080p60 source each looked like *"there is no face in
this video"* rather than like a fault of their own:

* MediaPipe scales its input down to about **128 px** on the short side, so
  a face **120 px** wide in a **1920 px** frame is smaller than one pixel of
  what the detector looks at. The frame is now looked at tile by tile.
* A tile cut out of a frame is a **view**, not a copy, and MediaPipe read
  the view with the wrong strides — so every tiled frame came back empty,
  which looked exactly like "there is no face here".
* A decoder **cannot seek backwards**. The clips come in rank order, and
  rank is not position, so walking them as given asked the decoder to seek
  back and it refused: *"Input timestamp must be monotonically increasing"*.

The tests are about those three decisions. The tiles are chosen by geometry,
and the clock is chosen by a fake decoder that behaves like OpenCV's — the
real one is not needed to know that it refuses to go backwards.
"""

from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest
from autoclip.pipeline.reframe.faces import (
    DEDUP_IOU,
    FACE_TILE_PX,
    TILE_OVERLAP,
    _iter_frames,
    _tile_frame,
    _tile_positions,
    _tiles,
)

#: The fake decoder's property names. Real OpenCV uses numbers; the names
#: keep the fake readable and keep the two from drifting apart.
_CAPTURE_FPS = "fps"
_CAPTURE_WIDTH = "width"
_CAPTURE_HEIGHT = "height"
_CAPTURE_POS_FRAMES = "pos_frames"


class _FakeCapture:
    """A decoder that behaves like OpenCV's.

    The one behaviour that matters here is the refusal: asked to seek
    backwards, the real decoder raises *"Input timestamp must be
    monotonically increasing"* rather than replaying the frames.
    """

    def __init__(self, path: str) -> None:
        self.path = path
        self.frames = 10000
        self.fps = 10.0
        self.width = 1920
        self.height = 1080
        self.position = 0
        self.seeks: list[int] = []

    def isOpened(self) -> bool:
        return True

    def get(self, prop: str) -> float:
        if prop == _CAPTURE_FPS:
            return self.fps
        if prop == _CAPTURE_WIDTH:
            return self.width
        if prop == _CAPTURE_HEIGHT:
            return self.height
        return 0.0

    def set(self, prop: str, value: int) -> bool:
        if prop != _CAPTURE_POS_FRAMES:
            return True
        if value < self.position:
            raise RuntimeError("Input timestamp must be monotonically increasing.")
        self.position = value
        self.seeks.append(value)
        return True

    def read(self) -> tuple[bool, Any]:
        if self.position >= self.frames:
            return False, None
        frame = SimpleNamespace(index=self.position)
        self.position += 1
        return True, frame

    def release(self) -> None:
        return None


def _fake_cv2() -> SimpleNamespace:
    return SimpleNamespace(
        VideoCapture=_FakeCapture,
        cvtColor=lambda frame, code: frame,
        COLOR_BGR2RGB="bgr2rgb",
        CAP_PROP_FPS=_CAPTURE_FPS,
        CAP_PROP_FRAME_WIDTH=_CAPTURE_WIDTH,
        CAP_PROP_FRAME_HEIGHT=_CAPTURE_HEIGHT,
        CAP_PROP_POS_FRAMES=_CAPTURE_POS_FRAMES,
    )


def _timestamps(cv2: Any, **kwargs: Any) -> list[float]:
    return [timestamp for timestamp, *_ in _iter_frames(cv2, Path("source.mp4"), **kwargs)]


# --------------------------------------------------------------------------
# The tiles
# --------------------------------------------------------------------------


class TestTheTiles:
    def test_a_big_frame_is_looked_at_in_pieces(self) -> None:
        """One look at 1920x1080 finds nothing; six looks at 640 find plenty."""

        tiles = _tiles(1920, 1080, FACE_TILE_PX)

        assert tiles
        assert all(
            width <= FACE_TILE_PX and height <= FACE_TILE_PX for _, _, width, height in tiles
        )

    def test_the_tiles_cover_the_whole_frame(self) -> None:
        """A face on a seam must be inside some tile, or it is never seen."""

        width, height = 1920, 1080
        tiles = _tiles(width, height, FACE_TILE_PX)

        for x in range(0, width, 40):
            for y in range(0, height, 40):
                assert any(
                    tile_x <= x < tile_x + tile_w and tile_y <= y < tile_y + tile_h
                    for tile_x, tile_y, tile_w, tile_h in tiles
                ), f"({x}, {y}) is in no tile"

    def test_neighbouring_tiles_overlap(self) -> None:
        """A face on the seam between two tiles is then seen whole by one."""

        positions = _tile_positions(1920, FACE_TILE_PX)

        assert positions[1] - positions[0] < FACE_TILE_PX
        assert TILE_OVERLAP > 0

    def test_a_small_frame_is_not_tiled(self) -> None:
        """One look at a small frame is enough, and much cheaper."""

        assert _tiles(160, 120, FACE_TILE_PX) == []

    def test_a_tile_is_a_copy_and_not_a_view(self) -> None:
        """MediaPipe reads the buffer as it is, and a view has the wrong strides.

        A tile cut out of a frame is a view into it. Handed to the detector
        as it is, it is read with the strides of the whole frame and comes
        back empty — which looks exactly like a frame with no face in it.
        """
        import numpy as np

        frame = np.zeros((1080, 1920, 3), dtype=np.uint8)

        tile = _tile_frame(frame, (640, 0, 640, 640))

        assert tile.flags["C_CONTIGUOUS"] is True
        assert tile.shape == (640, 640, 3)

    def test_two_sights_of_one_face_are_one_face(self) -> None:
        """The whole frame and a tile both see a large face; it is still one."""

        from autoclip.pipeline.reframe.faces import FaceObservation, _already_seen

        first = FaceObservation(
            t=1.0, cx=100.0, cy=100.0, width=80.0, height=80.0, eye_y=80.0, mar=0.2
        )
        second = FaceObservation(
            t=1.0, cx=104.0, cy=102.0, width=80.0, height=80.0, eye_y=82.0, mar=0.2
        )

        assert first.iou(second) >= DEDUP_IOU
        assert _already_seen([first], second) is True


# --------------------------------------------------------------------------
# The clock
# --------------------------------------------------------------------------


class TestTheClock:
    def test_the_windows_are_walked_in_the_order_they_sit_in_the_source(self) -> None:
        """The clips come in rank order, and rank is not position.

        A decoder cannot seek backwards: asked to, it refuses with *"Input
        timestamp must be monotonically increasing"*. The windows are
        therefore walked in the order they sit in the source, whatever order
        they were given in.
        """
        cv2 = _fake_cv2()

        stamps = _timestamps(
            cv2,
            start_s=0.0,
            end_s=None,
            sample_fps=1.0,
            windows=[(30.0, 32.0), (10.0, 12.0)],
        )

        assert stamps == sorted(stamps)
        assert stamps == pytest.approx([10.0, 11.0, 30.0, 31.0])

    def test_the_times_are_the_sources_own(self) -> None:
        """A window's times are the source's, not the clip's."""

        cv2 = _fake_cv2()

        stamps = _timestamps(
            cv2,
            start_s=0.0,
            end_s=None,
            sample_fps=1.0,
            windows=[(530.31, 532.0)],
        )

        assert stamps[0] == pytest.approx(530.3, abs=0.2)

    def test_a_clip_that_starts_part_way_into_the_source_starts_at_zero(self) -> None:
        """A frame index is a whole number, so the first frame can sit a
        fraction of a frame before the clip's own start. Its time is never
        negative: the detector's timeline and the crop path both expect time
        to start at zero.
        """
        cv2 = _fake_cv2()

        stamps = _timestamps(cv2, start_s=10.55, end_s=12.0, sample_fps=1.0)

        assert stamps
        assert stamps[0] == pytest.approx(0.0)
        assert all(stamp >= 0.0 for stamp in stamps)

    def test_the_times_only_ever_go_forwards(self) -> None:
        cv2 = _fake_cv2()

        stamps = _timestamps(
            cv2,
            start_s=0.0,
            end_s=None,
            sample_fps=2.0,
            windows=[(5.0, 8.0), (1.0, 3.0), (20.0, 22.0)],
        )

        assert stamps == sorted(stamps)
