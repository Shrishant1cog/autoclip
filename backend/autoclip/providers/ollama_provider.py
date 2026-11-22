"""Ollama provider — the fully-local path.

Talks to Ollama's HTTP API directly rather than through its SDK, keeping the
dependency surface to httpx (already required elsewhere).

Clip quality tracks model quality closely here. A 3B model will return
syntactically valid JSON full of mediocre clips; the recommendation list below
reflects what actually produces usable selections.
"""

from __future__ import annotations

import logging

import httpx

from ..errors import TIMEOUT
from .base import (
    CHARS_PER_TOKEN,
    DetectionConfig,
    LLMProvider,
    PromptBudget,
    ProviderError,
    ProviderStatus,
    render_window_overhead,
)

log = logging.getLogger(__name__)

DEFAULT_BASE_URL = "http://localhost:11434"

#: Models with enough instruction-following to hold the JSON contract and enough
#: judgement to rank clips sensibly. Below roughly 7B, selection quality falls
#: off sharply even when the JSON stays valid.
RECOMMENDED_MODELS = [
    "llama3.1:8b",
    "qwen2.5:14b",
    "mistral-nemo:12b",
    "gemma2:9b",
]

#: How long to wait for one request before giving up, in seconds.
#:
#: Highlight detection over an eight-minute window is slow on consumer
#: hardware, and slower still when there is no GPU: one such call was
#: measured on an eight-core CPU at 1,993 s, of which 554 s went into
#: evaluating the prompt alone. The old ceiling of 600 s was shorter than
#: calls that were about to succeed, so it failed jobs that had not
#: actually gone wrong — and told the user to try again, which reproduced
#: the failure exactly.
DEFAULT_TIMEOUT_S = 3600.0

#: The context window to ask Ollama for, in tokens.
#:
#: Ollama's own default is 4,096. The detection prompt for one
#: eight-minute window measured 5,862 tokens, so the prompt alone did not
#: fit: the server truncated it without saying so, the model answered from
#: a partial transcript, and the request ran for half an hour without
#: finishing. 8,192 holds the prompt and the answer together.
DEFAULT_CONTEXT_TOKENS = 8192

#: The smallest answer worth asking for. Below this a model cannot finish
#: a JSON object of clip candidates.
MIN_ANSWER_TOKENS = 256


class OllamaProvider(LLMProvider):
    name = "ollama"
    requires_key = False
    #: Ollama is local by definition; the endpoint is the loopback address.
    DEFAULT_ENDPOINT = DEFAULT_BASE_URL

    def __init__(
        self,
        model: str = "",
        *,
        api_key: str | None = None,
        base_url: str | None = None,
        timeout_s: int = 0,
        context_tokens: int = 0,
    ):
        super().__init__(
            model,
            api_key=api_key,
            base_url=base_url or DEFAULT_BASE_URL,
            timeout_s=timeout_s,
            context_tokens=context_tokens,
        )
        #: The effective request timeout, in seconds.
        self.request_timeout_s = float(timeout_s) if timeout_s else DEFAULT_TIMEOUT_S
        #: The effective context window, in tokens.
        self.context_window = int(context_tokens) if context_tokens else DEFAULT_CONTEXT_TOKENS

    @property
    def url(self) -> str:
        return (self.base_url or DEFAULT_BASE_URL).rstrip("/")

    def answer_budget(self, config: DetectionConfig) -> int:
        """How many tokens the answer may take.

        The prompt and the answer have to fit in the context together. A
        budget as large as the whole context leaves nothing for the prompt,
        which is what made the server truncate it and then run for an hour.
        A quarter of the context is the share a detection answer needs: the
        measured answer for a ten-clip window was 875 tokens.
        """
        reserve = max(MIN_ANSWER_TOKENS, self.context_window // 4)
        return min(config.max_output_tokens, reserve)

    def prompt_budget(self, config: DetectionConfig) -> PromptBudget:
        """How much of a prompt this provider can take."""
        fixed = len(self._system_prompt(config)) + render_window_overhead(config)
        room = self.context_window - self.answer_budget(config)
        return PromptBudget(max_chars=int(room * CHARS_PER_TOKEN), fixed_chars=fixed)

    async def _complete(self, system: str, user: str, config: DetectionConfig) -> str:
        if not self.model:
            raise ProviderError(
                "No Ollama model is selected.",
                provider=self.name,
                hint=f"Pull one first, e.g. `ollama pull {RECOMMENDED_MODELS[0]}`.",
            )

        payload = {
            "model": self.model,
            "system": system,
            "prompt": user,
            "stream": False,
            # Ollama's JSON mode constrains decoding to valid JSON, which is the
            # single biggest reliability win for small local models.
            "format": "json",
            "options": {
                "temperature": config.temperature,
                "num_predict": self.answer_budget(config),
                # Ask for the context this request needs, explicitly. Ollama
                # re-reads the model with it when it differs from the one
                # already loaded; left to its own default of 4,096, a prompt
                # larger than that is truncated without a word of complaint.
                "num_ctx": self.context_window,
            },
        }

        try:
            async with httpx.AsyncClient(
                timeout=httpx.Timeout(self.request_timeout_s, connect=5.0)
            ) as client:
                response = await client.post(f"{self.url}/api/generate", json=payload)
                response.raise_for_status()
                data = response.json()
        except httpx.ConnectError as exc:
            raise ProviderError(
                f"Could not reach Ollama at {self.url}.",
                provider=self.name,
                hint="Start it with `ollama serve`, or install it from ollama.com.",
            ) from exc
        except httpx.TimeoutException as exc:
            raise ProviderError(
                f"Ollama did not answer within {self.request_timeout_s:.0f} s.",
                provider=self.name,
                code=TIMEOUT,
                hint=(
                    "A local model runs on the CPU when no GPU is present, and one "
                    "detection call over a long window can take many minutes. "
                    "Raise the request timeout in Settings → AI Providers, use a "
                    "faster model, or use a hosted provider if you have one."
                ),
            ) from exc
        except httpx.HTTPStatusError as exc:
            raise _translate_status(exc, self.name, self.model) from exc

        prompt_tokens = data.get("prompt_eval_count", 0) or 0
        self._record_usage(
            input_tokens=prompt_tokens,
            output_tokens=data.get("eval_count", 0) or 0,
        )

        # The server does not say when it has truncated a prompt: it simply
        # answers from what is left. Catching it here is the difference
        # between a wrong answer and an honest failure.
        room = self.context_window - self.answer_budget(config)
        if prompt_tokens > room:
            raise ProviderError(
                f"The prompt was larger than Ollama's context window: "
                f"{prompt_tokens} token(s) of prompt, {room} available.",
                provider=self.name,
                hint=(
                    "Raise the context window in Settings → AI Providers, or use a "
                    "model with a larger context."
                ),
            )

        return data.get("response", "")

    async def health_check(self) -> ProviderStatus:
        try:
            async with httpx.AsyncClient(timeout=httpx.Timeout(5.0)) as client:
                response = await client.get(f"{self.url}/api/tags")
                response.raise_for_status()
                data = response.json()
        except httpx.ConnectError:
            return ProviderStatus(
                name=self.name,
                available=False,
                detail=f"Not running at {self.url}",
            )
        except Exception as exc:
            return ProviderStatus(name=self.name, available=False, detail=str(exc)[:200])

        models = [m.get("name", "") for m in data.get("models", [])]
        models = [m for m in models if m]

        if not models:
            return ProviderStatus(
                name=self.name,
                available=False,
                detail=f"Running, but no models pulled. Try `ollama pull {RECOMMENDED_MODELS[0]}`.",
                models=[],
            )

        return ProviderStatus(
            name=self.name, available=True, detail=f"{len(models)} model(s)", models=sorted(models)
        )


def _translate_status(exc: httpx.HTTPStatusError, provider: str, model: str) -> ProviderError:
    if exc.response.status_code == 404:
        return ProviderError(
            f"Ollama has no model named '{model}'.",
            provider=provider,
            hint=f"Pull it with `ollama pull {model}`, or pick one you already have.",
        )
    return ProviderError(f"Ollama returned HTTP {exc.response.status_code}.", provider=provider)
