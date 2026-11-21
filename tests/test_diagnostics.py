"""M3 — the objective quality diagnostics and the story/action balance.

Two things are being tested here, and both are about honesty:

* the **diagnostics** measure real things and say what they measured.
  There is no score, and no claim that anything will perform well;
* the **balance** is a bias the user controls, measured from real
  signals, and the default changes nothing at all.
"""

from __future__ import annotations

import subprocess
from pathlib import Path

import pytest
from autoclip.db.models import Clip
from autoclip.pipeline import diagnostics, intent
from autoclip.pipeline.reframe.croppath import CropKeyframe, CropPath, CropSegment, FaceRect
from autoclip.pipeline.transcript import Word

# --------------------------------------------------------------------------
# Helpers
# --------------------------------------------------------------------------


def _clip(clip_id: str, start_s: float, end_s: float, score: int = 70) -> Clip:
    return Clip(
        id=clip_id,
        job_id="job1",
        start_s=start_s,
        end_s=end_s,
        rank=1,
        title=clip_id,
        score=score,
    )


def _words(*spans: tuple[float, float]) -> list[Word]:
    return [Word(text=f"w{i}", start=start, end=end) for i, (start, end) in enumerate(spans)]


def _ffmpeg_path() -> str:
    from autoclip.pipeline import ffmpeg

    return ffmpeg.ffmpeg_path()


def _make_video(path: Path, *, seconds: int = 2, with_audio: bool = True) -> Path:
    """A real video file, so the measurements have something to measure."""
    command = [
        _ffmpeg_path(),
        "-hide_banner",
        "-loglevel",
        "error",
        "-y",
        "-f",
        "lavfi",
        "-i",
        f"testsrc2=size=320x240:rate=30:duration={seconds}",
    ]
    if with_audio:
        command += [
            "-f",
            "lavfi",
            "-i",
            f"sine=frequency=440:duration={seconds}",
            "-c:a",
            "aac",
            "-shortest",
        ]
    command += [
        "-c:v",
        "libx264",
        "-pix_fmt",
        "yuv420p",
        str(path),
    ]
    subprocess.run(command, check=True, capture_output=True)
    return path


# --------------------------------------------------------------------------
# The diagnostics
# --------------------------------------------------------------------------


def test_a_report_has_no_score() -> None:
    """A single "quality" number would be invented, so there is none."""
    report = diagnostics.DiagnosticsReport()

    payload = report.to_dict()

    assert "score" not in payload
    assert "quality" not in payload
    assert "rating" not in payload


def test_a_measurement_says_what_it_measured() -> None:
    diagnostic = diagnostics.Diagnostic(
        "resolution",
        "Video resolution",
        ok=True,
        measured="1080x1920",
    )

    payload = diagnostic.to_dict()

    assert payload["measured"] == "1080x1920"
    assert payload["ok"] is True
    assert payload["detail"] == ""


def test_a_problem_is_explained_in_plain_words() -> None:
    diagnostic = diagnostics.Diagnostic(
        "audio_clipping",
        "Audio clipping",
        ok=False,
        measured="2.500% of samples at full scale",
        detail="The sound is being cut off.",
    )

    assert "cut off" in diagnostic.detail


def test_an_unmeasurable_thing_is_not_a_pass() -> None:
    """A measurement that could not be made is not the same as a correct one."""
    diagnostic = diagnostics.Diagnostic(
        "audio_clipping",
        "Audio clipping",
        ok=True,
        measured="not measured",
        available=False,
    )

    assert diagnostic.available is False
    assert diagnostic.to_dict()["available"] is False


def test_a_missing_export_is_reported_rather_than_hidden() -> None:
    report = diagnostics.diagnose_clip(None, clip_id="c1")

    names = {d.name for d in report.diagnostics}
    assert "export_validity" in names
    assert report.ok is False


def test_every_named_measurement_is_present() -> None:
    """The specification lists ten measurements; all ten are here."""
    assert len(diagnostics.MEASUREMENTS) == 10
    for expected in (
        "audio_clipping",
        "caption_timing",
        "crop_safety",
        "duplicate_clips",
        "export_validity",
        "missing_audio",
        "resolution",
        "frame_rate_consistency",
        "black_frames",
        "duration",
    ):
        assert expected in diagnostics.MEASUREMENTS


def test_the_plan_measurements_are_the_ones_that_need_no_file() -> None:
    report = diagnostics.diagnose_clip(
        Path("nowhere.mp4"),
        clip_id="c1",
        words=_words((0.0, 1.0)),
    )

    names = {d.name for d in report.diagnostics}
    for expected in diagnostics.PLAN_MEASUREMENTS:
        assert expected in names
    assert "export_validity" in names


def test_the_words_outside_the_clip_are_reported() -> None:
    report = diagnostics.diagnose_clip(
        None,
        clip_id="c1",
        words=_words((0.0, 1.0), (5.0, 6.0)),
        start_s=0.0,
        end_s=2.0,
    )

    timing = next(d for d in report.diagnostics if d.name == "caption_timing")
    assert timing.ok is False
    assert "outside the clip" in timing.detail


def test_the_words_inside_the_clip_are_fine() -> None:
    report = diagnostics.diagnose_clip(
        None,
        clip_id="c1",
        words=_words((0.0, 1.0), (1.1, 1.9)),
        start_s=0.0,
        end_s=2.0,
    )

    timing = next(d for d in report.diagnostics if d.name == "caption_timing")
    assert timing.ok is True


def test_overlapping_captions_are_reported() -> None:
    report = diagnostics.diagnose_clip(
        None,
        clip_id="c1",
        words=_words((0.0, 1.0), (0.5, 1.5)),
        start_s=0.0,
        end_s=2.0,
    )

    timing = next(d for d in report.diagnostics if d.name == "caption_timing")
    assert timing.ok is False
    assert "overlap" in timing.detail


# -- crop safety ------------------------------------------------------------


def _crop(
    *,
    x: int = 0,
    y: int = 0,
    width: int = 320,
    height: int = 240,
    faces: list[FaceRect] | None = None,
    keyframe_t: float = 0.0,
) -> CropPath:
    return CropPath(
        source_width=320,
        source_height=240,
        segments=[
            CropSegment(
                start_s=0.0,
                end_s=2.0,
                width=width,
                height=height,
                keyframes=[CropKeyframe(t=keyframe_t, x=x, y=y)],
            )
        ],
        faces=faces or [],
    )


def test_a_crop_that_stays_inside_the_frame_is_safe() -> None:
    report = diagnostics.diagnose_clip(
        None,
        clip_id="c1",
        crop_path=_crop(),
        source_size=(320, 240),
    )

    safety = next(d for d in report.diagnostics if d.name == "crop_safety")
    assert safety.ok is True


def test_a_crop_that_leaves_the_frame_is_reported() -> None:
    report = diagnostics.diagnose_clip(
        None,
        clip_id="c1",
        crop_path=_crop(x=300, width=100),
        source_size=(320, 240),
    )

    safety = next(d for d in report.diagnostics if d.name == "crop_safety")
    assert safety.ok is False
    assert "leaves the frame" in safety.detail


def test_a_crop_that_cuts_through_the_face_is_reported() -> None:
    report = diagnostics.diagnose_clip(
        None,
        clip_id="c1",
        crop_path=_crop(
            x=30,
            y=30,
            width=100,
            height=100,
            faces=[FaceRect(t=0.0, x=10.0, y=10.0, width=50.0, height=50.0)],
        ),
        source_size=(320, 240),
    )

    safety = next(d for d in report.diagnostics if d.name == "crop_safety")
    assert safety.ok is False
    assert "face" in safety.detail


def test_a_crop_that_holds_the_whole_face_is_safe() -> None:
    report = diagnostics.diagnose_clip(
        None,
        clip_id="c1",
        crop_path=_crop(
            x=0,
            y=0,
            width=320,
            height=240,
            faces=[FaceRect(t=0.0, x=10.0, y=10.0, width=50.0, height=50.0)],
        ),
        source_size=(320, 240),
    )

    safety = next(d for d in report.diagnostics if d.name == "crop_safety")
    assert safety.ok is True


def test_a_face_from_another_moment_is_not_compared_with_this_crop() -> None:
    """A face measured elsewhere says nothing about this crop.

    The crop plan for a clip is planned around the faces in *that* clip, at
    the times the crop is at. A rectangle measured at another moment — the
    webcam region the detector found once for the whole source, for
    instance — must not be compared with it: that is how a clip with no
    face in it at all gets reported as cutting through one.
    """
    report = diagnostics.diagnose_clip(
        None,
        clip_id="c1",
        crop_path=_crop(
            x=30,
            y=0,
            width=100,
            height=240,
            keyframe_t=10.0,
            faces=[FaceRect(t=0.0, x=0.0, y=20.0, width=80.0, height=120.0)],
        ),
        source_size=(320, 240),
    )

    safety = next(d for d in report.diagnostics if d.name == "crop_safety")
    assert safety.ok is True
    assert "face" not in safety.detail


def test_a_clip_with_no_face_is_not_reported_as_cutting_one() -> None:
    report = diagnostics.diagnose_clip(
        None,
        clip_id="c1",
        crop_path=_crop(x=30, y=0, width=100, height=240),
        source_size=(320, 240),
    )

    safety = next(d for d in report.diagnostics if d.name == "crop_safety")
    assert safety.ok is True
    assert "no face tracked" in safety.measured


def test_the_face_is_matched_to_the_crop_by_time() -> None:
    """The face that matters is the one at the keyframe's own moment.

    The face is clear of the crop at t=0 and inside it at t=1.0. A check
    that ignored time would have to call one of them wrong; the right
    answer is that the crop at t=1.0 is fine and the crop at t=0 is not.
    """
    path = CropPath(
        source_width=320,
        source_height=240,
        segments=[
            CropSegment(
                start_s=0.0,
                end_s=2.0,
                width=100,
                height=240,
                keyframes=[CropKeyframe(t=1.0, x=100, y=0)],
            )
        ],
        faces=[FaceRect(t=1.0, x=120.0, y=20.0, width=50.0, height=120.0)],
    )

    report = diagnostics.diagnose_clip(
        None,
        clip_id="c1",
        crop_path=path,
        source_size=(320, 240),
    )

    safety = next(d for d in report.diagnostics if d.name == "crop_safety")
    assert safety.ok is True
    assert "1 face(s) tracked" in safety.measured


def test_a_crop_that_leaves_the_frame_is_reported_even_without_a_face() -> None:
    """An older crop plan, with no faces recorded, still gets checked."""
    report = diagnostics.diagnose_clip(
        None,
        clip_id="c1",
        crop_path=_crop(x=300, width=100),
        source_size=(320, 240),
    )

    safety = next(d for d in report.diagnostics if d.name == "crop_safety")
    assert safety.ok is False
    assert "leaves the frame" in safety.detail


def test_a_crop_planned_for_another_frame_size_is_reported() -> None:
    report = diagnostics.diagnose_clip(
        None,
        clip_id="c1",
        crop_path=_crop(),
        source_size=(1920, 1080),
    )

    safety = next(d for d in report.diagnostics if d.name == "crop_safety")
    assert safety.ok is False
    assert "different frame size" in safety.detail


# -- duplicate clips --------------------------------------------------------


def test_two_clips_that_overlap_are_duplicates() -> None:
    clips = [
        _clip("c1", 0.0, 30.0),
        _clip("c2", 10.0, 40.0),
    ]

    pairs = diagnostics.duplicate_clips(clips)

    assert len(pairs) == 1
    assert pairs[0][0] == "c1"
    assert pairs[0][1] == "c2"
    assert pairs[0][2] == pytest.approx(20.0 / 30.0, abs=0.01)


def test_two_clips_that_do_not_overlap_are_not_duplicates() -> None:
    clips = [
        _clip("c1", 0.0, 30.0),
        _clip("c2", 40.0, 70.0),
    ]

    assert diagnostics.duplicate_clips(clips) == []


def test_a_small_overlap_is_not_a_duplicate() -> None:
    clips = [
        _clip("c1", 0.0, 60.0),
        _clip("c2", 55.0, 70.0),
    ]

    assert diagnostics.duplicate_clips(clips) == []


def test_a_duplicate_is_reported_on_the_clip() -> None:
    clips = [
        _clip("c1", 0.0, 30.0),
        _clip("c2", 10.0, 40.0),
    ]

    report = diagnostics.diagnose_clip(None, clip_id="c1", clips=clips)

    duplicate = next(d for d in report.diagnostics if d.name == "duplicate_clips")
    assert duplicate.ok is False
    assert "overlaps another one" in duplicate.detail


# -- the measurements on a real file ----------------------------------------


@pytest.mark.slow
def test_a_real_render_is_measured(tmp_path: Path) -> None:
    """The measurements run against a real ffmpeg render."""
    video = _make_video(tmp_path / "clip.mp4", seconds=2)

    report = diagnostics.diagnose_clip(
        video,
        clip_id="c1",
        start_s=0.0,
        end_s=2.0,
        expected_size=(320, 240),
    )

    by_name = {d.name: d for d in report.diagnostics}
    assert by_name["export_validity"].ok is True
    assert by_name["resolution"].ok is True
    assert by_name["resolution"].measured == "320x240"
    assert by_name["duration"].ok is True
    assert by_name["missing_audio"].ok is True
    # Every measurement in the list is reported, even the ones that
    # could not be made — an absent measurement would read like a pass.
    assert set(diagnostics.MEASUREMENTS) == set(by_name)
    # The clipping measurement ran; whether it passed is the render's
    # business, but it must not be missing.
    assert by_name["audio_clipping"].available is True


@pytest.mark.slow
def test_a_silent_file_is_reported_as_missing_audio(tmp_path: Path) -> None:
    video = _make_video(tmp_path / "silent.mp4", seconds=1, with_audio=False)

    report = diagnostics.diagnose_clip(
        video,
        clip_id="c1",
        start_s=0.0,
        end_s=1.0,
        require_audio=True,
    )

    missing = next(d for d in report.diagnostics if d.name == "missing_audio")
    assert missing.ok is False
    assert "silent" in missing.detail


# --------------------------------------------------------------------------
# The story and gameplay balance
# --------------------------------------------------------------------------


def test_the_default_changes_nothing() -> None:
    """A user who never touches the setting gets the old behaviour."""
    for speech in (0.0, 0.3, 0.7, 1.0):
        for cuts in (0.0, 2.0, 8.0, 30.0):
            score, _ = intent.adjust_score(
                70,
                speech_density=speech,
                cuts_per_minute=cuts,
                story_density=0.5,
                highlight_style="auto",
            )
            assert score == 70


def test_a_story_preference_lifts_a_talking_clip() -> None:
    score, character = intent.adjust_score(
        70,
        speech_density=1.0,
        cuts_per_minute=0.0,
        story_density=0.75,
    )

    assert score > 70
    assert character.story == 1.0


def test_a_story_preference_pushes_an_action_clip_down() -> None:
    score, _ = intent.adjust_score(
        70,
        speech_density=0.0,
        cuts_per_minute=20.0,
        story_density=0.75,
    )

    assert score < 70


def test_an_action_preference_lifts_an_action_clip() -> None:
    score, _ = intent.adjust_score(
        70,
        speech_density=0.0,
        cuts_per_minute=20.0,
        story_density=0.25,
    )

    assert score > 70


def test_the_adjustment_is_bounded() -> None:
    """The model's own judgement is never thrown away."""
    for density in (0.0, 0.25, 0.5, 0.75, 1.0):
        for speech in (0.0, 0.5, 1.0):
            score, _ = intent.adjust_score(
                100,
                speech_density=speech,
                cuts_per_minute=0.0,
                story_density=density,
            )
            assert 0 <= score <= 100
            assert abs(score - 100) <= intent.STORY_BIAS


def test_the_style_switch_overrides_the_density() -> None:
    assert intent.effective_density(story_density=0.1, highlight_style="story") == 0.75
    assert intent.effective_density(story_density=0.9, highlight_style="action") == 0.25
    assert intent.effective_density(story_density=0.9, highlight_style="auto") == 0.9


def test_the_style_switch_wins_over_the_density() -> None:
    story, _ = intent.adjust_score(
        70,
        speech_density=1.0,
        cuts_per_minute=0.0,
        story_density=0.1,
        highlight_style="story",
    )
    auto, _ = intent.adjust_score(
        70,
        speech_density=1.0,
        cuts_per_minute=0.0,
        story_density=0.1,
        highlight_style="auto",
    )

    assert story != auto


def test_a_clip_with_no_signals_is_untouched() -> None:
    """A silent clip with no cuts has no character to bias."""
    score, character = intent.adjust_score(
        70,
        speech_density=0.0,
        cuts_per_minute=0.0,
        story_density=1.0,
    )

    assert score == 70
    assert character.balance == 0.5


def test_the_instruction_names_the_kind_of_moment() -> None:
    story = intent.style_instruction(story_density=0.5, highlight_style="story")
    action = intent.style_instruction(story_density=0.5, highlight_style="action")
    neither = intent.style_instruction(story_density=0.5, highlight_style="auto")

    assert "STORY" in story
    assert "ACTION" in action
    assert neither == ""


def test_the_instruction_mentions_the_balance_when_it_is_not_the_default() -> None:
    text = intent.style_instruction(story_density=0.8, highlight_style="auto")

    assert text
    assert "story" in text.lower()
