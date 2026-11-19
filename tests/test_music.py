"""Phase 8 — background music library and mixing graph tests."""

from __future__ import annotations

import io

import pytest
from autoclip.config import ExportSettings
from autoclip.pipeline import export, music
from autoclip.pipeline.reframe.croppath import CropPath, CropSegment
from fastapi.testclient import TestClient

# --------------------------------------------------------------------------
# Library
# --------------------------------------------------------------------------


def test_music_dir_empty(autoclip_home) -> None:
    assert music.list_tracks() == []
    assert music.resolve_track("anything.mp3") is None


def test_list_tracks(autoclip_home) -> None:
    directory = music.music_dir()
    directory.mkdir(parents=True, exist_ok=True)
    (directory / "bed.mp3").write_bytes(b"fake")
    (directory / "notes.txt").write_text("not audio")
    (directory / "loop.WAV").write_bytes(b"fake")

    tracks = music.list_tracks()
    assert [t["name"] for t in tracks] == ["bed.mp3", "loop.WAV"]


def test_resolve_track_library_and_absolute(autoclip_home) -> None:
    directory = music.music_dir()
    directory.mkdir(parents=True, exist_ok=True)
    (directory / "bed.mp3").write_bytes(b"fake")

    resolved = music.resolve_track("bed.mp3")
    assert resolved is not None and resolved.name == "bed.mp3"

    absolute = directory / "bed.mp3"
    assert music.resolve_track(str(absolute)) == absolute

    assert music.resolve_track("missing.mp3") is None
    assert music.resolve_track("") is None


# --------------------------------------------------------------------------
# Filtergraph construction
# --------------------------------------------------------------------------


def test_plain_graph_unchanged_without_music() -> None:
    settings = ExportSettings()
    graph = export.build_audio_filtergraph(settings)
    assert "loudnorm" in graph
    assert "amix" not in graph


def test_mixed_graph_without_ducking() -> None:
    settings = ExportSettings(music_track="bed.mp3", music_ducking=False)
    mixed = export.build_mixed_audio_filtergraph(settings, "C:/x/bed.mp3", 5.0)
    assert "amix=inputs=2" in mixed["filter_complex"]
    assert "sidechaincompress" not in mixed["filter_complex"]
    assert mixed["map"] == "[aout]"
    assert mixed["input_args"][-1] == "C:/x/bed.mp3"


def test_mixed_graph_with_ducking() -> None:
    settings = ExportSettings(music_track="bed.mp3", music_ducking=True, ducking_amount_db=-12)
    mixed = export.build_mixed_audio_filtergraph(settings, "C:/x/bed.mp3", 12.5)
    assert "sidechaincompress" in mixed["filter_complex"]
    # -12 dB ≈ 0.2512 linear threshold.
    assert "threshold=0.2512" in mixed["filter_complex"]
    assert "amix=inputs=2" in mixed["filter_complex"]
    # The bed is trimmed to the clip duration and speech still reads input 0.
    assert "[0:a]loudnorm" in mixed["filter_complex"]
    assert "[1:a]atrim=0:12.5000" in mixed["filter_complex"]
    # normalize=0 keeps speech at full level when the bed is added.
    assert "normalize=0" in mixed["filter_complex"]


def test_volume_clamped() -> None:
    settings = ExportSettings(music_track="bed.mp3", music_volume=5.0)
    mixed = export.build_mixed_audio_filtergraph(settings, "C:/x/bed.mp3", 5.0)
    assert "volume=1.000" in mixed["filter_complex"]

    settings = ExportSettings(music_track="bed.mp3", music_volume=-1.0)
    mixed = export.build_mixed_audio_filtergraph(settings, "C:/x/bed.mp3", 5.0)
    assert "volume=0.000" in mixed["filter_complex"]


def test_ducking_amount_clamped() -> None:
    settings = ExportSettings(music_track="bed.mp3", ducking_amount_db=-100)
    mixed = export.build_mixed_audio_filtergraph(settings, "C:/x/bed.mp3", 5.0)
    # Clamped to -60 dB = 0.001 linear.
    assert "threshold=0.0010" in mixed["filter_complex"]


# --------------------------------------------------------------------------
# Export arg assembly (no ffmpeg run — inspect the built argv)
# --------------------------------------------------------------------------


def test_export_args_include_music_input(monkeypatch: pytest.MonkeyPatch, tmp_path) -> None:
    """The ffmpeg argv carries the music input and mixed graph when configured."""
    captured: dict = {}

    def fake_run(args, **kwargs):
        captured["args"] = args
        # Materialise the output so the post-run size check passes.
        from pathlib import Path as _Path

        _Path(args[-1]).write_bytes(b"rendered")

    monkeypatch.setattr(export.ffmpeg, "run", fake_run)

    source = tmp_path / "src.mp4"
    source.write_bytes(b"fake")
    destination = tmp_path / "out.mp4"

    track = tmp_path / "bed.mp3"
    track.write_bytes(b"fake")
    settings = ExportSettings(music_track=str(track), music_volume=0.2)
    request = export.ExportRequest(
        source=source,
        destination=destination,
        start_s=0.0,
        end_s=5.0,
        crop_path=CropPath(
            source_width=1080,
            source_height=1920,
            segments=[CropSegment(start_s=0.0, end_s=5.0, width=608, height=1080)],
        ),
        words=[],
        style="bold_pop",
        burn_captions=False,
    )
    export.export_clip(request, work_dir=tmp_path, settings=settings)

    args = captured["args"]
    # The music file appears as an input.
    assert "bed.mp3" in " ".join(str(a) for a in args)
    # The mixed graph is in filter_complex and no bare -af remains.
    joined = " ".join(str(a) for a in args)
    assert "sidechaincompress" in joined or "amix" in joined
    assert "-af" not in args or "loudnorm" not in args[args.index("-af") + 1]


def test_silent_source_skips_music_bed(monkeypatch: pytest.MonkeyPatch, tmp_path) -> None:
    """A source with no audio falls back to the plain graph instead of failing."""
    captured: dict = {}

    def fake_run(args, **kwargs):
        captured["args"] = args
        from pathlib import Path as _Path

        _Path(args[-1]).write_bytes(b"rendered")

    monkeypatch.setattr(export.ffmpeg, "run", fake_run)
    monkeypatch.setattr(export, "_source_has_audio", lambda path: False)

    source = tmp_path / "src.mp4"
    source.write_bytes(b"fake")
    track = tmp_path / "bed.mp3"
    track.write_bytes(b"fake")

    settings = ExportSettings(music_track=str(track))
    request = export.ExportRequest(
        source=source,
        destination=tmp_path / "out.mp4",
        start_s=0.0,
        end_s=5.0,
        crop_path=CropPath(
            source_width=1080,
            source_height=1920,
            segments=[CropSegment(start_s=0.0, end_s=5.0, width=608, height=1080)],
        ),
        words=[],
        style="bold_pop",
        burn_captions=False,
    )
    export.export_clip(request, work_dir=tmp_path, settings=settings)

    joined = " ".join(str(a) for a in captured["args"])
    assert "bed.mp3" not in joined
    assert "sidechaincompress" not in joined


def test_music_api_upload_list_delete(autoclip_home) -> None:
    from autoclip.app import create_app

    with TestClient(create_app()) as client:
        assert client.get("/api/music/tracks").json() == []

        upload = client.post(
            "/api/music/tracks",
            files={"file": ("bed.mp3", io.BytesIO(b"not really audio"), "audio/mpeg")},
        )
        assert upload.status_code == 201
        assert upload.json()["name"] == "bed.mp3"
        assert music.music_dir().joinpath("bed.mp3").is_file()

        listed = client.get("/api/music/tracks").json()
        assert [t["name"] for t in listed] == ["bed.mp3"]

        rejected = client.post(
            "/api/music/tracks",
            files={"file": ("notes.txt", io.BytesIO(b"text"), "text/plain")},
        )
        assert rejected.status_code == 400

        assert client.delete("/api/music/tracks/bed.mp3").status_code == 204
        assert client.get("/api/music/tracks").json() == []
        assert client.delete("/api/music/tracks/bed.mp3").status_code == 404
