"""Turning a finished export into a YouTube upload.

Two entry points:

``enqueue_export`` runs at the end of every successful export. It is a no-op
unless the user turned automation on and has a channel connected, so exporting
while the toggle is off never queues work.

``process_upload`` is called by the worker. It generates the metadata once and
stores it before the network call, so a retry after a failed transfer reuses the
same title/description/tags instead of paying for another model pass.
"""

from __future__ import annotations

import asyncio
import logging
from pathlib import Path

from .. import config
from ..db import store
from ..db.models import YouTubeUpload, new_id
from ..pipeline import thumbnails
from ..pipeline.transcript import Transcript, Word
from ..providers import LLMProvider, build_provider
from ..providers.base import looks_like_auth_failure
from . import duplicates, oauth, uploader
from . import metadata as metadata_module

log = logging.getLogger(__name__)


class DuplicateUploadError(uploader.YouTubeError):
    """This row would put a clip on YouTube that is already there."""


def enqueue_export(export_id: str, settings: config.Settings | None = None) -> YouTubeUpload | None:
    """Queue uploads for ``export_id`` and return the first row, if any.

    Kept for callers that only need a yes/no plus a row to report; the full
    fan-out is :func:`enqueue_export_all`.
    """
    rows = enqueue_export_all(export_id, settings)
    return rows[0] if rows else None


def enqueue_export_all(
    export_id: str, settings: config.Settings | None = None
) -> list[YouTubeUpload]:
    """Queue one upload per target channel for ``export_id``.

    Routing rules decide the channels; when there are no channel profiles the
    legacy single-row behaviour (``channel_row_id = ''``) is used so existing
    installs keep working. Never raises: an upload problem must not fail a
    pipeline that has already produced a perfectly good file.
    """
    try:
        settings = settings or config.load()
        if not settings.youtube.auto_upload:
            return []
        if not oauth.is_connected(settings):
            return []

        export = store.get_export(export_id)
        if export is None:
            log.warning("Cannot enqueue upload: export %s is missing.", export_id)
            return []

        # Phase 9: a clip that failed validation is never published.
        try:
            clip = store.get_clip(export.clip_id)
        except Exception:  # a lookup failure must not block an otherwise valid upload
            log.debug("Could not read clip %s for upload gating.", export.clip_id, exc_info=True)
            clip = None
        if clip is not None and clip.status == "invalid":
            log.warning("Not queueing upload for invalid clip %s.", clip.id)
            return []

        try:
            from ..routing import resolve_target_channels

            targets = resolve_target_channels(export.clip_id, settings)
        except Exception:  # routing must never block publishing
            log.warning("Channel routing failed; using the default destination.", exc_info=True)
            targets = []

        if not targets:
            row = store.create_upload(
                YouTubeUpload(
                    id=new_id(),
                    export_id=export.id,
                    clip_id=export.clip_id,
                    privacy=settings.youtube.privacy,
                )
            )
            log.info("Queued YouTube upload %s for export %s.", row.id, export_id)
            return [row]

        rows: list[YouTubeUpload] = []
        for channel in targets:
            row = store.create_upload(
                YouTubeUpload(
                    id=new_id(),
                    export_id=export.id,
                    clip_id=export.clip_id,
                    channel_row_id=channel["id"],
                    privacy=channel.get("privacy") or settings.youtube.privacy,
                )
            )
            rows.append(row)
            log.info(
                "Queued YouTube upload %s for export %s to channel %s.",
                row.id,
                export_id,
                channel.get("channel_id", channel["id"]),
            )
        return rows
    except Exception:  # pragma: no cover - defensive
        log.exception("Could not queue a YouTube upload for %s.", export_id)
        return []


def retry_upload(upload_id: str, settings: config.Settings | None = None) -> YouTubeUpload | None:
    """Put a failed upload back in the queue.

    A channel fan-out row keeps its own channel's privacy; only the legacy
    default-channel row re-reads the global setting.
    """
    settings = settings or config.load()
    upload = store.get_upload(upload_id)
    if upload is None:
        return None
    if upload.status == "done":
        return upload
    privacy = settings.youtube.privacy
    if upload.channel_row_id:
        from . import accounts as accounts_store

        channel = accounts_store.get_channel(upload.channel_row_id)
        if channel is not None:
            privacy = channel["privacy"]
    store.update_upload(
        upload.id,
        status="pending",
        privacy=privacy,
        clear_error=True,
    )
    return store.get_upload(upload.id)


async def process_upload(upload: YouTubeUpload, settings: config.Settings | None = None) -> str:
    """Generate metadata, upload the file, and return the video id.

    Raises :class:`uploader.YouTubeError` (or ``oauth.OAuthError``) for the
    worker to record against the row.
    """
    settings = settings or config.load()
    export = store.get_export(upload.export_id)
    if export is None:
        raise uploader.YouTubeError("The export this upload belongs to no longer exists.")

    path = Path(export.path)
    if not path.is_file():
        raise uploader.YouTubeError(
            "The exported file has been moved or deleted. Export the clip again."
        )

    clip = store.get_clip(export.clip_id)
    if clip is None:
        raise uploader.YouTubeError("The clip this upload belongs to no longer exists.")

    conflict = duplicates.conflict_for(upload)
    if conflict is not None:
        reference = conflict.video_id or conflict.id
        raise DuplicateUploadError(
            "Skipped as a duplicate: this clip is already queued or published "
            f"as upload {reference}."
        )

    words, language = clip_words(clip)
    generated = await _metadata(upload, clip, words, language, settings)
    if not generated.title:
        raise uploader.YouTubeError("The generated title was empty; nothing was uploaded.")

    # Phase 10: the row already names its channel (fan-out created it), so the
    # worker publishes to exactly that destination instead of re-routing.
    privacy = upload.privacy or settings.youtube.privacy
    category_id = settings.youtube.category_id
    account_id: str | None = None
    channel: dict | None = None
    if upload.channel_row_id:
        from ..youtube import accounts as accounts_store

        channel = accounts_store.get_channel(upload.channel_row_id)
        if channel is None:
            raise uploader.YouTubeError(
                "The destination channel for this upload no longer exists. "
                "Reconnect the channel or delete the upload."
            )
        privacy = upload.privacy or channel["privacy"]
        category_id = channel["category_id"]
        account_id = channel["account_id"]
        suffix = channel.get("title_suffix") or ""
        if suffix and not generated.title.endswith(suffix):
            generated.title = f"{generated.title} {suffix}".strip()
    else:
        # Legacy path: no channel profile, fall back to rule routing.
        try:
            from ..routing import resolve_target_channel

            channel = resolve_target_channel(clip.id, settings)
        except Exception:  # noqa: BLE001 - routing must never block publishing
            log.warning("Channel routing failed; using the default destination.", exc_info=True)
            channel = None
        if channel is not None:
            privacy = upload.privacy or channel["privacy"]
            category_id = channel["category_id"]
            account_id = channel["account_id"]

    video_id = await asyncio.to_thread(
        uploader.upload_video,
        settings,
        path=path,
        metadata=generated,
        privacy=privacy,
        category_id=category_id,
        language=language,
        account_id=account_id,
    )

    # The video is already published at this point, so a thumbnail problem is
    # logged and swallowed: a missing thumbnail must never undo a good upload.
    thumbnail = _thumbnail_for(path, clip)
    if thumbnail is not None:
        try:
            await asyncio.to_thread(
                uploader.set_thumbnail,
                settings,
                video_id=video_id,
                path=thumbnail,
                account_id=account_id,
            )
        except Exception as exc:
            log.warning("Upload %s published, but its thumbnail failed: %s", upload.id, exc)

    return video_id


def _thumbnail_for(export_path: Path, clip) -> Path | None:
    """Return the thumbnail for an export, rendering one if it is missing.

    Rendering here rather than at export time keeps the export stage free of
    YouTube concerns and still gives every published clip a thumbnail.
    """
    target = thumbnails.thumbnail_path_for(export_path)
    if target.is_file():
        return target

    eyebrow = ""
    job = store.get_job(clip.job_id)
    if job is not None:
        source = store.get_source(job.source_id)
        if source is not None:
            eyebrow = source.title

    try:
        return thumbnails.render_thumbnail(
            export_path,
            title=clip.title or "Highlight clip",
            eyebrow=eyebrow,
            output=target,
        )
    except Exception as exc:
        log.warning("Could not render a thumbnail for %s: %s", export_path.name, exc)
        return None


def clip_words(clip) -> tuple[list[Word], str]:
    """Read the clip's own subtitle slice, falling back to an empty list."""
    transcript_record = store.get_transcript(clip.job_id)
    if transcript_record is None:
        return [], ""
    try:
        transcript = Transcript.load(Path(transcript_record.json_path))
    except (OSError, ValueError) as exc:
        log.warning("Could not read the transcript for job %s: %s", clip.job_id, exc)
        return [], transcript_record.language or ""

    return transcript.slice(clip.start_word, clip.end_word), (
        transcript.language or transcript_record.language or ""
    )


async def _metadata(
    upload: YouTubeUpload,
    clip,
    words: list[Word],
    language: str,
    settings: config.Settings,
) -> metadata_module.ClipMetadata:
    """Use stored metadata when it exists; otherwise ask the model."""
    if upload.title and upload.description:
        return metadata_module.ClipMetadata(
            title=upload.title, description=upload.description, tags=list(upload.tags)
        )

    title, hook, reason = clip.title, clip.hook, clip.reason
    provider = _build_provider(settings)
    generated: metadata_module.ClipMetadata | None = None
    try:
        generated = await _ask(provider, title, hook, reason, words, clip.duration_s, language)
    except Exception as exc:  # metadata must never block the upload
        log.warning("Metadata generation failed (%s).", exc)
        if settings.active_provider != "ollama" and looks_like_auth_failure(exc):
            try:
                generated = await _ask(
                    build_provider("ollama", settings),
                    title,
                    hook,
                    reason,
                    words,
                    clip.duration_s,
                    language,
                )
            except Exception as fallback_exc:
                log.warning("The Ollama metadata fallback failed too (%s).", fallback_exc)

    if generated is None:
        generated = metadata_module.fallback_metadata(
            title=title, hook=hook, reason=reason, words=words, duration_s=clip.duration_s
        )

    store.update_upload(
        upload.id,
        title=generated.title,
        description=generated.description,
        tags=generated.tags,
    )
    return generated


async def _ask(
    provider: LLMProvider,
    title: str,
    hook: str,
    reason: str,
    words: list[Word],
    duration_s: float,
    language: str,
) -> metadata_module.ClipMetadata:
    return await metadata_module.generate_metadata(
        provider,
        title=title,
        hook=hook,
        reason=reason,
        words=words,
        duration_s=duration_s,
        language=language,
    )


def _build_provider(settings: config.Settings) -> LLMProvider:
    """The active provider, or local Ollama when its API key was rejected."""
    name = settings.active_provider
    try:
        return build_provider(name, settings)
    except Exception as exc:
        if not looks_like_auth_failure(exc) or name == "ollama":
            raise
        log.warning("Provider %s is unusable (%s); using Ollama.", name, exc)
        return build_provider("ollama", settings)
