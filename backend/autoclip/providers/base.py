"""LLM provider abstraction.

Highlight detection is the one place AutoClip asks a language model to make a
judgement call, so the interface is deliberately narrow: a window of transcript
goes in, a validated list of clip candidates comes out.

Two design choices carry most of the weight:

**Word indices, not seconds.** The model returns ``start_word_index`` /
``end_word_index``. Timing is then looked up from measured word timestamps, so a
model that is bad at arithmetic — which they all are — cannot produce a clip
that starts at the wrong moment.

**Validate, then retry with the error.** Small local models produce malformed
JSON often enough that a single retry carrying the actual validation message
turns most failures into successes. That loop lives here so every provider
inherits it.
"""

from __future__ import annotations

import json
import logging
import re
import time
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from pydantic import BaseModel, Field, ValidationError, field_validator

from ..resources import TokenUsage
from ..security import consent
from ..security.egress import Transfer, gateway
from ..security.urlpolicy import ConsentRequired, UrlRejected

log = logging.getLogger(__name__)

PROMPT_DIR = Path(__file__).resolve().parent.parent / "prompts"


class ProviderError(RuntimeError):
    """A provider could not produce a usable response."""

    def __init__(self, message: str, *, provider: str = "", hint: str = "") -> None:
        super().__init__(message)
        self.provider = provider
        self.hint = hint

    def __str__(self) -> str:
        base = super().__str__()
        return f"{base}\n\n{self.hint}" if self.hint else base


class ProviderConsentRequired(ProviderError):
    """The provider's destination may not be contacted.

    Distinct from a generic provider failure on purpose: a refused transfer is
    not "the model is down", and the caller must not respond by trying a
    different external provider. The only acceptable continuation is a local
    one, which sends nothing anywhere.
    """


#: Phrases that mean a provider rejected the credentials rather than the
#: content — the signal that falling back to a local model is worthwhile.
_AUTH_FAILURE_MARKERS = (
    "api key",
    "api_key",
    "invalid key",
    "unauthorized",
    "unauthenticated",
    "permission",
    "401",
    "403",
)


def looks_like_auth_failure(error: BaseException | str) -> bool:
    """Return True when a provider error is about credentials, not content."""
    message = str(error).lower()
    return any(marker in message for marker in _AUTH_FAILURE_MARKERS)


#: Markers for transient provider failures — overload, quota, timeouts,
#: connection errors. These are worth retrying on another provider rather
#: than failing the whole job, unlike a malformed request or bad content.
_TRANSIENT_FAILURE_MARKERS = (
    "rate limit",
    "rate_limit",
    "ratelimit",
    "quota",
    "resource_exhausted",
    "overloaded",
    "high demand",
    "unavailable",
    "timeout",
    "timed out",
    "connection",
    "temporarily",
    "429",
    "500",
    "502",
    "503",
    "504",
)


def looks_like_transient_failure(error: BaseException | str) -> bool:
    """Return True when a provider error looks temporary (429, 503, timeout…).

    Deliberately broad: the fallback path re-checks that the alternative
    provider is actually healthy before switching, so a false positive here
    costs one failed health check, not a bad transcript.
    """
    message = str(error).lower()
    return any(marker in message for marker in _TRANSIENT_FAILURE_MARKERS)


# --------------------------------------------------------------------------
# Contracts
# --------------------------------------------------------------------------


class ClipCandidate(BaseModel):
    """One proposed clip, as returned by the model."""

    start_word_index: int = Field(ge=0)
    end_word_index: int = Field(ge=0)
    title: str = ""
    hook: str = ""
    score: int = Field(default=50, ge=0, le=100)
    reason: str = ""

    @field_validator("title", "hook", "reason", mode="before")
    @classmethod
    def _coerce_to_string(cls, value: Any) -> str:
        # Models occasionally return null or a number where text was asked for.
        return "" if value is None else str(value)

    @field_validator("score", mode="before")
    @classmethod
    def _coerce_score(cls, value: Any) -> int:
        """Accept floats and 0-1 fractions, which models emit despite the schema."""
        if value is None:
            return 50
        try:
            number = float(value)
        except (TypeError, ValueError):
            return 50
        if 0.0 < number <= 1.0:
            number *= 100
        return max(0, min(100, round(number)))


class ClipCandidates(BaseModel):
    clips: list[ClipCandidate] = Field(default_factory=list)


@dataclass
class TranscriptWindow:
    """A slice of transcript presented to the model.

    ``first_word`` lets a provider work on a window while still reporting
    indices in the full transcript's coordinate space.
    """

    text: str
    first_word: int
    last_word: int
    duration_s: float = 0.0
    speakers: list[str] = field(default_factory=list)

    @property
    def word_count(self) -> int:
        return self.last_word - self.first_word + 1


@dataclass
class DetectionConfig:
    min_duration_s: float = 20.0
    max_duration_s: float = 90.0
    max_clips: int = 10
    language: str = ""
    #: Prompt file stem in ``autoclip/prompts/``. Versioned so contributors can
    #: iterate on prompts without touching code.
    prompt_version: str = "highlight_v1"
    temperature: float = 0.3
    #: Cap on the tokens the model may return for one call (Phase 16). Each
    #: vendor has its own default and they differ; one explicit number makes
    #: the cost of a job predictable.
    max_output_tokens: int = 4096
    #: Which kind of moment to look for, and how much the story is
    #: favoured over the action. Empty means "no preference" — the
    #: default, which changes nothing.
    highlight_style: str = "auto"
    story_density: float = 0.5


@dataclass
class ProviderStatus:
    name: str
    available: bool
    detail: str = ""
    models: list[str] = field(default_factory=list)


# --------------------------------------------------------------------------
# Base provider
# --------------------------------------------------------------------------


class LLMProvider(ABC):
    """Base class for highlight-detection providers."""

    #: Stable identifier, matching the key used in settings.
    name: str = ""
    #: Whether the provider needs an API key.
    requires_key: bool = True
    #: Where this adapter sends its requests when no ``base_url`` is set. The
    #: vendor SDKs have their own defaults; naming them here means the egress
    #: policy classifies the real destination instead of guessing.
    DEFAULT_ENDPOINT: str = ""

    def __init__(self, model: str, *, api_key: str | None = None, base_url: str | None = None):
        self.model = model
        self.api_key = api_key
        self.base_url = base_url
        #: What the most recent call cost (Phase 16). Reset on every call, so
        #: a caller can read it straight after a request without having to
        #: subtract anything.
        self.last_usage = TokenUsage()
        #: What every call through this provider has cost. Detection runs
        #: several windows concurrently against one provider, so the
        #: "last call" figure is a race between them — only the running
        #: total can be attributed exactly.
        self.total_usage = TokenUsage()

    @property
    def endpoint(self) -> str:
        """The URL this provider will actually contact."""
        return self.base_url or self.DEFAULT_ENDPOINT

    # -- to implement ------------------------------------------------------

    @abstractmethod
    async def _complete(self, system: str, user: str, config: DetectionConfig) -> str:
        """Send one prompt and return the raw response text."""

    @abstractmethod
    async def health_check(self) -> ProviderStatus:
        """Report whether this provider is usable right now."""

    # -- shared behaviour --------------------------------------------------

    def _authorize(self, data_summary: str, *, operation: str = "") -> None:
        """Check that this provider's destination may be contacted.

        The check happens here, in the base class, because this is the one
        place every adapter's request passes through. A provider that forgets
        to ask cannot send anything anywhere.

        A refusal raises :class:`ProviderConsentRequired`, which the caller
        treats differently from a provider failure: it is not retried against
        another external provider.

        ``operation`` says which kind of transfer this is, so the user can
        grant and withdraw each one on its own. It defaults to the
        highlight-detection operation, which is the oldest and still the
        most common.
        """
        endpoint = self.endpoint
        if not endpoint:
            raise ProviderError(
                f"{self.name} has no configured endpoint.",
                provider=self.name,
                hint="Set the provider's base URL in Settings → Providers.",
            )
        transfer = Transfer(
            operation=operation or consent.Operation.HIGHLIGHTS,
            url=endpoint,
            data_summary=data_summary,
            provider=self.name,
            configured=bool(self.api_key),
        )
        try:
            gateway.require(transfer)
        except ConsentRequired as exc:
            raise ProviderConsentRequired(
                f"{self.name} may not be contacted: {exc}",
                provider=self.name,
                hint=(
                    "Allow AI processing to reach public destinations in "
                    "Settings → External processing, or switch to a local model."
                ),
            ) from exc
        except UrlRejected as exc:
            raise ProviderConsentRequired(
                f"{self.name} points at an address AutoClip will not contact: {exc}",
                provider=self.name,
                hint="Change the provider's base URL in Settings → Providers.",
            ) from exc

    async def _send(
        self,
        system: str,
        user: str,
        config: DetectionConfig,
        *,
        operation: str = "",
        data_summary: str = "",
    ) -> str:
        """Authorize, then perform the request.

        Every provider call goes through here, so the consent check cannot be
        forgotten by an adapter.
        """
        summary = data_summary or "Transcript text and standing instructions for AI analysis."
        self._authorize(summary, operation=operation)
        started = time.perf_counter()
        try:
            raw = await self._complete(system, user, config)
        except Exception as exc:
            gateway.record(
                Transfer(
                    operation=operation or consent.Operation.HIGHLIGHTS,
                    url=self.endpoint,
                    data_summary=summary,
                    provider=self.name,
                ),
                "failed",
                detail=str(exc),
                duration_ms=int((time.perf_counter() - started) * 1000),
            )
            raise
        gateway.record(
            Transfer(
                operation=operation or consent.Operation.HIGHLIGHTS,
                url=self.endpoint,
                data_summary=summary,
                provider=self.name,
            ),
            "ok",
            duration_ms=int((time.perf_counter() - started) * 1000),
        )
        return raw

    def _record_usage(self, input_tokens: int = 0, output_tokens: int = 0) -> None:
        """Record what the last call cost.

        Only real numbers are recorded. A provider that does not report usage
        leaves the counters at zero rather than guessing — an estimate that
        reads as "cheap" would make the cost controls look effective when they
        are not.

        Both the per-call figure and the running total are updated, so a
        concurrent caller can take the difference of the total and attribute
        every token to exactly one call.
        """
        self.last_usage = TokenUsage(
            calls=1,
            input_tokens=max(0, int(input_tokens)),
            output_tokens=max(0, int(output_tokens)),
        )
        self.total_usage.add(self.last_usage)

    # -- shared behaviour --------------------------------------------------

    async def generate_text(
        self,
        system: str,
        user: str,
        *,
        temperature: float = 0.4,
        operation: str = "",
        data_summary: str = "",
    ) -> str:
        """Send one free-form prompt and return the raw reply.

        Used for tasks that are not clip detection (e.g. YouTube metadata).
        Providers only see a system/user pair, so no extra implementations are
        needed.

        ``operation`` says which kind of transfer this is, so the user can
        grant and withdraw each one on its own.
        """
        return await self._send(
            system,
            user,
            DetectionConfig(temperature=temperature),
            operation=operation,
            data_summary=data_summary,
        )

    async def detect_highlights(
        self, window: TranscriptWindow, config: DetectionConfig
    ) -> ClipCandidates:
        """Ask the model for clip candidates in ``window``, validating the reply.

        One retry is attempted on a schema violation, feeding the validation
        error back so the model can correct itself.
        """
        system = load_prompt(config.prompt_version)
        user = render_window_prompt(window, config)

        # Phase 11: the user's improve.txt standing instructions ride along on
        # every detection call. A read failure must never break detection.
        try:
            from ..learning import improve

            system += improve.prompt_section()
        except Exception:  # noqa: BLE001
            log.debug("Could not load improve.txt feedback.", exc_info=True)

        # Phase 12: current YouTube trends inform which angles to prefer.
        try:
            from ..trends import research as trend_research

            system += trend_research.prompt_section(trend_research.cached_context())
        except Exception:  # noqa: BLE001
            log.debug("Could not load the trend context.", exc_info=True)

        raw = await self._send(system, user, config)
        try:
            return self._parse(raw, window)
        except (ValidationError, ValueError) as first_error:
            log.warning("%s returned invalid JSON; retrying with feedback.", self.name)
            repair = (
                f"{user}\n\n"
                "Your previous response did not match the required schema.\n"
                f"Validation error:\n{first_error}\n\n"
                "Respond again with ONLY the corrected JSON object. No prose, no "
                "markdown fences."
            )
            raw = await self._send(system, repair, config)
            try:
                return self._parse(raw, window)
            except (ValidationError, ValueError) as second_error:
                raise ProviderError(
                    f"{self.name} returned malformed clip data twice.",
                    provider=self.name,
                    hint=(
                        f"Last validation error: {second_error}\n\n"
                        "Smaller local models struggle with strict JSON. Try a larger "
                        "model, or switch to a hosted provider."
                    ),
                ) from second_error

    def _parse(self, raw: str, window: TranscriptWindow) -> ClipCandidates:
        """Validate a raw response and clamp indices into the window."""
        payload = extract_json_object(raw)
        candidates = ClipCandidates.model_validate(payload)

        cleaned: list[ClipCandidate] = []
        for candidate in candidates.clips:
            start = max(window.first_word, min(candidate.start_word_index, window.last_word))
            end = max(window.first_word, min(candidate.end_word_index, window.last_word))
            if end <= start:
                # A zero-or-negative-length clip is a model slip, not a candidate.
                continue
            candidate.start_word_index = start
            candidate.end_word_index = end
            cleaned.append(candidate)

        return ClipCandidates(clips=cleaned)


# --------------------------------------------------------------------------
# Prompt handling
# --------------------------------------------------------------------------


def load_prompt(version: str) -> str:
    """Read a versioned prompt file from ``autoclip/prompts/``."""
    path = PROMPT_DIR / f"{version}.txt"
    if not path.exists():
        raise ProviderError(
            f"Prompt '{version}' not found at {path}.",
            hint="Prompt files live in backend/autoclip/prompts/ as versioned .txt files.",
        )
    return path.read_text(encoding="utf-8")


def render_window_prompt(window: TranscriptWindow, config: DetectionConfig) -> str:
    """Build the user message for one transcript window."""
    speaker_note = ""
    if window.speakers:
        speaker_note = (
            f"\nThis section has {len(window.speakers)} distinct speakers "
            f"({', '.join(window.speakers)}); speaker labels are shown inline.\n"
        )

    # The story/action preference, said in words. The model sees the
    # transcript, not the signals, so the balance has to be named.
    style_note = ""
    if config.highlight_style or config.story_density != 0.5:
        from ..pipeline.intent import style_instruction

        instruction = style_instruction(
            story_density=config.story_density,
            highlight_style=config.highlight_style,
        )
        if instruction:
            style_note = f"\n{instruction}\n"

    return (
        f"Transcript section, words {window.first_word} to {window.last_word}.\n"
        f"Each word is tagged with its index as [index]word.\n"
        f"{speaker_note}{style_note}\n"
        f"Clip length must be between {config.min_duration_s:.0f} and "
        f"{config.max_duration_s:.0f} seconds.\n"
        f"Return at most {config.max_clips} clips.\n\n"
        f"---\n{window.text}\n---\n\n"
        "Respond with ONLY a JSON object matching the schema. No prose, no markdown fences."
    )


_JSON_FENCE = re.compile(r"```(?:json)?\s*(.*?)```", re.DOTALL)


def extract_json_object(raw: str) -> dict[str, Any]:
    """Pull a JSON object out of a model response.

    Handles the three things models do despite being told not to: wrap the JSON
    in markdown fences, prepend an explanatory sentence, and append a trailing
    note. Falls back to brace matching so a stray character outside the object
    doesn't cost a retry round-trip.
    """
    text = raw.strip()
    if not text:
        raise ValueError("The provider returned an empty response.")

    if match := _JSON_FENCE.search(text):
        text = match.group(1).strip()

    try:
        parsed = json.loads(text)
    except json.JSONDecodeError:
        parsed = _json_by_brace_matching(text)

    if isinstance(parsed, list):
        # Some models skip the wrapper object and return the array directly.
        return {"clips": parsed}
    if not isinstance(parsed, dict):
        raise ValueError(f"Expected a JSON object, got {type(parsed).__name__}.")
    return parsed


def _json_by_brace_matching(text: str) -> Any:
    """Extract the first balanced ``{...}`` or ``[...]`` region and parse it."""
    for opener, closer in (("{", "}"), ("[", "]")):
        start = text.find(opener)
        if start == -1:
            continue
        depth = 0
        in_string = False
        escaped = False
        for i in range(start, len(text)):
            char = text[i]
            if in_string:
                if escaped:
                    escaped = False
                elif char == "\\":
                    escaped = True
                elif char == '"':
                    in_string = False
                continue
            if char == '"':
                in_string = True
            elif char == opener:
                depth += 1
            elif char == closer:
                depth -= 1
                if depth == 0:
                    return json.loads(text[start : i + 1])

    raise ValueError("No JSON object found in the response.")
