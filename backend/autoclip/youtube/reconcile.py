"""Looking for an upload that may have succeeded anyway.

An upload can succeed and the answer can be lost. The last chunk
arrives, YouTube creates the video, and the connection drops before the
response is read — or the process is killed between the transfer and
the row being written. The row then says "failed" while YouTube has the
video.

Retrying blindly would publish the clip twice. So before a retry, the
status is reconciled, and the evidence is graded:

**confirmed**
    YouTube itself says the upload is finished and names the video.
    This comes from the upload session, which is YouTube's own record
    of that particular transfer. It is a confirmation.

**evidence**
    A video on the destination channel has the same title and was
    published in the right window. That is a strong hint and nothing
    more: a title can repeat, a video can be renamed, and a clock can
    disagree. It is *evidence*, and it never marks the upload
    successful on its own.

**not_uploaded**
    The session says the transfer did not finish, and the channel shows
    no candidate. Safe to retry.

**unknown**
    The lookup itself failed. The upload may or may not have happened,
    so it is not retried blindly either.

Anything that is not a confirmation leaves the upload needing the
owner's eyes. It is never reported as published, and it is never
retried on AutoClip's own judgement.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from typing import Any

import httpx

from .. import config
from ..db.models import YouTubeUpload
from . import oauth, quota, resumable

log = logging.getLogger(__name__)

__all__ = [
    "CONFIRMED",
    "EVIDENCE",
    "NOT_UPLOADED",
    "UNKNOWN",
    "Reconciliation",
    "reconcile",
]

#: YouTube confirmed the upload and named the video.
CONFIRMED = "confirmed"

#: Something on the channel looks like this upload. Evidence, not proof.
EVIDENCE = "evidence"

#: The upload did not happen. Safe to retry.
NOT_UPLOADED = "not_uploaded"

#: The lookup failed. The upload may or may not have happened.
UNKNOWN = "unknown"

_CHANNELS_URL = "https://www.googleapis.com/youtube/v3/channels"
_PLAYLIST_ITEMS_URL = "https://www.googleapis.com/youtube/v3/playlistItems"

#: How many of the channel's recent uploads are looked at. The window
#: is short on purpose — a video from last month is not this upload.
_RECENT_ITEMS = 25

#: How far before the row was queued a matching video may have been
#: published and still count as a candidate. It covers the clock
#: difference between this machine and YouTube's.
_CLOCK_TOLERANCE = timedelta(minutes=10)


@dataclass(frozen=True)
class Reconciliation:
    """What we found when we went looking for the upload."""

    #: One of CONFIRMED, EVIDENCE, NOT_UPLOADED or UNKNOWN.
    status: str = UNKNOWN
    #: The video id, when there is one.
    video_id: str = ""
    #: The title of the candidate.
    title: str = ""
    #: The privacy YouTube reports, when it was confirmed.
    actual_privacy: str = ""
    #: The channel the candidate is on.
    channel_id: str = ""
    #: How we looked: 'session', 'channel' or 'none'.
    method: str = "none"
    #: A sentence for the owner.
    detail: str = ""
    #: Every candidate we found, for the owner to choose between.
    candidates: tuple[dict[str, Any], ...] = field(default_factory=tuple)

    @property
    def confirmed(self) -> bool:
        """True only when YouTube itself confirmed the upload."""
        return self.status == CONFIRMED

    @property
    def needs_owner(self) -> bool:
        """True when the upload cannot be settled without the owner."""
        return self.status in (EVIDENCE, UNKNOWN)

    def to_dict(self) -> dict[str, Any]:
        return {
            "status": self.status,
            "video_id": self.video_id,
            "title": self.title,
            "actual_privacy": self.actual_privacy,
            "channel_id": self.channel_id,
            "method": self.method,
            "detail": self.detail,
            "candidates": [dict(candidate) for candidate in self.candidates],
        }


def _parse_time(value: str) -> datetime | None:
    """Parse an ISO-8601 timestamp, tolerating a missing offset."""
    if not value:
        return None
    try:
        when = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None
    if when.tzinfo is None:
        when = when.replace(tzinfo=UTC)
    return when


def _expected_titles(upload: YouTubeUpload, title_suffix: str = "") -> list[str]:
    """The titles this upload could have gone out under.

    The channel's suffix is appended to the title just before the
    upload, so both forms have to be considered.
    """
    titles: list[str] = []
    base = (upload.title or "").strip()
    if base:
        titles.append(base)
        if title_suffix and not base.endswith(title_suffix):
            titles.append(f"{base} {title_suffix}".strip())
    return titles


def _via_session(
    upload: YouTubeUpload,
    token: str,
    total_bytes: int,
) -> Reconciliation | None:
    """Ask the upload session whether the transfer finished.

    The session is YouTube's own record of this transfer, so a finished
    session with a video id is a confirmation. A session that says
    "308, I have this many bytes" is YouTube saying the upload did not
    finish, which is just as useful.

    ``None`` means the session could not answer — it is gone, or the
    request failed — and the caller should try another way.
    """
    if not upload.session_url:
        return None
    try:
        result = resumable.probe_session(
            session_url=upload.session_url,
            token=token,
            total_bytes=total_bytes or upload.total_bytes,
        )
    except resumable.SessionGone:
        log.info("The upload session for %s is gone; looking elsewhere.", upload.id)
        return None
    except resumable.ResumableError as exc:
        log.warning("Could not ask YouTube about upload %s: %s", upload.id, exc)
        return None

    if result.complete:
        resource = result.resource
        video_id = str(resource.get("id", ""))
        if not video_id:
            # The session says it is finished but names no video. That
            # is not a confirmation, so it is not treated as one.
            return Reconciliation(
                status=UNKNOWN,
                method="session",
                detail="YouTube says the upload finished but returned no video id.",
            )
        status = resource.get("status")
        privacy = ""
        if isinstance(status, dict):
            privacy = str(status.get("privacyStatus", ""))
        return Reconciliation(
            status=CONFIRMED,
            video_id=video_id,
            title=str(resource.get("title", "") or upload.title),
            actual_privacy=privacy,
            channel_id=str(resource.get("channelId", "")),
            method="session",
            detail=f"YouTube confirms the upload as video {video_id}.",
        )

    return Reconciliation(
        status=NOT_UPLOADED,
        method="session",
        detail=(
            f"YouTube has {result.bytes_received} of {total_bytes or upload.total_bytes} "
            "bytes, so the upload did not finish."
        ),
    )


def _channel_uploads_playlist(token: str, channel_id: str) -> str:
    """The id of the channel's uploads playlist."""
    response = httpx.get(
        _CHANNELS_URL,
        params={"part": "contentDetails", "id": channel_id},
        headers={"Authorization": f"Bearer {token}"},
        timeout=30.0,
    )
    response.raise_for_status()
    payload = response.json()
    items = payload.get("items") if isinstance(payload, dict) else None
    if not isinstance(items, list) or not items:
        return ""
    details = items[0].get("contentDetails") if isinstance(items[0], dict) else None
    if not isinstance(details, dict):
        return ""
    related = details.get("relatedPlaylists")
    if not isinstance(related, dict):
        return ""
    return str(related.get("uploads", ""))


def _recent_uploads(token: str, playlist_id: str) -> list[dict[str, Any]]:
    """The channel's most recent uploads, newest first."""
    response = httpx.get(
        _PLAYLIST_ITEMS_URL,
        params={
            "part": "snippet",
            "playlistId": playlist_id,
            "maxResults": _RECENT_ITEMS,
        },
        headers={"Authorization": f"Bearer {token}"},
        timeout=30.0,
    )
    response.raise_for_status()
    payload = response.json()
    items = payload.get("items") if isinstance(payload, dict) else None
    if not isinstance(items, list):
        return []
    uploads: list[dict[str, Any]] = []
    for item in items:
        if not isinstance(item, dict):
            continue
        snippet = item.get("snippet")
        if not isinstance(snippet, dict):
            continue
        resource = snippet.get("resourceId")
        video_id = ""
        if isinstance(resource, dict):
            video_id = str(resource.get("videoId", ""))
        if not video_id:
            continue
        uploads.append(
            {
                "video_id": video_id,
                "title": str(snippet.get("title", "")),
                "published_at": str(snippet.get("publishedAt", "")),
            }
        )
    return uploads


def _via_channel(
    upload: YouTubeUpload,
    token: str,
    channel_id: str,
    title_suffix: str = "",
) -> Reconciliation:
    """Look for the upload on the destination channel.

    A title match inside the right window is evidence. It is never a
    confirmation, because a title can repeat and a video can be
    renamed — so a candidate leaves the upload needing the owner.
    """
    if not channel_id:
        return Reconciliation(
            status=UNKNOWN,
            method="channel",
            detail="The destination channel is not known, so the upload cannot be looked for.",
        )

    expected = _expected_titles(upload, title_suffix)
    if not expected:
        return Reconciliation(
            status=UNKNOWN,
            method="channel",
            detail="This upload has no title yet, so there is nothing to match against.",
        )

    try:
        playlist_id = _channel_uploads_playlist(token, channel_id)
        if not playlist_id:
            return Reconciliation(
                status=UNKNOWN,
                method="channel",
                detail="YouTube did not report an uploads playlist for that channel.",
            )
        uploads = _recent_uploads(token, playlist_id)
    except httpx.HTTPError as exc:
        log.warning("Could not look for upload %s on the channel: %s", upload.id, exc)
        return Reconciliation(
            status=UNKNOWN,
            method="channel",
            detail=f"The lookup failed: {exc}",
        )
    except ValueError:
        return Reconciliation(
            status=UNKNOWN,
            method="channel",
            detail="YouTube sent a response that could not be read.",
        )

    quota.record_read()

    queued_at = _parse_time(upload.created_at)
    floor = queued_at - _CLOCK_TOLERANCE if queued_at else None
    candidates: list[dict[str, Any]] = []
    for item in uploads:
        if item["title"] not in expected:
            continue
        published = _parse_time(item["published_at"])
        if floor is not None and published is not None and published < floor:
            continue
        candidates.append(item)

    if not candidates:
        return Reconciliation(
            status=NOT_UPLOADED,
            method="channel",
            channel_id=channel_id,
            detail=(
                f"There is no video titled “{expected[0]}” among the channel's "
                "recent uploads, so the upload did not happen."
            ),
        )

    first = candidates[0]
    if len(candidates) == 1:
        detail = (
            f"There is a video titled “{first['title']}” on the channel that may be "
            "this upload. A matching title is evidence, not proof, so it has not "
            "been marked as published."
        )
    else:
        detail = (
            f"There are {len(candidates)} videos titled “{first['title']}” on the "
            "channel. Which one is this upload is not something AutoClip can "
            "decide, so it has not been marked as published."
        )
    return Reconciliation(
        status=EVIDENCE,
        video_id=first["video_id"],
        title=first["title"],
        channel_id=channel_id,
        method="channel",
        detail=detail,
        candidates=tuple(candidates),
    )


def reconcile(
    upload: YouTubeUpload,
    settings: config.Settings | None = None,
    *,
    account_id: str | None = None,
    channel_id: str = "",
    title_suffix: str = "",
    total_bytes: int = 0,
) -> Reconciliation:
    """Find out whether an upload that may have succeeded actually did.

    The session is asked first, because it is YouTube's own record of
    the transfer. The channel is asked only when the session cannot
    answer.
    """
    settings = settings or config.load()
    try:
        token = oauth.access_token(settings, account_id=account_id)
    except oauth.OAuthError as exc:
        log.warning("Could not reconcile upload %s: %s", upload.id, exc)
        return Reconciliation(
            status=UNKNOWN,
            detail="The channel sign-in could not be used, so the upload could not be checked.",
        )

    from_session = _via_session(upload, token, total_bytes)
    if from_session is not None:
        if from_session.status == NOT_UPLOADED and not upload.session_url:
            # The session answered and the upload did not finish. That
            # is YouTube's own word, so no channel search is needed.
            return from_session
        if from_session.confirmed or from_session.status == NOT_UPLOADED:
            return from_session
        # The session could not answer; try the channel.

    return _via_channel(upload, token, channel_id, title_suffix)
