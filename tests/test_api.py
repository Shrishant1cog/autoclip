"""REST API contract tests.

Exercised through the real app with its lifespan running, so the database
migration, event broker binding, and job queue startup are all covered too.
"""

from __future__ import annotations

import json
import sys
from collections.abc import Iterator

import pytest
from autoclip import app as app_module
from autoclip import config
from autoclip.app import create_app
from autoclip.db import store
from autoclip.db.models import Clip, Job, Source, new_id
from fastapi.testclient import TestClient


@pytest.fixture
def client(autoclip_home, monkeypatch: pytest.MonkeyPatch) -> Iterator[TestClient]:
    # The background worker is off here so queued jobs stay queued: these tests
    # are about the HTTP contract, and a worker racing to pick jobs up would
    # make every status assertion flaky. The worker has its own tests.
    monkeypatch.setenv(app_module.ENV_NO_WORKER, "1")
    with TestClient(create_app()) as test_client:
        yield test_client


@pytest.fixture
def source() -> Source:
    return store.create_source(
        Source(
            id=new_id(),
            type="upload",
            path="C:/media/video.mp4",
            title="Test source",
            duration_s=600.0,
            width=1920,
            height=1080,
            fps=30.0,
        )
    )


class TestHealthAndSystem:
    def test_health(self, client: TestClient) -> None:
        response = client.get("/api/health")

        assert response.status_code == 200
        assert response.json()["status"] == "ok"

    def test_system_reports_this_machine(self, client: TestClient) -> None:
        body = client.get("/api/system").json()

        # Compared against the running interpreter, not a hardcoded version:
        # the project supports 3.11 and 3.12, and pinning the assertion to one
        # of them made the test contradict the CI matrix it runs under.
        running = f"{sys.version_info.major}.{sys.version_info.minor}"
        assert body["python_version"].startswith(running)
        assert (3, 11) <= sys.version_info[:2] < (3, 13)

        assert body["accel"] in ("cuda", "mps", "cpu")
        assert isinstance(body["nvenc_works"], bool)

    def test_unknown_api_route_is_404_not_the_spa(self, client: TestClient) -> None:
        # The SPA catch-all must never swallow a mistyped API path — that turns
        # a clear 404 into an HTML page the client can't parse.
        assert client.get("/api/does-not-exist").status_code == 404


class TestCaptionStyles:
    def test_lists_all_four(self, client: TestClient) -> None:
        styles = client.get("/api/caption-styles").json()

        assert {s["key"] for s in styles} == {
            "bold_pop",
            "karaoke_fill",
            "clean_lower",
            "boxed",
        }

    def test_includes_preview_metadata(self, client: TestClient) -> None:
        styles = client.get("/api/caption-styles").json()
        preview = next(s for s in styles if s["key"] == "bold_pop")["preview"]

        assert preview["accent"]
        assert preview["allCaps"] is True
        assert preview["maxWords"] > 0


class TestSettings:
    def test_get_returns_defaults(self, client: TestClient) -> None:
        body = client.get("/api/settings").json()

        assert body["active_provider"] == "anthropic"
        assert body["whisper"]["model"] == "small"

    def test_the_subtitles_are_in_english_by_default(self, client: TestClient) -> None:
        """English is the default, so nothing has to be set up for it."""
        body = client.get("/api/settings").json()

        assert body["export"]["subtitle_language"] == "en"

    def test_the_subtitle_language_can_be_changed(self, client: TestClient) -> None:
        response = client.put("/api/settings", json={"export": {"subtitle_language": "hi"}})

        assert response.status_code == 200
        assert response.json()["export"]["subtitle_language"] == "hi"
        assert client.get("/api/settings").json()["export"]["subtitle_language"] == "hi"

    def test_the_subtitles_can_follow_the_video(self, client: TestClient) -> None:
        response = client.put("/api/settings", json={"export": {"subtitle_language": "source"}})

        assert response.status_code == 200
        assert response.json()["export"]["subtitle_language"] == "source"

    def test_a_language_that_is_not_a_language_is_rejected(self, client: TestClient) -> None:
        response = client.put("/api/settings", json={"export": {"subtitle_language": "klingon"}})

        assert response.status_code == 400

    def test_partial_update_leaves_other_sections_alone(self, client: TestClient) -> None:
        client.put("/api/settings", json={"whisper": {"model": "large-v3"}})

        body = client.get("/api/settings").json()
        assert body["whisper"]["model"] == "large-v3"
        assert body["clips"]["max_clips"] == 10

    def test_provider_switch(self, client: TestClient) -> None:
        response = client.put("/api/settings", json={"active_provider": "ollama"})

        assert response.status_code == 200
        assert response.json()["active_provider"] == "ollama"

    def test_unknown_provider_is_rejected(self, client: TestClient) -> None:
        response = client.put("/api/settings", json={"active_provider": "skynet"})

        assert response.status_code == 400

    def test_inverted_clip_lengths_are_rejected(self, client: TestClient) -> None:
        response = client.put(
            "/api/settings", json={"clips": {"min_duration_s": 90, "max_duration_s": 20}}
        )

        assert response.status_code == 400

    def test_the_provider_timeout_and_context_are_stored(self, client: TestClient) -> None:
        """A local model needs both: one request can outlast a fixed ceiling,
        and the prompt has to fit the context the server is running with."""
        response = client.put(
            "/api/settings",
            json={"providers": {"ollama": {"timeout_s": 900, "context_tokens": 8192}}},
        )

        assert response.status_code == 200
        provider = response.json()["providers"]["ollama"]
        assert provider["timeout_s"] == 900
        assert provider["context_tokens"] == 8192

    def test_a_negative_provider_timeout_is_rejected(self, client: TestClient) -> None:
        """The update path validated nothing before, so a negative timeout
        would have been stored and used as if it were a number."""
        response = client.put("/api/settings", json={"providers": {"ollama": {"timeout_s": -1}}})

        assert response.status_code == 400

    def test_secrets_are_never_returned(self, client: TestClient, fake_keyring) -> None:
        client.put("/api/settings/secrets", json={"key": "anthropic", "value": "sk-secret-value"})

        body = client.get("/api/settings").json()

        assert "sk-secret-value" not in str(body)
        assert body["keys_present"]["anthropic"] is True

    def test_empty_secret_is_rejected(self, client: TestClient, fake_keyring) -> None:
        response = client.put("/api/settings/secrets", json={"key": "anthropic", "value": "   "})

        assert response.status_code == 400

    def test_unknown_secret_key_is_rejected(self, client: TestClient) -> None:
        response = client.put("/api/settings/secrets", json={"key": "aws", "value": "x"})

        assert response.status_code == 400

    def test_secret_can_be_deleted(self, client: TestClient, fake_keyring) -> None:
        client.put("/api/settings/secrets", json={"key": "openai", "value": "sk-x"})
        client.delete("/api/settings/secrets/openai")

        assert client.get("/api/settings").json()["keys_present"]["openai"] is False


class TestSources:
    def test_empty_initially(self, client: TestClient) -> None:
        assert client.get("/api/sources").json() == []

    def test_lists_a_created_source(self, client: TestClient, source: Source) -> None:
        body = client.get("/api/sources").json()

        assert len(body) == 1
        assert body[0]["title"] == "Test source"

    def test_never_exposes_the_filesystem_path(self, client: TestClient, source: Source) -> None:
        body = client.get(f"/api/sources/{source.id}").json()

        assert "path" not in body
        assert "C:/media" not in str(body)

    def test_missing_source_is_404(self, client: TestClient) -> None:
        assert client.get("/api/sources/nope").status_code == 404

    def test_non_youtube_url_is_rejected(self, client: TestClient) -> None:
        response = client.post("/api/sources/youtube", json={"url": "https://vimeo.com/12345"})

        assert response.status_code == 400

    def test_unsupported_upload_type_is_rejected(self, client: TestClient) -> None:
        response = client.post(
            "/api/sources/upload",
            files={"file": ("notes.txt", b"hello", "text/plain")},
        )

        assert response.status_code == 415
        body = response.json()
        # The unified error shape (Phase 15): a flat detail plus a stable code.
        assert "supported" in body["detail"]
        assert body["code"] == "validation"
        assert body["hint"]
        assert body["retryable"] is False


class TestJobs:
    def test_create_and_fetch(self, client: TestClient, source: Source) -> None:
        created = client.post("/api/jobs", json={"source_id": source.id})

        assert created.status_code == 201
        job_id = created.json()["id"]

        fetched = client.get(f"/api/jobs/{job_id}").json()
        assert fetched["status"] == "queued"
        assert fetched["source"]["title"] == "Test source"

    def test_overrides_are_applied(self, client: TestClient, source: Source) -> None:
        response = client.post(
            "/api/jobs",
            json={
                "source_id": source.id,
                "settings": {"provider": "ollama", "max_clips": 3},
            },
        )

        assert response.json()["provider"] == "ollama"

    def test_missing_source_is_404(self, client: TestClient) -> None:
        response = client.post("/api/jobs", json={"source_id": "nope"})

        assert response.status_code == 404

    def test_inverted_durations_are_rejected(self, client: TestClient, source: Source) -> None:
        response = client.post(
            "/api/jobs",
            json={
                "source_id": source.id,
                "settings": {"min_duration_s": 90, "max_duration_s": 20},
            },
        )

        assert response.status_code == 400

    def test_cancel_a_queued_job(self, client: TestClient, source: Source) -> None:
        job_id = client.post("/api/jobs", json={"source_id": source.id}).json()["id"]

        response = client.post(f"/api/jobs/{job_id}/cancel")

        assert response.status_code == 200
        assert client.get(f"/api/jobs/{job_id}").json()["status"] == "cancelled"

    def test_cancelling_a_finished_job_conflicts(self, client: TestClient, source: Source) -> None:
        job = store.create_job(Job(id=new_id(), source_id=source.id, status="done"))

        assert client.post(f"/api/jobs/{job.id}/cancel").status_code == 409

    def test_retry_requeues_a_failed_job(self, client: TestClient, source: Source) -> None:
        job = store.create_job(Job(id=new_id(), source_id=source.id, status="failed", error="boom"))

        response = client.post(f"/api/jobs/{job.id}/retry")

        assert response.status_code == 200
        assert response.json()["status"] == "queued"
        assert response.json()["error"] is None

    def test_retrying_a_running_job_conflicts(self, client: TestClient, source: Source) -> None:
        job = store.create_job(Job(id=new_id(), source_id=source.id, status="running"))

        assert client.post(f"/api/jobs/{job.id}/retry").status_code == 409

    def test_missing_job_is_404(self, client: TestClient) -> None:
        assert client.get("/api/jobs/nope").status_code == 404
        assert client.post("/api/jobs/nope/cancel").status_code == 404
        assert client.post("/api/jobs/nope/retry").status_code == 404


class TestClips:
    @pytest.fixture
    def job_with_clips(self, source: Source) -> Job:
        job = store.create_job(Job(id=new_id(), source_id=source.id, status="done"))
        store.replace_clips(
            job.id,
            [
                Clip(
                    id=new_id(),
                    job_id=job.id,
                    rank=rank,
                    start_s=rank * 60.0,
                    end_s=rank * 60.0 + 40.0,
                    start_word=rank * 100,
                    end_word=rank * 100 + 80,
                    title=f"Clip {rank}",
                    score=90 - rank,
                )
                for rank in (1, 2, 3)
            ],
        )
        return job

    def test_list_clips_for_a_job(self, client: TestClient, job_with_clips: Job) -> None:
        clips = client.get(f"/api/jobs/{job_with_clips.id}/clips").json()

        assert len(clips) == 3
        assert [c["rank"] for c in clips] == [1, 2, 3]
        assert clips[0]["duration_s"] == pytest.approx(40.0)

    def test_library_lists_clips_with_their_source_and_job_status(
        self, client: TestClient, job_with_clips: Job, source: Source
    ) -> None:
        body = client.get("/api/clips").json()

        assert len(body) == 3
        assert {clip["source_title"] for clip in body} == {source.title}
        assert {clip["job_status"] for clip in body} == {"done"}
        assert {clip["job_id"] for clip in body} == {job_with_clips.id}
        assert all(isinstance(clip["exports"], list) for clip in body)

    def test_library_respects_limit(self, client: TestClient, job_with_clips: Job) -> None:
        assert len(client.get("/api/clips?limit=2").json()) == 2

    def test_patch_title_and_status(self, client: TestClient, job_with_clips: Job) -> None:
        clip_id = client.get(f"/api/jobs/{job_with_clips.id}/clips").json()[0]["id"]

        response = client.patch(
            f"/api/clips/{clip_id}", json={"title": "Renamed", "status": "kept"}
        )

        assert response.status_code == 200
        assert response.json()["title"] == "Renamed"
        assert response.json()["status"] == "kept"

    def test_inverted_trim_is_rejected(self, client: TestClient, job_with_clips: Job) -> None:
        clip_id = client.get(f"/api/jobs/{job_with_clips.id}/clips").json()[0]["id"]

        response = client.patch(f"/api/clips/{clip_id}", json={"start_s": 90.0, "end_s": 30.0})

        assert response.status_code == 400

    def test_caption_style_is_persisted(self, client: TestClient, job_with_clips: Job) -> None:
        clip_id = client.get(f"/api/jobs/{job_with_clips.id}/clips").json()[0]["id"]

        response = client.patch(
            f"/api/clips/{clip_id}/captions", json={"caption_style": "karaoke_fill"}
        )

        assert response.status_code == 200
        assert response.json()["caption_style"] == "karaoke_fill"

    def test_unknown_caption_style_is_rejected(
        self, client: TestClient, job_with_clips: Job
    ) -> None:
        clip_id = client.get(f"/api/jobs/{job_with_clips.id}/clips").json()[0]["id"]

        response = client.patch(
            f"/api/clips/{clip_id}/captions", json={"caption_style": "explosion"}
        )

        assert response.status_code == 400

    def test_missing_clip_is_404(self, client: TestClient) -> None:
        assert client.get("/api/clips/nope").status_code == 404
        assert client.patch("/api/clips/nope", json={"title": "x"}).status_code == 404
        assert client.get("/api/clips/nope/crop-path").status_code == 404

    def test_crop_path_is_404_before_reframe(self, client: TestClient, job_with_clips: Job) -> None:
        # The review player treats this as "fall back to a centre crop", which
        # is what the renderer does for these clips too.
        clip_id = client.get(f"/api/jobs/{job_with_clips.id}/clips").json()[0]["id"]

        assert client.get(f"/api/clips/{clip_id}/crop-path").status_code == 404

    def test_crop_path_is_served_when_present(
        self, client: TestClient, job_with_clips: Job, autoclip_home
    ) -> None:
        from autoclip.pipeline.reframe.croppath import centre_crop
        from autoclip.pipeline.runner import JobWorkspace

        clip = client.get(f"/api/jobs/{job_with_clips.id}/clips").json()[0]
        path = centre_crop(1920, 1080, clip["duration_s"])
        path.save(JobWorkspace(job_with_clips.id).crop_path(clip["id"]))

        body = client.get(f"/api/clips/{clip['id']}/crop-path").json()

        assert body["source_width"] == 1920
        assert body["source_height"] == 1080
        assert len(body["segments"]) == 1
        # The client needs these to position the video; a missing field means a
        # silently centre-cropped preview that disagrees with the export.
        segment = body["segments"][0]
        assert {"start_s", "end_s", "width", "height", "keyframes", "fit"} <= segment.keys()

    def test_words_need_a_transcript(self, client: TestClient, job_with_clips: Job) -> None:
        # The job has clips but no transcript on disk, which is exactly the
        # state a partially-restored workspace would be in.
        clip_id = client.get(f"/api/jobs/{job_with_clips.id}/clips").json()[0]["id"]

        assert client.get(f"/api/clips/{clip_id}/words").status_code == 404


class TestClipExportHonoursTheUsersMusic:
    """A re-export must render what the user chose, not what was left over.

    The pipeline's own export stage takes the music from the creative
    stage's selection. A re-export from the review page has no creative
    stage, so the user's own choice — the clip's, the source's or the
    global one — is what the renderer has to be given. Before this was
    fixed, the review page's "Export this clip" rendered the plain speech
    audio: the chosen track and the ducking were both silently dropped.
    """

    @pytest.fixture
    def track(self, tmp_path) -> str:
        from autoclip.music import store as music_store
        from autoclip.music.licensing import LicenseRecord, LicenseState

        bed = tmp_path / "bed.wav"
        bed.write_bytes(b"RIFF....WAVEfmt ")
        indexed = music_store.upsert_track(bed)
        music_store.set_license(
            LicenseRecord(
                track_id=indexed.id,
                state=LicenseState.USER_CONFIRMED,
                source="test",
                evidence="A fixture.",
            )
        )
        return indexed.id

    @pytest.fixture
    def job(self, source: Source) -> Job:
        from autoclip.pipeline.runner import JobWorkspace
        from autoclip.pipeline.transcript import Transcript, Word

        created = store.create_job(Job(id=new_id(), source_id=source.id, status="done"))
        store.replace_clips(
            created.id,
            [
                Clip(
                    id=new_id(),
                    job_id=created.id,
                    rank=1,
                    start_s=60.0,
                    end_s=100.0,
                    start_word=0,
                    end_word=4,
                    title="Clip 1",
                    score=90,
                )
            ],
        )
        # The review page reads the clip's words from the transcript.
        Transcript(
            words=[
                Word(text=f"word{index}", start=60.0 + index, end=61.0 + index)
                for index in range(5)
            ]
        ).save(JobWorkspace(created.id).transcript)
        return created

    @pytest.fixture
    def rendered(self, monkeypatch):
        """Capture what the renderer was asked for, without rendering anything."""
        from autoclip.pipeline import export as export_module
        from autoclip.pipeline import validate as validate_module

        calls: list[dict] = []

        def fake_export(request, *, work_dir, settings=None, **kwargs):
            calls.append({"request": request, "settings": settings})
            request.destination.parent.mkdir(parents=True, exist_ok=True)
            request.destination.write_bytes(b"0" * 64)
            return request.destination

        monkeypatch.setattr(export_module, "export_clip", fake_export)
        monkeypatch.setattr(
            validate_module,
            "validate_media",
            lambda *args, **kwargs: validate_module.ValidationReport(
                ok=True, checks=[], duration_s=40.0, width=1080, height=1920
            ),
        )
        return calls

    def _export(self, client: TestClient, job: Job) -> dict:
        clip_id = client.get(f"/api/jobs/{job.id}/clips").json()[0]["id"]
        response = client.post(
            f"/api/clips/{clip_id}/export",
            json={"ratio": "9:16", "style": "bold_pop"},
        )
        assert response.status_code == 201, response.text
        return {"clip_id": clip_id, "response": response}

    def test_the_clips_own_choice_is_used(
        self, client: TestClient, job: Job, track: str, rendered: list
    ) -> None:
        from autoclip.music import preferences as music_preferences
        from autoclip.music import store as music_store

        clip_id = client.get(f"/api/jobs/{job.id}/clips").json()[0]["id"]
        music_preferences.set_preference(music_preferences.SCOPE_CLIP, clip_id, track)

        self._export(client, job)

        expected = music_store.get_track(track).path
        assert rendered[0]["settings"].music_track == expected

    def test_the_sources_choice_is_used_when_the_clip_has_none(
        self, client: TestClient, job: Job, source: Source, track: str, rendered: list
    ) -> None:
        from autoclip.music import preferences as music_preferences
        from autoclip.music import store as music_store

        music_preferences.set_preference(music_preferences.SCOPE_SOURCE, source.id, track)

        self._export(client, job)

        expected = music_store.get_track(track).path
        assert rendered[0]["settings"].music_track == expected

    def test_the_global_choice_is_used_when_nothing_more_specific_is_set(
        self, client: TestClient, job: Job, track: str, rendered: list
    ) -> None:
        from autoclip.music import preferences as music_preferences
        from autoclip.music import store as music_store

        music_preferences.set_preference(music_preferences.SCOPE_GLOBAL, "", track)

        self._export(client, job)

        expected = music_store.get_track(track).path
        assert rendered[0]["settings"].music_track == expected

    def test_no_music_wins_over_the_global_export_setting(
        self, client: TestClient, job: Job, rendered: list
    ) -> None:
        from autoclip.music import preferences as music_preferences

        settings = config.load()
        settings.export.music_track = "bed.wav"
        config.save(settings)

        clip_id = client.get(f"/api/jobs/{job.id}/clips").json()[0]["id"]
        music_preferences.set_preference(
            music_preferences.SCOPE_CLIP, clip_id, music_preferences.NO_MUSIC
        )

        self._export(client, job)

        # "No music" is an answer, not a gap: the bed stays off even though
        # the global export setting names a track.
        assert rendered[0]["settings"].music_track == ""

    def test_no_preference_anywhere_keeps_the_global_export_setting(
        self, client: TestClient, job: Job, rendered: list
    ) -> None:
        settings = config.load()
        settings.export.music_track = "bed.wav"
        config.save(settings)

        self._export(client, job)

        # A gap falls back to the setting, so an install that configured a
        # bed keeps it.
        assert rendered[0]["settings"].music_track == "bed.wav"

    def test_the_speech_timeline_is_passed_to_the_renderer(
        self, client: TestClient, job: Job, rendered: list
    ) -> None:
        from autoclip.pipeline.runner import JobWorkspace
        from autoclip.pipeline.speech_timeline import SpeechInterval, SpeechTimeline

        SpeechTimeline(
            intervals=[
                SpeechInterval(start_ms=70_000, end_ms=75_000, source="vad"),
                SpeechInterval(start_ms=10_000, end_ms=12_000, source="vad"),
            ],
            duration_s=180.0,
        ).save(JobWorkspace(job.id).speech_timeline)

        self._export(client, job)

        intervals = rendered[0]["request"].speech_intervals
        # The clip starts at 60s, so the timeline is re-based on the clip's
        # own first frame — the renderer counts from there.
        assert [(i.start_ms, i.end_ms) for i in intervals] == [(10_000, 15_000)]

    def test_a_timeline_with_no_speech_in_this_clip_is_not_a_missing_timeline(
        self, client: TestClient, job: Job, rendered: list
    ) -> None:
        """An empty slice and an absent timeline are different answers.

        The timeline exists and found speech — just not in this clip. The
        renderer has to be told "there is nothing to duck under", which is
        not the same as "there is no timeline, work it out from the audio".
        """
        from autoclip.pipeline.runner import JobWorkspace
        from autoclip.pipeline.speech_timeline import SpeechInterval, SpeechTimeline

        SpeechTimeline(
            intervals=[SpeechInterval(start_ms=10_000, end_ms=12_000, source="vad")],
            duration_s=180.0,
        ).save(JobWorkspace(job.id).speech_timeline)

        self._export(client, job)

        # The clip runs from 60s to 100s, and the only interval is at 10s.
        assert rendered[0]["request"].speech_intervals == []

    def test_no_timeline_at_all_is_reported_as_none(
        self, client: TestClient, job: Job, rendered: list
    ) -> None:
        """With no timeline the renderer is told to key on the audio itself."""
        self._export(client, job)

        assert rendered[0]["request"].speech_intervals is None

    def test_a_blocked_licence_is_a_clean_error(
        self, client: TestClient, job: Job, track: str
    ) -> None:
        from autoclip.music import preferences as music_preferences
        from autoclip.music import store as music_store
        from autoclip.music.licensing import LicenseRecord, LicenseState

        music_store.set_license(
            LicenseRecord(track_id=track, state=LicenseState.UNKNOWN, source="test")
        )
        clip_id = client.get(f"/api/jobs/{job.id}/clips").json()[0]["id"]
        music_preferences.set_preference(music_preferences.SCOPE_CLIP, clip_id, track)

        response = client.post(
            f"/api/clips/{clip_id}/export",
            json={"ratio": "9:16", "style": "bold_pop"},
        )

        # The real renderer runs here, and its licence gate stops the export
        # before any ffmpeg work. The user gets the reason, not a stack trace.
        assert response.status_code == 409
        assert "licence is unknown" in response.json()["detail"]


class TestProviderStatus:
    def test_reports_every_provider(self, client: TestClient, fake_keyring) -> None:
        statuses = client.get("/api/providers/status").json()

        assert {s["name"] for s in statuses} == {
            "anthropic",
            "openai",
            "gemini",
            "ollama",
        }

    def test_missing_key_is_reported_as_unavailable(self, client: TestClient, fake_keyring) -> None:
        statuses = {s["name"]: s for s in client.get("/api/providers/status").json()}

        assert statuses["anthropic"]["has_key"] is False
        assert statuses["anthropic"]["available"] is False

    def test_ollama_never_requires_a_key(self, client: TestClient) -> None:
        statuses = {s["name"]: s for s in client.get("/api/providers/status").json()}

        assert statuses["ollama"]["requires_key"] is False


class TestEventStream:
    def test_finished_job_streams_a_snapshot_and_closes(
        self, client: TestClient, source: Source
    ) -> None:
        job = store.create_job(Job(id=new_id(), source_id=source.id, status="done", progress=1.0))

        with client.stream("GET", f"/api/jobs/{job.id}/events") as response:
            assert response.status_code == 200
            body = "".join(response.iter_text())

        # A client opening the stream after completion must still learn the
        # final state rather than hanging on an empty connection.
        assert "snapshot" in body
        assert "done" in body

    def test_missing_job_is_404(self, client: TestClient) -> None:
        assert client.get("/api/jobs/nope/events").status_code == 404

    def test_the_snapshot_carries_the_source(self, client: TestClient, source: Source) -> None:
        """The snapshot is the same shape as ``GET /api/jobs/{id}``.

        The progress page fetches the job once and then replaces it with
        whatever the stream sends. If the snapshot carries no source, the
        title, the duration and the resolution all disappear from the page
        the moment the stream opens — which is the moment the user is
        watching.
        """
        job = store.create_job(Job(id=new_id(), source_id=source.id, status="done", progress=1.0))

        with client.stream("GET", f"/api/jobs/{job.id}/events") as response:
            body = "".join(response.iter_text())

        payload = json.loads(body.split("data: ", 1)[1].split("\n", 1)[0])

        assert payload["source"] is not None
        assert payload["source"]["id"] == source.id
        assert payload["source"]["title"] == source.title


class TestSecretsNeverLeak:
    def test_settings_response_has_no_secret_values(self, client: TestClient, fake_keyring) -> None:
        for key in ("anthropic", "openai", "gemini"):
            client.put("/api/settings/secrets", json={"key": key, "value": f"sk-{key}-DEADBEEF"})

        payload = str(client.get("/api/settings").json())

        assert "DEADBEEF" not in payload

    def test_config_file_has_no_secrets_when_keyring_works(
        self, client: TestClient, fake_keyring, autoclip_home
    ) -> None:
        client.put("/api/settings/secrets", json={"key": "anthropic", "value": "sk-DEADBEEF"})
        client.put("/api/settings", json={"whisper": {"model": "medium"}})

        from autoclip import paths

        assert "DEADBEEF" not in paths.config_path().read_text(encoding="utf-8")
        assert config.get_secret("anthropic") == "sk-DEADBEEF"


class TestClipsWithTheSameTitle:
    """Two clips of one job can carry the same title.

    The exports live in one directory, so a file name built from the title
    alone lets the second export overwrite the first: the clip is gone, and
    its subtitles with it. A real run produced exactly that — two clips the
    model had both called "The language of love in videos", and one export
    file of 14 MB replaced by another of 54 MB.
    """

    TITLE = "The language of love in videos"

    @pytest.fixture
    def job(self, source: Source) -> Job:
        from autoclip.pipeline.runner import JobWorkspace
        from autoclip.pipeline.transcript import Transcript, Word

        created = store.create_job(Job(id=new_id(), source_id=source.id, status="done"))
        store.replace_clips(
            created.id,
            [
                Clip(
                    id=new_id(),
                    job_id=created.id,
                    rank=1,
                    start_s=60.0,
                    end_s=100.0,
                    start_word=0,
                    end_word=4,
                    title=self.TITLE,
                    score=70,
                ),
                Clip(
                    id=new_id(),
                    job_id=created.id,
                    rank=2,
                    start_s=120.0,
                    end_s=160.0,
                    start_word=10,
                    end_word=14,
                    title=self.TITLE,
                    score=65,
                ),
            ],
        )
        Transcript(
            words=[
                Word(text=f"word{index}", start=float(index), end=float(index) + 0.5)
                for index in range(20)
            ]
        ).save(JobWorkspace(created.id).transcript)
        return created

    @pytest.fixture
    def rendered(self, monkeypatch):
        """Capture what the renderer was asked for, without rendering anything."""
        from autoclip.pipeline import export as export_module
        from autoclip.pipeline import validate as validate_module

        calls: list = []

        def fake_export(request, *, work_dir, settings=None, **kwargs):
            calls.append(request)
            request.destination.parent.mkdir(parents=True, exist_ok=True)
            request.destination.write_bytes(b"0" * 64)
            return request.destination

        monkeypatch.setattr(export_module, "export_clip", fake_export)
        monkeypatch.setattr(
            validate_module,
            "validate_media",
            lambda *args, **kwargs: validate_module.ValidationReport(
                ok=True, checks=[], duration_s=40.0, width=1080, height=1920
            ),
        )
        return calls

    def test_the_two_exports_get_different_files(
        self, client: TestClient, job: Job, rendered: list
    ) -> None:
        clips = client.get(f"/api/jobs/{job.id}/clips").json()

        for clip in clips:
            response = client.post(
                f"/api/clips/{clip['id']}/export",
                json={"ratio": "9:16", "style": "bold_pop"},
            )
            assert response.status_code == 201, response.text

        destinations = [request.destination for request in rendered]
        assert len(destinations) == 2
        assert destinations[0] != destinations[1]

    def test_both_exports_are_recorded(self, client: TestClient, job: Job, rendered: list) -> None:
        clips = client.get(f"/api/jobs/{job.id}/clips").json()

        for clip in clips:
            response = client.post(
                f"/api/clips/{clip['id']}/export",
                json={"ratio": "9:16", "style": "bold_pop"},
            )
            assert response.status_code == 201, response.text

        recorded = [export.path for export in store.list_exports(clips[0]["id"])]
        recorded += [export.path for export in store.list_exports(clips[1]["id"])]
        assert len(set(recorded)) == 2
