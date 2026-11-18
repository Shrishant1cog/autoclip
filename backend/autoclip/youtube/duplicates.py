"""Find uploads that would put the same clip on YouTube twice.

Automation re-exports, a manual "Export again", or a retry after a crash can
each leave more than one upload row pointing at the same moment of the same
video. YouTube has no idempotency key, so the only defence is to look before
sending. This module is that look:

* **same clip** — a clip already published, with another row still waiting.
* **identical file** — two rows whose exported MP4s hash to the same bytes.
* **same title** — an opt-in check for repeated titles across clips, which
  usually means the model produced near-identical metadata for two moments.
Detection is read-only unless :func:`skip_duplicates` is called, which turns
queued duplicate rows into ``skipped`` so the worker never sends them. The
worker also calls :func:`conflict_for` immediately before every upload, so an
automation run cannot publish the same clip twice even if nobody runs the
script. In-flight uploads are reported but never interrupted.
"""

from __future__ import annotations

import hashlib
import re
from collections import defaultdict
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Literal

from ..db import store
from ..db.models import YouTubeUpload

Reason = Literal["same-clip", "identical-file", "same-title"]

REASON_LABELS: dict[str, str] = {
    "same-clip": "clip already on YouTube",
    "identical-file": "identical exported file",
    "same-title": "same title already used",
}

#: Rows the worker may still pick up (or that a user could retry by hand).
_ACTIONABLE = {"pending", "uploading"}


def destination_channel_id(channel_row_id: str, cache: dict[str, str] | None = None) -> str:
    """The YouTube channel id an upload row targets.

    Two rows are the same destination when they resolve to the same YouTube
    channel — not when they name the same internal row. The legacy path stores
    ``''`` instead of a channel row, but it targets the connected channel,
    which is the same UC id as the imported channel profile. Comparing raw row
    ids would therefore treat a re-export of an already-published clip as a
    fresh destination and publish it a second time.

    The result is a YouTube channel id (``UC…``) where one can be resolved, and
    a namespaced fallback otherwise so two genuinely different destinations
    never collide.
    """
    cache = cache if cache is not None else {}
    if channel_row_id in cache:
        return cache[channel_row_id]

    resolved = ""
    if channel_row_id:
        try:
            from . import accounts as accounts_store

            channel = accounts_store.get_channel(channel_row_id)
            if channel and channel.get("channel_id"):
                resolved = str(channel["channel_id"])
        except Exception:  # noqa: BLE001
            resolved = ""
        if not resolved:
            resolved = f"row:{channel_row_id}"
    else:
        # The legacy single-account path: the connected channel.
        try:
            from .. import config

            legacy = config.load().youtube.channel_id
            if legacy:
                resolved = legacy
        except Exception:  # noqa: BLE001
            resolved = ""
        if not resolved:
            try:
                from . import accounts as accounts_store

                default = accounts_store.default_channel()
                if default and default.get("channel_id"):
                    resolved = str(default["channel_id"])
            except Exception:  # noqa: BLE001
                resolved = ""
        if not resolved:
            resolved = "legacy"

    cache[channel_row_id] = resolved
    return resolved


@dataclass
class DuplicateGroup:
    """One primary upload plus the rows that would duplicate it."""

    reason: Reason
    keep: YouTubeUpload
    duplicates: list[YouTubeUpload] = field(default_factory=list)

    @property
    def actionable(self) -> list[YouTubeUpload]:
        """Duplicates a skip run can safely stop."""
        return [row for row in self.duplicates if row.status == "pending"]


def conflict_for(upload: YouTubeUpload) -> YouTubeUpload | None:
    """Return another upload this row would duplicate, if any.

    This is the last line of defence used by the worker, so it stays cheap and
    conservative: same clip only (byte-identical detection lives in the script,
    where hashing is acceptable). A finished upload always wins, then one that is
    already in flight, then an earlier queued row. That last case stops a
    double-enqueue from publishing twice even before the worker touches YouTube.
    """
    rows = store.list_all_uploads()

    done: list[YouTubeUpload] = []
    in_flight: list[YouTubeUpload] = []
    queued: list[YouTubeUpload] = []
    destinations: dict[str, str] = {}
    target = destination_channel_id(upload.channel_row_id, destinations)
    for row in rows:
        if row.id == upload.id:
            continue
        # The same clip legitimately fans out to several channels; a duplicate
        # is only a duplicate within one destination channel. The destination
        # is the YouTube channel, so the legacy row and its imported profile
        # count as the same place.
        if row.clip_id != upload.clip_id:
            continue
        if destination_channel_id(row.channel_row_id, destinations) != target:
            continue
        if row.status == "done":
            done.append(row)
        elif row.status == "uploading":
            in_flight.append(row)
        elif row.status == "pending" and _is_earlier(row, upload):
            queued.append(row)

    if done:
        return _keep_order(done)[0]
    if in_flight:
        return _keep_order(in_flight)[0]
    # A row that is already uploading has been past this check once; only a
    # finished upload may stop it now.
    if upload.status != "uploading" and queued:
        return _keep_order(queued)[0]
    return None


def _is_earlier(row: YouTubeUpload, upload: YouTubeUpload) -> bool:
    return (row.created_at, row.id) < (upload.created_at, upload.id)


def find_duplicates(
    *,
    include_failed: bool = False,
    by_title: bool = False,
    check_files: bool = True,
) -> list[DuplicateGroup]:
    """Return every duplicate group, primary first."""
    rows = store.list_all_uploads()
    if not rows:
        return []

    claimed: set[str] = set()
    groups: list[DuplicateGroup] = []

    for group in _same_clip(rows, include_failed):
        groups.append(group)
        claimed.update(row.id for row in group.duplicates)

    if check_files:
        for group in _identical_files(rows, include_failed, claimed):
            groups.append(group)
            claimed.update(row.id for row in group.duplicates)

    if by_title:
        for group in _same_title(rows, claimed):
            groups.append(group)
            claimed.update(row.id for row in group.duplicates)

    return groups


def _is_candidate(row: YouTubeUpload, include_failed: bool) -> bool:
    return row.status in _ACTIONABLE or (include_failed and row.status == "failed")


def _keep_order(rows: list[YouTubeUpload]) -> list[YouTubeUpload]:
    """Prefer a finished upload, then the oldest row, as the one to keep."""
    return sorted(rows, key=lambda row: (row.status != "done", row.created_at, row.id))


def _same_clip(rows: list[YouTubeUpload], include_failed: bool) -> list[DuplicateGroup]:
    by_clip: dict[tuple[str, str], list[YouTubeUpload]] = defaultdict(list)
    for row in rows:
        by_clip[(row.clip_id, row.channel_row_id)].append(row)

    groups: list[DuplicateGroup] = []
    for clip_rows in by_clip.values():
        done = [row for row in clip_rows if row.status == "done"]
        if not done:
            continue
        keep = _keep_order(done)[0]
        duplicates = [
            row for row in clip_rows if row.id != keep.id and _is_candidate(row, include_failed)
        ]
        if duplicates:
            groups.append(
                DuplicateGroup(reason="same-clip", keep=keep, duplicates=_keep_order(duplicates))
            )
    return groups


def _identical_files(
    rows: list[YouTubeUpload], include_failed: bool, claimed: set[str]
) -> list[DuplicateGroup]:
    """Hash exports only when two uploads share a file size, so singles are free."""
    by_size: dict[tuple[int, str], list[tuple[YouTubeUpload, Path]]] = defaultdict(list)
    for row in rows:
        export = store.get_export(row.export_id)
        if export is None:
            continue
        path = Path(export.path)
        try:
            size = path.stat().st_size
        except OSError:
            continue
        if size > 0:
            by_size[(size, row.channel_row_id)].append((row, path))

    groups: list[DuplicateGroup] = []
    for same_size in by_size.values():
        if len(same_size) < 2:
            continue

        by_digest: dict[str, list[YouTubeUpload]] = defaultdict(list)
        for row, path in same_size:
            digest = _sha256(path)
            if digest:
                by_digest[digest].append(row)

        for same_bytes in by_digest.values():
            if len(same_bytes) < 2:
                continue
            keep = _keep_order(same_bytes)[0]
            duplicates = [
                row
                for row in _keep_order(same_bytes)
                if row.id != keep.id
                and row.id not in claimed
                and _is_candidate(row, include_failed)
            ]
            if duplicates:
                groups.append(
                    DuplicateGroup(reason="identical-file", keep=keep, duplicates=duplicates)
                )
    return groups


def _same_title(rows: list[YouTubeUpload], claimed: set[str]) -> list[DuplicateGroup]:
    by_title: dict[tuple[str, str], list[YouTubeUpload]] = defaultdict(list)
    destinations: dict[str, str] = {}
    for row in rows:
        if row.id in claimed:
            continue
        title = _normalise(row.title)
        if title:
            # Group by the resolved YouTube channel, so a legacy row and its
            # imported channel profile are recognised as the same place.
            key = (title, destination_channel_id(row.channel_row_id, destinations))
            by_title[key].append(row)

    groups: list[DuplicateGroup] = []
    for same_title in by_title.values():
        if len(same_title) < 2:
            continue
        keep = _keep_order(same_title)[0]
        duplicates = [row for row in _keep_order(same_title) if row.id != keep.id]
        if duplicates:
            groups.append(DuplicateGroup(reason="same-title", keep=keep, duplicates=duplicates))
    return groups


def _normalise(title: str) -> str:
    return re.sub(r"\s+", " ", title.strip().lower())


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    try:
        with path.open("rb") as handle:
            for chunk in iter(lambda: handle.read(1024 * 1024), b""):
                digest.update(chunk)
    except OSError:
        return ""
    return digest.hexdigest()


def skip_duplicates(groups: list[DuplicateGroup]) -> tuple[int, int]:
    """Mark duplicate rows as skipped. Returns ``(skipped, left_in_flight)``.

    Only ``pending`` rows are touched: an ``uploading`` row is already talking to
    YouTube and rewriting its status would race the worker, so it is reported as
    left alone instead of silently mislabelled.
    """
    skipped = 0
    in_flight = 0

    for group in groups:
        keep = group.keep
        reference = keep.video_id or keep.id
        reason = (
            "Skipped as a duplicate: this clip is already queued or "
            f"published as upload {reference}."
        )
        for row in group.duplicates:
            if row.status == "pending":
                store.update_upload(row.id, status="skipped", error=reason)
                row.status = "skipped"
                row.error = reason
                skipped += 1
            elif row.status == "uploading":
                in_flight += 1

    return skipped, in_flight


def describe(
    row: YouTubeUpload, *, path: Path | None = None, size: int | None = None
) -> dict[str, Any]:
    """A JSON-friendly view used by the report and the script."""
    return {
        "id": row.id,
        "clip_id": row.clip_id,
        "export_id": row.export_id,
        "status": row.status,
        "video_id": row.video_id,
        "watch_url": f"https://youtu.be/{row.video_id}" if row.video_id else "",
        "title": row.title,
        "privacy": row.privacy,
        "error": row.error,
        "created_at": row.created_at,
        "export_path": str(path) if path else "",
        "size_bytes": size,
    }


def as_json(groups: list[DuplicateGroup]) -> list[dict[str, Any]]:
    payload: list[dict[str, Any]] = []
    for group in groups:
        payload.append(
            {
                "reason": group.reason,
                "label": REASON_LABELS[group.reason],
                "keep": _describe_row(group.keep),
                "duplicates": [_describe_row(row) for row in group.duplicates],
                "actionable": len(group.actionable),
            }
        )
    return payload


def _describe_row(row: YouTubeUpload) -> dict[str, Any]:
    path, size = _export_file(row)
    return describe(row, path=path, size=size)


def _export_file(row: YouTubeUpload) -> tuple[Path | None, int | None]:
    export = store.get_export(row.export_id)
    if export is None:
        return None, None
    path = Path(export.path)
    try:
        return path, path.stat().st_size
    except OSError:
        return path, None
