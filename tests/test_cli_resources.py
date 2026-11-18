"""Phase 16 — the ``autoclip resources`` and ``autoclip cleanup`` commands.

The CLI is how the app is operated without the browser, so the two commands
that report and reclaim disk have to work there too. These tests drive the
real Typer app against a throwaway home directory.
"""

from __future__ import annotations

from pathlib import Path

import pytest
from autoclip import config
from autoclip.cli import app
from autoclip.db import store
from autoclip.db.models import Clip, Export, Job, Source, YouTubeUpload, new_id
from typer.testing import CliRunner

runner = CliRunner()


@pytest.fixture
def cli_home(autoclip_home: Path, initialised_db: int) -> Path:
    """The throwaway home the CLI commands will operate on."""
    return autoclip_home


def test_resources_reports_disk_usage(cli_home: Path) -> None:
    work = cli_home / "work" / "job" / "audio.wav"
    work.parent.mkdir(parents=True, exist_ok=True)
    work.write_bytes(b"x" * 2048)

    result = runner.invoke(app, ["resources"])

    assert result.exit_code == 0, result.output
    assert "Disk usage" in result.output
    assert "work" in result.output
    assert "Model and render usage" in result.output


def test_resources_reports_the_configured_limits(cli_home: Path) -> None:
    result = runner.invoke(app, ["resources"])

    assert result.exit_code == 0, result.output
    assert "parallel ffmpeg" in result.output
    assert "Retention:" in result.output


def test_cleanup_dry_run_deletes_nothing(cli_home: Path) -> None:
    orphan = cli_home / "exports" / "gone" / "leftover.mp4"
    orphan.parent.mkdir(parents=True, exist_ok=True)
    orphan.write_bytes(b"x" * 1024)

    result = runner.invoke(app, ["cleanup", "--dry-run"])

    assert result.exit_code == 0, result.output
    assert "on disk now" in result.output
    assert orphan.exists()


def test_cleanup_removes_orphans_and_reports_it(cli_home: Path) -> None:
    orphan = cli_home / "exports" / "gone" / "leftover.mp4"
    orphan.parent.mkdir(parents=True, exist_ok=True)
    orphan.write_bytes(b"x" * 1024)

    result = runner.invoke(app, ["cleanup"])

    assert result.exit_code == 0, result.output
    assert "Removed" in result.output
    assert not orphan.exists()


def test_cleanup_says_so_when_there_is_nothing_to_reclaim(cli_home: Path) -> None:
    result = runner.invoke(app, ["cleanup"])

    assert result.exit_code == 0, result.output
    assert "Nothing to reclaim" in result.output


def test_cleanup_keeps_an_unpublished_clip(cli_home: Path) -> None:
    """The command must not delete work the user can still want."""
    source = Source(id=new_id(), type="upload", path="C:/videos/source.mp4", title="A Video")
    store.create_source(source)
    job = Job(id=new_id(), source_id=source.id, status="done")
    store.create_job(job)
    clip = Clip(id=new_id(), job_id=job.id, start_s=0, end_s=20, title="Not published")
    store.replace_clips(job.id, [clip])
    file = cli_home / "exports" / job.id / "clip.mp4"
    file.parent.mkdir(parents=True, exist_ok=True)
    file.write_bytes(b"x" * 1024)
    store.create_export(Export(id=new_id(), clip_id=clip.id, path=str(file)))

    settings = config.load()
    settings.resources.export_retention_days = 7
    config.save(settings)

    result = runner.invoke(app, ["cleanup"])

    assert result.exit_code == 0, result.output
    assert file.exists()


def test_cleanup_removes_a_published_clip_past_its_retention(cli_home: Path) -> None:
    source = Source(id=new_id(), type="upload", path="C:/videos/source.mp4", title="A Video")
    store.create_source(source)
    job = Job(id=new_id(), source_id=source.id, status="done")
    store.create_job(job)
    clip = Clip(id=new_id(), job_id=job.id, start_s=0, end_s=20, title="Published")
    store.replace_clips(job.id, [clip])
    file = cli_home / "exports" / job.id / "clip.mp4"
    file.parent.mkdir(parents=True, exist_ok=True)
    file.write_bytes(b"x" * 1024)
    export = Export(id=new_id(), clip_id=clip.id, path=str(file), created_at="2020-01-01T00:00:00")
    store.create_export(export)
    store.create_upload(
        YouTubeUpload(id=new_id(), export_id=export.id, clip_id=clip.id, status="done")
    )

    settings = config.load()
    settings.resources.export_retention_days = 7
    config.save(settings)

    result = runner.invoke(app, ["cleanup"])

    assert result.exit_code == 0, result.output
    assert not file.exists()
    # The row survives: it is the record that the clip was published.
    assert store.get_export(export.id) is not None
