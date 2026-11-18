"""Phase 16 — resource optimisation: measurement, bounds, and reclamation.

The tests here exist because resource management fails quietly. A cleanup
routine that deletes the wrong file, a concurrency gate that never limits
anything, and a token counter that reports zero are all invisible until the
disk is full or the bill arrives — so each one is checked directly.
"""

from __future__ import annotations

import time
from pathlib import Path

import pytest
from autoclip import config, resources
from autoclip.db import store
from autoclip.db.models import Clip, Export, Job, JobResources, Source, YouTubeUpload, new_id
from fastapi.testclient import TestClient

# --------------------------------------------------------------------------
# Helpers
# --------------------------------------------------------------------------


def _seed_source(*, kind: str = "upload", path: str = "C:/videos/source.mp4") -> Source:
    source = Source(id=new_id(), type=kind, path=path, title="A Video")
    store.create_source(source)
    return source


def _seed_job(source: Source, *, status: str = "done", finished_at: str | None = None) -> Job:
    job = Job(
        id=new_id(),
        source_id=source.id,
        status=status,
        finished_at=finished_at or "2020-01-01T00:00:00+00:00",
        updated_at=finished_at or "2020-01-01T00:00:00+00:00",
    )
    store.create_job(job)
    return job


def _write(path: Path, size: int = 1024) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(b"x" * size)
    return path


def _settings(**overrides) -> config.Settings:
    settings = config.Settings()
    for name, value in overrides.items():
        setattr(settings.resources, name, value)
    return settings


# --------------------------------------------------------------------------
# Disk usage
# --------------------------------------------------------------------------


def test_disk_usage_counts_real_files(autoclip_home: Path, initialised_db: int) -> None:
    _write(autoclip_home / "raw" / "abc" / "video.mp4", 2048)
    _write(autoclip_home / "work" / "job" / "audio.wav", 4096)
    _write(autoclip_home / "exports" / "job" / "clip.mp4", 1024)

    usage = resources.disk_usage()
    by_name = {d.name: d for d in usage.directories}

    assert by_name["raw"].size_bytes == 2048
    assert by_name["raw"].file_count == 1
    assert by_name["work"].size_bytes == 4096
    assert by_name["exports"].size_bytes == 1024
    assert usage.database_bytes > 0
    assert usage.total_bytes == 2048 + 4096 + 1024 + usage.database_bytes


def test_format_bytes_is_honest() -> None:
    assert resources.format_bytes(0) == "0 B"
    assert resources.format_bytes(512) == "512 B"
    assert resources.format_bytes(1024) == "1.0 KB"
    assert resources.format_bytes(1024 * 1024) == "1.0 MB"
    assert resources.format_bytes(3 * 1024**3) == "3.0 GB"


# --------------------------------------------------------------------------
# Cleanup — scratch directories
# --------------------------------------------------------------------------


def test_cleanup_removes_old_scratch_of_a_finished_job(
    autoclip_home: Path, initialised_db: int
) -> None:
    source = _seed_source()
    job = _seed_job(source, status="done", finished_at="2020-01-01T00:00:00+00:00")
    _write(autoclip_home / "work" / job.id / "audio.wav", 4096)

    report = resources.cleanup(_settings(work_retention_days=7))

    assert report.removed_directories == 1
    assert report.freed_bytes == 4096
    assert not (autoclip_home / "work" / job.id).exists()


def test_cleanup_keeps_the_scratch_of_a_failed_job(
    autoclip_home: Path, initialised_db: int
) -> None:
    """A failed job's scratch is what makes "run it again" resume."""
    source = _seed_source()
    job = _seed_job(source, status="failed", finished_at="2020-01-01T00:00:00+00:00")
    _write(autoclip_home / "work" / job.id / "audio.wav", 4096)

    report = resources.cleanup(_settings(work_retention_days=7))

    assert report.removed_directories == 0
    assert (autoclip_home / "work" / job.id / "audio.wav").exists()


def test_cleanup_keeps_the_scratch_of_a_running_job(
    autoclip_home: Path, initialised_db: int
) -> None:
    source = _seed_source()
    job = _seed_job(source, status="running", finished_at=None)
    _write(autoclip_home / "work" / job.id / "audio.wav", 4096)

    resources.cleanup(_settings(work_retention_days=1))

    assert (autoclip_home / "work" / job.id / "audio.wav").exists()


def test_cleanup_keeps_recent_scratch(autoclip_home: Path, initialised_db: int) -> None:
    source = _seed_source()
    job = _seed_job(source, status="done", finished_at="2026-01-01T00:00:00+00:00")
    _write(autoclip_home / "work" / job.id / "audio.wav", 4096)

    report = resources.cleanup(_settings(work_retention_days=3650))

    assert report.removed_directories == 0
    assert (autoclip_home / "work" / job.id / "audio.wav").exists()


def test_retention_of_zero_keeps_everything(autoclip_home: Path, initialised_db: int) -> None:
    source = _seed_source()
    job = _seed_job(source, status="done", finished_at="2020-01-01T00:00:00+00:00")
    _write(autoclip_home / "work" / job.id / "audio.wav", 4096)

    report = resources.cleanup(_settings(work_retention_days=0))

    assert report.removed_directories == 0
    assert (autoclip_home / "work" / job.id / "audio.wav").exists()


# --------------------------------------------------------------------------
# Cleanup — published clips and downloaded videos
# --------------------------------------------------------------------------


def test_cleanup_removes_a_published_clip_past_its_retention(
    autoclip_home: Path, initialised_db: int
) -> None:
    source = _seed_source()
    job = _seed_job(source)
    clip = Clip(id=new_id(), job_id=job.id, start_s=0, end_s=20, title="Published")
    store.replace_clips(job.id, [clip])
    file = _write(autoclip_home / "exports" / job.id / "clip.mp4", 2048)
    export = Export(id=new_id(), clip_id=clip.id, path=str(file), created_at="2020-01-01T00:00:00")
    store.create_export(export)
    store.create_upload(
        YouTubeUpload(
            id=new_id(),
            export_id=export.id,
            clip_id=clip.id,
            status="done",
            video_id="abc123",
        )
    )

    report = resources.cleanup(_settings(export_retention_days=7))

    assert report.removed_files == 1
    assert not file.exists()
    # The row survives: it is the record that the clip was published, and the
    # duplicate check reads it.
    assert store.get_export(export.id) is not None


def test_cleanup_keeps_an_unpublished_clip(autoclip_home: Path, initialised_db: int) -> None:
    """An unpublished clip is the user's own work — never deleted automatically."""
    source = _seed_source()
    job = _seed_job(source)
    clip = Clip(id=new_id(), job_id=job.id, start_s=0, end_s=20, title="Not published")
    store.replace_clips(job.id, [clip])
    file = _write(autoclip_home / "exports" / job.id / "clip.mp4", 2048)
    export = Export(id=new_id(), clip_id=clip.id, path=str(file), created_at="2020-01-01T00:00:00")
    store.create_export(export)

    report = resources.cleanup(_settings(export_retention_days=7))

    assert report.removed_files == 0
    assert file.exists()


def test_cleanup_keeps_a_clip_whose_upload_is_still_pending(
    autoclip_home: Path, initialised_db: int
) -> None:
    source = _seed_source()
    job = _seed_job(source)
    clip = Clip(id=new_id(), job_id=job.id, start_s=0, end_s=20, title="Pending")
    store.replace_clips(job.id, [clip])
    file = _write(autoclip_home / "exports" / job.id / "clip.mp4", 2048)
    export = Export(id=new_id(), clip_id=clip.id, path=str(file), created_at="2020-01-01T00:00:00")
    store.create_export(export)
    store.create_upload(
        YouTubeUpload(
            id=new_id(), export_id=export.id, clip_id=clip.id, status="pending"
        )
    )

    resources.cleanup(_settings(export_retention_days=7))

    assert file.exists()


def test_cleanup_removes_an_old_youtube_download(autoclip_home: Path, initialised_db: int) -> None:
    raw = _write(autoclip_home / "raw" / "src" / "video.mp4", 4096)
    source = _seed_source(kind="youtube", path=str(raw))
    _seed_job(source)

    import os

    old = time.time() - 60 * 60 * 24 * 30
    os.utime(raw, (old, old))

    report = resources.cleanup(_settings(raw_retention_days=7))

    assert report.removed_files == 1
    assert not raw.exists()


def test_cleanup_never_removes_an_uploaded_source(
    autoclip_home: Path, initialised_db: int
) -> None:
    """An uploaded file cannot be downloaded again, so it is never deleted."""
    media = _write(autoclip_home / "media" / "src" / "mine.mp4", 4096)
    source = _seed_source(kind="upload", path=str(media))
    _seed_job(source)

    import os

    old = time.time() - 60 * 60 * 24 * 30
    os.utime(media, (old, old))

    report = resources.cleanup(_settings(raw_retention_days=1))

    assert report.removed_files == 0
    assert media.exists()


# --------------------------------------------------------------------------
# Cleanup — orphans
# --------------------------------------------------------------------------


def test_cleanup_removes_files_no_row_points_at(autoclip_home: Path, initialised_db: int) -> None:
    orphan = _write(autoclip_home / "exports" / "gone" / "leftover.mp4", 1024)
    orphan_work = _write(autoclip_home / "work" / "ghost" / "audio.wav", 1024)

    report = resources.cleanup(_settings())

    assert report.removed_files >= 1
    assert not orphan.exists()
    assert not orphan_work.exists()


def test_cleanup_keeps_files_a_row_points_at(autoclip_home: Path, initialised_db: int) -> None:
    source = _seed_source()
    job = _seed_job(source)
    clip = Clip(id=new_id(), job_id=job.id, start_s=0, end_s=20)
    store.replace_clips(job.id, [clip])
    file = _write(autoclip_home / "exports" / job.id / "clip.mp4", 1024)
    store.create_export(Export(id=new_id(), clip_id=clip.id, path=str(file)))

    resources.cleanup(_settings())

    assert file.exists()


def test_cleanup_keeps_the_thumbnail_of_a_kept_export(
    autoclip_home: Path, initialised_db: int
) -> None:
    """A thumbnail is an artifact of the export, not an orphan file."""
    source = _seed_source()
    job = _seed_job(source)
    clip = Clip(id=new_id(), job_id=job.id, start_s=0, end_s=20)
    store.replace_clips(job.id, [clip])
    video = _write(autoclip_home / "exports" / job.id / "clip_9x16.mp4", 1024)
    thumbnail = _write(autoclip_home / "exports" / job.id / "clip_9x16.jpg", 512)
    store.create_export(Export(id=new_id(), clip_id=clip.id, path=str(video)))

    resources.cleanup(_settings())

    assert video.exists()
    assert thumbnail.exists()


def test_cleanup_keeps_a_source_sidecar(autoclip_home: Path, initialised_db: int) -> None:
    """A source owns its whole directory, including yt-dlp's sidecars."""
    media = _write(autoclip_home / "media" / "src" / "source.mp4", 1024)
    sidecar = _write(autoclip_home / "media" / "src" / "source.info.json", 128)
    source = _seed_source(kind="youtube", path=str(media))

    resources.cleanup(_settings())

    assert media.exists()
    assert sidecar.exists()
    assert store.get_source(source.id) is not None


def test_cleanup_removes_a_published_clip_thumbnail_too(
    autoclip_home: Path, initialised_db: int
) -> None:
    source = _seed_source()
    job = _seed_job(source)
    clip = Clip(id=new_id(), job_id=job.id, start_s=0, end_s=20)
    store.replace_clips(job.id, [clip])
    video = _write(autoclip_home / "exports" / job.id / "clip_9x16.mp4", 1024)
    thumbnail = _write(autoclip_home / "exports" / job.id / "clip_9x16.jpg", 512)
    export = Export(id=new_id(), clip_id=clip.id, path=str(video), created_at="2020-01-01T00:00:00")
    store.create_export(export)
    store.create_upload(
        YouTubeUpload(id=new_id(), export_id=export.id, clip_id=clip.id, status="done")
    )

    resources.cleanup(_settings(export_retention_days=7))

    assert not video.exists()
    assert not thumbnail.exists()


def test_cleanup_keeps_a_file_a_running_job_has_not_recorded_yet(
    autoclip_home: Path, initialised_db: int
) -> None:
    """A render writes the file before the row; cleanup must not race it."""
    source = _seed_source()
    job = _seed_job(source, status="running", finished_at=None)
    rendered = _write(autoclip_home / "exports" / job.id / "clip_9x16.mp4", 1024)

    resources.cleanup(_settings())

    assert rendered.exists()


def test_cleanup_keeps_a_published_clip_of_a_running_job(
    autoclip_home: Path, initialised_db: int
) -> None:
    source = _seed_source()
    job = _seed_job(source, status="running", finished_at=None)
    clip = Clip(id=new_id(), job_id=job.id, start_s=0, end_s=20)
    store.replace_clips(job.id, [clip])
    video = _write(autoclip_home / "exports" / job.id / "clip.mp4", 1024)
    export = Export(id=new_id(), clip_id=clip.id, path=str(video), created_at="2020-01-01T00:00:00")
    store.create_export(export)
    store.create_upload(
        YouTubeUpload(id=new_id(), export_id=export.id, clip_id=clip.id, status="done")
    )

    resources.cleanup(_settings(export_retention_days=7))

    assert video.exists()


# --------------------------------------------------------------------------
# The concurrency gate
# --------------------------------------------------------------------------


def test_the_gate_limits_concurrency() -> None:
    gate = resources.ConcurrencyGate(2)
    peak = 0
    current = 0

    def worker() -> None:
        nonlocal peak, current
        with gate.slot():
            current += 1
            peak = max(peak, current)
            time.sleep(0.05)
            current -= 1

    import threading

    threads = [threading.Thread(target=worker) for _ in range(6)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()

    assert peak <= 2
    assert peak >= 2


def test_the_gate_limit_can_change() -> None:
    gate = resources.ConcurrencyGate(1)
    assert gate.limit == 1
    gate.set_limit(4)
    assert gate.limit == 4
    # A limit below one would deadlock everything, so it is clamped.
    gate.set_limit(0)
    assert gate.limit == 1


def test_the_gate_releases_its_slot_after_an_error() -> None:
    gate = resources.ConcurrencyGate(1)
    with pytest.raises(RuntimeError), gate.slot():
        raise RuntimeError("boom")
    assert gate.active == 0


# --------------------------------------------------------------------------
# Measured usage
# --------------------------------------------------------------------------


def test_job_usage_round_trips(autoclip_home: Path, initialised_db: int) -> None:
    source = _seed_source()
    job = _seed_job(source)

    store.upsert_job_resources(
        JobResources(
            job_id=job.id,
            llm_calls=3,
            llm_input_tokens=1000,
            llm_output_tokens=250,
            ffmpeg_runs=4,
            ffmpeg_seconds=12.5,
            export_bytes=2048,
            windows_skipped=1,
        )
    )

    row = store.get_job_resources(job.id)
    assert row is not None
    assert row.llm_calls == 3
    assert row.llm_total_tokens == 1250
    assert row.windows_skipped == 1

    totals = store.total_job_resources()
    assert totals.llm_calls == 3
    assert totals.export_bytes == 2048


def test_job_usage_is_replaced_not_added(autoclip_home: Path, initialised_db: int) -> None:
    source = _seed_source()
    job = _seed_job(source)
    store.upsert_job_resources(JobResources(job_id=job.id, llm_calls=1))
    store.upsert_job_resources(JobResources(job_id=job.id, llm_calls=7))

    assert store.get_job_resources(job.id).llm_calls == 7


def test_token_usage_adds_up() -> None:
    usage = resources.TokenUsage(calls=1, input_tokens=100, output_tokens=20)
    usage.add(resources.TokenUsage(calls=2, input_tokens=50, output_tokens=5))

    assert usage.calls == 3
    assert usage.input_tokens == 150
    assert usage.output_tokens == 25
    assert usage.total_tokens == 175


def test_a_provider_records_the_usage_it_reports(autoclip_home: Path) -> None:
    """Usage comes from the provider's own numbers, never an estimate."""
    from autoclip.providers.base import LLMProvider, ProviderStatus

    class Fake(LLMProvider):
        name = "fake"

        async def _complete(self, system, user, config):  # pragma: no cover
            return "{}"

        async def health_check(self) -> ProviderStatus:  # pragma: no cover
            return ProviderStatus(name=self.name, available=True)

    provider = Fake("model")
    assert provider.last_usage.calls == 0
    assert provider.total_usage.calls == 0

    provider._record_usage(input_tokens=120, output_tokens=45)
    assert provider.last_usage.calls == 1
    assert provider.last_usage.input_tokens == 120
    assert provider.last_usage.output_tokens == 45

    provider._record_usage(input_tokens=30, output_tokens=10)
    assert provider.last_usage.calls == 1
    assert provider.total_usage.calls == 2
    assert provider.total_usage.input_tokens == 150
    assert provider.total_usage.output_tokens == 55


def test_a_usage_delta_is_the_difference_between_two_snapshots() -> None:
    before = resources.TokenUsage(calls=1, input_tokens=100, output_tokens=20)
    snapshot = before.snapshot()
    before.add(resources.TokenUsage(calls=2, input_tokens=50, output_tokens=5))

    delta = snapshot.delta(before)

    assert delta.calls == 2
    assert delta.input_tokens == 50
    assert delta.output_tokens == 5
    assert delta.total_tokens == 55


def test_a_usage_delta_never_goes_negative() -> None:
    snapshot = resources.TokenUsage(calls=5, input_tokens=100)
    delta = snapshot.delta(resources.TokenUsage(calls=1, input_tokens=10))

    assert delta.calls == 0
    assert delta.input_tokens == 0


# --------------------------------------------------------------------------
# The API
# --------------------------------------------------------------------------


@pytest.fixture
def client(autoclip_home: Path) -> TestClient:
    from autoclip.app import create_app

    with TestClient(create_app()) as test_client:
        yield test_client


def test_the_resource_overview_reports_real_numbers(client: TestClient) -> None:
    response = client.get("/api/resources")

    assert response.status_code == 200
    body = response.json()
    assert "directories" in body["disk"]
    assert body["disk"]["total_bytes"] > 0
    assert body["limits"]["max_parallel_ffmpeg"] >= 1
    assert body["usage"]["totals"]["llm_calls"] == 0
    assert body["usage"]["jobs"] == []


def test_cleanup_runs_from_the_api(client: TestClient) -> None:
    response = client.post("/api/resources/cleanup")

    assert response.status_code == 200
    body = response.json()
    assert "freed_bytes" in body
    assert isinstance(body["details"], list)


def test_the_resource_settings_are_settable(client: TestClient) -> None:
    response = client.put(
        "/api/settings",
        json={
            "resources": {
                "ffmpeg_threads": 2,
                "max_parallel_ffmpeg": 1,
                "work_retention_days": 30,
                "export_retention_days": 0,
                "raw_retention_days": 0,
                "cleanup_on_start": False,
                "max_output_tokens": 2048,
                "max_llm_calls_per_job": 5,
            }
        },
    )

    assert response.status_code == 200
    body = response.json()
    assert body["resources"]["ffmpeg_threads"] == 2
    assert body["resources"]["max_llm_calls_per_job"] == 5

    stored = config.load()
    assert stored.resources.max_parallel_ffmpeg == 1
    assert stored.resources.max_output_tokens == 2048


def test_saving_resource_settings_reaches_the_running_gate(client: TestClient) -> None:
    client.put("/api/settings", json={"resources": {"max_parallel_ffmpeg": 3}})

    assert resources.ffmpeg_gate.limit == 3

    # Put it back so the rest of the suite is unaffected.
    resources.ffmpeg_gate.set_limit(2)


def test_a_nonsensical_resource_limit_is_refused(client: TestClient) -> None:
    """Zero parallel ffmpeg processes would mean nothing ever renders."""
    response = client.put("/api/settings", json={"resources": {"max_parallel_ffmpeg": 0}})

    assert response.status_code == 400
    body = response.json()
    assert "resources" in body["detail"].lower()

    # The stored value is untouched.
    assert config.load().resources.max_parallel_ffmpeg == 2


def test_a_negative_retention_is_refused(client: TestClient) -> None:
    response = client.put("/api/settings", json={"resources": {"work_retention_days": -1}})

    assert response.status_code == 400
    assert config.load().resources.work_retention_days == 7


# --------------------------------------------------------------------------
# Bounding the work
# --------------------------------------------------------------------------


def test_the_thread_cap_reaches_the_ffmpeg_command(
    autoclip_home: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """ffmpeg spawns one worker per core by default, which oversubscribes."""
    from autoclip.pipeline import ffmpeg

    captured: dict[str, list[str]] = {}

    class FakeProc:
        returncode = 0
        stdout = None
        stderr = None

        def communicate(self):  # pragma: no cover - trivial
            return "", ""

        def kill(self):  # pragma: no cover - trivial
            pass

        def wait(self):  # pragma: no cover - trivial
            return 0

    def fake_popen(command, **kwargs):
        captured["command"] = list(command)
        return FakeProc()

    monkeypatch.setattr(ffmpeg.subprocess, "Popen", fake_popen)
    monkeypatch.setattr(ffmpeg, "ffmpeg_path", lambda: "ffmpeg")

    ffmpeg.run(["-i", "in.mp4", "out.mp4"], threads=2)

    command = captured["command"]
    assert "-threads" in command
    assert command[command.index("-threads") + 1] == "2"
    assert "-filter_threads" in command


def test_no_thread_cap_leaves_ffmpeg_alone(
    autoclip_home: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from autoclip.pipeline import ffmpeg

    captured: dict[str, list[str]] = {}

    class FakeProc:
        returncode = 0
        stdout = None
        stderr = None

        def communicate(self):  # pragma: no cover - trivial
            return "", ""

        def kill(self):  # pragma: no cover - trivial
            pass

        def wait(self):  # pragma: no cover - trivial
            return 0

    def fake_popen(command, **kwargs):
        captured["command"] = list(command)
        return FakeProc()

    monkeypatch.setattr(
        ffmpeg.subprocess,
        "Popen",
        fake_popen,
    )
    monkeypatch.setattr(ffmpeg, "ffmpeg_path", lambda: "ffmpeg")

    ffmpeg.run(["-i", "in.mp4", "out.mp4"])

    assert "-threads" not in captured["command"]


def test_the_encoder_respects_the_thread_cap() -> None:
    from autoclip.pipeline import export

    settings = config.ExportSettings(prefer_hardware_encoder=False)

    assert "-threads" not in export.encoder_args(settings)
    args = export.encoder_args(settings, threads=3)
    assert args[args.index("-threads") + 1] == "3"


def test_the_detection_budget_caps_the_windows(
    autoclip_home: Path, initialised_db: int
) -> None:
    """A capped budget must say how much of the video it skipped."""
    import asyncio

    from autoclip.pipeline import highlights
    from autoclip.pipeline.transcript import Transcript, Word

    words = [Word(text=f"w{i}", start=i * 1.0, end=i * 1.0 + 0.5) for i in range(3000)]
    transcript = Transcript(words=words, language="en", model="test", source="whisper")

    class FakeProvider:
        name = "fake"
        calls = 0

        def __init__(self) -> None:
            self.last_usage = resources.TokenUsage()
            self.total_usage = resources.TokenUsage()

        async def detect_highlights(self, window, config):
            FakeProvider.calls += 1
            self.last_usage = resources.TokenUsage(calls=1, input_tokens=10, output_tokens=2)
            self.total_usage.add(self.last_usage)
            return type("Result", (), {"clips": []})()

    provider = FakeProvider()
    usage = resources.Usage()
    # The same windowing the detector uses, so the expected count matches.
    windows = highlights.build_windows(transcript)

    with pytest.raises(highlights.HighlightError):
        asyncio.run(
            highlights.detect(
                transcript,
                provider,  # type: ignore[arg-type]
                type("Config", (), {"min_duration_s": 20, "max_duration_s": 90})(),
                job_id="job",
                usage=usage,
                max_calls=2,
            )
        )

    assert FakeProvider.calls <= 2
    assert usage.llm.calls == FakeProvider.calls
    assert usage.windows_skipped == len(windows) - 2


def test_an_unlimited_budget_skips_nothing(
    autoclip_home: Path, initialised_db: int
) -> None:
    import asyncio

    from autoclip.pipeline import highlights
    from autoclip.pipeline.transcript import Transcript, Word

    words = [Word(text=f"w{i}", start=i * 1.0, end=i * 1.0 + 0.5) for i in range(500)]
    transcript = Transcript(words=words, language="en", model="test", source="whisper")

    class FakeProvider:
        name = "fake"

        def __init__(self) -> None:
            self.last_usage = resources.TokenUsage()
            self.total_usage = resources.TokenUsage()

        async def detect_highlights(self, window, config):
            self.last_usage = resources.TokenUsage(calls=1, input_tokens=10, output_tokens=2)
            self.total_usage.add(self.last_usage)
            return type("Result", (), {"clips": []})()

    usage = resources.Usage()
    with pytest.raises(highlights.HighlightError):
        asyncio.run(
            highlights.detect(
                transcript,
                FakeProvider(),  # type: ignore[arg-type]
                type("Config", (), {"min_duration_s": 20, "max_duration_s": 90})(),
                job_id="job",
                usage=usage,
                max_calls=0,
            )
        )

    assert usage.windows_skipped == 0
    assert usage.llm.calls > 0


def test_concurrent_windows_are_each_charged_exactly_once(
    autoclip_home: Path, initialised_db: int
) -> None:
    """The windows run in parallel, so the tokens must not be double-counted.

    The provider's "last call" figure is a race between them; only the
    running total can attribute every token to exactly one call.
    """
    import asyncio

    from autoclip.pipeline import highlights
    from autoclip.pipeline.transcript import Transcript, Word

    words = [Word(text=f"w{i}", start=i * 1.0, end=i * 1.0 + 0.5) for i in range(3000)]
    transcript = Transcript(words=words, language="en", model="test", source="whisper")

    class SlowProvider:
        name = "fake"

        def __init__(self) -> None:
            self.last_usage = resources.TokenUsage()
            self.total_usage = resources.TokenUsage()
            self.calls = 0

        async def detect_highlights(self, window, config):
            self.calls += 1
            # A pause makes the calls overlap, which is what breaks a
            # "read the last call's usage" approach.
            await asyncio.sleep(0.01)
            self.last_usage = resources.TokenUsage(calls=1, input_tokens=10, output_tokens=2)
            self.total_usage.add(self.last_usage)
            return type("Result", (), {"clips": []})()

    provider = SlowProvider()
    usage = resources.Usage()

    with pytest.raises(highlights.HighlightError):
        asyncio.run(
            highlights.detect(
                transcript,
                provider,  # type: ignore[arg-type]
                type("Config", (), {"min_duration_s": 20, "max_duration_s": 90})(),
                job_id="job",
                usage=usage,
                max_calls=0,
            )
        )

    assert provider.calls > 1, "the windows must actually overlap for this test to mean anything"
    assert usage.llm.calls == provider.calls
    assert usage.llm.input_tokens == provider.calls * 10
    assert usage.llm.output_tokens == provider.calls * 2


# --------------------------------------------------------------------------
# The schema
# --------------------------------------------------------------------------

def test_the_schema_migrates_to_v11(autoclip_home: Path) -> None:
    from autoclip import db

    version = db.init()

    assert version == 11
    with db.connection() as conn:
        assert conn.execute("PRAGMA user_version").fetchone()[0] == 11
        rows = conn.execute("SELECT name FROM sqlite_master WHERE type = 'table'").fetchall()
        tables = {row[0] for row in rows}
    assert "job_resources" in tables


def test_migrating_twice_is_a_no_op(autoclip_home: Path) -> None:
    from autoclip import db

    first = db.init()
    second = db.init()

    assert first == second == 11
