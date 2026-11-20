"""The publishing policy: where a clip goes, who it is for, and how it is seen.

Three questions, one answer, and no guessing:

**Where does it go?** The destination is named, never inferred. A channel
row carries the YouTube channel id that Google reported; an upload row
carries the channel it was aimed at, and the id YouTube confirms after
the fact.

**Who is it for?** ``madeForKids`` is a legal declaration about who the
video is made for. It has three states, and the empty one is not the same
as "no":

* ``""`` — not decided. The upload is **refused** until the owner
  answers. A legal declaration is not a preference AutoClip can fill in.
* ``"false"`` — not made for kids.
* ``"true"`` — made for kids.

**How is it seen?** The privacy that was asked for and the privacy that
YouTube actually applied are two different things, and they are recorded
separately. A new Google Cloud project cannot publish a public video
until it passes YouTube's API audit, so YouTube quietly forces the video
private. A row that said "public" when YouTube made it private would be
a lie, and the UI would claim a video is on YouTube when nobody can see
it.

The policy is resolved **before** the network call and written onto the
upload row, so the record of what was intended exists even if the
transfer fails halfway.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Any

from .. import config
from . import uploader

log = logging.getLogger(__name__)

__all__ = [
    "AudienceUndecided",
    "AUDIENCE_OPTIONS",
    "PublishPolicy",
    "describe",
    "resolve",
]

#: The three states of the audience declaration, in the order the owner
#: sees them. The first one is deliberately "not decided".
AUDIENCE_OPTIONS: tuple[tuple[str, str], ...] = (
    ("", "Not decided"),
    ("false", "No — not made for kids"),
    ("true", "Yes — made for kids"),
)

#: The privacy values YouTube understands.
PRIVACY_VALUES: tuple[str, ...] = ("private", "unlisted", "public")


class AudienceUndecided(uploader.YouTubeError):
    """The audience declaration has not been answered.

    The upload is refused rather than guessed. The message says what to
    do about it, because a refusal the owner cannot act on is just an
    obstacle.
    """

    def __init__(self, destination: str = "") -> None:
        where = f" on {destination}" if destination else ""
        super().__init__(
            f"The audience declaration{where} has not been answered.",
            hint=(
                "YouTube asks whether a video is made for kids, and that is a "
                "legal declaration rather than a setting AutoClip can choose "
                "for you. Answer it on the Channels page, then try again."
            ),
        )


@dataclass(frozen=True)
class PublishPolicy:
    """The whole publishing decision for one upload, resolved."""

    #: The privacy that will be asked for.
    privacy: str
    #: Whether the video is declared as made for kids.
    made_for_kids: bool
    #: The audience declaration as it was answered: '', 'false' or 'true'.
    #: The empty string means "not decided", which is not the same as
    #: 'false'.
    made_for_kids_state: str
    #: The category id sent with the upload.
    category_id: str
    #: The Google account that holds the credential.
    account_id: str = ""
    #: The channel *row* this publishes to. Empty = the legacy path.
    channel_row_id: str = ""
    #: The YouTube channel id this publishes to.
    destination_channel_id: str = ""
    #: The channel's display name, for messages.
    destination_title: str = ""

    def audience_text(self) -> str:
        """The audience declaration, in words."""
        return "made for kids" if self.made_for_kids else "not made for kids"

    def to_dict(self) -> dict[str, Any]:
        return {
            "privacy": self.privacy,
            "made_for_kids": self.made_for_kids,
            "made_for_kids_state": self.made_for_kids_state,
            "category_id": self.category_id,
            "account_id": self.account_id,
            "channel_row_id": self.channel_row_id,
            "destination_channel_id": self.destination_channel_id,
            "destination_title": self.destination_title,
        }


def _audience_state(raw: str) -> str:
    """Normalise an audience declaration to one of the three states."""
    value = (raw or "").strip().lower()
    if value in {"true", "1", "yes"}:
        return "true"
    if value in {"false", "0", "no"}:
        return "false"
    return ""


def resolve(
    channel: dict[str, Any] | None,
    settings: config.Settings,
    *,
    require_audience: bool = True,
    audience_override: str = "",
) -> PublishPolicy:
    """Resolve the publishing policy for a destination.

    ``channel`` is the channel row the upload names, or ``None`` for the
    legacy path where the destination comes from the global settings.

    ``audience_override`` is an answer the owner gave for this one
    upload. It wins over the channel's own answer, because an answer
    about a specific upload is more specific than one about a channel.

    With ``require_audience`` (the default) an unanswered audience
    declaration raises :class:`AudienceUndecided`. The caller that only
    wants to *describe* the policy — the UI, the settings page — passes
    ``False`` and gets the unanswered state back instead.
    """
    privacy = settings.youtube.privacy
    category_id = settings.youtube.category_id
    account_id = ""
    channel_row_id = ""
    destination_channel_id = ""
    destination_title = ""
    raw_audience = settings.youtube.made_for_kids

    if channel:
        channel_row_id = channel.get("id", "")
        destination_channel_id = channel.get("channel_id", "")
        destination_title = channel.get("title", "")
        account_id = channel.get("account_id", "")
        privacy = channel.get("privacy") or privacy
        category_id = channel.get("category_id") or category_id
        raw_audience = channel.get("made_for_kids") or raw_audience

    state = _audience_state(audience_override) or _audience_state(raw_audience)
    if state == "":
        if require_audience:
            raise AudienceUndecided(destination_title or destination_channel_id)
        return PublishPolicy(
            privacy=privacy,
            made_for_kids=False,
            made_for_kids_state="",
            category_id=category_id,
            account_id=account_id,
            channel_row_id=channel_row_id,
            destination_channel_id=destination_channel_id,
            destination_title=destination_title,
        )

    return PublishPolicy(
        privacy=privacy,
        made_for_kids=state == "true",
        made_for_kids_state=state,
        category_id=category_id,
        account_id=account_id,
        channel_row_id=channel_row_id,
        destination_channel_id=destination_channel_id,
        destination_title=destination_title,
    )


def describe(
    channel_row_id: str = "",
    settings: config.Settings | None = None,
) -> dict[str, Any]:
    """Describe the publishing policy for a channel, without raising.

    This is what the settings page asks for: what would happen, and what
    is still missing. An unanswered audience declaration is reported as
    unanswered rather than as "not made for kids".
    """
    settings = settings or config.load()
    channel: dict[str, Any] | None = None
    if channel_row_id:
        from . import accounts as accounts_store

        channel = accounts_store.get_channel(channel_row_id)

    policy = resolve(channel, settings, require_audience=False)
    state = _audience_state((channel or {}).get("made_for_kids") or settings.youtube.made_for_kids)
    return {
        **policy.to_dict(),
        "made_for_kids_state": state,
        "audience_decided": state != "",
        "audience_options": [{"value": value, "label": label} for value, label in AUDIENCE_OPTIONS],
        "privacy_options": list(PRIVACY_VALUES),
    }
