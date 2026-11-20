"""Music licensing — what the user knows about a track's rights.

The states are deliberately narrow, and one of them cannot be set by the user:

``unknown``
    Nothing is known. The export is blocked. This is the default, and it is
    the honest default: AutoClip cannot tell whether a file in a folder is
    licensed for use.

``user_confirmed``
    The user says they have the rights. This is an **attestation**, not a
    verification, and the UI says so wherever it is shown. It is enough to
    let the export proceed, because the user is the one who knows.

``verified``
    Independently verified against evidence. The UI cannot set this; it needs
    a recorded verification source, and a user's own word is not a source.

``incompatible``
    The licence does not permit this use. The export is blocked.

``expired``
    The licence has an expiry date in the past. The export is blocked.

The rules the export gate applies are in :func:`evaluate`. They are written
here rather than scattered through the export path so that one file answers
"may this track be used, and why not".
"""

from __future__ import annotations

import time
from dataclasses import asdict, dataclass, field

__all__ = [
    "LicenseBlocked",
    "LicenseRecord",
    "LicenseState",
    "USER_SETTABLE_STATES",
    "evaluate",
    "is_expired",
]

#: The states that stop an export.
BLOCKING_STATES = ("unknown", "incompatible", "expired")


class LicenseState:
    """The vocabulary of licensing states."""

    UNKNOWN = "unknown"
    USER_CONFIRMED = "user_confirmed"
    VERIFIED = "verified"
    INCOMPATIBLE = "incompatible"
    EXPIRED = "expired"

    @classmethod
    def all(cls) -> tuple[str, ...]:
        return (
            cls.UNKNOWN,
            cls.USER_CONFIRMED,
            cls.VERIFIED,
            cls.INCOMPATIBLE,
            cls.EXPIRED,
        )


#: The states a user may set from the UI. 'verified' is missing on purpose:
#: independent verification is not something a user can assert about their
#: own files, and letting them set it would turn an attestation into a
#: certification.
USER_SETTABLE_STATES = (
    LicenseState.UNKNOWN,
    LicenseState.USER_CONFIRMED,
    LicenseState.INCOMPATIBLE,
    LicenseState.EXPIRED,
)


class LicenseBlocked(RuntimeError):
    """A track may not be used for this export."""

    def __init__(self, message: str, *, state: str = "", track_name: str = "") -> None:
        super().__init__(message)
        self.state = state
        self.track_name = track_name


@dataclass
class LicenseRecord:
    """What is known about one track's rights."""

    track_id: str
    state: str = LicenseState.UNKNOWN
    #: Where the knowledge came from — a store, a licence file, a purchase.
    source: str = ""
    #: The evidence itself: a receipt reference, a licence URL, a note.
    evidence: str = ""
    #: Text that must be credited when the track is used.
    attribution: str = ""
    commercial_use: bool = False
    non_commercial: bool = False
    derivative: bool = False
    share_alike: bool = False
    #: ISO date. Empty means the licence does not expire.
    expires_at: str = ""
    #: Who verified it, and when. Empty for a user attestation.
    verified_by: str = ""
    verified_at: str = ""
    updated_at: str = ""

    def to_dict(self) -> dict[str, object]:
        return asdict(self)


@dataclass
class LicenseVerdict:
    """The gate's answer for one track."""

    allowed: bool
    state: str
    reason: str = ""
    #: Things the user should know but that do not block the export.
    warnings: list[str] = field(default_factory=list)


def is_expired(record: LicenseRecord, *, now: str | None = None) -> bool:
    """Whether the licence's expiry date has passed.

    The expiry is stored as an ISO date. An unparseable date is treated as
    **not** expired: a typo in a date field should not silently block an
    export the user has otherwise cleared, but it is reported as a warning.
    """
    raw = (record.expires_at or "").strip()
    if not raw:
        return False
    if record.state == LicenseState.EXPIRED:
        return True
    try:
        expiry = time.strptime(raw[:10], "%Y-%m-%d")
    except ValueError:
        return False
    today = now or time.strftime("%Y-%m-%d")
    try:
        today_parts = time.strptime(today[:10], "%Y-%m-%d")
    except ValueError:
        return False
    return expiry < today_parts


def evaluate(record: LicenseRecord, *, now: str | None = None) -> LicenseVerdict:
    """Decide whether a track may be used, and say why."""
    state = record.state or LicenseState.UNKNOWN

    if state == LicenseState.INCOMPATIBLE:
        return LicenseVerdict(
            allowed=False,
            state=state,
            reason=record.evidence or "This track's licence does not permit this use.",
        )

    if state == LicenseState.EXPIRED or is_expired(record, now=now):
        return LicenseVerdict(
            allowed=False,
            state=LicenseState.EXPIRED,
            reason=(
                f"This track's licence expired on {record.expires_at}."
                if record.expires_at
                else "This track's licence has expired."
            ),
        )

    if state == LicenseState.UNKNOWN:
        return LicenseVerdict(
            allowed=False,
            state=state,
            reason=(
                "This track's licence is unknown. Record where it came from in "
                "Settings → Music before using it in an export."
            ),
        )

    warnings: list[str] = []
    if state == LicenseState.USER_CONFIRMED:
        warnings.append("You confirmed this licence yourself. That is not an independent check.")
    if record.attribution:
        warnings.append(f"Credit required: {record.attribution}")
    if record.non_commercial:
        warnings.append("Non-commercial use only.")
    if record.share_alike:
        warnings.append("Share-alike terms apply.")
    if record.derivative is False and state == LicenseState.VERIFIED:
        warnings.append("Derivative works are not permitted by this licence.")

    return LicenseVerdict(allowed=True, state=state, warnings=warnings)
