"""Phase 9 — clip validation tests."""

from __future__ import annotations

import subprocess

import pytest
from autoclip.db import store
from autoclip.db.models import Clip, Job, Source, new_id
from autoclip.pipeline import ffmpeg, validate
from autoclip.pipeline.transcript import Transcript, Word

# --------------------------------------------------------------------------
# Migration
# --------------------------------------------------------------------------


def test_migration_v8_adds_validation_column(initialised_db: int) -> None:
    from autoclip.db.store import connection

    with connection() as conn:
        version = conn.execute("PRAGMA user_version").fetchone()[0]
        columns = {r[1] for r in conn.execute("PRAGMA table_info(clips)").fetchall()}
    assert version >= 8
    assert "validation_json" in columns


# --------------------------------------------------------------------------
# Bounds
# --------------------------------------------------------------------------


def _transcript(seconds: float = 120.0) -> Transcript:
    words = [
        Word(text=f"word{i}", start=i * 0.5, end=i * 0.5 + 0.45) for i in range(int(seconds / 0.5))
    ]
    return Transcript(words=words)


def test_bounds_accept_a_sane_clip() -> None:
    checks = validate.validate_bounds(
        start_s=10.0,
        end_s=40.0,
        start_word=20,
        end_word=80,
        transcript=_transcript(),
        min_duration_s=15.0,
        max_duration_s=60.0,
    )
    assert all(c.ok for c in checks), [c for c in checks if not c.ok]


def test_bounds_reject_short_long_and_inverted_clips() -> None:
    short = validate.validate_bounds(
        start_s=10.0,
        end_s=12.0,
        start_word=20,
        end_word=24,
        transcript=_transcript(),
        min_duration_s=15.0,
        max_duration_s=60.0,
    )
    assert {c.name for c in short if not c.ok} == {"duration_min"}

    long = validate.validate_bounds(
        start_s=0.0,
        end_s=90.0,
        start_word=0,
        end_word=180,
        transcript=_transcript(),
        min_duration_s=15.0,
        max_duration_s=60.0,
    )
    assert {c.name for c in long if not c.ok} == {"duration_max"}

    inverted = validate.validate_bounds(
        start_s=40.0,
        end_s=30.0,
        start_word=80,
        end_word=60,
        transcript=_transcript(),
        min_duration_s=15.0,
        max_duration_s=60.0,
    )
    failing = {c.name for c in inverted if not c.ok}
    assert "duration_positive" in failing
    assert "word_range" in failing


def test_bounds_reject_end_past_transcript() -> None:
    checks = validate.validate_bounds(
        start_s=100.0,
        end_s=130.0,
        start_word=200,
        end_word=240,
        transcript=_transcript(seconds=120.0),
        min_duration_s=15.0,
        max_duration_s=60.0,
    )
    assert "end_in_source" in {c.name for c in checks if not c.ok}


# --------------------------------------------------------------------------
# Media (real ffmpeg)
# --------------------------------------------------------------------------


def _make_video(path, *, seconds: float, size: str, audio: bool = True) -> None:
    command = [
        ffmpeg.ffmpeg_path(),
        "-y",
        "-loglevel",
        "error",
        "-f",
        "lavfi",
        "-i",
        f"testsrc=size={size}:rate=24:duration={seconds}",
    ]
    if audio:
        command += ["-f", "lavfi", "-i", f"sine=frequency=440:duration={seconds}"]
    command += ["-c:v", "libx264", "-pix_fmt", "yuv420p"]
    if audio:
        command += ["-c:a", "aac", "-shortest"]
    command.append(str(path))
    subprocess.run(command, check=True)


def test_validate_media_accepts_a_good_render(tmp_path) -> None:
    path = tmp_path / "good.mp4"
    _make_video(path, seconds=4.0, size="270x480")

    report = validate.validate_media(
        path, expected_duration_s=4.0, expected_size=(270, 480), require_audio=True
    )
    assert report.ok, report.failures()
    assert report.width == 270 and report.height == 480
    assert 3.5 <= report.duration_s <= 4.5


def test_validate_media_catches_wrong_resolution_and_duration(tmp_path) -> None:
    path = tmp_path / "wrong.mp4"
    _make_video(path, seconds=3.0, size="640x360")

    report = validate.validate_media(
        path, expected_duration_s=9.0, expected_size=(270, 480), require_audio=True
    )
    failing = {c.name for c in report.checks if not c.ok}
    assert {"resolution", "duration"} <= failing


def test_validate_media_catches_missing_audio(tmp_path) -> None:
    path = tmp_path / "silent.mp4"
    _make_video(path, seconds=2.0, size="270x480", audio=False)

    report = validate.validate_media(
        path, expected_duration_s=2.0, expected_size=(270, 480), require_audio=True
    )
    assert "has_audio" in {c.name for c in report.checks if not c.ok}


def test_validate_media_catches_silent_track(tmp_path) -> None:
    path = tmp_path / "quiet.mp4"
    subprocess.run(
        [
            ffmpeg.ffmpeg_path(),
            "-y",
            "-loglevel",
            "error",
            "-f",
            "lavfi",
            "-i",
            "testsrc=size=270x480:rate=24:duration=2",
            "-f",
            "lavfi",
            "-i",
            "anullsrc=r=48000:cl=stereo",
            "-t",
            "2",
            "-c:v",
            "libx264",
            "-pix_fmt",
            "yuv420p",
            "-c:a",
            "aac",
            str(path),
        ],
        check=True,
    )

    report = validate.validate_media(
        path, expected_duration_s=2.0, expected_size=(270, 480), require_audio=True
    )
    assert "audio_not_silent" in {c.name for c in report.checks if not c.ok}


def test_validate_media_missing_file(tmp_path) -> None:
    report = validate.validate_media(
        tmp_path / "nope.mp4", expected_duration_s=1.0, require_audio=True
    )
    assert not report.ok
    assert "file_exists" in {c.name for c in report.checks if not c.ok}


# --------------------------------------------------------------------------
# Persistence and publishing gate
# --------------------------------------------------------------------------


def _seed_clip() -> tuple[Source, Job, Clip]:
    source = Source(
        id=new_id(),
        type="upload",
        path="C:/videos/source.mp4",
        title="source",
        duration_s=120.0,
    )
    store.create_source(source)
    job = Job(id=new_id(), source_id=source.id, status="done")
    store.create_job(job)
    clip = Clip(id=new_id(), job_id=job.id, start_s=1.0, end_s=20.0, rank=1)
    store.replace_clips(job.id, [clip])
    return source, job, clip


def test_validation_report_round_trips(initialised_db: int) -> None:
    _, _, clip = _seed_clip()
    store.update_clip(
        clip.id,
        status="invalid",
        validation={"ok": False, "checks": [{"name": "duration", "ok": False, "detail": "x"}]},
    )
    reloaded = store.get_clip(clip.id)
    assert reloaded is not None
    assert reloaded.status == "invalid"
    assert reloaded.validation is not None
    assert reloaded.validation["checks"][0]["name"] == "duration"


def test_invalid_clip_is_not_queued_for_upload(
    initialised_db: int, monkeypatch: pytest.MonkeyPatch
) -> None:
    from autoclip.config import Settings
    from autoclip.db.models import Export
    from autoclip.youtube import oauth, uploads

    _, _, clip = _seed_clip()
    export = Export(id=new_id(), clip_id=clip.id, path="C:/out.mp4")
    store.create_export(export)
    store.update_clip(clip.id, status="invalid")

    settings = Settings()
    settings.youtube.auto_upload = True
    monkeypatch.setattr(oauth, "is_connected", lambda _settings=None: True)

    assert uploads.enqueue_export(export.id, settings) is None

    # A valid clip still queues.
    store.update_clip(clip.id, status="exported")
    queued = uploads.enqueue_export(export.id, settings)
    assert queued is not None and queued.clip_id == clip.id
