"""Tests for provider-failure fallback and stage notices."""

from __future__ import annotations

from pathlib import Path

import pytest
from autoclip.config import Settings
from autoclip.db.models import Job, Source
from autoclip.pipeline import Stage
from autoclip.pipeline.runner import PipelineRunner, looks_like_auth_failure


def _runner(settings: Settings) -> PipelineRunner:
    job = Job(id="job123", source_id="src123")
    source = Source(id="src123", type="youtube", path="source.webm")
    return PipelineRunner(job, source, settings=settings)


@pytest.mark.parametrize(
    "message",
    [
        "Google rejected the API key.",
        "No Gemini API key is set.",
        "Anthropic rejected the API key.",
        "The endpoint rejected the API key.",
        "Highlight detection failed in every window. Original error: 401 Unauthorized",
    ],
)
def test_credential_errors_are_recognised(message: str) -> None:
    assert looks_like_auth_failure(message)


@pytest.mark.parametrize(
    "message",
    [
        "Gemini attempt 1 failed (503 UNAVAILABLE).",
        "Ollama timed out.",
        "The account has no remaining quota.",
        "No clips were found.",
    ],
)
def test_other_errors_do_not_look_like_auth_failures(message: str) -> None:
    assert not looks_like_auth_failure(message)


def test_fallback_switches_to_ollama_on_a_rejected_key() -> None:
    settings = Settings()
    settings.providers["ollama"].model = "llama3.1:8b"
    runner = _runner(settings)

    result = runner._ollama_fallback("gemini", RuntimeError("Google rejected the API key."))

    assert result is not None
    provider, notice = result
    assert provider.name == "ollama"
    assert provider.model == "llama3.1:8b"
    assert "API key failed" in notice
    assert "llama3.1:8b" in notice


def test_no_fallback_when_the_provider_is_already_ollama() -> None:
    runner = _runner(Settings())

    assert runner._ollama_fallback("ollama", RuntimeError("No API key is set.")) is None


def test_no_fallback_on_transient_errors() -> None:
    runner = _runner(Settings())

    assert runner._ollama_fallback("gemini", RuntimeError("Gemini returned 503.")) is None


def test_stage_notice_is_reused_by_later_progress_updates(autoclip_home: Path) -> None:
    from autoclip import db

    db.init()
    runner = _runner(Settings())
    events = []
    runner.on_progress = events.append

    runner._set_notice(Stage.HIGHLIGHTS, "Gemini API key failed — using local Ollama.")
    runner._emit(Stage.HIGHLIGHTS, 0.5)

    assert events[-1].message == "Gemini API key failed — using local Ollama."

    runner._finish_stage(Stage.HIGHLIGHTS)
    runner._emit(Stage.HIGHLIGHTS, 0.75)

    assert events[-1].message == Stage.HIGHLIGHTS.label
