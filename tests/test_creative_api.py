"""The M3 API — the budget, the plan and the music preferences.

These are the surfaces a user touches to answer three questions:

* *What did this job spend?* — the budget, with the refusals written down.
* *What did the AI decide, and why?* — the plan, including the problems.
* *What music do I want?* — the preferences, at three scopes.
"""

from __future__ import annotations

from pathlib import Path

import pytest
from autoclip.db.models import Job, Source, new_id
from fastapi.testclient import TestClient


@pytest.fixture
def a_job(initialised_db: int) -> Job:
    from autoclip.db import store

    source = Source(id=new_id(), type="upload", filename="clip.mp4", path="", title="A clip")
    store.create_source(source)
    job = Job(id=new_id(), source_id=source.id, status="done")
    store.create_job(job)
    return job


def _track(tmp_path: Path, name: str = "bed.mp3") -> str:
    from autoclip.music import store as music_store

    folder = tmp_path / "music"
    folder.mkdir(exist_ok=True)
    path = folder / name
    path.write_bytes(b"audio")
    track = music_store.upsert_track(path)
    return track.id


# --------------------------------------------------------------------------
# The budget
# --------------------------------------------------------------------------


def test_a_job_that_has_not_run_reports_its_allowance(initialised_db: int, a_job: Job) -> None:
    from autoclip.app import create_app

    with TestClient(create_app()) as client:
        response = client.get(f"/api/jobs/{a_job.id}/budget")

    assert response.status_code == 200
    body = response.json()
    assert body["plan"]["max_calls"] == 1
    assert body["repair"]["max_calls"] == 1
    assert body["music"]["max_calls"] == 10
    assert body["total_limit"] == 12
    assert body["total_used"] == 0
    assert body["overruns"] == []


def test_the_budget_reports_what_was_spent(initialised_db: int, a_job: Job) -> None:
    from autoclip.app import create_app
    from autoclip.budget import budget_for

    budget = budget_for(a_job.id, max_clips=10)
    budget.take_plan()
    budget.take_music()
    budget.save()

    with TestClient(create_app()) as client:
        response = client.get(f"/api/jobs/{a_job.id}/budget")

    body = response.json()
    assert body["plan"]["used"] == 1
    assert body["music"]["used"] == 1
    assert body["total_used"] == 2


def test_the_budget_reports_the_refusals(initialised_db: int, a_job: Job) -> None:
    from autoclip.app import create_app
    from autoclip.budget import budget_for

    budget = budget_for(a_job.id, max_clips=0)
    budget.take_plan()
    budget.take_plan("the planning call was already used")
    budget.save()

    with TestClient(create_app()) as client:
        response = client.get(f"/api/jobs/{a_job.id}/budget")

    overruns = response.json()["overruns"]
    assert overruns
    assert overruns[0]["category"] == "plan"
    assert "already used" in overruns[0]["reason"]


def test_an_unknown_job_has_no_budget(initialised_db: int) -> None:
    from autoclip.app import create_app

    with TestClient(create_app()) as client:
        response = client.get("/api/jobs/nope/budget")

    assert response.status_code == 404


# --------------------------------------------------------------------------
# The plan
# --------------------------------------------------------------------------


def test_a_job_with_no_plan_says_so(initialised_db: int, a_job: Job) -> None:
    from autoclip.app import create_app

    with TestClient(create_app()) as client:
        response = client.get(f"/api/jobs/{a_job.id}/plan")

    assert response.status_code == 200
    body = response.json()
    assert body["clips"] == []
    assert body["state"] == "not planned yet"


def test_the_plan_keeps_the_problems(initialised_db: int, a_job: Job) -> None:
    """A silent fallback would read exactly like a plan the model agreed with."""
    from autoclip.app import create_app
    from autoclip.db import plan_store
    from autoclip.db.models import Clip
    from autoclip.pipeline import creative

    clip = Clip(id="c1", job_id=a_job.id, start_s=0.0, end_s=20.0, rank=1, title="One")
    plan = creative.fallback_plan([clip], reason="the plan did not match the schema")
    plan_store.save(a_job.id, plan)

    with TestClient(create_app()) as client:
        response = client.get(f"/api/jobs/{a_job.id}/plan")

    body = response.json()
    assert body["source"] == "fallback"
    assert body["problems"]
    assert body["clips"][0]["clip_id"] == "c1"


def test_an_unknown_job_has_no_plan(initialised_db: int) -> None:
    from autoclip.app import create_app

    with TestClient(create_app()) as client:
        response = client.get("/api/jobs/nope/plan")

    assert response.status_code == 404


# --------------------------------------------------------------------------
# The preferences
# --------------------------------------------------------------------------


def test_the_preferences_start_empty(initialised_db: int) -> None:
    from autoclip.app import create_app

    with TestClient(create_app()) as client:
        response = client.get("/api/music/preferences")

    body = response.json()
    assert body["track_id"] == ""
    assert body["none"] is False
    assert body["scope"] == ""


def test_a_preference_is_saved_and_read_back(initialised_db: int, tmp_path: Path) -> None:
    from autoclip.app import create_app

    track_id = _track(tmp_path)

    with TestClient(create_app()) as client:
        saved = client.put(
            "/api/music/preferences",
            json={"scope": "global", "track_id": track_id},
        )
        read = client.get("/api/music/preferences")

    assert saved.status_code == 200
    assert read.json()["track_id"] == track_id
    assert read.json()["scope"] == "global"


def test_a_source_preference_is_kept_separate(initialised_db: int, tmp_path: Path) -> None:
    from autoclip.app import create_app

    track_id = _track(tmp_path)

    with TestClient(create_app()) as client:
        client.put("/api/music/preferences", json={"scope": "global", "track_id": track_id})
        client.put(
            "/api/music/preferences",
            json={"scope": "source", "scope_id": "src1", "track_id": track_id},
        )
        read = client.get("/api/music/preferences?source_id=src1")

    assert read.json()["scope"] == "source"


def test_clearing_a_scope_keeps_the_global_one(initialised_db: int, tmp_path: Path) -> None:
    from autoclip.app import create_app

    track_id = _track(tmp_path)

    with TestClient(create_app()) as client:
        client.put("/api/music/preferences", json={"scope": "global", "track_id": track_id})
        client.put(
            "/api/music/preferences",
            json={"scope": "source", "scope_id": "src1", "track_id": track_id},
        )
        client.delete("/api/music/preferences?scope=source&scope_id=src1")
        read = client.get("/api/music/preferences?source_id=src1")

    assert read.json()["scope"] == "global"
    assert read.json()["track_id"] == track_id


def test_no_music_is_a_different_answer_from_unset(initialised_db: int) -> None:
    from autoclip.app import create_app

    with TestClient(create_app()) as client:
        client.put("/api/music/preferences", json={"scope": "global", "track_id": "__none__"})
        read = client.get("/api/music/preferences")

    body = read.json()
    assert body["none"] is True
    assert body["track_id"] == ""


def test_an_unknown_scope_is_refused(initialised_db: int) -> None:
    from autoclip.app import create_app

    with TestClient(create_app()) as client:
        response = client.put("/api/music/preferences", json={"scope": "galaxy", "track_id": "x"})

    assert response.status_code == 400


def test_a_preference_for_a_track_that_does_not_exist_is_refused(initialised_db: int) -> None:
    from autoclip.app import create_app

    with TestClient(create_app()) as client:
        response = client.put(
            "/api/music/preferences", json={"scope": "global", "track_id": "made-up"}
        )

    assert response.status_code == 404


def test_a_source_preference_needs_a_source(initialised_db: int) -> None:
    from autoclip.app import create_app

    with TestClient(create_app()) as client:
        response = client.put("/api/music/preferences", json={"scope": "source", "track_id": "x"})

    assert response.status_code == 400


# --------------------------------------------------------------------------
# The formats and the filters
# --------------------------------------------------------------------------


def test_the_formats_are_listed_with_their_measurements(initialised_db: int) -> None:
    from autoclip.app import create_app

    with TestClient(create_app()) as client:
        response = client.get("/api/music/formats")

    assert response.status_code == 200
    body = response.json()
    assert body
    assert all(entry["measured"] for entry in body)
    assert all(entry["description"] for entry in body)


def test_the_library_filters_on_energy(initialised_db: int, tmp_path: Path) -> None:
    from autoclip.app import create_app
    from autoclip.music import store as music_store
    from autoclip.music.analysis import Analysis

    track_id = _track(tmp_path)
    music_store.analyse_track(track_id, Analysis(duration_s=30.0, energy=0.85, bpm=140.0))

    with TestClient(create_app()) as client:
        loud = client.get("/api/music/library?min_energy=0.6").json()
        quiet = client.get("/api/music/library?max_energy=0.4").json()

    assert len(loud) == 1
    assert quiet == []


def test_the_library_filters_on_format(initialised_db: int, tmp_path: Path) -> None:
    from autoclip.app import create_app
    from autoclip.music import store as music_store
    from autoclip.music.analysis import Analysis

    track_id = _track(tmp_path)
    music_store.analyse_track(track_id, Analysis(duration_s=30.0, energy=0.85, bpm=140.0))

    with TestClient(create_app()) as client:
        driving = client.get("/api/music/library?format=driving").json()
        sparse = client.get("/api/music/library?format=sparse").json()

    assert len(driving) == 1
    assert sparse == []


# --------------------------------------------------------------------------
# The clip carries its music
# --------------------------------------------------------------------------


def test_a_clip_carries_its_music_selection(initialised_db: int, a_job: Job) -> None:
    from autoclip.app import create_app
    from autoclip.db import store
    from autoclip.db.models import Clip

    clip = Clip(
        id=new_id(),
        job_id=a_job.id,
        start_s=0.0,
        end_s=20.0,
        rank=1,
        title="One",
        music_track_id="track-1",
        music_source="user",
        music_reason="Chosen by you.",
    )
    store.replace_clips(a_job.id, [clip])

    with TestClient(create_app()) as client:
        response = client.get(f"/api/jobs/{a_job.id}/clips")

    body = response.json()
    assert body[0]["music_track_id"] == "track-1"
    assert body[0]["music_source"] == "user"
    assert body[0]["music_reason"] == "Chosen by you."
