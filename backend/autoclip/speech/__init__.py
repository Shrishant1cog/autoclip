"""Speech services — external-first speech-to-text with local fallback.

The pipeline's transcription stage resolves an engine through
:func:`resolve_engine`: whichever external STT provider is configured and
healthy runs first, and the local faster-whisper engine takes over on *any*
failure (auth, rate limit, outage, timeout, unusable result). Engines return
the same :class:`~autoclip.pipeline.transcript.Transcript`, so nothing
downstream knows or cares which one ran — ``Transcript.source`` records it.
"""

from __future__ import annotations

from .base import SpeechCancelled, SpeechError, resolve_engine
from .elevenlabs import ElevenLabsSTT
from .local import LocalWhisperSTT

__all__ = [
    "ElevenLabsSTT",
    "LocalWhisperSTT",
    "SpeechCancelled",
    "SpeechError",
    "resolve_engine",
]
