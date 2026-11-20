"""Webcam region detection and tracking.

The tests are about the decisions, not the pixels: a region that holds still
while the gameplay cuts is an overlay, a region that jumps at every cut is a
person in the scene, and a detector that finds nothing says so instead of
raising.
"""

from __future__ import annotations

from pathlib import Path

import pytest
from autoclip.pipeline.reframe import webcam as webcam_module
from autoclip.pipeline.reframe.faces import FaceObservation
from autoclip.pipeline.reframe.scenes import Shot
from autoclip.pipeline.reframe.webcam import (
    BASE_SAMPLE_FPS,
    MAX_SAMPLE_FPS,
    MIN_CONFIDENCE,
    MIN_SAMPLE_FPS,
    MIN_SAMPLES_PER_SHOT,
    Rect,
    WebcamCandidate,
    adaptive_sample_fps,
    detect_webcam,
    estimate_webcam_rect,
    track_webcam,
)

WIDTH = 1920
HEIGHT = 1080


def _face(
    t: float,
    cx: float = 1600.0,
    cy: float = 200.0,
    width: float = 120.0,
    height: float = 160.0,
) -> FaceObservation:
    return FaceObservation(
        t=t,
        cx=cx,
        cy=cy,
        width=width,
        height=height,
        eye_y=cy - height * 0.2,
        mar=0.2,
    )


def _shots(count: int, each_s: float = 2.0) -> list[Shot]:
    return [Shot(i * each_s, (i + 1) * each_s) for i in range(count)]


# --------------------------------------------------------------------------
# Adaptive sampling
# --------------------------------------------------------------------------


class TestAdaptiveSampleFps:
    def test_calm_footage_uses_the_base_rate(self) -> None:
        fps, reason = adaptive_sample_fps(_shots(3, each_s=10.0), 30.0)

        assert fps == pytest.approx(BASE_SAMPLE_FPS)
        assert "calm" in reason

    def test_fast_cut_footage_is_sampled_harder(self) -> None:
        fps, reason = adaptive_sample_fps(_shots(60, each_s=0.5), 30.0)

        assert fps > BASE_SAMPLE_FPS
        assert "fast-cut" in reason

    def test_every_shot_is_seen_at_least_twice(self) -> None:
        """One look at a shot is not enough to make a decision about it."""
        shots = _shots(40, each_s=0.5)
        duration = 20.0

        fps, _ = adaptive_sample_fps(shots, duration)

        assert fps * duration >= len(shots) * MIN_SAMPLES_PER_SHOT

    def test_the_rate_is_bounded(self) -> None:
        fast, _ = adaptive_sample_fps(_shots(600, each_s=0.05), 30.0)
        slow, _ = adaptive_sample_fps(_shots(1, each_s=600.0), 600.0)

        assert MIN_SAMPLE_FPS <= fast <= MAX_SAMPLE_FPS
        assert MIN_SAMPLE_FPS <= slow <= MAX_SAMPLE_FPS

    def test_the_reason_is_always_given(self) -> None:
        """The choice belongs in the run record, not in a silent constant."""
        _, reason = adaptive_sample_fps(_shots(3, each_s=10.0), 30.0)

        assert reason


# --------------------------------------------------------------------------
# The region around a face
# --------------------------------------------------------------------------


class TestEstimateWebcamRect:
    def test_the_region_is_wider_than_the_face(self) -> None:
        cluster = [_face(t, cx=500.0, cy=300.0) for t in range(10)]

        rect = estimate_webcam_rect(cluster, width=WIDTH, height=HEIGHT)

        assert rect is not None
        assert rect.width > 120.0
        assert rect.height > 160.0

    def test_the_region_is_clamped_to_the_frame(self) -> None:
        """A face in the corner must not produce a region outside the frame."""
        cluster = [_face(t, cx=1900.0, cy=30.0) for t in range(10)]

        rect = estimate_webcam_rect(cluster, width=WIDTH, height=HEIGHT)

        assert rect is not None
        assert rect.x >= 0
        assert rect.y >= 0
        assert rect.right <= WIDTH
        assert rect.bottom <= HEIGHT

    def test_one_bad_detection_cannot_drag_the_region(self) -> None:
        """The median is used, so a single stray detection is ignored."""
        cluster = [_face(t, cx=500.0, cy=300.0) for t in range(10)]
        cluster.append(_face(10.0, cx=1500.0, cy=900.0))

        rect = estimate_webcam_rect(cluster, width=WIDTH, height=HEIGHT)

        assert rect is not None
        assert rect.cx < 700.0

    def test_a_region_that_is_too_small_is_rejected(self) -> None:
        cluster = [_face(t, cx=500.0, cy=300.0, width=6.0, height=6.0) for t in range(10)]

        assert estimate_webcam_rect(cluster, width=WIDTH, height=HEIGHT) is None

    def test_no_faces_means_no_region(self) -> None:
        assert estimate_webcam_rect([], width=WIDTH, height=HEIGHT) is None


# --------------------------------------------------------------------------
# Scoring
# --------------------------------------------------------------------------


class TestCandidates:
    def test_an_overlay_beats_a_face_in_the_scene(self) -> None:
        """The decisive difference: an overlay does not move when the shot cuts."""
        shots = _shots(4, each_s=2.0)

        # The overlay: same place before and after every cut.
        overlay = [_face(t / 5.0, cx=1600.0, cy=200.0) for t in range(40)]
        # The scene face: jumps to the other side at every cut.
        scene: list[FaceObservation] = []
        for index, shot in enumerate(shots):
            side = 400.0 if index % 2 == 0 else 1400.0
            scene.extend(_face(shot.start_s + step * 0.2, cx=side, cy=500.0) for step in range(10))

        candidates = webcam_module._candidates(
            overlay + scene,
            shots=shots,
            width=WIDTH,
            height=HEIGHT,
            duration_s=8.0,
            sample_fps=5.0,
        )

        assert candidates
        assert candidates[0].cut_stability > 0.5
        # The best candidate is the overlay, not the face that moves.
        assert candidates[0].rect.cx > 1200.0

    def test_a_single_glimpse_is_not_a_region(self) -> None:
        shots = _shots(2, each_s=5.0)

        candidates = webcam_module._candidates(
            [_face(1.0)],
            shots=shots,
            width=WIDTH,
            height=HEIGHT,
            duration_s=10.0,
            sample_fps=5.0,
        )

        assert candidates == []

    def test_candidates_are_best_first(self) -> None:
        shots = _shots(4, each_s=2.0)
        overlay = [_face(t / 5.0, cx=1600.0, cy=200.0) for t in range(40)]

        candidates = webcam_module._candidates(
            overlay,
            shots=shots,
            width=WIDTH,
            height=HEIGHT,
            duration_s=8.0,
            sample_fps=5.0,
        )

        scores = [candidate.confidence for candidate in candidates]
        assert scores == sorted(scores, reverse=True)


# --------------------------------------------------------------------------
# Tracking
# --------------------------------------------------------------------------


def _candidate(rect: Rect, confidence: float = 0.8) -> WebcamCandidate:
    return WebcamCandidate(
        rect=rect,
        confidence=confidence,
        support=0.9,
        stability=0.9,
        cut_stability=0.9,
        persistence=1.0,
        observations=40,
    )


class TestTrackWebcam:
    def test_the_spans_cover_the_clip(self) -> None:
        shots = _shots(3, each_s=2.0)
        rect = Rect(x=1500.0, y=50.0, width=300.0, height=300.0)
        observations = [_face(t / 5.0, cx=1650.0, cy=200.0) for t in range(30)]

        track = track_webcam(
            _candidate(rect),
            observations=observations,
            shots=shots,
            width=WIDTH,
            height=HEIGHT,
        )

        assert track.spans[0].start_s == pytest.approx(0.0)
        assert track.spans[-1].end_s == pytest.approx(6.0)
        assert all(span.present for span in track.spans)
        assert track.uncertain is False

    def test_a_shot_without_a_face_is_marked(self) -> None:
        """'We could not see the webcam here' is not 'there was no webcam'."""
        shots = _shots(2, each_s=2.0)
        rect = Rect(x=1500.0, y=50.0, width=300.0, height=300.0)
        # The face is only in the first shot.
        observations = [
            _face(shot.start_s + step * 0.2, cx=1650.0, cy=200.0)
            for shot in shots[:1]
            for step in range(10)
        ]

        track = track_webcam(
            _candidate(rect),
            observations=observations,
            shots=shots,
            width=WIDTH,
            height=HEIGHT,
        )

        assert track.spans[0].present is True
        assert track.spans[1].present is False
        assert track.spans[1].reason
        assert track.uncertain is True
        assert track.reason

    def test_confidence_falls_when_the_face_is_missing(self) -> None:
        shots = _shots(2, each_s=2.0)
        rect = Rect(x=1500.0, y=50.0, width=300.0, height=300.0)
        observations = [_face(step * 0.2, cx=1650.0, cy=200.0) for step in range(10)]

        track = track_webcam(
            _candidate(rect, confidence=0.9),
            observations=observations,
            shots=shots,
            width=WIDTH,
            height=HEIGHT,
        )

        assert track.confidence < 0.9

    def test_a_face_outside_the_region_does_not_count(self) -> None:
        shots = _shots(1, each_s=4.0)
        rect = Rect(x=1500.0, y=50.0, width=300.0, height=300.0)
        observations = [_face(step * 0.2, cx=300.0, cy=500.0) for step in range(20)]

        track = track_webcam(
            _candidate(rect),
            observations=observations,
            shots=shots,
            width=WIDTH,
            height=HEIGHT,
        )

        assert track.spans[0].present is False


# --------------------------------------------------------------------------
# Slicing a track for one clip
# --------------------------------------------------------------------------


class TestSlicingATrack:
    def _track(self) -> object:
        shots = _shots(3, each_s=2.0)
        rect = Rect(x=1500.0, y=50.0, width=300.0, height=300.0)
        observations = [_face(t / 5.0, cx=1650.0, cy=200.0) for t in range(30)]
        return track_webcam(
            _candidate(rect),
            observations=observations,
            shots=shots,
            width=WIDTH,
            height=HEIGHT,
        )

    def test_the_spans_are_measured_from_the_clip(self) -> None:
        """A clip's clock starts at the clip, not at the source."""
        track = self._track()

        sliced = track.slice(2.0, 4.0)

        assert sliced.start_s == pytest.approx(0.0)
        assert sliced.end_s == pytest.approx(2.0)
        assert sliced.spans[0].start_s == pytest.approx(0.0)
        assert sliced.spans[-1].end_s == pytest.approx(2.0)

    def test_the_region_does_not_move(self) -> None:
        """An overlay stays where it is, so the region is carried over."""
        track = self._track()

        sliced = track.slice(2.0, 4.0)

        assert sliced.rect == track.rect

    def test_a_clip_outside_the_track_has_no_spans(self) -> None:
        track = self._track()

        sliced = track.slice(30.0, 40.0)

        assert sliced.spans == []
        assert sliced.uncertain is False

    def test_a_clip_that_missed_the_webcam_says_so(self) -> None:
        """'We could not see the webcam here' survives the slice."""
        shots = _shots(2, each_s=2.0)
        rect = Rect(x=1500.0, y=50.0, width=300.0, height=300.0)
        observations = [
            _face(shot.start_s + step * 0.2, cx=1650.0, cy=200.0)
            for shot in shots[:1]
            for step in range(10)
        ]
        track = track_webcam(
            _candidate(rect),
            observations=observations,
            shots=shots,
            width=WIDTH,
            height=HEIGHT,
        )

        sliced = track.slice(2.0, 4.0)

        assert sliced.spans[0].present is False
        assert sliced.uncertain is True
        assert sliced.reason


# --------------------------------------------------------------------------
# The report
# --------------------------------------------------------------------------


class TestDetectWebcam:
    def test_a_clip_with_no_duration_is_a_report_not_a_crash(self) -> None:
        report = detect_webcam(Path("x.mp4"), end_s=0.0)

        assert report.found is False
        assert report.unavailable_reason

    def test_an_unknown_frame_size_is_a_report_not_a_crash(self) -> None:
        report = detect_webcam(Path("x.mp4"), end_s=10.0, width=0, height=0)

        assert report.found is False
        assert report.unavailable_reason
        assert report.to_dict()["found"] is False

    def test_the_report_says_how_it_sampled(self) -> None:
        report = detect_webcam(Path("x.mp4"), end_s=10.0, width=0, height=0)

        assert report.sample_fps > 0
        assert report.sampling_reason

    def test_a_whole_video_is_detected_without_a_time_range(self) -> None:
        """``detect_webcam(path)`` works on its own.

        The duration is measured rather than assumed. Without this the
        detector reported "the clip has no duration" for every whole video,
        and the settings page could never look at one.
        """
        import subprocess

        from autoclip.pipeline import ffmpeg

        path = Path(__file__).with_name("_tmp_probe_video.mp4")
        subprocess.run(
            [
                ffmpeg.ffmpeg_path(),
                "-hide_banner",
                "-loglevel",
                "error",
                "-y",
                "-f",
                "lavfi",
                "-i",
                "testsrc2=size=160x120:rate=10:duration=2",
                "-c:v",
                "libx264",
                "-pix_fmt",
                "yuv420p",
                str(path),
            ],
            check=True,
            capture_output=True,
        )
        try:
            report = detect_webcam(path)
        finally:
            path.unlink(missing_ok=True)

        # The length was measured, so the detector got as far as looking.
        assert report.unavailable_reason != "the clip has no duration"
        assert report.source_width == 160
        assert report.source_height == 120
        assert report.sample_fps > 0

    def test_the_threshold_is_not_a_magic_number(self) -> None:
        """The confidence floor is a named constant, not a literal in the code."""
        assert 0.0 < MIN_CONFIDENCE < 1.0
