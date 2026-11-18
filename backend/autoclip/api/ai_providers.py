"""AI provider manager API — presets, key pools, health, task execution."""

from __future__ import annotations

import logging

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from .. import config
from ..providers import keypool, resolver
from ..providers import presets as preset_registry
from .schemas import ProviderStatusOut
from .settings import providers_status as legacy_providers_status

log = logging.getLogger(__name__)

router = APIRouter(prefix="/api/ai", tags=["ai-providers"])


class KeyIn(BaseModel):
    label: str = ""
    value: str


class KeyStateIn(BaseModel):
    enabled: bool


class TaskIn(BaseModel):
    task: str = "text"
    system: str
    user: str
    chain: list[str] | None = None
    temperature: float = 0.4


@router.get("/providers")
async def all_providers() -> list[dict]:
    """Every provider preset with pool health — drives the AI Providers page."""
    settings = config.load()
    return resolver.available_providers(settings)


@router.get("/providers/{key}/keys")
async def provider_keys(key: str) -> list[dict]:
    if preset_registry.get_preset(key) is None:
        raise HTTPException(status_code=404, detail=f"Unknown provider {key!r}.")
    return [
        {
            "label": rec.label,
            "enabled": rec.enabled,
            "failures": rec.failures,
            "last_error": rec.last_error,
            "cooling_down": rec.cooldown_until > 0,
            "last_used": rec.last_used,
        }
        for rec in keypool.list_keys(key)
    ]


@router.post("/providers/{key}/keys", status_code=201)
async def add_key(key: str, payload: KeyIn) -> dict:
    if preset_registry.get_preset(key) is None:
        raise HTTPException(status_code=404, detail=f"Unknown provider {key!r}.")
    if not payload.value.strip():
        raise HTTPException(status_code=400, detail="The key value cannot be empty.")
    to_keyring = keypool.add_key(key, payload.label, payload.value.strip())
    return {"stored": "keyring" if to_keyring else "insecure-fallback"}


@router.delete("/providers/{key}/keys/{label}", status_code=204)
async def delete_key(key: str, label: str) -> None:
    keypool.remove_key(key, label)


@router.put("/providers/{key}/keys/{label}/state", status_code=204)
async def set_key_state(key: str, label: str, payload: KeyStateIn) -> None:
    keypool.set_key_enabled(key, label, payload.enabled)


@router.get("/presets")
async def presets() -> dict:
    return {
        key: {
            "label": p.label,
            "adapter": p.adapter,
            "default_model": p.default_model,
            "default_base_url": p.default_base_url,
            "suggested_models": p.suggested_models,
            "capabilities": list(p.capabilities),
            "is_local": p.is_local,
        }
        for key, p in preset_registry.PRESETS.items()
    }


@router.get("/health", response_model=list[ProviderStatusOut])
async def health() -> list[ProviderStatusOut]:
    """Legacy per-adapter live health, unchanged from the Settings page.

    The response model is declared rather than left to ``list[dict]``: the
    status list is a list of models, and a plain ``dict`` annotation made
    FastAPI reject the response it had just built — the endpoint answered
    500 instead of the provider statuses.
    """
    return await legacy_providers_status()


@router.post("/tasks")
async def run_task(payload: TaskIn) -> dict:
    """Run one AI task over the fallback chain. Returns output + provider used."""
    settings = config.load()
    try:
        output, provider_label = await resolver.run_with_fallback(
            payload.task,
            payload.system,
            payload.user,
            settings,
            chain=payload.chain,
            temperature=payload.temperature,
        )
    except resolver.AllProvidersFailedError as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc
    return {"output": output, "provider": provider_label}
