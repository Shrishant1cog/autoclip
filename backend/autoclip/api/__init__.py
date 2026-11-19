"""REST API routers."""

from __future__ import annotations

from fastapi import APIRouter

from . import (
    ai_providers,
    batches,
    chat,
    clips,
    jobs,
    learning,
    music,
    notifications,
    privacy,
    recovery,
    resources,
    restarts,
    routing,
    settings,
    sources,
    trends,
    workflows,
    youtube,
    youtube_accounts,
)

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
api_router.include_router(routing.router)
api_router.include_router(batches.router)
api_router.include_router(music.router)
api_router.include_router(learning.router)
api_router.include_router(trends.router)
api_router.include_router(chat.router)
api_router.include_router(notifications.router)
api_router.include_router(recovery.router)
api_router.include_router(resources.router)
api_router.include_router(restarts.router)
api_router.include_router(privacy.router)
