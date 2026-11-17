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

from .. import paths
from ..config import Settings
from ..config import load as load_settings
from ..db import store
from ..db.models import Clip, Export, Job, Source, new_id, utcnow
from ..db.models import Transcript as TranscriptRow
from ..providers import LLMProvider, build_provider, detection_config
from ..providers.base import looks_like_auth_failure
from . import Stage, captions, export, ffmpeg, highlights, ingest, prepare, transcribe
from .prepare import Silence
from .reframe import ReframeConfig, build_crop_path
from .reframe.croppath import CropPath
from .transcript import Transcript

log = logging.getLogger(__name__)


def _maybe_enqueue_upload(export_id: str, settings: Settings) -> None:
    """Queue a YouTube upload when automation is on. Never raises."""
    try:
        from ..youtube.queue import upload_queue
        from ..youtube.uploads import enqueue_export

        if enqueue_export(export_id, settings) is not None:
            upload_queue.notify()
    except Exception:  # an upload must never fail the pipeline
        log.exception("Could not queue a YouTube upload for export %s.", export_id)


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
            raise
        except Exception as exc:
            log.exception("Job %s failed.", self.job.id)
            store.update_job(self.job.id, status="failed", error=str(exc), finished_at=utcnow())
            raise

        store.update_job(self.job.id, status="done", progress=1.0, finished_at=utcnow())
        return clips

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
            )

        if self.source.has_video and not self.workspace.thumbnails.exists():
            prepare.generate_thumbnails(source_path, self.workspace.thumbnails)

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

        self._emit(stage, 0.0, "Transcribing")
        transcript = transcribe.transcribe(
            audio,
            self.settings.whisper,
            duration_s=self.source.duration_s,
            on_progress=self._stage_progress(stage),
            cancelled=self._is_cancelled,
        )

        if self.settings.whisper.diarization:
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

        self._finish_stage(stage)
        return transcript

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
        try:
            clips = await highlights.detect(
                transcript,
                provider,
                config,
                job_id=self.job.id,
                silences=silences,
                on_progress=self._stage_progress(stage),
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
            )

        store.replace_clips(self.job.id, clips)
        self._finish_stage(stage)
        return clips

    def _ollama_fallback(
        self, provider_name: str, error: BaseException
    ) -> tuple[LLMProvider, str] | None:
        """Return a local Ollama provider when a hosted API key was rejected.

        Only credential failures trigger a switch: a rate limit or an outage
        should surface as itself rather than silently changing the model and
        producing worse clips.
        """
        if provider_name == "ollama" or not looks_like_auth_failure(error):
            return None

        try:
            fallback = build_provider("ollama", self.settings)
        except Exception as exc:  # provider misconfigured or unreachable
            log.warning("Could not build the Ollama fallback: %s", exc)
            return None

        model = fallback.model or "local model"
        notice = (
            f"{provider_name.capitalize()} API key failed — switched to local "
            f"Ollama ({model}). Check the API key in Settings."
        )
        return fallback, notice

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
            )

            def clip_progress(fraction: float, i: int = index) -> None:
                self._emit(stage, (i + fraction) / len(clips), f"Exporting clip {i + 1}")

            export.export_clip(
                request,
                work_dir=self.workspace.captions_dir,
                settings=self.settings.export,
                on_progress=clip_progress,
                cancelled=self._is_cancelled,
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
            store.update_clip(clip.id, status="exported")
            _maybe_enqueue_upload(record.id, self.settings)

        self._finish_stage(stage)

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
