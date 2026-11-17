"""ElevenLabs Scribe — hosted speech-to-text.

Posts the extracted 16 kHz mono WAV straight to
``POST /v1/speech-to-text`` — the ``pcm_s16le_16`` fast path means no
re-encode. The response's flat word list is mapped onto AutoClip's
:class:`Transcript`: non-word entries (``spacing``, ``audio_event``) are
dropped because clip boundaries are word-indexed, speaker labels are
normalised to the WhisperX convention, and segments are synthesised by
grouping words on sentence ends, because Scribe returns none.
"""

from __future__ import annotations

import logging
from collections.abc import Callable
from pathlib import Path

import httpx

from ..config import TranscriptionSettings, get_secret
from ..pipeline.transcript import Segment, Transcript, Word
from .base import SpeechError

log = logging.getLogger(__name__)

API_URL = "https://api.elevenlabs.io/v1/speech-to-text"
REQUEST_TIMEOUT = 600.0  # a 4-hour upload can take a while to transcribe

#: Scribe word types that are not words. ``spacing`` is silence between words;
#: ``audio_event`` is (laughter), (music) and friends. Neither may enter the
#: word list — highlight detection addresses the audio by word index.
_NON_WORD_TYPES = frozenset({"spacing", "audio_event"})


def synthesize_segments(words: list[Word]) -> list[Segment]:
    """Group a flat word list into sentence-ish segments.

    Scribe returns only words; every downstream consumer (highlight windows,
    the transcript sidebar, diarization turns) expects segments. A new segment
    starts where the previous word ended a sentence or clause, or where the
    pause between words exceeds three seconds.
    """
    segments: list[Segment] = []
    first_word = 0

    for i, word in enumerate(words):
        last = i == len(words) - 1
        gap_break = not last and i + 1 < len(words) and words[i + 1].start - word.end > 3.0
        if word.ends_clause or last or gap_break:
            text = " ".join(w.text for w in words[first_word : i + 1])
            segments.append(
                Segment(
                    text=text,
                    start=words[first_word].start,
                    end=word.end,
                    first_word=first_word,
                    last_word=i,
                )
            )
            first_word = i + 1

    return segments


class ElevenLabsSTT:
    """Hosted transcription via the ElevenLabs Scribe API."""

    name = "elevenlabs"

    def transcribe(
        self,
        audio: Path,
        settings: TranscriptionSettings,
        *,
        language: str = "",
        duration_s: float | None = None,
        on_progress: Callable[[float], None] | None = None,
        cancelled: Callable[[], bool] | None = None,
    ) -> Transcript:
        api_key = get_secret("elevenlabs")
        if not api_key:
            raise SpeechError("No ElevenLabs API key configured. Add one in Settings → Keys.")

        if cancelled is not None and cancelled():
            raise SpeechError("Transcription cancelled.")

        if on_progress:
            on_progress(0.05)

        fields: dict[str, str] = {
            "model_id": settings.elevenlabs_model,
            # The extracted WAV is already 16-bit / 16 kHz / mono, so this
            # skips server-side decoding entirely.
            "file_format": "pcm_s16le_16",
            "timestamps_granularity": "word",
            "diarize": "true" if settings.diarize else "false",
            "tag_audio_events": "true",
        }
        if language:
            fields["language_code"] = language

        if on_progress:
            on_progress(0.1)

        try:
            with httpx.Client(timeout=REQUEST_TIMEOUT) as client, audio.open("rb") as handle:
                # Stream the upload so a multi-hundred-MB WAV is not slurped
                # into memory just to be sent.
                response = client.post(
                    API_URL,
                    headers={"xi-api-key": api_key},
                    data=fields,
                    files={"file": (audio.name, handle, "audio/wav")},
                )
        except httpx.HTTPError as exc:
            raise SpeechError(f"ElevenLabs request failed: {exc}") from exc

        if response.status_code >= 400:
            detail = response.text[:300]
            raise SpeechError(f"ElevenLabs returned {response.status_code}: {detail}")

        try:
            payload = response.json()
        except ValueError as exc:
            raise SpeechError("ElevenLabs returned a non-JSON response.") from exc

        if cancelled is not None and cancelled():
            raise SpeechError("Transcription cancelled.")

        try:
            words = self._map_words(payload.get("words") or [])
        except (KeyError, TypeError, AttributeError) as exc:
            raise SpeechError(f"Unexpected ElevenLabs response shape: {exc}") from exc

        if not words:
            raise SpeechError(
                "ElevenLabs returned no words for this audio. If the file really "
                "does contain speech, check the model setting or the audio track."
            )

        transcript = Transcript(
            language=str(payload.get("language_code") or language or ""),
            model=settings.elevenlabs_model,
            source=self.name,
        )
        transcript.words = words
        transcript.segments = synthesize_segments(words)

        if on_progress:
            on_progress(1.0)

        log.info("Transcribed %d words with ElevenLabs %s.", len(words), settings.elevenlabs_model)
        return transcript

    def _map_words(self, raw_words: list[dict]) -> list[Word]:
        """Convert Scribe word objects to AutoClip words.

        Speaker labels are normalised from Scribe's ``speaker_1`` to the
        WhisperX-style ``SPEAKER_01`` that the reframe stage matches faces
        against.
        """
        words: list[Word] = []
        for item in raw_words:
            if item.get("type") in _NON_WORD_TYPES:
                continue
            text = str(item.get("text") or "").strip()
            if not text:
                continue
            start = item.get("start")
            end = item.get("end")
            if start is None or end is None:
                continue
            speaker = item.get("speaker_id")
            if speaker:
                digits = "".join(ch for ch in str(speaker) if ch.isdigit())
                speaker = f"SPEAKER_{int(digits or 0):02d}"
            words.append(Word(text=text, start=float(start), end=float(end), speaker=speaker))
        return words


__all__ = ["ElevenLabsSTT", "synthesize_segments"]
