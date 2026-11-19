"""Phase 15 — unified error handling and the recovery centre."""

from __future__ import annotations

import pytest
from autoclip import errors
from autoclip.db import store
from autoclip.db.models import Clip, Export, Job, Source, YouTubeUpload, new_id
from fastapi.testclient import TestClient

# --------------------------------------------------------------------------
# Helpers
# --------------------------------------------------------------------------


def _seed_source(title: str = "A Video") -> Source:
    source = Source(id=new_id(), type="upload", path="C:/videos/source.mp4", title=title)
    store.create_source(source)
    return source


def _seed_job(source: Source, *, status: str = "failed", error: str | None = None) -> Job:
    job = Job(id=new_id(), source_id=source.id, status=status, error=error)
    store.create_job(job)
    return job


def _seed_clip(job: Job, *, title: str = "A Clip", status: str = "invalid") -> Clip:
    clip = Clip(
        id=new_id(), job_id=job.id, start_s=0.0, end_s=20.0, rank=1, title=title, status=status
    )
    store.replace_clips(job.id, [clip])
    return clip


# --------------------------------------------------------------------------
# The taxonomy
# --------------------------------------------------------------------------


def test_quota_is_recognised() -> None:
    info = errors.classify(RuntimeError("YouTube API quota exceeded for this project"))
    assert info.code == errors.QUOTA
    assert info.retryable is True
    assert info.status == 429
    assert "quota" in info.hint.lower()


def test_rate_limit_is_retryable() -> None:
    info = errors.classify(RuntimeError("429 Too Many Requests"))
    assert info.code == errors.RATE_LIMIT
    assert info.retryable is True


def test_auth_failure_is_not_retryable() -> None:
    info = errors.classify(RuntimeError("401 Unauthorized: invalid api key"))
    assert info.code == errors.AUTH
    assert info.retryable is False
    assert "Settings" in info.hint


def test_a_response_validation_error_is_never_an_auth_failure() -> None:
    """A response this app could not build is a bug, not a bad key.

    The message can quote anything the payload contained — a provider's
    "401" among it — so the markers must not be read from it. Reporting
    this as an auth failure would tell the user to check a key that was
    never the problem.
    """
    from fastapi.exceptions import ResponseValidationError

    exc = ResponseValidationError(
        [
            {
                "type": "dict_type",
                "loc": ("response", 0),
                "msg": "Input should be a valid dictionary",
                "input": "Error code: 401 - Incorrect API key provided.",
            }
        ],
        body="[]",
    )

    info = errors.classify(exc)

    assert info.code == errors.INTERNAL
    assert info.status == 500


def test_network_failure_is_retryable() -> None:
    info = errors.classify(RuntimeError("Connection reset by peer"))
    assert info.code == errors.NETWORK
    assert info.retryable is True


def test_timeout_is_retryable() -> None:
    info = errors.classify(RuntimeError("The request timed out"))
    assert info.code == errors.TIMEOUT
    assert info.retryable is True


def test_provider_error_is_classified() -> None:
    from autoclip.providers.base import ProviderError

    info = errors.classify(ProviderError("The provider refused the request."))
    assert info.code == errors.PROVIDER
    assert info.retryable is False


def test_unknown_errors_stay_internal() -> None:
    """An unrecognised failure is not given a guessed cause."""
    info = errors.classify(RuntimeError("Something entirely unexpected happened"))
    assert info.code == errors.INTERNAL
    assert info.retryable is True  # internal errors are worth one retry


def test_the_real_message_is_always_kept() -> None:
    text = "ffmpeg exited with code 1 while writing the output"
    info = errors.classify(RuntimeError(text))
    assert info.message == text


def test_an_explicit_code_wins() -> None:
    class Coded(RuntimeError):
        code = "config"

    info = errors.classify(Coded("Something is misconfigured"))
    assert info.code == "config"
    assert info.status == 400


def test_a_missing_file_is_not_found(autoclip_home, initialised_db: int) -> None:
    """A file that is gone is a missing item, not an unexpected crash."""
    info = errors.classify(
        RuntimeError("The exported file has been moved or deleted. Export the clip again.")
    )
    assert info.code == errors.NOT_FOUND
    assert info.retryable is False


def test_ffmpeg_failures_are_media(autoclip_home, initialised_db: int) -> None:
    info = errors.classify(RuntimeError("ffmpeg exited with code 1"))
    assert info.code == errors.MEDIA


def test_classify_text_defaults_to_internal() -> None:
    info = errors.classify_text("the pipeline gave up")
    assert info.code == errors.INTERNAL
    assert info.message == "the pipeline gave up"


def test_error_info_response_shape() -> None:
    info = errors.classify(RuntimeError("quota exceeded"))
    body = info.to_response()
    assert set(body) == {"detail", "code", "hint", "retryable"}
    assert body["code"] == errors.QUOTA


def test_row_id_extraction() -> None:
    assert errors.row_id_in("upload 0123456789abcdef failed") == "0123456789abcdef"
    assert errors.row_id_in("no id here") == ""


# --------------------------------------------------------------------------
# The API error shape
# --------------------------------------------------------------------------


def test_http_errors_use_the_unified_shape(autoclip_home, initialised_db: int) -> None:
    from autoclip.app import create_app

    with TestClient(create_app(), raise_server_exceptions=False) as client:
        response = client.get("/api/clips/does-not-exist")
        assert response.status_code == 404
        body = response.json()
        assert body["code"] == errors.NOT_FOUND
        assert body["retryable"] is False
        assert body["detail"]


def test_unhandled_errors_use_the_unified_shape(
    autoclip_home, initialised_db: int, monkeypatch: pytest.MonkeyPatch
) -> None:
    """An unexpected exception becomes a classified 500, not a stack trace."""
    from autoclip.app import create_app

    def boom(_clip_id: str):
        raise RuntimeError("the widget exploded")

    monkeypatch.setattr(store, "get_clip", boom)

    with TestClient(create_app(), raise_server_exceptions=False) as client:
        response = client.get("/api/clips/anything")
        assert response.status_code == 500
        body = response.json()
        assert body["code"] == errors.INTERNAL
        assert body["detail"] == "the widget exploded"
        assert body["retryable"] is True
        assert "Traceback" not in body["detail"]


def test_validation_errors_are_classified(autoclip_home, initialised_db: int) -> None:
    from autoclip.app import create_app

    with TestClient(create_app()) as client:
        response = client.post("/api/chat", json={"message": 123})
        assert response.status_code == 422
        body = response.json()
        assert body["code"] == errors.VALIDATION
        assert body["retryable"] is False


# --------------------------------------------------------------------------
# The recovery centre
# --------------------------------------------------------------------------


def test_recovery_lists_failed_jobs(autoclip_home, initialised_db: int) -> None:
    source = _seed_source("Broken Video")
    job = _seed_job(source, error="ffmpeg exited with code 1")

    report = __import__("autoclip.recovery", fromlist=["build_report"]).build_report()

    assert report["counts"]["job"] == 1
    item = report["items"][0]
    assert item["kind"] == "job"
    assert item["title"] == "Broken Video"
    assert "ffmpeg exited with code 1" in item["detail"]
    assert item["action"] == f"/api/jobs/{job.id}/retry"
    assert item["retryable"] is True


def test_recovery_lists_failed_uploads(autoclip_home, initialised_db: int) -> None:
    source = _seed_source()
    job = _seed_job(source, status="done", error=None)
    clip = _seed_clip(job, status="exported", title="Good clip")
    export = Export(id=new_id(), clip_id=clip.id, path="C:/out.mp4")
    store.create_export(export)
    upload = store.create_upload(
        YouTubeUpload(
            id=new_id(),
            export_id=export.id,
            clip_id=clip.id,
            status="failed",
            error="quotaExceeded",
            title="The upload title",
        )
    )

    from autoclip import recovery

    report = recovery.build_report()

    assert report["counts"]["upload"] == 1
    item = next(i for i in report["items"] if i["kind"] == "upload")
    assert item["title"] == "The upload title"
    assert item["detail"] == "quotaExceeded"
    assert item["code"] == errors.QUOTA
    assert item["action"] == f"/api/youtube/uploads/{upload.id}/retry"


def test_recovery_lists_invalid_clips(autoclip_home, initialised_db: int) -> None:
    source = _seed_source()
    job = _seed_job(source, status="done", error=None)
    clip = _seed_clip(job, title="Broken render")
    store.update_clip(
        clip.id,
        validation={
            "ok": False,
            "checks": [
                {"name": "resolution", "ok": False, "detail": "wrong"},
                {"name": "duration", "ok": True, "detail": "fine"},
            ],
        },
    )

    from autoclip import recovery

    report = recovery.build_report()

    assert report["counts"]["clip"] == 1
    item = next(i for i in report["items"] if i["kind"] == "clip")
    assert item["title"] == "Broken render"
    assert "resolution" in item["detail"]
    assert item["action"] == f"/api/clips/{clip.id}/export"


def test_recovery_ignores_healthy_work(autoclip_home, initialised_db: int) -> None:
    source = _seed_source()
    job = _seed_job(source, status="done", error=None)
    _seed_clip(job, status="exported")

    from autoclip import recovery

    report = recovery.build_report()

    assert report["counts"]["total"] == 0
    assert report["items"] == []


def test_a_superseded_failure_leaves_the_recovery_list(autoclip_home, initialised_db: int) -> None:
    """Re-rendering the clip fixes the failure; it must not linger."""
    source = _seed_source()
    job = _seed_job(source, status="done", error=None)
    clip = _seed_clip(job, status="exported", title="Clip with a missing file")
    export = Export(id=new_id(), clip_id=clip.id, path="C:/out.mp4")
    store.create_export(export)
    upload = store.create_upload(
        YouTubeUpload(
            id=new_id(),
            export_id=export.id,
            clip_id=clip.id,
            status="failed",
            error="The exported file has been moved or deleted. Export the clip again.",
        )
    )
    assert upload.id

    from autoclip import recovery

    assert recovery.build_report()["counts"]["upload"] == 1

    # The clip is rendered again, producing a strictly newer export.
    newer = Export(id=new_id(), clip_id=clip.id, path="C:/out2.mp4")
    store.create_export(newer)
    with store.connection() as conn:
        conn.execute(
            "UPDATE exports SET created_at = '2099-01-01T00:00:00+00:00' WHERE id = ?",
            (newer.id,),
        )

    report = recovery.build_report()
    assert report["counts"]["upload"] == 0
    assert report["items"] == []


def test_a_missing_file_offers_a_re_render_not_a_retry(autoclip_home, initialised_db: int) -> None:
    """Retrying an upload whose file is gone would fail in the same way."""
    source = _seed_source()
    job = _seed_job(source, status="done", error=None)
    clip = _seed_clip(job, status="exported", title="Clip with a missing file")
    export = Export(id=new_id(), clip_id=clip.id, path="C:/out.mp4")
    store.create_export(export)
    store.create_upload(
        YouTubeUpload(
            id=new_id(),
            export_id=export.id,
            clip_id=clip.id,
            status="failed",
            error="The exported file has been moved or deleted. Export the clip again.",
        )
    )

    from autoclip import recovery

    report = recovery.build_report()
    item = next(i for i in report["items"] if i["kind"] == "upload")

    assert item["code"] == errors.NOT_FOUND
    assert item["action"] == f"/api/clips/{clip.id}/export"
    assert item["action_label"] == "Render it again"


def test_a_rate_limited_upload_offers_a_retry(autoclip_home, initialised_db: int) -> None:
    """A transient failure is worth trying again as it was."""
    source = _seed_source()
    job = _seed_job(source, status="done", error=None)
    clip = _seed_clip(job, status="exported")
    export = Export(id=new_id(), clip_id=clip.id, path="C:/out.mp4")
    store.create_export(export)
    upload = store.create_upload(
        YouTubeUpload(
            id=new_id(),
            export_id=export.id,
            clip_id=clip.id,
            status="failed",
            error="429 Too Many Requests",
        )
    )

    from autoclip import recovery

    report = recovery.build_report()
    item = next(i for i in report["items"] if i["kind"] == "upload")

    assert item["code"] == errors.RATE_LIMIT
    assert item["retryable"] is True
    assert item["action"] == f"/api/youtube/uploads/{upload.id}/retry"
    assert item["action_label"] == "Try publishing again"


def test_an_auth_failure_is_not_offered_as_a_retry(autoclip_home, initialised_db: int) -> None:
    """A rejected credential needs the user to fix something first."""
    source = _seed_source()
    job = _seed_job(source, status="done", error=None)
    clip = _seed_clip(job, status="exported")
    export = Export(id=new_id(), clip_id=clip.id, path="C:/out.mp4")
    store.create_export(export)
    store.create_upload(
        YouTubeUpload(
            id=new_id(),
            export_id=export.id,
            clip_id=clip.id,
            status="failed",
            error="401 Unauthorized: invalid api key",
        )
    )

    from autoclip import recovery

    report = recovery.build_report()
    item = next(i for i in report["items"] if i["kind"] == "upload")

    assert item["code"] == errors.AUTH
    assert item["retryable"] is False


def test_recovery_api(autoclip_home, initialised_db: int) -> None:
    from autoclip.app import create_app

    source = _seed_source("Failed Video")
    _seed_job(source, error="the provider refused")

    with TestClient(create_app()) as client:
        report = client.get("/api/recovery").json()
        assert report["counts"]["total"] == 1
        assert report["items"][0]["title"] == "Failed Video"
