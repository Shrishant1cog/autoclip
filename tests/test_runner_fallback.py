"""Tests for provider-failure fallback, stage notices and progress reporting."""

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


def test_fallback_switches_to_ollama_on_a_rejected_key(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    settings = Settings()
    settings.providers["ollama"].model = "llama3.1:8b"
    runner = _runner(settings)
    monkeypatch.setattr(PipelineRunner, "_provider_healthy", staticmethod(lambda _p: True))

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


def test_no_fallback_when_the_local_fallback_is_unhealthy(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A transient error is worth retrying elsewhere, but only if 'elsewhere' answers.

    With Ollama not running, the 503 must surface as itself rather than being
    swapped for a vaguer local failure.
    """
    runner = _runner(Settings())
    monkeypatch.setattr(PipelineRunner, "_provider_healthy", staticmethod(lambda _p: False))

    assert runner._ollama_fallback("gemini", RuntimeError("Gemini returned 503.")) is None


def test_fallback_switches_to_ollama_on_transient_errors(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Rate limits and outages degrade to the local model instead of failing the job."""
    settings = Settings()
    runner = _runner(settings)
    monkeypatch.setattr(PipelineRunner, "_provider_healthy", staticmethod(lambda _p: True))

    for error in (
        RuntimeError("Gemini request failed: 503 UNAVAILABLE."),
        RuntimeError("Gemini rate limit or quota reached."),
        RuntimeError("Request timed out after 30s."),
    ):
        result = runner._ollama_fallback("gemini", error)
        assert result is not None, f"no fallback for {error}"
        provider, notice = result
        assert provider.name == "ollama"
        assert "rate-limited or unavailable" in notice or "unavailable" in notice


def test_malformed_requests_still_surfaced() -> None:
    """A bad request is a bug, not an outage — no fallback, no retry."""
    runner = _runner(Settings())
    monkeypatch = pytest.MonkeyPatch()
    try:
        monkeypatch.setattr(PipelineRunner, "_provider_healthy", staticmethod(lambda _p: True))
        assert runner._ollama_fallback("gemini", RuntimeError("Invalid JSON in request.")) is None
    finally:
        monkeypatch.undo()


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


def test_progress_never_goes_backwards(autoclip_home: Path) -> None:
    """A stage that reports a lower fraction must not drag the bar backwards.

    ffmpeg's output clock can tick back by a frame when a filter reorders
    frames, and a provider that reports window-by-window can repeat a
    fraction. The progress bar is a promise to the user, so it only ever
    moves forward.
    """
    from autoclip import db

    db.init()
    runner = _runner(Settings())
    events = []
    runner.on_progress = events.append

    runner._emit(Stage.EXPORT, 0.6)
    runner._emit(Stage.EXPORT, 0.55)  # a frame out of order
    runner._emit(Stage.EXPORT, 0.7)

    overall = [event.overall for event in events]

    assert overall == sorted(overall)
    # No stage has finished yet, so the bar is this stage's own weight only.
    assert overall[-1] == pytest.approx(0.23 * 0.7)


def test_progress_does_not_exceed_one(autoclip_home: Path) -> None:
    from autoclip import db

    db.init()
    runner = _runner(Settings())
    events = []
    runner.on_progress = events.append

    runner._emit(Stage.EXPORT, 5.0)

    assert events[-1].overall == 1.0
