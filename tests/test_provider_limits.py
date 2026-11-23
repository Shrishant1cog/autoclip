"""Local-model limits — the request timeout and the context window.

The M5.4 run against a second real YouTube URL failed at highlight detection
with "Ollama timed out." twice, and the message blamed "a small GPU" on a
machine that has none. Two things were wrong underneath that message:

* the ceiling was a hard-coded 600 s, while one legitimate detection call over
  an eight-minute window was measured at 1,993 s on this CPU-only box; and
* the prompt for that window was 5,861 tokens against a 4,096-token context,
  so the server truncated it without saying so, and the request never finished.

These tests pin the four fixes that came out of it: a timeout the user can
configure, a timeout message that states the truth, a stage that stops at the
first timeout instead of queueing behind the request it abandoned, and a
request whose prompt and answer both fit the context the provider was asked
for.
"""

from __future__ import annotations

import asyncio
from dataclasses import dataclass
from typing import Any

import httpx
import pytest
from autoclip.config import Settings
from autoclip.errors import TIMEOUT, classify
from autoclip.pipeline import highlights
from autoclip.pipeline.transcript import Transcript, Word
from autoclip.providers import (
    ClipCandidates,
    DetectionConfig,
    LLMProvider,
    OllamaProvider,
    ProviderError,
    ProviderStatus,
    TranscriptWindow,
    build_provider,
)

#: One detection call over an eight-minute window was measured at 1,993 s on
#: this machine (554 s of it evaluating the prompt). The old ceiling was 600 s,
#: so it cut off calls that were about to succeed.
MEASURED_CALL_S = 1993.0

#: The prompt for that window measured 5,861 tokens, and Ollama was running
#: with its own default context of 4,096.
MEASURED_PROMPT_TOKENS = 5861


# --------------------------------------------------------------------------
# A stand-in for Ollama's HTTP client
# --------------------------------------------------------------------------


class _FakeResponse:
    def __init__(self, payload: dict[str, Any]) -> None:
        self._payload = payload

    def raise_for_status(self) -> None:
        return None

    def json(self) -> dict[str, Any]:
        return self._payload


class _FakeClient:
    def __init__(self, recorder: _OllamaHTTP, **kwargs: Any) -> None:
        self._recorder = recorder
        self.timeout = kwargs.get("timeout")

    async def __aenter__(self) -> _FakeClient:
        return self

    async def __aexit__(self, *exc: Any) -> bool:
        return False

    async def post(self, url: str, json: dict[str, Any] | None = None) -> _FakeResponse:
        self._recorder.calls.append({"url": url, "payload": json, "timeout": self.timeout})
        if self._recorder.error is not None:
            raise self._recorder.error
        return _FakeResponse(self._recorder.response)


class _OllamaHTTP:
    """Records what the provider sent, and answers with what the test wants."""

    def __init__(self) -> None:
        self.calls: list[dict[str, Any]] = []
        self.response: dict[str, Any] = {"response": '{"clips": []}'}
        self.error: Exception | None = None

    def client(self, **kwargs: Any) -> _FakeClient:
        return _FakeClient(self, **kwargs)


@pytest.fixture
def ollama_http(monkeypatch: pytest.MonkeyPatch) -> _OllamaHTTP:
    recorder = _OllamaHTTP()
    monkeypatch.setattr(httpx, "AsyncClient", recorder.client)
    return recorder


# --------------------------------------------------------------------------
# The timeout
# --------------------------------------------------------------------------


class TestTheTimeout:
    def test_the_default_outlasts_a_measured_call(self) -> None:
        provider = OllamaProvider("llama3.1:8b")

        assert provider.request_timeout_s > MEASURED_CALL_S

    def test_the_timeout_is_a_setting(self) -> None:
        settings = Settings()
        settings.providers["ollama"].timeout_s = 900

        provider = build_provider("ollama", settings)

        assert provider.request_timeout_s == 900

    def test_the_configured_timeout_reaches_the_http_client(self, ollama_http) -> None:
        provider = OllamaProvider("llama3.1:8b", timeout_s=900)

        asyncio.run(provider._complete("system", "user", DetectionConfig()))

        assert ollama_http.calls[0]["timeout"].read == 900

    def test_the_message_names_the_timeout_it_waited_for(self, ollama_http) -> None:
        ollama_http.error = httpx.ReadTimeout("timed out")
        provider = OllamaProvider("llama3.1:8b", timeout_s=600)

        with pytest.raises(ProviderError) as caught:
            asyncio.run(provider._complete("system", "user", DetectionConfig()))

        assert "600" in str(caught.value)

    def test_the_message_does_not_blame_a_gpu_that_is_not_there(self, ollama_http) -> None:
        """The old hint said "Large transcripts on a small GPU can exceed the limit"."""
        ollama_http.error = httpx.ReadTimeout("timed out")
        provider = OllamaProvider("llama3.1:8b", timeout_s=600)

        with pytest.raises(ProviderError) as caught:
            asyncio.run(provider._complete("system", "user", DetectionConfig()))

        assert "small GPU" not in str(caught.value)

    def test_a_timeout_is_classified_as_a_timeout(self, ollama_http) -> None:
        ollama_http.error = httpx.ReadTimeout("timed out")
        provider = OllamaProvider("llama3.1:8b", timeout_s=600)

        with pytest.raises(ProviderError) as caught:
            asyncio.run(provider._complete("system", "user", DetectionConfig()))

        info = classify(caught.value)
        assert info.code == TIMEOUT
        assert info.retryable is True

    def test_the_hint_points_at_the_setting_that_changes_it(self, ollama_http) -> None:
        ollama_http.error = httpx.ReadTimeout("timed out")
        provider = OllamaProvider("llama3.1:8b", timeout_s=600)

        with pytest.raises(ProviderError) as caught:
            asyncio.run(provider._complete("system", "user", DetectionConfig()))

        assert "timeout" in caught.value.hint.lower()


# --------------------------------------------------------------------------
# The context window
# --------------------------------------------------------------------------


class TestTheContextWindow:
    def test_the_request_asks_for_the_context_window(self, ollama_http) -> None:
        provider = OllamaProvider("llama3.1:8b")

        asyncio.run(provider._complete("system", "user", DetectionConfig()))

        assert ollama_http.calls[0]["payload"]["options"]["num_ctx"] == 8192

    def test_the_context_is_a_setting(self) -> None:
        settings = Settings()
        settings.providers["ollama"].context_tokens = 16384

        provider = build_provider("ollama", settings)

        assert provider.context_window == 16384

    def test_the_answer_leaves_room_for_the_prompt(self, ollama_http) -> None:
        """An answer budget as large as the whole context leaves nothing for it."""
        provider = OllamaProvider("llama3.1:8b")
        config = DetectionConfig()

        asyncio.run(provider._complete("system", "user", config))

        options = ollama_http.calls[0]["payload"]["options"]
        assert options["num_predict"] == provider.answer_budget(config)
        assert options["num_predict"] < options["num_ctx"]

    def test_the_prompt_budget_holds_the_measured_prompt(self) -> None:
        """The measured prompt was 5,861 tokens; the budget must hold it."""
        from autoclip.providers import PromptBudget

        provider = OllamaProvider("llama3.1:8b")
        config = DetectionConfig()

        budget = provider.prompt_budget(config)
        assert isinstance(budget, PromptBudget)
        # 5,861 tokens at the conservative 2 characters per token.
        assert budget.max_chars >= MEASURED_PROMPT_TOKENS * 2

    def test_a_prompt_larger_than_the_context_is_reported(self, ollama_http) -> None:
        """The server truncates silently; the provider has to notice."""
        ollama_http.response = {
            "response": '{"clips": []}',
            "prompt_eval_count": 7000,
            "eval_count": 12,
        }
        provider = OllamaProvider("llama3.1:8b")

        with pytest.raises(ProviderError) as caught:
            asyncio.run(provider._complete("system", "user", DetectionConfig()))

        assert "context" in str(caught.value).lower()

    def test_a_prompt_that_fits_is_not_reported(self, ollama_http) -> None:
        ollama_http.response = {
            "response": '{"clips": []}',
            "prompt_eval_count": 5862,
            "eval_count": 875,
        }
        provider = OllamaProvider("llama3.1:8b")

        result = asyncio.run(provider._complete("system", "user", DetectionConfig()))

        assert result == '{"clips": []}'


# --------------------------------------------------------------------------
# Windows sized to the provider's budget
# --------------------------------------------------------------------------


def _transcript(words: int) -> Transcript:
    """A transcript of evenly spaced one-word-per-half-second words."""
    return Transcript(
        words=[Word(text=f"w{i}", start=i * 0.5, end=i * 0.5 + 0.5) for i in range(words)],
        language="en",
        model="test",
        source="whisper",
    )


@dataclass(frozen=True)
class _Budget:
    """The provider's answer to "how much prompt can you take?".

    The shape the pipeline reads — ``max_chars``, ``fixed_chars`` and the
    ``window_chars`` they leave — rather than the class itself, so the test
    double does not depend on where the dataclass lives.
    """

    max_chars: int
    fixed_chars: int

    @property
    def window_chars(self) -> int:
        return max(0, self.max_chars - self.fixed_chars)


class _BudgetProvider(LLMProvider):
    """A provider that knows how much prompt it can take."""

    name = "ollama"
    requires_key = False
    DEFAULT_ENDPOINT = "http://localhost:11434"

    def __init__(self, window_chars: int) -> None:
        super().__init__("test-model")
        self.window_chars = window_chars
        self.windows: list[TranscriptWindow] = []

    def prompt_budget(self, config: DetectionConfig) -> _Budget:
        return _Budget(max_chars=self.window_chars + 500, fixed_chars=500)

    async def _complete(self, system: str, user: str, config: DetectionConfig) -> str:
        return '{"clips": []}'

    async def health_check(self) -> ProviderStatus:
        return ProviderStatus(name=self.name, available=True)

    async def detect_highlights(
        self, window: TranscriptWindow, config: DetectionConfig
    ) -> ClipCandidates:
        self.windows.append(window)
        return ClipCandidates(clips=[])


class TestWindowsFitTheBudget:
    def test_a_window_never_exceeds_the_character_budget(self) -> None:
        transcript = _transcript(2000)

        windows = highlights.build_windows(transcript, max_chars=2000)

        assert windows
        assert all(len(window.text) <= 2000 for window in windows)

    def test_a_smaller_budget_makes_more_windows(self) -> None:
        transcript = _transcript(2000)

        unconstrained = highlights.build_windows(transcript)
        constrained = highlights.build_windows(transcript, max_chars=2000)

        assert len(constrained) > len(unconstrained)

    def test_detection_sizes_the_windows_to_the_provider(self) -> None:
        transcript = _transcript(2000)
        provider = _BudgetProvider(window_chars=2000)

        with pytest.raises(highlights.HighlightError):
            asyncio.run(
                highlights.detect(transcript, provider, DetectionConfig(), job_id="job"),
            )

        assert provider.windows
        assert all(len(window.text) <= 2000 for window in provider.windows)

    def test_a_provider_without_a_limit_keeps_the_windows_as_they_were(self) -> None:
        transcript = _transcript(2000)

        windows = highlights.build_windows(transcript)
        budgeted = highlights.build_windows(transcript, max_chars=None)

        assert [w.first_word for w in windows] == [w.first_word for w in budgeted]


# --------------------------------------------------------------------------
# A timeout stops the stage
# --------------------------------------------------------------------------


class _TimingOutProvider(LLMProvider):
    """Every call times out, the way a local model on a slow box does."""

    name = "ollama"
    requires_key = False
    DEFAULT_ENDPOINT = "http://localhost:11434"

    def __init__(self) -> None:
        super().__init__("test-model")
        self.calls: list[TranscriptWindow] = []

    async def _complete(self, system: str, user: str, config: DetectionConfig) -> str:
        return '{"clips": []}'

    async def health_check(self) -> ProviderStatus:
        return ProviderStatus(name=self.name, available=True)

    async def detect_highlights(
        self, window: TranscriptWindow, config: DetectionConfig
    ) -> ClipCandidates:
        self.calls.append(window)
        raise ProviderError(
            "Ollama did not answer within 600 s.",
            provider=self.name,
            code=TIMEOUT,
        )


class _PartlyTimingOutProvider(LLMProvider):
    """The first window answers; the second times out."""

    name = "ollama"
    requires_key = False
    DEFAULT_ENDPOINT = "http://localhost:11434"

    def __init__(self) -> None:
        super().__init__("test-model")
        self.calls: list[TranscriptWindow] = []

    async def _complete(self, system: str, user: str, config: DetectionConfig) -> str:
        return '{"clips": []}'

    async def health_check(self) -> ProviderStatus:
        return ProviderStatus(name=self.name, available=True)

    async def detect_highlights(
        self, window: TranscriptWindow, config: DetectionConfig
    ) -> ClipCandidates:
        self.calls.append(window)
        if len(self.calls) == 1:
            return ClipCandidates.model_validate(
                {
                    "clips": [
                        {
                            "start_word_index": window.first_word,
                            "end_word_index": window.first_word + 100,
                            "title": "Answered window",
                            "score": 80,
                        }
                    ]
                }
            )
        raise ProviderError(
            "Ollama did not answer within 600 s.",
            provider=self.name,
            code=TIMEOUT,
        )


class TestATimeoutStopsTheStage:
    def test_the_windows_after_the_timeout_are_not_sent(self) -> None:
        """The local server keeps generating the abandoned request; the next
        window would queue behind it and burn its own timeout without ever
        starting."""
        transcript = _transcript(2000)
        provider = _TimingOutProvider()

        with pytest.raises(highlights.HighlightError):
            asyncio.run(
                highlights.detect(transcript, provider, DetectionConfig(), job_id="job"),
            )

        assert len(provider.calls) == 1

    def test_the_error_says_how_many_windows_were_not_analysed(self) -> None:
        transcript = _transcript(2000)
        provider = _TimingOutProvider()
        expected = len(highlights.build_windows(transcript)) - 1

        with pytest.raises(highlights.HighlightError) as caught:
            asyncio.run(
                highlights.detect(transcript, provider, DetectionConfig(), job_id="job"),
            )

        message = str(caught.value)
        assert "not analysed" in message
        assert f"{expected} window(s)" in message

    def test_the_error_does_not_claim_every_window_failed(self) -> None:
        """Only one window was tried; saying "failed in every window" was a lie."""
        transcript = _transcript(2000)
        provider = _TimingOutProvider()

        with pytest.raises(highlights.HighlightError) as caught:
            asyncio.run(
                highlights.detect(transcript, provider, DetectionConfig(), job_id="job"),
            )

        assert "failed in every window" not in str(caught.value)

    def test_the_original_error_is_still_reported(self) -> None:
        transcript = _transcript(2000)
        provider = _TimingOutProvider()

        with pytest.raises(highlights.HighlightError) as caught:
            asyncio.run(
                highlights.detect(transcript, provider, DetectionConfig(), job_id="job"),
            )

        assert "did not answer within" in str(caught.value)

    def test_the_windows_that_were_not_analysed_are_recorded(self) -> None:
        """One window answered and one timed out: the job must still say that
        part of the video was never looked at."""
        from autoclip import resources

        transcript = _transcript(2000)
        provider = _PartlyTimingOutProvider()
        usage = resources.Usage()

        clips = asyncio.run(
            highlights.detect(
                transcript, provider, DetectionConfig(), job_id="job", usage=usage
            ),
        )

        assert clips
        assert usage.windows_skipped == 1
