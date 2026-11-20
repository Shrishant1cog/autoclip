"""Pydantic request and response models for the REST API.

Kept separate from the dataclasses in ``db.models``: those mirror SQLite rows,
these are the wire contract. Splitting them means a schema change doesn't
silently reshape the API, and the API can expose derived fields (durations,
export URLs) that don't belong in storage.
"""

from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, Field

from ..db import models


class SourceOut(BaseModel):
    id: str
    type: str
    title: str
    url: str | None = None
    filename: str | None = None
    channel: str | None = None
    duration_s: float
    width: int | None = None
    height: int | None = None
    fps: float | None = None
    has_audio: bool
    has_video: bool
    created_at: str

    @classmethod
    def of(cls, source: models.Source) -> SourceOut:
        # Built field by field rather than from vars(): the row carries an
        # absolute filesystem path that has no business leaving the process.
        return cls(
            id=source.id,
            type=source.type,
            title=source.title,
            url=source.url,
            filename=source.filename,
            channel=source.channel,
            duration_s=source.duration_s,
            width=source.width,
            height=source.height,
            fps=source.fps,
            has_audio=source.has_audio,
            has_video=source.has_video,
            created_at=source.created_at,
        )


class YouTubeIngestIn(BaseModel):
    url: str
    cookies_from_browser: str | None = None


class JobSettingsIn(BaseModel):
    """Per-job overrides. Anything omitted falls back to saved settings."""

    provider: str | None = None
    whisper_model: str | None = None
    language: str | None = None
    diarization: bool | None = None
    min_duration_s: float | None = Field(default=None, gt=0)
    max_duration_s: float | None = Field(default=None, gt=0)
    max_clips: int | None = Field(default=None, ge=1, le=50)
    caption_style: str | None = None
    ratio: Literal["9:16", "1:1", "16:9"] | None = None


class JobCreateIn(BaseModel):
    source_id: str
    settings: JobSettingsIn = Field(default_factory=JobSettingsIn)


class JobOut(BaseModel):
    id: str
    source_id: str
    status: str
    current_stage: str
    progress: float
    error: str | None = None
    provider: str
    created_at: str
    updated_at: str
    started_at: str | None = None
    finished_at: str | None = None
    source: SourceOut | None = None

    @classmethod
    def of(cls, job: models.Job, source: models.Source | None = None) -> JobOut:
        return cls(
            id=job.id,
            source_id=job.source_id,
            status=job.status,
            current_stage=job.current_stage,
            progress=job.progress,
            error=job.error,
            provider=job.provider,
            created_at=job.created_at,
            updated_at=job.updated_at,
            started_at=job.started_at,
            finished_at=job.finished_at,
            source=SourceOut.of(source) if source else None,
        )


class WordOut(BaseModel):
    text: str
    start: float
    end: float
    speaker: str | None = None


class UploadOut(BaseModel):
    """One YouTube upload attempt attached to an export."""

    id: str
    export_id: str
    clip_id: str
    channel_row_id: str = ""
    status: str
    video_id: str | None = None
    title: str = ""
    description: str = ""
    tags: list[str] = Field(default_factory=list)
    privacy: str = "public"
    error: str | None = None
    watch_url: str = ""
    created_at: str
    updated_at: str

    @classmethod
    def of(cls, upload: models.YouTubeUpload) -> UploadOut:
        return cls(
            id=upload.id,
            export_id=upload.export_id,
            clip_id=upload.clip_id,
            channel_row_id=upload.channel_row_id,
            status=upload.status,
            video_id=upload.video_id,
            title=upload.title,
            description=upload.description,
            tags=upload.tags,
            privacy=upload.privacy,
            error=upload.error,
            watch_url=(f"https://youtu.be/{upload.video_id}" if upload.video_id else ""),
            created_at=upload.created_at,
            updated_at=upload.updated_at,
        )


class YouTubeStatusOut(BaseModel):
    configured: bool
    connected: bool
    auto_upload: bool
    client_id: str = ""
    redirect_uri: str = ""
    privacy: str = "public"
    channel_id: str = ""
    channel_title: str = ""
    channel_url: str = ""
    connected_at: str = ""


class YouTubeConnectOut(BaseModel):
    auth_url: str


class YouTubeConnectIn(BaseModel):
    """Which account a sign-in is for.

    ``account_id`` empty means "a new account". The sign-in that comes
    back is filed under that account, so two accounts never share a
    credential.
    """

    account_id: str = ""
    label: str = ""


class YouTubeDisconnectIn(BaseModel):
    """Which account to disconnect. Empty means the legacy connection."""

    account_id: str = ""


class YouTubeAutoIn(BaseModel):
    enabled: bool


class YouTubePrivacyIn(BaseModel):
    privacy: Literal["private", "unlisted", "public"]


class ExportOut(BaseModel):
    id: str
    clip_id: str
    ratio: str
    style: str
    size_bytes: int
    created_at: str
    download_url: str
    #: Present when this export was queued for YouTube, so the UI can show
    #: progress or a retry button next to the download link. ``upload`` keeps
    #: the first row for backwards compatibility; ``uploads`` lists every
    #: fan-out destination.
    upload: UploadOut | None = None
    uploads: list[UploadOut] = Field(default_factory=list)

    @classmethod
    def of(
        cls,
        export: models.Export,
        upload: models.YouTubeUpload | None = None,
        *,
        uploads: list[models.YouTubeUpload] | None = None,
    ) -> ExportOut:
        rows = uploads if uploads is not None else ([upload] if upload else [])
        return cls(
            id=export.id,
            clip_id=export.clip_id,
            ratio=export.ratio,
            style=export.style,
            size_bytes=export.size_bytes,
            created_at=export.created_at,
            download_url=f"/api/exports/{export.id}/download",
            upload=UploadOut.of(rows[0]) if rows else None,
            uploads=[UploadOut.of(row) for row in rows],
        )


class ClipOut(BaseModel):
    id: str
    job_id: str
    rank: int
    start_s: float
    end_s: float
    duration_s: float
    start_word: int
    end_word: int
    title: str
    hook: str
    #: The model's suggestion for how strong the moment is, 0–100.
    #:
    #: This is a **creative judgement, not a measured quality number**. It
    #: is what the clips are ordered by. The measurements live in
    #: ``diagnostics``, and there is no single quality score anywhere.
    score: int
    reason: str
    status: str
    user_trimmed: bool
    validation: dict | None = None
    caption_style: str = "bold_pop"
    ratio: str = "9:16"
    #: The music this clip ended up with. Empty when it has none.
    music_track_id: str = ""
    #: Whose choice it was: "user", "ai" or "deterministic".
    music_source: str = ""
    #: Why that track was chosen, in plain words.
    music_reason: str = ""
    #: The objective quality measurements. These are measurements, not a
    #: score — there is no single quality number.
    diagnostics: dict | None = None
    exports: list[ExportOut] = Field(default_factory=list)

    @classmethod
    def of(
        cls,
        clip: models.Clip,
        *,
        edit: models.ClipEdit | None = None,
        exports: list[models.Export] | None = None,
        uploads: dict[str, list[models.YouTubeUpload]] | None = None,
    ) -> ClipOut:
        uploads = uploads or {}
        return cls(
            id=clip.id,
            job_id=clip.job_id,
            rank=clip.rank,
            start_s=clip.start_s,
            end_s=clip.end_s,
            duration_s=clip.duration_s,
            start_word=clip.start_word,
            end_word=clip.end_word,
            title=clip.title,
            hook=clip.hook,
            score=clip.score,
            reason=clip.reason,
            status=clip.status,
            user_trimmed=clip.user_trimmed,
            validation=clip.validation,
            caption_style=edit.caption_style if edit else "bold_pop",
            ratio=edit.ratio if edit else "9:16",
            music_track_id=clip.music_track_id,
            music_source=clip.music_source,
            music_reason=clip.music_reason,
            diagnostics=clip.diagnostics,
            exports=[ExportOut.of(e, uploads=uploads.get(e.id, [])) for e in (exports or [])],
        )


class LibraryClipOut(ClipOut):
    """A clip plus the context the all-clips library needs to group it."""

    source_title: str = ""
    job_status: str = ""


class ClipPatchIn(BaseModel):
    start_s: float | None = Field(default=None, ge=0)
    end_s: float | None = Field(default=None, gt=0)
    title: str | None = None
    status: Literal["candidate", "kept", "discarded", "exported"] | None = None


class CaptionPatchIn(BaseModel):
    """Word-level caption edits for one clip."""

    words: list[WordOut] | None = None
    caption_style: str | None = None
    ratio: Literal["9:16", "1:1", "16:9"] | None = None


class ExportRequestIn(BaseModel):
    ratio: Literal["9:16", "1:1", "16:9"] = "9:16"
    style: str = "bold_pop"
    write_srt: bool = False


class CaptionStyleOut(BaseModel):
    key: str
    label: str
    description: str
    #: Enough for the UI to approximate the look in HTML/CSS before rendering.
    preview: dict[str, Any]


class ProviderStatusOut(BaseModel):
    name: str
    available: bool
    detail: str = ""
    models: list[str] = Field(default_factory=list)
    requires_key: bool = True
    has_key: bool = False


class SettingsOut(BaseModel):
    active_provider: str
    providers: dict[str, dict[str, Any]]
    whisper: dict[str, Any]
    transcription: dict[str, Any]
    clips: dict[str, Any]
    ingest: dict[str, Any]
    export: dict[str, Any]
    resources: dict[str, Any] = Field(default_factory=dict)
    youtube: dict[str, Any]
    insecure_secret_storage: bool
    #: Which providers have a key stored. The keys themselves never leave the
    #: keyring, so the UI shows presence, not value.
    keys_present: dict[str, bool] = Field(default_factory=dict)
    #: YouTube OAuth client secret presence (never the value).
    youtube_secret_present: bool = False


class SettingsIn(BaseModel):
    active_provider: str | None = None
    providers: dict[str, dict[str, Any]] | None = None
    whisper: dict[str, Any] | None = None
    transcription: dict[str, Any] | None = None
    clips: dict[str, Any] | None = None
    ingest: dict[str, Any] | None = None
    export: dict[str, Any] | None = None
    resources: dict[str, Any] | None = None
    youtube: dict[str, Any] | None = None


class SecretIn(BaseModel):
    key: str
    value: str


class SystemOut(BaseModel):
    ready: bool
    python_version: str
    platform: str
    ffmpeg_version: str | None
    has_libass: bool
    nvenc_works: bool
    accel: str
    gpu_name: str | None
    compute_type: str
    diarization_available: bool
