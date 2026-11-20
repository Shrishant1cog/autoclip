"""Resumable upload, in chunks, with the session kept across restarts.

YouTube's resumable upload is a session: you ask for one, then send the
file in pieces. The single PUT that AutoClip used to make worked, but it
meant one dropped connection cost the whole file — a home connection
sending 80 MB will drop it sooner than anyone expects.

The pieces are:

* :func:`create_session` asks YouTube for a session and says how big the
  file is.
* :func:`probe` asks YouTube how much of the file it already has, so a
  restart continues rather than starts again.
* :func:`upload_file` walks the chunks and sends each one with a
  ``Content-Range``, reporting progress as it goes.

The session URL is the handle. It is stored on the upload row, so an
upload interrupted by a crash, a restart or a dropped connection picks
up where it left off instead of starting from zero.

A chunk is 8 MiB. YouTube accepts any chunk size that is a multiple of
256 KiB, and 8 MiB keeps the number of round trips down without holding
a huge buffer in memory.
"""

from __future__ import annotations

import logging
from collections.abc import Callable, Iterator
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

import httpx

from . import oauth
from .metadata import ClipMetadata

log = logging.getLogger(__name__)

__all__ = [
    "CHUNK_SIZE",
    "ResumableError",
    "SessionGone",
    "UploadSession",
    "chunk_ranges",
    "create_session",
    "probe",
    "upload_file",
]

#: The chunk size. YouTube wants a multiple of 256 KiB; 8 MiB keeps the
#: round trips down without a large buffer.
CHUNK_SIZE = 8 * 1024 * 1024

#: The session URL is only good for about a week, and a session that has
#: expired has to be replaced — which costs the whole file again.
SESSION_TTL_S = 6 * 24 * 60 * 60

#: The upload timeout covers the body transfer, not just the connection.
_UPLOAD_TIMEOUT = httpx.Timeout(1800.0, connect=30.0, write=300.0)


class ResumableError(RuntimeError):
    """The chunked upload could not continue."""


class SessionGone(ResumableError):
    """The session no longer exists and the file has to start again.

    A session lives for about a week. Once it is gone, asking how far it
    got is not the answer — the whole file has to be sent again. This is
    a different thing from a dropped connection, and the caller treats
    it differently: a new session is opened rather than the old one
    being retried.
    """


@dataclass(frozen=True)
class UploadSession:
    """The handle for one resumable upload."""

    #: The URL YouTube gave for the session.
    url: str
    #: When the session stops being usable.
    expires_at: str = ""
    #: The total size of the file, in bytes.
    total_bytes: int = 0

    def expired(self, now: float) -> bool:
        """True when the session is past its expiry."""
        if not self.expires_at:
            return False
        try:
            expiry = datetime.fromisoformat(self.expires_at)
        except ValueError:
            return False
        if expiry.tzinfo is None:
            expiry = expiry.replace(tzinfo=UTC)
        return expiry.timestamp() <= now


def chunk_ranges(total: int, chunk_size: int = CHUNK_SIZE) -> list[tuple[int, int]]:
    """The byte ranges to send, as inclusive ``(start, end)`` pairs.

    The last chunk is short. A file of exactly ``chunk_size`` bytes is
    one chunk, and a file of zero bytes is no chunks at all.
    """
    if total <= 0 or chunk_size <= 0:
        return []
    ranges: list[tuple[int, int]] = []
    start = 0
    while start < total:
        end = min(start + chunk_size, total) - 1
        ranges.append((start, end))
        start = end + 1
    return ranges


def create_session(
    *,
    url: str,
    token: str,
    metadata: ClipMetadata,
    privacy: str,
    made_for_kids: bool,
    category_id: str = "24",
    language: str = "",
    total_bytes: int = 0,
    timeout: float = 60.0,
) -> UploadSession:
    """Ask YouTube for a resumable session and return its handle.

    The metadata goes in the same request, which is what creates the
    video; the bytes come afterwards.
    """
    snippet: dict[str, Any] = {
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
        "X-Upload-Content-Length": str(total_bytes),
        "X-Upload-Content-Type": "video/mp4",
    }

    try:
        response = httpx.post(
            url,
            params={"uploadType": "resumable", "part": "snippet,status"},
            json=body,
            headers=headers,
            timeout=timeout,
        )
    except httpx.HTTPError as exc:
        raise ResumableError(f"Could not reach YouTube: {exc}") from exc

    if response.status_code >= 400:
        raise ResumableError(f"YouTube refused to start the upload: HTTP {response.status_code}")

    session_url = response.headers.get("location") or response.headers.get("Location")
    if not session_url:
        raise ResumableError("YouTube did not return an upload session URL.")
    # The session URL is where the bytes go. It came from Google over
    # TLS, so it is trusted — but a URL that is not HTTPS would mean
    # sending the file in the clear, and one pointing at a local
    # address would be reaching into the machine. Neither is acceptable,
    # and neither can be a real YouTube session.
    if not session_url.lower().startswith("https://"):
        raise ResumableError("YouTube returned an upload session URL that is not secure.")

    expires_at = response.headers.get("x-goog-expires") or response.headers.get("X-Goog-Expires")
    expiry = ""
    if expires_at:
        expiry = (datetime.now(UTC) + timedelta(seconds=int(expires_at))).isoformat(
            timespec="seconds"
        )

    return UploadSession(url=session_url, expires_at=expiry, total_bytes=total_bytes)


def probe(
    *,
    session_url: str,
    token: str,
    total_bytes: int,
    timeout: float = 30.0,
) -> int:
    """Ask YouTube how many bytes it already has.

    The request carries no body and says ``bytes */total``, which is
    YouTube's way of asking for the current offset. The answer is the
    ``Range`` header. Zero means YouTube has nothing, so the upload
    starts from the beginning.
    """
    try:
        response = httpx.put(
            session_url,
            content=b"",
            headers={
                "Authorization": f"Bearer {token}",
                "Content-Length": "0",
                "Content-Range": f"bytes */{total_bytes}",
            },
            timeout=timeout,
        )
    except httpx.HTTPError as exc:
        raise ResumableError(f"Could not ask YouTube how far the upload got: {exc}") from exc

    if response.status_code not in (200, 201, 308):
        if response.status_code in (404, 410):
            # The session is gone. The file has to start again — there
            # is nothing left to continue.
            raise SessionGone(
                "The upload session has expired; the file has to be sent again from the beginning."
            )
        raise ResumableError(
            f"YouTube could not report the upload progress: HTTP {response.status_code}"
        )

    raw = response.headers.get("range") or response.headers.get("Range") or ""
    # The header looks like "bytes=0-1048575" — the count is the end
    # plus one, because the range is inclusive.
    if "=" not in raw:
        return 0
    _, _, span = raw.partition("=")
    end = span.split("-")[-1]
    try:
        return int(end) + 1
    except ValueError:
        return 0


def upload_file(
    *,
    session: UploadSession,
    path: Path,
    token: str,
    start_offset: int = 0,
    progress: Callable[[int, int], None] | None = None,
    timeout: httpx.Timeout | None = None,
) -> dict[str, Any]:
    """Send the file in chunks and return YouTube's final response.

    ``start_offset`` is where to begin: the number of bytes YouTube
    already has. ``progress`` is called after every chunk with the
    running total and the file's size.
    """
    total = path.stat().st_size
    if total <= 0:
        raise ResumableError("The exported file is empty; there is nothing to upload.")

    if start_offset < 0 or start_offset > total:
        start_offset = 0

    sent = start_offset
    if progress is not None:
        progress(sent, total)

    timeout = timeout or _UPLOAD_TIMEOUT
    # The ranges start at the offset, not at zero. YouTube requires each
    # chunk to begin exactly where the last one stopped, and the offset
    # is not necessarily on a chunk boundary — a connection that dropped
    # halfway through a chunk leaves a partial one behind.
    ranges: list[tuple[int, int]] = []
    start = start_offset
    while start < total:
        end = min(start + CHUNK_SIZE, total) - 1
        ranges.append((start, end))
        start = end + 1

    with path.open("rb") as handle:
        for start, end in ranges:
            handle.seek(start)
            chunk = handle.read(end - start + 1)
            headers = {
                "Authorization": f"Bearer {token}",
                "Content-Type": "video/mp4",
                "Content-Length": str(len(chunk)),
                "Content-Range": f"bytes {start}-{end}/{total}",
            }
            try:
                response = httpx.put(session.url, content=chunk, headers=headers, timeout=timeout)
            except httpx.HTTPError as exc:
                raise ResumableError(
                    f"The upload stopped after {sent} of {total} bytes: {exc}"
                ) from exc

            if response.status_code not in (200, 201, 308):
                # 308 ("Resume Incomplete") is the *normal* answer for a
                # chunk that is not the last one: YouTube is saying "I
                # have that much, send the next". 200 and 201 mean the
                # video is created. Anything else is a refusal.
                detail = ""
                try:
                    error = response.json().get("error", {})
                    detail = error.get("message", "") if isinstance(error, dict) else str(error)
                except ValueError:
                    detail = str(getattr(response, "text", ""))[:300]
                raise ResumableError(
                    f"YouTube refused the upload at byte {sent} of {total}: "
                    f"{detail or f'HTTP {response.status_code}'}"
                )

            sent = end + 1
            if progress is not None:
                progress(sent, total)

            if response.status_code in (200, 201):
                try:
                    return response.json()
                except ValueError as exc:
                    raise ResumableError("YouTube finished the upload but sent no body.") from exc

    raise ResumableError("The upload finished without YouTube confirming the video.")


def access_token(settings: Any, account_id: str | None = None) -> str:
    """The access token for the account that owns the upload."""
    return oauth.access_token(settings, account_id=account_id)


def iter_chunks(path: Path, chunk_size: int = CHUNK_SIZE) -> Iterator[bytes]:
    """Read a file in chunks. Used by the tests and by the diagnostics."""
    with path.open("rb") as handle:
        while True:
            chunk = handle.read(chunk_size)
            if not chunk:
                return
            yield chunk
