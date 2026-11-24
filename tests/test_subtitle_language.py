"""The language the subtitles are in — the setting, the decision, and the call.

A video's speech and its captions are two different languages more often than
not. The default is English, so a Hindi gaming video gets English captions
without anybody configuring anything, and the user can change the language at
any time.

The tests here cover the three places the decision is made:

* the setting itself — what it accepts, and what it defaults to;
* the plan — which task the recogniser runs for which pair of languages;
* the call — that the plan reaches faster-whisper unchanged, and that the
  transcript records which language the words are in and which language was
  spoken.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest
from autoclip.config import ExportSettings, Settings
from autoclip.pipeline.language import SOURCE_LANGUAGE, plan_subtitles
from autoclip.pipeline.transcript import Transcript

# --------------------------------------------------------------------------
# The setting
# --------------------------------------------------------------------------


class TestSubtitleLanguageSetting:
    def test_english_is_the_default(self) -> None:
        assert ExportSettings().subtitle_language == "en"

    def test_the_default_survives_an_existing_installation(self) -> None:
        # An installation that was configured before the setting existed must
        # not come up with a different default.
        assert Settings().export.subtitle_language == "en"

    def test_the_language_spoken_in_the_video_is_accepted(self) -> None:
        assert ExportSettings(subtitle_language="source").subtitle_language == SOURCE_LANGUAGE

    def test_a_two_letter_code_is_accepted(self) -> None:
        assert ExportSettings(subtitle_language="hi").subtitle_language == "hi"

    def test_the_code_is_normalised(self) -> None:
        assert ExportSettings(subtitle_language=" HI ").subtitle_language == "hi"

    def test_an_empty_value_means_the_default(self) -> None:
        assert ExportSettings(subtitle_language="").subtitle_language == "en"

    def test_a_word_that_is_not_a_language_is_rejected(self) -> None:
        with pytest.raises(ValueError, match="two-letter language code"):
            ExportSettings(subtitle_language="english")

    def test_a_three_letter_code_is_rejected(self) -> None:
        with pytest.raises(ValueError, match="two-letter language code"):
            ExportSettings(subtitle_language="hin")


# --------------------------------------------------------------------------
# The plan
# --------------------------------------------------------------------------


class TestSubtitlePlan:
    def test_the_same_language_is_transcribed(self) -> None:
        plan = plan_subtitles(spoken="hi", target="hi")

        assert plan.task == "transcribe"
        assert plan.language == "hi"
        assert plan.spoken == "hi"
        assert not plan.translated

    def test_english_speech_is_transcribed_not_translated(self) -> None:
        plan = plan_subtitles(spoken="en", target="en")

        assert plan.task == "transcribe"
        assert plan.language == "en"

    def test_other_speech_is_translated_into_english(self) -> None:
        plan = plan_subtitles(spoken="hi", target="en")

        assert plan.task == "translate"
        assert plan.language == "hi"
        assert plan.spoken == "hi"
        assert plan.translated

    def test_an_unknown_language_is_translated_into_english(self) -> None:
        # English is the one target that can be promised without knowing what
        # is being spoken: the translate task produces English whatever the
        # audio turns out to be.
        plan = plan_subtitles(spoken="", target="en")

        assert plan.task == "translate"
        assert plan.spoken == ""

    def test_the_spoken_language_is_kept_when_that_is_what_was_asked_for(self) -> None:
        plan = plan_subtitles(spoken="hi", target=SOURCE_LANGUAGE)

        assert plan.task == "transcribe"
        assert plan.language == "hi"
        assert plan.target == "hi"

    def test_another_target_is_transcribed_with_the_target_pinned(self) -> None:
        plan = plan_subtitles(spoken="hi", target="es")

        assert plan.task == "transcribe"
        assert plan.language == "es"
        assert plan.spoken == "hi"

    def test_an_empty_target_means_english(self) -> None:
        plan = plan_subtitles(spoken="hi", target="")

        assert plan.target == "en"
        assert plan.task == "translate"

    def test_the_codes_are_normalised(self) -> None:
        plan = plan_subtitles(spoken="HI", target=" EN ")

        assert plan.spoken == "hi"
        assert plan.target == "en"


# --------------------------------------------------------------------------
# The call
# --------------------------------------------------------------------------


class _FakeWord:
    def __init__(self, text: str, start: float, end: float) -> None:
        self.word = text
        self.start = start
        self.end = end


class _FakeSegment:
    def __init__(self, text: str, start: float, end: float) -> None:
        self.text = text
        self.start = start
        self.end = end
        self.words = [_FakeWord("hello", start, end)]


class _FakeInfo:
    def __init__(self, language: str = "hi") -> None:
        self.language = language
        self.duration = 10.0


class _FakeModel:
    """A stand-in for faster-whisper's model, recording how it was called."""

    def __init__(self, factory: _FakeFactory, model: str) -> None:
        self.factory = factory
        self.model = model
        self.transcribe_kwargs: dict[str, Any] = {}

    def transcribe(self, audio: str, **kwargs: Any) -> tuple[Any, _FakeInfo]:
        self.transcribe_kwargs = kwargs
        # The real model reports the language it was pinned to, and the one it
        # detected when it was not pinned to anything.
        language = kwargs.get("language") or self.factory.detected[0]
        return iter([_FakeSegment(" hello ", 0.0, 1.0)]), _FakeInfo(language)

    def detect_language(self, audio: Any = None, **kwargs: Any) -> tuple[str, float, list[Any]]:
        return (
            self.factory.detected[0],
            self.factory.detected[1],
            [(self.factory.detected[0], self.factory.detected[1])],
        )


class _FakeFactory:
    """What the fake model answers when it is asked to detect the language."""

    def __init__(self) -> None:
        self.detected = ("hi", 0.99)
        self.models: list[_FakeModel] = []

    def make(self, model: str, device: str = "cpu", compute_type: str = "int8") -> _FakeModel:
        instance = _FakeModel(self, model)
        self.models.append(instance)
        return instance


@pytest.fixture
def fake_whisper(monkeypatch: pytest.MonkeyPatch) -> _FakeFactory:
    """Replace faster-whisper's model with one that records its calls."""
    import faster_whisper

    factory = _FakeFactory()

    monkeypatch.setattr(faster_whisper, "WhisperModel", factory.make)

    from autoclip.pipeline import transcribe as local_transcribe

    monkeypatch.setattr(local_transcribe, "audio_excerpt", lambda *_a, **_k: [0.0, 0.1])

    return factory


class TestTranscriptionLanguage:
    def test_the_default_translates_other_speech_into_english(
        self, fake_whisper: _FakeFactory, tmp_path: Path
    ) -> None:
        from autoclip.pipeline import transcribe as local_transcribe

        transcript = local_transcribe.transcribe(tmp_path / "audio.wav")

        assert fake_whisper.models[0].transcribe_kwargs["task"] == "translate"
        assert fake_whisper.models[0].transcribe_kwargs["language"] == "hi"
        assert transcript.language == "en"
        assert transcript.source_language == "hi"

    def test_english_speech_is_transcribed(
        self, fake_whisper: _FakeFactory, tmp_path: Path
    ) -> None:
        from autoclip.pipeline import transcribe as local_transcribe

        fake_whisper.detected = ("en", 0.99)

        transcript = local_transcribe.transcribe(tmp_path / "audio.wav")

        assert fake_whisper.models[0].transcribe_kwargs["task"] == "transcribe"
        assert fake_whisper.models[0].transcribe_kwargs["language"] == "en"
        assert transcript.language == "en"
        assert transcript.source_language == "en"

    def test_the_spoken_language_can_be_pinned_in_the_settings(
        self, fake_whisper: _FakeFactory, tmp_path: Path
    ) -> None:
        from autoclip.config import WhisperSettings
        from autoclip.pipeline import transcribe as local_transcribe

        local_transcribe.transcribe(
            tmp_path / "audio.wav",
            WhisperSettings(language="hi"),
            subtitle_language="en",
        )

        # The pinned language is used as it is: no detection pass is needed.
        assert fake_whisper.models[0].transcribe_kwargs["task"] == "translate"
        assert fake_whisper.models[0].transcribe_kwargs["language"] == "hi"

    def test_the_source_language_asks_for_no_translation(
        self, fake_whisper: _FakeFactory, tmp_path: Path
    ) -> None:
        from autoclip.pipeline import transcribe as local_transcribe

        transcript = local_transcribe.transcribe(
            tmp_path / "audio.wav", subtitle_language=SOURCE_LANGUAGE
        )

        assert fake_whisper.models[0].transcribe_kwargs["task"] == "transcribe"
        assert fake_whisper.models[0].transcribe_kwargs["language"] is None
        assert transcript.language == "hi"
        assert transcript.source_language == "hi"

    def test_a_weak_detection_leaves_the_decision_to_the_recogniser(
        self, fake_whisper: _FakeFactory, tmp_path: Path
    ) -> None:
        from autoclip.pipeline import transcribe as local_transcribe

        fake_whisper.detected = ("hi", 0.2)

        local_transcribe.transcribe(tmp_path / "audio.wav")

        # Unknown speech, English wanted: the translate task still guarantees
        # English, so it is the one that runs.
        assert fake_whisper.models[0].transcribe_kwargs["task"] == "translate"
        assert fake_whisper.models[0].transcribe_kwargs["language"] is None

    def test_a_chosen_language_is_honoured(
        self, fake_whisper: _FakeFactory, tmp_path: Path
    ) -> None:
        from autoclip.pipeline import transcribe as local_transcribe

        transcript = local_transcribe.transcribe(tmp_path / "audio.wav", subtitle_language="es")

        assert fake_whisper.models[0].transcribe_kwargs["task"] == "transcribe"
        assert fake_whisper.models[0].transcribe_kwargs["language"] == "es"
        assert transcript.language == "es"
        assert transcript.source_language == "hi"


# --------------------------------------------------------------------------
# The transcript record
# --------------------------------------------------------------------------


class TestTranscriptLanguages:
    def test_the_source_language_survives_a_round_trip(self, tmp_path: Path) -> None:
        transcript = Transcript(language="en", source_language="hi", words=[])

        path = transcript.save(tmp_path / "transcript.json")
        reloaded = Transcript.load(path)

        assert reloaded.language == "en"
        assert reloaded.source_language == "hi"

    def test_an_older_transcript_without_the_field_still_loads(self, tmp_path: Path) -> None:
        path = tmp_path / "transcript.json"
        path.write_text(
            '{"language": "hi", "model": "small", "source": "whisper", "words": []}',
            encoding="utf-8",
        )

        reloaded = Transcript.load(path)

        assert reloaded.language == "hi"
        assert reloaded.source_language == ""


# --------------------------------------------------------------------------
# The runner
# --------------------------------------------------------------------------


class _RecordingEngine:
    """A speech engine that records its calls and returns a fixed transcript."""

    def __init__(self, transcript: Transcript, name: str = "whisper") -> None:
        self.name = name
        self.transcript = transcript
        self.calls: list[dict[str, Any]] = []

    def transcribe(self, *args: Any, **kwargs: Any) -> Transcript:
        self.calls.append(kwargs)
        return self.transcript


def _runner(monkeypatch: pytest.MonkeyPatch, settings: Settings, engine: Any):
    from autoclip.db import store
    from autoclip.db.models import Job, Source
    from autoclip.pipeline.runner import PipelineRunner

    monkeypatch.setattr(PipelineRunner, "_set_notice", lambda *_a, **_k: None)
    monkeypatch.setattr(PipelineRunner, "_emit", lambda *_a, **_k: None)
    monkeypatch.setattr(PipelineRunner, "_finish_stage", lambda *_a, **_k: None)

    store.create_source(
        Source(id="src123", type="youtube", path="source.mp4", url="https://youtu.be/x")
    )
    store.create_job(Job(id="job123", source_id="src123"))

    job = Job(id="job123", source_id="src123")
    source = Source(id="src123", type="youtube", path="source.mp4")
    return PipelineRunner(job, source, settings=settings)


class TestRunnerSubtitleLanguage:
    def test_the_requested_language_reaches_the_engine(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path, initialised_db: int
    ) -> None:
        from autoclip.speech import base as speech

        settings = Settings()
        settings.export.subtitle_language = "es"
        engine = _RecordingEngine(Transcript(language="es", source_language="hi"))
        monkeypatch.setattr(speech, "resolve_engine", lambda _s: (engine, None))

        runner = _runner(monkeypatch, settings, engine)
        runner._stage_transcribe(tmp_path / "audio.wav")

        assert engine.calls[0]["subtitle_language"] == "es"

    def test_an_external_engine_that_cannot_translate_is_tried_locally(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path, initialised_db: int
    ) -> None:
        from autoclip.pipeline import runner as runner_module
        from autoclip.speech import base as speech

        settings = Settings()
        settings.export.subtitle_language = "en"

        external = _RecordingEngine(
            Transcript(language="hi", source_language="hi"), name="elevenlabs"
        )
        local = _RecordingEngine(Transcript(language="en", source_language="hi"), name="whisper")
        monkeypatch.setattr(speech, "resolve_engine", lambda _s: (external, None))
        monkeypatch.setattr(runner_module, "LocalWhisperSTT", lambda: local)

        runner = _runner(monkeypatch, settings, external)
        transcript = runner._stage_transcribe(tmp_path / "audio.wav")

        assert local.calls, "the local engine should have been asked for English captions"
        assert transcript.language == "en"

    def test_a_pinned_external_engine_says_what_it_cannot_do(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path, initialised_db: int
    ) -> None:
        from autoclip.speech import base as speech
        from autoclip.speech.base import SpeechError

        settings = Settings()
        settings.export.subtitle_language = "en"
        settings.transcription.engine = "elevenlabs"

        external = _RecordingEngine(
            Transcript(language="hi", source_language="hi"), name="elevenlabs"
        )
        monkeypatch.setattr(speech, "resolve_engine", lambda _s: (external, None))

        runner = _runner(monkeypatch, settings, external)

        with pytest.raises(SpeechError, match="does not"):
            runner._stage_transcribe(tmp_path / "audio.wav")

    def test_a_saved_transcript_in_another_language_is_not_reused(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path, initialised_db: int
    ) -> None:
        from autoclip.speech import base as speech

        settings = Settings()
        settings.export.subtitle_language = "en"

        engine = _RecordingEngine(Transcript(language="en", source_language="hi"))
        monkeypatch.setattr(speech, "resolve_engine", lambda _s: (engine, None))

        runner = _runner(monkeypatch, settings, engine)
        runner.workspace.transcript.parent.mkdir(parents=True, exist_ok=True)
        Transcript(language="hi", source_language="hi").save(runner.workspace.transcript)

        transcript = runner._stage_transcribe(tmp_path / "audio.wav")

        assert engine.calls, "the transcript should have been made again"
        assert transcript.language == "en"

    def test_a_saved_transcript_in_the_right_language_is_reused(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path, initialised_db: int
    ) -> None:
        from autoclip.speech import base as speech

        settings = Settings()
        settings.export.subtitle_language = "en"

        engine = _RecordingEngine(Transcript(language="en", source_language="hi"))
        monkeypatch.setattr(speech, "resolve_engine", lambda _s: (engine, None))

        runner = _runner(monkeypatch, settings, engine)
        runner.workspace.transcript.parent.mkdir(parents=True, exist_ok=True)
        Transcript(language="en", source_language="hi").save(runner.workspace.transcript)

        transcript = runner._stage_transcribe(tmp_path / "audio.wav")

        assert not engine.calls, "the saved transcript should have been reused"
        assert transcript.language == "en"
