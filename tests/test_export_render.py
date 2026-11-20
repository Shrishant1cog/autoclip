"""End-to-end render tests against real ffmpeg.

These are the tests that catch what unit tests structurally cannot: a
filtergraph that parses but produces the wrong thing, a font libass can't
resolve, a path escaping bug that only appears on Windows, an encoder flag the
local build rejects. Marked ``slow`` — they shell out and encode video.
"""

from __future__ import annotations

import subprocess
from pathlib import Path

import pytest
from autoclip.config import ExportSettings
from autoclip.pipeline import captions, export, ffmpeg
from autoclip.pipeline.reframe.croppath import (
    CropKeyframe,
    CropPath,
    CropSegment,
    Strategy,
    centre_crop,
)
from autoclip.pipeline.reframe.layout import (
    LayoutPath,
    LayoutSegment,
    LayoutSlot,
    LayoutVariant,
)
from autoclip.pipeline.reframe.webcam import Rect
from autoclip.pipeline.transcript import Word

pytestmark = pytest.mark.slow

SOURCE_W, SOURCE_H = 1280, 720
SOURCE_DURATION = 10.0

#: Where the webcam region sits in the marked source below.
CAM_X, CAM_Y, CAM_W, CAM_H = 900, 40, 340, 260


@pytest.fixture(scope="module")
def source_video(tmp_path_factory) -> Path:
    """A synthetic 1280x720 test clip with a tone, generated once per session."""
    path = tmp_path_factory.mktemp("media") / "source.mp4"
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
            f"testsrc2=size={SOURCE_W}x{SOURCE_H}:rate=30:duration={SOURCE_DURATION}",
            "-f",
            "lavfi",
            "-i",
            f"sine=frequency=440:duration={SOURCE_DURATION}",
            "-c:v",
            "libx264",
            "-pix_fmt",
            "yuv420p",
            "-c:a",
            "aac",
            "-shortest",
            str(path),
        ],
        check=True,
        capture_output=True,
    )
    return path


@pytest.fixture(scope="module")
def marked_source(tmp_path_factory) -> Path:
    """A still source with a red rectangle where the webcam would be.

    Still, so the only thing that can change a pixel is the layout. Moving
    is the one thing a test must not have.
    """
    path = tmp_path_factory.mktemp("media") / "marked.mp4"
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
            f"color=c=0x203040:s={SOURCE_W}x{SOURCE_H}:r=30:d={SOURCE_DURATION}",
            "-f",
            "lavfi",
            "-i",
            f"color=c=0xdd3311:s={CAM_W}x{CAM_H}:r=30:d={SOURCE_DURATION}",
            "-filter_complex",
            f"[0:v][1:v]overlay={CAM_X}:{CAM_Y}:shortest=1[v]",
            "-map",
            "[v]",
            "-c:v",
            "libx264",
            "-pix_fmt",
            "yuv420p",
            str(path),
        ],
        check=True,
        capture_output=True,
    )
    return path


@pytest.fixture
def words() -> list[Word]:
    """Words spanning 2.0-7.0s of the source, matching the clip under test."""
    texts = [
        "this",
        "is",
        "a",
        "test",
        "of",
        "the",
        "caption",
        "rendering",
        "pipeline",
        "right",
        "now",
    ]
    step = 5.0 / len(texts)
    return [
        Word(text=text, start=2.0 + i * step, end=2.0 + i * step + step * 0.85)
        for i, text in enumerate(texts)
    ]


def make_request(source: Path, destination: Path, crop_path: CropPath, words, **kwargs):
    return export.ExportRequest(
        source=source,
        destination=destination,
        start_s=2.0,
        end_s=7.0,
        crop_path=crop_path,
        words=words,
        style=kwargs.pop("style", captions.get_style("bold_pop")),
        **kwargs,
    )


class TestSingleSegmentRender:
    def test_renders_a_vertical_clip(self, source_video, words, tmp_path) -> None:
        destination = tmp_path / "out.mp4"
        request = make_request(
            source_video, destination, centre_crop(SOURCE_W, SOURCE_H, 5.0), words
        )

        export.export_clip(request, work_dir=tmp_path / "work")

        assert destination.exists()
        info = ffmpeg.probe(destination)
        assert (info.width, info.height) == (1080, 1920)
        assert info.has_audio
        assert info.duration_s == pytest.approx(5.0, abs=0.35)

    @pytest.mark.parametrize("ratio", ["9:16", "1:1", "16:9"])
    def test_every_ratio_renders(self, source_video, words, tmp_path, ratio: str) -> None:
        destination = tmp_path / f"out_{ratio.replace(':', 'x')}.mp4"
        aspect = tuple(int(part) for part in ratio.split(":"))
        crop_path = centre_crop(SOURCE_W, SOURCE_H, 5.0, aspect_w=aspect[0], aspect_h=aspect[1])

        export.export_clip(
            make_request(source_video, destination, crop_path, words, ratio=ratio),
            work_dir=tmp_path / "work",
        )

        info = ffmpeg.probe(destination)
        assert (info.width, info.height) == export.ratio_dimensions(ratio)

    @pytest.mark.parametrize("style_key", list(captions.PRESETS))
    def test_every_caption_style_burns_in(
        self, source_video, words, tmp_path, style_key: str
    ) -> None:
        # A style whose font libass can't resolve still "succeeds" but renders
        # in a substituted face, so this checks the render completes for each.
        destination = tmp_path / f"out_{style_key}.mp4"
        request = make_request(
            source_video,
            destination,
            centre_crop(SOURCE_W, SOURCE_H, 5.0),
            words,
            style=captions.get_style(style_key),
        )

        export.export_clip(request, work_dir=tmp_path / "work")

        assert destination.stat().st_size > 1000

    def test_captions_visibly_change_the_output(self, source_video, words, tmp_path) -> None:
        """Burned captions must actually alter the pixels.

        Without this, a silently-failing `ass` filter would leave every other
        assertion passing while shipping clips with no captions on them.
        """
        with_captions = tmp_path / "with.mp4"
        without_captions = tmp_path / "without.mp4"

        export.export_clip(
            make_request(source_video, with_captions, centre_crop(SOURCE_W, SOURCE_H, 5.0), words),
            work_dir=tmp_path / "work",
        )
        export.export_clip(
            make_request(
                source_video,
                without_captions,
                centre_crop(SOURCE_W, SOURCE_H, 5.0),
                words,
                burn_captions=False,
            ),
            work_dir=tmp_path / "work",
        )

        assert _frame_signature(with_captions, 2.5) != _frame_signature(without_captions, 2.5)


class TestMultiSegmentRender:
    def test_concatenated_segments_render(self, source_video, words, tmp_path) -> None:
        crop_w, crop_h = 404, 720
        crop_path = CropPath(
            source_width=SOURCE_W,
            source_height=SOURCE_H,
            segments=[
                CropSegment(
                    start_s=0.0,
                    end_s=2.5,
                    width=crop_w,
                    height=crop_h,
                    keyframes=[CropKeyframe(0.0, 100.0, 0.0)],
                    strategy=Strategy.TRACK,
                ),
                CropSegment(
                    start_s=2.5,
                    end_s=5.0,
                    width=crop_w,
                    height=crop_h,
                    keyframes=[CropKeyframe(2.5, 700.0, 0.0)],
                    strategy=Strategy.TRACK,
                ),
            ],
        )
        destination = tmp_path / "multi.mp4"

        export.export_clip(
            make_request(source_video, destination, crop_path, words),
            work_dir=tmp_path / "work",
        )

        info = ffmpeg.probe(destination)
        assert (info.width, info.height) == (1080, 1920)
        assert info.duration_s == pytest.approx(5.0, abs=0.35)

    def test_segments_actually_show_different_regions(self, source_video, words, tmp_path) -> None:
        """A crop that doesn't move would make the two segments identical."""
        crop_w, crop_h = 404, 720
        crop_path = CropPath(
            source_width=SOURCE_W,
            source_height=SOURCE_H,
            segments=[
                CropSegment(
                    start_s=0.0,
                    end_s=2.5,
                    width=crop_w,
                    height=crop_h,
                    keyframes=[CropKeyframe(0.0, 0.0, 0.0)],
                ),
                CropSegment(
                    start_s=2.5,
                    end_s=5.0,
                    width=crop_w,
                    height=crop_h,
                    keyframes=[CropKeyframe(2.5, 876.0, 0.0)],
                ),
            ],
        )
        destination = tmp_path / "regions.mp4"

        export.export_clip(
            make_request(source_video, destination, crop_path, words, burn_captions=False),
            work_dir=tmp_path / "work",
        )

        assert _frame_signature(destination, 1.0) != _frame_signature(destination, 4.0)

    def test_animated_crop_expression_renders(self, source_video, words, tmp_path) -> None:
        crop_path = CropPath(
            source_width=SOURCE_W,
            source_height=SOURCE_H,
            segments=[
                CropSegment(
                    start_s=0.0,
                    end_s=5.0,
                    width=404,
                    height=720,
                    keyframes=[
                        CropKeyframe(0.0, 0.0, 0.0),
                        CropKeyframe(2.5, 400.0, 0.0),
                        CropKeyframe(5.0, 876.0, 0.0),
                    ],
                    strategy=Strategy.TRACK,
                )
            ],
        )
        destination = tmp_path / "animated.mp4"

        export.export_clip(
            make_request(source_video, destination, crop_path, words, burn_captions=False),
            work_dir=tmp_path / "work",
        )

        # A broken expression would evaluate to a constant, leaving these equal.
        assert _frame_signature(destination, 0.5) != _frame_signature(destination, 4.5)

    def test_fit_segment_renders_with_blurred_background(
        self, source_video, words, tmp_path
    ) -> None:
        crop_path = CropPath(
            source_width=SOURCE_W,
            source_height=SOURCE_H,
            segments=[
                CropSegment(
                    start_s=0.0,
                    end_s=5.0,
                    width=SOURCE_W,
                    height=SOURCE_H,
                    keyframes=[CropKeyframe(0.0, 0.0, 0.0)],
                    strategy=Strategy.WIDE,
                    fit=True,
                )
            ],
        )
        destination = tmp_path / "fit.mp4"

        export.export_clip(
            make_request(source_video, destination, crop_path, words),
            work_dir=tmp_path / "work",
        )

        info = ffmpeg.probe(destination)
        assert (info.width, info.height) == (1080, 1920)


class TestLayoutRender:
    """The layout has to survive contact with ffmpeg.

    A filtergraph can parse and still produce the wrong thing, so these
    tests look at the pixels rather than at the string.
    """

    def _stacked(self, *, speech_spans: list[tuple[float, float]] | None = None) -> LayoutPath:
        strip = LayoutSlot(x=0, y=0, width=1080, height=768)
        gameplay = LayoutSlot(x=0, y=768, width=1080, height=1152)
        return LayoutPath(
            source_width=SOURCE_W,
            source_height=SOURCE_H,
            output_width=1080,
            output_height=1920,
            segments=[
                LayoutSegment(
                    start_s=0.0,
                    end_s=5.0,
                    variant=LayoutVariant.ABOVE,
                    gameplay_slot=gameplay,
                    webcam_slot=strip,
                    webcam_strip=strip,
                    gameplay_source=Rect(x=134.0, y=0.0, width=1012.0, height=720.0),
                    webcam_source=Rect(x=CAM_X, y=CAM_Y + 9, width=CAM_W, height=242),
                    speech_spans=speech_spans or [],
                )
            ],
        )

    def _corner(self) -> LayoutPath:
        slot = LayoutSlot(x=756, y=32, width=292, height=224)
        return LayoutPath(
            source_width=SOURCE_W,
            source_height=SOURCE_H,
            output_width=1080,
            output_height=1920,
            segments=[
                LayoutSegment(
                    start_s=0.0,
                    end_s=5.0,
                    variant=LayoutVariant.CORNER,
                    gameplay_slot=LayoutSlot(x=0, y=0, width=1080, height=1920),
                    webcam_slot=slot,
                    webcam_strip=slot,
                    gameplay_source=Rect(x=134.0, y=0.0, width=1012.0, height=720.0),
                    webcam_source=Rect(x=CAM_X, y=CAM_Y, width=CAM_W, height=CAM_H),
                )
            ],
        )

    def test_the_stacked_layout_renders(self, marked_source, words, tmp_path) -> None:
        destination = tmp_path / "stacked.mp4"
        crop_path = centre_crop(SOURCE_W, SOURCE_H, 5.0, aspect_w=15, aspect_h=16)

        export.export_clip(
            make_request(
                marked_source,
                destination,
                crop_path,
                words,
                layout=self._stacked(),
            ),
            work_dir=tmp_path / "work",
        )

        info = ffmpeg.probe(destination)
        assert (info.width, info.height) == (1080, 1920)
        assert info.duration_s == pytest.approx(5.0, abs=0.35)

    def test_the_corner_layout_renders(self, marked_source, words, tmp_path) -> None:
        destination = tmp_path / "corner.mp4"

        export.export_clip(
            make_request(
                marked_source,
                destination,
                centre_crop(SOURCE_W, SOURCE_H, 5.0),
                words,
                layout=self._corner(),
            ),
            work_dir=tmp_path / "work",
        )

        info = ffmpeg.probe(destination)
        assert (info.width, info.height) == (1080, 1920)

    def test_the_webcam_is_actually_drawn(self, marked_source, words, tmp_path) -> None:
        """The webcam has to be on the frame, not merely in the filtergraph."""
        with_layout = tmp_path / "with.mp4"
        without_layout = tmp_path / "without.mp4"

        export.export_clip(
            make_request(
                marked_source,
                with_layout,
                centre_crop(SOURCE_W, SOURCE_H, 5.0, aspect_w=15, aspect_h=16),
                words,
                layout=self._stacked(),
                burn_captions=False,
            ),
            work_dir=tmp_path / "work",
        )
        export.export_clip(
            make_request(
                marked_source,
                without_layout,
                centre_crop(SOURCE_W, SOURCE_H, 5.0, aspect_w=15, aspect_h=16),
                words,
                burn_captions=False,
            ),
            work_dir=tmp_path / "work",
        )

        # The top strip is where the webcam goes.
        assert _region_signature(with_layout, 2.5, 0, 0, 1080, 768) != _region_signature(
            without_layout, 2.5, 0, 0, 1080, 768
        )

    def test_the_gameplay_is_in_the_bottom_of_the_frame(
        self, marked_source, words, tmp_path
    ) -> None:
        """The gameplay sits under the webcam, not behind it."""
        destination = tmp_path / "split.mp4"

        export.export_clip(
            make_request(
                marked_source,
                destination,
                centre_crop(SOURCE_W, SOURCE_H, 5.0, aspect_w=15, aspect_h=16),
                words,
                layout=self._stacked(),
                burn_captions=False,
            ),
            work_dir=tmp_path / "work",
        )

        # The webcam's red rectangle reaches the bottom of the strip, so the
        # strip is not plain background.
        assert _region_signature(destination, 2.5, 0, 700, 1080, 68) != _region_signature(
            destination, 2.5, 0, 1200, 1080, 68
        )

    def test_the_speech_emphasis_renders(self, marked_source, words, tmp_path) -> None:
        """The emphasis changes the picture while someone is speaking."""
        destination = tmp_path / "emphasis.mp4"

        export.export_clip(
            make_request(
                marked_source,
                destination,
                centre_crop(SOURCE_W, SOURCE_H, 5.0, aspect_w=15, aspect_h=16),
                words,
                layout=self._stacked(speech_spans=[(1.0, 3.0)]),
                burn_captions=False,
            ),
            work_dir=tmp_path / "work",
        )

        quiet = _region_signature(destination, 0.3, 0, 0, 1080, 768)
        talking = _region_signature(destination, 2.0, 0, 0, 1080, 768)

        assert quiet != talking

    def test_the_clip_is_not_lengthened_by_the_layout(self, marked_source, words, tmp_path) -> None:
        """Speech makes the webcam bigger. It does not make the clip longer."""
        destination = tmp_path / "length.mp4"

        export.export_clip(
            make_request(
                marked_source,
                destination,
                centre_crop(SOURCE_W, SOURCE_H, 5.0, aspect_w=15, aspect_h=16),
                words,
                layout=self._stacked(speech_spans=[(1.0, 3.0)]),
            ),
            work_dir=tmp_path / "work",
        )

        assert ffmpeg.probe(destination).duration_s == pytest.approx(5.0, abs=0.35)


class TestEncoding:
    def test_software_encoder_path(self, source_video, words, tmp_path) -> None:
        settings = ExportSettings(prefer_hardware_encoder=False)
        destination = tmp_path / "x264.mp4"

        export.export_clip(
            make_request(source_video, destination, centre_crop(SOURCE_W, SOURCE_H, 5.0), words),
            work_dir=tmp_path / "work",
            settings=settings,
        )

        assert ffmpeg.probe(destination).video_codec == "h264"

    def test_output_is_yuv420p(self, source_video, words, tmp_path) -> None:
        # Anything else fails to play on a surprising number of phones.
        destination = tmp_path / "pixfmt.mp4"
        export.export_clip(
            make_request(source_video, destination, centre_crop(SOURCE_W, SOURCE_H, 5.0), words),
            work_dir=tmp_path / "work",
        )

        result = subprocess.run(
            [
                ffmpeg.ffprobe_path(),
                "-v",
                "error",
                "-select_streams",
                "v:0",
                "-show_entries",
                "stream=pix_fmt",
                "-of",
                "csv=p=0",
                str(destination),
            ],
            capture_output=True,
            text=True,
            check=True,
        )

        assert result.stdout.strip() == "yuv420p"

    def test_srt_sidecar_is_written_when_requested(self, source_video, words, tmp_path) -> None:
        settings = ExportSettings(write_srt=True)
        destination = tmp_path / "sidecar.mp4"

        export.export_clip(
            make_request(source_video, destination, centre_crop(SOURCE_W, SOURCE_H, 5.0), words),
            work_dir=tmp_path / "work",
            settings=settings,
        )

        assert destination.with_suffix(".srt").exists()

    def test_progress_reaches_completion(self, source_video, words, tmp_path) -> None:
        seen: list[float] = []

        export.export_clip(
            make_request(
                source_video, tmp_path / "progress.mp4", centre_crop(SOURCE_W, SOURCE_H, 5.0), words
            ),
            work_dir=tmp_path / "work",
            on_progress=seen.append,
        )

        assert seen
        assert seen[-1] == 1.0
        assert all(0.0 <= value <= 1.0 for value in seen)


class TestInstagramCompatibility:
    """The exported file has to satisfy Meta's documented Reel rules.

    Two of them are not visible in a normal ``ffprobe`` report: the
    ``moov`` atom has to be at the front of the file, and there must be
    no edit list. FFmpeg writes an edit list by default, so the export
    turns it off — this class is the guard that it stays off.
    """

    def test_the_exported_file_meets_instagrams_reel_requirements(
        self, source_video, words, tmp_path
    ) -> None:
        from autoclip.instagram import media as ig_media

        destination = tmp_path / "out.mp4"

        export.export_clip(
            make_request(source_video, destination, centre_crop(SOURCE_W, SOURCE_H, 5.0), words),
            work_dir=tmp_path / "work",
        )

        report = ig_media.validate_reel(destination)

        assert report.ok is True, report.problems
        assert report.facts["moov_at_front"] is True

    def test_the_exported_file_carries_no_edit_list(self, source_video, words, tmp_path) -> None:
        from autoclip.instagram import media as ig_media

        destination = tmp_path / "out.mp4"

        export.export_clip(
            make_request(source_video, destination, centre_crop(SOURCE_W, SOURCE_H, 5.0), words),
            work_dir=tmp_path / "work",
        )

        boxes = ig_media.scan_boxes(destination)

        assert boxes["has_edit_list"] is False

    def test_removing_the_edit_list_does_not_change_the_duration(
        self, source_video, words, tmp_path
    ) -> None:
        """An edit list is how a player skips the encoder's priming
        samples. Removing it must not shorten the clip."""
        destination = tmp_path / "out.mp4"

        export.export_clip(
            make_request(source_video, destination, centre_crop(SOURCE_W, SOURCE_H, 5.0), words),
            work_dir=tmp_path / "work",
        )

        info = ffmpeg.probe(destination)

        assert info.duration_s == pytest.approx(5.0, abs=0.35)
        assert info.has_audio


class TestPathsWithSpecialCharacters:
    def test_directory_with_spaces_and_punctuation(self, source_video, words, tmp_path) -> None:
        """The escaping test that actually matters on Windows.

        A drive letter plus a space plus an apostrophe is the combination that
        breaks naive filtergraph quoting.
        """
        awkward = tmp_path / "My Clips (2026)" / "it's here"
        awkward.mkdir(parents=True)
        destination = awkward / "out.mp4"

        export.export_clip(
            make_request(source_video, destination, centre_crop(SOURCE_W, SOURCE_H, 5.0), words),
            work_dir=awkward / "work",
        )

        assert destination.exists()
        assert ffmpeg.probe(destination).width == 1080


def _frame_signature(video: Path, timestamp: float) -> str:
    """Hash one frame's pixels, for comparing rendered output."""
    result = subprocess.run(
        [
            ffmpeg.ffmpeg_path(),
            "-hide_banner",
            "-loglevel",
            "error",
            "-ss",
            str(timestamp),
            "-i",
            str(video),
            "-frames:v",
            "1",
            "-f",
            "hash",
            "-hash",
            "md5",
            "-",
        ],
        capture_output=True,
        text=True,
        check=True,
    )
    return result.stdout.strip()


def _region_signature(video: Path, timestamp: float, x: int, y: int, w: int, h: int) -> str:
    """Hash one rectangle of one frame, for comparing parts of a render."""
    result = subprocess.run(
        [
            ffmpeg.ffmpeg_path(),
            "-hide_banner",
            "-loglevel",
            "error",
            "-ss",
            str(timestamp),
            "-i",
            str(video),
            "-frames:v",
            "1",
            "-vf",
            f"crop={w}:{h}:{x}:{y}",
            "-f",
            "hash",
            "-hash",
            "md5",
            "-",
        ],
        capture_output=True,
        text=True,
        check=True,
    )
    return result.stdout.strip()
