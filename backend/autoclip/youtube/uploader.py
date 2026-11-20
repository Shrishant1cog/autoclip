"""Resumable upload to YouTube's Data API v3.

Two requests: a JSON metadata POST that returns a resumable session URL, then a
single PUT of the rendered file to that URL. httpx streams the file, so an
80 MB export never sits in memory.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import httpx

from .. import config
from ..security import consent
from ..security.egress import Transfer, gateway
from ..security.urlpolicy import UrlRejected
from . import oauth
from .metadata import ClipMetadata

log = logging.getLogger(__name__)

UPLOAD_URL = "https://www.googleapis.com/upload/youtube/v3/videos"
THUMBNAIL_URL = "https://www.googleapis.com/upload/youtube/v3/thumbnails/set"

#: Uploads are large and home upload speeds are slow; the read timeout covers
#: the body transfer, not just the connection.
_UPLOAD_TIMEOUT = httpx.Timeout(1800.0, connect=30.0, write=300.0)


class YouTubeError(RuntimeError):
    """The upload was rejected by YouTube."""

    def __init__(self, message: str, *, hint: str = "") -> None:
        super().__init__(message)
        self.hint = hint

    def __str__(self) -> str:
        base = super().__str__()
        return f"{base}\n\n{self.hint}" if self.hint else base


def upload_video(
    settings: config.Settings,
    *,
    path: Path,
    metadata: ClipMetadata,
    privacy: str,
    made_for_kids: bool,
    category_id: str = "24",
    language: str = "",
    account_id: str | None = None,
) -> str:
    """Upload one file and return its YouTube video id.

    ``made_for_kids`` is required, and it is the owner's answer rather
    than a default. It used to be hard-coded to ``False``, which meant
    AutoClip made a legal declaration on the owner's behalf. The
    declaration is resolved by :mod:`autoclip.youtube.policy`, which
    refuses to resolve one that has not been answered.
    """
    if not path.is_file():
        raise YouTubeError(f"The exported file is missing: {path}")

    token = oauth.access_token(settings, account_id=account_id)

    snippet: dict[str, object] = {
        "title": metadata.title,
        "description": metadata.description,
        "tags": metadata.tags,
        "categoryId": category_id or "24",
    }
    if language and len(language) == 2 and language.isalpha():
        snippet["defaultLanguage"] = language.lower()

    body = {
        "snippet": snippet,
        "status": {
            "privacyStatus": privacy,
            "selfDeclaredMadeForKids": made_for_kids,
        },
    }

    headers = {
        "Authorization": f"Bearer {token}",
        "Content-Type": "application/json; charset=UTF-8",
        "X-Upload-Content-Length": str(path.stat().st_size),
        "X-Upload-Content-Type": "video/mp4",
    }

    # The rendered clip is about to leave the machine. Publishing is an
    # explicit owner action, so it is recorded rather than consent-gated — but
    # it still goes through the gateway, so the destination is classified and
    # the transfer is in the log the user can read.
    transfer = Transfer(
        operation=consent.Operation.PUBLISHING,
        url=UPLOAD_URL,
        data_summary=f"The rendered clip {path.name} and its metadata.",
        provider="youtube",
        requires_consent=False,
    )
    try:
        gateway.authorize(transfer)
    except UrlRejected as exc:
        raise YouTubeError(f"YouTube was refused as a destination: {exc}") from exc

    try:
        init = httpx.post(
            UPLOAD_URL,
            params={"uploadType": "resumable", "part": "snippet,status"},
            json=body,
            headers=headers,
            timeout=60.0,
        )
    except httpx.HTTPError as exc:
        gateway.record(transfer, "failed", detail=str(exc))
        raise YouTubeError(f"Could not reach YouTube: {exc}") from exc

    if init.status_code >= 400:
        gateway.record(transfer, "failed", detail=f"HTTP {init.status_code}")
        raise _translate(init)
    location = init.headers.get("location") or init.headers.get("Location")
    if not location:
        gateway.record(transfer, "failed", detail="no session URL")
        raise YouTubeError("YouTube did not return an upload session URL.")

    size = path.stat().st_size
    try:
        with path.open("rb") as handle:
            response = httpx.put(
                location,
                content=handle,
                headers={
                    "Content-Type": "video/mp4",
                    "Content-Length": str(size),
                },
                timeout=_UPLOAD_TIMEOUT,
            )
    except httpx.HTTPError as exc:
        gateway.record(transfer, "failed", detail=str(exc))
        raise YouTubeError(f"The upload was interrupted: {exc}") from exc

    if response.status_code >= 400:
        gateway.record(transfer, "failed", detail=f"HTTP {response.status_code}")
        raise _translate(response)

    video_id = response.json().get("id", "")
    if not video_id:
        gateway.record(transfer, "failed", detail="no video id in the response")
        raise YouTubeError("YouTube accepted the upload but returned no video id.")
    gateway.record(transfer, "ok")
    log.info("Uploaded %s to YouTube as %s.", path.name, video_id)
    return video_id


@dataclass(frozen=True)
class UploadOutcome:
    """What YouTube says about a video after it has been uploaded.

    This is the difference between *asked for* and *got*. YouTube can
    force a video private — an un-audited API project cannot publish a
    public video — and a row that claims to be public when YouTube made
    it private is a lie that the UI would repeat.
    """

    #: The privacy YouTube reports.
    actual_privacy: str = ""
    #: The channel YouTube says the video is on.
    channel_id: str = ""
    #: The video's title, as YouTube has it.
    title: str = ""
    #: True when the privacy came back as something other than "private".
    found: bool = False

    def is_public(self) -> bool:
        return self.actual_privacy == "public"

    def to_dict(self) -> dict[str, object]:
        return {
            "actual_privacy": self.actual_privacy,
            "channel_id": self.channel_id,
            "title": self.title,
            "found": self.found,
        }


#: The read-back asks for the parts that answer "where did it go and how
#: can people see it".
_VIDEOS_URL = "https://www.googleapis.com/youtube/v3/videos"


def read_back(
    settings: config.Settings,
    *,
    video_id: str,
    account_id: str | None = None,
) -> UploadOutcome:
    """Ask YouTube what it actually did with the upload.

    Two things are checked: the privacy the video ended up with, and the
    channel it is on. A video that was asked to be public but came back
    private is reported as private, and a video that landed on a
    different channel is reported as such. Nothing here fails the upload
    — the upload did happen — so a network error returns an outcome that
    says "not found" rather than raising.
    """
    if not video_id:
        return UploadOutcome()

    try:
        token = oauth.access_token(settings, account_id=account_id)
    except oauth.OAuthError:
        log.warning("Could not read back video %s: no access token.", video_id)
        return UploadOutcome()

    try:
        response = httpx.get(
            _VIDEOS_URL,
            params={"part": "status,snippet", "id": video_id},
            headers={"Authorization": f"Bearer {token}"},
            timeout=30.0,
        )
    except httpx.HTTPError as exc:
        log.warning("Could not read back video %s: %s", video_id, exc)
        return UploadOutcome()

    if response.status_code >= 400:
        log.warning("Could not read back video %s: HTTP %s", video_id, response.status_code)
        return UploadOutcome()

    try:
        payload = response.json()
    except ValueError:
        return UploadOutcome()
    if not isinstance(payload, dict):
        return UploadOutcome()
    items = payload.get("items")
    if not isinstance(items, list) or not items:
        return UploadOutcome()

    item = items[0] if isinstance(items[0], dict) else {}
    raw_status = item.get("status")
    status: dict[str, Any] = raw_status if isinstance(raw_status, dict) else {}
    raw_snippet = item.get("snippet")
    snippet: dict[str, Any] = raw_snippet if isinstance(raw_snippet, dict) else {}
    return UploadOutcome(
        actual_privacy=str(status.get("privacyStatus", "")),
        channel_id=str(snippet.get("channelId", "")),
        title=str(snippet.get("title", "")),
        found=True,
    )


def set_thumbnail(
    settings: config.Settings,
    *,
    video_id: str,
    path: Path,
    account_id: str | None = None,
) -> str:
    """Attach a custom thumbnail to an uploaded video.

    YouTube takes the thumbnail as a raw image body rather than a resumable
    upload, so this is a single POST. The ``youtube.upload`` scope covers
    ``thumbnails.set``.

    Preconditions:
        the video exists and ``path`` is a JPEG under 2 MB.
    """
    path = Path(path)
    if not path.is_file():
        raise YouTubeError(f"The thumbnail is missing: {path}")

    token = oauth.access_token(settings, account_id=account_id)
    try:
        response = httpx.post(
            THUMBNAIL_URL,
            params={"videoId": video_id},
            content=path.read_bytes(),
            headers={
                "Authorization": f"Bearer {token}",
                "Content-Type": "image/jpeg",
            },
            timeout=120.0,
        )
    except httpx.HTTPError as exc:
        raise YouTubeError(f"Could not upload the thumbnail: {exc}") from exc

    if response.status_code >= 400:
        raise _translate(response)

    log.info("Set thumbnail for YouTube video %s.", video_id)
    return str(response.json().get("url", ""))


def _translate(response: httpx.Response) -> YouTubeError:
    """Turn Google's error payload into a message the user can act on."""
    message = ""
    reason = ""
    try:
        error = response.json().get("error", {})
        if isinstance(error, str):
            message = error
        else:
            message = error.get("message", "")
            errors = error.get("errors") or []
            if errors and isinstance(errors[0], dict):
                reason = errors[0].get("reason", "")
    except ValueError:
        pass
    message = message or f"YouTube returned HTTP {response.status_code}."

    if reason == "quotaExceeded" or "quota" in message.lower():
        return YouTubeError(
            message,
            hint=(
                "The project's daily YouTube API quota is used up. Uploads cost "
                "1600 units of the 10,000/day default — roughly six per day."
            ),
        )
    if reason == "uploadLimitExceeded":
        return YouTubeError(
            message,
            hint="This channel has reached YouTube's daily upload limit. Try again tomorrow.",
        )
    if reason in {"forbidden", "youtubeSignupRequired"} or response.status_code == 403:
        return YouTubeError(
            message,
            hint=(
                "A new Google Cloud project can only upload private videos until "
                "it passes YouTube's API audit. Set privacy to Private, or request "
                "the audit in Google Cloud Console."
            ),
        )
    if response.status_code == 401:
        return YouTubeError(
            message,
            hint="The channel sign-in expired. Disconnect and connect the channel again.",
        )
    return YouTubeError(message)
