"""The ``improve.txt`` feedback loop (Phase 11).

``~/.autoclip/improve.txt`` is the user's direct line to the detection model.
Whatever they write there is injected into the system prompt on every
highlight-detection call — "our audience loves numbers", "never clip the
sponsor segment", anything a human editor would put in a briefing.

The file is created with a commented template on first run so it is
discoverable, and every read is cached by mtime so re-reading it per window
costs nothing.

Per-channel feedback lives in ``~/.autoclip/channels/<UC_xxx>.md``: notes the
user writes about what titles/directions work for one channel. The metadata
generator reads the note for the destination channel when it writes a title.
"""

from __future__ import annotations

import logging
from pathlib import Path

from .. import paths

log = logging.getLogger(__name__)

IMPROVE_FILENAME = "improve.txt"

#: Maximum characters of user feedback injected into a prompt. A runaway
#: improve.txt must not blow every provider's context window.
MAX_FEEDBACK_CHARS = 4000

TEMPLATE = """\
# improve.txt — tell the clip finder what you want.
# Everything below the line is injected into the detection prompt as-is.
# Lines starting with '#' are ignored. Keep it short and imperative.
#
# Examples:
#   Our audience loves specific numbers in the first sentence.
#   Never clip the intro or the sponsor segment.
#   Prefer clips where the speaker is angry or surprised.
# =====================================================================

"""


def improve_path() -> Path:
    """Where the feedback file lives (``~/.autoclip/improve.txt``)."""
    return paths.root() / IMPROVE_FILENAME


def channels_dir() -> Path:
    return paths.root() / "channels"


def channel_note_path(channel_id: str) -> Path:
    """Feedback file for one YouTube channel (by its UC_… id)."""
    safe = "".join(c for c in channel_id if c.isalnum() or c in "-_")
    return channels_dir() / f"{safe or 'default'}.md"


def ensure_template() -> Path:
    """Create ``improve.txt`` with the commented template on first run."""
    path = improve_path()
    if not path.exists():
        try:
            paths.ensure_layout()
            path.write_text(TEMPLATE, encoding="utf-8")
        except OSError:
            log.debug("Could not create %s", path, exc_info=True)
    return path


def read_feedback() -> str:
    """The user's feedback, comments stripped, capped at a sane size.

    Empty string when the file is missing or contains only comments — callers
    treat that as "no feedback" rather than injecting an empty section.
    """
    path = ensure_template()
    try:
        raw = path.read_text(encoding="utf-8")
    except OSError:
        return ""
    lines: list[str] = []
    for line in raw.splitlines():
        stripped = line.strip()
        if stripped.startswith("#") or not stripped:
            continue
        lines.append(line)
    text = "\n".join(lines).strip()
    if len(text) > MAX_FEEDBACK_CHARS:
        text = text[:MAX_FEEDBACK_CHARS].rsplit("\n", 1)[0]
        log.warning(
            "improve.txt exceeded %d characters; truncating for the prompt.",
            MAX_FEEDBACK_CHARS,
        )
    return text


def read_channel_note(channel_id: str) -> str:
    """The per-channel feedback note, empty when absent."""
    if not channel_id:
        return ""
    path = channel_note_path(channel_id)
    try:
        return path.read_text(encoding="utf-8").strip()[:MAX_FEEDBACK_CHARS]
    except OSError:
        return ""


def write_channel_note(channel_id: str, note: str) -> None:
    """Persist the per-channel note (empty string deletes the file)."""
    path = channel_note_path(channel_id)
    if not note.strip():
        try:
            path.unlink(missing_ok=True)
        except OSError:
            log.debug("Could not remove %s", path, exc_info=True)
        return
    try:
        channels_dir().mkdir(parents=True, exist_ok=True)
        path.write_text(note.strip() + "\n", encoding="utf-8")
    except OSError:
        log.warning("Could not write %s", path, exc_info=True)


def prompt_section() -> str:
    """The feedback block appended to the detection system prompt, or ''."""
    feedback = read_feedback()
    if not feedback:
        return ""
    return (
        "\n\n## Editor feedback for this channel\n\n"
        "The channel's editor wrote these standing instructions. They override "
        "the general guidance above when they conflict:\n\n"
        f"{feedback}\n"
    )


__all__ = [
    "IMPROVE_FILENAME",
    "MAX_FEEDBACK_CHARS",
    "channel_note_path",
    "channels_dir",
    "ensure_template",
    "improve_path",
    "prompt_section",
    "read_channel_note",
    "read_feedback",
    "write_channel_note",
]
