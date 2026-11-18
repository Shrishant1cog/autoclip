"""Analytics for clip outcomes (Phase 11).

Learning starts with honest numbers. This module aggregates what actually
happened to clips — how many were kept, discarded, exported, published — so the
learning engine and the UI reason over evidence instead of guesses.

Two aggregate views exist:

* **Score bands** — do high-scoring clips survive contact with the user?
  If clips scored 85+ are routinely discarded while 60s get exported, the
  prompt's scoring calibration is off.
* **Per-channel outcomes** — which destinations actually receive content.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from ..db import store

#: Score bands used for calibration reporting.
BANDS: tuple[tuple[str, int, int], ...] = (
    ("85-100", 85, 100),
    ("70-84", 70, 84),
    ("50-69", 50, 69),
    ("0-49", 0, 49),
)


@dataclass
class BandOutcome:
    """What happened to clips in one score band."""

    band: str
    total: int = 0
    kept: int = 0
    discarded: int = 0
    exported: int = 0
    uploaded: int = 0
    trimmed: int = 0

    def to_dict(self) -> dict[str, Any]:
        return {
            "band": self.band,
            "total": self.total,
            "kept": self.kept,
            "discarded": self.discarded,
            "exported": self.exported,
            "uploaded": self.uploaded,
            "trimmed": self.trimmed,
            "keep_rate": round(self.kept / self.total, 3) if self.total else 0.0,
            "export_rate": round(self.exported / self.total, 3) if self.total else 0.0,
        }


@dataclass
class ChannelOutcome:
    """Upload outcomes for one destination channel."""

    channel_row_id: str
    channel_title: str
    total: int = 0
    done: int = 0
    failed: int = 0
    skipped: int = 0
    pending: int = 0

    def to_dict(self) -> dict[str, Any]:
        return {
            "channel_row_id": self.channel_row_id,
            "channel_title": self.channel_title,
            "total": self.total,
            "done": self.done,
            "failed": self.failed,
            "skipped": self.skipped,
            "pending": self.pending,
        }


@dataclass
class PipelineSummary:
    """Top-line counts for the whole library."""

    clips: int = 0
    exported: int = 0
    invalid: int = 0
    discarded: int = 0
    uploads_done: int = 0
    uploads_failed: int = 0
    sources: int = 0
    validation_failures: dict[str, int] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "clips": self.clips,
            "exported": self.exported,
            "invalid": self.invalid,
            "discarded": self.discarded,
            "uploads_done": self.uploads_done,
            "uploads_failed": self.uploads_failed,
            "sources": self.sources,
            "validation_failures": dict(sorted(
                self.validation_failures.items(), key=lambda kv: -kv[1]
            )),
        }


def _band_for(score: int) -> str:
    for name, low, high in BANDS:
        if low <= score <= high:
            return name
    return "0-49"


def score_band_outcomes() -> list[BandOutcome]:
    """Outcome counts per score band over every clip ever produced."""
    bands = {name: BandOutcome(band=name) for name, _, _ in BANDS}
    uploads_by_clip: dict[str, int] = {}
    for upload in store.list_all_uploads():
        uploads_by_clip[upload.clip_id] = uploads_by_clip.get(upload.clip_id, 0) + 1

    for clip in store.list_all_clips(limit=100000):
        band = bands[_band_for(max(clip.score, 0))]
        band.total += 1
        if clip.status == "kept":
            band.kept += 1
        elif clip.status == "discarded":
            band.discarded += 1
        if clip.status in ("exported", "invalid"):
            band.exported += 1
        if clip.user_trimmed:
            band.trimmed += 1
        if uploads_by_clip.get(clip.id):
            band.uploaded += 1
    return [bands[name] for name, _, _ in BANDS]


def channel_outcomes() -> list[ChannelOutcome]:
    """Upload counts grouped by destination channel row."""
    titles: dict[str, str] = {}
    try:
        from ..youtube import accounts as accounts_store

        titles = {row["id"]: row["title"] for row in accounts_store.list_channels()}
    except Exception:  # noqa: BLE001 - analytics must never raise
        pass

    order: list[str] = []
    stats: dict[str, ChannelOutcome] = {}
    for upload in store.list_all_uploads():
        key = upload.channel_row_id or ""
        if key not in stats:
            label = (
                titles.get(key, "Unknown channel") if key else "Default channel (legacy)"
            )
            stats[key] = ChannelOutcome(channel_row_id=key, channel_title=label)
            order.append(key)
        row = stats[key]
        row.total += 1
        if upload.status in ("done", "failed", "skipped", "pending"):
            setattr(row, upload.status, getattr(row, upload.status) + 1)
    return [stats[key] for key in order]


def pipeline_summary() -> PipelineSummary:
    """Whole-library counters, including the most common validation failures."""
    summary = PipelineSummary()
    for clip in store.list_all_clips(limit=100000):
        summary.clips += 1
        if clip.status == "exported":
            summary.exported += 1
        elif clip.status == "invalid":
            summary.invalid += 1
        elif clip.status == "discarded":
            summary.discarded += 1
        if clip.validation and not clip.validation.get("ok", True):
            for check in clip.validation.get("checks", []):
                if not check.get("ok", True):
                    summary.validation_failures[check["name"]] = (
                        summary.validation_failures.get(check["name"], 0) + 1
                    )
    for upload in store.list_all_uploads():
        if upload.status == "done":
            summary.uploads_done += 1
        elif upload.status == "failed":
            summary.uploads_failed += 1
    summary.sources = len(store.list_sources(limit=100000))
    return summary


__all__ = [
    "BANDS",
    "BandOutcome",
    "ChannelOutcome",
    "PipelineSummary",
    "channel_outcomes",
    "pipeline_summary",
    "score_band_outcomes",
]
