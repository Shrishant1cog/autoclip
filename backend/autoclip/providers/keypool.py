"""API key pool — multiple keys per provider with intelligent rotation.

Keys are stored in the OS keyring under ``autoclip`` with a composite entry
name (``<provider>#<label>``). The primary (label-less) key keeps its legacy
entry so nothing breaks for existing users. Rotation rules:

- A key that fails with an auth error is disabled (not deleted) until the
  user re-enables it or replaces it.
- Rate-limited / quota-exhausted keys enter a cooldown instead of being
  disabled — they recover automatically when the window passes.
- The pool always hands out the healthiest key: enabled, not cooling down,
  fewest consecutive failures, least recently used.
"""

from __future__ import annotations

import contextlib
import json
import logging
import os
import time
from dataclasses import asdict, dataclass, field

from .. import config

log = logging.getLogger(__name__)

#: Pool state file (non-secret metadata only — the keys live in the keyring).
_POOL_PATH = None  # resolved lazily through paths


def _pool_path():
    from .. import paths

    return paths.config_path().parent / "key_pools.json"


@dataclass
class KeyRecord:
    label: str  # stable identifier within the provider
    enabled: bool = True
    failures: int = 0
    last_used: float = 0.0
    last_error: str = ""
    cooldown_until: float = 0.0
    last_success: float = 0.0


@dataclass
class ProviderPool:
    keys: dict[str, KeyRecord] = field(default_factory=dict)

    def healthy(self) -> list[KeyRecord]:
        now = time.time()
        return sorted(
            (k for k in self.keys.values() if k.enabled and k.cooldown_until < now),
            key=lambda k: (k.failures, k.last_used),
        )


def _load_pools() -> dict[str, ProviderPool]:
    path = _pool_path()
    if not path.exists():
        return {}
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}
    pools: dict[str, ProviderPool] = {}
    for provider, entries in raw.items():
        pool = ProviderPool()
        for label, data in entries.items():
            pool.keys[label] = KeyRecord(**data)
        pools[provider] = pool
    return pools


def _save_pools(pools: dict[str, ProviderPool]) -> None:
    path = _pool_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        provider: {label: asdict(rec) for label, rec in pool.keys.items()}
        for provider, pool in pools.items()
    }
    tmp = path.with_suffix(".json.tmp")
    tmp.write_text(json.dumps(payload, indent=2), encoding="utf-8")

    with contextlib.suppress(Exception):
        config._restrict_permissions(tmp)
    os.replace(tmp, path)


def _secret_entry(provider: str, label: str) -> str:
    """Keyring entry name. The first key keeps the legacy bare-name entry."""
    return provider if label == "primary" else f"{provider}#{label}"


def list_keys(provider: str) -> list[KeyRecord]:
    pools = _load_pools()
    pool = pools.get(provider)
    if pool is not None:
        return list(pool.keys.values())
    # Legacy single-key setups: surface the bare entry as the primary key.
    if config.get_secret(provider) is not None:
        return [KeyRecord(label="primary")]
    return []


def add_key(provider: str, label: str, value: str) -> bool:
    """Store a key in the keyring and register it in the pool. True → keyring."""
    label = label.strip() or f"key{len(list_keys(provider)) + 1}"
    to_keyring = config.set_secret(_secret_entry(provider, label), value)
    pools = _load_pools()
    pool = pools.setdefault(provider, ProviderPool())
    pool.keys[label] = KeyRecord(label=label)
    _save_pools(pools)
    log.info("Added %s key %r to the pool.", provider, label)
    return to_keyring


def remove_key(provider: str, label: str) -> None:
    from .. import config as cfg

    cfg.delete_secret(_secret_entry(provider, label))
    pools = _load_pools()
    pool = pools.get(provider)
    if pool:
        pool.keys.pop(label, None)
        _save_pools(pools)


def set_key_enabled(provider: str, label: str, enabled: bool) -> None:
    pools = _load_pools()
    pool = pools.get(provider)
    if pool and label in pool.keys:
        pool.keys[label].enabled = enabled
        if enabled:
            pool.keys[label].failures = 0
            pool.keys[label].cooldown_until = 0.0
        _save_pools(pools)


def pick_key(provider: str) -> tuple[str, str] | None:
    """Return ``(label, key_value)`` for the healthiest key, or None."""
    candidates = [k for k in list_keys(provider) if k.enabled]
    now = time.time()
    candidates = [k for k in candidates if k.cooldown_until < now]
    if not candidates:
        return None
    best = sorted(candidates, key=lambda k: (k.failures, k.last_used))[0]

    value = config.get_secret(_secret_entry(provider, best.label))
    if value:
        return best.label, value
    return None


def record_success(provider: str, label: str) -> None:
    pools = _load_pools()
    pool = pools.get(provider)
    if pool and label in pool.keys:
        rec = pool.keys[label]
        rec.failures = 0
        rec.last_used = time.time()
        rec.last_success = time.time()
        rec.last_error = ""
        rec.cooldown_until = 0.0
        _save_pools(pools)


def record_failure(provider: str, label: str, error: str, *, retryable: bool) -> None:
    """Disable on auth errors; cool down on rate limits; just note the rest."""
    pools = _load_pools()
    pool = pools.get(provider)
    if not pool or label not in pool.keys:
        return
    rec = pool.keys[label]
    rec.last_used = time.time()
    rec.last_error = error[:300]
    lowered = error.lower()
    if any(m in lowered for m in ("api key", "unauthorized", "401", "403", "invalid key")):
        rec.enabled = False
        log.warning("%s key %r disabled after an auth failure.", provider, label)
    elif retryable and any(
        m in lowered for m in ("rate limit", "quota", "429", "resource_exhausted")
    ):
        # 60-second cooldown; the key recovers by itself.
        rec.cooldown_until = time.time() + 60.0
        log.info("%s key %r cooling down for 60s (%s).", provider, label, error[:120])
    else:
        rec.failures += 1
    _save_pools(pools)


__all__ = [
    "KeyRecord",
    "add_key",
    "list_keys",
    "pick_key",
    "record_failure",
    "record_success",
    "remove_key",
    "set_key_enabled",
]
