"""Recovery centre API (Phase 15).

One list of everything that failed, classified, with the action that would
fix each one. The actions point at the endpoints that already own the work,
so nothing here starts anything on its own.
"""

from __future__ import annotations

import asyncio
import logging

from fastapi import APIRouter

from .. import recovery

log = logging.getLogger(__name__)

router = APIRouter(prefix="/api/recovery", tags=["recovery"])


@router.get("")
async def report() -> dict:
    """Every recoverable failure, with the action that would fix it."""
    return await asyncio.to_thread(recovery.build_report)
