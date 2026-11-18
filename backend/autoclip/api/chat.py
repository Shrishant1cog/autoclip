"""Project-aware assistant (Phase 13).

The assistant answers questions about this AutoClip installation using a
snapshot of its real state. It never fabricates: if no provider can answer,
the endpoint returns the failure instead of a plausible-sounding reply.
"""

from __future__ import annotations

import logging

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from .. import config
from ..chat import agent
from ..chat.context import build_context
from ..providers import resolver
from ..providers.base import ProviderError

log = logging.getLogger(__name__)

router = APIRouter(prefix="/api/chat", tags=["chat"])


class MessageIn(BaseModel):
    role: str = "user"
    content: str = ""


class AskIn(BaseModel):
    message: str
    history: list[MessageIn] = Field(default_factory=list)
    clip_id: str = ""
    job_id: str = ""


@router.get("/starters")
async def starters() -> dict:
    """Suggested opening questions."""
    return {"starters": list(agent.STARTERS)}


@router.get("/context")
async def context(clip_id: str = "", job_id: str = "") -> dict:
    """The exact project snapshot the assistant reasons over.

    Exposed so the user can see what the assistant can and cannot see.
    """
    settings = config.load()
    snapshot = build_context(settings, clip_id=clip_id, job_id=job_id)
    return {"context": snapshot.to_dict(), "prompt": snapshot.as_prompt()}


@router.post("")
async def ask(payload: AskIn) -> dict:
    """Answer one question about the project."""
    message = payload.message.strip()
    if not message:
        raise HTTPException(status_code=400, detail="Say something first.")

    history = [
        agent.ChatTurn(role=turn.role, content=turn.content)
        for turn in payload.history
        if turn.content.strip()
    ]
    if history and history[-1].content.strip() == message:
        # The client already appended the question; do not repeat it.
        history = history[:-1]

    settings = config.load()
    try:
        answer = await agent.ask(
            message,
            settings=settings,
            history=history,
            clip_id=payload.clip_id,
            job_id=payload.job_id,
        )
    except resolver.AllProvidersFailedError as exc:
        raise HTTPException(
            status_code=502,
            detail=(
                "No AI provider could answer. Add a key in Settings → AI Providers, "
                "or start a local provider. The project data was not sent anywhere."
            ),
            headers={"X-AutoClip-Reason": str(exc)[:200]},
        ) from exc
    except ProviderError as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc

    return answer.to_dict()
