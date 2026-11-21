"""Clip review, editing, preview media, and export."""

from __future__ import annotations

import asyncio
import logging
from pathlib import Path

from fastapi import APIRouter, HTTPException, Query
from fastapi.responses import FileResponse

from .. import paths
from ..config import load as load_settings
from ..db import store
from ..db.models import Export, new_id
from ..music.licensing import LicenseBlocked
from ..pipeline import captions as captions_module
from ..pipeline import diagnostics
from ..pipeline import export as export_module
from ..pipeline import speech_timeline as speech_timeline_module
from ..pipeline import validate as validate_module
from ..pipeline.reframe.croppath import CropPath, centre_crop
from ..pipeline.runner import JobWorkspace
from ..pipeline.transcript import Transcript, Word
from .schemas import (
    CaptionPatchIn,
    CaptionStyleOut,
    ClipOut,
    ClipPatchIn,
    ExportOut,
    ExportRequestIn,
    LibraryClipOut,
    WordOut,
)

log = logging.getLogger(__name__)

router = APIRouter(prefix="/api", tags=["clips"])


def _clip_out(clip) -> ClipOut:
    edit = store.get_clip_edit(clip.id)
    exports = store.list_exports(clip.id)
    uploads: dict[str, list] = {}
    for upload in store.list_uploads_for_clip(clip.id):
        uploads.setdefault(upload.export_id, []).append(upload)
    # Instagram runs on its own queue, so its rows are collected separately:
    # an Instagram post never appears in a YouTube upload list.
    instagram_uploads: dict[str, list] = {}
    for row in store.list_instagram_uploads_for_clip(clip.id):
        instagram_uploads.setdefault(row.export_id, []).append(row)
    # Where the clip would go, and why. The routing layer reads the
    # clip's classification and the user's rules, so it is asked here
    # rather than being carried around in the clip row.
    routing = None
    try:
        from ..routing import decision as decision_module

        routing = decision_module.decide(clip.id)
    except Exception:  # noqa: BLE001
        # A routing lookup must never stop a clip from being listed.
        log.debug("Could not work out the routing for clip %s.", clip.id, exc_info=True)
    return ClipOut.of(
        clip,
        edit=edit,
        exports=exports,
        uploads=uploads,
        instagram_uploads=instagram_uploads,
        routing=routing,
    )


def _notify_export(clip, *, ok: bool, failures: list[str]) -> None:
    """Record the export outcome in the notification centre. Never raises."""
    try:
        from ..notifications import events

        events.clip_exported(
            clip.id,
            clip.title or f"Clip {clip.rank}",
            ok=ok,
            failures=failures,
        )
    except Exception:  # noqa: BLE001
        log.debug("Could not record the export notification.", exc_info=True)


async def list_clips_for_job(job_id: str) -> list[ClipOut]:
    job = await asyncio.to_thread(store.get_job, job_id)
    if job is None:
        raise HTTPException(status_code=404, detail="Job not found.")
    clips = await asyncio.to_thread(store.list_clips, job_id)
    return [await asyncio.to_thread(_clip_out, clip) for clip in clips]


@router.get("/clips", response_model=list[LibraryClipOut])
async def list_all_clips(limit: int = Query(default=200, ge=1, le=1000)) -> list[LibraryClipOut]:
    """Every clip the library has produced, newest first.

    The library screen needs the source title and the job's status alongside
    each clip — the status is what tells the UI whether exporting is safe yet.
    Both are fetched once and shared, rather than joined per clip.
    """
    clips = await asyncio.to_thread(store.list_all_clips, limit)

    jobs = {}
    sources = {}
    for job_id in {clip.job_id for clip in clips}:
        job = await asyncio.to_thread(store.get_job, job_id)
        if job is None:
            continue
        jobs[job_id] = job
        source = await asyncio.to_thread(store.get_source, job.source_id)
        if source is not None:
            sources[source.id] = source

    library: list[LibraryClipOut] = []
    for clip in clips:
        job = jobs.get(clip.job_id)
        source = sources.get(job.source_id) if job else None
        base = await asyncio.to_thread(_clip_out, clip)
        library.append(
            LibraryClipOut(
                **base.model_dump(),
                source_title=source.title if source else "",
                job_status=job.status if job else "",
            )
        )
    return library


@router.get("/clips/{clip_id}", response_model=ClipOut)
async def get_clip(clip_id: str) -> ClipOut:
    clip = await asyncio.to_thread(store.get_clip, clip_id)
    if clip is None:
        raise HTTPException(status_code=404, detail="Clip not found.")
    return await asyncio.to_thread(_clip_out, clip)


@router.get("/clips/{clip_id}/words", response_model=list[WordOut])
async def clip_words(clip_id: str) -> list[WordOut]:
    """Words for a clip — the caption editor's source of truth.

    Returns the user's edited words when they exist, falling back to the
    transcript's originals.
    """
    clip = await asyncio.to_thread(store.get_clip, clip_id)
    if clip is None:
        raise HTTPException(status_code=404, detail="Clip not found.")

    edit = await asyncio.to_thread(store.get_clip_edit, clip_id)
    if edit is not None and edit.edited_words:
        return [WordOut(**word) for word in edit.edited_words]

    transcript = await asyncio.to_thread(_load_transcript, clip.job_id)
    words = transcript.slice(clip.start_word, clip.end_word)
    return [WordOut(text=w.text, start=w.start, end=w.end, speaker=w.speaker) for w in words]


@router.get("/clips/{clip_id}/crop-path")
async def clip_crop_path(clip_id: str) -> dict:
    """The computed crop path for a clip, so the preview can match the export.

    Without this the review player can only centre-crop, which on a tracked shot
    shows different framing from the file that gets rendered — sometimes with
    the speaker half out of frame. Reviewing framing against the wrong framing
    is worse than not previewing it at all.
    """
    clip = await asyncio.to_thread(store.get_clip, clip_id)
    if clip is None:
        raise HTTPException(status_code=404, detail="Clip not found.")

    cached = JobWorkspace(clip.job_id).crop_path(clip.id)
    if not cached.exists():
        # Audio-only sources and pre-reframe jobs legitimately have none; the
        # client falls back to a centre crop.
        raise HTTPException(status_code=404, detail="No crop path for this clip yet.")

    return (await asyncio.to_thread(CropPath.load, cached)).to_dict()


@router.patch("/clips/{clip_id}", response_model=ClipOut)
async def patch_clip(clip_id: str, payload: ClipPatchIn) -> ClipOut:
    """Trim, retitle, or keep/discard a clip.

    A trim re-derives the word range from the new times, so captions stay in
    step with the boundaries without the client having to compute indices.
    """
    clip = await asyncio.to_thread(store.get_clip, clip_id)
    if clip is None:
        raise HTTPException(status_code=404, detail="Clip not found.")

    start_s = payload.start_s if payload.start_s is not None else clip.start_s
    end_s = payload.end_s if payload.end_s is not None else clip.end_s
    if end_s <= start_s:
        raise HTTPException(status_code=400, detail="End must come after start.")

    trimmed = payload.start_s is not None or payload.end_s is not None
    start_word = end_word = None

    if trimmed:
        transcript = await asyncio.to_thread(_load_transcript, clip.job_id)
        first, last = transcript.indices_in_range(start_s, end_s)
        start_word, end_word = first, max(first, last - 1)

    await asyncio.to_thread(
        store.update_clip,
        clip_id,
        start_s=start_s if trimmed else None,
        end_s=end_s if trimmed else None,
        start_word=start_word,
        end_word=end_word,
        title=payload.title,
        status=payload.status,
        user_trimmed=True if trimmed else None,
    )

    updated = await asyncio.to_thread(store.get_clip, clip_id)
    return await asyncio.to_thread(_clip_out, updated)


@router.patch("/clips/{clip_id}/captions", response_model=ClipOut)
async def patch_captions(clip_id: str, payload: CaptionPatchIn) -> ClipOut:
    """Store word-level caption edits and style choices for a clip."""
    clip = await asyncio.to_thread(store.get_clip, clip_id)
    if clip is None:
        raise HTTPException(status_code=404, detail="Clip not found.")

    if payload.caption_style is not None:
        try:
            captions_module.get_style(payload.caption_style)
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

    existing = await asyncio.to_thread(store.get_clip_edit, clip_id)
    from ..db.models import ClipEdit

    edit = ClipEdit(
        clip_id=clip_id,
        edited_words=(
            [w.model_dump() for w in payload.words]
            if payload.words is not None
            else (existing.edited_words if existing else None)
        ),
        caption_style=payload.caption_style or (existing.caption_style if existing else "bold_pop"),
        ratio=payload.ratio or (existing.ratio if existing else "9:16"),
    )
    await asyncio.to_thread(store.upsert_clip_edit, edit)

    return await asyncio.to_thread(_clip_out, clip)


@router.post("/clips/{clip_id}/export", response_model=ExportOut, status_code=201)
async def export_clip(clip_id: str, payload: ExportRequestIn) -> ExportOut:
    """Render one clip and return its download link."""
    clip = await asyncio.to_thread(store.get_clip, clip_id)
    if clip is None:
        raise HTTPException(status_code=404, detail="Clip not found.")

    job = await asyncio.to_thread(store.get_job, clip.job_id)
    source = await asyncio.to_thread(store.get_source, job.source_id) if job else None
    if job is None or source is None:
        raise HTTPException(status_code=404, detail="The clip's source is missing.")

    try:
        style = captions_module.get_style(payload.style)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    words = [
        Word(text=w.text, start=w.start, end=w.end, speaker=w.speaker)
        for w in await clip_words(clip_id)
    ]

    settings = load_settings()
    settings.export.write_srt = payload.write_srt

    workspace = JobWorkspace(clip.job_id)
    crop_path = await asyncio.to_thread(_crop_path_for, workspace, clip, source, payload.ratio)

    destination = (
        paths.exports_dir()
        / clip.job_id
        / export_module.output_filename(clip.title or f"clip-{clip.rank}", payload.ratio)
    )

    # The music and the ducking are the user's choices, not the pipeline's
    # leftovers. A re-export from the review page has no creative stage to
    # read them from, so they are resolved here — the same precedence the
    # pipeline uses: the clip's own choice, then the source's, then the
    # global one.
    export_settings = await asyncio.to_thread(_export_settings_for, clip, source, settings.export)

    # The shared speech timeline, sliced to this clip. It is what the music
    # bed ducks against, so the bed and the webcam agree on when someone is
    # speaking.
    #
    # `ducking_intervals` keeps three answers apart: no timeline at all (the
    # ducking falls back to keying on the audio), a timeline that found no
    # speech in this clip (the bed is not ducked), and the speech itself.
    # Passing a plain empty list would collapse the first two, and a clip
    # with no talking would have its music pulled down by the source.
    timeline = await asyncio.to_thread(_speech_timeline_for, workspace)
    speech_intervals = speech_timeline_module.ducking_intervals(timeline, clip.start_s, clip.end_s)

    request = export_module.ExportRequest(
        source=Path(source.path),
        destination=destination,
        start_s=clip.start_s,
        end_s=clip.end_s,
        crop_path=crop_path,
        words=words,
        style=style,
        ratio=payload.ratio,
        speech_intervals=speech_intervals,
    )

    try:
        await asyncio.to_thread(
            export_module.export_clip,
            request,
            work_dir=workspace.captions_dir,
            settings=export_settings,
        )
    except LicenseBlocked as exc:
        # The track the user chose may not be used. The reason is the user's
        # own words from the licensing rules, so it is passed on unchanged
        # rather than replaced with something vaguer.
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    except export_module.ExportError as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc

    record = Export(
        id=new_id(),
        clip_id=clip_id,
        path=str(destination),
        ratio=payload.ratio,
        style=style.key,
        size_bytes=destination.stat().st_size,
    )
    await asyncio.to_thread(store.create_export, record)

    # Phase 9: validate the render, gate publishing on the result.
    report = await asyncio.to_thread(
        validate_module.validate_media,
        destination,
        expected_duration_s=clip.duration_s,
        expected_size=export_module.ratio_dimensions(payload.ratio),
        require_audio=bool(source.has_audio),
    )
    await asyncio.to_thread(
        store.update_clip,
        clip_id,
        status="exported" if report.ok else "invalid",
        validation=report.to_dict(),
    )

    if not report.ok:
        log.warning(
            "Export %s failed validation for clip %s: %s",
            record.id,
            clip_id,
            "; ".join(report.failures()),
        )
        _notify_export(clip, ok=False, failures=report.failures())
        return ExportOut.of(record, None)

    _notify_export(clip, ok=True, failures=[])

    uploads: list = []
    try:
        from ..youtube import uploads as youtube_uploads
        from ..youtube.queue import upload_queue

        uploads = await asyncio.to_thread(youtube_uploads.enqueue_export_all, record.id, settings)
        if uploads:
            upload_queue.notify()
    except Exception:  # the export succeeded; a queue failure is not fatal
        log.exception("Could not queue a YouTube upload for export %s.", record.id)

    return ExportOut.of(record, uploads=uploads)


@router.post("/clips/{clip_id}/validate")
async def validate_clip(clip_id: str) -> dict:
    """Re-run validation on a clip's newest export and persist the result."""
    clip = await asyncio.to_thread(store.get_clip, clip_id)
    if clip is None:
        raise HTTPException(status_code=404, detail="Clip not found.")

    exports = await asyncio.to_thread(store.list_exports, clip_id)
    if not exports:
        raise HTTPException(status_code=409, detail="This clip has not been exported yet.")
    latest = exports[-1]

    job = await asyncio.to_thread(store.get_job, clip.job_id)
    source = await asyncio.to_thread(store.get_source, job.source_id) if job else None

    report = await asyncio.to_thread(
        validate_module.validate_media,
        Path(latest.path),
        expected_duration_s=clip.duration_s,
        expected_size=export_module.ratio_dimensions(latest.ratio),
        require_audio=bool(source.has_audio) if source else True,
    )
    result = report.to_dict()
    await asyncio.to_thread(
        store.update_clip,
        clip_id,
        status="exported" if result["ok"] else "invalid",
        validation=result,
    )
    return {"clip_id": clip_id, "export_id": latest.id, **result}


@router.get("/clips/{clip_id}/diagnostics")
async def clip_diagnostics(clip_id: str) -> dict:
    """The objective quality measurements for a clip.

    These are measurements, not a score. Each one says what was
    measured, what the measurement came out as, and — when something is
    wrong — what to do about it. There is no single quality number,
    because there is no honest way to fold ten different measurements
    into one, and a number that looked like a verdict would be a lie.
    """
    clip = await asyncio.to_thread(store.get_clip, clip_id)
    if clip is None:
        raise HTTPException(status_code=404, detail="Clip not found.")

    if clip.diagnostics:
        return {"clip_id": clip_id, **clip.diagnostics}

    # The clip has not been measured yet. Measure it now, against its
    # newest export, so the answer is never "we did not look".
    exports = await asyncio.to_thread(store.list_exports, clip_id)
    if not exports:
        return {
            "clip_id": clip_id,
            "ok": False,
            "state": "not measured yet",
            "diagnostics": [],
        }

    latest = exports[-1]
    job = await asyncio.to_thread(store.get_job, clip.job_id)
    source = await asyncio.to_thread(store.get_source, job.source_id) if job else None

    # The same inputs the export-time report uses, so a clip measured on
    # demand is measured exactly as thoroughly as one measured during the
    # export: the caption words, and the crop the renderer used.
    words = [
        Word(text=word.text, start=word.start, end=word.end, speaker=word.speaker)
        for word in await clip_words(clip_id)
    ]

    crop_path = await asyncio.to_thread(_crop_path_for_review, clip.job_id, clip.id)

    report = await asyncio.to_thread(
        diagnostics.diagnose_clip,
        Path(latest.path),
        clip_id=clip.id,
        clips=await asyncio.to_thread(store.list_clips, clip.job_id),
        words=words,
        start_s=clip.start_s,
        end_s=clip.end_s,
        expected_size=export_module.ratio_dimensions(latest.ratio),
        source_size=(
            (source.width, source.height)
            if source is not None and source.width and source.height
            else None
        ),
        crop_path=crop_path,
        require_audio=bool(source.has_audio) if source else True,
    )
    result = report.to_dict()
    await asyncio.to_thread(store.update_clip, clip_id, diagnostics=result)
    return {"clip_id": clip_id, "state": "measured", **result}


def _crop_path_for_review(job_id: str, clip_id: str) -> CropPath | None:
    """The cached crop path for a clip, when the job has one.

    A job that has not reframed yet legitimately has none, and the
    measurement says so rather than pretending the crop was checked.
    """
    cached = JobWorkspace(job_id).crop_path(clip_id)
    if not cached.exists():
        return None
    try:
        return CropPath.load(cached)
    except Exception:  # noqa: BLE001 - an unreadable cache is not a failure
        return None


@router.get("/exports/{export_id}/download")
async def download_export(export_id: str) -> FileResponse:
    record = await asyncio.to_thread(store.get_export, export_id)
    if record is None:
        raise HTTPException(status_code=404, detail="Export not found.")

    path = Path(record.path)
    if not path.exists():
        raise HTTPException(status_code=410, detail="The exported file has been moved or deleted.")

    return FileResponse(path, media_type="video/mp4", filename=path.name)


@router.get("/jobs/{job_id}/media")
async def job_media(job_id: str) -> FileResponse:
    """Serve the source video, so the review player can scrub the original.

    Range requests are handled by FileResponse, which is what makes seeking in
    the preview player usable on a long source.
    """
    job = await asyncio.to_thread(store.get_job, job_id)
    if job is None:
        raise HTTPException(status_code=404, detail="Job not found.")

    source = await asyncio.to_thread(store.get_source, job.source_id)
    if source is None or not Path(source.path).exists():
        raise HTTPException(status_code=404, detail="Source media not found.")

    return FileResponse(Path(source.path))


@router.get("/caption-styles", response_model=list[CaptionStyleOut])
async def caption_styles() -> list[CaptionStyleOut]:
    """Style presets, with enough detail for the UI to approximate them in CSS."""
    return [
        CaptionStyleOut(
            key=style.key,
            label=style.label,
            description=style.description,
            preview={
                "font": style.font,
                "primary": style.primary,
                "accent": style.accent,
                "outline": style.outline,
                "outlineWidth": style.outline_width,
                "allCaps": style.all_caps,
                "sizeRatio": style.size_ratio,
                "marginRatio": style.margin_v_ratio,
                "boxed": style.boxed,
                "animation": style.animation,
                "maxWords": style.max_words,
            },
        )
        for style in captions_module.PRESETS.values()
    ]


# --------------------------------------------------------------------------
# Helpers
# --------------------------------------------------------------------------


def _load_transcript(job_id: str) -> Transcript:
    workspace = JobWorkspace(job_id)
    if not workspace.transcript.exists():
        raise HTTPException(status_code=404, detail="This job has no transcript yet.")
    return Transcript.load(workspace.transcript)


def _speech_timeline_for(workspace: JobWorkspace) -> speech_timeline_module.SpeechTimeline | None:
    """The job's shared speech timeline, or None if it has not been built.

    The timeline is written once, after the transcript exists. A job that
    has not got one — a restored workspace, or a job whose pipeline stopped
    before the timeline stage — exports without it, and the ducking falls
    back to keying on the audio itself.
    """
    path = workspace.speech_timeline
    if not path.exists():
        return None
    try:
        return speech_timeline_module.SpeechTimeline.load(path)
    except (OSError, ValueError) as exc:
        log.warning("The speech timeline for this job could not be read: %s", exc)
        return None


def _export_settings_for(clip, source, export_settings):
    """The export settings for one clip, including the music it should use.

    The pipeline's own export stage takes the music from the creative
    stage's selection. A re-export from the review page has no creative
    stage, so the user's own choice is resolved here instead, with the same
    precedence the music-selection stage uses: the clip's choice, then the
    source's, then the global one.

    Two answers are distinguished from a gap:

    * "no music at all" is a choice, and it is honoured — the bed is left
      off even when the global export setting names a track;
    * "no preference anywhere" is a gap, and the global export setting is
      the fallback, so an install that configured a bed keeps it.
    """
    from ..music import preferences as music_preferences
    from ..music import store as music_store

    track_id, scope = music_preferences.resolve_preference(
        clip_id=clip.id,
        source_id=source.id,
    )

    if not track_id:
        return export_settings

    if track_id == music_preferences.NO_MUSIC:
        return export_settings.model_copy(update={"music_track": ""})

    track = music_store.get_track(track_id)
    if track is None:
        # The track was removed from the library between the choice and the
        # export. The global setting is a better answer than a path that no
        # longer exists.
        log.warning(
            "The track chosen for clip %s (%s scope) is no longer in the library.",
            clip.id,
            scope,
        )
        return export_settings

    return export_settings.model_copy(update={"music_track": track.path})


def _crop_path_for(workspace: JobWorkspace, clip, source, ratio: str) -> CropPath:
    """Reuse the job's cached crop path, falling back to a centre crop.

    A re-export at a different ratio can't reuse a path computed for the
    original one, so the geometry is recomputed rather than stretched.
    """
    cached = workspace.crop_path(clip.id)
    if cached.exists() and ratio == "9:16":
        return CropPath.load(cached)

    aspect = {"9:16": (9, 16), "1:1": (1, 1), "16:9": (16, 9)}[ratio]
    return centre_crop(
        source.width or 1920,
        source.height or 1080,
        clip.end_s - clip.start_s,
        aspect_w=aspect[0],
        aspect_h=aspect[1],
    )
