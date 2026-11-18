"""Trending research (Phase 12).

"What should I clip next?" needs a signal from outside the user's own back
catalogue. This module gathers that signal from YouTube itself:

* **Trending videos** — the Data API's ``videos.list`` with ``chart=mostPopular``
  for the channel's category and region. One quota unit per call, so the result
  is cached for hours, not seconds.
* **Topic signals** — an AI task over the provider fallback chain that reads
  the trending titles and explains which angles are hot for the user's niche.
  When no provider is available the raw trend list is still returned; the
  explanation is never fabricated.

Results feed two places: the highlight prompt (what is hot right now) and the
research UI.
"""

from __future__ import annotations

import json
import logging
import time
from dataclasses import dataclass, field
from typing import Any

import httpx

from .. import config
from ..providers import resolver
from ..providers.base import ProviderError, extract_json_object

log = logging.getLogger(__name__)

TRENDING_URL = "https://www.googleapis.com/youtube/v3/videos"

#: How long a fetched trend list stays fresh. The chart barely moves in an
#: hour, and every call costs a quota unit.
CACHE_TTL_S = 6 * 3600

#: Default region/category for the "most popular" chart.
DEFAULT_REGION = "US"
DEFAULT_CATEGORY = "24"

MAX_RESULTS = 50

#: Module-level cache: {"key": (fetched_at, payload)}.
_cache: dict[str, tuple[float, dict[str, Any]]] = {}

TREND_SYSTEM_PROMPT = """You are a short-form video strategist. You are given the \
titles of currently trending YouTube videos and a creator niche.

Reply with ONE JSON object and nothing else:

{
  "themes": [
    {"theme": "short noun phrase", "why": "one sentence on why it resonates",
     "fit": "high|medium|low"}
  ],
  "formats": ["hook shapes that are working right now"],
  "avoid": ["angles that are saturated or tired"]
}

Keep at most 6 themes, 5 formats, and 4 avoid items. Never invent trends that are \
not in the list you were given."""


@dataclass
class TrendingVideo:
    """One trending video as the API reported it."""

    video_id: str
    title: str
    channel: str = ""
    published_at: str = ""
    view_count: int = 0
    category_id: str = ""
    tags: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "video_id": self.video_id,
            "title": self.title,
            "channel": self.channel,
            "published_at": self.published_at,
            "view_count": self.view_count,
            "category_id": self.category_id,
            "tags": self.tags,
            "url": f"https://youtu.be/{self.video_id}",
        }

    @classmethod
    def from_dict(cls, payload: dict[str, Any]) -> TrendingVideo:
        """Rebuild from a cached dict, ignoring the derived ``url`` field."""
        return cls(
            video_id=str(payload.get("video_id", "")),
            title=str(payload.get("title", "")),
            channel=str(payload.get("channel", "")),
            published_at=str(payload.get("published_at", "")),
            view_count=int(payload.get("view_count", 0) or 0),
            category_id=str(payload.get("category_id", "")),
            tags=list(payload.get("tags", []) or []),
        )


@dataclass
class TrendResearch:
    """A fetched trend list plus the AI's read on it (when available)."""

    videos: list[TrendingVideo] = field(default_factory=list)
    themes: list[dict[str, Any]] = field(default_factory=list)
    formats: list[str] = field(default_factory=list)
    avoid: list[str] = field(default_factory=list)
    provider: str = ""
    fetched_at: float = 0.0
    from_cache: bool = False
    error: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "videos": [video.to_dict() for video in self.videos],
            "themes": self.themes,
            "formats": self.formats,
            "avoid": self.avoid,
            "provider": self.provider,
            "fetched_at": self.fetched_at,
            "from_cache": self.from_cache,
            "error": self.error,
        }

    def summary_text(self, limit: int = 12) -> str:
        """A compact, prompt-friendly digest of the current trends."""
        lines: list[str] = []
        for video in self.videos[:limit]:
            lines.append(f"- {video.title} ({video.view_count:,} views)")
        if self.themes:
            lines.append("")
            for theme in self.themes[:6]:
                lines.append(
                    f"* {theme.get('theme', '')} — {theme.get('why', '')} "
                    f"(fit: {theme.get('fit', '')})"
                )
        if self.formats:
            lines.append("")
            lines.append("Formats working now: " + "; ".join(self.formats[:5]))
        if self.avoid:
            lines.append("Saturated: " + "; ".join(self.avoid[:4]))
        return "\n".join(lines).strip()


def cache_key(category_id: str, region: str) -> str:
    return f"{category_id}:{region}"


def clear_cache() -> None:
    _cache.clear()


def cached_context(
    category_id: str = DEFAULT_CATEGORY, region: str = DEFAULT_REGION
) -> TrendResearch:
    """The last fetched trend list, without touching the network.

    Detection runs synchronously inside a provider call, so this only reads
    what a previous research run already fetched. An empty result means "no
    trend context available", which the prompt simply skips.
    """
    cached = _cache.get(cache_key(category_id, region))
    if not cached:
        return TrendResearch()
    fetched_at, payload = cached
    return TrendResearch(
        videos=[TrendingVideo.from_dict(video) for video in payload.get("videos", [])],
        themes=payload.get("themes", []),
        formats=payload.get("formats", []),
        avoid=payload.get("avoid", []),
        provider=payload.get("provider", ""),
        fetched_at=fetched_at,
        from_cache=True,
    )


def fetch_trending_videos(
    settings: config.Settings,
    *,
    category_id: str = DEFAULT_CATEGORY,
    region: str = DEFAULT_REGION,
    max_results: int = MAX_RESULTS,
    account_id: str | None = None,
) -> list[TrendingVideo]:
    """Fetch the most-popular chart for a category/region.

    Raises :class:`ProviderError` when the API refuses (quota, auth, network).
    """
    from ..youtube import oauth

    token = oauth.access_token(settings, account_id=account_id)
    params = {
        "part": "snippet,statistics,contentDetails",
        "chart": "mostPopular",
        "regionCode": region,
        "maxResults": str(max(1, min(max_results, 50))),
    }
    if category_id:
        params["videoCategoryId"] = category_id

    try:
        response = httpx.get(
            TRENDING_URL,
            params=params,
            headers={"Authorization": f"Bearer {token}"},
            timeout=30.0,
        )
    except httpx.HTTPError as exc:
        raise ProviderError(f"Could not reach YouTube: {exc}") from exc

    if response.status_code >= 400:
        detail = response.text[:300]
        raise ProviderError(
            f"YouTube returned {response.status_code} for the trending chart.",
            hint=detail,
        )

    payload = response.json()
    videos: list[TrendingVideo] = []
    for item in payload.get("items", []):
        snippet = item.get("snippet", {})
        statistics = item.get("statistics", {})
        video_id = item.get("id", "")
        if not video_id:
            continue
        videos.append(
            TrendingVideo(
                video_id=video_id,
                title=snippet.get("title", ""),
                channel=snippet.get("channelTitle", ""),
                published_at=snippet.get("publishedAt", ""),
                view_count=int(statistics.get("viewCount", 0) or 0),
                category_id=snippet.get("categoryId", ""),
                tags=list(snippet.get("tags", []) or []),
            )
        )
    return videos


async def research(
    settings: config.Settings,
    *,
    niche: str = "",
    category_id: str = DEFAULT_CATEGORY,
    region: str = DEFAULT_REGION,
    force: bool = False,
    account_id: str | None = None,
) -> TrendResearch:
    """Fetch trending videos and, when a provider is available, analyse them.

    A provider failure is not fatal: the raw trending list is still returned
    with ``error`` set, so the caller never shows invented themes.
    """
    key = cache_key(category_id, region)
    now = time.time()
    cached = _cache.get(key)
    if cached and not force and now - cached[0] < CACHE_TTL_S:
        videos = [TrendingVideo.from_dict(video) for video in cached[1]["videos"]]
        result = TrendResearch(
            videos=videos,
            themes=cached[1].get("themes", []),
            formats=cached[1].get("formats", []),
            avoid=cached[1].get("avoid", []),
            provider=cached[1].get("provider", ""),
            fetched_at=cached[0],
            from_cache=True,
        )
    else:
        try:
            videos = fetch_trending_videos(
                settings,
                category_id=category_id,
                region=region,
                account_id=account_id,
            )
        except ProviderError as exc:
            log.warning("Trending fetch failed: %s", exc)
            return TrendResearch(error=str(exc), fetched_at=now)
        except Exception as exc:  # noqa: BLE001
            log.warning("Trending fetch raised: %s", exc)
            return TrendResearch(error=str(exc), fetched_at=now)

        result = TrendResearch(videos=videos, fetched_at=now)

    if not force and cached and result.from_cache:
        return result

    # AI analysis of the trend list. Failure leaves the raw list intact.
    try:
        output, provider_label = await resolver.run_with_fallback(
            "text",
            TREND_SYSTEM_PROMPT,
            _analysis_prompt(result.videos, niche),
            settings,
            temperature=0.5,
        )
        parsed = _parse_analysis(output)
        result.themes = parsed.get("themes", [])
        result.formats = parsed.get("formats", [])
        result.avoid = parsed.get("avoid", [])
        result.provider = provider_label
    except (ProviderError, ValueError, json.JSONDecodeError) as exc:
        log.warning("Trend analysis failed (%s); showing the raw trend list.", exc)
        result.error = str(exc)

    _cache[key] = (
        result.fetched_at,
        {
            "videos": [video.to_dict() for video in result.videos],
            "themes": result.themes,
            "formats": result.formats,
            "avoid": result.avoid,
            "provider": result.provider,
        },
    )
    return result


def _analysis_prompt(videos: list[TrendingVideo], niche: str) -> str:
    lines = [f"- {video.title} ({video.view_count:,} views)" for video in videos[:25]]
    target = niche.strip() or "short-form entertainment and gaming"
    return (
        f"Creator niche: {target}\n\n"
        "Trending video titles right now:\n"
        + "\n".join(lines)
        + "\n\nReturn the JSON object described in the system prompt."
    )


def _parse_analysis(raw: str) -> dict[str, Any]:
    payload = extract_json_object(raw)
    themes = payload.get("themes", [])
    if not isinstance(themes, list):
        themes = []
    clean_themes = [
        {
            "theme": str(item.get("theme", ""))[:120],
            "why": str(item.get("why", ""))[:400],
            "fit": str(item.get("fit", ""))[:20],
        }
        for item in themes
        if isinstance(item, dict) and item.get("theme")
    ]
    formats = [str(item)[:160] for item in payload.get("formats", []) if isinstance(item, str)]
    avoid = [str(item)[:160] for item in payload.get("avoid", []) if isinstance(item, str)]
    return {"themes": clean_themes[:6], "formats": formats[:5], "avoid": avoid[:4]}


def prompt_section(research: TrendResearch) -> str:
    """The trend block injected into the highlight prompt, or ''."""
    if not research.videos:
        return ""
    body = research.summary_text()
    if not body:
        return ""
    return (
        "\n\n## What is trending right now\n\n"
        "These are currently-popular YouTube videos and, where available, the "
        "themes the analyst read into them. Prefer angles that fit a trend, "
        "but only when the transcript genuinely contains the moment — never "
        "force a trending topic that is not there.\n\n"
        f"{body}\n"
    )


__all__ = [
    "CACHE_TTL_S",
    "DEFAULT_CATEGORY",
    "DEFAULT_REGION",
    "TrendResearch",
    "TrendingVideo",
    "cache_key",
    "cached_context",
    "clear_cache",
    "fetch_trending_videos",
    "prompt_section",
    "research",
]
