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
from typing import Any

from .. import config
from ..db import store
from ..db.models import YouTubeUpload, new_id, utcnow
from ..pipeline import thumbnails
from ..pipeline.transcript import Transcript, Word
from ..providers import LLMProvider, build_provider
from ..providers.base import looks_like_auth_failure
from . import duplicates, oauth, quota, uploader
from . import metadata as metadata_module
from . import policy as policy_module
from . import reconcile as reconcile_module

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


def _reconcile(
    upload: YouTubeUpload,
    settings: config.Settings,
    account_id: str | None,
    channel: dict | None,
    path: Path,
) -> str | None:
    """Settle an upload that may have succeeded, before sending it again.

    Returns the video id when the upload is confirmed — in which case
    nothing is sent again — and ``None`` when it is safe to carry on
    with the upload.

    Anything that cannot be settled raises
    :class:`uploader.YouTubeError`, and the row is left as
    ``needs_reconciliation``: the owner decides, not AutoClip.
    """
    channel_id = (channel or {}).get("channel_id", "")
    suffix = (channel or {}).get("title_suffix", "")
    total_bytes = 0
    try:
        total_bytes = path.stat().st_size
    except OSError:
        total_bytes = upload.total_bytes

    outcome = reconcile_module.reconcile(
        upload,
        settings,
        account_id=account_id,
        channel_id=channel_id,
        title_suffix=suffix,
        total_bytes=total_bytes,
    )

    store.update_upload(
        upload.id,
        reconcile_status=outcome.status,
        reconcile_detail=outcome.detail,
        reconciled_at=utcnow(),
    )

    if outcome.confirmed:
        # YouTube confirmed it. The upload is recorded, not repeated.
        log.info("Upload %s was already on YouTube as %s.", upload.id, outcome.video_id)
        store.update_upload(
            upload.id,
            video_id=outcome.video_id,
            actual_privacy=outcome.actual_privacy,
            session_url="",
            bytes_sent=0,
            next_attempt_at="",
        )
        return outcome.video_id

    if outcome.needs_owner:
        # There is a candidate, or the lookup itself failed. Either way
        # AutoClip does not know whether the upload succeeded, and a
        # blind retry could publish the clip twice.
        raise uploader.YouTubeError(
            outcome.detail
            or "It is not clear whether this upload reached YouTube, so it has not "
            "been sent again.",
            hint=(
                "Open YouTube and check whether the clip is there. If it is, mark the "
                "upload as done; if it is not, retry it."
            ),
            needs_reconciliation=True,
        )

    # Not uploaded: the session says the transfer did not finish. The
    # stale session is dropped and the file is sent again.
    if outcome.status == reconcile_module.NOT_UPLOADED and upload.session_url:
        store.update_upload(upload.id, session_url="", bytes_sent=0)
    return None


def confirm_upload(
    upload_id: str,
    video_id: str,
    settings: config.Settings | None = None,
) -> YouTubeUpload | None:
    """The owner says the upload is on YouTube. Verify it, then record it.

    The owner's word is not enough on its own — a row that claims to be
    published when the video is not there is a lie. So the video is
    asked about, and only a video YouTube confirms is recorded.

    Returns the updated row, or ``None`` when the row does not exist.
    Raises :class:`uploader.YouTubeError` when YouTube cannot confirm
    the video.
    """
    settings = settings or config.load()
    upload = store.get_upload(upload_id)
    if upload is None:
        return None

    account_id: str | None = None
    if upload.channel_row_id:
        from ..youtube import accounts as accounts_store

        channel = accounts_store.get_channel(upload.channel_row_id)
        if channel is None:
            raise uploader.YouTubeError("The destination channel for this upload no longer exists.")
        account_id = channel["account_id"]

    outcome = uploader.read_back(settings, video_id=video_id, account_id=account_id)
    if not outcome.found:
        raise uploader.YouTubeError(
            f"YouTube could not confirm that video {video_id} exists.",
            hint=(
                "Check the video id in the YouTube URL. If the video really is there, "
                "paste the id from the end of the address bar."
            ),
        )

    store.update_upload(
        upload.id,
        status="done",
        video_id=video_id,
        actual_privacy=outcome.actual_privacy,
        destination_channel_id=outcome.channel_id or upload.destination_channel_id,
        reconcile_status="confirmed_by_owner",
        reconcile_detail=f"The owner confirmed video {video_id}.",
        reconciled_at=utcnow(),
        session_url="",
        bytes_sent=0,
        next_attempt_at="",
        clear_error=True,
    )
    return store.get_upload(upload.id)


def retry_upload(
    upload_id: str,
    settings: config.Settings | None = None,
    *,
    force: bool = False,
) -> YouTubeUpload | None:
    """Put a failed upload back in the queue.

    The row keeps **its own** privacy. It used to re-read the current
    setting or the channel's current privacy and write that over the
    row, which meant a retry could publish a video under a different
    privacy than the one the owner was shown when the upload was
    queued. A privacy change is a decision, and a decision is made in
    the UI rather than by a retry.
    """
    settings = settings or config.load()
    upload = store.get_upload(upload_id)
    if upload is None:
        return None
    if upload.status == "done":
        return upload
    fields: dict[str, Any] = {
        "status": "pending",
        "clear_error": True,
        "next_attempt_at": "",
    }
    if upload.status == "needs_reconciliation":
        # The owner has looked at YouTube and asked for it to be sent.
        # Their decision replaces AutoClip's caution — and the record
        # says that is how it was decided, so it is not mistaken for an
        # automatic retry.
        fields["reconcile_status"] = "owner_retried"
        fields["reconcile_detail"] = (
            "The owner checked YouTube and asked for this upload to be sent again."
        )
        fields["reconciled_at"] = utcnow()
        fields["session_url"] = ""
        fields["bytes_sent"] = 0
    store.update_upload(upload.id, **fields)
    return store.get_upload(upload.id)


async def process_upload(upload: YouTubeUpload, settings: config.Settings | None = None) -> str:
    """Generate metadata, upload the file, and return the video id.

    Raises :class:`uploader.YouTubeError` (or ``oauth.OAuthError``) for the
    worker to record against the row.

    The publishing policy is resolved before the network call and written
    onto the row, so the record of what was intended exists even if the
    transfer fails halfway. After the upload, YouTube is asked what it
    actually did — a video that was asked to be public but came back
    private is reported as private, not as published.
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

    # Phase 10: the row already names its channel (fan-out created it), so the
    # worker publishes to exactly that destination instead of re-routing.
    # Resolved first because metadata generation uses the channel's note.
    channel: dict | None = None
    if upload.channel_row_id:
        from ..youtube import accounts as accounts_store

        channel = accounts_store.get_channel(upload.channel_row_id)
        if channel is None:
            raise uploader.YouTubeError(
                "The destination channel for this upload no longer exists. "
                "Reconnect the channel or delete the upload."
            )
    else:
        # Legacy path: no channel profile, fall back to rule routing.
        try:
            from ..routing import resolve_target_channel

            channel = resolve_target_channel(clip.id, settings)
        except Exception:  # noqa: BLE001 - routing must never block publishing
            log.warning("Channel routing failed; using the default destination.", exc_info=True)
            channel = None

    # The policy is the owner's decision, not AutoClip's: an unanswered
    # audience declaration stops the upload here rather than being guessed.
    policy = policy_module.resolve(
        channel,
        settings,
        audience_override=upload.made_for_kids,
    )
    # The row's own privacy wins over the channel's current one: the owner
    # was shown this privacy when the upload was queued.
    privacy = upload.privacy or policy.privacy
    category_id = policy.category_id
    account_id: str | None = policy.account_id or None

    # A previous attempt may have succeeded with the answer lost. Before
    # sending anything again, find out whether it did — a blind retry
    # would publish the clip twice. An owner who has already checked
    # YouTube and asked for it to be sent has settled that themselves.
    if upload.reconcile_status != "owner_retried" and (upload.attempts > 0 or upload.session_url):
        settled = _reconcile(upload, settings, account_id, channel, path)
        if settled is not None:
            return settled

    words, language = clip_words(clip)
    generated = await _metadata(
        upload,
        clip,
        words,
        language,
        settings,
        channel_id=(channel or {}).get("channel_id", ""),
    )
    if not generated.title:
        raise uploader.YouTubeError("The generated title was empty; nothing was uploaded.")

    if upload.channel_row_id and channel is not None:
        suffix = channel.get("title_suffix") or ""
        if suffix and not generated.title.endswith(suffix):
            generated.title = f"{generated.title} {suffix}".strip()
        # The row records the title that is actually sent, so a later
        # lookup for this upload can match it.
        store.update_upload(upload.id, title=generated.title)

    # Record the decision before the network call, so a transfer that dies
    # halfway still leaves the record of what was asked for.
    store.update_upload(
        upload.id,
        privacy=privacy,
        made_for_kids=policy.made_for_kids_state,
        requested_privacy=privacy,
        destination_channel_id=policy.destination_channel_id,
    )

    # The upload costs 1600 quota units, and the default daily quota is
    # 10 000 — six uploads. The units are reserved before the call, so
    # a retry loop cannot quietly eat the day's quota.
    quota.reserve(quota.UPLOAD_UNITS)

    def progress(sent: int, total: int) -> None:
        """Write the byte count after every chunk.

        The progress shown in the UI is this number, so it is the real
        one rather than a spinner.
        """
        store.update_upload(upload.id, bytes_sent=sent, total_bytes=total)

    def session_started(url: str, expires_at: str) -> None:
        """Keep the session handle, so the upload can be continued.

        A session that is not stored cannot be resumed, and an upload
        that dropped at 90% would have to start again.
        """
        store.update_upload(
            upload.id,
            session_url=url,
            session_expires_at=expires_at,
            total_bytes=path.stat().st_size,
        )

    video_id = await asyncio.to_thread(
        uploader.upload_video,
        settings,
        path=path,
        metadata=generated,
        privacy=privacy,
        made_for_kids=policy.made_for_kids,
        category_id=category_id,
        language=language,
        account_id=account_id,
        session_url=upload.session_url,
        bytes_sent=upload.bytes_sent,
        session_expires_at=upload.session_expires_at,
        on_progress=progress,
        on_session=session_started,
    )
    quota.record_upload_finished()

    # Ask YouTube what it actually did. The upload has already happened, so
    # a failure to read it back is not a failure of the upload — it just
    # means the actual privacy is unknown.
    outcome = await asyncio.to_thread(
        uploader.read_back,
        settings,
        video_id=video_id,
        account_id=account_id,
    )
    if outcome.found:
        store.update_upload(
            upload.id,
            actual_privacy=outcome.actual_privacy,
            destination_channel_id=outcome.channel_id or policy.destination_channel_id,
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
    channel_id: str = "",
) -> metadata_module.ClipMetadata:
    """Use stored metadata when it exists; otherwise ask the model.

    ``channel_id`` (the destination channel's UC_… id) selects that channel's
    learning note so per-channel title preferences apply.
    """
    if upload.title and upload.description:
        return metadata_module.ClipMetadata(
            title=upload.title, description=upload.description, tags=list(upload.tags)
        )

    title, hook, reason = clip.title, clip.hook, clip.reason
    provider = _build_provider(settings)
    generated: metadata_module.ClipMetadata | None = None
    try:
        generated = await _ask(
            provider,
            title,
            hook,
            reason,
            words,
            clip.duration_s,
            language,
            channel_id=channel_id,
        )
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
                    channel_id=channel_id,
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
    channel_id: str = "",
) -> metadata_module.ClipMetadata:
    return await metadata_module.generate_metadata(
        provider,
        title=title,
        hook=hook,
        reason=reason,
        words=words,
        duration_s=duration_s,
        language=language,
        channel_id=channel_id,
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
