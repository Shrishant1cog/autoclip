"""ElevenLabs text-to-speech — clip voiceover and narration.

A new capability, off by default: today's exports re-encode the source audio
and burn captions, and nothing generates speech. When enabled, a narration
track is synthesized per clip and muxed over a ducked original bed, so the
speaker stays faintly audible under the voiceover.
"""

from __future__ import annotations

import logging
from pathlib import Path

import httpx

from ..config import get_secret
from .base import SpeechError

log = logging.getLogger(__name__)

API_URL = "https://api.elevenlabs.io/v1/text-to-speech/{voice_id}"
REQUEST_TIMEOUT = 300.0

#: The ElevenLabs CLI's default voice (Rachel). Stable, documented id.
DEFAULT_VOICE_ID = "JBFqnCBsd6RMkjVDRZzb"
#: Flash v2.5 — the cheap low-latency tier; good default for narration.
DEFAULT_MODEL_ID = "eleven_flash_v2_5"


def synthesize_speech(
    text: str,
    destination: Path,
    *,
    voice_id: str = DEFAULT_VOICE_ID,
    model_id: str = DEFAULT_MODEL_ID,
    api_key: str | None = None,
) -> Path:
    """Synthesize ``text`` to an MP3 at ``destination``. Returns the path."""
    api_key = api_key or get_secret("elevenlabs")
    if not api_key:
        raise SpeechError("No ElevenLabs API key configured. Add one in Settings → Keys.")
    if not text.strip():
        raise SpeechError("Nothing to synthesize — the narration text is empty.")

    response = httpx.post(
        API_URL.format(voice_id=voice_id),
        headers={"xi-api-key": api_key, "accept": "audio/mpeg"},
        json={
            "text": text,
            "model_id": model_id,
            "voice_settings": {"stability": 0.5, "similarity_boost": 0.75},
        },
        timeout=REQUEST_TIMEOUT,
    )
    if response.status_code >= 400:
        raise SpeechError(f"ElevenLabs TTS returned {response.status_code}: {response.text[:300]}")

    destination.parent.mkdir(parents=True, exist_ok=True)
    destination.write_bytes(response.content)
    log.info("Synthesized %d chars of narration to %s.", len(text), destination)
    return destination


def mux_voiceover(
    clip_source: Path,
    narration: Path,
    destination: Path,
    *,
    narration_gain_db: float = 0.0,
    bed_gain_db: float = -12.0,
) -> Path:
    """Mux a narration track over the clip's original audio.

    The original bed is ducked (not removed) so the voiceover sits on top of
    the source sound rather than replacing it. The video stream is copied —
    no re-encode.
    """
    from ..pipeline.ffmpeg import FFmpegError
    from ..pipeline.ffmpeg import run as run_ffmpeg

    destination.parent.mkdir(parents=True, exist_ok=True)
    filtergraph = (
        f"[1:a]volume={narration_gain_db}dB[n];"
        f"[0:a]volume={bed_gain_db}dB[b];"
        "[n][b]amix=inputs=2:duration=first:dropout_transition=0[a]"
    )
    command = [
        "-i",
        str(clip_source),
        "-i",
        str(narration),
        "-filter_complex",
        filtergraph,
        "-map",
        "0:v",
        "-map",
        "[a]",
        "-c:v",
        "copy",
        "-c:a",
        "aac",
        "-b:a",
        "192k",
        "-shortest",
        str(destination),
    ]
    try:
        run_ffmpeg(command)
    except FFmpegError as exc:
        raise SpeechError(f"Could not mux the narration track: {exc}") from exc
    return destination


__all__ = ["DEFAULT_MODEL_ID", "DEFAULT_VOICE_ID", "mux_voiceover", "synthesize_speech"]
