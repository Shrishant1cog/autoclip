"""Duplicate-upload detection."""

from __future__ import annotations

from pathlib import Path

import pytest
from autoclip.db import store
from autoclip.db.models import Clip, Export, Job, Source, YouTubeUpload, new_id
from autoclip.youtube import duplicates, uploads


def _source() -> Source:
    return store.create_source(
        Source(id=new_id(), type="upload", path="C:/media/source.mp4", title="Source")
    )


def _clip(source: Source, title: str = "Steak trick") -> Clip:
    job = store.create_job(Job(id=new_id(), source_id=source.id, status="done"))
    return store.replace_clips(
        job.id,
        [Clip(id=new_id(), job_id=job.id, start_s=0.0, end_s=30.0, title=title)],
    )[0]


def _export(clip: Clip, path: Path, content: bytes = b"rendered-clip") -> Export:
    path.write_bytes(content)
    return store.create_export(
        Export(id=new_id(), clip_id=clip.id, path=str(path), size_bytes=path.stat().st_size)
    )


def _upload(
    clip: Clip, export: Export, *, status: str, title: str = "Steak trick", video_id=None
) -> YouTubeUpload:
    return store.create_upload(
        YouTubeUpload(
            id=new_id(),
            export_id=export.id,
            clip_id=clip.id,
            status=status,
            title=title,
            video_id=video_id,
        )
    )


def test_same_clip_with_a_finished_upload_is_flagged(initialised_db: int, tmp_path: Path) -> None:
    source = _source()
    clip = _clip(source)
    done = _upload(clip, _export(clip, tmp_path / "a.mp4"), status="done", video_id="published")
    pending = _upload(clip, _export(clip, tmp_path / "b.mp4"), status="pending")

    groups = duplicates.find_duplicates()

    assert len(groups) == 1
    assert groups[0].reason == "same-clip"
    assert groups[0].keep.id == done.id
    assert [row.id for row in groups[0].duplicates] == [pending.id]


def test_failed_uploads_are_ignored_unless_requested(initialised_db: int, tmp_path: Path) -> None:
    source = _source()
    clip = _clip(source)
    _upload(clip, _export(clip, tmp_path / "a.mp4"), status="done", video_id="published")
    _upload(clip, _export(clip, tmp_path / "b.mp4"), status="failed")

    assert duplicates.find_duplicates() == []

    groups = duplicates.find_duplicates(include_failed=True)

    assert len(groups) == 1
    assert groups[0].duplicates[0].status == "failed"


def test_identical_bytes_across_clips_are_flagged(initialised_db: int, tmp_path: Path) -> None:
    source = _source()
    first = _clip(source, "First moment")
    second = _clip(source, "Second moment")
    # Same bytes, different paths and different clips: re-ingesting the same
    # source should not publish the same render twice.
    _upload(first, _export(first, tmp_path / "one.mp4"), status="done", video_id="v1")
    _upload(second, _export(second, tmp_path / "two.mp4"), status="pending", title="Other")

    groups = duplicates.find_duplicates()

    reasons = {group.reason for group in groups}
    assert "identical-file" in reasons
    identical = next(group for group in groups if group.reason == "identical-file")
    assert identical.keep.status == "done"
    assert identical.duplicates[0].status == "pending"


def test_different_files_and_clips_are_not_duplicates(initialised_db: int, tmp_path: Path) -> None:
    source = _source()
    first = _clip(source, "First")
    second = _clip(source, "Second")
    _upload(first, _export(first, tmp_path / "one.mp4"), status="done", video_id="v1")

    two = tmp_path / "two.mp4"
    two.write_bytes(b"a completely different render")
    export_two = store.create_export(
        Export(id=new_id(), clip_id=second.id, path=str(two), size_bytes=two.stat().st_size)
    )
    _upload(second, export_two, status="pending", title="Different words entirely")

    assert duplicates.find_duplicates() == []


def test_same_title_is_opt_in(initialised_db: int, tmp_path: Path) -> None:
    source = _source()
    first = _clip(source, "First")
    second = _clip(source, "Second")
    _upload(
        first,
        _export(first, tmp_path / "one.mp4"),
        status="done",
        title="Same title",
    )
    _upload(
        second,
        _export(second, tmp_path / "two.mp4", content=b"another render"),
        status="pending",
        title="Same title",
    )

    assert duplicates.find_duplicates() == []

    groups = duplicates.find_duplicates(by_title=True)

    assert any(group.reason == "same-title" for group in groups)


def test_skip_marks_pending_duplicates_only(initialised_db: int, tmp_path: Path) -> None:
    source = _source()
    clip = _clip(source)
    _upload(clip, _export(clip, tmp_path / "a.mp4"), status="done", video_id="published")
    pending = _upload(clip, _export(clip, tmp_path / "b.mp4"), status="pending")
    inflight = _upload(clip, _export(clip, tmp_path / "c.mp4"), status="uploading")

    skipped, in_flight = duplicates.skip_duplicates(duplicates.find_duplicates())

    assert skipped == 1
    assert in_flight == 1
    assert store.get_upload(pending.id).status == "skipped"
    assert "duplicate" in (store.get_upload(pending.id).error or "").lower()
    assert store.get_upload(inflight.id).status == "uploading"


def test_skipped_rows_are_not_reported_again(initialised_db: int, tmp_path: Path) -> None:
    source = _source()
    clip = _clip(source)
    _upload(clip, _export(clip, tmp_path / "a.mp4"), status="done", video_id="published")
    _upload(clip, _export(clip, tmp_path / "b.mp4"), status="skipped")

    assert duplicates.find_duplicates() == []


def test_conflict_for_returns_a_finished_upload(initialised_db: int, tmp_path: Path) -> None:
    source = _source()
    clip = _clip(source)
    done = _upload(clip, _export(clip, tmp_path / "a.mp4"), status="done", video_id="published")
    pending = _upload(clip, _export(clip, tmp_path / "b.mp4"), status="pending")

    conflict = duplicates.conflict_for(pending)

    assert conflict is not None
    assert conflict.id == done.id


def test_conflict_for_returns_an_in_flight_upload(initialised_db: int, tmp_path: Path) -> None:
    source = _source()
    clip = _clip(source)
    pending = _upload(clip, _export(clip, tmp_path / "a.mp4"), status="pending")
    inflight = _upload(clip, _export(clip, tmp_path / "b.mp4"), status="uploading")

    assert duplicates.conflict_for(inflight) is None
    conflict = duplicates.conflict_for(pending)
    assert conflict is not None
    assert conflict.id == inflight.id


def test_conflict_for_ignores_other_clips(initialised_db: int, tmp_path: Path) -> None:
    source = _source()
    clip = _clip(source)
    other = _clip(source, "Other moment")
    _upload(clip, _export(clip, tmp_path / "a.mp4"), status="done", video_id="published")
    upload = _upload(other, _export(other, tmp_path / "b.mp4"), status="pending")

    assert duplicates.conflict_for(upload) is None


async def test_process_upload_refuses_a_duplicate(
    initialised_db: int, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    source = _source()
    clip = _clip(source)
    _upload(clip, _export(clip, tmp_path / "a.mp4"), status="done", video_id="published")
    pending = _upload(clip, _export(clip, tmp_path / "b.mp4"), status="pending")

    # If the guard fails, this records the call instead of reaching the network.
    def fail_upload(*args, **kwargs):
        raise AssertionError("duplicate must not reach uploader.upload_video")

    monkeypatch.setattr(uploads.uploader, "upload_video", fail_upload)

    with pytest.raises(uploads.DuplicateUploadError):
        await uploads.process_upload(pending)


def test_json_report_is_serialisable(initialised_db: int, tmp_path: Path) -> None:
    source = _source()
    clip = _clip(source)
    _upload(clip, _export(clip, tmp_path / "a.mp4"), status="done", video_id="published")
    _upload(clip, _export(clip, tmp_path / "b.mp4"), status="pending")

    payload = duplicates.as_json(duplicates.find_duplicates())

    assert payload[0]["reason"] == "same-clip"
    assert payload[0]["keep"]["watch_url"] == "https://youtu.be/published"
    assert payload[0]["duplicates"][0]["status"] == "pending"
