"""Key-pool and provider-resolver tests — no network, no real keyring."""

from __future__ import annotations

import pytest
from autoclip import config
from autoclip.providers import keypool
from autoclip.providers.presets import PRESETS, TASK_CAPABILITY
from autoclip.providers.resolver import (
    AllProvidersFailedError,
    resolve_chain,
)


@pytest.fixture
def isolated_pools(tmp_path, monkeypatch: pytest.MonkeyPatch):
    """Point the pool file at a temp dir and use an in-memory keyring."""
    pool_path = tmp_path / "key_pools.json"
    monkeypatch.setattr(keypool, "_pool_path", lambda: pool_path)
    store: dict[tuple[str, str], str] = {}

    class _KR:
        def get_password(self, service, key):
            return store.get((service, key))

        def set_password(self, service, key, value):
            store[(service, key)] = value

        def delete_password(self, service, key):
            store.pop((service, key), None)

    kr = _KR()
    monkeypatch.setattr(config, "_keyring", lambda: kr)
    return store


# --------------------------------------------------------------------------
# Key pool
# --------------------------------------------------------------------------


def test_add_and_pick_keys(isolated_pools) -> None:
    assert keypool.add_key("openai", "primary", "sk-1")
    assert keypool.add_key("openai", "backup", "sk-2")

    picked = keypool.pick_key("openai")
    assert picked is not None and picked[1] == "sk-1"  # fewest failures first

    labels = [k.label for k in keypool.list_keys("openai")]
    assert set(labels) == {"primary", "backup"}


def test_auth_failure_disables_key(isolated_pools) -> None:
    keypool.add_key("gemini", "primary", "g-1")
    keypool.add_key("gemini", "second", "g-2")

    keypool.record_failure("gemini", "primary", "401 Unauthorized: bad api key", retryable=False)

    records = {r.label: r for r in keypool.list_keys("gemini")}
    assert records["primary"].enabled is False

    picked = keypool.pick_key("gemini")
    assert picked is not None and picked[0] == "second"


def test_rate_limit_cooldown_not_disable(isolated_pools) -> None:
    keypool.add_key("openai", "primary", "sk-1")
    keypool.add_key("openai", "backup", "sk-2")

    keypool.record_failure("openai", "primary", "429 rate limit exceeded", retryable=True)

    records = {r.label: r for r in keypool.list_keys("openai")}
    assert records["primary"].enabled is True          # not disabled
    assert records["primary"].cooldown_until > 0       # cooling down

    picked = keypool.pick_key("openai")
    assert picked is not None and picked[0] == "backup"


def test_disabled_keys_exhaust_pool(isolated_pools) -> None:
    keypool.add_key("openai", "primary", "sk-1")
    keypool.record_failure("openai", "primary", "invalid key", retryable=False)
    assert keypool.pick_key("openai") is None


def test_remove_key_clears_both_store_and_pool(isolated_pools) -> None:
    keypool.add_key("openai", "primary", "sk-1")
    keypool.remove_key("openai", "primary")
    assert keypool.list_keys("openai") == []
    assert keypool.pick_key("openai") is None


def test_success_resets_failures_and_cooldown(isolated_pools) -> None:
    keypool.add_key("openai", "primary", "sk-1")
    keypool.record_failure("openai", "primary", "429 quota", retryable=True)
    keypool.record_success("openai", "primary")

    records = keypool.list_keys("openai")
    assert records[0].failures == 0
    assert records[0].cooldown_until == 0.0


# --------------------------------------------------------------------------
# Presets & capability registry
# --------------------------------------------------------------------------


def test_preset_registry_covers_required_providers() -> None:
    required = {
        "openai", "gemini", "anthropic", "freellmapi", "ollama", "openrouter",
        "groq", "cerebras", "together", "deepseek", "mistral", "huggingface",
        "nvidia", "lmstudio", "llamacpp", "vllm",
    }
    assert required <= set(PRESETS.keys())


def test_freellmapi_has_no_hardcoded_url() -> None:
    preset = PRESETS["freellmapi"]
    assert preset.default_base_url is None  # user-configured endpoint


def test_local_providers_require_no_key() -> None:
    for key in ("ollama", "lmstudio", "llamacpp", "vllm"):
        assert PRESETS[key].requires_key is False
        assert PRESETS[key].is_local is True


def test_clip_analysis_requires_json_capability() -> None:
    assert TASK_CAPABILITY["clip_analysis"] == "json"


# --------------------------------------------------------------------------
# Resolver chains
# --------------------------------------------------------------------------


def _settings(active: str = "openai") -> config.Settings:
    s = config.Settings()
    s.active_provider = active
    return s


def test_chain_starts_with_active_provider_then_externals_then_locals() -> None:
    chain = resolve_chain("clip_analysis", _settings("gemini"))
    assert chain[0].key == "gemini"
    keys = [p.key for p in chain]
    # All external presets precede all local ones.
    local_flags = [p.is_local for p in chain]
    assert local_flags == sorted(local_flags)
    assert "groq" in keys and "ollama" in keys


def test_chain_respects_capability() -> None:
    chain = resolve_chain("metadata", _settings("gemini"))
    # Every preset in the chain can serve text tasks.
    assert all("text" in p.capabilities for p in chain)


def test_explicit_override_chain_wins() -> None:
    chain = resolve_chain("clip_analysis", _settings("gemini"), override_chain=["groq", "ollama"])
    assert [p.key for p in chain] == ["groq", "ollama"]


def test_override_chain_filters_incompatible_providers() -> None:
    # All presets currently support text/json, so use a bogus key to test filtering.
    chain = resolve_chain("clip_analysis", _settings(), override_chain=["groq", "nonexistent"])
    assert [p.key for p in chain] == ["groq"]


# --------------------------------------------------------------------------
# run_with_fallback (fake adapters, no network)
# --------------------------------------------------------------------------


class _FakeProvider:
    def __init__(self, output: str, fail: bool = False) -> None:
        self._output = output
        self._fail = fail
        self.model = "fake"

    async def generate_text(self, system: str, user: str, *, temperature: float = 0.4) -> str:
        if self._fail:
            raise RuntimeError("503 UNAVAILABLE")
        return self._output


def test_run_with_fallback_tries_next_provider_on_failure(
    isolated_pools, monkeypatch: pytest.MonkeyPatch
) -> None:
    from autoclip.providers import resolver as res

    calls = {"n": 0}

    def build(preset, settings, **kwargs):
        calls["n"] += 1
        return _FakeProvider("ok", fail=(calls["n"] == 1))

    monkeypatch.setattr(res, "build_preset_provider", build)
    import asyncio

    output, label = asyncio.run(
        res.run_with_fallback("clip_analysis", "sys", "user", _settings())
    )
    assert output == "ok"
    assert calls["n"] >= 1
    assert label  # a provider was credited


def test_run_with_fallback_never_fabricates(
    isolated_pools, monkeypatch: pytest.MonkeyPatch
) -> None:
    from autoclip.providers import resolver as res

    def build(preset, settings, **kwargs):
        return _FakeProvider("", fail=True)

    monkeypatch.setattr(res, "build_preset_provider", build)
    import asyncio

    with pytest.raises(AllProvidersFailedError):
        asyncio.run(res.run_with_fallback("clip_analysis", "sys", "user", _settings()))
