"""Phase 11 — analytics and the improve.txt learning loop."""

from __future__ import annotations

import pytest
from autoclip.db import store
from autoclip.db.models import Clip, Export, Job, Source, YouTubeUpload, new_id
from autoclip.learning import analytics, improve
from autoclip.providers import base as providers_base
from fastapi.testclient import TestClient

# --------------------------------------------------------------------------
# Helpers
# --------------------------------------------------------------------------


def _seed_clip(*, score: int, status: str = "candidate", trimmed: bool = False) -> Clip:
    source = Source(
        id=new_id(), type="upload", path="C:/videos/source.mp4", title="source", duration_s=120.0
    )
    store.create_source(source)
    job = Job(id=new_id(), source_id=source.id, status="done")
    store.create_job(job)
    clip = Clip(
        id=new_id(), job_id=job.id, start_s=1.0, end_s=20.0, rank=1,
        score=score, status=status, user_trimmed=trimmed,
    )
    store.replace_clips(job.id, [clip])
    return clip


# --------------------------------------------------------------------------
# improve.txt
# --------------------------------------------------------------------------


def test_improve_template_created_and_comments_stripped(autoclip_home) -> None:
    path = improve.ensure_template()
    assert path.exists()
    assert improve.read_feedback() == ""

    path.write_text(
        "# a comment\n\nPrefer clips with numbers.\n# another\n", encoding="utf-8"
    )
    assert improve.read_feedback() == "Prefer clips with numbers."


def test_improve_feedback_is_truncated(autoclip_home) -> None:
    path = improve.ensure_template()
    path.write_text("x" * (improve.MAX_FEEDBACK_CHARS + 500), encoding="utf-8")
    feedback = improve.read_feedback()
    assert len(feedback) <= improve.MAX_FEEDBACK_CHARS


def test_prompt_section_appended_only_with_feedback(autoclip_home) -> None:
    assert improve.prompt_section() == ""
    improve.ensure_template().write_text("Never clip the intro.", encoding="utf-8")
    section = improve.prompt_section()
    assert "Never clip the intro." in section
    assert "Editor feedback" in section


def test_detection_prompt_includes_feedback(
    autoclip_home, monkeypatch: pytest.MonkeyPatch
) -> None:
    """detect_highlights must pass the feedback through in the system prompt."""
    improve.ensure_template().write_text("Our audience loves numbers.", encoding="utf-8")

    class DummyProvider(providers_base.LLMProvider):
        name = "dummy"

        def __init__(self):
            super().__init__("dummy-model")
            self.system_prompts: list[str] = []

        async def _complete(self, system, user, config):
            self.system_prompts.append(system)
            return '{"clips": []}'

        async def health_check(self):
            return providers_base.ProviderStatus(name=self.name, available=True)

    from autoclip.providers.base import DetectionConfig, TranscriptWindow

    provider = DummyProvider()
    window = TranscriptWindow(
        first_word=0, last_word=5, text="[0]hello [1]world", speakers=[]
    )

    import anyio

    anyio.run(
        lambda: provider.detect_highlights(
            window,
            DetectionConfig(min_duration_s=5, max_duration_s=60),
        )
    ) if False else __import__("asyncio").run(
        provider.detect_highlights(
            window, DetectionConfig(min_duration_s=5, max_duration_s=60)
        )
    )

    assert provider.system_prompts
    assert "Our audience loves numbers." in provider.system_prompts[0]


def test_channel_note_round_trip(autoclip_home) -> None:
    assert improve.read_channel_note("UCabc123") == ""
    improve.write_channel_note("UCabc123", "Titles here work best as questions.")
    assert improve.read_channel_note("UCabc123") == "Titles here work best as questions."
    improve.write_channel_note("UCabc123", "")
    assert improve.read_channel_note("UCabc123") == ""
    assert not improve.channel_note_path("UCabc123").exists()


# --------------------------------------------------------------------------
# Analytics
# --------------------------------------------------------------------------


def test_score_band_outcomes(initialised_db: int) -> None:
    _seed_clip(score=90, status="exported")
    _seed_clip(score=88, status="discarded")
    _seed_clip(score=75, status="kept", trimmed=True)
    _seed_clip(score=10, status="discarded")

    bands = {band.band: band for band in analytics.score_band_outcomes()}
    assert bands["85-100"].total == 2
    assert bands["85-100"].exported == 1
    assert bands["85-100"].discarded == 1
    assert bands["70-84"].kept == 1
    assert bands["70-84"].trimmed == 1
    assert bands["0-49"].discarded == 1


def test_channel_outcomes_and_summary(initialised_db: int) -> None:
    clip = _seed_clip(score=90, status="exported")
    export = Export(id=new_id(), clip_id=clip.id, path="C:/out.mp4")
    store.create_export(export)
    store.create_upload(
        YouTubeUpload(id=new_id(), export_id=export.id, clip_id=clip.id,
                      channel_row_id="chan-1", status="done")
    )
    store.create_upload(
        YouTubeUpload(id=new_id(), export_id=export.id, clip_id=clip.id,
                      channel_row_id="chan-2", status="failed", error="quota")
    )

    rows = {row.channel_row_id: row for row in analytics.channel_outcomes()}
    assert rows["chan-1"].done == 1
    assert rows["chan-2"].failed == 1

    summary = analytics.pipeline_summary()
    assert summary.clips == 1
    assert summary.exported == 1
    assert summary.uploads_done == 1
    assert summary.uploads_failed == 1


def test_validation_failures_aggregated(initialised_db: int) -> None:
    clip = _seed_clip(score=50, status="invalid")
    store.update_clip(
        clip.id,
        validation={
            "ok": False,
            "checks": [
                {"name": "resolution", "ok": False, "detail": "wrong"},
                {"name": "resolution", "ok": False, "detail": "wrong again"},
            ],
        },
    )
    summary = analytics.pipeline_summary()
    assert summary.invalid == 1
    assert summary.validation_failures["resolution"] == 2


# --------------------------------------------------------------------------
# HTTP API
# --------------------------------------------------------------------------


def test_learning_api_round_trip(autoclip_home, initialised_db: int) -> None:
    from autoclip.app import create_app

    _seed_clip(score=95, status="exported")

    with TestClient(create_app()) as client:
        summary = client.get("/api/learning/summary").json()
        assert summary["clips"] == 1

        bands = client.get("/api/learning/score-bands").json()
        assert bands[0]["band"] == "85-100"

        feedback = client.get("/api/learning/feedback").json()
        assert "improve.txt" in feedback["path"]

        saved = client.put(
            "/api/learning/feedback", json={"content": "# header\nBe punchier."}
        )
        assert saved.status_code == 200
        assert saved.json()["active_chars"] == len("Be punchier.")
        assert client.get("/api/learning/feedback").json()["content"].endswith("Be punchier.")

        # Saving blank content restores the template, not an empty file.
        cleared = client.put("/api/learning/feedback", json={"content": ""})
        assert cleared.status_code == 200
        restored = client.get("/api/learning/feedback").json()["content"]
        assert restored.startswith("# improve.txt")
        assert improve.read_feedback() == ""

        note = client.put(
            "/api/learning/channel-note/UCxyz",
            json={"channel_id": "UCxyz", "note": "Questions work."},
        )
        assert note.status_code == 200
        assert client.get("/api/learning/channel-note/UCxyz").json()["note"] == "Questions work."

        channels = client.get("/api/learning/channels").json()
        assert channels == []
