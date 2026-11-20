"""Database access for the music library.

The library is an *index* of files the user already owns. AutoClip never
copies them, never moves them and never deletes them: removing a track from
the library only removes the row, and the file stays where it is.

Rows are keyed by the file's absolute path, so re-scanning a folder keeps the
same track id — and therefore the same licence record — instead of orphaning
it.
"""

from __future__ import annotations

import hashlib
import json
import time
from dataclasses import dataclass
from pathlib import Path

from ..db import connection
from .analysis import Analysis
from .licensing import LicenseRecord, LicenseState

__all__ = [
    "MusicFolder",
    "MusicTrack",
    "add_folder",
    "analyse_track",
    "clear_analysis",
    "delete_track",
    "get_license",
    "get_track",
    "list_folders",
    "list_tracks",
    "remove_folder",
    "set_license",
    "set_track_flags",
    "track_id_for",
    "upsert_track",
]


def _now() -> str:
    return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())


def track_id_for(path: Path | str) -> str:
    """A stable id for a file path.

    Stable across scans on purpose: the licence record hangs off this id, and
    a new id on every scan would orphan it.
    """
    raw = str(Path(path).resolve()).casefold()
    digest = hashlib.sha1(raw.encode("utf-8", "replace")).hexdigest()[:16]
    return f"mus_{digest}"


@dataclass
class MusicFolder:
    id: str
    path: str
    added_at: str

    def to_dict(self) -> dict[str, object]:
        return {"id": self.id, "path": self.path, "added_at": self.added_at}


@dataclass
class MusicTrack:
    id: str
    path: str
    folder_id: str
    name: str
    title: str
    artist: str
    tags: str
    format: str
    size_bytes: int
    mtime: float
    duration_s: float
    analysis_at: str
    analysis: Analysis
    excluded: bool
    favourite: bool
    created_at: str
    updated_at: str

    @property
    def tag_list(self) -> list[str]:
        return [tag.strip() for tag in self.tags.split(",") if tag.strip()]

    def to_dict(self) -> dict[str, object]:
        return {
            "id": self.id,
            "path": self.path,
            "folder_id": self.folder_id,
            "name": self.name,
            "title": self.title,
            "artist": self.artist,
            "tags": self.tag_list,
            "format": self.format,
            "size_bytes": self.size_bytes,
            "mtime": self.mtime,
            "duration_s": self.duration_s,
            "analysis_at": self.analysis_at,
            "analysis": self.analysis.to_dict(),
            "excluded": self.excluded,
            "favourite": self.favourite,
            "created_at": self.created_at,
            "updated_at": self.updated_at,
        }


# --------------------------------------------------------------------------
# Folders
# --------------------------------------------------------------------------


def add_folder(path: Path | str) -> MusicFolder:
    """Record a folder the user pointed AutoClip at."""
    resolved = str(Path(path).expanduser().resolve())
    with connection() as conn:
        row = conn.execute(
            "SELECT id, path, added_at FROM music_folders WHERE path = ?", (resolved,)
        ).fetchone()
        if row is not None:
            return MusicFolder(row["id"], row["path"], row["added_at"])
        folder = MusicFolder(
            id=track_id_for(resolved),
            path=resolved,
            added_at=_now(),
        )
        conn.execute(
            "INSERT INTO music_folders (id, path, added_at) VALUES (?, ?, ?)",
            (folder.id, folder.path, folder.added_at),
        )
    return folder


def list_folders() -> list[MusicFolder]:
    with connection() as conn:
        rows = conn.execute("SELECT id, path, added_at FROM music_folders ORDER BY path").fetchall()
    return [MusicFolder(row["id"], row["path"], row["added_at"]) for row in rows]


def remove_folder(folder_id: str) -> None:
    """Forget a folder. The tracks it held stay in the library."""
    with connection() as conn:
        conn.execute("DELETE FROM music_folders WHERE id = ?", (folder_id,))
        conn.execute("UPDATE music_tracks SET folder_id = '' WHERE folder_id = ?", (folder_id,))


# --------------------------------------------------------------------------
# Tracks
# --------------------------------------------------------------------------


def _row_to_track(row) -> MusicTrack:
    return MusicTrack(
        id=row["id"],
        path=row["path"],
        folder_id=row["folder_id"],
        name=row["name"],
        title=row["title"],
        artist=row["artist"],
        tags=row["tags"],
        format=row["format"],
        size_bytes=int(row["size_bytes"]),
        mtime=float(row["mtime"]),
        duration_s=float(row["duration_s"]),
        analysis_at=row["analysis_at"],
        analysis=Analysis.from_json(row["analysis"]),
        excluded=bool(row["excluded"]),
        favourite=bool(row["favourite"]),
        created_at=row["created_at"],
        updated_at=row["updated_at"],
    )


def upsert_track(
    path: Path | str,
    *,
    folder_id: str = "",
    title: str = "",
    artist: str = "",
) -> MusicTrack:
    """Record a file in the library, keeping any analysis and licence it has."""
    resolved = Path(path).expanduser().resolve()
    stat = resolved.stat()
    identifier = track_id_for(resolved)
    stamp = _now()
    with connection() as conn:
        row = conn.execute("SELECT * FROM music_tracks WHERE id = ?", (identifier,)).fetchone()
        if row is None:
            conn.execute(
                "INSERT INTO music_tracks "
                "(id, path, folder_id, name, title, artist, tags, format, size_bytes, mtime, "
                " duration_s, analysis_at, analysis, excluded, favourite, created_at, updated_at) "
                "VALUES (?, ?, ?, ?, ?, ?, '', ?, ?, ?, 0, '', '{}', 0, 0, ?, ?)",
                (
                    identifier,
                    str(resolved),
                    folder_id,
                    resolved.name,
                    title,
                    artist,
                    resolved.suffix.lower().lstrip("."),
                    stat.st_size,
                    stat.st_mtime,
                    stamp,
                    stamp,
                ),
            )
        else:
            # The analysis is keyed by the file's size and mtime: a file that
            # has not changed keeps the measurement it already has.
            changed = (
                int(row["size_bytes"]) != stat.st_size
                or abs(float(row["mtime"]) - stat.st_mtime) > 0.001
            )
            conn.execute(
                "UPDATE music_tracks SET folder_id = ?, name = ?, format = ?, size_bytes = ?, "
                "mtime = ?, updated_at = ?"
                + (", analysis = '{}', analysis_at = '', duration_s = 0" if changed else "")
                + " WHERE id = ?",
                (
                    folder_id or row["folder_id"],
                    resolved.name,
                    resolved.suffix.lower().lstrip("."),
                    stat.st_size,
                    stat.st_mtime,
                    stamp,
                    identifier,
                ),
            )
        fresh = conn.execute("SELECT * FROM music_tracks WHERE id = ?", (identifier,)).fetchone()
    return _row_to_track(fresh)


def get_track(track_id: str) -> MusicTrack | None:
    with connection() as conn:
        row = conn.execute("SELECT * FROM music_tracks WHERE id = ?", (track_id,)).fetchone()
    return _row_to_track(row) if row is not None else None


def list_tracks(*, include_excluded: bool = False) -> list[MusicTrack]:
    query = "SELECT * FROM music_tracks"
    if not include_excluded:
        query += " WHERE excluded = 0"
    query += " ORDER BY name"
    with connection() as conn:
        rows = conn.execute(query).fetchall()
    return [_row_to_track(row) for row in rows]


def delete_track(track_id: str) -> None:
    """Remove a track from the library. The file itself is untouched."""
    with connection() as conn:
        conn.execute("DELETE FROM music_tracks WHERE id = ?", (track_id,))
        conn.execute("DELETE FROM music_licenses WHERE track_id = ?", (track_id,))


def set_track_flags(
    track_id: str,
    *,
    favourite: bool | None = None,
    excluded: bool | None = None,
    tags: str | None = None,
    title: str | None = None,
    artist: str | None = None,
) -> MusicTrack | None:
    updates: list[str] = []
    values: list[object] = []
    if favourite is not None:
        updates.append("favourite = ?")
        values.append(1 if favourite else 0)
    if excluded is not None:
        updates.append("excluded = ?")
        values.append(1 if excluded else 0)
    if tags is not None:
        updates.append("tags = ?")
        values.append(tags)
    if title is not None:
        updates.append("title = ?")
        values.append(title)
    if artist is not None:
        updates.append("artist = ?")
        values.append(artist)
    if not updates:
        return get_track(track_id)
    updates.append("updated_at = ?")
    values.append(_now())
    values.append(track_id)
    with connection() as conn:
        conn.execute(f"UPDATE music_tracks SET {', '.join(updates)} WHERE id = ?", values)
    return get_track(track_id)


def analyse_track(track_id: str, analysis: Analysis) -> MusicTrack | None:
    """Store a measurement against a track."""
    with connection() as conn:
        conn.execute(
            "UPDATE music_tracks SET analysis = ?, analysis_at = ?, duration_s = ?, updated_at = ? "
            "WHERE id = ?",
            (
                analysis.to_json(),
                _now(),
                analysis.duration_s,
                _now(),
                track_id,
            ),
        )
    return get_track(track_id)


def clear_analysis(track_id: str) -> None:
    with connection() as conn:
        conn.execute(
            "UPDATE music_tracks SET analysis = '{}', analysis_at = '', updated_at = ? "
            "WHERE id = ?",
            (_now(), track_id),
        )


# --------------------------------------------------------------------------
# Licences
# --------------------------------------------------------------------------


def get_license(track_id: str) -> LicenseRecord:
    """The licence record for a track. Unknown when there is none."""
    with connection() as conn:
        row = conn.execute(
            "SELECT * FROM music_licenses WHERE track_id = ?", (track_id,)
        ).fetchone()
    if row is None:
        return LicenseRecord(track_id=track_id, state=LicenseState.UNKNOWN)
    return LicenseRecord(
        track_id=row["track_id"],
        state=row["state"],
        source=row["source"],
        evidence=row["evidence"],
        attribution=row["attribution"],
        commercial_use=bool(row["commercial_use"]),
        non_commercial=bool(row["non_commercial"]),
        derivative=bool(row["derivative"]),
        share_alike=bool(row["share_alike"]),
        expires_at=row["expires_at"],
        verified_by=row["verified_by"],
        verified_at=row["verified_at"],
        updated_at=row["updated_at"],
    )


def set_license(record: LicenseRecord) -> LicenseRecord:
    """Store a licence record."""
    record.updated_at = _now()
    with connection() as conn:
        conn.execute(
            "INSERT INTO music_licenses "
            "(track_id, state, source, evidence, attribution, commercial_use, non_commercial, "
            " derivative, share_alike, expires_at, verified_by, verified_at, updated_at) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?) "
            "ON CONFLICT(track_id) DO UPDATE SET state = excluded.state, source = excluded.source, "
            "evidence = excluded.evidence, attribution = excluded.attribution, "
            "commercial_use = excluded.commercial_use, non_commercial = excluded.non_commercial, "
            "derivative = excluded.derivative, share_alike = excluded.share_alike, "
            "expires_at = excluded.expires_at, verified_by = excluded.verified_by, "
            "verified_at = excluded.verified_at, updated_at = excluded.updated_at",
            (
                record.track_id,
                record.state,
                record.source,
                record.evidence,
                record.attribution,
                1 if record.commercial_use else 0,
                1 if record.non_commercial else 0,
                1 if record.derivative else 0,
                1 if record.share_alike else 0,
                record.expires_at,
                record.verified_by,
                record.verified_at,
                record.updated_at,
            ),
        )
    return record


def licence_states_for(track_ids: list[str]) -> dict[str, str]:
    """The licence state of each track, for listing."""
    if not track_ids:
        return {}
    placeholders = ",".join("?" for _ in track_ids)
    with connection() as conn:
        rows = conn.execute(
            f"SELECT track_id, state FROM music_licenses WHERE track_id IN ({placeholders})",
            track_ids,
        ).fetchall()
    states = {row["track_id"]: row["state"] for row in rows}
    return {track_id: states.get(track_id, LicenseState.UNKNOWN) for track_id in track_ids}


def dump_tracks() -> str:
    """A JSON dump of the library. Used by the selection code."""
    tracks = list_tracks(include_excluded=True)
    return json.dumps([track.to_dict() for track in tracks], ensure_ascii=False)
