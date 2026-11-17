"""Tests for the speech engines — ElevenLabs STT, local wrapping, resolution.

The ElevenLabs adapter is exercised against canned Scribe API responses; no
test in this file touches the network or the real keyring.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest
from autoclip.config import Settings, TranscriptionSettings
from autoclip.pipeline.transcript import Transcript
from autoclip.speech import ElevenLabsSTT, LocalWhisperSTT, SpeechError, resolve_engine
from autoclip.speech.elevenlabs import synthesize_segments

# --------------------------------------------------------------------------
# Word mapping
# --------------------------------------------------------------------------


def _scribe_word(text: str, start: float, end: float, **extra: Any) -> dict:
    return {"text": text, "type": "word", "start": start, "end": end, **extra}


def test_spacing_and_audio_event_entries_are_dropped() -> None:
    raw = [
        {"text": " ", "type": "spacing", "start": 0.0, "end": 0.2},
        _scribe_word("Hello", 0.2, 0.5),
        {"text": "(laughter)", "type": "audio_event", "start": 0.5, "end": 1.0},
        _scribe_word("world", 1.0, 1.4),
    ]
    words = ElevenLabsSTT()._map_words(raw)
    assert [w.text for w in words] == ["Hello", "world"]


def test_speaker_ids_are_normalised_to_whisperx_style() -> None:
    raw = [_scribe_word("Hi", 0.0, 0.3, speaker_id="speaker_1")]
    (word,) = ElevenLabsSTT()._map_words(raw)
    assert word.speaker == "SPEAKER_01"


def test_words_without_timings_are_skipped() -> None:
    raw = [_scribe_word("Hi", None, None), _scribe_word("there", 0.5, 0.8)]
    words = ElevenLabsSTT()._map_words(raw)
    assert [w.text for w in words] == ["there"]


def test_segment_grouping_on_sentence_ends() -> None:
    words = [
        *ElevenLabsSTT()._map_words(
            [_scribe_word("First", 0.0, 0.4), _scribe_word("sentence.", 0.4, 0.9)]
        ),
        *ElevenLabsSTT()._map_words(
            [_scribe_word("Second", 1.0, 1.4), _scribe_word("one.", 1.4, 1.8)]
        ),
    ]
    segments = synthesize_segments(words)
    assert len(segments) == 2
    assert segments[0].first_word == 0 and segments[0].last_word == 1
    assert segments[1].first_word == 2 and segments[1].last_word == 3
    assert segments[0].text == "First sentence."
    assert segments[1].start == pytest.approx(1.0)


def test_segment_grouping_on_long_pauses() -> None:
    words = ElevenLabsSTT()._map_words(
        [_scribe_word("One", 0.0, 0.5), _scribe_word("Two", 5.0, 5.5)]
    )
    segments = synthesize_segments(words)
    assert len(segments) == 2


# --------------------------------------------------------------------------
# The Scribe API call (mocked HTTP)
# --------------------------------------------------------------------------


class _FakeResponse:
    def __init__(self, status_code: int, payload: dict | str) -> None:
        self.status_code = status_code
        self._payload = payload

    def json(self) -> dict:
        if isinstance(self._payload, str):
            raise ValueError("not json")
        return self._payload

    @property
    def text(self) -> str:
        return self._payload if isinstance(self._payload, str) else json.dumps(self._payload)


def _post_scribe(monkeypatch: pytest.MonkeyPatch, response: _FakeResponse, calls: list[dict]):
    import httpx

    def fake_post(self, url, **kwargs):
        calls.append({"url": url, **kwargs})
        return response

    monkeypatch.setattr(httpx.Client, "post", fake_post)


@pytest.fixture
def scribe_key(fake_keyring, monkeypatch: pytest.MonkeyPatch) -> None:
    from autoclip import config

    monkeypatch.setattr(config, "get_secret", lambda key, settings=None: "sk-test-key")
    fake_keyring.set_password("autoclip", "elevenlabs", "sk-test-key")


def test_successful_transcription_builds_a_transcript(
    scribe_key, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    calls: list[dict] = []
    payload = {
        "language_code": "en",
        "language_probability": 0.98,
        "text": "Hello world.",
        "words": [
            {"text": " ", "type": "spacing", "start": 0.0, "end": 0.1},
            _scribe_word("Hello", 0.1, 0.5, speaker_id="speaker_0"),
            _scribe_word("world.", 0.5, 1.0),
        ],
    }
    _post_scribe(monkeypatch, _FakeResponse(200, payload), calls)

    audio = tmp_path / "audio.wav"
    audio.write_bytes(b"fake")
    transcript = ElevenLabsSTT().transcribe(audio, TranscriptionSettings())

    assert isinstance(transcript, Transcript)
    assert transcript.source == "elevenlabs"
    assert transcript.language == "en"
    assert [w.text for w in transcript.words] == ["Hello", "world."]
    assert len(transcript.segments) == 1
    assert transcript.segments[0].last_word == 1

    # The request must have carried the pcm fast-path and word timestamps.
    sent = calls[0]["data"]
    assert sent["file_format"] == "pcm_s16le_16"
    assert sent["timestamps_granularity"] == "word"
    assert sent["model_id"] == "scribe_v2"


def test_http_error_becomes_speech_error(
    scribe_key, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    _post_scribe(monkeypatch, _FakeResponse(503, {"error": "overloaded"}), [])

    audio = tmp_path / "audio.wav"
    audio.write_bytes(b"fake")
    with pytest.raises(SpeechError, match="503"):
        ElevenLabsSTT().transcribe(audio, TranscriptionSettings())


def test_missing_key_is_a_configuration_error(tmp_path: Path) -> None:
    audio = tmp_path / "audio.wav"
    audio.write_bytes(b"fake")
    with pytest.raises(SpeechError, match="No ElevenLabs API key"):
        ElevenLabsSTT().transcribe(audio, TranscriptionSettings())


def test_empty_word_list_is_an_error_not_a_crash(
    scribe_key, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    _post_scribe(monkeypatch, _FakeResponse(200, {"language_code": "en", "words": []}), [])

    audio = tmp_path / "audio.wav"
    audio.write_bytes(b"fake")
    with pytest.raises(SpeechError, match="no words"):
        ElevenLabsSTT().transcribe(audio, TranscriptionSettings())


# --------------------------------------------------------------------------
# Engine resolution
# --------------------------------------------------------------------------


def test_auto_without_a_key_resolves_local(monkeypatch: pytest.MonkeyPatch) -> None:
    from autoclip.speech import base as speech_base

    monkeypatch.setattr(speech_base, "get_secret", lambda key, settings=None: None)
    engine, notice = resolve_engine(Settings())
    assert engine.name == "whisper"
    assert notice is not None


def test_auto_with_a_key_resolves_elevenlabs(monkeypatch: pytest.MonkeyPatch) -> None:
    from autoclip.speech import base as speech_base

    monkeypatch.setattr(speech_base, "get_secret", lambda key, settings=None: "sk-test")
    engine, notice = resolve_engine(Settings())
    assert engine.name == "elevenlabs"
    assert notice is None


def test_pinned_local_never_falls_back_to_external(monkeypatch: pytest.MonkeyPatch) -> None:
    from autoclip import config

    monkeypatch.setattr(config, "get_secret", lambda key, settings=None: "sk-test")
    settings = Settings()
    settings.transcription.engine = "local"
    engine, notice = resolve_engine(settings)
    assert engine.name == "whisper"
    assert notice is None


def test_pinned_elevenlabs_ignores_the_local_engine() -> None:
    settings = Settings()
    settings.transcription.engine = "elevenlabs"
    engine, _ = resolve_engine(settings)
    assert engine.name == "elevenlabs"


# --------------------------------------------------------------------------
# Local engine wrapper
# --------------------------------------------------------------------------


def test_local_engine_wraps_transcription_errors(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    from autoclip.pipeline import transcribe as local_transcribe

    def boom(*args: Any, **kwargs: Any) -> None:
        raise local_transcribe.TranscriptionError("No speech was detected in this audio.")

    monkeypatch.setattr(local_transcribe, "transcribe", boom)
    audio = tmp_path / "audio.wav"
    audio.write_bytes(b"fake")
    with pytest.raises(SpeechError, match="No speech"):
        LocalWhisperSTT().transcribe(audio, TranscriptionSettings())


# --------------------------------------------------------------------------
# Runner integration: external fails → local takes over
# --------------------------------------------------------------------------


class _FailingEngine:
    name = "elevenlabs"

    def transcribe(self, *args: Any, **kwargs: Any) -> None:
        raise SpeechError("ElevenLabs returned 503.")


class _WorkingEngine:
    name = "whisper"

    def __init__(self) -> None:
        self.called = False

    def transcribe(self, *args: Any, **kwargs: Any) -> Transcript:
        self.called = True
        return Transcript(source="whisper", model="small")


def test_runner_falls_back_to_local_when_external_fails(
    monkeypatch: pytest.MonkeyPatch, initialised_db: int
) -> None:
    from autoclip.db import store
    from autoclip.db.models import Job, Source
    from autoclip.pipeline.runner import PipelineRunner
    from autoclip.speech import base as speech

    store.create_source(
        Source(id="src123", type="youtube", path="source.webm", url="https://youtu.be/x")
    )
    store.create_job(Job(id="job123", source_id="src123"))

    settings = Settings()
    settings.transcription.engine = "auto"
    job = Job(id="job123", source_id="src123")
    source = Source(id="src123", type="youtube", path="source.webm")
    runner = PipelineRunner(job, source, settings=settings)

    working = _WorkingEngine()
    monkeypatch.setattr(speech, "resolve_engine", lambda _s: (_FailingEngine(), None))
    import autoclip.pipeline.runner as runner_module

    monkeypatch.setattr(runner_module, "LocalWhisperSTT", lambda: working)
    monkeypatch.setattr(runner, "_set_notice", lambda *_a, **_k: None)
    monkeypatch.setattr(runner, "_emit", lambda *_a, **_k: None)
    monkeypatch.setattr(runner, "_finish_stage", lambda *_a, **_k: None)

    transcript = runner._stage_transcribe(Path("audio.wav"))

    assert working.called
    assert transcript.source == "whisper"


def test_runner_surfaces_the_error_when_the_engine_is_pinned(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from autoclip.db.models import Job, Source
    from autoclip.pipeline.runner import PipelineRunner
    from autoclip.speech import base as speech

    settings = Settings()
    settings.transcription.engine = "elevenlabs"
    job = Job(id="job123", source_id="src123")
    source = Source(id="src123", type="youtube", path="source.webm")
    runner = PipelineRunner(job, source, settings=settings)

    monkeypatch.setattr(speech, "resolve_engine", lambda _s: (_FailingEngine(), None))
    monkeypatch.setattr(runner, "_set_notice", lambda *_a, **_k: None)
    monkeypatch.setattr(runner, "_emit", lambda *_a, **_k: None)

    with pytest.raises(SpeechError):
        runner._stage_transcribe(Path("audio.wav"))
