"""Publish previously clipped videos to YouTube with metadata and thumbnails.

Three phases, deliberately separate:

``--prepare``
    Renders a thumbnail for every exported clip and asks the active model for
    a title, description and tags built from that clip's own subtitles. The
    result is written to ``~/.autoclip/youtube_staging/uploads.json`` so it can
    be reviewed before anything is published. Nothing here touches YouTube, so
    it costs no API quota. The thumbnail is drawn *after* the title is known,
    so the picture and the video title always say the same thing.

``--publish``
    Uploads each staged clip, attaches its thumbnail, and records the result
    in the ``youtube_uploads`` table so the app shows it and the duplicate
    guard can see it. The duplicate guard runs first: a clip that is already
    published is skipped rather than uploaded twice.

``--fix-thumbnails``
    Redraws the thumbnail of an already published video and sets it again.
    YouTube can take a video down after the upload call returned, and a
    thumbnail drawn before the final title was known needs replacing;
    ``thumbnails.set`` costs a few quota units against a full re-upload.

Usage::

    python scripts/upload_previous_clips.py --prepare
    python scripts/upload_previous_clips.py --publish --limit 6
    python scripts/upload_previous_clips.py --fix-thumbnails --force
"""

from __future__ import annotations

import argparse
import asyncio
import copy
import json
import sys
from dataclasses import asdict, dataclass, field
from pathlib import Path

import httpx
from autoclip import config, paths
from autoclip.config import ProviderSettings
from autoclip.db import store
from autoclip.db.models import YouTubeUpload, new_id
from autoclip.pipeline import thumbnails
from autoclip.providers import build_provider
from autoclip.youtube import duplicates, oauth, uploader
from autoclip.youtube import metadata as metadata_module
from autoclip.youtube.uploads import clip_words

STAGING_DIR = paths.exports_dir().parent / "youtube_staging"
STAGING_FILE = STAGING_DIR / "uploads.json"

#: Models tried in turn when Gemini is busy. A busy model errors out rather
#: than answering badly, so the ladder just moves to the next one.
#:
#: The order matters: ``gemini-3.1-flash-lite`` answers in about twenty
#: seconds, while the flash models in front of it can sit in the SDK's retry
#: loop for a minute and a half before giving up on a 503.
_MODEL_LADDER = ("gemini-3.1-flash-lite", "gemini-3.5-flash-lite", "gemini-3.8-flash")

#: Hard ceiling on one model's metadata call. The SDK retries a busy model
#: internally, so without this a single 503 loop can stall the whole run.
_METADATA_TIMEOUT_S = 120.0

#: YouTube's API categories worth distinguishing. 24 is Entertainment, which
#: is the safe default; 20 is Gaming.
CATEGORY_ENTERTAINMENT = "24"
CATEGORY_GAMING = "20"

_GAMING_WORDS = (
    "fortnite",
    "gaming",
    "gameplay",
    "minecraft",
    "cod",
    "pubg",
    "valorant",
    "gta",
    "epic games",
    "twitch",
)


@dataclass
class StagedUpload:
    """One clip prepared for publication."""

    export_id: str
    clip_id: str
    job_id: str
    source_title: str
    source_url: str
    clip_start_s: float
    clip_duration_s: float
    title: str
    description: str
    tags: list[str] = field(default_factory=list)
    thumbnail: str = ""
    privacy: str = "public"
    category_id: str = CATEGORY_ENTERTAINMENT
    path: str = ""
    #: The title the thumbnail was rendered with, so a re-prepare can tell a
    #: stale thumbnail from a current one.
    thumbnail_title: str = ""


def _target_exports(job_filter: set[str]) -> list[tuple]:
    """Every exported clip, published or not.

    Published clips stay in the list: their metadata and thumbnail still need
    to be staged, because a thumbnail drawn before the final title was known
    has to be redrawn and set again. The publish step skips them.
    """
    targets: list[tuple] = []
    for export in store.list_all_exports():
        clip = store.get_clip(export.clip_id)
        if clip is None:
            continue
        if job_filter and clip.job_id not in job_filter:
            continue
        if not Path(export.path).is_file():
            print(f"  skip  {export.path} (file is missing)")
            continue
        targets.append((export, clip))
    return targets


def _category_for(source_title: str, title: str) -> str:
    """Pick the YouTube category from what the clip is about."""
    haystack = f"{source_title} {title}".lower()
    if any(word in haystack for word in _GAMING_WORDS):
        return CATEGORY_GAMING
    return CATEGORY_ENTERTAINMENT


def _timestamp(seconds: float) -> str:
    total = int(seconds)
    return f"{total // 60}:{total % 60:02d}"


def _attribution(source_title: str, source_url: str | None, start_s: float) -> str:
    """Credit the original video, which is what a clip channel should do."""
    lines = [f"Clip from {source_title}" if source_title else "Clip"]
    if source_url:
        lines.append(source_url)
    lines.append(f"Timestamp: {_timestamp(start_s)}")
    return "\n".join(lines)


async def _generate_metadata(
    settings,
    *,
    title: str,
    hook: str,
    reason: str,
    words,
    duration_s: float,
    language: str,
) -> metadata_module.ClipMetadata:
    """Ask the model for metadata, trying each model in turn.

    A model that is busy returns an error rather than a bad answer, and
    :func:`generate_metadata` turns that into the local fallback. The fallback
    is recognisable, so a model that only ever produces it counts as a failure
    and the next model gets a turn.
    """
    fallback = metadata_module.fallback_metadata(
        title=title, hook=hook, reason=reason, words=words, duration_s=duration_s
    )

    models = _MODEL_LADDER if settings.active_provider == "gemini" else [""]
    last: metadata_module.ClipMetadata = fallback
    for model in models:
        attempt = copy.deepcopy(settings)
        if model:
            attempt.providers.setdefault("gemini", ProviderSettings()).model = model
        try:
            provider = build_provider(attempt.active_provider, attempt)
            generated = await asyncio.wait_for(
                metadata_module.generate_metadata(
                    provider,
                    title=title,
                    hook=hook,
                    reason=reason,
                    words=words,
                    duration_s=duration_s,
                    language=language,
                ),
                timeout=_METADATA_TIMEOUT_S,
            )
        except Exception as exc:
            print(f"      {model or attempt.active_provider} failed: {str(exc)[:90]}", flush=True)
            continue

        if generated != fallback:
            print(f"      metadata by {model or attempt.active_provider}")
            return generated
        last = generated
        print(f"      {model or attempt.active_provider} was unavailable — trying the next")

    print("      using the local fallback metadata")
    return last


async def prepare(args: argparse.Namespace) -> int:
    """Render thumbnails and generate metadata for every target clip."""
    settings = config.load()

    job_filter = {j.strip() for j in args.jobs.split(",") if j.strip()}
    targets = _target_exports(job_filter)
    if not targets:
        print("Nothing to prepare — there are no exports to stage.")
        return 0

    staged: list[StagedUpload] = []
    # Metadata already generated in an earlier run is reused, so a rerun only
    # pays for the clips that are still missing it.
    done: dict[str, StagedUpload] = {}
    if STAGING_FILE.is_file():
        try:
            for item in _load_staged():
                done[item.export_id] = item
        except Exception:
            done = {}

    for index, (export, clip) in enumerate(targets, start=1):
        export_path = Path(export.path)
        job = store.get_job(clip.job_id)
        source = store.get_source(job.source_id) if job else None
        source_title = source.title if source else ""
        source_url = source.url if source else None

        thumbnail_path = thumbnails.thumbnail_path_for(export_path)

        cached = done.get(export.id)
        if cached is not None and not args.refresh:
            # The thumbnail carries the published title, so a staged entry whose
            # thumbnail was drawn for a different title needs a new one.
            stale = cached.thumbnail_title != cached.title
            if stale or not thumbnail_path.is_file():
                thumbnails.render_thumbnail(
                    export_path,
                    title=cached.title,
                    eyebrow=source_title,
                    output=thumbnail_path,
                )
                cached.thumbnail_title = cached.title
                print(f"  [{index}/{len(targets)}] thumbnail  {thumbnail_path.name} (redrawn)")
            else:
                print(
                    f"  [{index}/{len(targets)}] thumbnail  {thumbnail_path.name} (cached)",
                    flush=True,
                )
            staged.append(cached)
            print(f"  [{index}/{len(targets)}] metadata  (cached)", flush=True)
            continue

        words, language = clip_words(clip)
        generated = await _generate_metadata(
            settings,
            title=clip.title,
            hook=clip.hook,
            reason=clip.reason,
            words=words,
            duration_s=clip.duration_s,
            language=language,
        )

        # The thumbnail carries the published title, so it is drawn after the
        # metadata is known. A thumbnail left over from an earlier title is
        # re-rendered rather than reused.
        if (
            not thumbnail_path.is_file()
            or cached is None
            or cached.thumbnail_title != generated.title
            or cached.title != generated.title
        ):
            thumbnails.render_thumbnail(
                export_path,
                title=generated.title,
                eyebrow=source_title,
                output=thumbnail_path,
            )
            print(f"  [{index}/{len(targets)}] thumbnail  {thumbnail_path.name}", flush=True)
        else:
            print(
                f"  [{index}/{len(targets)}] thumbnail  {thumbnail_path.name} (cached)", flush=True
            )

        description = generated.description
        attribution = _attribution(source_title, source_url, clip.start_s)
        if attribution:
            description = f"{description}\n\n{attribution}"

        staged.append(
            StagedUpload(
                export_id=export.id,
                clip_id=clip.id,
                job_id=clip.job_id,
                source_title=source_title,
                source_url=source_url or "",
                clip_start_s=clip.start_s,
                clip_duration_s=clip.duration_s,
                title=generated.title,
                description=description,
                tags=generated.tags,
                thumbnail=str(thumbnail_path),
                thumbnail_title=generated.title,
                privacy=args.privacy,
                category_id=_category_for(source_title, generated.title),
                path=str(export_path),
            )
        )

        # Checkpoint after every clip: a run that dies half way still leaves a
        # staging file that the next run can pick up.
        _write_staged(staged)

    _write_staged(staged)

    print(f"\nPrepared {len(staged)} clip(s). Staging file: {STAGING_FILE}", flush=True)
    for item in staged:
        print(f"  - {item.title}  [{item.category_id}]  thumb={Path(item.thumbnail).name}")
    return 0


def _write_staged(staged: list[StagedUpload]) -> None:
    """Write the staging file atomically."""
    STAGING_DIR.mkdir(parents=True, exist_ok=True)
    payload = json.dumps([asdict(item) for item in staged], indent=2, ensure_ascii=False)
    tmp = STAGING_FILE.with_suffix(".json.tmp")
    tmp.write_text(payload, encoding="utf-8")
    tmp.replace(STAGING_FILE)


def _load_staged() -> list[StagedUpload]:
    if not STAGING_FILE.is_file():
        print(f"No staging file at {STAGING_FILE}. Run --prepare first.")
        return []
    raw = json.loads(STAGING_FILE.read_text(encoding="utf-8"))
    return [StagedUpload(**item) for item in raw]


def _is_removed(settings, upload) -> bool:
    """True when YouTube no longer knows about this video.

    A video can be taken down after the upload call succeeded, so the local
    row says "done" while the video is gone. Asking the API costs one unit
    and is the only way to tell.
    """
    if not upload.video_id:
        return False
    try:
        response = httpx.get(
            "https://www.googleapis.com/youtube/v3/videos",
            params={"part": "id", "id": upload.video_id},
            headers={"Authorization": f"Bearer {oauth.access_token(settings)}"},
            timeout=30.0,
        )
    except httpx.HTTPError:
        return False
    if response.status_code >= 400:
        return False
    return not response.json().get("items")


def publish(args: argparse.Namespace) -> int:
    """Upload each staged clip, attach its thumbnail, and record the result."""
    settings = config.load()
    if not oauth.is_connected(settings):
        print("No channel is connected. Connect YouTube in Settings first.")
        return 1

    staged = _load_staged()
    if not staged:
        return 1
    if args.limit:
        staged = staged[: args.limit]

    published = 0
    skipped = 0
    failed = 0

    for item in staged:
        export_path = Path(item.path)

        # A finished upload for this export means the clip is already live.
        # ``create_upload`` returns the existing row rather than inserting a
        # second one, so without this check a re-run would publish it twice.
        existing = store.get_upload_for_export(item.export_id)
        if existing is not None and existing.status == "done":
            if args.retry_removed and _is_removed(settings, existing):
                # YouTube can take a video down after the upload call returns
                # (a spam filter, a copyright claim). The row still says done,
                # but the video is gone, so it is worth sending again.
                store.update_upload(
                    existing.id,
                    status="failed",
                    error="YouTube removed this video after it was uploaded.",
                    clear_error=True,
                )
                print(f"  retry  {item.title} (the previous upload was removed)")
            else:
                skipped += 1
                print(f"  skip  {item.title} (already published as {existing.video_id})")
                continue
        if existing is not None and existing.status == "skipped":
            skipped += 1
            print(f"  skip  {item.title} (marked as a duplicate)")
            continue

        upload = store.create_upload(
            YouTubeUpload(
                id=new_id(),
                export_id=item.export_id,
                clip_id=item.clip_id,
                status="uploading",
                title=item.title,
                description=item.description,
                tags=list(item.tags),
                privacy=item.privacy,
            )
        )

        conflict = duplicates.conflict_for(upload)
        if conflict is not None:
            store.update_upload(
                upload.id, status="skipped", error=f"Duplicate of upload {conflict.id}."
            )
            skipped += 1
            print(f"  skip  {item.title} (duplicate of {conflict.id})")
            continue

        store.update_upload(
            upload.id,
            status="uploading",
            title=item.title,
            description=item.description,
            tags=list(item.tags),
            clear_error=True,
        )

        print(f"  upload  {item.title}  ({export_path.stat().st_size / 1e6:.1f} MB)")
        try:
            video_id = uploader.upload_video(
                settings,
                path=export_path,
                metadata=metadata_module.ClipMetadata(
                    title=item.title,
                    description=item.description,
                    tags=list(item.tags),
                ),
                privacy=item.privacy,
                category_id=item.category_id,
            )
        except uploader.YouTubeError as exc:
            message = str(exc)
            store.update_upload(upload.id, status="failed", error=message)
            failed += 1
            print(f"    failed: {message.splitlines()[0]}")
            if "quota" in message.lower():
                print(
                    "\nDaily API quota reached. The remaining clips stay staged; "
                    "run --publish again tomorrow."
                )
                break
            continue

        thumbnail = Path(item.thumbnail)
        if thumbnail.is_file():
            try:
                uploader.set_thumbnail(settings, video_id=video_id, path=thumbnail)
            except Exception as exc:
                print(f"    thumbnail failed: {exc}")

        store.update_upload(upload.id, status="done", video_id=video_id, clear_error=True)
        published += 1
        print(f"    live  https://youtu.be/{video_id}")

    print(f"\nPublished {published}, skipped {skipped}, failed {failed}.")
    return 0


def fix_thumbnails(args: argparse.Namespace) -> int:
    """Re-render thumbnails for published videos and push them to YouTube.

    A thumbnail that was drawn before the final title was known carries the
    old wording. This redraws it from the staged title and sets it again on
    the live video. ``thumbnails.set`` costs a handful of quota units, so it
    is far cheaper than a second upload.
    """
    settings = config.load()
    if not oauth.is_connected(settings):
        print("No channel is connected.")
        return 1

    staged = {item.export_id: item for item in _load_staged()}
    fixed = 0
    for upload in store.list_all_uploads():
        if upload.status != "done" or not upload.video_id:
            continue
        item = staged.get(upload.export_id)
        if item is None:
            print(f"  skip  {upload.video_id} (not in the staging file)")
            continue

        export = store.get_export(upload.export_id)
        if export is None:
            continue
        export_path = Path(export.path)
        if not export_path.is_file():
            print(f"  skip  {upload.video_id} (the exported file is missing)")
            continue

        thumbnail_path = thumbnails.thumbnail_path_for(export_path)
        job = (
            store.get_job(store.get_clip(item.clip_id).job_id)
            if store.get_clip(item.clip_id)
            else None
        )
        source_title = ""
        if job is not None:
            source = store.get_source(job.source_id)
            source_title = source.title if source else ""

        title = item.title or upload.title
        if not thumbnail_path.is_file() or args.force:
            thumbnails.render_thumbnail(
                export_path,
                title=title,
                eyebrow=source_title,
                output=thumbnail_path,
            )
        try:
            uploader.set_thumbnail(settings, video_id=upload.video_id, path=thumbnail_path)
            fixed += 1
            print(f"  fixed  {upload.video_id}  {title}")
        except Exception as exc:
            print(f"  failed {upload.video_id}: {exc}")

    print(f"\nUpdated {fixed} thumbnail(s).")
    return 0


def status() -> int:
    """Show what is already published and what is still waiting."""
    for upload in store.list_all_uploads():
        print(f"  {upload.status:9} {upload.video_id or '-':14} {upload.title or '(no title yet)'}")
    print("\nStaged:")
    for item in _load_staged():
        print(f"  {item.privacy:8} [{item.category_id}] {item.title}")
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--prepare",
        action="store_true",
        help="Render thumbnails and generate metadata (no YouTube calls).",
    )
    parser.add_argument(
        "--publish",
        action="store_true",
        help="Upload the staged clips with their thumbnails.",
    )
    parser.add_argument(
        "--fix-thumbnails",
        action="store_true",
        help="Re-render thumbnails for published videos and set them again.",
    )
    parser.add_argument("--status", action="store_true", help="Show published and staged work.")
    parser.add_argument("--limit", type=int, default=0, help="Publish at most N clips.")
    parser.add_argument("--jobs", default="", help="Comma-separated job ids to include.")
    parser.add_argument(
        "--refresh",
        action="store_true",
        help="Regenerate metadata even for clips that already have some staged.",
    )
    parser.add_argument(
        "--force",
        action="store_true",
        help="Re-render thumbnails even when the file already exists.",
    )
    parser.add_argument(
        "--retry-removed",
        action="store_true",
        help="Upload again any clip YouTube took down after the first upload.",
    )
    parser.add_argument(
        "--privacy",
        default="public",
        choices=("public", "unlisted", "private"),
        help="Privacy status for the staged uploads.",
    )
    args = parser.parse_args(argv)

    if not (args.prepare or args.publish or args.status or args.fix_thumbnails):
        parser.print_help()
        return 1

    if args.status:
        return status()
    if args.fix_thumbnails:
        return fix_thumbnails(args)
    if args.prepare:
        return asyncio.run(prepare(args))
    return publish(args)


if __name__ == "__main__":
    sys.exit(main())
