"""Project context for the assistant (Phase 13).

The assistant can only be as useful as what it can see, and as trustworthy as
that view is. This module assembles a **snapshot of real project state** from
the database, the settings file, the learning feedback and the trend cache —
nothing else. Every fact here can be traced back to a row or a file.

The snapshot is deliberately small: a prompt has a budget, and a long tail of
old rows is less useful than the recent state plus the failures. The assistant
is told explicitly that this is the whole of its knowledge, which is what keeps
it from inventing facts.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Any

from .. import config
from ..db import store

log = logging.getLogger(__name__)

#: How many recent rows to include in the snapshot.
RECENT_JOBS = 8
RECENT_CLIPS = 15
MAX_FAILURES = 8


@dataclass
class ProjectContext:
    """A read-only snapshot of everything the assistant knows."""

    summary: dict[str, Any] = field(default_factory=dict)
    settings: dict[str, Any] = field(default_factory=dict)
    jobs: list[dict[str, Any]] = field(default_factory=list)
    clips: list[dict[str, Any]] = field(default_factory=list)
    failures: list[dict[str, Any]] = field(default_factory=list)
    channels: list[dict[str, Any]] = field(default_factory=list)
    routing: list[dict[str, Any]] = field(default_factory=list)
    feedback: str = ""
    trends: dict[str, Any] = field(default_factory=dict)
    focus: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "summary": self.summary,
            "settings": self.settings,
            "jobs": self.jobs,
            "clips": self.clips,
            "failures": self.failures,
            "channels": self.channels,
            "routing": self.routing,
            "feedback": self.feedback,
            "trends": self.trends,
            "focus": self.focus,
        }

    def as_prompt(self) -> str:
        """Render the snapshot as the factual brief handed to the model."""
        lines: list[str] = []

        summary = self.summary
        if summary:
            lines.append("## Library summary")
            lines.append(
                f"- {summary.get('clips', 0)} clips produced, "
                f"{summary.get('exported', 0)} exported, "
                f"{summary.get('invalid', 0)} failed validation, "
                f"{summary.get('discarded', 0)} discarded"
            )
            lines.append(
                f"- {summary.get('uploads_done', 0)} uploads published, "
                f"{summary.get('uploads_failed', 0)} upload failures, "
                f"{summary.get('sources', 0)} source videos"
            )
            failures = summary.get("validation_failures") or {}
            if failures:
                top = ", ".join(f"{name} ({count})" for name, count in list(failures.items())[:5])
                lines.append(f"- Common failed validation checks: {top}")

        if self.settings:
            lines.append("")
            lines.append("## Current settings")
            for key, value in self.settings.items():
                lines.append(f"- {key}: {value}")

        if self.jobs:
            lines.append("")
            lines.append("## Recent jobs")
            for job in self.jobs:
                detail = (
                    f"- [{job['status']}] {job['source_title']} "
                    f"(stage: {job['stage'] or 'n/a'}, provider: {job['provider'] or 'n/a'})"
                )
                if job.get("error"):
                    detail += f" — error: {job['error']}"
                lines.append(detail)

        if self.clips:
            lines.append("")
            lines.append("## Recent clips")
            for clip in self.clips:
                lines.append(
                    f"- {clip['title']!r} from {clip['source_title']} "
                    f"— score {clip['score']}, {clip['duration_s']}s, status {clip['status']}"
                )
                if clip.get("reason"):
                    lines.append(f"  reason given: {clip['reason']}")
                if clip.get("hook"):
                    lines.append(f"  hook: {clip['hook']}")
                if clip.get("upload_status"):
                    lines.append(
                        f"  upload: {clip['upload_status']}"
                        + (f" ({clip['upload_error']})" if clip.get("upload_error") else "")
                    )

        if self.failures:
            lines.append("")
            lines.append("## Failures")
            for failure in self.failures:
                lines.append(f"- {failure['kind']}: {failure['detail']}")

        if self.channels:
            lines.append("")
            lines.append("## YouTube channels")
            for channel in self.channels:
                lines.append(
                    f"- {channel['title']} ({channel['channel_id']}) "
                    f"— privacy {channel['privacy']}, auto-upload "
                    f"{'on' if channel['auto_upload'] else 'off'}"
                )

        if self.routing:
            lines.append("")
            lines.append("## Routing rules")
            for rule in self.routing:
                detail = (
                    f"- priority {rule['priority']}: {rule['name'] or 'unnamed rule'} "
                    f"(keyword '{rule['keyword']}') → {rule['target_label']}"
                )
                if rule.get("extra_label"):
                    detail += f", plus {rule['extra_label']}"
                if not rule.get("enabled"):
                    detail += " [disabled]"
                lines.append(detail)

        if self.feedback:
            lines.append("")
            lines.append("## Standing instructions from the user")
            lines.append(self.feedback)

        if self.trends:
            lines.append("")
            lines.append("## Current trends")
            for video in self.trends.get("videos", [])[:8]:
                lines.append(f"- {video['title']} ({video['view_count']:,} views)")
            for theme in self.trends.get("themes", [])[:5]:
                lines.append(f"  theme: {theme.get('theme', '')} ({theme.get('fit', '')} fit)")

        if self.focus:
            lines.append("")
            lines.append("## The item in question")
            for key, value in self.focus.items():
                lines.append(f"- {key}: {value}")

        return "\n".join(lines).strip()


def _source_title(source_id: str, titles: dict[str, str]) -> str:
    return titles.get(source_id, source_id)


def _clip_focus(clip_id: str) -> dict[str, Any]:
    """Everything known about one clip — the "why was this chosen?" detail."""
    clip = store.get_clip(clip_id)
    if clip is None:
        return {}
    job = store.get_job(clip.job_id)
    source = store.get_source(clip.job_id and job.source_id) if job else None
    uploads = store.list_uploads_for_clip(clip.id)
    focus: dict[str, Any] = {
        "clip_id": clip.id,
        "title": clip.title,
        "hook": clip.hook,
        "score": clip.score,
        "status": clip.status,
        "start_s": clip.start_s,
        "end_s": clip.end_s,
        "duration_s": round(clip.duration_s, 2),
        "reason": clip.reason,
        "user_trimmed": clip.user_trimmed,
        "source": source.title if source else "",
        "job_status": job.status if job else "",
        "job_error": job.error if job and job.error else "",
        "exports": len(store.list_exports(clip.id)),
    }
    if uploads:
        upload = uploads[0]
        focus["upload_status"] = upload.status
        focus["upload_error"] = upload.error or ""
        focus["upload_title"] = upload.title
    if clip.validation:
        failed = [
            check["name"]
            for check in clip.validation.get("checks", [])
            if not check.get("ok", True)
        ]
        focus["validation_ok"] = bool(clip.validation.get("ok", True))
        focus["validation_failures"] = ", ".join(failed) or "none"
    return focus


def _job_focus(job_id: str) -> dict[str, Any]:
    job = store.get_job(job_id)
    if job is None:
        return {}
    source = store.get_source(job.source_id)
    clips = store.list_clips(job_id)
    focus: dict[str, Any] = {
        "job_id": job.id,
        "status": job.status,
        "stage": job.current_stage,
        "progress": job.progress,
        "provider": job.provider,
        "error": job.error or "",
        "source": source.title if source else job.source_id,
        "clips_found": len(clips),
    }
    for clip in clips:
        focus[f"clip_{clip.rank}"] = (
            f"{clip.title} (score {clip.score}, {clip.status}) — {clip.reason}"
        )
    return focus


def build_context(
    settings: config.Settings | None = None, *, clip_id: str = "", job_id: str = ""
) -> ProjectContext:
    """Assemble the project snapshot the assistant reasons over."""
    settings = settings or config.load()
    context = ProjectContext()

    try:
        from ..learning import analytics

        context.summary = analytics.pipeline_summary().to_dict()
    except Exception as exc:  # noqa: BLE001
        log.debug("Could not build the library summary: %s", exc)
        context.summary = {}

    context.settings = {
        "active AI provider": settings.active_provider,
        "clip length range (s)": f"{settings.clips.min_duration_s}-{settings.clips.max_duration_s}",
        "max clips per video": settings.clips.max_clips,
        "export ratio": settings.export.ratio,
        "caption style": settings.export.caption_style,
        "background music": settings.export.music_track or "none",
        "auto-upload": "on" if settings.youtube.auto_upload else "off",
        "transcription engine": settings.transcription.engine,
    }

    sources = store.list_sources(limit=1000)
    titles = {source.id: (source.title or source.filename or source.id) for source in sources}

    for job in store.list_jobs(limit=RECENT_JOBS):
        context.jobs.append(
            {
                "id": job.id,
                "status": job.status,
                "stage": job.current_stage,
                "progress": job.progress,
                "provider": job.provider,
                "error": job.error or "",
                "source_title": _source_title(job.source_id, titles),
            }
        )

    uploads_by_clip: dict[str, Any] = {}
    for upload in store.list_all_uploads():
        uploads_by_clip.setdefault(upload.clip_id, upload)

    for clip in store.list_all_clips(limit=RECENT_CLIPS):
        job = store.get_job(clip.job_id)
        upload = uploads_by_clip.get(clip.id)
        context.clips.append(
            {
                "id": clip.id,
                "title": clip.title,
                "hook": clip.hook,
                "score": clip.score,
                "status": clip.status,
                "duration_s": round(clip.duration_s, 2),
                "reason": clip.reason,
                "source_title": _source_title(job.source_id if job else "", titles),
                "upload_status": upload.status if upload else "",
                "upload_error": upload.error or "" if upload else "",
            }
        )

    for job in store.list_jobs(limit=50, status="failed"):
        if len(context.failures) >= MAX_FAILURES:
            break
        context.failures.append(
            {
                "kind": "job failed",
                "detail": f"{_source_title(job.source_id, titles)}: {job.error or 'unknown error'}",
            }
        )
    for upload in store.list_all_uploads():
        if len(context.failures) >= MAX_FAILURES:
            break
        if upload.status == "failed":
            context.failures.append(
                {
                    "kind": "upload failed",
                    "detail": (
                        f"{upload.title or upload.clip_id}: {upload.error or 'unknown error'}"
                    ),
                }
            )

    try:
        from ..youtube import accounts as accounts_store

        for channel in accounts_store.list_channels():
            context.channels.append(
                {
                    "title": channel.get("title") or channel.get("channel_id"),
                    "channel_id": channel.get("channel_id", ""),
                    "privacy": channel.get("privacy", ""),
                    "auto_upload": bool(channel.get("auto_upload")),
                }
            )
    except Exception as exc:  # noqa: BLE001
        log.debug("Could not list channels: %s", exc)

    try:
        from ..routing import classifier

        channel_titles = {channel["channel_id"]: channel["title"] for channel in context.channels}
        for rule in classifier.list_rules():
            target = rule.get("target_channel_id", "")
            label = channel_titles.get(target, target or "no channel")
            extras = rule.get("extra_channel_ids") or []
            extra_label = ", ".join(channel_titles.get(e, e) for e in extras)
            context.routing.append(
                {
                    "priority": rule.get("priority", 0),
                    "name": rule.get("name", ""),
                    "keyword": rule.get("match_keyword", ""),
                    "enabled": bool(rule.get("enabled")),
                    "target_label": label,
                    "extra_label": extra_label,
                }
            )
    except Exception as exc:  # noqa: BLE001
        log.debug("Could not list routing rules: %s", exc)

    try:
        from ..learning import improve

        context.feedback = improve.read_feedback()
    except Exception as exc:  # noqa: BLE001
        log.debug("Could not read improve.txt: %s", exc)

    try:
        from ..trends import research as trend_research

        cached = trend_research.cached_context()
        if cached.videos:
            context.trends = {
                "videos": [video.to_dict() for video in cached.videos[:10]],
                "themes": cached.themes,
            }
    except Exception as exc:  # noqa: BLE001
        log.debug("Could not read the trend cache: %s", exc)

    if clip_id:
        context.focus = _clip_focus(clip_id)
    elif job_id:
        context.focus = _job_focus(job_id)

    return context


__all__ = ["MAX_FAILURES", "RECENT_CLIPS", "RECENT_JOBS", "ProjectContext", "build_context"]
