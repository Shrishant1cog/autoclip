"""M1 — the music library, the measurements, the licence and the choice.

Three things are being tested:

* the library is an **index**: it never copies, moves or deletes the user's
  music;
* the **licence** is a real gate, and the states behave the way the
  specification says they do;
* the **choice** follows one rule — a manual choice wins, a model's proposal
  is checked against facts, and the deterministic scorer has the last word.

The analysis test runs the real measurement on a generated WAV: ffmpeg is a
hard dependency of the project, so the measurement is part of what the
project promises to do, not an optional extra.
"""

from __future__ import annotations

import math
import wave
from pathlib import Path

import numpy as np
import pytest
from autoclip.music import analysis as music_analysis
from autoclip.music import library as music_library
from autoclip.music import selection as music_selection
from autoclip.music import store as music_store
from autoclip.music.licensing import LicenseRecord, LicenseState
from autoclip.pipeline.speech_timeline import SpeechInterval, SpeechTimeline
from fastapi.testclient import TestClient

# --------------------------------------------------------------------------
# Helpers
# --------------------------------------------------------------------------


def _tone(
    *,
    duration_s: float = 1.0,
    frequency: float = 220.0,
    amplitude: float = 0.5,
    sample_rate: int = 22_050,
) -> np.ndarray:
    count = int(duration_s * sample_rate)
    times = np.arange(count, dtype=np.float32) / sample_rate
    return (amplitude * np.sin(2 * np.pi * frequency * times)).astype(np.float32)


def _write_wav(path: Path, samples: np.ndarray, sample_rate: int = 22_050) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    pcm = np.clip(samples, -1.0, 1.0)
    data = (pcm * 32767.0).astype("<i2").tobytes()
    with wave.open(str(path), "wb") as handle:
        handle.setnchannels(1)
        handle.setsampwidth(2)
        handle.setframerate(sample_rate)
        handle.writeframes(data)
    return path


def _make_folder(tmp_path: Path, name: str = "music") -> Path:
    folder = tmp_path / name
    folder.mkdir(parents=True, exist_ok=True)
    (folder / "bed.mp3").write_bytes(b"not really audio")
    (folder / "loop.WAV").write_bytes(b"not really audio either")
    (folder / "notes.txt").write_text("not audio")
    return folder


def _confirm(track_id: str, state: str = LicenseState.USER_CONFIRMED) -> None:
    music_store.set_license(
        LicenseRecord(track_id=track_id, state=state, source="test", evidence="A fixture.")
    )


# --------------------------------------------------------------------------
# The library is an index
# --------------------------------------------------------------------------


def test_a_scan_indexes_files_without_touching_them(tmp_path: Path, initialised_db: int):
    """AutoClip reads the user's music; it never moves or rewrites it."""
    folder = _make_folder(tmp_path)
    before = {
        path.name: (path.read_bytes(), path.stat().st_mtime)
        for path in folder.iterdir()
        if path.is_file()
    }

    report = music_library.scan(folder=folder)

    assert report.found == 2
    assert report.added == 2

    after = {
        path.name: (path.read_bytes(), path.stat().st_mtime)
        for path in folder.iterdir()
        if path.is_file()
    }
    assert after == before


def test_a_scan_ignores_files_that_are_not_audio(tmp_path: Path, initialised_db: int):
    folder = _make_folder(tmp_path)
    music_library.scan(folder=folder)
    names = {track.name for track in music_store.list_tracks()}
    assert "notes.txt" not in names


def test_a_track_id_is_stable_across_scans(tmp_path: Path, initialised_db: int):
    """The licence hangs off the id, so a re-scan must not orphan it."""
    folder = _make_folder(tmp_path)
    music_library.scan(folder=folder)

    track = next(t for t in music_store.list_tracks() if t.name == "bed.mp3")
    _confirm(track.id)

    music_library.scan(folder=folder)

    again = music_store.get_track(track.id)
    assert again is not None
    assert music_store.get_license(track.id).state == LicenseState.USER_CONFIRMED


def test_removing_a_track_from_the_library_does_not_delete_the_file(
    tmp_path: Path, initialised_db: int
):
    """AutoClip does not own the user's music."""
    folder = _make_folder(tmp_path)
    music_library.scan(folder=folder)
    track = next(t for t in music_store.list_tracks() if t.name == "bed.mp3")

    music_store.delete_track(track.id)

    assert music_store.get_track(track.id) is None
    assert (folder / "bed.mp3").is_file()


def test_a_changed_file_is_re_indexed_and_its_measurement_dropped(
    tmp_path: Path, initialised_db: int
):
    """A stale measurement must never be used for a different file."""
    folder = tmp_path / "music"
    folder.mkdir()
    target = folder / "bed.mp3"
    target.write_bytes(b"first version")

    track = music_store.upsert_track(target)
    music_store.analyse_track(track.id, music_analysis.Analysis(duration_s=10.0, bpm=120.0))
    assert music_store.get_track(track.id).analysis.bpm == 120.0

    target.write_bytes(b"a different file with a different length")
    music_store.upsert_track(target)

    refreshed = music_store.get_track(track.id)
    assert refreshed is not None
    assert refreshed.analysis.bpm == 0.0
    assert refreshed.analysis_at == ""


# --------------------------------------------------------------------------
# Licensing
# --------------------------------------------------------------------------


def test_a_new_track_has_an_unknown_licence(tmp_path: Path, initialised_db: int):
    folder = _make_folder(tmp_path)
    music_library.scan(folder=folder)
    track = music_store.list_tracks()[0]
    assert music_store.get_license(track.id).state == LicenseState.UNKNOWN


def test_an_unknown_licence_blocks_the_export_gate(tmp_path: Path, initialised_db: int):
    from autoclip.music.licensing import LicenseBlocked

    folder = _make_folder(tmp_path)
    music_library.scan(folder=folder)
    track = music_store.list_tracks()[0]

    with pytest.raises(LicenseBlocked) as caught:
        music_library.check_export_allowed(track.id)
    assert caught.value.state == LicenseState.UNKNOWN


def test_a_user_confirmation_allows_the_export_gate(tmp_path: Path, initialised_db: int):
    folder = _make_folder(tmp_path)
    music_library.scan(folder=folder)
    track = music_store.list_tracks()[0]
    _confirm(track.id)

    record = music_library.check_export_allowed(track.id)
    assert record.state == LicenseState.USER_CONFIRMED


def test_a_user_confirmation_warns_that_it_is_not_a_verification(
    tmp_path: Path, initialised_db: int
):
    """The difference between asserting and verifying must stay visible."""
    from autoclip.music.licensing import evaluate

    record = LicenseRecord(track_id="mus_x", state=LicenseState.USER_CONFIRMED)
    verdict = evaluate(record)
    assert verdict.allowed
    assert any("not an independent check" in warning for warning in verdict.warnings)


def test_an_incompatible_licence_blocks_the_export_gate(tmp_path: Path, initialised_db: int):
    from autoclip.music.licensing import LicenseBlocked

    folder = _make_folder(tmp_path)
    music_library.scan(folder=folder)
    track = music_store.list_tracks()[0]
    _confirm(track.id, state=LicenseState.INCOMPATIBLE)

    with pytest.raises(LicenseBlocked):
        music_library.check_export_allowed(track.id)


def test_an_expired_licence_blocks_the_export_gate(tmp_path: Path, initialised_db: int):
    from autoclip.music.licensing import LicenseBlocked

    folder = _make_folder(tmp_path)
    music_library.scan(folder=folder)
    track = music_store.list_tracks()[0]
    _confirm(track.id, state=LicenseState.EXPIRED)

    with pytest.raises(LicenseBlocked):
        music_library.check_export_allowed(track.id)


def test_a_licence_that_expires_in_the_past_blocks_the_export_gate(
    tmp_path: Path, initialised_db: int
):
    """An expiry date in the past blocks, even if the state says otherwise."""
    from autoclip.music.licensing import LicenseBlocked

    folder = _make_folder(tmp_path)
    music_library.scan(folder=folder)
    track = music_store.list_tracks()[0]
    music_store.set_license(
        LicenseRecord(
            track_id=track.id,
            state=LicenseState.USER_CONFIRMED,
            expires_at="2001-01-01",
        )
    )

    with pytest.raises(LicenseBlocked):
        music_library.check_export_allowed(track.id)


def test_a_licence_that_expires_in_the_future_allows_the_export_gate(
    tmp_path: Path, initialised_db: int
):
    folder = _make_folder(tmp_path)
    music_library.scan(folder=folder)
    track = music_store.list_tracks()[0]
    music_store.set_license(
        LicenseRecord(
            track_id=track.id,
            state=LicenseState.USER_CONFIRMED,
            expires_at="2999-01-01",
        )
    )

    music_library.check_export_allowed(track.id)


def test_verified_is_not_a_state_the_user_can_assert(tmp_path: Path, initialised_db: int):
    """Independent verification is not something a user can say about themselves."""
    from autoclip.music.licensing import USER_SETTABLE_STATES

    assert LicenseState.VERIFIED not in USER_SETTABLE_STATES
    assert LicenseState.VERIFIED in LicenseState.all()


# --------------------------------------------------------------------------
# The API
# --------------------------------------------------------------------------


def test_the_api_adds_a_folder_without_copying_anything(tmp_path: Path, initialised_db: int):
    from autoclip.app import create_app

    folder = _make_folder(tmp_path)

    with TestClient(create_app()) as client:
        response = client.post("/api/music/folders", json={"path": str(folder)})

    assert response.status_code == 201
    body = response.json()
    assert body["folder"]["path"] == str(folder.resolve())
    assert body["scan"]["found"] == 2
    # The files are still where they were.
    assert (folder / "bed.mp3").is_file()


def test_the_api_refuses_a_folder_that_does_not_exist(tmp_path: Path, initialised_db: int):
    from autoclip.app import create_app

    with TestClient(create_app()) as client:
        response = client.post("/api/music/folders", json={"path": str(tmp_path / "nope")})

    assert response.status_code == 400


def test_the_api_refuses_to_set_a_verified_licence(tmp_path: Path, initialised_db: int):
    from autoclip.app import create_app

    folder = _make_folder(tmp_path)
    music_library.scan(folder=folder)
    track = music_store.list_tracks()[0]

    with TestClient(create_app()) as client:
        response = client.put(
            f"/api/music/library/{track.id}/licence",
            json={"state": LicenseState.VERIFIED},
        )

    assert response.status_code == 400
    assert "verified" in response.json()["detail"].lower()
    # And nothing was written.
    assert music_store.get_license(track.id).state == LicenseState.UNKNOWN


def test_the_api_records_a_licence(tmp_path: Path, initialised_db: int):
    from autoclip.app import create_app

    folder = _make_folder(tmp_path)
    music_library.scan(folder=folder)
    track = music_store.list_tracks()[0]

    with TestClient(create_app()) as client:
        response = client.put(
            f"/api/music/library/{track.id}/licence",
            json={
                "state": LicenseState.USER_CONFIRMED,
                "source": "Bought on a music store",
                "evidence": "Receipt 12345",
                "attribution": "Artist — Track",
            },
        )
        assert response.status_code == 200
        fetched = client.get(f"/api/music/library/{track.id}/licence")

    assert fetched.json()["state"] == LicenseState.USER_CONFIRMED
    assert fetched.json()["attribution"] == "Artist — Track"


def test_the_library_api_filters_by_licence(tmp_path: Path, initialised_db: int):
    from autoclip.app import create_app

    folder = _make_folder(tmp_path)
    music_library.scan(folder=folder)
    tracks = music_store.list_tracks()
    _confirm(tracks[0].id)

    with TestClient(create_app()) as client:
        confirmed = client.get("/api/music/library?licence=user_confirmed").json()
        unknown = client.get("/api/music/library?licence=unknown").json()

    assert len(confirmed) == 1
    assert confirmed[0]["license"]["state"] == LicenseState.USER_CONFIRMED
    assert len(unknown) == 1
    assert unknown[0]["license"]["state"] == LicenseState.UNKNOWN


def test_the_library_api_reports_whether_a_track_may_be_used(tmp_path: Path, initialised_db: int):
    from autoclip.app import create_app

    folder = _make_folder(tmp_path)
    music_library.scan(folder=folder)
    track = music_store.list_tracks()[0]

    with TestClient(create_app()) as client:
        before = client.get("/api/music/library").json()

    entry = next(item for item in before if item["id"] == track.id)
    assert entry["license_allowed"] is False
    assert entry["license_reason"]


def test_removing_a_track_through_the_api_leaves_the_file_alone(
    tmp_path: Path, initialised_db: int
):
    from autoclip.app import create_app

    folder = _make_folder(tmp_path)
    music_library.scan(folder=folder)
    track = next(t for t in music_store.list_tracks() if t.name == "bed.mp3")

    with TestClient(create_app()) as client:
        response = client.delete(f"/api/music/library/{track.id}")

    assert response.status_code == 204
    assert (folder / "bed.mp3").is_file()
    assert music_store.get_track(track.id) is None


# --------------------------------------------------------------------------
# The preview
# --------------------------------------------------------------------------


def test_the_preview_streams_the_whole_file(tmp_path: Path, initialised_db: int):
    """Without a Range header the browser gets the file."""
    from autoclip.app import create_app

    target = _write_wav(tmp_path / "tone.wav", _tone(duration_s=0.5))
    track = music_store.upsert_track(target)

    with TestClient(create_app()) as client:
        response = client.get(f"/api/music/library/{track.id}/audio")

    assert response.status_code == 200
    assert response.content == target.read_bytes()
    # The browser is told it may ask for a slice.
    assert response.headers["accept-ranges"] == "bytes"


def test_the_preview_answers_a_range_request(tmp_path: Path, initialised_db: int):
    """A Range request gets exactly the bytes that were asked for."""
    from autoclip.app import create_app

    target = _write_wav(tmp_path / "tone.wav", _tone(duration_s=0.5))
    track = music_store.upsert_track(target)
    whole = target.read_bytes()

    with TestClient(create_app()) as client:
        response = client.get(
            f"/api/music/library/{track.id}/audio",
            headers={"Range": "bytes=0-99"},
        )

    assert response.status_code == 206
    assert response.content == whole[:100]
    assert response.headers["content-range"] == f"bytes 0-99/{len(whole)}"
    assert response.headers["content-length"] == "100"


def test_the_preview_answers_a_suffix_range(tmp_path: Path, initialised_db: int):
    """``bytes=-100`` means "the last hundred bytes"."""
    from autoclip.app import create_app

    target = _write_wav(tmp_path / "tone.wav", _tone(duration_s=0.5))
    track = music_store.upsert_track(target)
    whole = target.read_bytes()

    with TestClient(create_app()) as client:
        response = client.get(
            f"/api/music/library/{track.id}/audio",
            headers={"Range": "bytes=-100"},
        )

    assert response.status_code == 206
    assert response.content == whole[-100:]
    assert (
        response.headers["content-range"]
        == f"bytes {len(whole) - 100}-{len(whole) - 1}/{len(whole)}"
    )


def test_the_preview_refuses_a_range_that_is_not_there(tmp_path: Path, initialised_db: int):
    """A range past the end of the file is a 416, not a silent full read."""
    from autoclip.app import create_app

    target = _write_wav(tmp_path / "tone.wav", _tone(duration_s=0.5))
    track = music_store.upsert_track(target)

    with TestClient(create_app()) as client:
        response = client.get(
            f"/api/music/library/{track.id}/audio",
            headers={"Range": "bytes=99999999-"},
        )

    assert response.status_code == 416


def test_the_preview_of_a_track_that_is_not_indexed_is_a_404(tmp_path: Path, initialised_db: int):
    from autoclip.app import create_app

    with TestClient(create_app()) as client:
        response = client.get("/api/music/library/mus_does_not_exist/audio")

    assert response.status_code == 404


def test_the_preview_of_a_file_that_has_gone_is_a_404(tmp_path: Path, initialised_db: int):
    """The index can outlive the file; the route says so rather than crashing."""
    from autoclip.app import create_app

    target = _write_wav(tmp_path / "tone.wav", _tone(duration_s=0.5))
    track = music_store.upsert_track(target)
    target.unlink()

    with TestClient(create_app()) as client:
        response = client.get(f"/api/music/library/{track.id}/audio")

    assert response.status_code == 404


# --------------------------------------------------------------------------
# The ducking envelope
# --------------------------------------------------------------------------


def _job_with_timeline(intervals: list[SpeechInterval], duration_s: float = 10.0) -> str:
    """A finished job with a speech timeline on disk."""
    from autoclip.db import store
    from autoclip.db.models import Job, Source, new_id
    from autoclip.paths import job_work_dir

    source_id = new_id()
    store.create_source(Source(id=source_id, type="upload", path="clip.mp4"))
    job_id = new_id()
    store.create_job(Job(id=job_id, source_id=source_id))
    timeline = SpeechTimeline(intervals=intervals, duration_s=duration_s, detector="test")
    work = job_work_dir(job_id)
    work.mkdir(parents=True, exist_ok=True)
    timeline.save(work / "speech_timeline.json")
    return job_id


def test_the_envelope_route_draws_the_timeline(tmp_path: Path, initialised_db: int):
    """The preview is drawn from the same timeline the export uses."""
    from autoclip.app import create_app

    job_id = _job_with_timeline([SpeechInterval(start_ms=1000, end_ms=2000)])

    with TestClient(create_app()) as client:
        response = client.get(f"/api/music/envelope?job_id={job_id}")

    assert response.status_code == 200
    body = response.json()
    assert body["job_id"] == job_id
    assert len(body["intervals"]) == 1
    assert body["intervals"][0]["start_ms"] == 1000
    assert body["points"]
    # The envelope dips under the speech and comes back up.
    gains = [point["gain"] for point in body["points"]]
    assert min(gains) < max(gains)


def test_the_envelope_route_needs_a_job(tmp_path: Path, initialised_db: int):
    from autoclip.app import create_app

    with TestClient(create_app()) as client:
        assert client.get("/api/music/envelope").status_code == 400
        assert client.get("/api/music/envelope?job_id=job_nope").status_code == 404


def test_the_envelope_route_says_when_there_is_no_timeline(tmp_path: Path, initialised_db: int):
    """A job that has not been processed yet has nothing to draw."""
    from autoclip.app import create_app
    from autoclip.db import store
    from autoclip.db.models import Job, Source, new_id

    source_id = new_id()
    store.create_source(Source(id=source_id, type="upload", path="clip.mp4"))
    job_id = new_id()
    store.create_job(Job(id=job_id, source_id=source_id))

    with TestClient(create_app()) as client:
        response = client.get(f"/api/music/envelope?job_id={job_id}")

    assert response.status_code == 404
    assert "speech timeline" in response.json()["detail"].lower()


# --------------------------------------------------------------------------
# The measurement
# --------------------------------------------------------------------------


def test_a_track_is_measured_locally(tmp_path: Path, initialised_db: int):
    """The real measurement, on a real file."""
    target = _write_wav(tmp_path / "tone.wav", _tone(duration_s=1.0, amplitude=0.6))
    track = music_store.upsert_track(target)

    measured = music_library.analyse(track.id)

    assert measured.analysis.duration_s == pytest.approx(1.0, abs=0.05)
    assert measured.analysis.sample_rate == music_analysis.ANALYSIS_RATE
    assert 0.0 <= measured.analysis.energy <= 1.0
    assert measured.analysis.mood in music_analysis.MOODS
    assert measured.analysis_at
    assert measured.duration_s == pytest.approx(1.0, abs=0.05)


def test_a_mono_file_is_measured_at_its_real_duration(tmp_path: Path, initialised_db: int):
    """A mono file must not be measured as if half of it were missing."""
    target = _write_wav(tmp_path / "tone.wav", _tone(duration_s=2.0, amplitude=0.6))
    track = music_store.upsert_track(target)

    measured = music_library.analyse(track.id)

    assert measured.analysis.duration_s == pytest.approx(2.0, abs=0.05)
    # A mono source has no stereo width, and the measurement says so.
    assert measured.analysis.stereo_width == pytest.approx(0.0, abs=0.001)


def test_the_measurement_is_deterministic(tmp_path: Path, initialised_db: int):
    """The same file always produces the same numbers."""
    target = _write_wav(tmp_path / "tone.wav", _tone(duration_s=1.0, amplitude=0.6))

    first = music_analysis.analyze_track(target)
    second = music_analysis.analyze_track(target)

    assert first.to_dict() == second.to_dict()


def test_a_measurement_is_cached_against_the_file(
    tmp_path: Path, initialised_db: int, monkeypatch: pytest.MonkeyPatch
):
    """An unchanged file is not measured twice."""
    target = _write_wav(tmp_path / "tone.wav", _tone(duration_s=1.0, amplitude=0.6))
    track = music_store.upsert_track(target)

    music_library.analyse(track.id)

    calls: list[Path] = []
    original = music_analysis.analyze_track

    def counting(path: Path, **kwargs):
        calls.append(Path(path))
        return original(path, **kwargs)

    monkeypatch.setattr(music_library, "analyze_track", counting)

    music_library.analyse(track.id)

    assert calls == []


def test_a_changed_file_is_measured_again(
    tmp_path: Path, initialised_db: int, monkeypatch: pytest.MonkeyPatch
):
    """A file that changed is measured again, even though the id is the same."""
    target = _write_wav(tmp_path / "tone.wav", _tone(duration_s=1.0, amplitude=0.6))
    track = music_store.upsert_track(target)
    music_library.analyse(track.id)

    # Rewrite the file so its size and mtime differ from the cached ones.
    _write_wav(target, _tone(duration_s=1.5, amplitude=0.6))
    music_store.upsert_track(target)

    calls: list[Path] = []
    original = music_analysis.analyze_track

    def counting(path: Path, **kwargs):
        calls.append(Path(path))
        return original(path, **kwargs)

    monkeypatch.setattr(music_library, "analyze_track", counting)

    music_library.analyse(track.id)

    assert len(calls) == 1


def test_a_file_that_cannot_be_decoded_says_so(tmp_path: Path, initialised_db: int):
    target = tmp_path / "broken.mp3"
    target.write_bytes(b"this is not audio")
    track = music_store.upsert_track(target)

    with pytest.raises(music_analysis.AnalysisError):
        music_library.analyse(track.id)


def test_the_mood_rules_are_explainable():
    """Every mood has a score, and the rules are the documented ones."""
    mood, scores = music_analysis.classify_mood(
        bpm=120.0, energy=0.8, centroid_hz=2000.0, percussive_ratio=0.6
    )
    assert mood in music_analysis.MOODS
    assert set(scores) == set(music_analysis.MOODS)
    assert scores[mood] == max(scores.values())


def test_a_slow_quiet_track_is_calm():
    mood, _ = music_analysis.classify_mood(
        bpm=70.0, energy=0.1, centroid_hz=600.0, percussive_ratio=0.1
    )
    assert mood == "calm"


def test_a_fast_loud_track_is_energetic():
    mood, _ = music_analysis.classify_mood(
        bpm=150.0, energy=0.9, centroid_hz=3000.0, percussive_ratio=0.7
    )
    assert mood == "energetic"


# --------------------------------------------------------------------------
# The choice
# --------------------------------------------------------------------------


def _two_tracks(tmp_path: Path) -> tuple[str, str]:
    folder = tmp_path / "music"
    folder.mkdir()
    first = folder / "calm.mp3"
    second = folder / "loud.mp3"
    first.write_bytes(b"a")
    second.write_bytes(b"b")
    music_store.upsert_track(first)
    music_store.upsert_track(second)
    one = next(t for t in music_store.list_tracks() if t.name == "calm.mp3")
    two = next(t for t in music_store.list_tracks() if t.name == "loud.mp3")
    _confirm(one.id)
    _confirm(two.id)
    return one.id, two.id


def test_a_manual_choice_wins_and_no_model_is_consulted(tmp_path: Path, initialised_db: int):
    first, second = _two_tracks(tmp_path)

    def proposer(context):
        raise AssertionError("the model must not be consulted for a manual choice")

    selection = music_selection.select_track(
        music_selection.ClipContext(clip_id="c1", duration_s=30.0),
        proposer=proposer,
        user_choice=second,
    )

    assert selection is not None
    assert selection.track_id == second
    assert selection.source == "user"


def test_a_proposal_that_names_a_usable_track_is_used(tmp_path: Path, initialised_db: int):
    first, second = _two_tracks(tmp_path)

    selection = music_selection.select_track(
        music_selection.ClipContext(clip_id="c1", duration_s=30.0),
        proposer=lambda context: f'{{"track_id": "{second}", "reason": "It fits."}}',
    )

    assert selection is not None
    assert selection.track_id == second
    assert selection.source == "ai"
    assert selection.reason == "It fits."


def test_a_proposal_that_names_an_unusable_track_is_ignored(tmp_path: Path, initialised_db: int):
    """A track the user may not publish is not a candidate, whatever the model says."""
    first, second = _two_tracks(tmp_path)
    music_store.set_license(LicenseRecord(track_id=second, state=LicenseState.INCOMPATIBLE))

    selection = music_selection.select_track(
        music_selection.ClipContext(clip_id="c1", duration_s=30.0),
        proposer=lambda context: f'{{"track_id": "{second}"}}',
    )

    assert selection is not None
    assert selection.track_id == first
    assert selection.source == "deterministic"


def test_a_proposal_that_names_nothing_falls_back_to_the_scorer(
    tmp_path: Path, initialised_db: int
):
    first, _ = _two_tracks(tmp_path)

    selection = music_selection.select_track(
        music_selection.ClipContext(clip_id="c1", duration_s=30.0),
        proposer=lambda context: "I have no idea.",
    )

    assert selection is not None
    assert selection.source == "deterministic"
    assert selection.track_id == first


def test_a_failing_model_does_not_fail_the_selection(tmp_path: Path, initialised_db: int):
    first, _ = _two_tracks(tmp_path)

    def proposer(context):
        raise RuntimeError("the provider is down")

    selection = music_selection.select_track(
        music_selection.ClipContext(clip_id="c1", duration_s=30.0),
        proposer=proposer,
    )

    assert selection is not None
    assert selection.source == "deterministic"


def test_the_budget_caps_the_number_of_model_calls(tmp_path: Path, initialised_db: int):
    """One music call per clip, and no more, whatever the model asks for."""
    _two_tracks(tmp_path)
    budget = music_selection.CallBudget(max_calls=1)

    calls: list[int] = []

    def proposer(context):
        calls.append(1)
        return "{}"

    context = music_selection.ClipContext(clip_id="c1", duration_s=30.0)
    music_selection.select_track(context, proposer=proposer, budget=budget)
    music_selection.select_track(context, proposer=proposer, budget=budget)

    assert len(calls) == 1
    assert budget.used == 1
    assert budget.remaining == 0


def test_the_default_budget_is_one_call_per_clip():
    assert music_selection.default_budget(10).max_calls == 10
    assert music_selection.default_budget(12).max_calls == 12


def test_the_proposal_context_carries_no_paths(tmp_path: Path, initialised_db: int):
    """The model is told what the tracks are, not where they live."""
    _two_tracks(tmp_path)
    context = music_selection.ClipContext(clip_id="c1", duration_s=30.0)
    payload = music_selection.build_proposal_context(context, music_store.list_tracks())

    text = repr(payload)
    assert str(tmp_path) not in text
    assert "path" not in payload["tracks"][0]
    for track in payload["tracks"]:
        assert set(track) == {
            "id",
            "name",
            "title",
            "artist",
            "tags",
            "duration_s",
            "bpm",
            "bpm_confidence",
            "energy",
            "mood",
            "beat_regularity",
            "groove_strength",
            "loudness_lufs",
        }


def test_the_scorer_prefers_the_track_that_fits_the_clip(tmp_path: Path, initialised_db: int):
    """A talking clip wants calmer music than a busy one."""
    calm = music_analysis.Analysis(energy=0.1, bpm=70.0, beat_regularity=0.2)
    loud = music_analysis.Analysis(energy=0.9, bpm=150.0, beat_regularity=0.8)

    talking = music_selection.ClipContext(
        clip_id="c1", duration_s=30.0, intensity=0.4, speech_density=0.8
    )
    action = music_selection.ClipContext(
        clip_id="c2", duration_s=30.0, intensity=0.9, speech_density=0.1
    )

    assert music_selection.score_track(talking, calm) > music_selection.score_track(talking, loud)
    assert music_selection.score_track(action, loud) > music_selection.score_track(action, calm)


def test_the_scorer_stays_between_zero_and_one(tmp_path: Path, initialised_db: int):
    extreme = music_analysis.Analysis(energy=5.0, bpm=900.0, beat_regularity=9.0)
    context = music_selection.ClipContext(clip_id="c1", duration_s=30.0, intensity=5.0)
    score = music_selection.score_track(context, extreme)
    assert 0.0 <= score <= 1.0


def test_a_track_that_cannot_be_used_is_not_a_candidate(tmp_path: Path, initialised_db: int):
    """With every track blocked, there is no selection to make."""
    first, second = _two_tracks(tmp_path)
    music_store.set_license(LicenseRecord(track_id=first, state=LicenseState.UNKNOWN))
    music_store.set_license(LicenseRecord(track_id=second, state=LicenseState.UNKNOWN))

    selection = music_selection.select_track(
        music_selection.ClipContext(clip_id="c1", duration_s=30.0),
        proposer=lambda context: "{}",
    )

    assert selection is None


def test_the_tempo_target_follows_the_intensity():
    slow = music_selection._target_bpm(0.0)
    fast = music_selection._target_bpm(1.0)
    assert slow < fast
    assert math.isclose(slow, 70.0)
    assert math.isclose(fast, 150.0)
