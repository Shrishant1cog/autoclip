"""Instagram Platform errors, and what AutoClip does about each one.

Meta's Graph API answers a failed call with an envelope like this::

    {"error": {
        "message": "...",
        "type": "OAuthException",
        "code": 9,
        "error_subcode": 2207042,
        "is_transient": false,
        "error_user_title": "...",
        "error_user_msg": "...",
        "fbtrace_id": "A6LJylpZRKw2xKLFsAP-cJh"
    }}

The table in :data:`_BY_CODE` is transcribed from Meta's own error-codes
reference (read 2026-11-20, and recorded in
``docs/INSTAGRAM-API-EVALUATION.md`` §9.1.10). Every entry says what the
failure *means* and what AutoClip should do next, because those are
different questions: a dropped connection and a suspected-spam block are
both "the publish failed", but only one of them may be tried again.

The three outcomes are:

``transient``
    Worth another try. The worker leaves the row **pending** and backs off.

``owner_action_required``
    Meta is waiting for the account owner, not for another request. The
    account is restricted, or the publishing action looks like spam. Retrying
    would make things worse, so the upload is marked failed with the reason.

``permanent``
    The request itself is wrong — a bad format, a caption over the limit, a
    file that is not MOV/MP4. Retrying it unchanged fails identically.
"""

from __future__ import annotations

import time
from dataclasses import dataclass
from typing import Any

__all__ = [
    "InstagramError",
    "OwnerActionRequired",
    "translate_graph_error",
]


class InstagramError(RuntimeError):
    """The Instagram Platform refused something.

    ``transient`` says whether trying again later could work. A dropped
    connection is transient; a file in the wrong format is not.

    ``retry_at`` is set when the failure has a known clock of its own — the
    daily publishing limit comes back on its own, and waiting for the reset
    is better than guessing a delay.

    ``owner_action_required`` marks the failures that only the account owner
    can fix: a restricted account, or a publish that Meta believes is spam.

    ``needs_reconciliation`` marks the failures whose outcome is genuinely
    unknown: the publish request may have reached Instagram and been
    accepted, and the answer never came back. Such a row is neither failed
    nor retried — sending it again could post the clip twice. It waits for
    the owner, who checks Instagram and then either confirms the post or
    asks for it to be sent again.
    """

    def __init__(
        self,
        message: str,
        *,
        hint: str = "",
        transient: bool = False,
        retry_at: str = "",
        owner_action_required: bool = False,
        needs_reconnect: bool = False,
        needs_reconciliation: bool = False,
        code: int | None = None,
        subcode: int | None = None,
        fbtrace_id: str = "",
    ) -> None:
        super().__init__(message)
        self.hint = hint
        self.transient = transient
        self.retry_at = retry_at
        self.owner_action_required = owner_action_required
        self.needs_reconnect = needs_reconnect
        self.needs_reconciliation = needs_reconciliation
        self.code = code
        self.subcode = subcode
        self.fbtrace_id = fbtrace_id

    def __str__(self) -> str:
        base = super().__str__()
        parts = [base]
        if self.hint:
            parts.append(self.hint)
        if self.fbtrace_id:
            parts.append(f"Meta trace id: {self.fbtrace_id}")
        return "\n\n".join(parts)


class OwnerActionRequired(InstagramError):
    """Meta is waiting for the account owner, not for another request.

    A restricted account and a suspected-spam block both land here. The
    account has to be opened in the Instagram app and dealt with; no amount
    of retrying from here helps.
    """

    def __init__(self, message: str, **kwargs: Any) -> None:
        # The flag follows from the class, so raising one always says so
        # on the instance — a caller never has to remember to set it.
        kwargs.setdefault("owner_action_required", True)
        super().__init__(message, **kwargs)


@dataclass(frozen=True)
class _Outcome:
    """What one documented error code means and what to do about it."""

    transient: bool
    message: str
    hint: str = ""
    owner_action_required: bool = False
    needs_new_container: bool = False
    #: Set for the daily publishing limit, which has its own reset.
    waits_for_reset: bool = False
    #: Set when Meta stopped accepting the credential itself.
    needs_reconnect: bool = False


#: Meta's documented error codes, keyed by ``(code, subcode)``.
#:
#: The subcode is what distinguishes two failures that share a code, so it
#: is part of the key. A code that appears with an unknown subcode falls
#: back to the code-only entry, and then to the HTTP status.
_BY_CODE: dict[tuple[int, int], _Outcome] = {
    (-1, 2207001): _Outcome(
        True,
        "Instagram had a server error.",
        "This is Instagram's own fault, not the file's. It will be tried again.",
    ),
    (-1, 2207032): _Outcome(
        True,
        "Instagram could not create the media container.",
        "The container is created before anything is published, so nothing was "
        "posted. It will be tried again.",
    ),
    (-1, 2207053): _Outcome(
        True,
        "Instagram reported an unknown error during the upload.",
        "A new container will be created and the file sent again.",
        needs_new_container=True,
    ),
    (-2, 2207003): _Outcome(
        True,
        "Instagram took too long to download the media.",
        "It will be tried again.",
    ),
    (-2, 2207020): _Outcome(
        True,
        "The media Instagram was holding has expired.",
        "A new container will be created and the file sent again.",
        needs_new_container=True,
    ),
    (1, 2207057): _Outcome(
        False,
        "The thumbnail offset is outside the video.",
        "Instagram wants an offset inside the clip's length.",
    ),
    (4, 2207051): _Outcome(
        False,
        "Instagram thinks this publish looks like spam.",
        "Meta asks the account owner to confirm the publish is not spam. "
        "AutoClip does not retry into a spam block.",
        owner_action_required=True,
    ),
    (9, 2207042): _Outcome(
        True,
        "Instagram's publishing limit for this account has been reached.",
        "Accounts are limited to a set number of API-published posts in a rolling "
        "24-hour window. The upload will wait until the window has turned over.",
        waits_for_reset=True,
    ),
    (24, 2207006): _Outcome(
        True,
        "Instagram cannot find the media it was given.",
        "This is usually a permission problem or an expired token. A new container "
        "will be created and the file sent again.",
        needs_new_container=True,
    ),
    (24, 2207008): _Outcome(
        True,
        "The Instagram container no longer exists, or it has expired.",
        "Containers expire 24 hours after they are created. A new container will be "
        "created and the file sent again.",
        needs_new_container=True,
    ),
    (25, 2207050): _Outcome(
        False,
        "The Instagram account is restricted.",
        "Sign in to the Instagram app and complete whatever it asks for, then try again.",
        owner_action_required=True,
    ),
    (100, 2207028): _Outcome(
        False,
        "The number of carousel items is outside the allowed range.",
        "Instagram's own error message says 2 to 10 items; its endpoint reference "
        "says up to 20. AutoClip does not publish carousels.",
    ),
    (100, 2207040): _Outcome(
        False,
        "The caption has more than 20 @tags.",
        "Instagram allows 20 @tags, 30 hashtags and 2,200 characters.",
    ),
    (352, 2207026): _Outcome(
        False,
        "Instagram does not support this video format.",
        "Reels must be MOV or MP4 (MPEG-4 Part 14).",
    ),
    (9004, 2207052): _Outcome(
        True,
        "Instagram could not fetch the media from the address it was given.",
        "The address must be publicly reachable. It will be tried again.",
    ),
    (9007, 2207027): _Outcome(
        True,
        "The media is not ready for publishing yet.",
        "Instagram is still processing it. The container will be checked again.",
    ),
    (36000, 2207004): _Outcome(
        False,
        "The image is larger than 8 MiB.",
        "Instagram allows images up to 8 MiB.",
    ),
    (36001, 2207005): _Outcome(
        False,
        "Instagram does not support this image format.",
        "Only JPEG is supported.",
    ),
    (36003, 2207009): _Outcome(
        False,
        "The image's aspect ratio is outside the allowed range.",
        "Instagram allows 4:5 to 1.91:1.",
    ),
    (36004, 2207010): _Outcome(
        False,
        "The caption is too long.",
        "Instagram allows 2,200 characters, 30 hashtags and 20 @tags.",
    ),
}

#: Codes that mean the same thing whatever subcode they arrive with.
_BY_CODE_ONLY: dict[int, _Outcome] = {
    1: _Outcome(
        True,
        "Instagram is temporarily unavailable.",
        "This is usually temporary. It will be tried again.",
    ),
    2: _Outcome(
        True,
        "Instagram is temporarily unavailable.",
        "This is usually temporary. It will be tried again.",
    ),
    4: _Outcome(
        False,
        "Instagram thinks this publish looks like spam.",
        "Meta asks the account owner to confirm the publish is not spam. "
        "AutoClip does not retry into a spam block.",
        owner_action_required=True,
    ),
    9: _Outcome(
        True,
        "Instagram's publishing limit for this account has been reached.",
        "The upload will wait until the window has turned over.",
        waits_for_reset=True,
    ),
    10: _Outcome(
        False,
        "The app does not have permission for this.",
        "The publish permission has to be granted for this account.",
    ),
    25: _Outcome(
        False,
        "The Instagram account is restricted.",
        "Sign in to the Instagram app and complete whatever it asks for, then try again.",
        owner_action_required=True,
    ),
    190: _Outcome(
        False,
        "Instagram rejected the access token.",
        "The account needs to be connected again.",
        needs_reconnect=True,
    ),
}


#: The reset used when the publishing limit is reached.
#:
#: The limit is a **rolling** 24-hour window, so allowance can come back at
#: any moment once the oldest posts age out. There is no exact clock to
#: wait for, so AutoClip waits until local midnight — which is never too
#: early — and says so in the message rather than claiming a precision it
#: does not have.
def reset_at(now: float | None = None) -> str:
    """The moment the publishing-limit wait ends: local midnight tomorrow."""
    from datetime import datetime, timedelta

    moment = datetime.fromtimestamp(now if now is not None else time.time())
    tomorrow = (moment + timedelta(days=1)).replace(hour=0, minute=0, second=0, microsecond=0)
    return tomorrow.isoformat()


def _payload_error(payload: dict[str, Any]) -> dict[str, Any]:
    error = payload.get("error")
    if isinstance(error, dict):
        return error
    if isinstance(error, str):
        return {"message": error}
    return {}


def translate_graph_error(payload: dict[str, Any], http_status: int = 400) -> InstagramError:
    """Turn Meta's error envelope into an :class:`InstagramError`.

    The envelope's own ``is_transient`` flag is honoured when Meta sets it,
    but it does not override the documented table: Meta marks a server error
    as non-transient in some responses, and retrying that one is still
    right. The table is the authority; the flag is a second opinion.
    """
    error = _payload_error(payload)
    code = _as_int(error.get("code"))
    subcode = _as_int(error.get("error_subcode"))
    fbtrace_id = str(error.get("fbtrace_id") or "")

    outcome = None
    if code is not None and subcode is not None:
        outcome = _BY_CODE.get((code, subcode))
    if outcome is None and code is not None:
        outcome = _BY_CODE_ONLY.get(code)

    message = str(error.get("error_user_msg") or error.get("message") or "").strip()
    if not message and outcome is not None:
        message = outcome.message
    if not message:
        message = f"Instagram returned HTTP {http_status}."

    if outcome is None:
        # Nothing documented matches. The HTTP status is the best guide:
        # a server-side status is worth another try, a client-side one is
        # the request's own fault.
        transient = http_status == 429 or http_status >= 500
        return InstagramError(
            message,
            hint=(
                "Instagram did not name the failure. It will be tried again."
                if transient
                else "Instagram did not name the failure."
            ),
            transient=transient,
            code=code,
            subcode=subcode,
            fbtrace_id=fbtrace_id,
        )

    hint = outcome.hint
    if outcome.waits_for_reset:
        retry_at = reset_at()
        hint = (
            f"{hint} The upload will be tried again after midnight, when the "
            "24-hour window has certainly turned over."
        )
    else:
        retry_at = ""

    # Meta's own words go first, because they speak to the account owner
    # in Meta's language. AutoClip's explanation of what the failure
    # *means* follows, because Meta's message rarely says whether the
    # upload may be tried again.
    if outcome.message and outcome.message.lower() not in message.lower():
        message = f"{message} {outcome.message}"

    error_cls = OwnerActionRequired if outcome.owner_action_required else InstagramError
    return error_cls(
        message,
        hint=hint,
        transient=outcome.transient,
        retry_at=retry_at,
        owner_action_required=outcome.owner_action_required,
        needs_reconnect=outcome.needs_reconnect,
        code=code,
        subcode=subcode,
        fbtrace_id=fbtrace_id,
    )


def _as_int(value: object) -> int | None:
    """Read an integer out of a JSON value, or ``None`` when it is not one."""
    if isinstance(value, bool):
        return None
    if isinstance(value, int):
        return value
    if isinstance(value, float):
        return int(value)
    if isinstance(value, str):
        try:
            return int(value.strip())
        except ValueError:
            return None
    return None
