"""REST API routers."""

from __future__ import annotations

from fastapi import APIRouter

from . import ai_providers, clips, jobs, settings, sources, workflows, youtube, youtube_accounts

__all__ = ["api_router"]

api_router = APIRouter()
api_router.include_router(sources.router)
api_router.include_router(jobs.router)
api_router.include_router(clips.router)
api_router.include_router(settings.router)
api_router.include_router(youtube.router)
api_router.include_router(workflows.router)
api_router.include_router(ai_providers.router)
api_router.include_router(youtube_accounts.router)
