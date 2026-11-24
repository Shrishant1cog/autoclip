"""What the pipeline reuses between runs, and what it must not.

Two caches stand between a retry and a fresh run: the crop plan saved for a
clip, and the webcam report saved for the source. Both are answers to a
question, and both are only answers if the question is the same one.

* The crop plan depends on the **aspect ratio** it was made for and on the
  **webcam region** it was kept clear of. A plan made for the old aspect is
  the wrong shape for the new slot, and reusing it renders the gameplay in
  the wrong proportions. This is not hypothetical: a plan built before the
  webcam was found was reused after it was, and the gameplay was cropped to
  9:16 and then stretched into a 15:16 slot.
* The webcam report is reused only when the detector actually **looked**. A
  report that says the detection *failed* is the absence of an answer, and
  keeping it means a job that could have found the webcam never will.

The third thing here is not a cache but the same kind of mistake: the
detector is asked for the stretches the clips use, and the clips are in
**rank order**. Rank is not position, and a decoder cannot seek backwards.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest
from autoclip.config import Settings
from autoclip.db.models import Clip, Job, Source
from autoclip.pipeline import runner as runner_module
from autoclip.pipeline.reframe import plan_fingerprint
from autoclip.pipeline.reframe.croppath import centre_crop
from autoclip.pipeline.reframe.layout import (
    LayoutPath,
    LayoutSegment,
    LayoutSlot,
    LayoutVariant,
)
from autoclip.pipeline.reframe.webcam import (
    REPORT_VERSION,
    Rect,
    WebcamReport,
    WebcamTrack,
)

WIDTH = 1920
HEIGHT = 1080


def _runner() -> runner_module.PipelineRunner:
    return runner_module.PipelineRunner(
        Job(id="job-cache", source_id="src-cache"),
        Source(id="src-cache", type="upload", path="C:/videos/source.mp4"),
        settings=Settings(),
    )


def _patch_probe(monkeypatch: pytest.MonkeyPatch) -> None:
    """A source of the right shape, without a file behind it."""
    from autoclip.pipeline import ffmpeg

    monkeypatch.setattr(
        ffmpeg,
        "probe",
        lambda path: ffmpeg.MediaInfo(
            path=Path(path),
            duration_s=2279.0,
            has_video=True,
            has_audio=True,
            width=WIDTH,
            height=HEIGHT,
            fps=59.94,
        ),
    )


def _layout(gameplay_width: int = 1080, gameplay_height: int = 1152) -> LayoutPath:
    """A stacked layout: the webcam above, the gameplay below."""
    strip = LayoutSlot(x=0, y=0, width=1080, height=768)
    gameplay = LayoutSlot(x=0, y=768, width=gameplay_width, height=gameplay_height)
    return LayoutPath(
        source_width=WIDTH,
        source_height=HEIGHT,
        output_width=1080,
        output_height=1920,
        segments=[
            LayoutSegment(
                start_s=0.0,
                end_s=30.0,
                variant=LayoutVariant.ABOVE,
                gameplay_slot=gameplay,
                webcam_slot=strip,
                webcam_strip=strip,
                gameplay_source=Rect(x=0.0, y=0.0, width=1012.0, height=1080.0),
                webcam_source=Rect(x=1272.0, y=0.0, width=640.0, height=436.0),
                webcam_region=Rect(x=1272.0, y=0.0, width=640.0, height=436.0),
            )
        ],
    )


def _clips() -> list[Clip]:
    """Three clips, in rank order — which is not the order they sit in."""
    return [
        Clip(id="clip-c", job_id="job-cache", start_s=1273.12, end_s=1303.96, rank=1),
        Clip(id="clip-a", job_id="job-cache", start_s=530.31, end_s=562.88, rank=2),
        Clip(id="clip-b", job_id="job-cache", start_s=958.74, end_s=990.41, rank=3),
    ]


# --------------------------------------------------------------------------
# The crop plan
# --------------------------------------------------------------------------


class TestTheSavedCropPlan:
    def test_a_plan_built_for_another_layout_is_not_reused(self, tmp_path: Path) -> None:
        """The plan is a crop *for an aspect ratio* and *clear of a region*."""

        saved = tmp_path / "crop.json"
        centre_crop(WIDTH, HEIGHT, 30.0).save(saved)

        assert runner_module._load_crop_path(saved, "aspect=9x16;something") is None

    def test_a_plan_built_for_the_same_layout_is_reused(self, tmp_path: Path) -> None:
        from autoclip.pipeline.reframe import ReframeConfig

        config = ReframeConfig(aspect_w=15, aspect_h=16)
        path = centre_crop(WIDTH, HEIGHT, 30.0)
        path.config_fingerprint = plan_fingerprint(config)
        saved = tmp_path / "crop.json"
        path.save(saved)

        loaded = runner_module._load_crop_path(saved, plan_fingerprint(config))

        assert loaded is not None
        assert loaded.source_width == WIDTH

    def test_a_broken_plan_is_built_again(self, tmp_path: Path) -> None:
        saved = tmp_path / "crop.json"
        saved.write_text("{not json", encoding="utf-8")

        assert runner_module._load_crop_path(saved, "aspect=9x16") is None

    def test_the_stage_builds_a_new_plan_when_the_layout_has_changed(
        self, monkeypatch: pytest.MonkeyPatch, initialised_db: int
    ) -> None:
        """The webcam's region changes the aspect the gameplay is cropped to.

        The plan saved before the webcam was found was cropped to 9:16; the
        stacked layout leaves the bottom sixty per cent for gameplay, which
        is 15:16. Reusing the old plan would stretch the gameplay.
        """
        runner = _runner()
        built: list[tuple[int, int]] = []

        def fake_build(source: Path, **kwargs: Any) -> Any:
            config = kwargs["config"]
            built.append((config.aspect_w, config.aspect_h))
            path = centre_crop(
                WIDTH, HEIGHT, 30.0, aspect_w=config.aspect_w, aspect_h=config.aspect_h
            )
            path.config_fingerprint = plan_fingerprint(config)
            return path

        monkeypatch.setattr(runner_module, "build_crop_path", fake_build)
        monkeypatch.setattr(
            runner_module.PipelineRunner,
            "_detect_webcam",
            lambda self, source_path, *, windows=None: WebcamReport(
                track=WebcamTrack(
                    rect=Rect(x=1272.0, y=0.0, width=640.0, height=436.0),
                    confidence=0.9,
                    start_s=0.0,
                    end_s=2279.0,
                    spans=[],
                ),
                source_width=WIDTH,
                source_height=HEIGHT,
            ),
        )
        layouts: list[LayoutPath] = []

        def fake_plan(self: Any, *args: Any, **kwargs: Any) -> LayoutPath:
            return layouts[-1]

        monkeypatch.setattr(runner_module.PipelineRunner, "_plan_layout", fake_plan)
        monkeypatch.setattr(runner_module.PipelineRunner, "_finish_stage", lambda *a, **k: None)

        # The first run: no webcam was found, so the gameplay is cropped to
        # the whole 9:16 output.
        layouts.append(_layout(gameplay_width=1080, gameplay_height=1920))
        runner._stage_reframe(_clips(), transcript=None)
        assert built[0] == (9, 16)

        # The second run: the webcam was found, so the gameplay is cropped to
        # the bottom strip — a different shape.
        layouts.append(_layout())
        runner._stage_reframe(_clips(), transcript=None)
        assert built[-1] == (15, 16)

        # The third run: nothing has changed, so the plan is reused.
        count = len(built)
        runner._stage_reframe(_clips(), transcript=None)
        assert len(built) == count


# --------------------------------------------------------------------------
# The webcam report
# --------------------------------------------------------------------------


class TestTheSavedWebcamReport:
    def test_a_failed_report_is_not_reused(
        self, monkeypatch: pytest.MonkeyPatch, initialised_db: int
    ) -> None:
        """A detection that could not run is not an answer.

        The detector could not look. That is not the same as there being no
        webcam, and a job that keeps the failure keeps the absence of a
        webcam for ever.
        """
        runner = _runner()
        runner.workspace.webcam_report.write_text(
            f'{{"version": {REPORT_VERSION}, "failed": true, "unavailable_reason": '
            '"Input timestamp must be monotonically increasing.", '
            '"windows": [[530.0, 560.0]]}',
            encoding="utf-8",
        )
        called: list[Path] = []
        _patch_probe(monkeypatch)

        def fake_detect(source: Path, **kwargs: Any) -> WebcamReport:
            called.append(source)
            return WebcamReport(source_width=WIDTH, source_height=HEIGHT)

        monkeypatch.setattr(runner_module, "detect_webcam", fake_detect)

        report = runner._detect_webcam(Path("source.mp4"), windows=[(530.0, 560.0)])

        assert called
        assert report.failed is False

    def test_a_negative_report_is_reused(
        self, monkeypatch: pytest.MonkeyPatch, initialised_db: int
    ) -> None:
        """'There is no webcam in this footage' is an answer, and it is kept."""

        runner = _runner()
        runner.workspace.webcam_report.write_text(
            f'{{"version": {REPORT_VERSION}, "failed": false, "unavailable_reason": '
            '"no faces were found", "windows": [[530.0, 560.0]]}',
            encoding="utf-8",
        )

        def fake_detect(source: Path, **kwargs: Any) -> WebcamReport:
            raise AssertionError("the detection must not run again")

        monkeypatch.setattr(runner_module, "detect_webcam", fake_detect)

        report = runner._detect_webcam(Path("source.mp4"), windows=[(530.0, 560.0)])

        assert report.unavailable_reason == "no faces were found"

    def test_a_report_made_for_other_windows_is_not_reused(
        self, monkeypatch: pytest.MonkeyPatch, initialised_db: int
    ) -> None:
        """A report is an answer about the stretches that were looked at."""

        runner = _runner()
        runner.workspace.webcam_report.write_text(
            '{"failed": false, "unavailable_reason": "no faces were found", '
            '"windows": [[1.0, 2.0]]}',
            encoding="utf-8",
        )
        called: list[Path] = []
        _patch_probe(monkeypatch)

        def fake_detect(source: Path, **kwargs: Any) -> WebcamReport:
            called.append(source)
            return WebcamReport(source_width=WIDTH, source_height=HEIGHT)

        monkeypatch.setattr(runner_module, "detect_webcam", fake_detect)

        runner._detect_webcam(Path("source.mp4"), windows=[(530.0, 560.0)])

        assert called

    def test_a_report_for_the_same_windows_is_reused(
        self, monkeypatch: pytest.MonkeyPatch, initialised_db: int
    ) -> None:
        """The same stretches, asked for again, do not pay for the detection.

        A clip's own end time is whatever the detector measured — it can be
        ``1303.9599999999998`` — and the report is written down with its
        times rounded. The two are the same moment, and the report is an
        answer about it.
        """

        runner = _runner()
        runner.workspace.webcam_report.write_text(
            f'{{"version": {REPORT_VERSION}, "failed": false, "unavailable_reason": '
            '"no faces were found", "windows": [[530.31, 562.88], '
            "[1273.12, 1303.96]]}",
            encoding="utf-8",
        )

        def fake_detect(source: Path, **kwargs: Any) -> WebcamReport:
            raise AssertionError("the detection must not run again")

        monkeypatch.setattr(runner_module, "detect_webcam", fake_detect)

        report = runner._detect_webcam(
            Path("source.mp4"),
            windows=[(530.31, 562.88), (1273.12, 1303.9599999999998)],
        )

        assert report.unavailable_reason == "no faces were found"

    def test_a_report_written_by_another_version_is_not_reused(
        self, monkeypatch: pytest.MonkeyPatch, initialised_db: int
    ) -> None:
        """An older report cannot say whether the detection failed.

        The format that can is the current one; an older one is detected
        again rather than believed.
        """
        runner = _runner()
        runner.workspace.webcam_report.write_text(
            '{"unavailable_reason": "Input timestamp must be monotonically '
            'increasing.", "windows": [[530.0, 560.0]]}',
            encoding="utf-8",
        )
        called: list[Path] = []
        _patch_probe(monkeypatch)

        def fake_detect(source: Path, **kwargs: Any) -> WebcamReport:
            called.append(source)
            return WebcamReport(source_width=WIDTH, source_height=HEIGHT)

        monkeypatch.setattr(runner_module, "detect_webcam", fake_detect)

        runner._detect_webcam(Path("source.mp4"), windows=[(530.0, 560.0)])

        assert called

    def test_the_report_says_which_version_it_is(self) -> None:
        from autoclip.pipeline.reframe.webcam import REPORT_VERSION

        report = WebcamReport()

        assert report.version == REPORT_VERSION
        assert report.to_dict()["version"] == REPORT_VERSION


# --------------------------------------------------------------------------
# The re-export path
# --------------------------------------------------------------------------


class TestTheReExportPath:
    def test_a_re_export_does_not_stretch_a_plan_built_for_another_shape(
        self, initialised_db: int
    ) -> None:
        """A saved plan is a crop *for an aspect ratio*.

        A stacked layout leaves the bottom of the frame for gameplay, and
        that area is not the whole 9:16. A plan made for it cannot be
        stretched into a 9:16 frame, so a re-export at 9:16 uses a crop of
        its own shape instead.
        """
        from autoclip.api.clips import _crop_path_for
        from autoclip.pipeline.runner import JobWorkspace

        runner = _runner()
        clip = _clips()[0]
        source = runner.source
        # The shape a stacked layout's gameplay area has: 15:16.
        stacked = centre_crop(WIDTH, HEIGHT, 30.0, aspect_w=15, aspect_h=16)
        stacked.save(JobWorkspace(runner.job.id).crop_path(clip.id))

        chosen = _crop_path_for(JobWorkspace(runner.job.id), clip, source, "9:16")

        segment = chosen.segments[0]
        assert segment.width / segment.height == pytest.approx(9 / 16, rel=0.02)

    def test_a_re_export_uses_the_plan_when_the_shape_is_the_same(
        self, initialised_db: int
    ) -> None:
        from autoclip.api.clips import _crop_path_for
        from autoclip.pipeline.runner import JobWorkspace

        runner = _runner()
        clip = _clips()[0]
        saved = centre_crop(WIDTH, HEIGHT, 30.0, aspect_w=9, aspect_h=16)
        saved.save(JobWorkspace(runner.job.id).crop_path(clip.id))

        chosen = _crop_path_for(JobWorkspace(runner.job.id), clip, runner.source, "9:16")

        assert chosen.segments[0].width == saved.segments[0].width


# --------------------------------------------------------------------------
# The order the stretches are asked for
# --------------------------------------------------------------------------


class TestTheOrderTheWindowsAreAskedFor:
    def test_the_detector_is_asked_for_the_windows_in_source_order(
        self, monkeypatch: pytest.MonkeyPatch, initialised_db: int
    ) -> None:
        """The clips are in rank order, and rank is not position.

        A decoder cannot seek backwards, so the stretches are asked for in
        the order they sit in the source.
        """
        runner = _runner()
        asked: list[list[tuple[float, float]]] = []

        def fake_detect(self: Any, source_path: Path, *, windows=None) -> WebcamReport:
            asked.append(list(windows or []))
            return WebcamReport(source_width=WIDTH, source_height=HEIGHT)

        monkeypatch.setattr(runner_module.PipelineRunner, "_detect_webcam", fake_detect)
        monkeypatch.setattr(runner_module.PipelineRunner, "_plan_layout", lambda *a, **k: _layout())
        monkeypatch.setattr(
            runner_module.PipelineRunner,
            "_finish_stage",
            lambda *a, **k: None,
        )
        monkeypatch.setattr(
            runner_module,
            "build_crop_path",
            lambda source, **kwargs: centre_crop(WIDTH, HEIGHT, 30.0),
        )

        runner._stage_reframe(_clips(), transcript=None)

        assert asked
        assert asked[0] == sorted(asked[0])
        assert asked[0] == [(530.31, 562.88), (958.74, 990.41), (1273.12, 1303.96)]
