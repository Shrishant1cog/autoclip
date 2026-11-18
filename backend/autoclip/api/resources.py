"""Resource usage and cleanup endpoints (Phase 16).

Two questions the app used to be unable to answer: *how much disk am I
using*, and *what can be reclaimed without losing anything*. These endpoints
answer both, and the cleanup one is the only place in AutoClip that deletes
files on the user's behalf — it does exactly what the retention settings say
and reports precisely what it did.
"""

from __future__ import annotations

import asyncio
import logging

from fastapi import APIRouter

from .. import config, resources
from ..db import store

log = logging.getLogger(__name__)

router = APIRouter(prefix="/api/resources", tags=["resources"])


def _limits(settings: config.Settings) -> dict[str, object]:
    """The configured ceilings, so the UI can show what the app is allowed."""
    return {
        "ffmpeg_threads": settings.resources.ffmpeg_threads,
        "max_parallel_ffmpeg": settings.resources.max_parallel_ffmpeg,
        "work_retention_days": settings.resources.work_retention_days,
        "export_retention_days": settings.resources.export_retention_days,
        "raw_retention_days": settings.resources.raw_retention_days,
        "cleanup_on_start": settings.resources.cleanup_on_start,
        "max_output_tokens": settings.resources.max_output_tokens,
        "max_llm_calls_per_job": settings.resources.max_llm_calls_per_job,
    }


def _job_usage() -> list[dict[str, object]]:
    rows = store.list_job_resources(limit=50)
    out: list[dict[str, object]] = []
    for row in rows:
        job = store.get_job(row.job_id)
        source = store.get_source(job.source_id) if job else None
        out.append(
            {
                "job_id": row.job_id,
                "status": job.status if job else "unknown",
                "title": source.title if source else "",
                "llm_calls": row.llm_calls,
                "llm_input_tokens": row.llm_input_tokens,
                "llm_output_tokens": row.llm_output_tokens,
                "llm_total_tokens": row.llm_total_tokens,
                "ffmpeg_runs": row.ffmpeg_runs,
                "ffmpeg_seconds": round(row.ffmpeg_seconds, 1),
                "export_bytes": row.export_bytes,
                "windows_skipped": row.windows_skipped,
                "updated_at": row.updated_at,
            }
        )
    return out


@router.get("")
async def resource_overview() -> dict:
    """What AutoClip is using, and what it is allowed to use."""
    settings = config.load()

    disk = await asyncio.to_thread(resources.disk_usage)
    totals = await asyncio.to_thread(store.total_job_resources)
    jobs = await asyncio.to_thread(_job_usage)

    return {
        "disk": disk.to_dict(),
        "limits": _limits(settings),
        "usage": {
            "totals": {
                "llm_calls": totals.llm_calls,
                "llm_input_tokens": totals.llm_input_tokens,
                "llm_output_tokens": totals.llm_output_tokens,
                "llm_total_tokens": totals.llm_total_tokens,
                "ffmpeg_runs": totals.ffmpeg_runs,
                "ffmpeg_seconds": round(totals.ffmpeg_seconds, 1),
                "export_bytes": totals.export_bytes,
                "export_human": resources.format_bytes(totals.export_bytes),
                "windows_skipped": totals.windows_skipped,
            },
            "jobs": jobs,
        },
    }


@router.post("/cleanup")
async def run_cleanup() -> dict:
    """Reclaim what the retention settings allow, now.

    Only removes what the settings allow: scratch directories of finished
    jobs, files of already-published clips past their retention, downloaded
    YouTube videos past their retention, and files no row points at any more.
    An unpublished clip and an uploaded source file are never touched.
    """
    settings = config.load()
    report = await asyncio.to_thread(resources.cleanup, settings)
    return report.to_dict()
