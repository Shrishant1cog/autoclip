"""Speech engine contract and external-first resolution.

An engine turns an extracted ``audio.wav`` into the same
:class:`~autoclip.pipeline.transcript.Transcript` the local Whisper path
produces. The resolver in :func:`resolve_engine` encodes the product rule:
external first, local fallback, always — a dead external service degrades
transcription speed, never the job.
"""

from __future__ import annotations

import logging
from collections.abc import Callable
from pathlib import Path
from typing import Protocol

from ..config import Settings, TranscriptionSettings, get_secret

log = logging.getLogger(__name__)


class SpeechError(RuntimeError):
    """A speech engine could not produce a transcript."""


class SpeechCancelled(SpeechError):
    """The transcription stopped because the job was cancelled.

    Not a failure — the user asked for it. It is its own type so the runner
    can tell "the engine broke" from "the user stopped the job": a
    cancellation must never trigger the fallback to another engine, because
    the fallback would keep a job running that the user asked to stop.
    """


class SpeechEngine(Protocol):
    """One speech-to-text backend."""

    #: Stable identifier recorded in ``Transcript.source``.
    name: str

    def transcribe(
        self,
        audio: Path,
        settings: TranscriptionSettings,
        *,
        language: str = "",
        duration_s: float | None = None,
        on_progress: Callable[[float], None] | None = None,
        cancelled: Callable[[], bool] | None = None,
    ):  # -> Transcript; kept untyped to avoid a circular import at module load
        """Transcribe ``audio`` into a :class:`Transcript`."""


def resolve_engine(settings: Settings) -> tuple[SpeechEngine, str | None]:
    """Return the engine to run, plus a notice when falling back.

    Resolution order:

    1. ``transcription.engine == "local"`` — the local engine, no fallback.
    2. ``"elevenlabs"`` — the Scribe engine, no fallback.
    3. ``"auto"`` (default) — Scribe when a key is configured, else local. A
       missing key here is a *configuration*, not an error: plenty of users
       will never add one, and the local engine is the correct default for
       them.
    """
    engine = settings.transcription.engine

    if engine == "elevenlabs":
        from .elevenlabs import ElevenLabsSTT

        return ElevenLabsSTT(), None
    if engine == "local":
        from .local import LocalWhisperSTT

        return LocalWhisperSTT(), None

    # auto — external first.
    if get_secret("elevenlabs", settings):
        from .elevenlabs import ElevenLabsSTT

        return ElevenLabsSTT(), None

    notice = "No ElevenLabs key configured — using local Whisper."
    log.info(notice)
    from .local import LocalWhisperSTT

    return LocalWhisperSTT(), notice


__all__ = [
    "SpeechCancelled",
    "SpeechEngine",
    "SpeechError",
    "resolve_engine",
]
