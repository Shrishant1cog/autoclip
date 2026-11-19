"""Phase 12 — trending research: fetch, cache, analysis, prompt injection."""

from __future__ import annotations

import asyncio
import json
import time

import httpx
import pytest
from autoclip.providers import base as providers_base
from autoclip.providers.base import ProviderError
from autoclip.trends import research
from fastapi.testclient import TestClient


@pytest.fixture(autouse=True)
def _clear_trend_cache():
    """The trend cache is module-level; keep tests isolated from each other."""
    research.clear_cache()
    yield
    research.clear_cache()


# --------------------------------------------------------------------------
# Helpers
# --------------------------------------------------------------------------


def _youtube_payload() -> dict:
    return {
        "items": [
            {
                "id": "abc123",
                "snippet": {
                    "title": "I Survived 100 Days in a Haunted House",
                    "channelTitle": "Horror Stories",
                    "publishedAt": "2026-11-01T10:00:00Z",
                    "categoryId": "24",
                    "tags": ["horror", "challenge"],
                },
                "statistics": {"viewCount": "1234567"},
            },
            {
                "id": "def456",
                "snippet": {
                    "title": "The Fastest Way to Edit a Video",
                    "channelTitle": "Creator Tips",
                    "publishedAt": "2026-11-03T10:00:00Z",
                    "categoryId": "24",
                },
                "statistics": {"viewCount": "98765"},
            },
        ]
    }


def _mock_youtube(monkeypatch: pytest.MonkeyPatch, status: int = 200) -> list[dict]:
    """Replace the YouTube chart call with a recorded fake response."""
    calls: list[dict] = []

    def fake_get(url: str, *, params: dict, headers: dict, timeout: float):
        calls.append({"url": url, "params": params, "headers": headers})
        if status >= 400:
            return httpx.Response(status, json={"error": {"message": "quota exceeded"}})
        return httpx.Response(200, json=_youtube_payload())

    monkeypatch.setattr(research.httpx, "get", fake_get)
    return calls


def _mock_token(monkeypatch: pytest.MonkeyPatch) -> None:
    from autoclip.youtube import oauth

    monkeypatch.setattr(oauth, "access_token", lambda settings=None, account_id=None: "tok-123")


def _mock_analysis(monkeypatch: pytest.MonkeyPatch, output: str) -> None:
    from autoclip.providers import resolver

    async def fake_run(task, system, user, settings, chain=None, temperature=0.4):
        return output, "test-provider"

    monkeypatch.setattr(resolver, "run_with_fallback", fake_run)


# --------------------------------------------------------------------------
# Fetching
# --------------------------------------------------------------------------


def test_fetch_trending_videos_parses_chart(autoclip_home, monkeypatch: pytest.MonkeyPatch) -> None:
    _mock_token(monkeypatch)
    calls = _mock_youtube(monkeypatch)

    videos = research.fetch_trending_videos(
        __import__("autoclip.config", fromlist=["config"]).load(),
        category_id="24",
        region="GB",
    )

    assert len(videos) == 2
    assert videos[0].video_id == "abc123"
    assert videos[0].title == "I Survived 100 Days in a Haunted House"
    assert videos[0].view_count == 1234567
    assert videos[0].tags == ["horror", "challenge"]
    assert videos[1].view_count == 98765

    # The chart call is one quota unit and must ask for mostPopular.
    assert calls[0]["params"]["chart"] == "mostPopular"
    assert calls[0]["params"]["regionCode"] == "GB"
    assert calls[0]["params"]["videoCategoryId"] == "24"
    assert calls[0]["headers"]["Authorization"] == "Bearer tok-123"


def test_fetch_trending_videos_raises_on_http_error(
    autoclip_home, monkeypatch: pytest.MonkeyPatch
) -> None:
    _mock_token(monkeypatch)
    _mock_youtube(monkeypatch, status=403)

    from autoclip import config

    with pytest.raises(ProviderError):
        research.fetch_trending_videos(config.load())


# --------------------------------------------------------------------------
# Research + caching
# --------------------------------------------------------------------------


def test_research_returns_raw_list_when_provider_fails(
    autoclip_home, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A provider outage must not erase the real trend data or invent themes."""
    _mock_token(monkeypatch)
    _mock_youtube(monkeypatch)

    from autoclip import config
    from autoclip.providers import resolver

    async def failing(task, system, user, settings, chain=None, temperature=0.4):
        raise resolver.AllProvidersFailedError("every provider failed")

    monkeypatch.setattr(resolver, "run_with_fallback", failing)

    result = asyncio.run(research.research(config.load(), niche="gaming"))

    assert len(result.videos) == 2
    assert result.themes == []
    assert result.error
    assert "every provider failed" in result.error


def test_research_returns_error_when_youtube_fails(
    autoclip_home, monkeypatch: pytest.MonkeyPatch
) -> None:
    _mock_token(monkeypatch)
    _mock_youtube(monkeypatch, status=403)

    from autoclip import config

    result = asyncio.run(research.research(config.load()))

    assert result.videos == []
    assert result.error
    assert result.themes == []


def test_research_parses_ai_analysis(autoclip_home, monkeypatch: pytest.MonkeyPatch) -> None:
    _mock_token(monkeypatch)
    _mock_youtube(monkeypatch)
    _mock_analysis(
        monkeypatch,
        json.dumps(
            {
                "themes": [
                    {
                        "theme": "challenge runs",
                        "why": "completion stories pull viewers in",
                        "fit": "high",
                    }
                ],
                "formats": ["open with the stakes"],
                "avoid": ["more reaction faces"],
            }
        ),
    )

    from autoclip import config

    result = asyncio.run(research.research(config.load(), niche="gaming"))

    assert result.provider == "test-provider"
    assert result.themes[0]["theme"] == "challenge runs"
    assert result.formats == ["open with the stakes"]
    assert result.avoid == ["more reaction faces"]
    assert result.error == ""


def test_cache_reuses_result_within_ttl(autoclip_home, monkeypatch: pytest.MonkeyPatch) -> None:
    _mock_token(monkeypatch)
    calls = _mock_youtube(monkeypatch)
    _mock_analysis(monkeypatch, json.dumps({"themes": [], "formats": [], "avoid": []}))

    from autoclip import config

    settings = config.load()
    first = asyncio.run(research.research(settings))
    assert first.from_cache is False

    second = asyncio.run(research.research(settings))
    assert second.from_cache is True
    assert len(second.videos) == 2
    # Only one real fetch happened — the second call served the cache.
    assert len(calls) == 1


def test_force_refetches(autoclip_home, monkeypatch: pytest.MonkeyPatch) -> None:
    _mock_token(monkeypatch)
    calls = _mock_youtube(monkeypatch)
    _mock_analysis(monkeypatch, json.dumps({"themes": [], "formats": [], "avoid": []}))

    from autoclip import config

    settings = config.load()
    asyncio.run(research.research(settings))
    forced = asyncio.run(research.research(settings, force=True))

    assert forced.from_cache is False
    assert len(calls) == 2


def test_cache_expires(autoclip_home, monkeypatch: pytest.MonkeyPatch) -> None:
    _mock_token(monkeypatch)
    calls = _mock_youtube(monkeypatch)
    _mock_analysis(monkeypatch, json.dumps({"themes": [], "formats": [], "avoid": []}))

    from autoclip import config

    settings = config.load()
    asyncio.run(research.research(settings))

    # Age the cache past its TTL.
    key = research.cache_key(research.DEFAULT_CATEGORY, research.DEFAULT_REGION)
    fetched_at, payload = research._cache[key]
    research._cache[key] = (fetched_at - research.CACHE_TTL_S - 1, payload)

    asyncio.run(research.research(settings))
    assert len(calls) == 2


def test_cached_context_reads_without_network(
    autoclip_home, monkeypatch: pytest.MonkeyPatch
) -> None:
    _mock_token(monkeypatch)
    _mock_youtube(monkeypatch)
    _mock_analysis(
        monkeypatch,
        json.dumps(
            {"themes": [{"theme": "x", "why": "y", "fit": "high"}], "formats": [], "avoid": []}
        ),
    )

    from autoclip import config

    assert research.cached_context().videos == []

    asyncio.run(research.research(config.load()))
    context = research.cached_context()

    assert len(context.videos) == 2
    assert context.from_cache is True
    assert context.themes[0]["theme"] == "x"


# --------------------------------------------------------------------------
# Prompt injection
# --------------------------------------------------------------------------


def test_prompt_section_shape() -> None:
    result = research.TrendResearch(
        videos=[
            research.TrendingVideo(
                video_id="v1", title="Hot Video", view_count=1000, channel="Chan"
            )
        ],
        themes=[{"theme": "challenge runs", "why": "works", "fit": "high"}],
        formats=["stakes up front"],
        avoid=["reaction faces"],
    )
    section = research.prompt_section(result)

    assert "What is trending right now" in section
    assert "Hot Video" in section
    assert "challenge runs" in section
    assert "stakes up front" in section


def test_prompt_section_empty_without_videos() -> None:
    assert research.prompt_section(research.TrendResearch()) == ""


def test_detection_prompt_includes_trend_context(
    autoclip_home, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The trend block must ride along in the detection system prompt."""
    _mock_token(monkeypatch)
    _mock_youtube(monkeypatch)
    _mock_analysis(
        monkeypatch,
        json.dumps(
            {
                "themes": [{"theme": "challenge runs", "why": "works", "fit": "high"}],
                "formats": [],
                "avoid": [],
            }
        ),
    )

    from autoclip import config

    asyncio.run(research.research(config.load(), niche="gaming"))

    class DummyProvider(providers_base.LLMProvider):
        name = "dummy"

        def __init__(self):
            super().__init__("dummy-model")
            self.system_prompts: list[str] = []

        async def _complete(self, system, user, config):
            self.system_prompts.append(system)
            return '{"clips": []}'

        async def health_check(self):
            return providers_base.ProviderStatus(name=self.name, available=True)

    from autoclip.providers.base import DetectionConfig, TranscriptWindow

    provider = DummyProvider()
    window = TranscriptWindow(first_word=0, last_word=5, text="[0]hello [1]world", speakers=[])

    asyncio.run(
        provider.detect_highlights(window, DetectionConfig(min_duration_s=5, max_duration_s=60))
    )

    assert provider.system_prompts
    prompt = provider.system_prompts[0]
    assert "What is trending right now" in prompt
    assert "I Survived 100 Days in a Haunted House" in prompt


def test_detection_prompt_survives_missing_trend_context(
    autoclip_home, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A broken trend cache must never break detection."""
    from autoclip.trends import research as trend_research

    def boom(*args, **kwargs):
        raise RuntimeError("trend cache exploded")

    monkeypatch.setattr(trend_research, "cached_context", boom)

    class DummyProvider(providers_base.LLMProvider):
        name = "dummy"

        def __init__(self):
            super().__init__("dummy-model")
            self.system_prompts: list[str] = []

        async def _complete(self, system, user, config):
            self.system_prompts.append(system)
            return '{"clips": []}'

        async def health_check(self):
            return providers_base.ProviderStatus(name=self.name, available=True)

    from autoclip.providers.base import DetectionConfig, TranscriptWindow

    provider = DummyProvider()
    window = TranscriptWindow(first_word=0, last_word=5, text="[0]hi", speakers=[])

    asyncio.run(
        provider.detect_highlights(window, DetectionConfig(min_duration_s=5, max_duration_s=60))
    )

    assert provider.system_prompts
    assert "What is trending right now" not in provider.system_prompts[0]


# --------------------------------------------------------------------------
# HTTP API
# --------------------------------------------------------------------------


def test_trends_api(autoclip_home, initialised_db: int, monkeypatch: pytest.MonkeyPatch) -> None:
    from autoclip.app import create_app

    _mock_token(monkeypatch)
    _mock_youtube(monkeypatch)
    _mock_analysis(
        monkeypatch,
        json.dumps(
            {
                "themes": [{"theme": "challenge runs", "why": "works", "fit": "high"}],
                "formats": ["open with stakes"],
                "avoid": [],
            }
        ),
    )

    with TestClient(create_app()) as client:
        current = client.get("/api/trends/current?niche=gaming")
        assert current.status_code == 200
        body = current.json()
        assert body["niche"] == "gaming"
        assert len(body["videos"]) == 2
        assert body["themes"][0]["theme"] == "challenge runs"

        # A second GET is served from the cache.
        again = client.get("/api/trends/current?niche=gaming").json()
        assert again["from_cache"] is True

        context = client.get("/api/trends/context").json()
        assert context["available"] is True
        assert "What is trending right now" in context["section"]

        refreshed = client.post("/api/trends/refresh", json={"niche": "gaming", "force": True})
        assert refreshed.status_code == 200
        assert refreshed.json()["from_cache"] is False


def test_trends_api_reports_error_without_connection(
    autoclip_home, initialised_db: int, monkeypatch: pytest.MonkeyPatch
) -> None:
    """No YouTube connection must yield a clear error, not a crash."""
    from autoclip.app import create_app
    from autoclip.youtube import oauth

    def no_token(settings=None, account_id=None):
        raise oauth.OAuthError("No YouTube channel is connected.")

    monkeypatch.setattr(oauth, "access_token", no_token)

    with TestClient(create_app()) as client:
        response = client.get("/api/trends/current")
        assert response.status_code == 200
        body = response.json()
        assert body["videos"] == []
        assert "No YouTube channel is connected." in body["error"]


def test_clear_cache(autoclip_home) -> None:
    research._cache["x:y"] = (time.time(), {"videos": []})
    research.clear_cache()
    assert research._cache == {}
