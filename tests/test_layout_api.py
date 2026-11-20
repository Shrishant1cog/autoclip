"""The layout API and the per-source layout record.

These tests cover the parts a user touches: choosing a layout, changing
their mind, and being told honestly what was detected.
"""

from __future__ import annotations

from pathlib import Path

import pytest
from autoclip.db.models import Source, new_id
from fastapi.testclient import TestClient


@pytest.fixture
def a_source(initialised_db: int) -> Source:
    """A source with a video file on disk."""
    from autoclip.db import store

    source = Source(
        id=new_id(),
        type="upload",
        url=None,
        filename="clip.mp4",
        path="",
        title="A clip",
        channel=None,
        duration_s=30.0,
        width=1920,
        height=1080,
        fps=30.0,
        has_audio=True,
        has_video=True,
        created_at="2026-01-01T00:00:00Z",
    )
    store.create_source(source)
    return source


# --------------------------------------------------------------------------
# The store
# --------------------------------------------------------------------------


def test_a_source_with_no_layout_has_no_record(initialised_db: int) -> None:
    from autoclip.pipeline.reframe import layout_store

    assert layout_store.get_source_layout("src_nothing") is None


def test_the_detection_is_recorded(initialised_db: int, a_source: Source) -> None:
    from autoclip.pipeline.reframe import layout_store

    layout_store.record_detection(
        a_source.id,
        rect={"x": 1500.0, "y": 50.0, "width": 380.0, "height": 300.0},
        confidence=0.82,
        face_width=200.0,
        reason="the region held a face throughout",
    )

    stored = layout_store.get_source_layout(a_source.id)
    assert stored is not None
    assert stored.has_detection is True
    assert stored.detected_confidence == pytest.approx(0.82)
    assert stored.detected_width == pytest.approx(380.0)
    assert stored.detected_reason == "the region held a face throughout"


def test_the_user_choice_is_kept_when_detection_runs_again(
    initialised_db: int, a_source: Source
) -> None:
    """A re-detection must not wipe what the user chose."""
    from autoclip.pipeline.reframe import layout_store

    layout_store.set_layout_override(
        a_source.id,
        variant="corner",
        rect_x=10.0,
        rect_y=20.0,
        rect_width=300.0,
        rect_height=200.0,
        position="bottom-left",
    )
    layout_store.record_detection(
        a_source.id,
        rect={"x": 1500.0, "y": 50.0, "width": 380.0, "height": 300.0},
        confidence=0.9,
        face_width=200.0,
        reason="found again",
    )

    stored = layout_store.get_source_layout(a_source.id)
    assert stored is not None
    assert stored.variant == "corner"
    assert stored.position == "bottom-left"
    assert stored.detected_confidence == pytest.approx(0.9)


def test_clearing_the_choice_keeps_the_detection(initialised_db: int, a_source: Source) -> None:
    from autoclip.pipeline.reframe import layout_store

    layout_store.record_detection(
        a_source.id,
        rect={"x": 10.0, "y": 20.0, "width": 300.0, "height": 200.0},
        confidence=0.8,
        face_width=100.0,
        reason="found",
    )
    layout_store.set_layout_override(a_source.id, variant="above")

    stored = layout_store.clear_layout_override(a_source.id)

    assert stored is not None
    assert stored.has_override is False
    assert stored.has_detection is True


# --------------------------------------------------------------------------
# The API
# --------------------------------------------------------------------------


def test_the_api_says_when_nothing_was_detected(initialised_db: int, a_source: Source) -> None:
    from autoclip.app import create_app

    with TestClient(create_app()) as client:
        response = client.get(f"/api/layout/sources/{a_source.id}")

    assert response.status_code == 200
    body = response.json()
    assert body["detected"] is False
    assert body["variant"] == ""


def test_the_api_saves_the_users_choice(initialised_db: int, a_source: Source) -> None:
    from autoclip.app import create_app

    with TestClient(create_app()) as client:
        response = client.put(
            f"/api/layout/sources/{a_source.id}",
            json={
                "source_id": a_source.id,
                "variant": "corner",
                "rect_x": 10.0,
                "rect_y": 20.0,
                "rect_width": 300.0,
                "rect_height": 200.0,
                "position": "bottom-left",
            },
        )

    assert response.status_code == 200
    body = response.json()
    assert body["variant"] == "corner"
    assert body["position"] == "bottom-left"
    assert body["rect_width"] == pytest.approx(300.0)


def test_the_api_refuses_a_layout_it_does_not_know(initialised_db: int, a_source: Source) -> None:
    from autoclip.app import create_app

    with TestClient(create_app()) as client:
        response = client.put(
            f"/api/layout/sources/{a_source.id}",
            json={"source_id": a_source.id, "variant": "diagonal"},
        )

    assert response.status_code == 400


def test_the_api_refuses_a_position_it_does_not_know(initialised_db: int, a_source: Source) -> None:
    from autoclip.app import create_app

    with TestClient(create_app()) as client:
        response = client.put(
            f"/api/layout/sources/{a_source.id}",
            json={"source_id": a_source.id, "variant": "corner", "position": "middle"},
        )

    assert response.status_code == 400


def test_the_api_refuses_a_source_that_is_not_there(initialised_db: int) -> None:
    from autoclip.app import create_app

    with TestClient(create_app()) as client:
        response = client.get("/api/layout/sources/src_missing")

    assert response.status_code == 404


def test_clearing_the_choice_hands_the_decision_back(initialised_db: int, a_source: Source) -> None:
    from autoclip.app import create_app

    with TestClient(create_app()) as client:
        client.put(
            f"/api/layout/sources/{a_source.id}",
            json={"source_id": a_source.id, "variant": "above"},
        )
        response = client.delete(f"/api/layout/sources/{a_source.id}")

    assert response.status_code == 200
    assert response.json()["variant"] == ""


def test_the_api_lists_the_variants_it_offers(initialised_db: int) -> None:
    from autoclip.app import create_app

    with TestClient(create_app()) as client:
        response = client.get("/api/layout/variants")

    assert response.status_code == 200
    body = response.json()
    values = [variant["value"] for variant in body["variants"]]
    assert "above" in values
    assert "corner" in values
    assert "gameplay_only" in values


def test_detecting_a_source_without_a_video_is_refused(
    initialised_db: int, a_source: Source
) -> None:
    from autoclip.app import create_app
    from autoclip.db import store

    source = store.get_source(a_source.id)
    assert source is not None
    source.path = ""
    source.has_video = False
    store.update_source(source)

    with TestClient(create_app()) as client:
        response = client.post(f"/api/layout/sources/{a_source.id}/detect")

    assert response.status_code == 400


def test_detecting_a_real_video_reports_what_it_found(
    initialised_db: int, a_source: Source, tmp_path: Path
) -> None:
    """Detection on a video with no faces says so, and does not crash."""
    import subprocess

    from autoclip.app import create_app
    from autoclip.db import store
    from autoclip.pipeline import ffmpeg

    video = tmp_path / "plain.mp4"
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
            "testsrc2=size=320x240:rate=10:duration=2",
            "-c:v",
            "libx264",
            "-pix_fmt",
            "yuv420p",
            str(video),
        ],
        check=True,
        capture_output=True,
    )

    source = store.get_source(a_source.id)
    assert source is not None
    source.path = str(video)
    store.update_source(source)

    with TestClient(create_app()) as client:
        response = client.post(f"/api/layout/sources/{a_source.id}/detect")

    assert response.status_code == 200
    body = response.json()
    # The test pattern has no faces, so nothing should be claimed.
    assert body["found"] is False
    assert body["reason"]
