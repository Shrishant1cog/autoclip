"""Transcribe stage — audio to word-level timestamps.

faster-whisper does the transcription; WhisperX (optional) adds speaker labels.
Word-level timing is non-negotiable: clip boundaries, caption animation, and
trim-handle snapping all derive from it.
"""

from __future__ import annotations

import logging
from collections.abc import Callable
from pathlib import Path
from typing import Any

from ..config import WhisperSettings
from ..system import GPUInfo, report
from . import ffmpeg
from .language import (
    DEFAULT_SUBTITLE_LANGUAGE,
    SOURCE_LANGUAGE,
    SubtitlePlan,
    normalise_target,
    plan_subtitles,
)
from .transcript import Segment, Transcript, Word

log = logging.getLogger(__name__)

#: How much of the audio the language detector is given.
#:
#: Thirty seconds is what Whisper itself looks at when it detects a language,
#: so the answer here and the answer inside the transcription agree.
LANGUAGE_DETECT_SECONDS = 30.0

#: Below this probability the detected language is not trusted, and the
#: recogniser is left to decide for itself.
LANGUAGE_DETECT_MIN_CONFIDENCE = 0.5


class TranscriptionError(RuntimeError):
    """Transcription could not be completed."""


def resolve_compute(settings: WhisperSettings, gpu: GPUInfo | None = None) -> tuple[str, str]:
    """Return the ``(device, compute_type)`` to run Whisper with.

    An explicit ``settings.compute_type`` wins, but only if the device actually
    supports it. An override the backend will reject fails at model load with a
    message that points at cuDNN rather than at the setting, so an unsupported
    override is warned about and ignored rather than honoured into a crash.
    """
    gpu = gpu if gpu is not None else report().gpu
    automatic = gpu.compute_type

    override = settings.compute_type
    if not override:
        return gpu.device, automatic

    supported = gpu.supported_compute_types
    if supported and override not in supported:
        log.warning(
            "whisper.compute_type is set to %r, which %s does not support "
            "(supported: %s). Using %r instead.",
            override,
            gpu.device,
            ", ".join(sorted(supported)),
            automatic,
        )
        return gpu.device, automatic

    return gpu.device, override


def _model_load_error(exc: Exception, device: str, compute_type: str) -> TranscriptionError:
    """Turn a Whisper model-load failure into something actionable.

    The two causes look identical from the outside and need opposite fixes, so
    they're distinguished rather than lumped under one guess.
    """
    message = str(exc)
    lowered = message.lower()

    if "compute type" in lowered or "not support" in lowered:
        supported = report().gpu.supported_compute_types
        options = ", ".join(sorted(supported)) if supported else "unknown"
        return TranscriptionError(
            f"This device does not support the '{compute_type}' compute type.\n"
            f"Supported on {device}: {options}.\n\n"
            "Clear whisper.compute_type in config.json to let AutoClip choose, "
            "or set it to one of the supported values."
        )

    if device == "cuda" and ("cudnn" in lowered or "library" in lowered or "dll" in lowered):
        return TranscriptionError(
            f"Could not load Whisper on the GPU: {message}\n\n"
            "This is a missing CUDA runtime library. Install it with "
            "`uv pip install 'autoclip[gpu]'`, then retry — the job resumes "
            "from this stage."
        )

    return TranscriptionError(f"Could not load the Whisper model: {message}")


def transcribe(
    audio: Path,
    settings: WhisperSettings | None = None,
    *,
    duration_s: float | None = None,
    on_progress: Callable[[float], None] | None = None,
    cancelled: Callable[[], bool] | None = None,
    subtitle_language: str = "",
) -> Transcript:
    """Transcribe an audio file into a :class:`Transcript` with word timings.

    ``subtitle_language`` is the language the captions are wanted in, not the
    language the audio is in. The default is English, so a video spoken in
    another language is translated as it is decoded and every word keeps the
    timing of the speech it came from. ``source`` keeps the spoken language;
    any other two-letter code asks for that language.

    Preconditions:
        audio is a decodable audio file, ideally 16 kHz mono as produced by
        :func:`autoclip.pipeline.prepare.extract_audio`.
    """
    settings = settings or WhisperSettings()

    # Must happen before faster-whisper pulls in CTranslate2, which resolves its
    # CUDA dependencies at import.
    from ..cuda import ensure_cuda_libraries

    ensure_cuda_libraries()

    try:
        from faster_whisper import WhisperModel
    except ImportError as exc:  # pragma: no cover - faster-whisper is a core dep
        raise TranscriptionError(
            "faster-whisper is not installed. Run `autoclip doctor` for details."
        ) from exc

    device, compute_type = resolve_compute(settings)
    log.info(
        "Transcribing with model=%s device=%s compute_type=%s",
        settings.model,
        device,
        compute_type,
    )

    try:
        model = WhisperModel(settings.model, device=device, compute_type=compute_type)
    except Exception as exc:
        raise _model_load_error(exc, device, compute_type) from exc

    plan = _plan_for(audio, model, settings=settings, subtitle_language=subtitle_language)
    log.info(
        "Transcribing with model=%s device=%s compute_type=%s task=%s language=%s "
        "(spoken=%s, subtitles in %s)",
        settings.model,
        device,
        compute_type,
        plan.task,
        plan.language or "auto",
        plan.spoken or "unknown",
        plan.target or "the spoken language",
    )

    segments_iter, info = model.transcribe(
        str(audio),
        language=plan.language or None,
        task=plan.task,
        word_timestamps=True,
        vad_filter=True,
        # Trims long silences before decoding, which both speeds things up and
        # stops Whisper hallucinating text into empty audio.
        vad_parameters={"min_silence_duration_ms": 500},
    )

    total = duration_s or getattr(info, "duration", 0.0) or 0.0
    transcript = Transcript(
        language=_subtitle_language_of(plan, info),
        source_language=_spoken_language_of(plan, info),
        model=settings.model,
        source="whisper",
    )

    for segment in segments_iter:
        if cancelled is not None and cancelled():
            raise TranscriptionError("Transcription cancelled.")

        first_word = len(transcript.words)
        for word in getattr(segment, "words", None) or []:
            text = (word.word or "").strip()
            if not text:
                continue
            transcript.words.append(Word(text=text, start=float(word.start), end=float(word.end)))

        # A segment with no word timings still carries text worth keeping for
        # display, but it can't contribute to word-indexed clip boundaries.
        last_word = max(first_word, len(transcript.words) - 1)
        transcript.segments.append(
            Segment(
                text=(segment.text or "").strip(),
                start=float(segment.start),
                end=float(segment.end),
                first_word=first_word,
                last_word=last_word,
            )
        )

        if on_progress and total:
            on_progress(min(1.0, float(segment.end) / total))

    if not transcript.words:
        raise TranscriptionError(
            "No speech was detected in this audio. If the file really does contain "
            "speech, try a larger Whisper model or check that the correct audio track "
            "was extracted."
        )

    if on_progress:
        on_progress(1.0)

    log.info(
        "Transcribed %d words in %d segments.", len(transcript.words), len(transcript.segments)
    )
    return transcript


# --------------------------------------------------------------------------
# Language
# --------------------------------------------------------------------------


def _plan_for(
    audio: Path,
    model: Any,
    *,
    settings: WhisperSettings,
    subtitle_language: str,
) -> SubtitlePlan:
    """Decide what the recogniser should do, detecting the spoken language if needed.

    The spoken language is only needed when the captions are wanted in a
    language that is not the one being spoken. When it is needed and is not
    already pinned in the settings, the detector is asked for it — one short
    pass over the opening of the audio, which is what Whisper itself does when
    it is left to decide.
    """
    target = normalise_target(subtitle_language)
    spoken = (settings.language or "").strip().lower()

    if spoken or target == SOURCE_LANGUAGE:
        return plan_subtitles(spoken=spoken, target=target)

    detected, probability = detect_spoken_language(model, audio)
    if detected and probability < LANGUAGE_DETECT_MIN_CONFIDENCE:
        log.warning(
            "The language of the audio was only %.0f%% certain (%s); the recogniser "
            "will decide for itself.",
            probability * 100,
            detected,
        )
        detected = ""

    return plan_subtitles(spoken=detected, target=target)


def detect_spoken_language(model: Any, audio: Path) -> tuple[str, float]:
    """The language spoken in the audio, as Whisper sees it.

    Returns the language code and the confidence. An empty code means the
    question could not be answered; it is never a guess.
    """
    excerpt = audio_excerpt(audio, LANGUAGE_DETECT_SECONDS)
    if excerpt is None or len(excerpt) == 0:
        return "", 0.0

    try:
        language, probability, _ = model.detect_language(audio=excerpt)
    except Exception as exc:  # noqa: BLE001 - a detector failure is an answer, not a crash
        log.warning("Could not detect the language of %s: %s", audio.name, exc)
        return "", 0.0

    return (language or "").strip().lower(), float(probability or 0.0)


def audio_excerpt(audio: Path, seconds: float) -> Any:
    """The first ``seconds`` of the audio, as 16 kHz mono float samples.

    The recogniser's language detector wants exactly this: one channel of
    16 kHz floats. Decoding it with ffmpeg means any input the pipeline can
    handle works, not only the prepared WAV.
    """
    import numpy as np

    command = [
        ffmpeg.ffmpeg_path(),
        "-hide_banner",
        "-nostats",
        *ffmpeg.protocol_args(),
        "-t",
        f"{max(1.0, seconds):.3f}",
        "-i",
        str(audio),
        "-f",
        "f32le",
        "-ac",
        "1",
        "-ar",
        "16000",
        "-",
    ]

    try:
        proc = ffmpeg.run_captured_bytes(command)
    except ffmpeg.FFmpegError as exc:
        log.warning("Could not read the opening of %s: %s", audio.name, exc)
        return None

    if proc.returncode != 0:
        log.warning(
            "Could not read the opening of %s: %s",
            audio.name,
            (proc.stderr or b"").decode("utf-8", "replace").strip()[:300],
        )
        return None

    return np.frombuffer(proc.stdout, dtype=np.float32)


def _subtitle_language_of(plan: SubtitlePlan, info: Any) -> str:
    """The language the words are in.

    After a translation the words are English even though the audio was not,
    and after a plain transcription they are whatever was spoken. The
    recogniser's own answer wins where there is one, because it is the
    language of the text it actually produced.
    """
    detected = (getattr(info, "language", "") or "").strip().lower()
    if plan.translated:
        return DEFAULT_SUBTITLE_LANGUAGE
    return detected or plan.target or plan.spoken


def _spoken_language_of(plan: SubtitlePlan, info: Any) -> str:
    """The language spoken in the audio.

    The plan's own answer comes first: when the recogniser was pinned to a
    target language, the language it reports is that target, not the speech.
    """
    detected = (getattr(info, "language", "") or "").strip().lower()
    return plan.spoken or detected


# --------------------------------------------------------------------------
# Diarization
# --------------------------------------------------------------------------


def diarize(
    audio: Path,
    transcript: Transcript,
    *,
    hf_token: str | None = None,
    min_speakers: int | None = None,
    max_speakers: int | None = None,
) -> Transcript:
    """Label each word with a speaker, in place.

    Uses pyannote via WhisperX. Returns the transcript unchanged (with a logged
    warning) if diarization isn't available — speaker labels improve reframing
    but are never required for the pipeline to complete.

    Preconditions:
        transcript already has word-level timings.
    """
    if not transcript.words:
        return transcript

    pipeline_cls = _load_diarization_pipeline()
    if pipeline_cls is None:
        log.warning(
            "WhisperX is not installed; skipping diarization. "
            "Install it with `uv pip install 'autoclip[diarization]'`."
        )
        return transcript

    if not hf_token:
        log.warning(
            "Diarization needs a HuggingFace token. Set one with "
            "`autoclip config set-secret huggingface_token`, and accept the pyannote "
            "model licences on huggingface.co. Continuing without speaker labels."
        )
        return transcript

    device = report().gpu.device
    try:
        pipeline = pipeline_cls(use_auth_token=hf_token, device=device)
        diarization = pipeline(str(audio), min_speakers=min_speakers, max_speakers=max_speakers)
    except Exception as exc:
        log.warning("Diarization failed (%s); continuing without speaker labels.", exc)
        return transcript

    turns = _diarization_turns(diarization)
    if not turns:
        return transcript

    _assign_speakers(transcript, turns)
    log.info("Diarization labelled %d speakers.", len(transcript.speakers))
    return transcript


def _load_diarization_pipeline():
    """Import WhisperX's diarization pipeline across its API reshuffles."""
    try:
        from whisperx.diarize import DiarizationPipeline

        return DiarizationPipeline
    except ImportError:
        pass
    try:
        from whisperx import DiarizationPipeline  # type: ignore[attr-defined]

        return DiarizationPipeline
    except (ImportError, AttributeError):
        return None


def _diarization_turns(diarization) -> list[tuple[str, float, float]]:
    """Normalise WhisperX output into ``(speaker, start, end)`` tuples.

    Recent versions return a pandas DataFrame; older ones return a pyannote
    ``Annotation``. Both are handled so the extra can be upgraded independently.
    """
    turns: list[tuple[str, float, float]] = []

    if hasattr(diarization, "itertuples"):  # DataFrame
        for row in diarization.itertuples():
            speaker = getattr(row, "speaker", None)
            start = getattr(row, "start", None)
            end = getattr(row, "end", None)
            if speaker is not None and start is not None and end is not None:
                turns.append((str(speaker), float(start), float(end)))
        return turns

    if hasattr(diarization, "itertracks"):  # pyannote Annotation
        for segment, _, speaker in diarization.itertracks(yield_label=True):
            turns.append((str(speaker), float(segment.start), float(segment.end)))

    return turns


def _assign_speakers(transcript: Transcript, turns: list[tuple[str, float, float]]) -> None:
    """Attach a speaker to every word by maximum temporal overlap.

    Overlap rather than midpoint containment: words straddling a turn boundary
    are common, and the speaker who covers more of the word is the better guess.
    """
    turns = sorted(turns, key=lambda t: t[1])

    for word in transcript.words:
        best_speaker: str | None = None
        best_overlap = 0.0
        for speaker, start, end in turns:
            if start > word.end:
                break
            overlap = min(word.end, end) - max(word.start, start)
            if overlap > best_overlap:
                best_overlap = overlap
                best_speaker = speaker
        word.speaker = best_speaker

    for segment in transcript.segments:
        segment.speaker = transcript.dominant_speaker(segment.first_word, segment.last_word)
