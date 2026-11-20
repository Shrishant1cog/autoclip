"""The music library — folders the user points AutoClip at, and what is in them.

Three things happen here, and they are deliberately separate:

* **Scanning** finds files. It never copies them, never renames them and
  never deletes them. The library is an index; the music stays where the
  user put it.
* **Analysis** measures a track once and caches the result against the file's
  size and mtime, so an unchanged file is never measured twice.
* **Licensing** records what the user knows about a track's rights and gates
  the export on it.

The old fixed ``~/.autoclip/music/`` directory is still supported: it is
treated as one more folder in the library, so existing users keep their bed.
"""

from __future__ import annotations

import contextlib
import logging
from dataclasses import dataclass, field
from pathlib import Path

from ..pipeline import music as legacy_music
from . import store
from .analysis import Analysis, AnalysisError, analyze_track
from .licensing import LicenseBlocked, LicenseRecord, LicenseState, evaluate

log = logging.getLogger(__name__)

__all__ = [
    "LibraryTrack",
    "ScanReport",
    "analyse",
    "check_export_allowed",
    "library_folders",
    "list_tracks",
    "scan",
    "search",
]


@dataclass
class LibraryTrack:
    """A track as the library sees it, with its licence attached."""

    track: store.MusicTrack
    license: LicenseRecord
    allowed: bool
    reason: str = ""
    warnings: list[str] | None = None

    def to_dict(self) -> dict[str, object]:
        data = self.track.to_dict()
        data["license"] = self.license.to_dict()
        data["license_allowed"] = self.allowed
        data["license_reason"] = self.reason
        data["license_warnings"] = self.warnings or []
        return data


@dataclass
class ScanReport:
    """What a scan found."""

    folders: int = 0
    found: int = 0
    added: int = 0
    skipped: int = 0
    errors: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, object]:
        return {
            "folders": self.folders,
            "found": self.found,
            "added": self.added,
            "skipped": self.skipped,
            "errors": list(self.errors),
        }


def library_folders() -> list[Path]:
    """Every folder the library reads from, including the legacy directory."""
    folders: list[Path] = []
    legacy = legacy_music.music_dir()
    if legacy.is_dir():
        folders.append(legacy)
    for folder in store.list_folders():
        path = Path(folder.path)
        if path.is_dir() and path not in folders:
            folders.append(path)
    return folders


def scan(*, folder: Path | str | None = None) -> ScanReport:
    """Index the audio files in the library.

    A file that has not changed keeps its analysis and its licence; a file
    that has changed is re-indexed and its analysis is dropped, so a stale
    measurement can never be used for a different file.
    """
    report = ScanReport()
    folders = [Path(folder).expanduser().resolve()] if folder else library_folders()
    report.folders = len(folders)

    for directory in folders:
        if not directory.is_dir():
            report.errors.append(f"{directory} is not a folder.")
            continue
        folder_id = ""
        for known in store.list_folders():
            if Path(known.path) == directory:
                folder_id = known.id
                break
        if not folder_id:
            folder_id = store.add_folder(directory).id

        for entry in sorted(directory.rglob("*")):
            if not entry.is_file():
                continue
            if entry.suffix.lower() not in legacy_music.AUDIO_EXTENSIONS:
                continue
            report.found += 1
            try:
                existing = store.get_track(store.track_id_for(entry))
                store.upsert_track(entry, folder_id=folder_id)
            except OSError as exc:
                report.skipped += 1
                report.errors.append(f"{entry.name}: {exc}")
                continue
            if existing is None:
                report.added += 1
            else:
                report.skipped += 1
    return report


def list_tracks(*, include_excluded: bool = False) -> list[LibraryTrack]:
    """Every track, with its licence and whether it may be used."""
    tracks = store.list_tracks(include_excluded=include_excluded)
    out: list[LibraryTrack] = []
    for track in tracks:
        record = store.get_license(track.id)
        verdict = evaluate(record)
        out.append(
            LibraryTrack(
                track=track,
                license=record,
                allowed=verdict.allowed,
                reason=verdict.reason,
                warnings=verdict.warnings,
            )
        )
    return out


def search(
    *,
    query: str = "",
    mood: str = "",
    min_bpm: float | None = None,
    max_bpm: float | None = None,
    licence_state: str = "",
    favourite_only: bool = False,
    tag: str = "",
) -> list[LibraryTrack]:
    """Filter the library.

    Every filter runs on the server so the result set is the same whether it
    is fetched by the Settings screen or by the selection code.
    """
    needle = query.strip().casefold()
    wanted_licence = licence_state.strip()
    wanted_tag = tag.strip().casefold()

    results: list[LibraryTrack] = []
    for entry in list_tracks():
        track = entry.track
        if favourite_only and not track.favourite:
            continue
        if needle:
            haystack = " ".join(
                [track.name, track.title, track.artist, track.tags, track.analysis.mood]
            ).casefold()
            if needle not in haystack:
                continue
        if mood and track.analysis.mood.casefold() != mood.casefold():
            continue
        if wanted_tag and wanted_tag not in [t.casefold() for t in track.tag_list]:
            continue
        if min_bpm is not None and track.analysis.bpm < min_bpm:
            continue
        if max_bpm is not None and track.analysis.bpm > max_bpm:
            continue
        if wanted_licence and entry.license.state != wanted_licence:
            continue
        results.append(entry)
    return results


def analyse(track_id: str, *, force: bool = False) -> store.MusicTrack:
    """Measure a track and cache the result."""
    track = store.get_track(track_id)
    if track is None:
        raise KeyError(f"No track {track_id!r}.")

    path = Path(track.path)
    if not path.is_file():
        raise AnalysisError(f"{track.name} is no longer at {path}.")

    if not force and track.analysis_at and track.analysis.bpm_confidence >= 0:
        # The cached measurement is keyed by size and mtime, so a file that has
        # not changed does not need to be measured again.
        stat = path.stat()
        if stat.st_size == track.size_bytes and abs(stat.st_mtime - track.mtime) < 0.001:
            return track

    measurement: Analysis = analyze_track(path)
    updated = store.analyse_track(track_id, measurement)
    assert updated is not None
    return updated


def check_export_allowed(track_id: str) -> LicenseRecord:
    """Raise :class:`LicenseBlocked` when the track may not be used.

    This is the export gate. It is called before the bed is mixed in, so a
    blocked track never reaches the renderer.
    """
    record = store.get_license(track_id)
    verdict = evaluate(record)
    if not verdict.allowed:
        track = store.get_track(track_id)
        raise LicenseBlocked(
            verdict.reason,
            state=verdict.state,
            track_name=track.name if track else track_id,
        )
    return record


def check_export_allowed_for_path(path: Path | str) -> LicenseRecord:
    """The export gate, for a track chosen by path.

    A track the user pointed at directly is indexed on the way through, so it
    appears in the library and the user has somewhere to record its licence.
    """
    resolved = Path(path).expanduser().resolve()
    identifier = store.track_id_for(resolved)
    if store.get_track(identifier) is None:
        # The file may have been deleted between the choice and the export.
        # The licence check still applies, and an unindexed track has no
        # licence, so it is blocked.
        with contextlib.suppress(OSError):
            store.upsert_track(resolved)
    return check_export_allowed(identifier)


def licence_state(track_id: str) -> str:
    return store.get_license(track_id).state


def unknown_licence_count() -> int:
    """How many tracks still need a licence answer. Shown in Settings."""
    count = 0
    for entry in list_tracks():
        if entry.license.state == LicenseState.UNKNOWN:
            count += 1
    return count
