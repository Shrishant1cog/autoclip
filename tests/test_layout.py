"""The vertical streamer layout.

These tests are about the decisions a viewer would notice:

* the webcam takes about forty per cent and the gameplay about sixty;
* a webcam that cannot be shown without turning into a blur gets a corner
  instead, or is left out;
* the gameplay is never cropped through the webcam;
* what the user chose beats every automatic decision;
* the layout does not flap, but it is also not capped by a magic number;
* speech makes the webcam bigger and never makes the clip longer.
"""

from __future__ import annotations

from pathlib import Path

import pytest
from autoclip.pipeline import captions, export
from autoclip.pipeline.reframe.croppath import centre_crop
from autoclip.pipeline.reframe.layout import (
    MAX_FACE_SCALE,
    MIN_DWELL_S,
    MIN_FACE_WIDTH_PX,
    LayoutConfig,
    LayoutPath,
    LayoutSegment,
    LayoutSlot,
    LayoutVariant,
    ManualLayout,
    apply_dwell,
    plan_layout,
    transition_frequency,
)
from autoclip.pipeline.reframe.webcam import Rect, WebcamSpan, WebcamTrack

WIDTH = 1920
HEIGHT = 1080
DURATION = 10.0

#: A webcam overlay in the top right of a 1080p frame, with a face that is
#: big enough to read.
BIG_RECT = Rect(x=1500.0, y=50.0, width=380.0, height=300.0)
BIG_FACE = 200.0

#: A webcam so small that filling a strip with it would be a blur.
TINY_RECT = Rect(x=1800.0, y=40.0, width=60.0, height=60.0)
TINY_FACE = 25.0


def _track(
    rect: Rect,
    *,
    confidence: float = 0.8,
    face_width: float = BIG_FACE,
    spans: list[WebcamSpan] | None = None,
    duration_s: float = DURATION,
) -> WebcamTrack:
    """A webcam track, as the detector would have produced it."""
    if spans is None:
        spans = [WebcamSpan(0.0, duration_s, True, confidence)]
    return WebcamTrack(
        rect=rect,
        confidence=confidence,
        start_s=0.0,
        end_s=duration_s,
        spans=spans,
        face_width=face_width,
    )


def _plan(**kwargs: object) -> object:
    """Plan a layout with the usual defaults."""
    options: dict = {
        "source_width": WIDTH,
        "source_height": HEIGHT,
        "duration_s": DURATION,
    }
    options.update(kwargs)
    return plan_layout(**options)


# --------------------------------------------------------------------------
# The preset
# --------------------------------------------------------------------------


class TestTheStreamerPreset:
    def test_the_webcam_takes_forty_per_cent_and_the_gameplay_sixty(self) -> None:
        path = _plan(webcam=_track(BIG_RECT))

        segment = path.segments[0]
        assert segment.variant is LayoutVariant.ABOVE
        assert segment.webcam_strip is not None
        assert segment.gameplay_slot is not None

        strip_fraction = segment.webcam_strip.height / path.output_height
        gameplay_fraction = segment.gameplay_slot.height / path.output_height

        assert strip_fraction == pytest.approx(0.40, abs=0.01)
        assert gameplay_fraction == pytest.approx(0.60, abs=0.01)

    def test_the_split_is_a_preference_and_not_a_rule(self) -> None:
        """The fraction is configurable, and the planner obeys it."""
        config = LayoutConfig(webcam_height_frac=0.25)

        path = _plan(webcam=_track(BIG_RECT), config=config)

        segment = path.segments[0]
        assert segment.webcam_strip is not None
        assert segment.webcam_strip.height / path.output_height == pytest.approx(0.25, abs=0.01)

    def test_the_two_areas_do_not_overlap(self) -> None:
        path = _plan(webcam=_track(BIG_RECT))

        segment = path.segments[0]
        assert segment.webcam_strip is not None
        assert segment.gameplay_slot.y >= segment.webcam_strip.height

    def test_the_plan_says_why(self) -> None:
        path = _plan(webcam=_track(BIG_RECT))

        assert "above" in path.reason.lower()


# --------------------------------------------------------------------------
# The safe fallbacks
# --------------------------------------------------------------------------


class TestTheSafeFallbacks:
    def test_no_webcam_means_gameplay_only(self) -> None:
        path = _plan(webcam=None)

        assert path.has_webcam is False
        assert path.segments[0].variant is LayoutVariant.GAMEPLAY_ONLY
        assert path.segments[0].webcam_slot is None

    def test_a_low_confidence_webcam_means_gameplay_only(self) -> None:
        """Half a guess is not a webcam."""
        path = _plan(webcam=_track(BIG_RECT, confidence=0.2))

        assert path.has_webcam is False
        assert path.segments[0].variant is LayoutVariant.GAMEPLAY_ONLY
        assert "confidence" in path.reason.lower()

    def test_a_tiny_webcam_is_not_stacked(self) -> None:
        """A webcam too small for a strip gets an alternative layout."""
        path = _plan(webcam=_track(TINY_RECT, face_width=TINY_FACE))

        assert path.segments[0].variant is LayoutVariant.CORNER

    def test_a_tiny_webcam_is_never_blurred(self) -> None:
        """The face is never scaled up past the limit, wherever it goes."""
        path = _plan(webcam=_track(TINY_RECT, face_width=TINY_FACE))

        segment = path.segments[0]
        assert segment.webcam_slot is not None
        assert segment.webcam_source is not None

        scale = segment.webcam_slot.width / segment.webcam_source.width
        face_in_output = TINY_FACE * scale

        assert scale <= MAX_FACE_SCALE
        assert face_in_output >= MIN_FACE_WIDTH_PX

    def test_a_webcam_too_small_to_read_is_left_out(self) -> None:
        """There is no layout that shows a smudge, so there is no layout."""
        path = _plan(webcam=_track(Rect(x=1880.0, y=20.0, width=20.0, height=20.0), face_width=8.0))

        assert path.has_webcam is False
        assert path.segments[0].variant is LayoutVariant.GAMEPLAY_ONLY

    def test_the_gameplay_is_never_cropped_through_the_webcam(self) -> None:
        """The webcam must not appear twice."""
        # A webcam sitting where the centre crop would want to be.
        region = Rect(x=1300.0, y=40.0, width=380.0, height=300.0)

        path = _plan(webcam=_track(region))

        segment = path.segments[0]
        assert segment.gameplay_source is not None
        assert segment.gameplay_source.intersection_area(region) == 0.0


# --------------------------------------------------------------------------
# The manual choice
# --------------------------------------------------------------------------


class TestTheManualChoice:
    def test_a_manual_layout_beats_a_missing_webcam(self) -> None:
        manual = ManualLayout(variant=LayoutVariant.ABOVE, rect=BIG_RECT)

        path = _plan(webcam=None, manual=manual)

        assert path.manual is True
        assert path.segments[0].variant is LayoutVariant.ABOVE
        assert path.segments[0].webcam_slot is not None

    def test_a_manual_layout_beats_a_detected_webcam(self) -> None:
        """The automatic planner wanted the corner; the user wanted the strip."""
        manual = ManualLayout(variant=LayoutVariant.ABOVE, rect=TINY_RECT)

        path = _plan(webcam=_track(TINY_RECT, face_width=TINY_FACE), manual=manual)

        assert path.segments[0].variant is LayoutVariant.ABOVE

    def test_a_manual_gameplay_only_beats_a_detected_webcam(self) -> None:
        manual = ManualLayout(variant=LayoutVariant.GAMEPLAY_ONLY)

        path = _plan(webcam=_track(BIG_RECT), manual=manual)

        assert path.has_webcam is False
        assert path.segments[0].variant is LayoutVariant.GAMEPLAY_ONLY

    def test_a_manual_layout_survives_a_round_trip(self) -> None:
        manual = ManualLayout(variant=LayoutVariant.CORNER, rect=BIG_RECT, position="bottom-left")

        restored = ManualLayout.from_dict(manual.to_dict())

        assert restored == manual

    def test_a_manual_layout_is_not_blurred_either(self) -> None:
        """Even the user's choice is not allowed to produce a smudge."""
        manual = ManualLayout(variant=LayoutVariant.ABOVE, rect=TINY_RECT)

        path = _plan(webcam=_track(TINY_RECT, face_width=TINY_FACE), manual=manual)

        segment = path.segments[0]
        assert segment.webcam_slot is not None
        assert segment.webcam_source is not None
        scale = segment.webcam_slot.width / segment.webcam_source.width
        assert scale <= MAX_FACE_SCALE


# --------------------------------------------------------------------------
# Stability
# --------------------------------------------------------------------------


def _segment(start: float, end: float, variant: LayoutVariant) -> LayoutSegment:
    return LayoutSegment(
        start_s=start,
        end_s=end,
        variant=variant,
        gameplay_slot=LayoutSlot(x=0, y=0, width=1080, height=1920),
    )


class TestStability:
    def test_a_change_too_soon_is_pushed_back(self) -> None:
        segments = [
            _segment(0.0, 1.0, LayoutVariant.ABOVE),
            _segment(1.0, 5.0, LayoutVariant.GAMEPLAY_ONLY),
        ]

        result = apply_dwell(segments, min_dwell_s=MIN_DWELL_S)

        assert result[0].end_s == pytest.approx(MIN_DWELL_S)
        assert result[1].start_s == pytest.approx(MIN_DWELL_S)

    def test_a_change_in_good_time_is_left_alone(self) -> None:
        segments = [
            _segment(0.0, 2.0, LayoutVariant.ABOVE),
            _segment(2.0, 5.0, LayoutVariant.GAMEPLAY_ONLY),
        ]

        result = apply_dwell(segments, min_dwell_s=MIN_DWELL_S)

        assert result[0].end_s == pytest.approx(2.0)
        assert result[1].start_s == pytest.approx(2.0)

    def test_the_clip_is_not_cut_short(self) -> None:
        """A change that can never happen is dropped, not shortened away."""
        segments = [
            _segment(0.0, 1.0, LayoutVariant.ABOVE),
            _segment(1.0, 1.2, LayoutVariant.GAMEPLAY_ONLY),
        ]

        result = apply_dwell(segments, min_dwell_s=MIN_DWELL_S)

        assert len(result) == 1
        assert result[0].start_s == pytest.approx(0.0)
        assert result[0].end_s == pytest.approx(1.2)

    def test_the_input_is_not_modified(self) -> None:
        segments = [
            _segment(0.0, 1.0, LayoutVariant.ABOVE),
            _segment(1.0, 5.0, LayoutVariant.GAMEPLAY_ONLY),
        ]

        apply_dwell(segments, min_dwell_s=MIN_DWELL_S)

        assert segments[0].end_s == pytest.approx(1.0)
        assert segments[1].start_s == pytest.approx(1.0)

    def test_there_is_no_cap_on_the_number_of_transitions(self) -> None:
        """A long clip with many honest changes keeps every one of them."""
        segments = [
            _segment(
                index * 2.0,
                (index + 1) * 2.0,
                LayoutVariant.ABOVE if index % 2 == 0 else LayoutVariant.CORNER,
            )
            for index in range(20)
        ]

        result = apply_dwell(segments, min_dwell_s=MIN_DWELL_S)

        assert len(result) == 20

    def test_the_transition_frequency_is_measured_not_capped(self) -> None:
        segments = [
            _segment(
                index * 2.0,
                (index + 1) * 2.0,
                LayoutVariant.ABOVE if index % 2 == 0 else LayoutVariant.CORNER,
            )
            for index in range(20)
        ]

        # Nineteen changes over forty seconds.
        assert transition_frequency(segments) == pytest.approx(19 / 40 * 60)


# --------------------------------------------------------------------------
# Speech
# --------------------------------------------------------------------------


class TestTheSpeechTimeline:
    def test_speech_makes_the_webcam_bigger(self) -> None:
        path = _plan(webcam=_track(BIG_RECT), speech_spans=[(2.0, 4.0)])

        segment = path.segments[0]

        assert segment.emphasis_scale(3.0) > segment.emphasis_scale(1.0)

    def test_speech_does_not_move_the_gameplay(self) -> None:
        quiet = _plan(webcam=_track(BIG_RECT))
        talking = _plan(webcam=_track(BIG_RECT), speech_spans=[(2.0, 4.0)])

        assert quiet.segments[0].gameplay_slot == talking.segments[0].gameplay_slot

    def test_speech_never_changes_the_length_of_the_clip(self) -> None:
        quiet = _plan(webcam=_track(BIG_RECT))
        talking = _plan(webcam=_track(BIG_RECT), speech_spans=[(2.0, 4.0)])

        assert quiet.duration_s == pytest.approx(talking.duration_s)
        assert quiet.duration_s == pytest.approx(DURATION)

    def test_the_speech_spans_are_the_shared_timeline(self) -> None:
        """The layout reads the intervals it is given; it does not detect."""
        path = _plan(webcam=_track(BIG_RECT), speech_spans=[(2.0, 4.0), (6.0, 7.0)])

        segment = path.segments[0]

        assert segment.speech_spans == [(2.0, 4.0), (6.0, 7.0)]
        assert segment.emphasised is True


# --------------------------------------------------------------------------
# The render
# --------------------------------------------------------------------------


def _stacked_path(
    *, speech_spans: list[tuple[float, float]] | None = None, duration_s: float = DURATION
) -> LayoutPath:
    """A stacked layout, built by hand so the geometry is exact."""
    strip = LayoutSlot(x=0, y=0, width=1080, height=768)
    gameplay = LayoutSlot(x=0, y=768, width=1080, height=1152)
    return LayoutPath(
        source_width=WIDTH,
        source_height=HEIGHT,
        output_width=1080,
        output_height=1920,
        segments=[
            LayoutSegment(
                start_s=0.0,
                end_s=duration_s,
                variant=LayoutVariant.ABOVE,
                gameplay_slot=gameplay,
                webcam_slot=strip,
                webcam_strip=strip,
                gameplay_source=Rect(x=400.0, y=0.0, width=1012.0, height=1080.0),
                webcam_source=Rect(x=1500.0, y=65.0, width=380.0, height=270.0),
                speech_spans=speech_spans or [],
            )
        ],
    )


def _request(layout: LayoutPath | None = None):
    return export.ExportRequest(
        source=Path("source.mp4"),
        destination=Path("out.mp4"),
        start_s=0.0,
        end_s=5.0,
        crop_path=centre_crop(WIDTH, HEIGHT, 5.0),
        words=[],
        style=captions.get_style("bold_pop"),
        layout=layout,
    )


class TestTheRender:
    def test_no_layout_changes_nothing(self) -> None:
        """The plain crop path is the one the project has always used."""
        graph = export.build_video_filtergraph(_request(), subtitle_name=None)

        assert "split=2" not in graph
        assert "overlay" not in graph

    def test_a_layout_puts_the_webcam_on_the_frame(self) -> None:
        graph = export.build_video_filtergraph(_request(_stacked_path()), subtitle_name=None)

        assert "split=2" in graph
        assert "crop=" in graph
        assert "overlay=" in graph

    def test_the_gameplay_is_scaled_to_its_slot(self) -> None:
        """The gameplay fills the bottom sixty per cent, not the whole frame."""
        graph = export.build_video_filtergraph(_request(_stacked_path()), subtitle_name=None)

        assert "scale=1080:1152" in graph

    def test_the_webcam_is_cut_from_the_detected_region(self) -> None:
        graph = export.build_video_filtergraph(_request(_stacked_path()), subtitle_name=None)

        assert "crop=380:270:1500:65" in graph

    def test_the_webcam_is_only_drawn_where_it_was_seen(self) -> None:
        graph = export.build_video_filtergraph(_request(_stacked_path()), subtitle_name=None)

        assert "enable='between(t,0.0000,10.0000)'" in graph

    def test_the_speech_emphasis_reaches_the_render(self) -> None:
        path = _stacked_path(speech_spans=[(2.0, 4.0)])

        graph = export.build_video_filtergraph(_request(path), subtitle_name=None)

        assert "crop=w='" in graph
        assert "between(t,2.0000,4.0000)" in graph

    def test_a_layout_with_no_webcam_changes_nothing(self) -> None:
        path = LayoutPath(
            source_width=WIDTH,
            source_height=HEIGHT,
            output_width=1080,
            output_height=1920,
            segments=[
                LayoutSegment(
                    start_s=0.0,
                    end_s=DURATION,
                    variant=LayoutVariant.GAMEPLAY_ONLY,
                    gameplay_slot=LayoutSlot(x=0, y=0, width=1080, height=1920),
                )
            ],
        )

        graph = export.build_video_filtergraph(_request(path), subtitle_name=None)

        assert "split=2" not in graph
        assert "overlay" not in graph


# --------------------------------------------------------------------------
# The runner
# --------------------------------------------------------------------------


class TestTheRunner:
    def test_the_crop_path_matches_the_gameplay_slot(self) -> None:
        """The crop is built for the area the gameplay will occupy.

        A stacked layout leaves the bottom sixty per cent for gameplay. A
        crop path built for the full 9:16 would be stretched into that
        slot, so the aspect has to be the slot's aspect.
        """
        from autoclip.pipeline.runner import _crop_aspect

        path = _stacked_path()

        assert _crop_aspect(path, "9:16") == (15, 16)

    def test_a_clip_without_a_layout_keeps_the_export_ratio(self) -> None:
        from autoclip.pipeline.runner import _crop_aspect

        assert _crop_aspect(None, "9:16") == (9, 16)
        assert _crop_aspect(None, "16:9") == (16, 9)
        assert _crop_aspect(None, "1:1") == (1, 1)

    def test_a_gameplay_only_layout_keeps_the_export_ratio(self) -> None:
        """No webcam means the gameplay fills the frame."""
        from autoclip.pipeline.runner import _crop_aspect

        path = LayoutPath(
            source_width=WIDTH,
            source_height=HEIGHT,
            output_width=1080,
            output_height=1920,
            segments=[
                LayoutSegment(
                    start_s=0.0,
                    end_s=DURATION,
                    variant=LayoutVariant.GAMEPLAY_ONLY,
                    gameplay_slot=LayoutSlot(x=0, y=0, width=1080, height=1920),
                )
            ],
        )

        assert _crop_aspect(path, "9:16") == (9, 16)


# --------------------------------------------------------------------------
# The plan itself
# --------------------------------------------------------------------------


class TestThePlan:
    def test_the_segments_cover_the_clip_without_gaps(self) -> None:
        path = _plan(webcam=_track(BIG_RECT))

        previous_end = 0.0
        for segment in path.segments:
            assert segment.start_s == pytest.approx(previous_end)
            previous_end = segment.end_s
        assert previous_end == pytest.approx(DURATION)

    def test_the_plan_can_be_written_down(self) -> None:
        """The plan is a record, not a private calculation."""
        path = _plan(webcam=_track(BIG_RECT))

        written = path.to_dict()

        assert written["segments"]
        assert written["segments"][0]["variant"] == "above"
        assert written["segments"][0]["gameplay_slot"]["width"] == 1080

    def test_a_webcam_that_vanished_gives_a_gameplay_stretch(self) -> None:
        """'We could not see the webcam here' is not 'there was no webcam'."""
        spans = [
            WebcamSpan(0.0, 3.0, True, 0.8),
            WebcamSpan(3.0, 4.0, False, 0.0, reason="no face was seen inside the region"),
        ]

        path = _plan(webcam=_track(BIG_RECT, spans=spans))

        variants = [segment.variant for segment in path.segments]
        assert LayoutVariant.GAMEPLAY_ONLY in variants
        assert path.segments[-1].reason
