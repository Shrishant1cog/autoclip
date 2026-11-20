"""Notification centre (Phase 14).

An autonomous pipeline runs for minutes at a time; the user is not watching it.
Something has to tell them what happened while they were away — a job that
finished, an upload that failed, a clip that did not survive validation.

This module is the one place that knows how to describe those events. Call
sites stay one-liners, and every notification carries the real values from
the run that produced it: the clip's own title, the upload's own error
string, the number of clips actually found.

Two rules:

* **A notification never breaks the work it describes.** Every helper is
  wrapped so a failed insert is logged and swallowed — a full disk must not
  fail a publish.
* **Nothing is fabricated.** The wording says what happened; the counts come
  from the rows, not from an estimate.
"""

from __future__ import annotations

import logging
from typing import Any

from ..db import store
from ..db.models import Notification, new_id

log = logging.getLogger(__name__)

#: The inbox never grows without bound.
MAX_NOTIFICATIONS = 500


def notify(
    kind: str,
    *,
    severity: str = "info",
    title: str,
    body: str = "",
    link: str = "",
    entity_id: str = "",
) -> Notification | None:
    """Record one notification. Returns None when it could not be stored."""
    try:
        notification = Notification(
            id=new_id(),
            kind=kind,
            severity=severity,  # type: ignore[arg-type]
            title=title,
            body=body,
            link=link,
            entity_id=entity_id,
        )
        store.create_notification(notification)
    except Exception:  # noqa: BLE001 - a notification must never break the run
        log.warning("Could not store the %r notification.", kind, exc_info=True)
        return None

    try:
        store.prune_notifications(MAX_NOTIFICATIONS)
    except Exception:  # noqa: BLE001
        log.debug("Could not prune the notification inbox.", exc_info=True)
    return notification


# --------------------------------------------------------------------------
# Event helpers
# --------------------------------------------------------------------------


def job_done(job_id: str, title: str, clip_count: int) -> Notification | None:
    """The pipeline finished a video and found clips in it."""
    plural = "clip" if clip_count == 1 else "clips"
    return notify(
        "job_done",
        severity="success",
        title=f"Finished “{title}”",
        body=f"Found {clip_count} {plural}.",
        link=f"/jobs/{job_id}/clips",
        entity_id=job_id,
    )


def job_failed(job_id: str, title: str, error: str) -> Notification | None:
    """The pipeline could not finish a video."""
    return notify(
        "job_failed",
        severity="error",
        title=f"“{title}” failed",
        body=error.strip()[:500] or "Unknown error.",
        link=f"/jobs/{job_id}",
        entity_id=job_id,
    )


def clip_exported(
    clip_id: str, title: str, *, ok: bool, failures: list[str] | None = None
) -> Notification | None:
    """A clip was rendered — either cleanly or not."""
    if ok:
        return notify(
            "clip_exported",
            severity="success",
            title=f"Exported “{title}”",
            body="The render passed every validation check.",
            link="/clips",
            entity_id=clip_id,
        )
    detail = "; ".join(failures or []) or "Unknown validation failure."
    return notify(
        "clip_invalid",
        severity="warning",
        title=f"“{title}” failed validation",
        body=f"{detail}. It was not published.",
        link="/clips",
        entity_id=clip_id,
    )


def upload_done(
    upload_id: str,
    title: str,
    video_id: str,
    channel_title: str = "",
    privacy_note: str = "",
) -> Notification | None:
    """A clip was published to YouTube.

    ``privacy_note`` says when YouTube did something other than what was
    asked for — most often forcing a public video private because the
    API project has not been audited. The notification then says the
    video was uploaded but is not visible, rather than claiming it was
    published.
    """
    where = f" to {channel_title}" if channel_title else ""
    body = f"Published{where}."
    if video_id:
        body += f" https://youtu.be/{video_id}"
    if privacy_note:
        body += f" {privacy_note}"
    return notify(
        "upload_done",
        severity="success",
        title=f"Published “{title}”",
        body=body,
        link="/clips",
        entity_id=upload_id,
    )


def upload_failed(upload_id: str, title: str, error: str) -> Notification | None:
    """An upload could not be published."""
    return notify(
        "upload_failed",
        severity="error",
        title=f"Could not publish “{title}”",
        body=error.strip()[:500] or "Unknown error.",
        link="/clips",
        entity_id=upload_id,
    )


def upload_skipped(upload_id: str, title: str, reason: str) -> Notification | None:
    """An upload was deliberately not made (a duplicate, usually)."""
    return notify(
        "upload_skipped",
        severity="info",
        title=f"Skipped “{title}”",
        body=reason.strip()[:500] or "Skipped.",
        link="/clips",
        entity_id=upload_id,
    )


def batch_done(batch_id: str, name: str, done: int, failed: int) -> Notification | None:
    """A batch queue finished."""
    body = f"{done} finished"
    if failed:
        body += f", {failed} failed"
    return notify(
        "batch_done",
        severity="warning" if failed else "success",
        title=f"Batch “{name}” finished",
        body=f"{body}.",
        link="/clips",
        entity_id=batch_id,
    )


def provider_unavailable(detail: str) -> Notification | None:
    """Every AI provider failed — the pipeline cannot continue."""
    return notify(
        "provider_unavailable",
        severity="error",
        title="No AI provider is available",
        body=detail.strip()[:500]
        or "Every provider in the fallback chain failed. Add a key in Settings.",
        link="/settings",
    )


def app_restarted(*, jobs: int = 0, uploads: int = 0, batch_items: int = 0) -> Notification | None:
    """AutoClip restarted and picked interrupted work back up.

    Only says something when something was actually resumed: a restart with
    nothing in flight is the normal case and does not deserve a notification.

    The wording agrees with the count — "1 job that was interrupted" reads
    like something a person wrote, "1 job that were interrupted" does not.
    """
    total = jobs + uploads + batch_items
    if total == 0:
        return None

    parts = []
    for count, noun in (
        (jobs, "job"),
        (uploads, "upload"),
        (batch_items, "batch item"),
    ):
        if count:
            parts.append(f"{count} {noun}{'s' if count != 1 else ''}")

    return notify(
        "app_restarted",
        severity="warning",
        title="AutoClip restarted",
        body=(f"Resumed {', '.join(parts)} that {'was' if total == 1 else 'were'} interrupted."),
        link="/recovery",
    )


def context_snapshot(extra: dict[str, Any] | None = None) -> dict[str, Any]:
    """A small summary of the inbox, for the UI badge."""
    payload: dict[str, Any] = {
        "unread": store.unread_notification_count(),
        "total": len(store.list_notifications(limit=MAX_NOTIFICATIONS)),
    }
    if extra:
        payload.update(extra)
    return payload


__all__ = [
    "MAX_NOTIFICATIONS",
    "app_restarted",
    "batch_done",
    "clip_exported",
    "context_snapshot",
    "job_done",
    "job_failed",
    "notify",
    "provider_unavailable",
    "upload_done",
    "upload_failed",
    "upload_skipped",
]
