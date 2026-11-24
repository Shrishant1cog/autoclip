"""Face observation via MediaPipe's FaceLandmarker.

Landmarks rather than plain detection boxes, for two reasons: eye positions give
the headroom rule something real to anchor to, and lip landmarks give a
mouth-aspect ratio whose variance over time is the cheapest usable
active-speaker signal.

MediaPipe 1.0 removed the legacy ``mp.solutions`` API, so this uses the Tasks
API with a downloaded model bundle.
"""

from __future__ import annotations

import logging
from collections.abc import Callable, Iterator
from dataclasses import dataclass
from pathlib import Path
from typing import Any

log = logging.getLogger(__name__)

#: Frames per second to sample. Faces don't move fast enough to justify more,
#: and the crop path is smoothed anyway — this is the main cost lever in the
#: whole reframe stage.
DEFAULT_SAMPLE_FPS = 5.0

#: Maximum simultaneous faces. Beyond four, framing decisions stop being
#: meaningful and we fall back to a wide shot regardless.
MAX_FACES = 4

#: The size of the tiles the detector looks at, in pixels.
#:
#: MediaPipe scales its input down to about 128 pixels on the short side
#: before it looks for anything. A face 120 pixels wide in a 1920-pixel frame
#: is therefore eight pixels tall by the time the detector sees it, and it is
#: missed — which is exactly the size of a streamer in a webcam overlay, the
#: one face the reframe most needs to find. A tile is small enough that the
#: same face arrives twenty-four pixels tall, which it is not.
#:
#: Zero disables tiling: one look at the whole frame, which is cheaper and
#: enough when the faces in the video are large.
FACE_TILE_PX = 640

#: How much neighbouring tiles overlap, as a share of a tile's size. A face
#: on the seam between two tiles is then seen whole by at least one of them.
TILE_OVERLAP = 0.15

#: Two observations of the same face are the same face when their boxes
#: overlap by at least this much.
DEDUP_IOU = 0.3

# Canonical FaceMesh landmark indices.
_UPPER_INNER_LIP = 13
_LOWER_INNER_LIP = 14
_LEFT_MOUTH_CORNER = 61
_RIGHT_MOUTH_CORNER = 291
_EYE_LANDMARKS = (33, 133, 362, 263)


@dataclass
class FaceObservation:
    """One face seen at one moment, in source-pixel coordinates."""

    t: float
    cx: float
    cy: float
    width: float
    height: float
    #: Vertical position of the eye line — what the headroom rule aligns.
    eye_y: float
    #: Mouth aspect ratio: opening height over mouth width.
    mar: float

    @property
    def area(self) -> float:
        return self.width * self.height

    @property
    def left(self) -> float:
        return self.cx - self.width / 2

    @property
    def right(self) -> float:
        return self.cx + self.width / 2

    @property
    def top(self) -> float:
        return self.cy - self.height / 2

    @property
    def bottom(self) -> float:
        return self.cy + self.height / 2

    def iou(self, other: FaceObservation) -> float:
        overlap_w = max(0.0, min(self.right, other.right) - max(self.left, other.left))
        overlap_h = max(0.0, min(self.bottom, other.bottom) - max(self.top, other.top))
        intersection = overlap_w * overlap_h
        if intersection <= 0:
            return 0.0
        union = self.area + other.area - intersection
        return intersection / union if union else 0.0


class FaceDetectionUnavailable(RuntimeError):
    """Face detection could not run; the caller should fall back to a centre crop."""


def sample_faces(
    video: Path,
    *,
    start_s: float = 0.0,
    end_s: float | None = None,
    sample_fps: float = DEFAULT_SAMPLE_FPS,
    max_faces: int = MAX_FACES,
    tile_px: int = 0,
    frame_sink: Callable[[float, Any, list[FaceObservation]], None] | None = None,
    windows: list[tuple[float, float]] | None = None,
) -> list[FaceObservation]:
    """Sample the video and return every face observed, in clip-relative time.

    With ``tile_px`` above zero the frame is also searched tile by tile, so
    that a face too small for the detector to find in the whole picture is
    still found. The tiles' faces are mapped back into the frame's own
    coordinates, and a face seen twice is kept once.

    ``frame_sink`` is called once for every sampled picture with the time,
    the picture and the faces found in it. It is how the webcam's own frame
    is measured without decoding the video a second time.

    ``windows`` samples only the stretches given, in the source's own clock.
    The times returned are then the source's times, not the clip's, so a
    caller can lay several stretches of one source side by side. This is how
    the detector is kept off the parts of a long source no clip uses.

    Preconditions:
        video exists and has a video stream.
    """
    try:
        import cv2
        import mediapipe as mp
        from mediapipe.tasks.python import BaseOptions
        from mediapipe.tasks.python.vision import (
            FaceLandmarker,
            FaceLandmarkerOptions,
            RunningMode,
        )
    except ImportError as exc:
        raise FaceDetectionUnavailable(f"MediaPipe or OpenCV is unavailable: {exc}") from exc

    from ... import models

    model_file = models.ensure("face_landmarker")

    def _options() -> Any:
        return FaceLandmarkerOptions(
            base_options=BaseOptions(model_asset_path=str(model_file)),
            running_mode=RunningMode.VIDEO,
            num_faces=max_faces,
            min_face_detection_confidence=0.4,
            min_tracking_confidence=0.4,
        )

    observations: list[FaceObservation] = []
    tiles: list[tuple[int, int, int, int]] = []

    with FaceLandmarker.create_from_options(_options()) as landmarker:
        tile_landmarkers: list[Any] = []
        for timestamp, frame, width, height in _iter_frames(
            cv2, video, start_s, end_s, sample_fps, windows=windows
        ):
            if not tiles:
                tiles = _tiles(width, height, tile_px)
                tile_landmarkers = [FaceLandmarker.create_from_options(_options()) for _ in tiles]

            image = mp.Image(image_format=mp.ImageFormat.SRGB, data=frame)
            # VIDEO mode demands monotonically increasing integer milliseconds.
            result = landmarker.detect_for_video(image, int(timestamp * 1000))

            found: list[FaceObservation] = []
            for landmarks in result.face_landmarks or []:
                observation = _to_observation(landmarks, timestamp, width, height)
                if observation is not None:
                    found.append(observation)
                    observations.append(observation)

            # The tiles get their own detectors, each with its own timeline:
            # a landmarker tracks one picture, and a tile is a different
            # picture from the frame it was cut out of.
            for index, (tile_x, tile_y, tile_w, tile_h) in enumerate(tiles):
                tile_frame = _tile_frame(frame, (tile_x, tile_y, tile_w, tile_h))
                if tile_frame.size == 0:
                    continue
                tile_image = mp.Image(image_format=mp.ImageFormat.SRGB, data=tile_frame)
                tile_result = tile_landmarkers[index].detect_for_video(
                    tile_image, int(timestamp * 1000)
                )
                for landmarks in tile_result.face_landmarks or []:
                    observation = _to_observation(
                        landmarks,
                        timestamp,
                        tile_w,
                        tile_h,
                        offset_x=tile_x,
                        offset_y=tile_y,
                    )
                    if observation is not None and not _already_seen(observations, observation):
                        observations.append(observation)
                        found.append(observation)

            if frame_sink is not None:
                frame_sink(timestamp, frame, found)

        for tile_landmarker in tile_landmarkers:
            tile_landmarker.close()

    log.info("Sampled %d face observations from %s.", len(observations), video.name)
    return observations


def _tiles(width: int, height: int, tile_px: int) -> list[tuple[int, int, int, int]]:
    """The tiles that cover the frame, each at most ``tile_px`` square."""
    if tile_px <= 0:
        return []

    positions_x = _tile_positions(width, tile_px)
    positions_y = _tile_positions(height, tile_px)
    if len(positions_x) == 1 and len(positions_y) == 1:
        return []

    tiles: list[tuple[int, int, int, int]] = []
    for y in positions_y:
        for x in positions_x:
            tiles.append((x, y, min(tile_px, width - x), min(tile_px, height - y)))
    return tiles


def _tile_positions(length: int, tile_px: int) -> list[int]:
    """Where the tiles start, so that they cover the frame and overlap."""
    if length <= tile_px:
        return [0]

    step = max(1, int(tile_px * (1 - TILE_OVERLAP)))
    positions = list(range(0, length - tile_px + 1, step))
    last = length - tile_px
    if positions[-1] != last:
        positions.append(last)
    return positions


def _tile_frame(frame: Any, tile: tuple[int, int, int, int]) -> Any:
    """One tile of the frame, as a copy.

    MediaPipe reads the buffer it is given as it is. A tile cut out of a
    frame is a *view* into it — and therefore not contiguous — so the
    detector reads it with the wrong strides and finds nothing in it. The
    copy is what makes the tile readable.
    """
    import numpy as np

    tile_x, tile_y, tile_w, tile_h = tile
    return np.ascontiguousarray(frame[tile_y : tile_y + tile_h, tile_x : tile_x + tile_w])


def _already_seen(observations: list[FaceObservation], candidate: FaceObservation) -> bool:
    """True when this face has already been seen in this frame.

    The whole frame and the tiles both see the same face when it is large
    enough for the whole frame. Keeping both would put two boxes on one
    face, and the tracker would read that as two people.
    """
    for observation in observations:
        if abs(observation.t - candidate.t) > 0.001:
            continue
        if observation.iou(candidate) >= DEDUP_IOU:
            return True
    return False


def _iter_frames(
    cv2,
    video: Path,
    start_s: float,
    end_s: float | None,
    sample_fps: float,
    *,
    windows: list[tuple[float, float]] | None = None,
) -> Iterator[tuple[float, Any, int, int]]:
    """Yield ``(clip_relative_t, rgb_frame, width, height)`` at the sample rate.

    With ``windows`` the frames come from each window in turn and the times
    are the source's own clock, so several stretches of one source can be
    sampled side by side without their clocks overlapping.
    """
    capture = cv2.VideoCapture(str(video))
    if not capture.isOpened():
        raise FaceDetectionUnavailable(f"OpenCV could not open {video}.")

    try:
        source_fps = capture.get(cv2.CAP_PROP_FPS) or 30.0
        width = int(capture.get(cv2.CAP_PROP_FRAME_WIDTH))
        height = int(capture.get(cv2.CAP_PROP_FRAME_HEIGHT))
        if width <= 0 or height <= 0:
            raise FaceDetectionUnavailable(f"{video} reports no frame dimensions.")

        step = max(1, round(source_fps / sample_fps))

        if windows is None:
            spans = [(start_s, end_s)]
            # The times are measured from the start of the clip.
            base = start_s
        else:
            # The windows are walked in the order they sit in the source,
            # whatever order they were given in. A decoder cannot seek
            # backwards: asked to, it refuses with "Input timestamp must be
            # monotonically increasing", and MediaPipe refuses a picture
            # whose timestamp goes backwards too. The clips come in rank
            # order, and rank is not position.
            spans = sorted(windows)
            # The windows are given in the source's own clock, and so are the
            # times that come out of them.
            base = 0.0

        for span_start, span_end in spans:
            start_frame = int(span_start * source_fps)
            end_frame = int(span_end * source_fps) if span_end is not None else None

            capture.set(cv2.CAP_PROP_POS_FRAMES, start_frame)
            frame_index = start_frame
            # Timestamps come from the frame index rather than CAP_PROP_POS_MSEC,
            # which drifts on variable-frame-rate sources.
            while True:
                ok, frame = capture.read()
                if not ok:
                    break
                if end_frame is not None and frame_index >= end_frame:
                    break

                if (frame_index - start_frame) % step == 0:
                    # The first frame of a window can sit a fraction of a
                    # frame before the window's own start, because a frame
                    # index is a whole number. The time is never negative:
                    # the detector's timeline and the crop path both expect
                    # time to start at zero.
                    timestamp = max(0.0, (frame_index / source_fps) - base)
                    yield timestamp, cv2.cvtColor(frame, cv2.COLOR_BGR2RGB), width, height

                frame_index += 1
    finally:
        capture.release()


def _to_observation(
    landmarks,
    timestamp: float,
    width: int,
    height: int,
    *,
    offset_x: float = 0.0,
    offset_y: float = 0.0,
) -> FaceObservation | None:
    """Convert normalised landmarks into a pixel-space observation.

    ``offset_x`` and ``offset_y`` place the observation in the frame the
    landmarks were cut out of, so a face found in a tile is reported in the
    frame's own coordinates.
    """
    if not landmarks:
        return None

    xs = [lm.x * width + offset_x for lm in landmarks]
    ys = [lm.y * height + offset_y for lm in landmarks]
    if not xs or not ys:
        return None

    min_x, max_x = min(xs), max(xs)
    min_y, max_y = min(ys), max(ys)
    face_width = max_x - min_x
    face_height = max_y - min_y
    if face_width <= 1 or face_height <= 1:
        return None

    eye_y = sum(ys[i] for i in _EYE_LANDMARKS) / len(_EYE_LANDMARKS)

    return FaceObservation(
        t=timestamp,
        cx=(min_x + max_x) / 2,
        cy=(min_y + max_y) / 2,
        width=face_width,
        height=face_height,
        eye_y=eye_y,
        mar=_mouth_aspect_ratio(xs, ys),
    )


def _mouth_aspect_ratio(xs: list[float], ys: list[float]) -> float:
    """Mouth opening height divided by mouth width.

    Normalising by mouth width makes the value comparable between a face close
    to camera and one further away, which matters when comparing two people in
    the same frame.
    """
    try:
        opening = abs(ys[_LOWER_INNER_LIP] - ys[_UPPER_INNER_LIP])
        mouth_width = abs(xs[_RIGHT_MOUTH_CORNER] - xs[_LEFT_MOUTH_CORNER])
    except IndexError:
        return 0.0
    return opening / mouth_width if mouth_width > 1 else 0.0
