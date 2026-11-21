"""The filter graph the export stage builds has to fit in a command line.

Windows refuses a command line longer than 32,767 characters. The error it
raises — "the filename or extension is too long" — names the wrong thing: it
is the filter graph that is too long, and the job dies in the export stage
with nothing the user can act on.

The graph used to grow with the number of crop segments, because the webcam
crop was repeated for every one of them and the crop carried the whole
speech-emphasis expression. A perfectly ordinary 40-second clip produced a
36,000-character command line and never exported.

The numbers below are the ones from that clip: a 40-second podcast with a
face in the corner, a crop that follows them, and a dense speech timeline.

These tests build the graph, not the video, so they run in milliseconds.
"""

from __future__ import annotations

from pathlib import Path

from autoclip.pipeline import captions, export
from autoclip.pipeline.reframe.croppath import CropKeyframe, CropPath, CropSegment, Strategy
from autoclip.pipeline.reframe.layout import (
    LayoutPath,
    LayoutSegment,
    LayoutSlot,
    LayoutVariant,
)
from autoclip.pipeline.reframe.webcam import Rect
from autoclip.pipeline.transcript import Word
from graph_shape import graph_problems

#: Windows refuses a command line longer than this. The limit belongs to
#: CreateProcess, not to ffmpeg.
WINDOWS_COMMAND_LINE_LIMIT = 32_767

SOURCE_W, SOURCE_H = 1920, 1080

#: The webcam region of the clip that failed in the field.
WEBCAM_RECT = Rect(x=634.0, y=193.0, width=648.0, height=460.0)

#: The crop path of that clip: twenty stretches, the tracked ones carrying
#: keyframes because the crop follows the face.
CROP_STRETCHES = [
    (0.0, 3.801, 20),
    (3.801, 8.472, 1),
    (8.472, 12.109, 1),
    (12.109, 13.177, 1),
    (13.177, 14.711, 6),
    (14.711, 16.847, 1),
    (16.847, 18.549, 10),
    (18.549, 20.084, 1),
    (20.084, 21.552, 8),
    (21.552, 23.187, 1),
    (23.187, 24.621, 9),
    (24.621, 26.59, 1),
    (26.59, 27.691, 6),
    (27.691, 29.827, 1),
    (29.827, 32.329, 13),
    (32.329, 33.864, 1),
    (33.864, 35.632, 1),
    (35.632, 36.967, 6),
    (36.967, 38.469, 1),
    (38.469, 40.179, 8),
]

#: The layout of that clip: the webcam is on for half of it, and the speech
#: stretches are written against the clip's own timeline.
LAYOUT_STRETCHES = [
    (0.0, 3.8, True, [(0.0, 3.8)]),
    (3.8, 8.472, False, []),
    (8.472, 12.109, True, [(9.569, 10.199), (11.219, 11.999)]),
    (12.109, 13.609, False, []),
    (13.609, 15.109, True, [(13.229, 14.711)]),
    (15.109, 16.847, False, []),
    (16.847, 18.548, True, [(17.129, 17.429)]),
    (18.548, 20.083, False, []),
    (20.083, 21.583, True, [(20.083, 21.551)]),
    (21.583, 23.186, False, []),
    (23.186, 24.686, True, [(23.186, 24.621)]),
    (24.686, 26.59, False, []),
    (26.59, 28.09, True, [(26.59, 27.691)]),
    (28.09, 29.826, False, []),
    (29.826, 33.864, True, [(31.019, 32.069)]),
    (33.864, 35.632, False, []),
    (35.632, 37.132, True, [(35.632, 36.967)]),
    (37.132, 38.632, False, []),
    (38.632, 40.179, True, [(39.269, 40.179)]),
]


def make_crop_path(stretches=CROP_STRETCHES) -> CropPath:
    """The crop path of the clip that failed, rebuilt from its shape."""
    segments: list[CropSegment] = []
    for start, end, keyframe_count in stretches:
        keyframes = [
            CropKeyframe(
                t=round(start + (end - start) * (i / max(keyframe_count - 1, 1)), 4),
                x=454.0 + i * 3.5,
                y=0.0,
            )
            for i in range(keyframe_count)
        ]
        segments.append(
            CropSegment(
                start_s=start,
                end_s=end,
                width=1012,
                height=1080,
                keyframes=keyframes,
                strategy=Strategy.TRACK if keyframe_count > 1 else Strategy.GENERAL,
            )
        )

    return CropPath(
        source_width=SOURCE_W,
        source_height=SOURCE_H,
        segments=segments,
    )


def make_layout(stretches=LAYOUT_STRETCHES) -> LayoutPath:
    """The layout of the clip that failed, rebuilt from its shape."""
    strip = LayoutSlot(x=0, y=0, width=1080, height=768)
    gameplay = LayoutSlot(x=0, y=768, width=1080, height=1152)

    segments = [
        LayoutSegment(
            start_s=start,
            end_s=end,
            variant=LayoutVariant.ABOVE if has_webcam else LayoutVariant.GAMEPLAY_ONLY,
            gameplay_slot=gameplay,
            webcam_slot=strip if has_webcam else None,
            webcam_strip=strip if has_webcam else None,
            gameplay_source=Rect(x=454.0, y=0.0, width=1012.0, height=1080.0),
            webcam_source=WEBCAM_RECT if has_webcam else None,
            speech_spans=spans,
        )
        for start, end, has_webcam, spans in stretches
    ]

    return LayoutPath(
        source_width=SOURCE_W,
        source_height=SOURCE_H,
        output_width=1080,
        output_height=1920,
        segments=segments,
    )


def build_graph(*, crop_stretches=CROP_STRETCHES, layout_stretches=LAYOUT_STRETCHES) -> str:
    """The ``-filter_complex`` graph for one clip, as the export builds it."""
    request = export.ExportRequest(
        source=Path("source.mp4"),
        destination=Path("out.mp4"),
        start_s=0.0,
        end_s=40.179,
        crop_path=make_crop_path(crop_stretches),
        words=[Word(text="word", start=0.0, end=1.0)],
        style=captions.get_style("bold_pop"),
        ratio="9:16",
        layout=make_layout(layout_stretches),
    )
    return export.build_video_filtergraph(request, subtitle_name="captions.ass")


class TestCommandLineLength:
    def test_the_clip_that_failed_in_the_field_now_fits(self) -> None:
        # The graph this build produced for that clip was 36,588 characters —
        # past the limit, so the export died before it wrote a file.
        graph = build_graph()

        assert len(graph) < WINDOWS_COMMAND_LINE_LIMIT

    def test_a_clip_with_more_stretches_still_fits(self) -> None:
        stretches = [stretch for stretch in CROP_STRETCHES for _ in range(2)]
        graph = build_graph(crop_stretches=stretches)

        assert len(graph) < WINDOWS_COMMAND_LINE_LIMIT


class TestGraphGrowth:
    def test_the_emphasis_expression_is_not_repeated_for_every_segment(self) -> None:
        """One term per speech stretch, however many segments the clip has.

        The webcam crop used to be rebuilt for every crop segment, and every
        copy carried the whole speech expression with it.
        """
        small = build_graph(crop_stretches=CROP_STRETCHES[:2])
        large = build_graph(crop_stretches=CROP_STRETCHES * 2)

        assert small.count("between(t,") == large.count("between(t,")

    def test_the_emphasis_expression_appears_once_per_stretch(self) -> None:
        graph = build_graph()

        # The speech expression names every stretch of speech four times —
        # once for the width of the window, once for its height, and once in
        # each of the two offsets — and the webcam's presence expression
        # names every stretch of the layout once.
        assert graph.count("between(t,") == 11 * 4 + 10

    def test_the_webcam_crop_is_built_once(self) -> None:
        graph = build_graph()

        # The gameplay crop is `crop=w=...`; the webcam crop is `crop=w='...'`.
        assert graph.count("crop=w='") == 1

    def test_the_graph_does_not_grow_with_the_number_of_segments(self) -> None:
        """Only the segments themselves may add to the graph, and only once each."""
        small = build_graph(crop_stretches=CROP_STRETCHES[:2])
        large = build_graph(crop_stretches=CROP_STRETCHES * 2)

        # 38 more stretches, each adding a trim and a crop of its own.
        assert len(large) - len(small) < 38 * 1200


class TestGraphShape:
    """The graph has to be valid on every ffmpeg, not only the newest one.

    A filter output may be consumed only once. ffmpeg 9 tolerates naming the
    same output twice; ffmpeg 7 refuses it with *"Invalid stream specifier"*,
    and the export then fails on every strict ffmpeg for any clip whose crop
    path has more than one segment.

    The check is structural rather than a render, so it catches the defect on
    any ffmpeg — the developer's included.
    """

    def test_the_graph_is_well_formed_for_any_ffmpeg(self) -> None:
        graph = build_graph()

        problems = graph_problems(graph)

        assert not problems, "the filter graph is malformed: " + "; ".join(problems)

    def test_the_graph_is_well_formed_with_a_single_segment(self) -> None:
        graph = build_graph(
            crop_stretches=CROP_STRETCHES[:1], layout_stretches=LAYOUT_STRETCHES[:1]
        )

        problems = graph_problems(graph)

        assert not problems, "the filter graph is malformed: " + "; ".join(problems)

    def test_the_graph_is_well_formed_without_a_webcam(self) -> None:
        """A clip with no webcam has one consumer, and it gets one output."""
        graph = build_graph(
            layout_stretches=[(s, e, False, spans) for s, e, _, spans in LAYOUT_STRETCHES]
        )

        problems = graph_problems(graph)

        assert not problems, "the filter graph is malformed: " + "; ".join(problems)

    def test_every_segment_gets_its_own_copy_of_the_source(self) -> None:
        """The source is split once per consumer, not once per branch.

        This is the shape the fix took: a ``split`` with one output for each
        segment of each branch, so no output is ever named twice.
        """
        graph = build_graph(crop_stretches=CROP_STRETCHES[:3])

        # Three gameplay segments and three webcam segments: six outputs.
        assert "split=6" in graph
        assert graph.count("trim=start=") == 6
