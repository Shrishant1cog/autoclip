"""Provider resolution with fallback chains — the brain behind AI tasks.

Given a task, the resolver walks a chain: presets in priority order, each
with its key pool. A failing provider/key is diagnosed (auth / rate-limit /
transient), the pool is updated, and the next candidate is tried. A healthy
local provider is the terminal fallback for AI tasks — never for external
operations like YouTube publishing, which need their real service.
"""

from __future__ import annotations

import logging
from typing import Any

from ..config import Settings
from . import keypool
from .base import LLMProvider, ProviderConsentRequired, ProviderError
from .presets import PRESETS, TASK_CAPABILITY, ProviderPreset

log = logging.getLogger(__name__)


class AllProvidersFailedError(ProviderError):
    """Every provider in the chain failed; no fabricated output is returned."""


def build_preset_provider(
    preset: ProviderPreset, settings: Settings, *, model: str = "", base_url: str | None = None
) -> LLMProvider:
    """Construct the preset's adapter with model/base_url/key resolved."""

    provider_settings = settings.provider(preset.adapter)
    use_model = model or provider_settings.model or preset.default_model
    use_base_url = base_url
    if use_base_url is None:
        use_base_url = provider_settings.base_url or preset.default_base_url

    api_key = None
    if preset.requires_key:
        picked = keypool.pick_key(preset.key)
        if picked is None:
            raise ProviderError(
                f"No usable API key for {preset.label}.",
                hint=f"Add one in Settings → API Keys ({preset.key}).",
            )
        api_key = picked[1]

    adapter_cls = {
        "openai": "openai",
        "gemini": "gemini",
        "anthropic": "anthropic",
        "ollama": "ollama",
    }[preset.adapter]
    from . import PROVIDERS

    cls = PROVIDERS[adapter_cls]
    return cls(
        use_model,
        api_key=api_key,
        base_url=use_base_url,
        # The adapter's own limits — a local model's request timeout and
        # context window — travel with the adapter, whichever path built it.
        timeout_s=provider_settings.timeout_s,
        context_tokens=provider_settings.context_tokens,
    )


def resolve_chain(
    task: str, settings: Settings, *, override_chain: list[str] | None = None
) -> list[ProviderPreset]:
    """Ordered presets to try for ``task``.

    ``override_chain`` (explicit provider keys) wins; otherwise the user's
    active provider leads and capability-compatible presets follow, locals last.
    """
    capability = TASK_CAPABILITY.get(task, "text")

    if override_chain:
        chain = []
        for key in override_chain:
            preset = PRESETS.get(key)
            if preset is not None and capability in preset.capabilities:
                chain.append(preset)
        return chain

    chain: list[ProviderPreset] = []
    active = PRESETS.get(settings.active_provider)
    if active is not None and capability in active.capabilities:
        chain.append(active)

    for preset in PRESETS.values():
        if preset in chain or capability not in preset.capabilities:
            continue
        chain.append(preset)

    # Locals last: external first is the product rule; local is the floor.
    chain.sort(key=lambda p: p.is_local)
    return chain


async def run_with_fallback(
    task: str,
    prompt_system: str,
    prompt_user: str,
    settings: Settings,
    *,
    chain: list[str] | None = None,
    temperature: float = 0.4,
) -> tuple[str, str]:
    """Execute a text/JSON task over the provider chain.

    Returns ``(output, provider_label)``. Raises :class:`AllProvidersFailedError`
    when nothing in the chain answers — never a fabricated string.
    """
    errors: list[str] = []
    # Once an external provider is refused, no *other* external provider may be
    # tried: sending the same text to a different vendor without the user
    # choosing it is exactly the silent substitution the consent layer exists
    # to prevent. A local provider is still allowed — nothing leaves the
    # machine that way.
    external_refused = False

    for preset in resolve_chain(task, settings, override_chain=chain):
        if external_refused and not preset.is_local:
            errors.append(f"{preset.label}: skipped — an external provider was refused")
            continue
        try:
            provider = build_preset_provider(preset, settings)
            output = await provider.generate_text(
                prompt_system, prompt_user, temperature=temperature
            )
        except ProviderConsentRequired as exc:
            external_refused = True
            errors.append(f"{preset.label}: {exc}")
            log.warning("Provider %s refused for %s: %s", preset.label, task, exc)
            continue
        except ProviderError as exc:
            errors.append(f"{preset.label}: {exc}")
            log.warning("Provider %s failed for %s: %s", preset.label, task, exc)
            continue
        except Exception as exc:  # noqa: BLE001 — any failure moves down the chain
            errors.append(f"{preset.label}: {type(exc).__name__}: {exc}")
            log.warning("Provider %s raised for %s: %s", preset.label, task, exc)
            continue

        # Diagnose obvious auth failures even when the adapter didn't raise
        # ProviderError.
        lowered = output.lower()
        if "api key" in lowered and len(output) < 300:
            errors.append(f"{preset.label}: rejected key")
            continue
        return output, preset.label

    raise AllProvidersFailedError(f"All providers failed for task {task!r}. " + " | ".join(errors))


def available_providers(settings: Settings) -> list[dict[str, Any]]:
    """UI-facing summary: every preset, keyed-ness, key count, health."""
    out = []
    for preset in PRESETS.values():
        keys = keypool.list_keys(preset.key)
        healthy = [k for k in keys if k.enabled]
        out.append(
            {
                "key": preset.key,
                "label": preset.label,
                "adapter": preset.adapter,
                "requires_key": preset.requires_key,
                "default_model": preset.default_model,
                "default_base_url": preset.default_base_url,
                "suggested_models": preset.suggested_models,
                "capabilities": list(preset.capabilities),
                "is_local": preset.is_local,
                "keys_total": len(keys),
                "keys_healthy": len(healthy),
                "active": settings.active_provider == preset.key,
            }
        )
    return out


__all__ = [
    "AllProvidersFailedError",
    "available_providers",
    "build_preset_provider",
    "resolve_chain",
    "run_with_fallback",
]
