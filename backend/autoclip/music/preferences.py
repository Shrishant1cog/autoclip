"""The user's music choice, at three scopes.

The scopes are separate rows rather than one row with three columns,
because a clip's choice has to survive the source's choice being changed,
and clearing one scope must not clear another.

The most specific scope wins: **clip**, then **source**, then **global**,
then the automatic selection.

An empty track id means "no preference at this scope" rather than "no
music". A clip with no preference falls back to its source's choice, and a
source with no preference falls back to the global one. Turning the music
off is a separate, explicit act — the global preference is set to the
sentinel ``none``, which is not the same as being unset.
"""

from __future__ import annotations

import time
from dataclasses import dataclass

from ..db import connection

__all__ = [
    "MusicPreference",
    "NO_MUSIC",
    "SCOPE_CLIP",
    "SCOPE_GLOBAL",
    "SCOPE_SOURCE",
    "clear_preference",
    "get_preference",
    "resolve_preference",
    "set_preference",
]

SCOPE_GLOBAL = "global"
SCOPE_SOURCE = "source"
SCOPE_CLIP = "clip"

#: The sentinel that means "no music at all", as distinct from "no
#: preference here".
NO_MUSIC = "__none__"


def _now() -> str:
    return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())


@dataclass
class MusicPreference:
    """One stored music choice."""

    scope: str
    scope_id: str = ""
    track_id: str = ""
    updated_at: str = ""

    @property
    def is_none(self) -> bool:
        """True when this scope says "no music"."""
        return self.track_id == NO_MUSIC

    @property
    def is_set(self) -> bool:
        """True when this scope says something about the music."""
        return bool(self.track_id)

    def to_dict(self) -> dict[str, object]:
        return {
            "scope": self.scope,
            "scope_id": self.scope_id,
            "track_id": "" if self.is_none else self.track_id,
            "none": self.is_none,
            "updated_at": self.updated_at,
        }


def get_preference(scope: str, scope_id: str = "") -> MusicPreference | None:
    """The preference stored for one scope, or ``None``."""
    try:
        with connection() as conn:
            row = conn.execute(
                "SELECT * FROM music_preferences WHERE scope = ? AND scope_id = ?",
                (scope, scope_id),
            ).fetchone()
    except Exception:  # noqa: BLE001 - an unmigrated database has no table yet
        return None
    if row is None:
        return None
    return MusicPreference(
        scope=str(row["scope"]),
        scope_id=str(row["scope_id"]),
        track_id=str(row["track_id"]),
        updated_at=str(row["updated_at"]),
    )


def set_preference(scope: str, scope_id: str, track_id: str) -> MusicPreference:
    """Store a preference. An empty track id clears the scope."""
    if scope not in (SCOPE_GLOBAL, SCOPE_SOURCE, SCOPE_CLIP):
        raise ValueError(f"Unknown music preference scope {scope!r}.")

    if not track_id:
        return clear_preference(scope, scope_id) or MusicPreference(scope=scope, scope_id=scope_id)

    now = _now()
    with connection() as conn:
        conn.execute(
            """
            INSERT INTO music_preferences (scope, scope_id, track_id, updated_at)
            VALUES (?, ?, ?, ?)
            ON CONFLICT(scope, scope_id) DO UPDATE SET
                track_id = excluded.track_id,
                updated_at = excluded.updated_at
            """,
            (scope, scope_id, track_id, now),
        )
    return MusicPreference(scope=scope, scope_id=scope_id, track_id=track_id, updated_at=now)


def clear_preference(scope: str, scope_id: str = "") -> MusicPreference | None:
    """Forget a scope's preference."""
    try:
        with connection() as conn:
            conn.execute(
                "DELETE FROM music_preferences WHERE scope = ? AND scope_id = ?",
                (scope, scope_id),
            )
    except Exception:  # noqa: BLE001 - an unmigrated database has no table yet
        return None
    return get_preference(scope, scope_id)


def resolve_preference(
    *,
    clip_id: str = "",
    source_id: str = "",
) -> tuple[str, str]:
    """The music choice that applies, and where it came from.

    Returns ``(track_id, scope)``. An empty ``track_id`` means "no
    preference anywhere" — the automatic selection decides. The sentinel
    ``NO_MUSIC`` means the user turned the music off, and it is returned as
    is, because it is an answer and not a gap.
    """
    if clip_id:
        clip = get_preference(SCOPE_CLIP, clip_id)
        if clip is not None and clip.is_set:
            return (clip.track_id, SCOPE_CLIP)

    if source_id:
        source = get_preference(SCOPE_SOURCE, source_id)
        if source is not None and source.is_set:
            return (source.track_id, SCOPE_SOURCE)

    global_pref = get_preference(SCOPE_GLOBAL, "")
    if global_pref is not None and global_pref.is_set:
        return (global_pref.track_id, SCOPE_GLOBAL)

    return ("", "")
