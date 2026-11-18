"""Resumable upload to YouTube's Data API v3.

Two requests: a JSON metadata POST that returns a resumable session URL, then a
single PUT of the rendered file to that URL. httpx streams the file, so an
80 MB export never sits in memory.
"""

from __future__ import annotations

import logging
from pathlib import Path

import httpx

from .. import config
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
    category_id: str = "24",
    language: str = "",
    account_id: str | None = None,
) -> str:
    """Upload one file and return its YouTube video id."""
    if not path.is_file():
        raise YouTubeError(f"The exported file is missing: {path}")

    settings.youtube.privacy = privacy  # type: ignore[assignment]
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
        # Naming a game or other third-party content does not make the video
        # "for kids"; the uploader is for the user's own channel content.
        "status": {"privacyStatus": privacy, "selfDeclaredMadeForKids": False},
    }

    headers = {
        "Authorization": f"Bearer {token}",
        "Content-Type": "application/json; charset=UTF-8",
        "X-Upload-Content-Length": str(path.stat().st_size),
        "X-Upload-Content-Type": "video/mp4",
    }

    try:
        init = httpx.post(
            UPLOAD_URL,
            params={"uploadType": "resumable", "part": "snippet,status"},
            json=body,
            headers=headers,
            timeout=60.0,
        )
    except httpx.HTTPError as exc:
        raise YouTubeError(f"Could not reach YouTube: {exc}") from exc

    if init.status_code >= 400:
        raise _translate(init)
    location = init.headers.get("location") or init.headers.get("Location")
    if not location:
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
        raise YouTubeError(f"The upload was interrupted: {exc}") from exc

    if response.status_code >= 400:
        raise _translate(response)

    video_id = response.json().get("id", "")
    if not video_id:
        raise YouTubeError("YouTube accepted the upload but returned no video id.")
    log.info("Uploaded %s to YouTube as %s.", path.name, video_id)
    return video_id


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
