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
import contextlib
import json
import logging
from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from .. import paths, resources
from ..budget import budget_for
from ..config import Settings
from ..config import load as load_settings
from ..db import plan_store, store
from ..db.models import Clip, Export, Job, JobResources, Source, new_id, utcnow
from ..db.models import Transcript as TranscriptRow
from ..providers import LLMProvider, build_provider, detection_config
from ..providers.base import (
    ProviderConsentRequired,
    looks_like_auth_failure,
    looks_like_transient_failure,
)
from ..speech import LocalWhisperSTT
from ..speech import base as speech
from . import (
    Stage,
    captions,
    creative,
    diagnostics,
    export,
    ffmpeg,
    highlights,
    ingest,
    intent,
    music_selection,
    prepare,
    speech_timeline,
    transcribe,
    validate,
)
from . import (
    language as subtitle_language,
)
from .prepare import Silence
from .reframe import ReframeConfig, build_crop_path, layout_store, plan_fingerprint
from .reframe.croppath import CropPath
from .reframe.layout import (
    LayoutConfig,
    LayoutPath,
    LayoutVariant,
    ManualLayout,
    plan_layout,
)
from .reframe.scenes import Shot, detect_shots
from .reframe.webcam import (
    REPORT_VERSION,
    Rect,
    WebcamReport,
    WebcamTrack,
    detect_webcam,
)
from .transcript import Transcript

log = logging.getLogger(__name__)


def _honours_language(transcript: Transcript, target: str) -> bool:
    """True when the transcript's words are in the language that was asked for.

    "source" is always honoured: the words are in the language they were
    spoken in, whatever that turned out to be.
    """
    if target == subtitle_language.SOURCE_LANGUAGE:
        return True
    language = (transcript.language or "").strip().lower()
    return bool(language) and language == target


def _maybe_enqueue_upload(export_id: str, settings: Settings) -> None:
    """Queue YouTube uploads when automation is on. Never raises."""
    try:
        from ..youtube.queue import upload_queue
        from ..youtube.uploads import enqueue_export_all

        if enqueue_export_all(export_id, settings):
            upload_queue.notify()
    except Exception:  # an upload must never fail the pipeline
        log.exception("Could not queue a YouTube upload for export %s.", export_id)


def _maybe_enqueue_instagram(export_id: str, settings: Settings) -> None:
    """Queue an Instagram post when automation is on. Never raises.

    Separate from the YouTube call on purpose: the two platforms have
    their own queues, and one platform's problem must not affect the
    other's.
    """
    try:
        from ..instagram.queue import instagram_upload_queue
        from ..instagram.uploads import enqueue_export

        if enqueue_export(export_id, settings):
            instagram_upload_queue.notify()
    except Exception:  # an upload must never fail the pipeline
        log.exception("Could not queue an Instagram upload for export %s.", export_id)


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
    Stage.CREATIVE: 0.05,
    Stage.REFRAME: 0.20,
    Stage.CAPTIONS: 0.02,
    Stage.EXPORT: 0.18,
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


@dataclass
class ClipComposition:
    """How one clip is put together.

    The crop path says which part of the source the gameplay comes from.
    The layout says where the gameplay sits in the output and whether a
    webcam is drawn over it. They are planned together because the crop
    path's aspect ratio has to match the gameplay's slot.
    """

    crop_path: CropPath
    layout: LayoutPath | None = None


@dataclass
class CreativeResult:
    """What the creative stage decided.

    The plan is the model's structured answer, already checked. The music
    is one selection per clip — ``None`` where the clip has no bed.
    """

    plan: creative.CreativePlan
    music: dict[str, music_selection.MusicSelection | None] = field(default_factory=dict)


def _crop_aspect(layout: LayoutPath | None, ratio: str) -> tuple[int, int]:
    """The aspect ratio the crop path should be built for.

    A stacked layout leaves the bottom of the frame for gameplay, and that
    area is not the full 9:16. The crop path has to match it, or the
    gameplay would be stretched when it was scaled into the slot.
    """
    base = {
        "9:16": (9, 16),
        "1:1": (1, 1),
        "16:9": (16, 9),
    }.get(ratio, (9, 16))

    if layout is None:
        return base

    slot = layout.segments[0].gameplay_slot if layout.segments else None
    if slot is None or slot.width <= 0 or slot.height <= 0:
        return base

    # Reduce the slot's aspect to the smallest whole-number ratio that
    # describes it. A 1080x1152 slot is 15:16, not 0.9375:1.
    from math import gcd

    divisor = gcd(slot.width, slot.height)
    width = slot.width // divisor
    height = slot.height // divisor
    if width <= 0 or height <= 0 or width > 64 or height > 64:
        return base
    return (width, height)


def _webcam_region(layout: LayoutPath | None) -> Rect | None:
    """The webcam's own region, when the layout has one.

    The gameplay crop is kept clear of it: a webcam that is shown twice —
    once in the strip above the gameplay and once inside the gameplay — is
    the most obvious fault a split-screen layout can have.
    """
    if layout is None:
        return None
    for segment in layout.segments:
        if segment.webcam_region is not None:
            return segment.webcam_region
    return None


def _source_size(report: WebcamReport) -> tuple[int, int]:
    """The frame size the report was made against."""
    return (report.source_width, report.source_height)


def _same_windows(
    saved: list[tuple[float, float]] | None,
    wanted: list[tuple[float, float]] | None,
) -> bool:
    """True when a saved report was made about the stretches that are wanted.

    The report is written to disk with its times rounded to three decimal
    places, while a clip's own times are whatever the detector measured —
    ``1303.9599999999998`` and ``1303.96`` are the same moment. Comparing
    the two exactly would throw the report away for a rounding difference
    and make every retry pay for the detection again, so the comparison is
    made to a hundredth of a second. A stretch that is *really* different
    differs by far more than that.
    """
    if not saved or not wanted:
        return True
    if len(saved) != len(wanted):
        return False
    return all(
        abs(a[0] - b[0]) <= 0.01 and abs(a[1] - b[1]) <= 0.01
        for a, b in zip(saved, wanted, strict=True)
    )


def _load_crop_path(cached: Path, fingerprint: str) -> CropPath | None:
    """The saved plan for a clip, when it was built for the same settings.

    ``None`` means there is nothing usable saved: either there is no plan,
    or the plan was built for a different aspect ratio, or for a different
    webcam region, and a plan for one of those is a different plan.
    """
    if not cached.exists():
        return None
    try:
        path = CropPath.load(cached)
    except Exception:  # noqa: BLE001 - a broken artifact is built again
        log.warning("Could not read the saved crop plan %s; building it again.", cached.name)
        return None
    if path.config_fingerprint != fingerprint:
        log.info(
            "The saved crop plan %s was built for different settings; building it again.",
            cached.name,
        )
        return None
    return path


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

    def layout(self, clip_id: str) -> Path:
        return self.root / "layouts" / f"{clip_id}.json"

    @property
    def shots(self) -> Path:
        """The shot list for the source video.

        Detected once for the whole source, the same way the webcam
        detector does it: a shot boundary is a property of the video, not
        of a clip.
        """
        return self.root / "shots.json"

    @property
    def webcam_report(self) -> Path:
        """The webcam detection report for this source video.

        Detection runs once for the whole source, because a webcam overlay
        is in the same place in every shot. Slicing that one track per clip
        is faster than detecting again, and steadier.
        """
        return self.root / "webcam_report.json"

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
            creative_result = await self._stage_creative(clips)
            crop_paths = self._stage_reframe(clips, transcript, creative_result)
            self._stage_captions(clips, transcript)
            self._stage_export(clips, transcript, crop_paths, creative_result)
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

        target = subtitle_language.normalise_target(self.settings.export.subtitle_language)

        if self.workspace.transcript.exists():
            transcript = Transcript.load(self.workspace.transcript)
            if _honours_language(transcript, target):
                log.info("Reusing existing transcript for job %s.", self.job.id)
                self._finish_stage(stage)
                return transcript
            # The saved transcript is in another language — the user changed
            # the subtitle language after it was made. Keeping it would serve
            # captions in the language they no longer asked for.
            log.info(
                "The saved transcript for job %s is in %r, not %r; transcribing again.",
                self.job.id,
                transcript.language,
                target,
            )

        engine, notice = speech.resolve_engine(self.settings)
        if notice:
            self._set_notice(stage, notice)

        # External-first with automatic local fallback: a dead external
        # service slows a job down, it never kills it. Pinned engines
        # (transcription.engine != "auto") surface their own errors instead.
        pinned = self.settings.transcription.engine != "auto"
        # Whether the engine that produced the transcript is the local one.
        # The local recogniser is the only one that can translate, so this is
        # what decides whether a language mismatch can still be fixed.
        local_engine = engine.name == "whisper"
        self._emit(stage, 0.0, f"Transcribing with {engine.name}")
        try:
            transcript = engine.transcribe(
                audio,
                self.settings.transcription,
                language=self.settings.whisper.language,
                duration_s=self.source.duration_s,
                on_progress=self._stage_progress(stage),
                cancelled=self._is_cancelled,
                subtitle_language=target,
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
                subtitle_language=target,
            )
            local_engine = True

        if not _honours_language(transcript, target):
            # The engine transcribed the speech but did not write the
            # captions in the language that was asked for. Only the local
            # recogniser can translate, so it does the work — and if it is
            # already the engine that ran, there is nothing left to try and
            # the transcript stands as it is, with the mismatch recorded.
            if local_engine:
                log.warning(
                    "The transcript is in %r, not the requested %r.", transcript.language, target
                )
            else:
                if pinned:
                    raise speech.SpeechError(
                        f"The captions are in {transcript.language or 'an unknown language'}, "
                        f"not {target}. The external engine transcribes but does not "
                        "translate — set the subtitle language to the spoken language, or "
                        "use the local engine in Settings → Transcription."
                    )
                log.info(
                    "The external engine produced %r, not the requested %r; "
                    "re-transcribing locally so the captions can be written in %r.",
                    transcript.language,
                    target,
                    target,
                )
                self._emit(stage, 0.0, "Translating the captions with local Whisper")
                transcript = LocalWhisperSTT().transcribe(
                    audio,
                    self.settings.transcription,
                    language=self.settings.whisper.language,
                    duration_s=self.source.duration_s,
                    on_progress=self._stage_progress(stage),
                    cancelled=self._is_cancelled,
                    subtitle_language=target,
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

        clips = self._apply_story_balance(clips)

        store.replace_clips(self.job.id, clips)
        self._finish_stage(stage)
        return clips

    def _apply_story_balance(self, clips: list[Clip]) -> list[Clip]:
        """Tilt the ranking towards the story or the action, as configured.

        The tilt is measured, not guessed: story is the speech density
        from the shared timeline, action is the rate of scene changes
        from the shot list. The model's own score is kept — it judges
        the hook and the payoff, which no signal can — and the tilt is
        a small, bounded adjustment on top of it.

        With the default setting the adjustment is exactly zero, so
        nothing changes for a user who never touches it.
        """
        settings = self.settings.clips
        if settings.highlight_style == "auto" and abs(settings.story_density - 0.5) < 1e-9:
            return clips

        timeline = self._load_speech_timeline()
        shots = self._load_or_detect_shots()
        cut_counts: dict[str, int] = {}
        for clip in clips:
            cut_counts[clip.id] = sum(
                1 for shot in shots if clip.start_s < shot.start_s < clip.end_s
            )

        for clip in clips:
            duration = max(0.001, clip.end_s - clip.start_s)
            speech = music_selection.speech_density(timeline, clip.start_s, clip.end_s)
            cuts_per_minute = cut_counts.get(clip.id, 0) / duration * 60.0

            adjusted, character = intent.adjust_score(
                clip.score,
                speech_density=speech,
                cuts_per_minute=cuts_per_minute,
                story_density=settings.story_density,
                highlight_style=settings.highlight_style,
            )
            if adjusted != clip.score:
                log.info(
                    "Clip %s: score %d -> %d (story %.2f, action %.2f).",
                    clip.id,
                    clip.score,
                    adjusted,
                    character.story,
                    character.action,
                )
                clip.score = adjusted

        # The balance changes the order the clips are in, so they are
        # re-ranked and the clip count is re-applied.
        clips.sort(key=lambda c: c.score, reverse=True)
        clips = clips[: settings.max_clips]
        for rank, clip in enumerate(clips, start=1):
            clip.rank = rank
        return clips

    async def _stage_creative(self, clips: list[Clip]) -> CreativeResult:
        """Decide the creative plan and the music for each clip.

        Two things happen here, and both are bounded by the job's AI budget:

        * **One planning call** (and one repair retry) produce a structured
          plan — a layout, a crop, a caption strategy, a music track and a
          ducking depth for every clip. Everything in it is checked before
          it is used; anything that does not check out is rejected, and the
          deterministic plan is used instead.
        * **One music call per clip**, at most, and only for the clips that
          do not already have the user's own choice.

        The budget is loaded from the database, so a retried job does not
        get a fresh allowance.
        """
        stage = Stage.CREATIVE
        self._check_cancelled()

        budget = budget_for(self.job.id, max_clips=self.settings.clips.max_clips)

        provider: LLMProvider | None = None
        provider_name = self.job.provider or self.settings.active_provider
        try:
            provider = build_provider(provider_name, self.settings)
        except Exception as exc:  # noqa: BLE001 - no provider means the fallback
            log.warning("No provider is available for the creative plan: %s", exc)
            provider = None

        timeline = self._load_speech_timeline()
        scene_changes = self._scene_changes(clips)

        self._emit(stage, 0.05, "Planning the edit")
        try:
            plan = await creative.plan_creative(
                provider,
                budget,
                clips=clips,
                tracks=self._music_candidates(),
                detected_layout=self._detected_layout_name(),
                layout_confidence=self._detected_layout_confidence(),
                speech_density={
                    clip.id: music_selection.speech_density(timeline, clip.start_s, clip.end_s)
                    for clip in clips
                },
                scene_changes=scene_changes,
                default_ratio=self.settings.export.ratio,
            )
        except ProviderConsentRequired:
            # The user withdrew consent for AI creative planning. That is an
            # answer, not a failure: the deterministic plan is used and the
            # clips are still exported. No other provider is tried.
            log.info(
                "The AI creative planning was refused by the privacy settings; "
                "the automatic choices were made instead."
            )
            plan = creative.fallback_plan(
                clips,
                default_ratio=self.settings.export.ratio,
                reason="AI creative planning is switched off in the privacy settings",
            )

        self._emit(stage, 0.4, "Choosing the music")
        selections = await music_selection.select_for_clips(
            clips,
            provider=provider,
            budget=budget,
            timeline=timeline,
            scene_changes=scene_changes,
            source_id=self.source.id,
        )

        for clip in clips:
            selection = selections.get(clip.id)
            store.update_clip(
                clip.id,
                music_track_id=selection.track_id if selection else "",
                music_source=selection.source if selection else "",
                music_reason=selection.reason if selection else "",
            )

        try:
            plan_store.save(self.job.id, plan)
        except Exception:  # noqa: BLE001 - a plan that cannot be saved is not fatal
            log.warning("Could not save the creative plan.", exc_info=True)

        try:
            budget.save()
        except Exception:  # noqa: BLE001
            log.warning("Could not save the AI budget.", exc_info=True)

        if plan.source == "fallback" and plan.problems:
            self._set_notice(
                stage,
                "The AI plan could not be used, so the automatic choices were made instead.",
            )

        self._finish_stage(stage)
        return CreativeResult(plan=plan, music=selections)

    def _music_candidates(self) -> list[dict[str, Any]]:
        """The tracks the model may choose from, as measurements.

        Only the tracks that may legally be exported are offered, and only
        their metadata goes out — never the audio, never a file path.
        """
        from ..music import selection as music_selection_module

        candidates: list[dict[str, Any]] = []
        for track in music_selection_module.store.list_tracks():
            if track.excluded:
                continue
            candidates.append(
                {
                    "id": track.id,
                    "name": track.name,
                    "title": track.title,
                    "artist": track.artist,
                    "tags": track.tag_list,
                    "duration_s": round(track.analysis.duration_s or track.duration_s, 2),
                    "bpm": track.analysis.bpm,
                    "bpm_confidence": track.analysis.bpm_confidence,
                    "energy": track.analysis.energy,
                    "mood": track.analysis.mood,
                    "beat_regularity": track.analysis.beat_regularity,
                    "groove_strength": track.analysis.groove_strength,
                    "loudness_lufs": track.analysis.loudness_lufs,
                }
            )
        return candidates

    def _detected_layout_name(self) -> str:
        """The layout the detector found, or an empty string."""
        stored = layout_store.get_source_layout(self.source.id)
        if stored is None or not stored.has_detection:
            return ""
        return "auto"

    def _detected_layout_confidence(self) -> float:
        """How sure the detector was about the region."""
        stored = layout_store.get_source_layout(self.source.id)
        if stored is None:
            return 0.0
        return stored.detected_confidence

    def _scene_changes(self, clips: list[Clip]) -> dict[str, int]:
        """How many scene changes each clip contains.

        Counted from the shot list, which is detected once for the whole
        source — a shot boundary is a property of the video, not of a
        clip. The number is measured, not guessed.
        """
        shots = self._load_or_detect_shots()
        counts: dict[str, int] = {}
        for clip in clips:
            if not shots:
                counts[clip.id] = 0
                continue
            boundaries = [
                shot.start_s for shot in shots if clip.start_s < shot.start_s < clip.end_s
            ]
            counts[clip.id] = len(boundaries)
        return counts

    def _load_or_detect_shots(self) -> list[Shot]:
        """The source's shot list, detected once and cached."""
        cached = self.workspace.shots
        if cached.exists():
            try:
                raw = json.loads(cached.read_text(encoding="utf-8"))
                return [Shot(float(item["start_s"]), float(item["end_s"])) for item in raw]
            except Exception:  # noqa: BLE001 - a broken artifact is re-detected
                log.warning("Could not read the shot list; detecting it again.", exc_info=True)

        if not self.source.has_video:
            return []

        try:
            shots = detect_shots(Path(self.source.path))
        except Exception:  # noqa: BLE001 - detection must not fail a job
            log.warning("Could not detect the shots.", exc_info=True)
            return []

        cached.parent.mkdir(parents=True, exist_ok=True)
        cached.write_text(
            json.dumps([{"start_s": shot.start_s, "end_s": shot.end_s} for shot in shots]),
            encoding="utf-8",
        )
        return shots

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

    def _stage_reframe(
        self,
        clips: list[Clip],
        transcript: Transcript,
        creative_result: CreativeResult | None = None,
    ) -> dict[str, ClipComposition]:
        stage = Stage.REFRAME
        self._check_cancelled()
        source_path = Path(self.source.path)

        compositions: dict[str, ClipComposition] = {}

        if not self.source.has_video:
            # Audio-only sources render as captions on a solid background, so
            # there is nothing to reframe.
            self._finish_stage(stage)
            return compositions

        ratio = self.settings.export.ratio
        out_w, out_h = export.ratio_dimensions(ratio)
        timeline = self._load_speech_timeline()

        # The webcam is detected once for the whole source. A webcam overlay
        # is persistent — it is in the same place in every shot — so one
        # detection sliced per clip is both faster and steadier than
        # detecting again for every clip.
        #
        # The detector only walks the stretches the clips actually use. A
        # source that is half an hour long and a set of clips that use five
        # minutes of it do not need the other twenty-five minutes looked at:
        # the webcam is the same wherever it is found, and the boxes are
        # measured where the clips are.
        # The windows are in the source's own order, not the clips' rank
        # order: the detector walks the source forwards, and a decoder
        # cannot seek backwards.
        windows = sorted((clip.start_s, clip.end_s) for clip in clips)
        report = self._detect_webcam(source_path, windows=windows)

        for index, clip in enumerate(clips):
            self._check_cancelled()
            self._emit(
                stage,
                index / len(clips),
                f"Reframing clip {index + 1}/{len(clips)}",
            )

            layout = self._plan_layout(
                report,
                clip,
                timeline,
                out_w=out_w,
                out_h=out_h,
                creative_result=creative_result,
            )

            # The gameplay area decides the crop path's aspect ratio: a
            # stacked layout leaves the bottom sixty per cent for gameplay,
            # and the crop has to match that or the two would not line up.
            aspect_w, aspect_h = _crop_aspect(layout, ratio)
            config = ReframeConfig(
                aspect_w=aspect_w, aspect_h=aspect_h, avoid=_webcam_region(layout)
            )

            # A saved plan is only reused when it was built for the same
            # settings. The webcam's region changes the aspect the gameplay
            # is cropped to, and a plan made for the old aspect would be
            # the wrong shape for the new slot.
            fingerprint = plan_fingerprint(config)
            cached = self.workspace.crop_path(clip.id)
            crop_path = _load_crop_path(cached, fingerprint)
            if crop_path is None:
                crop_path = build_crop_path(
                    source_path,
                    start_s=clip.start_s,
                    end_s=clip.end_s,
                    transcript=transcript,
                    config=config,
                )
                crop_path.save(cached)

            compositions[clip.id] = ClipComposition(crop_path=crop_path, layout=layout)

        self._finish_stage(stage)
        return compositions

    def _detect_webcam(
        self, source_path: Path, *, windows: list[tuple[float, float]] | None = None
    ) -> WebcamReport:
        """Find the webcam region in the source, once.

        The result is cached in the job's workspace so a retry does not pay
        for detection again, and so the run record keeps the reasoning: the
        sampling rate, the confidence, and why the region was or was not
        used.
        """
        cached = self.workspace.webcam_report
        if cached.exists():
            report = WebcamReport.load(cached)
            # A report made for a different set of windows says nothing about
            # this one, so it is only reused when the windows match.
            #
            # A report that says the detection *failed* is not an answer
            # either: the detector could not look, which is not the same as
            # there being no webcam. That one is tried again — and so is a
            # report written by another version of the detector, which
            # cannot say whether it failed.
            if (
                report.version == REPORT_VERSION
                and not report.failed
                and (report.track is not None or report.unavailable_reason)
                and _same_windows(report.windows, windows)
            ):
                return report

        info = ffmpeg.probe(source_path)
        if not info.has_video or not info.width or not info.height:
            report = WebcamReport(unavailable_reason="the source has no video stream")
        else:
            report = detect_webcam(
                source_path,
                width=info.width,
                height=info.height,
                windows=windows,
            )
            report.windows = list(windows or [])
            report.save(cached)

        if report.track is not None:
            log.info(
                "Webcam found in %s at %s with %.0f%% confidence (%s).",
                source_path.name,
                report.track.rect.to_dict(),
                report.track.confidence * 100,
                report.sampling_reason,
            )
            try:
                layout_store.record_detection(
                    self.source.id,
                    rect=report.track.rect.to_dict(),
                    confidence=report.track.confidence,
                    face_width=report.track.face_width,
                    reason=report.track.reason or report.sampling_reason,
                )
            except Exception as exc:  # noqa: BLE001 - a record is not worth failing a render for
                log.warning("Could not record the webcam detection: %s", exc)
        else:
            log.info(
                "No webcam found in %s (%s); the clips will be gameplay only.",
                source_path.name,
                report.unavailable_reason or "no candidate was confident enough",
            )
        return report

    def _recommended_layout(
        self, clip: Clip, creative_result: CreativeResult | None
    ) -> LayoutVariant | None:
        """The layout the creative plan recommended for a clip.

        The recommendation is honoured only when it is one AutoClip knows
        how to build, and only when the user has not already made a
        choice — a manual choice is the user's, and it wins.
        """
        if creative_result is None:
            return None
        direction = creative_result.plan.direction_for(clip.id)
        if direction is None:
            return None
        if direction.layout in ("", "auto"):
            return None
        try:
            return LayoutVariant(direction.layout)
        except ValueError:
            return None

    def _plan_layout(
        self,
        report: WebcamReport,
        clip: Clip,
        timeline: speech_timeline.SpeechTimeline | None,
        *,
        out_w: int,
        out_h: int,
        creative_result: CreativeResult | None = None,
    ) -> LayoutPath | None:
        """Plan the composition for one clip.

        The order is the same as the planner's own: what the user asked for
        first, then what the creative plan recommended, then what was
        detected, then the geometry. A manual choice for this source beats
        every automatic decision.
        """
        settings = self.settings.export
        if settings.layout == "gameplay_only":
            # The user turned the webcam off. Nothing to plan.
            return None

        track: WebcamTrack | None = report.track
        if track is not None:
            track = track.slice(clip.start_s, clip.end_s)

        manual = self._manual_layout(track)
        if manual is None:
            recommended = self._recommended_layout(clip, creative_result)
            if recommended is not None:
                if track is None:
                    return None
                manual = ManualLayout(
                    variant=recommended,
                    rect=track.rect,
                    position=settings.webcam_position,
                )

        if manual is None and settings.layout in ("above", "corner"):
            # The user chose a layout in the settings rather than for this
            # source. It still needs a region to show.
            if track is None:
                return None
            variant = LayoutVariant.ABOVE if settings.layout == "above" else LayoutVariant.CORNER
            manual = ManualLayout(
                variant=variant,
                rect=track.rect,
                position=settings.webcam_position,
            )

        if track is None and manual is None:
            return None

        source_width, source_height = _source_size(report)
        if source_width <= 0 or source_height <= 0:
            return None

        # The speech intervals come from the shared timeline, so the webcam
        # emphasis and the music ducking agree about when somebody is
        # talking. There is no second detector here.
        spans: list[tuple[float, float]] = []
        if timeline is not None:
            for interval in timeline.relative_slice(clip.start_s, clip.end_s):
                spans.append((interval.start_ms / 1000.0, interval.end_ms / 1000.0))

        config = LayoutConfig(
            output_width=out_w,
            output_height=out_h,
            webcam_height_frac=settings.webcam_height_frac,
            corner_width_frac=settings.webcam_corner_frac,
        )

        path = plan_layout(
            source_width=source_width,
            source_height=source_height,
            config=config,
            webcam=track,
            manual=manual,
            speech_spans=spans,
            duration_s=clip.end_s - clip.start_s,
        )
        path_file = self.workspace.layout(clip.id)
        path_file.parent.mkdir(parents=True, exist_ok=True)
        path_file.write_text(json.dumps(path.to_dict(), indent=2), encoding="utf-8")
        return path

    def _manual_layout(self, track: WebcamTrack | None) -> ManualLayout | None:
        """The user's own choice for this source, if there is one."""
        override = layout_store.get_source_layout(self.source.id)
        if override is None or not override.has_override:
            return None

        try:
            variant = LayoutVariant(override.variant)
        except ValueError:
            return None

        rect = None
        if override.rect_width > 0 and override.rect_height > 0:
            rect = Rect(
                x=override.rect_x,
                y=override.rect_y,
                width=override.rect_width,
                height=override.rect_height,
            )
        elif track is not None:
            rect = track.rect

        return ManualLayout(
            variant=variant,
            rect=rect,
            scale=override.scale or None,
            position=override.position or "top-right",
        )

    def _export_settings_for(
        self,
        clip: Clip,
        export_settings: Any,
        creative_result: CreativeResult | None,
    ) -> Any:
        """The export settings for one clip, including its music.

        The music track comes from the creative stage's selection — which
        is the user's own choice, the model's proposal, or the
        deterministic scorer's answer. The user's global setting is still
        the fallback, so an existing install that configured a bed keeps
        it.
        """
        track_setting = export_settings.music_track
        selection = creative_result.music.get(clip.id) if creative_result is not None else None

        if selection is not None:
            from ..music import store as music_store

            track = music_store.get_track(selection.track_id)
            if track is not None:
                track_setting = track.path or track.name
            else:
                # The track was removed from the library between the
                # selection and the export. The global setting is a better
                # answer than a path that no longer exists.
                log.warning("The track chosen for clip %s is no longer in the library.", clip.id)
        elif selection is None and creative_result is not None and clip.id in creative_result.music:
            # The selection is explicitly "no music for this clip".
            return export_settings.model_copy(update={"music_track": ""})

        return export_settings.model_copy(update={"music_track": track_setting})

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
        compositions: dict[str, ClipComposition],
        creative_result: CreativeResult | None = None,
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

        # Two clips of one job can carry the same title — the model chose
        # it — and the exports share one directory. The names are made
        # unique against the whole set, so no export overwrites another.
        titles = [clip.title or f"clip-{clip.rank}" for clip in clips]

        for index, clip in enumerate(clips):
            self._check_cancelled()

            composition = compositions.get(clip.id)
            crop_path = (
                composition.crop_path if composition else self._fallback_crop_path(clip, ratio)
            )
            words = transcript.slice(clip.start_word, clip.end_word)
            destination = destination_dir / export.unique_output_filename(
                clip.title or f"clip-{clip.rank}",
                ratio,
                rank=clip.rank,
                sibling_titles=titles,
            )

            # The export settings for this clip. The creative plan may
            # recommend a caption style and a ducking depth; the rest comes
            # from the user's settings.
            export_settings = self.settings.export
            clip_style = style
            direction = (
                creative_result.plan.direction_for(clip.id) if creative_result is not None else None
            )
            if direction is not None:
                if direction.caption_strategy:
                    # An unknown style keeps the default rather than
                    # failing the export: the plan was already checked, so
                    # this is belt and braces.
                    with contextlib.suppress(Exception):
                        clip_style = captions.get_style(direction.caption_strategy)
                if direction.ducking_db:
                    export_settings = export_settings.model_copy(
                        update={"ducking_amount_db": direction.ducking_db}
                    )

            request = export.ExportRequest(
                source=source_path,
                destination=destination,
                start_s=clip.start_s,
                end_s=clip.end_s,
                crop_path=crop_path,
                words=words,
                style=clip_style,
                ratio=ratio,
                speech_intervals=speech_timeline.ducking_intervals(
                    timeline, clip.start_s, clip.end_s
                ),
                layout=composition.layout if composition else None,
            )

            def clip_progress(fraction: float, i: int = index) -> None:
                self._emit(stage, (i + fraction) / len(clips), f"Exporting clip {i + 1}")

            export.export_clip(
                request,
                work_dir=self.workspace.captions_dir,
                settings=self._export_settings_for(clip, export_settings, creative_result),
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

            # The objective quality measurements. These are kept apart
            # from the validation report on purpose: validation is the
            # pass/fail gate before publishing, and the diagnostics are
            # the evidence a person reads to decide what to change.
            self._record_diagnostics(
                clip,
                destination,
                words=words,
                compositions=compositions,
                ratio=ratio,
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
                _maybe_enqueue_instagram(record.id, self.settings)

        self._finish_stage(stage)

    def _record_diagnostics(
        self,
        clip: Clip,
        destination: Path,
        *,
        words: list[Any],
        compositions: dict[str, ClipComposition],
        ratio: str,
    ) -> None:
        """Measure the finished clip and keep the measurements.

        Nothing here can fail an export: a measurement that cannot be
        made is reported as unavailable and the rest are still made. The
        report holds measurements, not a score — there is no honest way
        to fold ten different measurements into one number, and a number
        that looked like a verdict would be a lie.
        """
        composition = compositions.get(clip.id)
        crop_path = composition.crop_path if composition else None

        try:
            report = diagnostics.diagnose_clip(
                destination,
                clip_id=clip.id,
                clips=store.list_clips(self.job.id),
                words=words,
                start_s=clip.start_s,
                end_s=clip.end_s,
                expected_size=export.ratio_dimensions(ratio),
                source_size=(
                    (self.source.width, self.source.height)
                    if self.source.width and self.source.height
                    else None
                ),
                crop_path=crop_path,
                require_audio=self.source.has_audio,
                duration_tolerance_s=validate.DURATION_TOLERANCE_S,
                caption_style=self.settings.export.caption_style,
            )
        except Exception:  # noqa: BLE001 - diagnostics never fail an export
            log.warning("Could not measure clip %s.", clip.id, exc_info=True)
            return

        store.update_clip(clip.id, diagnostics=report.to_dict())

        failures = report.failures()
        if failures:
            log.info(
                "Clip %s: %d diagnostic(s) to look at — %s",
                clip.id,
                len(failures),
                "; ".join(f"{d.title}: {d.detail}" for d in failures),
            )

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
