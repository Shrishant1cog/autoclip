"""Reframe stage — 16:9 source to a 9:16 crop path that follows the speaker.

Pipeline for one clip:

1. Split into shots. Crop paths never interpolate across a cut.
2. Sample face landmarks across the clip.
3. Link observations into per-person tracks.
4. Map diarized speakers onto tracks once, then let turn boundaries drive framing.
5. Per shot, pick a strategy — TRACK, WIDE, or GENERAL.
6. Build a raw crop path, smooth it, and emit segments.

The quality bar is "never jarring": no visible jitter, no cut-off faces, the
speaker on screen for essentially all of their speaking time. Every default here
is biased toward stillness — a locked frame that is slightly off-centre beats a
frame that is always correct and always moving.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from pathlib import Path

from .. import ffmpeg
from ..transcript import Transcript
from .croppath import (
    CropKeyframe,
    CropPath,
    CropSegment,
    FaceRect,
    Strategy,
    centre_crop,
    target_crop_size,
)
from .faces import FaceDetectionUnavailable, FaceObservation, sample_faces
from .scenes import Shot, detect_shots
from .smoothing import SmoothingConfig, smooth_series
from .speaker import assign_speakers, map_tracks_to_speakers
from .tracker import FaceTrack, build_tracks
from .webcam import Rect

log = logging.getLogger(__name__)

__all__ = [
    "CropPath",
    "CropSegment",
    "ReframeConfig",
    "Strategy",
    "build_crop_path",
]

#: Where the eye line sits within the crop, as a fraction of crop height.
#: Portrait convention puts the eyes near the upper third; 0.38 reads as
#: composed without leaving the chin tight to the bottom edge.
EYE_LINE_RATIO = 0.38

#: A face wider than this fraction of the crop is already a close-up; don't
#: track it, lock the frame.
LOCK_IF_FACE_WIDER_THAN = 0.55

#: If detected faces span more than this fraction of the crop width, no crop can
#: hold them and we fall back to a fitted (blurred-background) frame.
FIT_IF_SPREAD_EXCEEDS = 0.95

#: Slow push-in applied to shots with no face at all, to stop a static wide from
#: feeling like a still image. Off by default — see the note in export._zoom_filter.
GENERAL_ZOOM = 0.0


@dataclass
class ReframeConfig:
    aspect_w: int = 9
    aspect_h: int = 16
    sample_fps: float = 5.0
    smoothing: SmoothingConfig | None = None
    #: Skip face detection entirely and centre-crop everything.
    centre_only: bool = False
    #: The webcam's own region, in source pixels. The gameplay crop is kept
    #: clear of it, so the webcam is never shown twice: once in the strip
    #: above the gameplay, and once inside the gameplay itself.
    avoid: Rect | None = None


def _safe_x_range(source_w: int, avoid: Rect | None) -> tuple[float, float] | None:
    """The stretch of the frame the gameplay crop may use.

    The crop is a tall window in a wide frame, so the only way to keep it
    clear of a webcam is to keep it to one side of it. The wider side is
    the one that is used.
    """
    if avoid is None or avoid.area <= 0:
        return None

    left = max(0.0, min(avoid.x, float(source_w)))
    right = max(left, min(avoid.right, float(source_w)))
    if right <= left:
        # The webcam covers the whole width; there is nowhere to go.
        return None

    left_width = left
    right_width = source_w - right
    if right_width >= left_width:
        return (right, float(source_w))
    return (0.0, left)


def _constrain_x(x: float, crop_w: int, source_w: int, avoid: Rect | None) -> float:
    """Keep the crop window clear of the webcam."""
    safe = _safe_x_range(source_w, avoid)
    if safe is None:
        return x
    low, high = safe
    if high - low < crop_w:
        # The clear side is narrower than the crop. The window is pushed as
        # far clear as it can go, and the overlap that is left is smaller
        # than the webcam is wide.
        return max(0.0, min(x, max(0.0, high - crop_w)))
    return max(low, min(x, high - crop_w))


def _safe_window(
    source_w: int,
    source_h: int,
    crop_w: int,
    crop_h: int,
    avoid: Rect | None,
) -> tuple[float, float, int, int] | None:
    """The largest window of the right shape that stays clear of the webcam.

    This is what the wide-shot fallback uses when a webcam is on screen:
    showing the whole frame would show the webcam twice.
    """
    safe = _safe_x_range(source_w, avoid)
    if safe is None:
        return None
    low, high = safe

    width = min(crop_w, int(high - low))
    height = crop_h
    if width < crop_w:
        # The clear side is too narrow for the full-height window, so the
        # window is shortened rather than widened into the webcam.
        height = _even(int(width * crop_h / crop_w))
        width = _even(int(height * crop_w / crop_h))
    if width <= 0 or height <= 0:
        return None
    x = max(low, min((low + high - width) / 2, high - width))
    return x, (source_h - height) / 2, width, height


def _even(value: float) -> int:
    number = int(value)
    if number % 2:
        number -= 1
    return max(2, number)


def plan_fingerprint(config: ReframeConfig) -> str:
    """A short description of the settings a crop plan was built for.

    A crop plan is not just a crop: it is a crop *for an aspect ratio* and
    *clear of a region*. Change either and the plan is a different plan, so
    a saved one may only be reused when the settings still match.
    """
    avoid = config.avoid
    if avoid is None or avoid.area <= 0:
        avoid_part = "none"
    else:
        avoid_part = f"{avoid.x:.1f},{avoid.y:.1f},{avoid.width:.1f},{avoid.height:.1f}"
    smoothing = repr(config.smoothing) if config.smoothing is not None else "none"
    return (
        f"aspect={config.aspect_w}x{config.aspect_h};"
        f"fps={config.sample_fps};"
        f"centre={config.centre_only};"
        f"avoid={avoid_part};"
        f"smoothing={smoothing}"
    )


def build_crop_path(
    video: Path,
    *,
    start_s: float,
    end_s: float,
    transcript: Transcript | None = None,
    config: ReframeConfig | None = None,
) -> CropPath:
    """Compute the crop path for one clip.

    The plan records the settings it was built for, so that a saved plan is
    only reused when those settings still hold.

    Falls back to a centred crop whenever face detection is unavailable or finds
    nothing — a centre crop is an acceptable result, an exception is not.

    Preconditions:
        video exists; 0 <= start_s < end_s <= source duration.
    """
    config = config or ReframeConfig()
    path = _build_crop_path(
        video,
        start_s=start_s,
        end_s=end_s,
        transcript=transcript,
        config=config,
    )
    path.config_fingerprint = plan_fingerprint(config)
    return path


def _build_crop_path(
    video: Path,
    *,
    start_s: float,
    end_s: float,
    transcript: Transcript | None = None,
    config: ReframeConfig | None = None,
) -> CropPath:
    """The plan itself, without the settings it was built for.

    Falls back to a centred crop whenever face detection is unavailable or finds
    nothing — a centre crop is an acceptable result, an exception is not.

    Preconditions:
        video exists; 0 <= start_s < end_s <= source duration.
    """
    config = config or ReframeConfig()
    duration = end_s - start_s

    info = ffmpeg.probe(video)
    if not info.has_video or not info.width or not info.height:
        raise ValueError(f"{video.name} has no video stream to reframe.")

    source_w, source_h = info.width, info.height
    crop_w, crop_h = target_crop_size(source_w, source_h, config.aspect_w, config.aspect_h)

    if config.centre_only:
        return _held_clear(
            centre_crop(
                source_w, source_h, duration, aspect_w=config.aspect_w, aspect_h=config.aspect_h
            ),
            config.avoid,
        )

    try:
        observations = sample_faces(
            video, start_s=start_s, end_s=end_s, sample_fps=config.sample_fps
        )
    except FaceDetectionUnavailable as exc:
        log.warning("Face detection unavailable (%s); using a centre crop.", exc)
        return _held_clear(
            centre_crop(
                source_w,
                source_h,
                duration,
                aspect_w=config.aspect_w,
                aspect_h=config.aspect_h,
                zoom=GENERAL_ZOOM,
            ),
            config.avoid,
        )

    if not observations:
        log.info("No faces detected in %s; using a centre crop.", video.name)
        return _held_clear(
            centre_crop(
                source_w,
                source_h,
                duration,
                aspect_w=config.aspect_w,
                aspect_h=config.aspect_h,
                zoom=GENERAL_ZOOM,
            ),
            config.avoid,
        )

    tracks = build_tracks(observations)
    shots = detect_shots(video, start_s=start_s, end_s=end_s)

    turns = _clip_relative_turns(transcript, start_s, end_s)
    speaker_map = map_tracks_to_speakers(tracks, turns) if turns else {}

    segments: list[CropSegment] = []
    for shot in shots:
        segments.extend(
            _segments_for_shot(
                shot,
                tracks=tracks,
                turns=turns,
                speaker_map=speaker_map,
                source_w=source_w,
                source_h=source_h,
                crop_w=crop_w,
                crop_h=crop_h,
                config=config,
            )
        )

    if not segments:
        return _held_clear(
            centre_crop(
                source_w, source_h, duration, aspect_w=config.aspect_w, aspect_h=config.aspect_h
            ),
            config.avoid,
        )

    # Guarantee the segments tile the clip exactly; a gap or overlap would
    # desync the concatenated render from the audio.
    segments[0].start_s = 0.0
    segments[-1].end_s = duration
    for index in range(len(segments) - 1):
        segments[index].end_s = segments[index + 1].start_s

    segments = [s for s in segments if s.duration_s > 0.01]

    log.info(
        "Reframed %s into %d segment(s): %s",
        video.name,
        len(segments),
        ", ".join(s.strategy.value for s in segments),
    )
    # The faces the plan was built around travel with the plan. They are the
    # only face rectangles that belong to this clip, in this clip's time base;
    # anything measured elsewhere cannot say whether *this* crop kept the face.
    faces = [_face_rect(o) for o in observations]
    path = CropPath(
        source_width=source_w,
        source_height=source_h,
        segments=segments,
        faces=faces,
    )
    _keep_clear(path, config.avoid)
    return path


def _held_clear(path: CropPath, avoid: Rect | None) -> CropPath:
    """The plan, with its windows held clear of the webcam."""
    _keep_clear(path, avoid)
    return path


def _keep_clear(path: CropPath, avoid: Rect | None) -> None:
    """Move the crop windows clear of the webcam.

    This is the last word on where the gameplay crop may sit: it is applied
    to the finished plan, so the fallbacks — the centre crop when no face
    was found, the whole frame when the shot is too wide — are held clear of
    the webcam as well. A webcam that is shown twice is a worse fault than
    a crop that is a little off centre.
    """
    if avoid is None or avoid.area <= 0:
        return

    source_w = path.source_width
    for segment in path.segments:
        if segment.fit:
            safe = _safe_x_range(source_w, avoid)
            if safe is None:
                continue
            low, high = safe
            width = _even(high - low)
            if width <= 0:
                continue
            segment.width = width
            segment.height = path.source_height
            for keyframe in segment.keyframes:
                keyframe.x = low
                keyframe.y = 0.0
            continue

        for keyframe in segment.keyframes:
            keyframe.x = _constrain_x(keyframe.x, segment.width, source_w, avoid)


def _clip_relative_turns(
    transcript: Transcript | None, start_s: float, end_s: float
) -> list[tuple[str, float, float]]:
    """Rebase diarization turns onto the clip's timeline, dropping non-overlapping ones."""
    if transcript is None or not transcript.has_diarization:
        return []

    turns: list[tuple[str, float, float]] = []
    for speaker, turn_start, turn_end in transcript.speaker_turns():
        overlap_start = max(turn_start, start_s)
        overlap_end = min(turn_end, end_s)
        if overlap_end > overlap_start:
            turns.append((speaker, overlap_start - start_s, overlap_end - start_s))
    return turns


def _segments_for_shot(
    shot: Shot,
    *,
    tracks: list[FaceTrack],
    turns: list[tuple[str, float, float]],
    speaker_map: dict[str, FaceTrack],
    source_w: int,
    source_h: int,
    crop_w: int,
    crop_h: int,
    config: ReframeConfig,
) -> list[CropSegment]:
    assignments = assign_speakers(
        tracks,
        shot_start_s=shot.start_s,
        shot_end_s=shot.end_s,
        turns=turns,
        speaker_map=speaker_map,
    )

    segments: list[CropSegment] = []
    for assignment in assignments:
        visible = [
            t for t in tracks if t.observations_between(assignment.start_s, assignment.end_s)
        ]

        if assignment.track is not None:
            segments.append(
                _track_segment(
                    assignment.track,
                    start_s=assignment.start_s,
                    end_s=assignment.end_s,
                    source_w=source_w,
                    source_h=source_h,
                    crop_w=crop_w,
                    crop_h=crop_h,
                    config=config,
                )
            )
        elif visible:
            segments.append(
                _wide_segment(
                    visible,
                    start_s=assignment.start_s,
                    end_s=assignment.end_s,
                    source_w=source_w,
                    source_h=source_h,
                    crop_w=crop_w,
                    crop_h=crop_h,
                    avoid=config.avoid,
                )
            )
        else:
            segments.append(
                _general_segment(
                    start_s=assignment.start_s,
                    end_s=assignment.end_s,
                    source_w=source_w,
                    source_h=source_h,
                    crop_w=crop_w,
                    crop_h=crop_h,
                    avoid=config.avoid,
                )
            )

    return segments


def _track_segment(
    track: FaceTrack,
    *,
    start_s: float,
    end_s: float,
    source_w: int,
    source_h: int,
    crop_w: int,
    crop_h: int,
    config: ReframeConfig,
) -> CropSegment:
    """Frame a single subject, tracking them or locking on if they barely move."""
    observations = track.observations_between(start_s, end_s)
    if not observations:
        return _general_segment(
            start_s=start_s,
            end_s=end_s,
            source_w=source_w,
            source_h=source_h,
            crop_w=crop_w,
            crop_h=crop_h,
            avoid=config.avoid,
        )

    raw = [
        (
            o.t,
            _constrain_x(
                _clamp(o.cx - crop_w / 2, 0, source_w - crop_w), crop_w, source_w, config.avoid
            ),
            _clamp(o.eye_y - EYE_LINE_RATIO * crop_h, 0, source_h - crop_h),
        )
        for o in observations
    ]

    mean_face_width = sum(o.width for o in observations) / len(observations)
    spread_x = max(x for _, x, _ in raw) - min(x for _, x, _ in raw)

    # A close-up, or a subject who barely moves, is better locked than tracked.
    should_lock = (
        mean_face_width > crop_w * LOCK_IF_FACE_WIDER_THAN
        or spread_x < (config.smoothing or SmoothingConfig()).dead_zone_px
    )

    if should_lock or len(raw) < 3:
        x = sum(item[1] for item in raw) / len(raw)
        y = sum(item[2] for item in raw) / len(raw)
        keyframes = [CropKeyframe(t=start_s, x=x, y=y)]
    else:
        smoothing = config.smoothing or SmoothingConfig()
        xs = smooth_series([(t, x) for t, x, _ in raw], smoothing)
        ys = smooth_series([(t, y) for t, _, y in raw], smoothing)
        keyframes = [CropKeyframe(t=t, x=x, y=y) for (t, x), (_, y) in zip(xs, ys, strict=True)]
        # Anchor the ends so the expression covers the whole segment.
        if keyframes[0].t > start_s:
            keyframes.insert(0, CropKeyframe(start_s, keyframes[0].x, keyframes[0].y))
        if keyframes[-1].t < end_s:
            keyframes.append(CropKeyframe(end_s, keyframes[-1].x, keyframes[-1].y))

    return CropSegment(
        start_s=start_s,
        end_s=end_s,
        width=crop_w,
        height=crop_h,
        keyframes=keyframes,
        strategy=Strategy.TRACK,
        # The face this crop follows. It travels with the plan so that
        # "did the crop keep the face it was built around?" can be answered
        # from the plan itself.
        faces=[_face_rect(o) for o in observations],
    )


def _wide_segment(
    visible: list[FaceTrack],
    *,
    start_s: float,
    end_s: float,
    source_w: int,
    source_h: int,
    crop_w: int,
    crop_h: int,
    avoid: Rect | None = None,
) -> CropSegment:
    """Hold several faces at once — locked, never panning.

    Panning between two people who are both on screen is the most obviously
    robotic thing an auto-reframer does. If they fit, lock on their centroid; if
    they don't, fit the whole frame rather than cutting someone out.
    """
    observations: list[FaceObservation] = [
        o for track in visible for o in track.observations_between(start_s, end_s)
    ]
    if not observations:
        return _general_segment(
            start_s=start_s,
            end_s=end_s,
            source_w=source_w,
            source_h=source_h,
            crop_w=crop_w,
            crop_h=crop_h,
        )

    left = min(o.left for o in observations)
    right = max(o.right for o in observations)
    spread = right - left

    if spread > crop_w * FIT_IF_SPREAD_EXCEEDS:
        window = _safe_window(source_w, source_h, crop_w, crop_h, avoid)
        if window is not None:
            # The whole frame would show the webcam twice — once in the
            # strip above the gameplay and once inside it — so the window is
            # the biggest clear piece of the right shape instead.
            x, y, width, height = window
            return CropSegment(
                start_s=start_s,
                end_s=end_s,
                width=width,
                height=height,
                keyframes=[CropKeyframe(t=start_s, x=x, y=y)],
                strategy=Strategy.WIDE,
                faces=[_face_rect(o) for o in observations],
            )
        return CropSegment(
            start_s=start_s,
            end_s=end_s,
            width=source_w,
            height=source_h,
            keyframes=[CropKeyframe(t=start_s, x=0.0, y=0.0)],
            strategy=Strategy.WIDE,
            fit=True,
            faces=[_face_rect(o) for o in observations],
        )

    centre_x = (left + right) / 2
    eye_y = sum(o.eye_y for o in observations) / len(observations)

    return CropSegment(
        start_s=start_s,
        end_s=end_s,
        width=crop_w,
        height=crop_h,
        keyframes=[
            CropKeyframe(
                t=start_s,
                x=_constrain_x(
                    _clamp(centre_x - crop_w / 2, 0, source_w - crop_w),
                    crop_w,
                    source_w,
                    avoid,
                ),
                y=_clamp(eye_y - EYE_LINE_RATIO * crop_h, 0, source_h - crop_h),
            )
        ],
        strategy=Strategy.WIDE,
        # A wide shot is meant to hold everyone it can. All of them are the
        # faces the plan was built around, and the crop has to keep them.
        faces=[_face_rect(o) for o in observations],
    )


def _general_segment(
    *,
    start_s: float,
    end_s: float,
    source_w: int,
    source_h: int,
    crop_w: int,
    crop_h: int,
    avoid: Rect | None = None,
) -> CropSegment:
    """No usable face — centre crop."""
    return CropSegment(
        start_s=start_s,
        end_s=end_s,
        width=crop_w,
        height=crop_h,
        keyframes=[
            CropKeyframe(
                t=start_s,
                x=_constrain_x((source_w - crop_w) / 2, crop_w, source_w, avoid),
                y=(source_h - crop_h) / 2,
            )
        ],
        strategy=Strategy.GENERAL,
        zoom=GENERAL_ZOOM,
    )


def _clamp(value: float, low: float, high: float) -> float:
    return max(low, min(value, high)) if high > low else max(0.0, low)


def _face_rect(observation: FaceObservation) -> FaceRect:
    """One face observation, in the plan's own coordinates."""
    return FaceRect(
        t=observation.t,
        x=observation.left,
        y=observation.top,
        width=observation.width,
        height=observation.height,
    )
