"""Google Gemini provider."""

from __future__ import annotations

import asyncio
import logging

from .base import DetectionConfig, LLMProvider, ProviderError, ProviderStatus

log = logging.getLogger(__name__)

DEFAULT_MODEL = "gemini-3.5-flash"

SUGGESTED_MODELS = [
    "gemini-3.5-flash",
    "gemini-3.8-flash",
    "gemini-3.5-flash-lite",
    "gemini-3.1-flash-lite",
]


class GeminiProvider(LLMProvider):
    name = "gemini"
    requires_key = True

    def __init__(self, model: str = "", *, api_key: str | None = None, base_url: str | None = None):
        super().__init__(model or DEFAULT_MODEL, api_key=api_key, base_url=base_url)

    def _client(self):
        try:
            from google import genai
        except ImportError as exc:  # pragma: no cover - google-genai is a core dep
            raise ProviderError(
                "The google-genai package is not installed.", provider=self.name
            ) from exc

        if not self.api_key:
            raise ProviderError(
                "No Gemini API key is set.",
                provider=self.name,
                hint="Add one with `autoclip config set-secret gemini`.",
            )
        return genai.Client(api_key=self.api_key)

    async def _complete(self, system: str, user: str, config: DetectionConfig) -> str:
        from google.genai import types

        client = self._client()
        request_config = types.GenerateContentConfig(
            system_instruction=system,
            temperature=config.temperature,
            # Gemini enforces JSON natively, which removes most parse failures.
            response_mime_type="application/json",
            max_output_tokens=config.max_output_tokens,
        )

        last_error: Exception | None = None
        response = None
        for attempt in range(3):
            try:
                # The SDK's async surface has moved between releases; running the
                # sync call in a thread works across all of them and keeps the
                # event loop free.
                response = await asyncio.to_thread(
                    client.models.generate_content,
                    model=self.model,
                    contents=user,
                    config=request_config,
                )
                break
            except Exception as exc:
                last_error = exc
                # A busy model (503) is temporary; retrying is much better than
                # dropping this window's clips from an otherwise good video.
                if attempt < 2 and _is_transient(exc):
                    log.warning(
                        "Gemini attempt %d failed (%s); retrying in %ds.",
                        attempt + 1,
                        exc,
                        5 * (attempt + 1),
                    )
                    await asyncio.sleep(5 * (attempt + 1))
                    continue
                raise _translate(exc, self.name, self.model) from exc

        if response is None:
            assert last_error is not None
            raise _translate(last_error, self.name, self.model) from last_error

        usage = getattr(response, "usage_metadata", None)
        self._record_usage(
            input_tokens=getattr(usage, "prompt_token_count", 0) or 0,
            output_tokens=getattr(usage, "candidates_token_count", 0) or 0,
        )

        return getattr(response, "text", "") or ""

    async def health_check(self) -> ProviderStatus:
        if not self.api_key:
            return ProviderStatus(
                name=self.name, available=False, detail="No API key set", models=SUGGESTED_MODELS
            )
        try:
            client = self._client()
            models = await asyncio.to_thread(lambda: list(client.models.list()))
            names = sorted(
                m.name.removeprefix("models/") for m in models if getattr(m, "name", None)
            )[:50]
        except Exception as exc:
            return ProviderStatus(name=self.name, available=False, detail=str(exc)[:200])
        return ProviderStatus(
            name=self.name, available=True, detail=self.model, models=names or SUGGESTED_MODELS
        )


def _translate(exc: Exception, provider: str, model: str) -> ProviderError:
    message = str(exc)
    lowered = message.lower()

    if "api key" in lowered or "401" in lowered or "permission" in lowered:
        return ProviderError(
            "Google rejected the API key.",
            provider=provider,
            hint="Re-add it with `autoclip config set-secret gemini`.",
        )
    if "429" in lowered or "quota" in lowered or "resource_exhausted" in lowered:
        return ProviderError(
            "Gemini rate limit or quota reached.",
            provider=provider,
            hint="Wait and retry, or switch providers.",
        )
    if "404" in lowered or "not found" in lowered:
        return ProviderError(
            f"Gemini does not recognise the model '{model}'.",
            provider=provider,
            hint=f"Try one of: {', '.join(SUGGESTED_MODELS)}",
        )
    if "safety" in lowered or "blocked" in lowered:
        return ProviderError(
            "Gemini blocked the response under its safety filters.",
            provider=provider,
            hint="This can happen on transcripts with strong language. Try another provider.",
        )
    return ProviderError(f"Gemini request failed: {message}", provider=provider)


#: Errors that usually clear on their own within a few seconds.
_TRANSIENT_MARKERS = (
    "503",
    "unavailable",
    "high demand",
    "overloaded",
    "deadline exceeded",
    "timed out",
    "timeout",
)


def _is_transient(exc: Exception) -> bool:
    message = str(exc).lower()
    return any(marker in message for marker in _TRANSIENT_MARKERS)
