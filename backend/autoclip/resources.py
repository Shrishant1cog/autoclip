"""Resource accounting and reclamation (Phase 16).

An unattended AutoClip install accumulates three kinds of load, and none of
them announce themselves:

* **Disk.** Every job leaves a scratch directory holding a decoded WAV of the
  whole source (a one-hour video is roughly 300 MB), a transcript, crop paths
  and thumbnails. Every clip leaves a rendered MP4. Nothing was ever removed,
  so a few dozen videos fill a disk.
* **CPU.** ffmpeg defaults to one worker thread per core, and AutoClip can
  have several ffmpeg processes alive at once — preparing the next source
  while exporting the last clip. On a small machine that thrashes.
* **Tokens.** Detection sends one prompt per transcript window and the
  provider's default output cap differs per vendor, so the cost of a job is
  neither bounded nor visible.

This module owns the answers to all three: what is being used (:func:`disk_usage`),
what may be spent (:func:`ConcurrencyGate`, the settings in
:mod:`autoclip.config`), and what may be reclaimed (:func:`cleanup`).

Two rules govern every deletion here:

* **Never delete work the user can still want.** A failed job keeps its
  scratch directory so "run it again" resumes instead of re-transcribing. An
  unpublished clip is never deleted. An uploaded source file is never deleted,
  because it cannot be downloaded again.
* **Never delete something a live row points at.** A queued or running job's
  files, and the file behind a pending upload, are untouchable.
"""

from __future__ import annotations

import contextlib
import logging
import shutil
import threading
from collections.abc import Iterator
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from pathlib import Path

from . import paths
from .config import Settings
from .db import store

log = logging.getLogger(__name__)


# --------------------------------------------------------------------------
# Units
# --------------------------------------------------------------------------

_UNITS = ("B", "KB", "MB", "GB", "TB", "PB")


def format_bytes(size: float) -> str:
    """A human-readable size. Uses binary units, because that is what disk
    tools report."""
    value = float(size)
    for unit in _UNITS:
        if abs(value) < 1024.0 or unit == _UNITS[-1]:
            if unit == "B":
                return f"{int(value)} {unit}"
            return f"{value:.1f} {unit}"
        value /= 1024.0
    return f"{value:.1f} {_UNITS[-1]}"


def _parse_timestamp(value: str | None) -> datetime | None:
    """Parse an ISO-8601 timestamp from the database."""
    if not value:
        return None
    try:
        parsed = datetime.fromisoformat(value)
    except ValueError:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=UTC)
    return parsed


# --------------------------------------------------------------------------
# Usage accounting
# --------------------------------------------------------------------------


@dataclass
class TokenUsage:
    """Tokens spent on one or more model calls.

    Populated from what the provider actually reports, never estimated — an
    estimate that is wrong in the direction of "cheap" would make the cost
    control look like it works when it does not.
    """

    calls: int = 0
    input_tokens: int = 0
    output_tokens: int = 0

    @property
    def total_tokens(self) -> int:
        return self.input_tokens + self.output_tokens

    def add(self, other: TokenUsage) -> None:
        self.calls += other.calls
        self.input_tokens += other.input_tokens
        self.output_tokens += other.output_tokens

    def snapshot(self) -> TokenUsage:
        """A copy of this counter.

        Safe to keep while the original keeps changing — which is what a
        concurrent caller needs when it wants "what happened since I looked".
        """
        return TokenUsage(
            calls=self.calls,
            input_tokens=self.input_tokens,
            output_tokens=self.output_tokens,
        )

    def delta(self, later: TokenUsage) -> TokenUsage:
        """What was added between this snapshot and ``later``.

        Clamped at zero: a counter that went backwards would be a bug, and
        reporting a negative cost would be worse than reporting none.
        """
        return TokenUsage(
            calls=max(0, later.calls - self.calls),
            input_tokens=max(0, later.input_tokens - self.input_tokens),
            output_tokens=max(0, later.output_tokens - self.output_tokens),
        )

    def to_dict(self) -> dict[str, int]:
        return {
            "calls": self.calls,
            "input_tokens": self.input_tokens,
            "output_tokens": self.output_tokens,
            "total_tokens": self.total_tokens,
        }


@dataclass
class Usage:
    """Everything one job consumed.

    Passed down through the pipeline stages so the numbers are gathered where
    the work actually happens, rather than guessed from the outside.
    """

    llm: TokenUsage = field(default_factory=TokenUsage)
    ffmpeg_runs: int = 0
    ffmpeg_seconds: float = 0.0
    export_bytes: int = 0
    #: Transcript windows that were never sent to the model because the call
    #: budget ran out. Non-zero means the job analysed less of the video than
    #: its length suggests, and that has to be said out loud.
    windows_skipped: int = 0

    def to_dict(self) -> dict[str, object]:
        return {
            "llm": self.llm.to_dict(),
            "ffmpeg_runs": self.ffmpeg_runs,
            "ffmpeg_seconds": round(self.ffmpeg_seconds, 3),
            "export_bytes": self.export_bytes,
            "windows_skipped": self.windows_skipped,
        }


# --------------------------------------------------------------------------
# Concurrency
# --------------------------------------------------------------------------


class ConcurrencyGate:
    """A counting gate that lets at most ``limit`` callers through at once.

    :class:`threading.Semaphore` cannot be resized once created, and the limit
    here is a user setting that can change while the app is running, so this
    keeps its own counter instead.
    """

    def __init__(self, limit: int = 2) -> None:
        self._condition = threading.Condition()
        self._limit = max(1, int(limit))
        self._active = 0

    @property
    def limit(self) -> int:
        with self._condition:
            return self._limit

    @property
    def active(self) -> int:
        with self._condition:
            return self._active

    def set_limit(self, limit: int) -> None:
        """Change the limit. Callers already inside keep their slot."""
        with self._condition:
            self._limit = max(1, int(limit))
            self._condition.notify_all()

    @contextlib.contextmanager
    def slot(self) -> Iterator[None]:
        """Hold one slot for the duration of the block."""
        with self._condition:
            while self._active >= self._limit:
                self._condition.wait()
            self._active += 1
        try:
            yield
        finally:
            with self._condition:
                self._active -= 1
                self._condition.notify()


#: The process-wide ffmpeg gate. Every ffmpeg and ffprobe invocation takes a
#: slot, so a thumbnail pass cannot run on top of an export.
ffmpeg_gate = ConcurrencyGate(2)


def apply_ffmpeg_limit(settings: Settings | None = None) -> None:
    """Push the configured ffmpeg limits onto the process-wide gate."""
    from .config import load

    settings = settings or load()
    ffmpeg_gate.set_limit(settings.resources.max_parallel_ffmpeg)


# --------------------------------------------------------------------------
# Disk usage
# --------------------------------------------------------------------------


@dataclass
class DirectoryUsage:
    """How much space one directory holds."""

    name: str
    path: str
    size_bytes: int = 0
    file_count: int = 0

    def to_dict(self) -> dict[str, object]:
        return {
            "name": self.name,
            "path": self.path,
            "size_bytes": self.size_bytes,
            "file_count": self.file_count,
            "size_human": format_bytes(self.size_bytes),
        }


@dataclass
class DiskUsage:
    """The whole picture: what AutoClip is using, and how much of it is waste."""

    directories: list[DirectoryUsage] = field(default_factory=list)
    database_bytes: int = 0

    @property
    def total_bytes(self) -> int:
        return sum(d.size_bytes for d in self.directories) + self.database_bytes

    def to_dict(self) -> dict[str, object]:
        return {
            "directories": [d.to_dict() for d in self.directories],
            "database_bytes": self.database_bytes,
            "database_human": format_bytes(self.database_bytes),
            "total_bytes": self.total_bytes,
            "total_human": format_bytes(self.total_bytes),
        }


def _measure(directory: Path) -> tuple[int, int]:
    """Total bytes and file count under ``directory``.

    Symlinks are not followed: a link into the user's media library would
    otherwise be counted (and, in a cleanup, deleted) as if it were ours.
    """
    total = 0
    count = 0
    if not directory.exists():
        return 0, 0
    for path in directory.rglob("*"):
        if path.is_symlink():
            continue
        try:
            if path.is_file():
                total += path.stat().st_size
                count += 1
        except OSError:  # pragma: no cover - a file vanished mid-scan
            continue
    return total, count


def disk_usage() -> DiskUsage:
    """Measure what AutoClip is currently using on disk."""
    usage = DiskUsage()
    for name, directory in (
        ("raw", paths.raw_dir()),
        ("media", paths.media_dir()),
        ("work", paths.work_dir()),
        ("exports", paths.exports_dir()),
    ):
        size, count = _measure(directory)
        usage.directories.append(
            DirectoryUsage(name=name, path=str(directory), size_bytes=size, file_count=count)
        )

    db_path = paths.db_path()
    if db_path.exists():
        usage.database_bytes = db_path.stat().st_size
    return usage


# --------------------------------------------------------------------------
# Cleanup
# --------------------------------------------------------------------------


@dataclass
class CleanupReport:
    """What a cleanup pass actually did."""

    removed_files: int = 0
    removed_directories: int = 0
    freed_bytes: int = 0
    details: list[str] = field(default_factory=list)

    @property
    def changed(self) -> bool:
        return self.removed_files > 0 or self.removed_directories > 0

    def to_dict(self) -> dict[str, object]:
        return {
            "removed_files": self.removed_files,
            "removed_directories": self.removed_directories,
            "freed_bytes": self.freed_bytes,
            "freed_human": format_bytes(self.freed_bytes),
            "details": list(self.details),
            "changed": self.changed,
        }


def _remove_file(path: Path, report: CleanupReport, label: str) -> None:
    try:
        size = path.stat().st_size
    except OSError:
        size = 0
    try:
        path.unlink()
    except OSError as exc:
        log.warning("Could not remove %s: %s", path, exc)
        return
    report.removed_files += 1
    report.freed_bytes += size
    report.details.append(f"{label}: {path.name}")


def _remove_tree(path: Path, report: CleanupReport, label: str) -> None:
    size, _ = _measure(path)
    try:
        shutil.rmtree(path)
    except OSError as exc:
        log.warning("Could not remove %s: %s", path, exc)
        return
    report.removed_directories += 1
    report.freed_bytes += size
    report.details.append(f"{label}: {path.name}")


def _cutoff(days: int) -> datetime | None:
    """The instant before which something is old enough to reclaim."""
    if days <= 0:
        return None
    return datetime.now(UTC) - timedelta(days=days)


def _clean_work(report: CleanupReport, settings: Settings) -> None:
    """Remove scratch directories of jobs that are finished and past retention.

    A failed job keeps its scratch directory: that is what lets "run it again"
    resume from the transcript instead of transcribing the video again.
    """
    cutoff = _cutoff(settings.resources.work_retention_days)
    if cutoff is None:
        return

    live = {job.id for job in store.list_jobs(limit=1000, status="running")}
    live |= {job.id for job in store.list_jobs(limit=1000, status="queued")}

    for job in store.list_jobs(limit=1000):
        if job.id in live or job.status not in ("done", "cancelled"):
            continue
        finished = _parse_timestamp(job.finished_at) or _parse_timestamp(job.updated_at)
        if finished is None or finished > cutoff:
            continue
        directory = paths.job_work_dir(job.id)
        if directory.exists():
            _remove_tree(directory, report, "work")


def _clean_exports(report: CleanupReport, settings: Settings) -> None:
    """Remove rendered files of clips that are already published.

    The export row stays: it is the record that the clip was published, and
    the duplicate check reads it. Only the file goes, and the download link
    answers honestly that the file is gone.
    """
    cutoff = _cutoff(settings.resources.export_retention_days)
    if cutoff is None:
        return

    live = _live_job_ids()
    for export in store.list_all_exports():
        created = _parse_timestamp(export.created_at)
        if created is None or created > cutoff:
            continue
        clip = store.get_clip(export.clip_id)
        if clip is not None and clip.job_id in live:
            continue
        uploads = store.list_uploads_for_export(export.id)
        if not uploads or not any(u.status == "done" for u in uploads):
            continue
        if any(u.status in ("pending", "uploading") for u in uploads):
            continue
        path = Path(export.path)
        if path.exists():
            _remove_file(path, report, "export")
        # The thumbnail and subtitle sidecar belong to the export; leaving
        # them behind would keep the space and show a picture of a clip the
        # user can no longer open.
        for sibling in _export_siblings(path):
            if sibling.exists():
                _remove_file(sibling, report, "export sidecar")


def _clean_raw(report: CleanupReport, settings: Settings) -> None:
    """Remove downloaded YouTube videos that are past retention.

    Only YouTube sources: an uploaded file is the user's own and cannot be
    fetched again, so it is never deleted automatically.
    """
    cutoff = _cutoff(settings.resources.raw_retention_days)
    if cutoff is None:
        return

    for source in store.list_sources(limit=1000):
        if source.type != "youtube":
            continue
        path = Path(source.path)
        if not path.exists():
            continue
        try:
            modified = datetime.fromtimestamp(path.stat().st_mtime, UTC)
        except OSError:
            continue
        if modified > cutoff:
            continue
        _remove_file(path, report, "raw")


def _live_job_ids() -> set[str]:
    """The jobs that are queued or running right now.

    Their files are untouchable: a render writes the file *before* the
    database row that describes it, so a cleanup running at that moment
    would see an unreferenced file and delete a clip the job is about to
    publish.
    """
    live: set[str] = set()
    for status in ("running", "queued"):
        live |= {job.id for job in store.list_jobs(limit=1000, status=status)}
    return live


def _export_siblings(path: Path) -> list[Path]:
    """The files that belong to one export beside the video itself.

    The thumbnail is the video path with a ``.jpg`` suffix, and the subtitle
    sidecar (when enabled) is the same with ``.srt``. They are artifacts of
    the export, not separate rows — without this, a cleanup would delete the
    thumbnail of a clip it was supposed to keep.
    """
    return [path.with_suffix(".jpg"), path.with_suffix(".srt")]


def _clean_orphans(report: CleanupReport) -> None:
    """Remove files that no database row points at any more.

    These are the leftovers of a crash between writing a file and recording
    the row. Nothing references them, so nothing can miss them.
    """
    known_exports: set[Path] = set()
    for export in store.list_all_exports():
        path = Path(export.path)
        known_exports.add(path.resolve())
        for sibling in _export_siblings(path):
            known_exports.add(sibling.resolve())

    exports_root = paths.exports_dir()
    live = _live_job_ids()
    if exports_root.exists():
        for path in exports_root.rglob("*"):
            if not path.is_file() or path.is_symlink():
                continue
            with contextlib.suppress(OSError):
                if path.resolve() in known_exports:
                    continue
                # A live job's directory holds files it has rendered but not
                # yet recorded; those are not orphans.
                if live & {parent.name for parent in path.parents}:
                    continue
                _remove_file(path, report, "orphan export")

    # A source owns the directory its file lives in, including the sidecars
    # yt-dlp writes beside the video (``.info.json``, ``.part``, thumbnails).
    # Ownership is derived from the row's own path rather than from a
    # reconstructed ``media/{source_id}`` layout, so a source stored
    # anywhere else is still protected.
    sources = store.list_sources(limit=1000)
    known_sources = {Path(s.path).resolve() for s in sources}
    roots = {paths.raw_dir().resolve(), paths.media_dir().resolve()}
    source_dirs: set[Path] = set()
    for source in sources:
        parent = Path(source.path).resolve().parent
        # A file sitting directly in the root does not own the whole root.
        if parent not in roots:
            source_dirs.add(parent)

    for name, directory in (("raw", paths.raw_dir()), ("media", paths.media_dir())):
        if not directory.exists():
            continue
        for path in directory.rglob("*"):
            if not path.is_file() or path.is_symlink():
                continue
            with contextlib.suppress(OSError):
                resolved = path.resolve()
                if resolved in known_sources:
                    continue
                if any(parent in source_dirs for parent in resolved.parents):
                    continue
                _remove_file(path, report, f"orphan {name}")

    known_jobs = {job.id for job in store.list_jobs(limit=1000)}
    work_root = paths.work_dir()
    if work_root.exists():
        for directory in work_root.iterdir():
            if not directory.is_dir() or directory.name in known_jobs:
                continue
            _remove_tree(directory, report, "orphan work")


def _vacuum() -> None:
    """Reclaim free pages in the database file.

    Deleting rows frees pages but does not shrink the file; VACUUM does. It
    cannot run inside a transaction, so it is issued on its own.
    """
    from .db import connection

    try:
        with connection() as conn:
            conn.commit()
            conn.execute("VACUUM")
    except Exception as exc:  # pragma: no cover - VACUUM is best-effort
        log.debug("Could not vacuum the database: %s", exc)


def cleanup(settings: Settings | None = None, *, vacuum: bool = True) -> CleanupReport:
    """Reclaim what the retention settings allow, and report what went.

    Never raises for a single failed deletion — one locked file must not stop
    the rest of the cleanup.
    """
    from .config import load

    settings = settings or load()
    report = CleanupReport()

    _clean_work(report, settings)
    _clean_exports(report, settings)
    _clean_raw(report, settings)
    _clean_orphans(report)

    if report.changed and vacuum:
        _vacuum()

    if report.changed:
        log.info(
            "Cleanup removed %d file(s) and %d directory(ies), freeing %s.",
            report.removed_files,
            report.removed_directories,
            format_bytes(report.freed_bytes),
        )
    return report


__all__ = [
    "CleanupReport",
    "ConcurrencyGate",
    "DirectoryUsage",
    "DiskUsage",
    "TokenUsage",
    "Usage",
    "apply_ffmpeg_limit",
    "cleanup",
    "disk_usage",
    "ffmpeg_gate",
    "format_bytes",
]
