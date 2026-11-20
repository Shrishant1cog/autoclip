"""CRUD operations over the AutoClip database.

Every function opens its own transaction via :func:`autoclip.db.connection`,
so callers don't manage commits. Functions are synchronous; async callers should
wrap them in ``asyncio.to_thread``.
"""

from __future__ import annotations

import json
from typing import Any

from . import connection
from .models import (
    AppRestart,
    Clip,
    ClipEdit,
    ClipStatus,
    Export,
    Job,
    JobResources,
    JobStatus,
    Notification,
    Source,
    Transcript,
    UploadStatus,
    YouTubeUpload,
    new_id,
    utcnow,
)

# --------------------------------------------------------------------------
# Sources
# --------------------------------------------------------------------------


def create_source(source: Source) -> Source:
    with connection() as conn:
        conn.execute(
            """
            INSERT INTO sources (id, type, url, filename, path, title, channel,
                                 duration_s, width, height, fps, has_audio,
                                 has_video, created_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                source.id,
                source.type,
                source.url,
                source.filename,
                source.path,
                source.title,
                source.channel,
                source.duration_s,
                source.width,
                source.height,
                source.fps,
                int(source.has_audio),
                int(source.has_video),
                source.created_at,
            ),
        )
    return source


def update_source(source: Source) -> None:
    """Persist a source after ingestion fills in its downloaded file and metadata.

    The web flow inserts a pending YouTube source immediately, then the job's
    prepare stage downloads the media and writes the probed fields back here.
    """
    with connection() as conn:
        conn.execute(
            """
            UPDATE sources SET
                url = ?, filename = ?, path = ?, title = ?, channel = ?,
                duration_s = ?, width = ?, height = ?, fps = ?,
                has_audio = ?, has_video = ?
            WHERE id = ?
            """,
            (
                source.url,
                source.filename,
                source.path,
                source.title,
                source.channel,
                source.duration_s,
                source.width,
                source.height,
                source.fps,
                int(source.has_audio),
                int(source.has_video),
                source.id,
            ),
        )


def get_source(source_id: str) -> Source | None:
    with connection() as conn:
        row = conn.execute("SELECT * FROM sources WHERE id = ?", (source_id,)).fetchone()
    return Source.from_row(row) if row else None


def list_sources(limit: int = 50) -> list[Source]:
    with connection() as conn:
        rows = conn.execute(
            "SELECT * FROM sources ORDER BY created_at DESC LIMIT ?", (limit,)
        ).fetchall()
    return [Source.from_row(r) for r in rows]


# --------------------------------------------------------------------------
# Jobs
# --------------------------------------------------------------------------


def create_job(job: Job) -> Job:
    with connection() as conn:
        conn.execute(
            """
            INSERT INTO jobs (id, source_id, status, current_stage, progress, error,
                              provider, settings_json, created_at, updated_at,
                              started_at, finished_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                job.id,
                job.source_id,
                job.status,
                job.current_stage,
                job.progress,
                job.error,
                job.provider,
                json.dumps(job.settings),
                job.created_at,
                job.updated_at,
                job.started_at,
                job.finished_at,
            ),
        )
    return job


def get_job(job_id: str) -> Job | None:
    with connection() as conn:
        row = conn.execute("SELECT * FROM jobs WHERE id = ?", (job_id,)).fetchone()
    return Job.from_row(row) if row else None


def list_jobs(limit: int = 50, status: JobStatus | None = None) -> list[Job]:
    query = "SELECT * FROM jobs"
    params: list[Any] = []
    if status:
        query += " WHERE status = ?"
        params.append(status)
    query += " ORDER BY created_at DESC LIMIT ?"
    params.append(limit)

    with connection() as conn:
        rows = conn.execute(query, params).fetchall()
    return [Job.from_row(r) for r in rows]


class _Unset:
    """Sentinel distinguishing "leave this alone" from "set this to NULL".

    Without it, nullable columns can only ever be written, never cleared — a
    retried job would keep displaying the error message from its failed run.
    """

    def __repr__(self) -> str:  # pragma: no cover - debugging aid
        return "UNSET"


UNSET = _Unset()


def update_job(
    job_id: str,
    *,
    status: JobStatus | None = None,
    current_stage: str | None = None,
    progress: float | None = None,
    error: str | None | _Unset = UNSET,
    started_at: str | None | _Unset = UNSET,
    finished_at: str | None | _Unset = UNSET,
) -> None:
    """Patch the supplied fields. Omitted fields are left untouched.

    Nullable fields take :data:`UNSET` as their default, so passing ``None``
    explicitly clears them.

    ``updated_at`` is always refreshed so the UI can detect staleness.
    """
    fields: dict[str, Any] = {"updated_at": utcnow()}
    for name, value in (
        ("status", status),
        ("current_stage", current_stage),
        ("progress", progress),
    ):
        if value is not None:
            fields[name] = value

    for name, value in (
        ("error", error),
        ("started_at", started_at),
        ("finished_at", finished_at),
    ):
        if not isinstance(value, _Unset):
            fields[name] = value

    assignments = ", ".join(f"{name} = ?" for name in fields)
    with connection() as conn:
        conn.execute(
            f"UPDATE jobs SET {assignments} WHERE id = ?",
            (*fields.values(), job_id),
        )


def next_queued_job() -> Job | None:
    """Return the oldest queued job — the FIFO the worker pulls from."""
    with connection() as conn:
        row = conn.execute(
            "SELECT * FROM jobs WHERE status = 'queued' ORDER BY created_at ASC LIMIT 1"
        ).fetchone()
    return Job.from_row(row) if row else None


# --------------------------------------------------------------------------
# Transcripts
# --------------------------------------------------------------------------


def upsert_transcript(transcript: Transcript) -> Transcript:
    with connection() as conn:
        conn.execute(
            """
            INSERT INTO transcripts (job_id, json_path, language, model,
                                     has_diarization, word_count, source, created_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(job_id) DO UPDATE SET
                json_path = excluded.json_path,
                language = excluded.language,
                model = excluded.model,
                has_diarization = excluded.has_diarization,
                word_count = excluded.word_count,
                source = excluded.source
            """,
            (
                transcript.job_id,
                transcript.json_path,
                transcript.language,
                transcript.model,
                int(transcript.has_diarization),
                transcript.word_count,
                transcript.source,
                transcript.created_at,
            ),
        )
    return transcript


def get_transcript(job_id: str) -> Transcript | None:
    with connection() as conn:
        row = conn.execute("SELECT * FROM transcripts WHERE job_id = ?", (job_id,)).fetchone()
    return Transcript.from_row(row) if row else None


# --------------------------------------------------------------------------
# Clips
# --------------------------------------------------------------------------


def replace_clips(job_id: str, clips: list[Clip]) -> list[Clip]:
    """Swap in a fresh set of clips for a job.

    Used when highlight detection reruns — a retry should not leave the previous
    run's candidates behind.
    """
    with connection() as conn:
        conn.execute("DELETE FROM clips WHERE job_id = ?", (job_id,))
        conn.executemany(
            """
            INSERT INTO clips (id, job_id, rank, start_s, end_s, start_word, end_word,
                               title, hook, score, reason, status, user_trimmed, created_at,
                               music_track_id, music_source, music_reason)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            [
                (
                    c.id,
                    c.job_id,
                    c.rank,
                    c.start_s,
                    c.end_s,
                    c.start_word,
                    c.end_word,
                    c.title,
                    c.hook,
                    c.score,
                    c.reason,
                    c.status,
                    int(c.user_trimmed),
                    c.created_at,
                    c.music_track_id,
                    c.music_source,
                    c.music_reason,
                )
                for c in clips
            ],
        )
    return clips


def get_clip(clip_id: str) -> Clip | None:
    with connection() as conn:
        row = conn.execute("SELECT * FROM clips WHERE id = ?", (clip_id,)).fetchone()
    return Clip.from_row(row) if row else None


def list_clips(job_id: str) -> list[Clip]:
    with connection() as conn:
        rows = conn.execute(
            "SELECT * FROM clips WHERE job_id = ? ORDER BY rank ASC", (job_id,)
        ).fetchall()
    return [Clip.from_row(r) for r in rows]


def list_all_clips(limit: int = 200) -> list[Clip]:
    """Every clip, newest job first — the library view's source of truth."""
    with connection() as conn:
        rows = conn.execute(
            "SELECT * FROM clips ORDER BY created_at DESC, rank ASC LIMIT ?", (limit,)
        ).fetchall()
    return [Clip.from_row(r) for r in rows]


def update_clip(
    clip_id: str,
    *,
    start_s: float | None = None,
    end_s: float | None = None,
    start_word: int | None = None,
    end_word: int | None = None,
    title: str | None = None,
    status: ClipStatus | None = None,
    user_trimmed: bool | None = None,
    validation: dict[str, Any] | None = None,
    music_track_id: str | None = None,
    music_source: str | None = None,
    music_reason: str | None = None,
    diagnostics: dict[str, Any] | None = None,
) -> None:
    fields: dict[str, Any] = {}
    for name, value in (
        ("start_s", start_s),
        ("end_s", end_s),
        ("start_word", start_word),
        ("end_word", end_word),
        ("title", title),
        ("status", status),
        ("music_track_id", music_track_id),
        ("music_source", music_source),
        ("music_reason", music_reason),
    ):
        if value is not None:
            fields[name] = value
    if user_trimmed is not None:
        fields["user_trimmed"] = int(user_trimmed)
    if validation is not None:
        fields["validation_json"] = json.dumps(validation)
    if diagnostics is not None:
        fields["diagnostics_json"] = json.dumps(diagnostics)

    if not fields:
        return

    assignments = ", ".join(f"{name} = ?" for name in fields)
    with connection() as conn:
        conn.execute(
            f"UPDATE clips SET {assignments} WHERE id = ?",
            (*fields.values(), clip_id),
        )


# --------------------------------------------------------------------------
# Clip edits
# --------------------------------------------------------------------------


def upsert_clip_edit(edit: ClipEdit) -> ClipEdit:
    with connection() as conn:
        conn.execute(
            """
            INSERT INTO clip_edits (clip_id, edited_words_json, caption_style, ratio, updated_at)
            VALUES (?, ?, ?, ?, ?)
            ON CONFLICT(clip_id) DO UPDATE SET
                edited_words_json = excluded.edited_words_json,
                caption_style = excluded.caption_style,
                ratio = excluded.ratio,
                updated_at = excluded.updated_at
            """,
            (
                edit.clip_id,
                json.dumps(edit.edited_words) if edit.edited_words is not None else None,
                edit.caption_style,
                edit.ratio,
                utcnow(),
            ),
        )
    return edit


def get_clip_edit(clip_id: str) -> ClipEdit | None:
    with connection() as conn:
        row = conn.execute("SELECT * FROM clip_edits WHERE clip_id = ?", (clip_id,)).fetchone()
    return ClipEdit.from_row(row) if row else None


# --------------------------------------------------------------------------
# Exports
# --------------------------------------------------------------------------


def create_export(export: Export) -> Export:
    with connection() as conn:
        conn.execute(
            """
            INSERT INTO exports (id, clip_id, path, ratio, style, size_bytes, created_at)
            VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
            (
                export.id,
                export.clip_id,
                export.path,
                export.ratio,
                export.style,
                export.size_bytes,
                export.created_at,
            ),
        )
    return export


def get_export(export_id: str) -> Export | None:
    with connection() as conn:
        row = conn.execute("SELECT * FROM exports WHERE id = ?", (export_id,)).fetchone()
    return Export.from_row(row) if row else None


def list_exports(clip_id: str) -> list[Export]:
    with connection() as conn:
        rows = conn.execute(
            "SELECT * FROM exports WHERE clip_id = ? ORDER BY created_at DESC", (clip_id,)
        ).fetchall()
    return [Export.from_row(r) for r in rows]


def list_all_exports() -> list[Export]:
    """Every exported clip, oldest first. Used when backfilling uploads."""
    with connection() as conn:
        rows = conn.execute("SELECT * FROM exports ORDER BY created_at ASC").fetchall()
    return [Export.from_row(r) for r in rows]


# --------------------------------------------------------------------------
# YouTube uploads
# --------------------------------------------------------------------------


def create_upload(upload: YouTubeUpload) -> YouTubeUpload:
    """Insert an upload row. An existing row for the export is returned instead.

    Exports are enqueued from two places (the pipeline and the manual export
    endpoint); the unique index makes double-enqueue a no-op rather than an
    error.
    """
    with connection() as conn:
        existing = conn.execute(
            "SELECT * FROM youtube_uploads WHERE export_id = ? AND channel_row_id = ?",
            (upload.export_id, upload.channel_row_id),
        ).fetchone()
        if existing:
            return YouTubeUpload.from_row(existing)
        conn.execute(
            """
            INSERT INTO youtube_uploads (
                id, export_id, clip_id, channel_row_id, status, video_id, title,
                description, tags_json, privacy, error, created_at, updated_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                upload.id,
                upload.export_id,
                upload.clip_id,
                upload.channel_row_id,
                upload.status,
                upload.video_id,
                upload.title,
                upload.description,
                json.dumps(upload.tags),
                upload.privacy,
                upload.error,
                upload.created_at,
                upload.updated_at,
            ),
        )
    return upload


def get_upload(upload_id: str) -> YouTubeUpload | None:
    with connection() as conn:
        row = conn.execute("SELECT * FROM youtube_uploads WHERE id = ?", (upload_id,)).fetchone()
    return YouTubeUpload.from_row(row) if row else None


def get_upload_for_export(export_id: str) -> YouTubeUpload | None:
    """The first upload row for an export (legacy default channel first)."""
    with connection() as conn:
        row = conn.execute(
            "SELECT * FROM youtube_uploads WHERE export_id = ? "
            "ORDER BY (channel_row_id <> '') ASC, created_at ASC LIMIT 1",
            (export_id,),
        ).fetchone()
    return YouTubeUpload.from_row(row) if row else None


def list_uploads_for_export(export_id: str) -> list[YouTubeUpload]:
    with connection() as conn:
        rows = conn.execute(
            "SELECT * FROM youtube_uploads WHERE export_id = ? ORDER BY created_at ASC",
            (export_id,),
        ).fetchall()
    return [YouTubeUpload.from_row(r) for r in rows]


def list_uploads_for_clip(clip_id: str) -> list[YouTubeUpload]:
    with connection() as conn:
        rows = conn.execute(
            "SELECT * FROM youtube_uploads WHERE clip_id = ? ORDER BY created_at DESC",
            (clip_id,),
        ).fetchall()
    return [YouTubeUpload.from_row(r) for r in rows]


def next_pending_upload() -> YouTubeUpload | None:
    with connection() as conn:
        row = conn.execute(
            "SELECT * FROM youtube_uploads WHERE status = 'pending' ORDER BY created_at ASC LIMIT 1"
        ).fetchone()
    return YouTubeUpload.from_row(row) if row else None


def list_all_uploads() -> list[YouTubeUpload]:
    """Every upload row, oldest first. Used by the duplicate report."""
    with connection() as conn:
        rows = conn.execute(
            "SELECT * FROM youtube_uploads ORDER BY created_at ASC, id ASC"
        ).fetchall()
    return [YouTubeUpload.from_row(r) for r in rows]


def update_upload(
    upload_id: str,
    *,
    status: UploadStatus | None = None,
    video_id: str | None = None,
    title: str | None = None,
    description: str | None = None,
    tags: list[str] | None = None,
    privacy: str | None = None,
    error: str | None = None,
    clear_error: bool = False,
) -> None:
    fields: dict[str, Any] = {"updated_at": utcnow()}
    for name, value in (
        ("status", status),
        ("video_id", video_id),
        ("title", title),
        ("description", description),
        ("privacy", privacy),
        ("error", error),
    ):
        if value is not None:
            fields[name] = value
    if tags is not None:
        fields["tags_json"] = json.dumps(tags)
    if clear_error:
        fields["error"] = None

    assignments = ", ".join(f"{name} = ?" for name in fields)
    with connection() as conn:
        conn.execute(
            f"UPDATE youtube_uploads SET {assignments} WHERE id = ?",
            (*fields.values(), upload_id),
        )


def requeue_interrupted_uploads() -> list[str]:
    """Turn rows left mid-upload by a crash back into pending work.

    Returns the ids that were recovered, so the restart can be recorded and
    the user can be told what was resumed.
    """
    with connection() as conn:
        rows = conn.execute("SELECT id FROM youtube_uploads WHERE status = 'uploading'").fetchall()
        ids = [row["id"] for row in rows]
        if ids:
            conn.execute(
                """
                UPDATE youtube_uploads
                   SET status = 'pending', error = NULL, last_resumed_at = ?
                 WHERE status = 'uploading'
                """,
                (utcnow(),),
            )
    return ids


# --------------------------------------------------------------------------
# Restart recovery (Phase 17)
# --------------------------------------------------------------------------


def mark_job_resumed(job_id: str) -> None:
    """Record that a restart interrupted this job and the queue resumed it."""
    with connection() as conn:
        conn.execute("UPDATE jobs SET last_resumed_at = ? WHERE id = ?", (utcnow(), job_id))


def record_restart(
    *,
    jobs_resumed: int = 0,
    uploads_resumed: int = 0,
    batch_items_resumed: int = 0,
    job_ids: list[str] | None = None,
    upload_ids: list[str] | None = None,
    details: str = "",
) -> AppRestart:
    """Record one restart and what it recovered."""
    restart = AppRestart(
        id=new_id(),
        jobs_resumed=jobs_resumed,
        uploads_resumed=uploads_resumed,
        batch_items_resumed=batch_items_resumed,
        job_ids=list(job_ids or []),
        upload_ids=list(upload_ids or []),
        details=details,
    )
    with connection() as conn:
        conn.execute(
            """
            INSERT INTO app_restarts (
                id, started_at, jobs_resumed, uploads_resumed,
                batch_items_resumed, job_ids_json, upload_ids_json, details
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                restart.id,
                restart.started_at,
                restart.jobs_resumed,
                restart.uploads_resumed,
                restart.batch_items_resumed,
                json.dumps(restart.job_ids),
                json.dumps(restart.upload_ids),
                restart.details,
            ),
        )
    return restart


def list_restarts(limit: int = 20) -> list[AppRestart]:
    """Restarts, newest first."""
    with connection() as conn:
        rows = conn.execute(
            """
            SELECT * FROM app_restarts
             ORDER BY started_at DESC, rowid DESC
             LIMIT ?
            """,
            (max(1, min(limit, 200)),),
        ).fetchall()
    return [AppRestart.from_row(row) for row in rows]


# --------------------------------------------------------------------------
# Job resources (Phase 16)
# --------------------------------------------------------------------------


def upsert_job_resources(resources: JobResources) -> JobResources:
    """Record what a job consumed, replacing any earlier record for it."""
    with connection() as conn:
        conn.execute(
            """
            INSERT INTO job_resources (
                job_id, llm_calls, llm_input_tokens, llm_output_tokens,
                ffmpeg_runs, ffmpeg_seconds, export_bytes, windows_skipped,
                updated_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(job_id) DO UPDATE SET
                llm_calls = excluded.llm_calls,
                llm_input_tokens = excluded.llm_input_tokens,
                llm_output_tokens = excluded.llm_output_tokens,
                ffmpeg_runs = excluded.ffmpeg_runs,
                ffmpeg_seconds = excluded.ffmpeg_seconds,
                export_bytes = excluded.export_bytes,
                windows_skipped = excluded.windows_skipped,
                updated_at = excluded.updated_at
            """,
            (
                resources.job_id,
                resources.llm_calls,
                resources.llm_input_tokens,
                resources.llm_output_tokens,
                resources.ffmpeg_runs,
                resources.ffmpeg_seconds,
                resources.export_bytes,
                resources.windows_skipped,
                resources.updated_at,
            ),
        )
    return resources


def get_job_resources(job_id: str) -> JobResources | None:
    with connection() as conn:
        row = conn.execute("SELECT * FROM job_resources WHERE job_id = ?", (job_id,)).fetchone()
    return JobResources.from_row(row) if row else None


def list_job_resources(limit: int = 100) -> list[JobResources]:
    """Per-job usage, most recently updated first."""
    with connection() as conn:
        rows = conn.execute(
            "SELECT * FROM job_resources ORDER BY updated_at DESC, rowid DESC LIMIT ?",
            (max(1, min(limit, 1000)),),
        ).fetchall()
    return [JobResources.from_row(r) for r in rows]


def total_job_resources() -> JobResources:
    """The totals across every job that recorded usage."""
    with connection() as conn:
        row = conn.execute(
            """
            SELECT
                COALESCE(SUM(llm_calls), 0) AS llm_calls,
                COALESCE(SUM(llm_input_tokens), 0) AS llm_input_tokens,
                COALESCE(SUM(llm_output_tokens), 0) AS llm_output_tokens,
                COALESCE(SUM(ffmpeg_runs), 0) AS ffmpeg_runs,
                COALESCE(SUM(ffmpeg_seconds), 0) AS ffmpeg_seconds,
                COALESCE(SUM(export_bytes), 0) AS export_bytes,
                COALESCE(SUM(windows_skipped), 0) AS windows_skipped,
                MAX(updated_at) AS updated_at
            FROM job_resources
            """
        ).fetchone()
    # The aggregate has no job_id of its own; the totals belong to no single job.
    return JobResources(
        job_id="",
        llm_calls=row["llm_calls"],
        llm_input_tokens=row["llm_input_tokens"],
        llm_output_tokens=row["llm_output_tokens"],
        ffmpeg_runs=row["ffmpeg_runs"],
        ffmpeg_seconds=row["ffmpeg_seconds"],
        export_bytes=row["export_bytes"],
        windows_skipped=row["windows_skipped"],
        updated_at=row["updated_at"] or utcnow(),
    )


# --------------------------------------------------------------------------
# Notifications (Phase 14)
# --------------------------------------------------------------------------


def create_notification(
    notification: Notification,
) -> Notification:
    """Store one notification row."""
    with connection() as conn:
        conn.execute(
            "INSERT INTO notifications (id, kind, severity, title, body, link,"
            " entity_id, read, created_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (
                notification.id,
                notification.kind,
                notification.severity,
                notification.title,
                notification.body,
                notification.link,
                notification.entity_id,
                1 if notification.read else 0,
                notification.created_at,
            ),
        )
    return notification


def list_notifications(limit: int = 50, *, unread_only: bool = False) -> list[Notification]:
    """Recent notifications, newest first.

    ``rowid`` breaks ties: timestamps have second precision, so two events in
    the same second would otherwise come back in arbitrary order. ``rowid``
    increases with insertion, which is the true order they happened.
    """
    query = "SELECT * FROM notifications"
    params: list[Any] = []
    if unread_only:
        query += " WHERE read = 0"
    query += " ORDER BY created_at DESC, rowid DESC LIMIT ?"
    params.append(max(1, min(limit, 500)))
    with connection() as conn:
        rows = conn.execute(query, params).fetchall()
    return [Notification.from_row(r) for r in rows]


def unread_notification_count() -> int:
    """How many notifications the user has not read yet."""
    with connection() as conn:
        row = conn.execute("SELECT COUNT(*) FROM notifications WHERE read = 0").fetchone()
    return int(row[0])


def get_notification(notification_id: str) -> Notification | None:
    with connection() as conn:
        row = conn.execute(
            "SELECT * FROM notifications WHERE id = ?", (notification_id,)
        ).fetchone()
    return Notification.from_row(row) if row else None


def mark_notification_read(notification_id: str) -> bool:
    """Mark one notification read. Returns False when the id is unknown."""
    with connection() as conn:
        cursor = conn.execute("UPDATE notifications SET read = 1 WHERE id = ?", (notification_id,))
    return cursor.rowcount > 0


def mark_all_notifications_read() -> int:
    """Mark every unread notification read. Returns how many changed."""
    with connection() as conn:
        cursor = conn.execute("UPDATE notifications SET read = 1 WHERE read = 0")
    return cursor.rowcount


def delete_notification(notification_id: str) -> bool:
    """Remove one notification. Returns False when the id is unknown."""
    with connection() as conn:
        cursor = conn.execute("DELETE FROM notifications WHERE id = ?", (notification_id,))
    return cursor.rowcount > 0


def clear_read_notifications() -> int:
    """Remove every read notification, keeping the unread inbox intact."""
    with connection() as conn:
        cursor = conn.execute("DELETE FROM notifications WHERE read = 1")
    return cursor.rowcount


def prune_notifications(keep: int = 500) -> int:
    """Trim the inbox to the newest ``keep`` rows. Returns how many went."""
    with connection() as conn:
        cursor = conn.execute(
            "DELETE FROM notifications WHERE rowid NOT IN ("
            "  SELECT rowid FROM notifications ORDER BY created_at DESC, rowid DESC LIMIT ?"
            ")",
            (max(1, keep),),
        )
    return cursor.rowcount
