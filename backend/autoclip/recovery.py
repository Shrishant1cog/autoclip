"""Recovery centre (Phase 15).

Failed work is scattered across the job table, the upload table and the
validation reports. Before this, the user had to know which screen to open to
find it. Now there is one list: everything that failed, classified, with the
action that would fix it.

The list is read-only — the retries themselves go through the endpoints that
already own them (retry a job, retry an upload), so nothing here can start
work behind the user's back.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Any

from . import errors
from .db import store

log = logging.getLogger(__name__)

#: How many of each kind to surface.
MAX_JOBS = 25
MAX_UPLOADS = 25
MAX_CLIPS = 25


@dataclass
class RecoveryItem:
    """One failure and the action that would resolve it."""

    kind: str
    id: str
    title: str
    detail: str
    code: str = errors.INTERNAL
    retryable: bool = False
    action: str = ""
    action_label: str = ""
    link: str = ""
    entity_id: str = ""
    created_at: str = ""
    extra: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "kind": self.kind,
            "id": self.id,
            "title": self.title,
            "detail": self.detail,
            "code": self.code,
            "retryable": self.retryable,
            "action": self.action,
            "action_label": self.action_label,
            "link": self.link,
            "entity_id": self.entity_id,
            "created_at": self.created_at,
            **({"extra": self.extra} if self.extra else {}),
        }


def _source_titles() -> dict[str, str]:
    titles: dict[str, str] = {}
    for source in store.list_sources(limit=1000):
        titles[source.id] = source.title or source.filename or source.id
    return titles


def failed_jobs(titles: dict[str, str]) -> list[RecoveryItem]:
    """Jobs that failed and can be requeued."""
    items: list[RecoveryItem] = []
    for job in store.list_jobs(limit=200, status="failed"):
        if len(items) >= MAX_JOBS:
            break
        info = errors.classify_text(job.error or "The job failed without an error message.")
        items.append(
            RecoveryItem(
                kind="job",
                id=job.id,
                title=titles.get(job.source_id, job.source_id),
                detail=job.error or "The job failed without an error message.",
                code=info.code,
                retryable=True,
                action=f"/api/jobs/{job.id}/retry",
                action_label="Run it again",
                link=f"/jobs/{job.id}",
                entity_id=job.id,
                created_at=job.updated_at,
                extra={"stage": job.current_stage},
            )
        )
    return items


def _superseded(clip_id: str, failed_at: str, exports_by_clip: dict[str, list]) -> bool:
    """True when the clip has been rendered again since the failure.

    Recovering an upload by re-rendering creates a new export and a new
    upload row; the original failed row stays in the database as history.
    Without this check it would sit in the recovery list forever, asking for
    a fix that has already been applied.
    """
    newest = ""
    for export in exports_by_clip.get(clip_id, []):
        if export.created_at > newest:
            newest = export.created_at
    return bool(newest) and newest > failed_at


def failed_uploads(titles: dict[str, str]) -> list[RecoveryItem]:
    """Uploads that failed and can be recovered.

    The action depends on *why* it failed. A rate limit or a dropped
    connection is worth retrying — the file is fine and the network was not.
    A missing file is not: retrying the upload would fail in exactly the
    same way, so the fix is to render the clip again and publish the new
    file. Offering an action that cannot work would be worse than offering
    none.
    """
    items: list[RecoveryItem] = []
    exports_by_clip: dict[str, list] = {}
    for upload in store.list_all_uploads():
        if len(items) >= MAX_UPLOADS:
            break
        if upload.status != "failed":
            continue
        if upload.clip_id not in exports_by_clip:
            exports_by_clip[upload.clip_id] = store.list_exports(upload.clip_id)
        if _superseded(upload.clip_id, upload.updated_at, exports_by_clip):
            continue

        info = errors.classify_text(upload.error or "The upload failed.")
        clip = store.get_clip(upload.clip_id)
        title = upload.title or (clip.title if clip else upload.clip_id)

        if info.code == errors.NOT_FOUND:
            action = f"/api/clips/{upload.clip_id}/export"
            action_label = "Render it again"
            retryable = True
        else:
            action = f"/api/youtube/uploads/{upload.id}/retry"
            action_label = "Try publishing again"
            retryable = info.code in errors.RETRYABLE_CODES or info.code == errors.INTERNAL

        items.append(
            RecoveryItem(
                kind="upload",
                id=upload.id,
                title=title,
                detail=upload.error or "The upload failed.",
                code=info.code,
                retryable=retryable,
                action=action,
                action_label=action_label,
                link="/clips",
                entity_id=upload.clip_id,
                created_at=upload.updated_at,
            )
        )
    return items


def invalid_clips(titles: dict[str, str]) -> list[RecoveryItem]:
    """Clips whose render failed validation and were therefore not published."""
    items: list[RecoveryItem] = []
    for clip in store.list_all_clips(limit=1000):
        if len(items) >= MAX_CLIPS:
            break
        if clip.status != "invalid":
            continue
        failed = [
            check["name"]
            for check in (clip.validation or {}).get("checks", [])
            if not check.get("ok", True)
        ]
        items.append(
            RecoveryItem(
                kind="clip",
                id=clip.id,
                title=clip.title or f"Clip {clip.rank}",
                detail=(
                    "Failed validation: " + (", ".join(failed) or "unknown check")
                    if failed
                    else "Failed validation."
                ),
                code=errors.MEDIA,
                retryable=True,
                action=f"/api/clips/{clip.id}/export",
                action_label="Render it again",
                link="/clips",
                entity_id=clip.id,
                created_at=clip.created_at,
                extra={"failed_checks": failed},
            )
        )
    return items


def build_report() -> dict[str, Any]:
    """Every recoverable failure, newest first within each kind."""
    titles = _source_titles()
    items = failed_jobs(titles) + failed_uploads(titles) + invalid_clips(titles)
    return {
        "items": [item.to_dict() for item in items],
        "counts": {
            "job": len(failed_jobs(titles)),
            "upload": len(failed_uploads(titles)),
            "clip": len(invalid_clips(titles)),
            "total": len(items),
        },
    }


__all__ = [
    "MAX_CLIPS",
    "MAX_JOBS",
    "MAX_UPLOADS",
    "RecoveryItem",
    "build_report",
    "failed_jobs",
    "failed_uploads",
    "invalid_clips",
]
