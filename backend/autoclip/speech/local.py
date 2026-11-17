"""Local faster-whisper engine — the existing transcription path, wrapped.

Everything here re-uses :mod:`autoclip.pipeline.transcribe` unchanged; the
wrapper only adapts the call signature to the engine protocol so the runner
can treat local and external engines identically.
"""

from __future__ import annotations

import logging
from collections.abc import Callable
from pathlib import Path

from ..config import TranscriptionSettings
from ..pipeline import transcribe as local_transcribe
from .base import SpeechError

log = logging.getLogger(__name__)


class LocalWhisperSTT:
    """Transcribe with local faster-whisper."""

    name = "whisper"

    def transcribe(
        self,
        audio: Path,
        settings: TranscriptionSettings,
        *,
        language: str = "",
        duration_s: float | None = None,
        on_progress: Callable[[float], None] | None = None,
        cancelled: Callable[[], bool] | None = None,
    ):
        from ..config import load as load_settings

        root = load_settings()
        whisper = root.whisper
        if language:
            whisper = whisper.model_copy(update={"language": language})

        try:
            return local_transcribe.transcribe(
                audio,
                whisper,
                duration_s=duration_s,
                on_progress=on_progress,
                cancelled=cancelled,
            )
        except local_transcribe.TranscriptionError as exc:
            raise SpeechError(str(exc)) from exc


__all__ = ["LocalWhisperSTT"]
