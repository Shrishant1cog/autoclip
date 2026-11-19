"""Trending research API (Phase 12).

Exposes the YouTube most-popular chart plus the analyst's read on it. The
endpoints never fabricate data: if YouTube or the AI provider is unreachable,
the response carries the raw trend list and an ``error`` string.
"""

from __future__ import annotations

import logging

from fastapi import APIRouter
from pydantic import BaseModel

from .. import config
from ..trends import research
from ..youtube import accounts as accounts_store

log = logging.getLogger(__name__)

router = APIRouter(prefix="/api/trends", tags=["trends"])


class RefreshIn(BaseModel):
    niche: str = ""
    category_id: str = research.DEFAULT_CATEGORY
    region: str = research.DEFAULT_REGION
    account_id: str = ""
    force: bool = True


def _resolve_account(account_id: str = "") -> str | None:
    """Pick the Google account to query with.

    An explicit id wins; otherwise the default connected account; otherwise
    ``None``, which uses the legacy single-account token.
    """
    if account_id:
        return account_id
    account = accounts_store.default_account()
    if account:
        return str(account["id"])
    return None


def _category_for(account_id: str | None, fallback: str) -> str:
    """Use the default channel's category when it is set, else the fallback."""
    try:
        channel = accounts_store.default_channel(account_id)
    except Exception:  # noqa: BLE001
        channel = None
    if channel and channel.get("category_id"):
        return str(channel["category_id"])
    return fallback


@router.get("/current")
async def current(
    niche: str = "",
    category_id: str = "",
    region: str = research.DEFAULT_REGION,
    account_id: str = "",
) -> dict:
    """The current trend read.

    Serves the cached result when it is fresh; otherwise fetches it. With no
    YouTube connection the response explains why instead of failing.
    """
    settings = config.load()
    resolved_account = _resolve_account(account_id)
    category = category_id or _category_for(resolved_account, research.DEFAULT_CATEGORY)

    cached = research.cached_context(category, region)
    if cached.videos:
        payload = cached.to_dict()
        payload["niche"] = niche
        payload["category_id"] = category
        payload["region"] = region
        return payload

    result = await research.research(
        settings,
        niche=niche,
        category_id=category,
        region=region,
        account_id=resolved_account,
    )
    payload = result.to_dict()
    payload["niche"] = niche
    payload["category_id"] = category
    payload["region"] = region
    return payload


@router.post("/refresh")
async def refresh(payload: RefreshIn) -> dict:
    """Re-fetch the trending chart and re-run the analysis."""
    settings = config.load()
    resolved_account = _resolve_account(payload.account_id)
    category = payload.category_id or _category_for(resolved_account, research.DEFAULT_CATEGORY)

    result = await research.research(
        settings,
        niche=payload.niche,
        category_id=category,
        region=payload.region,
        force=payload.force,
        account_id=resolved_account,
    )
    body = result.to_dict()
    body["niche"] = payload.niche
    body["category_id"] = category
    body["region"] = payload.region
    return body


@router.get("/context")
async def context() -> dict:
    """The trend block that would be injected into the detection prompt.

    Useful for checking that trends are actually reaching the clip finder.
    """
    current_context = research.cached_context()
    section = research.prompt_section(current_context)
    return {
        "available": bool(current_context.videos),
        "section": section,
        "video_count": len(current_context.videos),
        "fetched_at": current_context.fetched_at,
        "provider": current_context.provider,
    }
