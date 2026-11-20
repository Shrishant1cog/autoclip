"""Pipeline orchestration.

Runs a job stage by stage, writing each stage's artifacts into
``work/{job_id}/``. Because every stage's output is a file on disk, a retry
skips everything already done and resumes at the stage that failed — which
matters when stage two took eleven minutes and stage four hit a rate limit.

Progress is reported through a callback rather than written directly, so the
same runner serves the CLI (a progress bar) and the web API (an SSE stream).
"""

from __future__ import annotations

import asyncio
import json
import logging
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from .. import paths, resources
from ..config import Settings
from ..config import load as load_settings
from ..db import store
from ..db.models import Clip, Export, Job, JobResources, Source, new_id, utcnow
from ..db.models import Transcript as TranscriptRow
from ..providers import LLMProvider, build_provider, detection_config
from ..providers.base import looks_like_auth_failure, looks_like_transient_failure
from ..speech import LocalWhisperSTT
from ..speech import base as speech
from . import (
    Stage,
    captions,
    export,
    ffmpeg,
    highlights,
    ingest,
    prepare,
    speech_timeline,
    transcribe,
    validate,
)
from .prepare import Silence
from .reframe import ReframeConfig, build_crop_path
from .reframe.croppath import CropPath
from .transcript import Transcript

log = logging.getLogger(__name__)


def _maybe_enqueue_upload(export_id: str, settings: Settings) -> None:
    """Queue YouTube uploads when automation is on. Never raises."""
    try:
        from ..youtube.queue import upload_queue
        from ..youtube.uploads import enqueue_export_all

        if enqueue_export_all(export_id, settings):
            upload_queue.notify()
    except Exception:  # an upload must never fail the pipeline
        log.exception("Could not queue a YouTube upload for export %s.", export_id)


def _job_title(job: Job) -> str:
    """The human name of the video a job is processing."""
    source = store.get_source(job.source_id)
    if source is None:
        return job.source_id
    return source.title or source.filename or job.source_id


def _notify_job_done(job: Job, clips: list[Clip]) -> None:
    """Tell the user the pipeline finished. Never raises."""
    try:
        from ..notifications import events

        events.job_done(job.id, _job_title(job), len(clips))
    except Exception:  # noqa: BLE001
        log.debug("Could not record the job-done notification.", exc_info=True)


def _notify_job_failed(job: Job, error: BaseException) -> None:
    """Tell the user the pipeline failed. Never raises."""
    try:
        from ..notifications import events

        events.job_failed(job.id, _job_title(job), str(error))
    except Exception:  # noqa: BLE001
        log.debug("Could not record the job-failed notification.", exc_info=True)


#: Weight of each stage in the overall progress bar. Rough proportions of wall
#: time on a mid-range machine — transcription and export dominate.
STAGE_WEIGHTS: dict[Stage, float] = {
    Stage.PREPARE: 0.05,
    Stage.TRANSCRIBE: 0.35,
    Stage.HIGHLIGHTS: 0.15,
    Stage.REFRAME: 0.20,
    Stage.CAPTIONS: 0.02,
    Stage.EXPORT: 0.23,
}


class JobCancelled(RuntimeError):
    """The job was cancelled by the user."""


class PipelineError(RuntimeError):
    """A stage failed in a way the user should see."""

    def __init__(self, message: str, *, stage: Stage) -> None:
        super().__init__(message)
        self.stage = stage


@dataclass
class ProgressEvent:
    stage: Stage
    #: Progress within the stage, 0..1.
    stage_progress: float
    #: Progress across the whole job, 0..1.
    overall: float
    message: str = ""


ProgressHandler = Callable[[ProgressEvent], None]


class JobWorkspace:
    """Paths for one job's intermediate artifacts."""

    def __init__(self, job_id: str) -> None:
        self.root = paths.job_work_dir(job_id)
        self.root.mkdir(parents=True, exist_ok=True)

    @property
    def audio(self) -> Path:
        return self.root / "audio.wav"

    @property
    def transcript(self) -> Path:
        return self.root / "transcript.json"

    @property
    def silences(self) -> Path:
        return self.root / "silences.json"

    @property
    def speech_timeline(self) -> Path:
        """The shared speech timeline for this source video.

        Built once, after the transcript exists, and reused by every
        downstream stage that needs to know when someone is speaking.
        """
        return self.root / "speech_timeline.json"

    @property
    def thumbnails(self) -> Path:
        return self.root / "thumbnails"

    def crop_path(self, clip_id: str) -> Path:
        return self.root / "crops" / f"{clip_id}.json"

    @property
    def captions_dir(self) -> Path:
        return self.root / "captions"


class PipelineRunner:
    """Executes one job."""

    def __init__(
        self,
        job: Job,
        source: Source,
        *,
        settings: Settings | None = None,
        on_progress: ProgressHandler | None = None,
        is_cancelled: Callable[[], bool] | None = None,
    ) -> None:
        self.job = job
        self.source = source
        self.settings = settings or load_settings()
        self.on_progress = on_progress
        self._is_cancelled = is_cancelled or (lambda: False)
        self.workspace = JobWorkspace(job.id)
        self._completed_weight = 0.0
        self._notices: dict[Stage, str] = {}
        self._last_overall = 0.0
        #: What this job consumed (Phase 16). Measured as the work happens.
        self.usage = resources.Usage()

    # -- progress ----------------------------------------------------------

    def _check_cancelled(self) -> None:
        if self._is_cancelled():
            raise JobCancelled("Job cancelled.")

    def _emit(
        self,
        stage: Stage,
        stage_progress: float,
        message: str = "",
        *,
        overall: float | None = None,
    ) -> None:
        if overall is None:
            overall = self._completed_weight + STAGE_WEIGHTS[stage] * stage_progress
        overall = min(1.0, overall)
        # The bar must never run backwards. Progress reported by a stage is not
        # guaranteed to be monotonic — ffmpeg's output clock can tick back by a
        # frame when a filter reorders frames, and a provider that reports
        # window-by-window can repeat a fraction. Clamping to the high-water
        # mark keeps the invariant regardless of what the stage hands us.
        overall = max(overall, self._last_overall)
        self._last_overall = overall
        store.update_job(self.job.id, current_stage=stage.value, progress=round(overall, 4))
        if not message:
            message = self._notices.get(stage, stage.label)
        if self.on_progress:
            self.on_progress(
                ProgressEvent(
                    stage=stage,
                    stage_progress=stage_progress,
                    overall=overall,
                    message=message,
                )
            )

    def _set_notice(self, stage: Stage, message: str) -> None:
        """Show ``message`` for every progress update until the stage finishes.

        Used for things the user must not miss — an API key failing and the
        pipeline switching to a local model — even as per-window progress
        events keep arriving with no message of their own.
        """
        self._notices[stage] = message

    def _finish_stage(self, stage: Stage) -> None:
        """Mark a stage complete.

        ``overall`` is passed explicitly rather than derived. Deriving it after
        incrementing the accumulated weight counts the stage twice, so the bar
        jumped past the true total and then snapped backwards when the next
        stage reported 0 — visibly, at every stage boundary.
        """
        self._completed_weight += STAGE_WEIGHTS[stage]
        self._emit(stage, 1.0, overall=self._completed_weight)
        self._notices.pop(stage, None)

    def _stage_progress(self, stage: Stage) -> Callable[[float], None]:
        def report(fraction: float) -> None:
            self._emit(stage, max(0.0, min(1.0, fraction)))

        return report

    # -- entry point -------------------------------------------------------

    async def run(self) -> list[Clip]:
        """Run the full pipeline and return the exported clips."""
        store.update_job(self.job.id, status="running", started_at=utcnow(), error=None)

        try:
            audio = self._stage_prepare()
            transcript = self._stage_transcribe(audio)
            silences = self._load_or_detect_silences(audio)
            clips = await self._stage_highlights(transcript, silences)
            crop_paths = self._stage_reframe(clips, transcript)
            self._stage_captions(clips, transcript)
            self._stage_export(clips, transcript, crop_paths)
        except JobCancelled:
            store.update_job(self.job.id, status="cancelled", finished_at=utcnow(), progress=0.0)
            self._record_usage()
            raise
        except Exception as exc:
            log.exception("Job %s failed.", self.job.id)
            store.update_job(self.job.id, status="failed", error=str(exc), finished_at=utcnow())
            self._record_usage()
            _notify_job_failed(self.job, exc)
            raise

        store.update_job(self.job.id, status="done", progress=1.0, finished_at=utcnow())
        self._record_usage()
        _notify_job_done(self.job, clips)
        return clips

    def _record_usage(self) -> None:
        """Persist what this job consumed (Phase 16).

        Written even when the job failed: the work spent up to the failure is
        still work spent, and a failed job that burned a lot of tokens is
        exactly the one worth knowing about.
        """
        try:
            store.upsert_job_resources(
                JobResources(
                    job_id=self.job.id,
                    llm_calls=self.usage.llm.calls,
                    llm_input_tokens=self.usage.llm.input_tokens,
                    llm_output_tokens=self.usage.llm.output_tokens,
                    ffmpeg_runs=self.usage.ffmpeg_runs,
                    ffmpeg_seconds=self.usage.ffmpeg_seconds,
                    export_bytes=self.usage.export_bytes,
                    windows_skipped=self.usage.windows_skipped,
                )
            )
        except Exception:  # noqa: BLE001 — accounting must never fail a job
            log.debug("Could not record resource usage for job %s.", self.job.id, exc_info=True)

    # -- stages ------------------------------------------------------------

    def _stage_prepare(self) -> Path:
        stage = Stage.PREPARE
        self._check_cancelled()

        # YouTube sources are inserted as pending rows so the API can return
        # immediately. The actual download happens here, on the background
        # worker, before any audio work starts.
        downloaded = False
        if not self._source_is_ready():
            self._download_source(stage)
            downloaded = True

        source_path = Path(self.source.path)
        report = self._stage_progress(stage)
        # Reserve the first 90% of the stage for the download, when there is one,
        # so extraction continues from where the download left off instead of
        # snapping the bar back to zero.
        base = 0.9 if downloaded else 0.0
        scale = 0.1 if downloaded else 1.0

        if self.workspace.audio.exists() and self.workspace.audio.stat().st_size > 0:
            log.info("Reusing existing audio for job %s.", self.job.id)
        else:
            self._emit(stage, base, "Extracting audio")
            prepare.extract_audio(
                source_path,
                self.workspace.audio,
                duration_s=self.source.duration_s,
                on_progress=lambda fraction: report(base + scale * fraction),
                threads=self.settings.resources.ffmpeg_threads,
                usage=self.usage,
            )

        if self.source.has_video and not self.workspace.thumbnails.exists():
            prepare.generate_thumbnails(
                source_path,
                self.workspace.thumbnails,
                threads=self.settings.resources.ffmpeg_threads,
                usage=self.usage,
            )

        self._finish_stage(stage)
        return self.workspace.audio

    def _source_is_ready(self) -> bool:
        """A source is downloadable/ready once its media file exists on disk."""
        return bool(self.source.path) and Path(self.source.path).is_file()

    def _download_source(self, stage: Stage) -> None:
        """Download a pending YouTube source with yt-dlp, then persist its metadata."""
        self._check_cancelled()
        self._emit(stage, 0.0, "Downloading video")

        def on_download_progress(fraction: float) -> None:
            self._emit(stage, min(0.9, fraction * 0.9), "Downloading video")

        log.info("Downloading pending source %s for job %s.", self.source.id, self.job.id)
        ingest.download_youtube(
            self.source,
            self.settings.ingest,
            on_progress=on_download_progress,
        )
        store.update_source(self.source)
        self._emit(stage, 0.9, "Download complete")

    def _stage_transcribe(self, audio: Path) -> Transcript:
        stage = Stage.TRANSCRIBE
        self._check_cancelled()

        if self.workspace.transcript.exists():
            log.info("Reusing existing transcript for job %s.", self.job.id)
            transcript = Transcript.load(self.workspace.transcript)
            self._finish_stage(stage)
            return transcript

        engine, notice = speech.resolve_engine(self.settings)
        if notice:
            self._set_notice(stage, notice)

        # External-first with automatic local fallback: a dead external
        # service slows a job down, it never kills it. Pinned engines
        # (transcription.engine != "auto") surface their own errors instead.
        pinned = self.settings.transcription.engine != "auto"
        self._emit(stage, 0.0, f"Transcribing with {engine.name}")
        try:
            transcript = engine.transcribe(
                audio,
                self.settings.transcription,
                language=self.settings.whisper.language,
                duration_s=self.source.duration_s,
                on_progress=self._stage_progress(stage),
                cancelled=self._is_cancelled,
            )
        except speech.SpeechCancelled as exc:
            # The job was cancelled, not broken. This is checked before the
            # fallback for a reason: falling back to another engine would
            # start a second transcription for a job the user asked to stop.
            raise JobCancelled("Transcription cancelled.") from exc
        except speech.SpeechError as exc:
            if pinned:
                raise
            fallback = LocalWhisperSTT()
            # A consent refusal is not a service failure, and saying "the
            # engine failed" would send the user looking in the wrong place.
            blocked = isinstance(exc, speech.SpeechConsentDenied)
            log.warning(
                "Transcription engine %s failed (%s); falling back to local.", engine.name, exc
            )
            if blocked:
                self._emit(stage, 0.0, "External transcription blocked — using local Whisper")
                self._set_notice(
                    stage,
                    "External transcription is blocked in Settings → External processing "
                    "— used local Whisper instead.",
                )
            else:
                self._emit(stage, 0.0, f"{engine.name} unavailable — using local Whisper")
                self._set_notice(
                    stage, f"{engine.name} transcription failed — used local Whisper instead."
                )
            transcript = fallback.transcribe(
                audio,
                self.settings.transcription,
                language=self.settings.whisper.language,
                duration_s=self.source.duration_s,
                on_progress=self._stage_progress(stage),
                cancelled=self._is_cancelled,
            )

        if (
            transcript.source == "whisper"
            and self.settings.whisper.diarization
            and not transcript.has_diarization
        ):
            from ..config import HF_TOKEN_KEY, get_secret

            self._emit(stage, 0.95, "Identifying speakers")
            transcribe.diarize(audio, transcript, hf_token=get_secret(HF_TOKEN_KEY, self.settings))

        transcript.save(self.workspace.transcript)
        store.upsert_transcript(
            TranscriptRow(
                job_id=self.job.id,
                json_path=str(self.workspace.transcript),
                language=transcript.language,
                model=transcript.model,
                has_diarization=transcript.has_diarization,
                word_count=len(transcript.words),
                source=transcript.source,
            )
        )

        # The shared speech timeline is built once here, from the transcript
        # and the prepared audio, and every later stage reads it. Two stages
        # asking "is someone speaking?" must get the same answer, so there is
        # one detector and one artifact.
        self._build_speech_timeline(audio, transcript)

        self._finish_stage(stage)
        return transcript

    def _build_speech_timeline(self, audio: Path, transcript: Transcript) -> None:
        """Measure when speech happens, once per job."""
        if self.workspace.speech_timeline.exists():
            return
        try:
            timeline = speech_timeline.build_timeline(audio, transcript)
        except Exception:  # noqa: BLE001 - a missing timeline must not fail a job
            log.warning("Could not build the speech timeline.", exc_info=True)
            return
        timeline.save(self.workspace.speech_timeline)
        log.info(
            "Speech timeline: %d interval(s) over %.1fs.",
            len(timeline.intervals),
            timeline.duration_s,
        )

    def _load_speech_timeline(self) -> speech_timeline.SpeechTimeline | None:
        """The shared speech timeline, when it was built."""
        if not self.workspace.speech_timeline.exists():
            return None
        try:
            return speech_timeline.SpeechTimeline.load(self.workspace.speech_timeline)
        except Exception:  # noqa: BLE001 - a broken artifact is not fatal
            log.warning("Could not read the speech timeline.", exc_info=True)
            return None

    def _load_or_detect_silences(self, audio: Path) -> list[Silence]:
        if self.workspace.silences.exists():
            raw = json.loads(self.workspace.silences.read_text(encoding="utf-8"))
            return [Silence(**item) for item in raw]

        silences = prepare.detect_silences(audio)
        self.workspace.silences.write_text(
            json.dumps([{"start": s.start, "end": s.end} for s in silences]),
            encoding="utf-8",
        )
        return silences

    async def _stage_highlights(
        self, transcript: Transcript, silences: list[Silence]
    ) -> list[Clip]:
        stage = Stage.HIGHLIGHTS
        self._check_cancelled()

        existing = store.list_clips(self.job.id)
        if existing:
            log.info("Reusing %d existing clips for job %s.", len(existing), self.job.id)
            self._finish_stage(stage)
            return existing

        provider_name = self.job.provider or self.settings.active_provider
        provider = build_provider(provider_name, self.settings)
        config = detection_config(self.settings)

        self._emit(stage, 0.0, f"Finding highlights with {provider.name}")
        max_calls = self.settings.resources.max_llm_calls_per_job
        try:
            clips = await highlights.detect(
                transcript,
                provider,
                config,
                job_id=self.job.id,
                silences=silences,
                on_progress=self._stage_progress(stage),
                usage=self.usage,
                max_calls=max_calls,
            )
        except highlights.HighlightError as exc:
            fallback = self._ollama_fallback(provider_name, exc)
            if fallback is None:
                raise
            provider, notice = fallback
            log.warning("Falling back to %s: %s", provider.name, notice)
            self._set_notice(stage, notice)
            self._emit(stage, 0.0, notice)
            clips = await highlights.detect(
                transcript,
                provider,
                config,
                job_id=self.job.id,
                silences=silences,
                on_progress=self._stage_progress(stage),
                usage=self.usage,
                max_calls=max_calls,
            )

        if self.usage.windows_skipped:
            # Never let a truncated analysis pass as a full one.
            self._set_notice(
                stage,
                f"Detection budget reached — {self.usage.windows_skipped} part(s) of this "
                "video were not analysed.",
            )

        store.replace_clips(self.job.id, clips)
        self._finish_stage(stage)
        return clips

    def _ollama_fallback(
        self, provider_name: str, error: BaseException
    ) -> tuple[LLMProvider, str] | None:
        """Return a local Ollama provider when the hosted provider is unusable.

        Triggers on credential failures *and* transient outages — rate limits,
        503s, timeouts. A transient failure used to kill the whole job; now it
        degrades to the local model the same way a rejected key does. Before
        switching, the fallback is health-checked so a dormant Ollama install
        doesn't trade a clear error for a vaguer one.
        """
        if provider_name == "ollama":
            return None
        if not (looks_like_auth_failure(error) or looks_like_transient_failure(error)):
            return None

        try:
            fallback = build_provider("ollama", self.settings)
        except Exception as exc:  # provider misconfigured or unreachable
            log.warning("Could not build the Ollama fallback: %s", exc)
            return None

        if not self._provider_healthy(fallback):
            log.info("Ollama fallback is not reachable; keeping the original error.")
            return None

        model = fallback.model or "local model"
        if looks_like_auth_failure(error):
            notice = (
                f"{provider_name.capitalize()} API key failed — switched to local "
                f"Ollama ({model}). Check the API key in Settings."
            )
        else:
            notice = (
                f"{provider_name.capitalize()} was rate-limited or unavailable — "
                f"switched to local Ollama ({model})."
            )
        return fallback, notice

    @staticmethod
    def _provider_healthy(provider: LLMProvider) -> bool:
        """Probe a provider once; a fallback that can't answer is not a fallback."""

        async def _check() -> bool:
            try:
                status = await provider.health_check()
            except Exception:
                return False
            return status.available

        try:
            return asyncio.run(_check())
        except Exception:  # pragma: no cover - defensive
            return False

    def _stage_reframe(self, clips: list[Clip], transcript: Transcript) -> dict[str, CropPath]:
        stage = Stage.REFRAME
        self._check_cancelled()
        source_path = Path(self.source.path)

        crop_paths: dict[str, CropPath] = {}

        if not self.source.has_video:
            # Audio-only sources render as captions on a solid background, so
            # there is nothing to reframe.
            self._finish_stage(stage)
            return crop_paths

        config = ReframeConfig(
            aspect_w=9 if self.settings.export.ratio == "9:16" else 1,
            aspect_h=16 if self.settings.export.ratio == "9:16" else 1,
        )
        if self.settings.export.ratio == "16:9":
            config = ReframeConfig(aspect_w=16, aspect_h=9)

        for index, clip in enumerate(clips):
            self._check_cancelled()
            self._emit(
                stage,
                index / len(clips),
                f"Reframing clip {index + 1}/{len(clips)}",
            )
            cached = self.workspace.crop_path(clip.id)
            if cached.exists():
                crop_paths[clip.id] = CropPath.load(cached)
            else:
                crop_paths[clip.id] = build_crop_path(
                    source_path,
                    start_s=clip.start_s,
                    end_s=clip.end_s,
                    transcript=transcript,
                    config=config,
                )
                crop_paths[clip.id].save(cached)

        self._finish_stage(stage)
        return crop_paths

    def _stage_captions(self, clips: list[Clip], transcript: Transcript) -> None:
        stage = Stage.CAPTIONS
        self._check_cancelled()
        # Caption files are written during export, where the output dimensions
        # are known. This stage validates the style so a typo fails fast rather
        # than after the reframe work is already done.
        captions.get_style(self.settings.export.caption_style)
        self._finish_stage(stage)

    def _stage_export(
        self,
        clips: list[Clip],
        transcript: Transcript,
        crop_paths: dict[str, CropPath],
    ) -> None:
        stage = Stage.EXPORT
        self._check_cancelled()

        style = captions.get_style(self.settings.export.caption_style)
        ratio = self.settings.export.ratio
        source_path = Path(self.source.path)
        destination_dir = paths.exports_dir() / self.job.id
        destination_dir.mkdir(parents=True, exist_ok=True)

        # The shared speech timeline, sliced per clip. The music ducking and
        # the webcam layout both read this, so they agree on when the
        # speaker is talking.
        timeline = self._load_speech_timeline()

        for index, clip in enumerate(clips):
            self._check_cancelled()

            crop_path = crop_paths.get(clip.id) or self._fallback_crop_path(clip, ratio)
            words = transcript.slice(clip.start_word, clip.end_word)
            destination = destination_dir / export.output_filename(
                clip.title or f"clip-{clip.rank}", ratio
            )

            request = export.ExportRequest(
                source=source_path,
                destination=destination,
                start_s=clip.start_s,
                end_s=clip.end_s,
                crop_path=crop_path,
                words=words,
                style=style,
                ratio=ratio,
                speech_intervals=(
                    timeline.slice(clip.start_s, clip.end_s) if timeline is not None else []
                ),
            )

            def clip_progress(fraction: float, i: int = index) -> None:
                self._emit(stage, (i + fraction) / len(clips), f"Exporting clip {i + 1}")

            export.export_clip(
                request,
                work_dir=self.workspace.captions_dir,
                settings=self.settings.export,
                on_progress=clip_progress,
                cancelled=self._is_cancelled,
                threads=self.settings.resources.ffmpeg_threads,
                usage=self.usage,
            )

            destination = self._maybe_narrate(destination, clip, index, len(clips), stage)

            # Phase 9: validate the render before it can be published. A failed
            # check marks the clip invalid and skips auto-publish; it never
            # substitutes a different file.
            report = validate.validate_media(
                destination,
                expected_duration_s=clip.duration_s,
                expected_size=export.ratio_dimensions(ratio),
                require_audio=self.source.has_audio,
            )
            bounds = validate.validate_bounds(
                start_s=clip.start_s,
                end_s=clip.end_s,
                start_word=clip.start_word,
                end_word=clip.end_word,
                transcript=transcript,
                min_duration_s=self.settings.clips.min_duration_s,
                max_duration_s=self.settings.clips.max_duration_s,
            )
            # The clip's own checks and the boundary checks, in one report.
            # The shape is the same as ValidationReport.to_dict(), with the
            # boundary checks appended.
            all_checks = [*report.checks, *bounds]
            combined: dict[str, Any] = {
                "ok": report.ok and all(c.ok for c in bounds),
                "checks": [{"name": c.name, "ok": c.ok, "detail": c.detail} for c in all_checks],
                "duration_s": report.duration_s,
                "width": report.width,
                "height": report.height,
            }
            store.update_clip(
                clip.id,
                status="exported" if combined["ok"] else "invalid",
                validation=combined,
            )
            if not combined["ok"]:
                failed = [c for c in all_checks if not c.ok]
                log.warning(
                    "Clip %s failed validation for job %s: %s",
                    clip.id,
                    self.job.id,
                    "; ".join(f"{c.name}: {c.detail}" for c in failed),
                )

            record = Export(
                id=new_id(),
                clip_id=clip.id,
                path=str(destination),
                ratio=ratio,
                style=style.key,
                size_bytes=destination.stat().st_size,
            )
            store.create_export(record)
            if combined["ok"]:
                _maybe_enqueue_upload(record.id, self.settings)

        self._finish_stage(stage)

    def _maybe_narrate(
        self, destination: Path, clip: Clip, index: int, total: int, stage: Stage
    ) -> Path:
        """Overlay an ElevenLabs voiceover on a finished export, when enabled.

        Narration is optional and must never fail an export: a TTS outage costs
        one clip's voiceover, not the job. The upload row was already created
        with the pre-narration file, so the narrated file replaces it in place.
        """
        if self.settings.transcription.voiceover != "muxed":
            return destination

        self._emit(stage, (index + 0.5) / total, f"Narrating clip {index + 1}")
        try:
            from ..speech import tts

            narration_text = (clip.hook or clip.title or "").strip()
            if not narration_text:
                return destination

            narration_path = destination.with_suffix(".narration.mp3")
            voice_id = self.settings.transcription.voice_id.strip() or tts.DEFAULT_VOICE_ID
            tts.synthesize_speech(narration_text, narration_path, voice_id=voice_id)
            final = destination.with_suffix(".narrated.mp4")
            tts.mux_voiceover(destination, narration_path, final)
            final.replace(destination)
            narration_path.unlink(missing_ok=True)
            log.info("Added voiceover to %s.", destination.name)
            return destination
        except Exception as exc:
            log.warning(
                "Voiceover failed for %s (%s); keeping the plain export.", destination.name, exc
            )
            return destination

    def _fallback_crop_path(self, clip: Clip, ratio: str) -> CropPath:
        """Centre crop for sources with no reframe data (audio-only, or a failure)."""
        from .reframe.croppath import centre_crop

        width, height = export.ratio_dimensions(ratio)
        info = ffmpeg.probe(Path(self.source.path))
        return centre_crop(
            info.width or width,
            info.height or height,
            clip.end_s - clip.start_s,
            aspect_w=9 if ratio == "9:16" else (1 if ratio == "1:1" else 16),
            aspect_h=16 if ratio == "9:16" else (1 if ratio == "1:1" else 9),
        )


async def run_job(
    job_id: str,
    *,
    settings: Settings | None = None,
    on_progress: ProgressHandler | None = None,
    is_cancelled: Callable[[], bool] | None = None,
) -> list[Clip]:
    """Load a job and run it to completion."""
    job = store.get_job(job_id)
    if job is None:
        raise PipelineError(f"Job {job_id} not found.", stage=Stage.PREPARE)

    source = store.get_source(job.source_id)
    if source is None:
        raise PipelineError(f"Source {job.source_id} not found.", stage=Stage.PREPARE)

    runner = PipelineRunner(
        job, source, settings=settings, on_progress=on_progress, is_cancelled=is_cancelled
    )
    # The pipeline is mostly blocking work (ffmpeg, Whisper, MediaPipe) with one
    # async stage. Running it in a worker thread keeps the web server's event
    # loop responsive while a job is going.
    return await asyncio.get_running_loop().run_in_executor(None, _run_sync, runner)


def _run_sync(runner: PipelineRunner) -> list[Clip]:
    return asyncio.run(runner.run())
