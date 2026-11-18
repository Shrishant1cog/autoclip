"""The project-aware assistant (Phase 13).

One job: answer questions about *this* AutoClip installation using the real
project snapshot as the only source of truth.

Three rules govern the implementation:

1. **No fabrication.** The model is given the project snapshot and told that
   it is the whole of its knowledge. If the snapshot does not contain the
   answer, the honest reply is "the project data does not say".
2. **No silent fallback.** If every provider in the fallback chain fails, the
   caller gets the failure — never a canned answer that looks like a reply.
3. **Local-first.** The chain is the standard provider resolver, so the user's
   configured provider leads and a healthy local model is the terminal
   fallback.
"""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass, field
from typing import Any

from .. import config
from ..providers import resolver
from ..providers.base import ProviderError
from .context import ProjectContext, build_context

log = logging.getLogger(__name__)

#: How many prior turns are carried into the prompt.
MAX_HISTORY_TURNS = 8

SYSTEM_PROMPT = """You are the AutoClip assistant. You work inside a local \
video-clipping pipeline that finds highlights in long videos, renders short \
clips, and publishes them to YouTube.

You have been given a snapshot of this installation's real state: its library, \
its recent jobs, its clips, its failures, its channels and its settings.

Rules:

- Answer only from the snapshot below. It is the entirety of what you know \
about this project.
- Answer in plain prose or Markdown. Never return JSON unless the user \
explicitly asks for JSON.
- Never invent counts, clip titles, errors, upload ids or YouTube URLs. If the \
snapshot does not contain something, say plainly that the project data does \
not record it.
- Quote exact values (scores, error strings, titles) when they matter.
- Be concise and concrete. Prefer short paragraphs and lists over prose.
- If the user asks how to do something, explain the steps using the settings \
that are actually configured here.
- If the snapshot shows failures, name them and say what they mean.
- Never claim to have performed an action. You can only describe what the \
snapshot shows."""

#: Added when the model tries to answer with JSON instead of a reply.
NO_JSON_NUDGE = (
    "Reply with the answer itself in plain prose. Do not wrap it in JSON, "
    "a code block, or a schema."
)

#: Offered when the user has not asked anything specific yet.
STARTERS: tuple[str, ...] = (
    "What has AutoClip produced so far?",
    "What is failing right now?",
    "Why was my highest-scoring clip chosen?",
    "How many clips were published, and to where?",
    "What should I change to get better clips?",
)


@dataclass
class ChatTurn:
    """One message in the conversation."""

    role: str
    content: str

    def to_dict(self) -> dict[str, str]:
        return {"role": self.role, "content": self.content}


@dataclass
class ChatAnswer:
    """The assistant's reply plus the evidence it was given."""

    answer: str
    provider: str = ""
    context: ProjectContext = field(default_factory=ProjectContext)

    def to_dict(self) -> dict[str, Any]:
        return {
            "answer": self.answer,
            "provider": self.provider,
            "context": self.context.to_dict(),
        }


def _history_block(history: list[ChatTurn]) -> str:
    """Render the recent conversation for the prompt.

    The final turn is the question being asked now, so it is shown once, on
    its own — a client that already appended it must not see it twice.
    """
    if not history:
        return ""
    lines = []
    if len(history) > 1:
        lines.append("## Conversation so far")
        for turn in history[:-1][-MAX_HISTORY_TURNS:]:
            who = "User" if turn.role == "user" else "Assistant"
            lines.append(f"{who}: {turn.content}")
        lines.append("")
    lines.append("## Current question")
    lines.append(f"User: {history[-1].content}")
    return "\n".join(lines).strip()


async def ask(
    message: str,
    *,
    settings: config.Settings | None = None,
    history: list[ChatTurn] | None = None,
    clip_id: str = "",
    job_id: str = "",
) -> ChatAnswer:
    """Answer one question about the project.

    Raises :class:`resolver.AllProvidersFailedError` when no provider could
    answer — the caller surfaces that rather than inventing a reply.
    """
    settings = settings or config.load()
    context = build_context(settings, clip_id=clip_id, job_id=job_id)

    turns = list(history or [])
    turns.append(ChatTurn(role="user", content=message))

    system = f"{SYSTEM_PROMPT}\n\n# Project snapshot\n\n{context.as_prompt()}"
    user = _history_block(turns) or f"User: {message}"

    output, provider_label = await resolver.run_with_fallback(
        "text", system, user, settings, temperature=0.3
    )
    answer = (output or "").strip()
    if not answer:
        raise ProviderError("The provider returned an empty answer.")

    # Some models reach for JSON on anything that looks structured. A chat
    # reply is prose, so ask once more when the answer is clearly a schema.
    if _looks_like_json(answer):
        try:
            retry, _ = await resolver.run_with_fallback(
                "text",
                f"{system}\n\n{NO_JSON_NUDGE}",
                user,
                settings,
                temperature=0.3,
            )
            retry = (retry or "").strip()
            if retry and not _looks_like_json(retry):
                answer = retry
        except ProviderError:
            log.debug("The prose retry failed; keeping the first answer.")

    return ChatAnswer(answer=answer, provider=provider_label, context=context)


def _looks_like_json(text: str) -> bool:
    """True when the answer is a JSON object/array rather than a reply."""
    stripped = text.strip()
    if not stripped.startswith(("{", "[")):
        return False
    try:
        json.loads(stripped)
    except (ValueError, TypeError):
        return False
    return True


__all__ = [
    "MAX_HISTORY_TURNS",
    "NO_JSON_NUDGE",
    "STARTERS",
    "SYSTEM_PROMPT",
    "ChatAnswer",
    "ChatTurn",
    "ask",
]
