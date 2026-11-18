"""One error taxonomy for the whole app (Phase 15).

Before this, a failure could arrive at the UI as a bare string, a FastAPI
``detail`` object, or a 500 with a stack trace in the log — and the UI could
not tell whether retrying was worth it. Now every failure is classified into
one of a small set of **codes**, each with a stable meaning, a suggested
status code, and a decision about whether trying again could plausibly work.

The rules the classification follows:

* **Never invent a cause.** An unrecognised exception becomes ``internal``
  with the real message — not a guess that it was, say, a quota problem.
* **Retryability is a property of the cause, not of the mood.** A rate limit
  or a dropped connection is worth retrying; a missing file or a rejected
  credential is not, and telling the user to "try again" there would be a lie.
* **The hint is the fix.** Where a code implies a concrete action, the hint
  says which one.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any

#: The stable codes the API and UI understand.
AUTH = "auth"
QUOTA = "quota"
RATE_LIMIT = "rate_limit"
PROVIDER = "provider"
NETWORK = "network"
TIMEOUT = "timeout"
NOT_FOUND = "not_found"
VALIDATION = "validation"
CONFIG = "config"
MEDIA = "media"
CONFLICT = "conflict"
INTERNAL = "internal"

#: Codes worth trying again. Everything else needs the user to change
#: something first (a key, a file, a setting).
RETRYABLE_CODES = frozenset({RATE_LIMIT, NETWORK, TIMEOUT, QUOTA, INTERNAL})

#: Default HTTP status per code.
_STATUS_BY_CODE = {
    AUTH: 401,
    QUOTA: 429,
    RATE_LIMIT: 429,
    PROVIDER: 502,
    NETWORK: 502,
    TIMEOUT: 504,
    NOT_FOUND: 404,
    VALIDATION: 400,
    CONFIG: 400,
    MEDIA: 422,
    CONFLICT: 409,
    INTERNAL: 500,
}

#: The action each code implies, if any.
_HINTS: dict[str, str] = {
    AUTH: "Check the API key or reconnect the account in Settings.",
    QUOTA: (
        "The provider's quota for this key is used up. Add another key, or wait "
        "for the quota to reset."
    ),
    RATE_LIMIT: "Too many requests. This usually clears on its own in a minute.",
    PROVIDER: "Every AI provider failed. Add a key in Settings → AI Providers.",
    NETWORK: "The connection dropped. Check your network and try again.",
    TIMEOUT: "The operation took too long. Try again, or use a smaller source.",
    NOT_FOUND: "That item no longer exists.",
    VALIDATION: "The request was not valid.",
    CONFIG: "Check the settings for this feature.",
    MEDIA: "The media file could not be processed.",
    CONFLICT: "Something already exists in that state.",
    INTERNAL: "An unexpected error occurred. The details are in the server log.",
}

#: Markers for each class of failure, checked against the message.
_AUTH_MARKERS = (
    "unauthorized",
    "unauthenticated",
    "invalid api key",
    "invalid_api_key",
    "invalid key",
    "authentication",
    "permission denied",
    "insufficient permissions",
    "401",
    "403",
    "credentials",
)
_QUOTA_MARKERS = (
    "quota exceeded",
    "quotaexceeded",
    "quota exhausted",
    "resource_exhausted",
    "insufficient_quota",
    "billing",
    "no quota",
)
_RATE_MARKERS = (
    "rate limit",
    "rate_limit",
    "ratelimit",
    "too many requests",
    "429",
    "overloaded",
    "try again later",
)
_TIMEOUT_MARKERS = ("timeout", "timed out", "deadline exceeded")
_NETWORK_MARKERS = (
    "connection",
    "network",
    "unreachable",
    "dns",
    "temporary failure in name resolution",
    "ssl",
    "reset by peer",
)
_MEDIA_MARKERS = (
    "ffmpeg",
    "codec",
    "invalid data found",
    "moov atom",
    "media",
)
#: A file or row that is simply gone — distinct from a file that is present
#: but cannot be processed.
_NOT_FOUND_MARKERS = (
    "no such file or directory",
    "has been moved or deleted",
    "no longer exists",
    "does not exist",
    "missing file",
)


@dataclass
class ErrorInfo:
    """A classified failure."""

    code: str
    message: str
    hint: str = ""
    retryable: bool = False
    status: int = 500

    def to_dict(self) -> dict[str, Any]:
        return {
            "code": self.code,
            "message": self.message,
            "hint": self.hint,
            "retryable": self.retryable,
            "status": self.status,
        }

    def to_response(self) -> dict[str, Any]:
        """The JSON body every API error uses."""
        return {
            "detail": self.message,
            "code": self.code,
            "hint": self.hint,
            "retryable": self.retryable,
        }


def _message_of(exc: BaseException) -> str:
    text = str(exc).strip()
    return text or exc.__class__.__name__


def _has(text: str, markers: tuple[str, ...]) -> bool:
    return any(marker in text for marker in markers)


def classify(exc: BaseException, *, hint: str = "") -> ErrorInfo:
    """Turn any exception into a classified :class:`ErrorInfo`.

    The message is always the real one. The *code* is inferred from the
    markers the message contains and from the exception's own type; when
    nothing matches, the failure is ``internal`` rather than a guess.
    """
    message = _message_of(exc)
    text = message.lower()

    # An explicit code on the exception wins: a component that knows exactly
    # what went wrong should say so.
    explicit = getattr(exc, "code", "")
    if isinstance(explicit, str) and explicit:
        code = explicit
        hint = hint or getattr(exc, "hint", "") or _HINTS.get(code, "")
        return ErrorInfo(
            code=code,
            message=message,
            hint=hint,
            retryable=code in RETRYABLE_CODES,
            status=_STATUS_BY_CODE.get(code, 500),
        )

    # Type-based classification first, then message markers.
    name = type(exc).__name__
    if name in ("ProviderError", "AllProvidersFailedError"):
        code = PROVIDER
    elif name in ("OAuthError", "AuthenticationError"):
        code = AUTH
    elif name == "YouTubeError":
        code = PROVIDER
    elif name == "DuplicateUploadError":
        code = CONFLICT
    elif name in ("FFmpegError", "ExportError", "ThumbnailError", "IngestError"):
        code = MEDIA
    elif name in ("ValidationError", "WorkflowValidationError"):
        code = VALIDATION
    elif _has(text, _QUOTA_MARKERS):
        code = QUOTA
    elif _has(text, _RATE_MARKERS):
        code = RATE_LIMIT
    elif _has(text, _AUTH_MARKERS):
        code = AUTH
    elif _has(text, _TIMEOUT_MARKERS):
        code = TIMEOUT
    elif _has(text, _NETWORK_MARKERS):
        code = NETWORK
    elif _has(text, _NOT_FOUND_MARKERS):
        code = NOT_FOUND
    elif _has(text, _MEDIA_MARKERS):
        code = MEDIA
    elif name in ("FileNotFoundError", "KeyError"):
        code = NOT_FOUND
    else:
        code = INTERNAL

    resolved_hint = hint or getattr(exc, "hint", "") or _HINTS.get(code, "")
    return ErrorInfo(
        code=code,
        message=message,
        hint=resolved_hint,
        retryable=code in RETRYABLE_CODES,
        status=_STATUS_BY_CODE.get(code, 500),
    )


def classify_text(text: str, *, code: str = INTERNAL) -> ErrorInfo:
    """Classify a stored error string (a job's ``error`` column, say).

    The same marker rules apply as for a raised exception, so an upload that
    failed with "quotaExceeded" is classified as a quota problem whether the
    string came from a live exception or from the database.
    """
    message = text.strip() or "Unknown error."
    if code != INTERNAL:
        return ErrorInfo(
            code=code,
            message=message,
            hint=_HINTS.get(code, ""),
            retryable=code in RETRYABLE_CODES,
            status=_STATUS_BY_CODE.get(code, 500),
        )
    return classify(RuntimeError(message))


#: A UUID-ish or hex id in free text. Used to pull a row id out of an error
#: message so the UI can link to it.
_ROW_ID = re.compile(r"\b[0-9a-f]{16}\b")


def row_id_in(text: str) -> str:
    """The first AutoClip row id mentioned in a message, or ''."""
    match = _ROW_ID.search(text or "")
    return match.group(0) if match else ""


__all__ = [
    "AUTH",
    "CONFLICT",
    "CONFIG",
    "INTERNAL",
    "MEDIA",
    "NETWORK",
    "NOT_FOUND",
    "PROVIDER",
    "QUOTA",
    "RATE_LIMIT",
    "RETRYABLE_CODES",
    "TIMEOUT",
    "VALIDATION",
    "ErrorInfo",
    "classify",
    "classify_text",
    "row_id_in",
]
