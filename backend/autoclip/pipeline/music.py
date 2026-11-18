"""Background music library (Phase 8).

Tracks live in ``~/.autoclip/music/``. Users drop audio files there (or set an
absolute path in settings); the export stage mixes them under the speech with
optional sidechain ducking. Nothing here calls ffmpeg — resolution and
validation only — so the pipeline stage stays the single place that shells out.
"""

from __future__ import annotations

import logging
from pathlib import Path

from .. import paths

log = logging.getLogger(__name__)

AUDIO_EXTENSIONS = {".mp3", ".m4a", ".aac", ".wav", ".ogg", ".flac", ".opus"}


def music_dir() -> Path:
    return paths.config_path().parent / "music"


def list_tracks() -> list[dict[str, str]]:
    """Every track in the library: name + resolved path."""
    directory = music_dir()
    if not directory.is_dir():
        return []
    tracks = []
    for entry in sorted(directory.iterdir()):
        if entry.is_file() and entry.suffix.lower() in AUDIO_EXTENSIONS:
            tracks.append({"name": entry.name, "path": str(entry)})
    return tracks


def resolve_track(setting: str) -> Path | None:
    """Resolve the music_track setting to a real file, or None.

    Accepts a bare library filename or an absolute path. A configured track
    that does not exist is a user-visible misconfiguration: log it loudly and
    mix without the bed rather than failing an otherwise-good export.
    """
    value = setting.strip()
    if not value:
        return None
    candidate = Path(value)
    if candidate.is_absolute():
        if candidate.is_file():
            return candidate
        log.warning("Music track %r does not exist; exporting without the bed.", value)
        return None
    library = music_dir() / value
    if library.is_file():
        return library
    log.warning(
        "Music track %r is not in %s; exporting without the bed.", value, music_dir()
    )
    return None


__all__ = ["AUDIO_EXTENSIONS", "list_tracks", "music_dir", "resolve_track"]
