"""Phase 13 — the project-aware assistant."""

from __future__ import annotations

import asyncio

import pytest
from autoclip.chat import agent
from autoclip.chat.context import build_context
from autoclip.db import store
from autoclip.db.models import Clip, Export, Job, Source, YouTubeUpload, new_id
from autoclip.providers import resolver
from autoclip.providers.base import ProviderError
from fastapi.testclient import TestClient

# --------------------------------------------------------------------------
# Fixtures / helpers
# --------------------------------------------------------------------------


def _seed_source(title: str = "My Source Video") -> Source:
    source = Source(id=new_id(), type="upload", path="C:/videos/source.mp4", title=title)
    store.create_source(source)
    return source


def _seed_job(source: Source, *, status: str = "done", error: str | None = None) -> Job:
    job = Job(id=new_id(), source_id=source.id, status=status, error=error)
    store.create_job(job)
    return job


def _seed_clip(job: Job, *, title: str = "A great clip", score: int = 90, reason: str = "") -> Clip:
    clip = Clip(
        id=new_id(),
        job_id=job.id,
        start_s=1.0,
        end_s=21.0,
        rank=1,
        score=score,
        title=title,
        hook="The opening hook",
        reason=reason or "Because it states a surprising number",
        status="exported",
    )
    store.replace_clips(job.id, [clip])
    return clip


def _mock_provider(monkeypatch: pytest.MonkeyPatch, output: str, label: str = "fake-provider"):
    """Capture the prompt the assistant would send and return a canned reply."""
    captured: dict[str, str] = {}

    async def fake_run(task, system, user, settings, chain=None, temperature=0.4):
        captured["task"] = task
        captured["system"] = system
        captured["user"] = user
        return output, label

    monkeypatch.setattr(resolver, "run_with_fallback", fake_run)
    return captured


# --------------------------------------------------------------------------
# Context assembly
# --------------------------------------------------------------------------


def test_context_reflects_real_library(autoclip_home, initialised_db: int) -> None:
    source = _seed_source("Horror Stream")
    job = _seed_job(source)
    clip = _seed_clip(job, title="The scariest moment", score=88)
    export = Export(id=new_id(), clip_id=clip.id, path="C:/out.mp4")
    store.create_export(export)
    store.create_upload(
        YouTubeUpload(id=new_id(), export_id=export.id, clip_id=clip.id, status="done")
    )

    context = build_context()
    prompt = context.as_prompt()

    assert context.summary["clips"] == 1
    assert context.summary["exported"] == 1
    assert context.summary["uploads_done"] == 1
    assert "The scariest moment" in prompt
    assert "Horror Stream" in prompt
    assert "The opening hook" in prompt
    assert "88" in prompt


def test_context_lists_failures(autoclip_home, initialised_db: int) -> None:
    source = _seed_source("Broken Video")
    _seed_job(source, status="failed", error="ffmpeg exited with code 1")

    context = build_context()
    prompt = context.as_prompt()

    assert any(f["kind"] == "job failed" for f in context.failures)
    assert "ffmpeg exited with code 1" in prompt


def test_context_lists_upload_failures(autoclip_home, initialised_db: int) -> None:
    source = _seed_source()
    job = _seed_job(source)
    clip = _seed_clip(job)
    export = Export(id=new_id(), clip_id=clip.id, path="C:/out.mp4")
    store.create_export(export)
    store.create_upload(
        YouTubeUpload(
            id=new_id(),
            export_id=export.id,
            clip_id=clip.id,
            status="failed",
            error="quotaExceeded",
        )
    )

    context = build_context()
    assert any(f["kind"] == "upload failed" for f in context.failures)
    assert "quotaExceeded" in context.as_prompt()


def test_clip_focus(autoclip_home, initialised_db: int) -> None:
    source = _seed_source("Focused Source")
    job = _seed_job(source)
    clip = _seed_clip(job, title="Focused clip", score=77, reason="Strong story beat")

    context = build_context(clip_id=clip.id)

    assert context.focus["clip_id"] == clip.id
    assert context.focus["title"] == "Focused clip"
    assert context.focus["score"] == 77
    assert context.focus["reason"] == "Strong story beat"
    assert "Focused clip" in context.as_prompt()


def test_job_focus(autoclip_home, initialised_db: int) -> None:
    source = _seed_source("Job Source")
    job = _seed_job(source)
    _seed_clip(job, title="Clip one")

    context = build_context(job_id=job.id)

    assert context.focus["job_id"] == job.id
    assert context.focus["clips_found"] == 1
    assert "Clip one" in context.as_prompt()


def test_context_includes_settings(autoclip_home, initialised_db: int) -> None:
    context = build_context()
    prompt = context.as_prompt()

    assert "Current settings" in prompt
    assert "max clips per video" in prompt
    assert "auto-upload" in prompt


def test_context_includes_user_feedback(autoclip_home, initialised_db: int) -> None:
    from autoclip.learning import improve

    improve.ensure_template().write_text("Never clip the intro.", encoding="utf-8")

    context = build_context()
    assert "Never clip the intro." in context.as_prompt()


# --------------------------------------------------------------------------
# The agent
# --------------------------------------------------------------------------


def test_ask_sends_the_snapshot_to_the_provider(
    autoclip_home, initialised_db: int, monkeypatch: pytest.MonkeyPatch
) -> None:
    source = _seed_source("Real Video")
    job = _seed_job(source)
    _seed_clip(job, title="Keeper")

    captured = _mock_provider(monkeypatch, "You have produced 1 clip.")

    answer = asyncio.run(agent.ask("What have I produced?"))

    assert answer.answer == "You have produced 1 clip."
    assert answer.provider == "fake-provider"
    assert "Keeper" in captured["system"]
    assert "Real Video" in captured["system"]
    assert "What have I produced?" in captured["user"]


def test_ask_carries_history(
    autoclip_home, initialised_db: int, monkeypatch: pytest.MonkeyPatch
) -> None:
    captured = _mock_provider(monkeypatch, "Sure.")

    asyncio.run(
        agent.ask(
            "And the second question?",
            history=[
                agent.ChatTurn(role="user", content="First question?"),
                agent.ChatTurn(role="assistant", content="First answer."),
            ],
        )
    )

    assert "First question?" in captured["user"]
    assert "First answer." in captured["user"]
    assert "And the second question?" in captured["user"]


def test_ask_raises_when_no_provider_answers(
    autoclip_home, initialised_db: int, monkeypatch: pytest.MonkeyPatch
) -> None:
    async def failing(task, system, user, settings, chain=None, temperature=0.4):
        raise resolver.AllProvidersFailedError("every provider failed")

    monkeypatch.setattr(resolver, "run_with_fallback", failing)

    with pytest.raises(resolver.AllProvidersFailedError):
        asyncio.run(agent.ask("Anything?"))


def test_ask_rejects_an_empty_answer(
    autoclip_home, initialised_db: int, monkeypatch: pytest.MonkeyPatch
) -> None:
    _mock_provider(monkeypatch, "   ")

    with pytest.raises(ProviderError):
        asyncio.run(agent.ask("Anything?"))


def test_json_answers_are_retried_as_prose(
    autoclip_home, initialised_db: int, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A chat reply must be prose; a JSON answer is retried once."""
    calls: list[str] = []

    async def fake_run(task, system, user, settings, chain=None, temperature=0.4):
        calls.append(system)
        if len(calls) == 1:
            return '{"clips": 15}', "fake-provider"
        return "You have produced 15 clips.", "fake-provider"

    monkeypatch.setattr(resolver, "run_with_fallback", fake_run)

    answer = asyncio.run(agent.ask("How many clips?"))

    assert answer.answer == "You have produced 15 clips."
    assert len(calls) == 2
    assert agent.NO_JSON_NUDGE in calls[1]


def test_json_is_kept_when_the_retry_also_fails(
    autoclip_home, initialised_db: int, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A JSON answer is better than no answer."""
    calls: list[str] = []

    async def fake_run(task, system, user, settings, chain=None, temperature=0.4):
        calls.append(system)
        return '{"clips": 15}', "fake-provider"

    monkeypatch.setattr(resolver, "run_with_fallback", fake_run)

    answer = asyncio.run(agent.ask("How many clips?"))

    assert answer.answer == '{"clips": 15}'
    assert len(calls) == 2


def test_prose_answers_are_not_retried(
    autoclip_home, initialised_db: int, monkeypatch: pytest.MonkeyPatch
) -> None:
    calls: list[str] = []

    async def fake_run(task, system, user, settings, chain=None, temperature=0.4):
        calls.append(system)
        return "You have produced 15 clips.", "fake-provider"

    monkeypatch.setattr(resolver, "run_with_fallback", fake_run)

    answer = asyncio.run(agent.ask("How many clips?"))

    assert answer.answer == "You have produced 15 clips."
    assert len(calls) == 1


def test_system_prompt_forbids_invention() -> None:
    assert "Never invent" in agent.SYSTEM_PROMPT
    assert "the entirety of what you know" in agent.SYSTEM_PROMPT


# --------------------------------------------------------------------------
# HTTP API
# --------------------------------------------------------------------------


def test_chat_api_answers(
    autoclip_home, initialised_db: int, monkeypatch: pytest.MonkeyPatch
) -> None:
    from autoclip.app import create_app

    source = _seed_source("API Video")
    job = _seed_job(source)
    _seed_clip(job, title="API Clip")

    _mock_provider(monkeypatch, "One clip so far.")

    with TestClient(create_app()) as client:
        response = client.post("/api/chat", json={"message": "What have I produced?"})
        assert response.status_code == 200
        body = response.json()
        assert body["answer"] == "One clip so far."
        assert body["provider"] == "fake-provider"
        assert body["context"]["summary"]["clips"] == 1


def test_chat_api_rejects_an_empty_message(
    autoclip_home, initialised_db: int
) -> None:
    from autoclip.app import create_app

    with TestClient(create_app()) as client:
        response = client.post("/api/chat", json={"message": "   "})
        assert response.status_code == 400


def test_chat_api_reports_provider_failure_honestly(
    autoclip_home, initialised_db: int, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A dead provider chain must surface as a failure, not a canned answer."""
    from autoclip.app import create_app

    async def failing(task, system, user, settings, chain=None, temperature=0.4):
        raise resolver.AllProvidersFailedError("every provider failed")

    monkeypatch.setattr(resolver, "run_with_fallback", failing)

    with TestClient(create_app()) as client:
        response = client.post("/api/chat", json={"message": "What have I produced?"})
        assert response.status_code == 502
        body = response.json()
        assert "No AI provider could answer" in body["detail"]
        assert "answer" not in body


def test_chat_context_endpoint_shows_the_snapshot(
    autoclip_home, initialised_db: int
) -> None:
    from autoclip.app import create_app

    source = _seed_source("Visible Video")
    job = _seed_job(source)
    _seed_clip(job, title="Visible Clip")

    with TestClient(create_app()) as client:
        response = client.get("/api/chat/context")
        assert response.status_code == 200
        body = response.json()
        assert "Visible Clip" in body["prompt"]
        assert body["context"]["summary"]["clips"] == 1


def test_chat_starters(autoclip_home, initialised_db: int) -> None:
    from autoclip.app import create_app

    with TestClient(create_app()) as client:
        body = client.get("/api/chat/starters").json()
        assert body["starters"]
        assert all(isinstance(item, str) for item in body["starters"])


def test_chat_history_is_not_duplicated(
    autoclip_home, initialised_db: int, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The client sends the new question plus history; it must appear once."""
    from autoclip.app import create_app

    captured = _mock_provider(monkeypatch, "Answer.")

    with TestClient(create_app()) as client:
        client.post(
            "/api/chat",
            json={
                "message": "How many clips?",
                "history": [
                    {"role": "user", "content": "Earlier question"},
                    {"role": "assistant", "content": "Earlier answer"},
                    {"role": "user", "content": "How many clips?"},
                ],
            },
        )

    assert captured["user"].count("How many clips?") == 1
    assert "Earlier question" in captured["user"]
