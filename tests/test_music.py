"""Phase 8 — background music library and mixing graph tests.

M1 adds two things to this file: the **licence gate** in front of the export,
and the **timeline-driven ducking** that replaces the blind sidechain
compressor when a speech timeline is available.
"""

from __future__ import annotations

import io
import re

import pytest
from autoclip.config import ExportSettings
from autoclip.music import store as music_store
from autoclip.music.licensing import LicenseRecord, LicenseState
from autoclip.pipeline import export, music
from autoclip.pipeline.reframe.croppath import CropPath, CropSegment
from autoclip.pipeline.speech_timeline import SpeechInterval
from fastapi.testclient import TestClient


def _confirm_licence(path, *, state: str = LicenseState.USER_CONFIRMED) -> str:
    """Record a licence for a track the way the Settings screen would.

    The assertions in the export tests are not weakened: a track with an
    unknown licence is genuinely blocked, so the tests say so and then
    clear the block explicitly.
    """
    track = music_store.upsert_track(path)
    music_store.set_license(
        LicenseRecord(
            track_id=track.id,
            state=state,
            source="test",
            evidence="A test fixture.",
        )
    )
    return track.id


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
    assert "amix=inputs=2" in mixed.filter_complex
    assert "sidechaincompress" not in mixed.filter_complex
    assert mixed.map == "[aout]"
    assert mixed.input_args[-1] == "C:/x/bed.mp3"


def test_mixed_graph_with_ducking() -> None:
    settings = ExportSettings(music_track="bed.mp3", music_ducking=True, ducking_amount_db=-12)
    mixed = export.build_mixed_audio_filtergraph(settings, "C:/x/bed.mp3", 12.5)
    assert "sidechaincompress" in mixed.filter_complex
    # -12 dB ≈ 0.2512 linear threshold.
    assert "threshold=0.2512" in mixed.filter_complex
    assert "amix=inputs=2" in mixed.filter_complex
    # The bed is trimmed to the clip duration and speech still reads input 0.
    assert "[0:a]loudnorm" in mixed.filter_complex
    assert "[1:a]atrim=0:12.5000" in mixed.filter_complex
    # normalize=0 keeps speech at full level when the bed is added.
    assert "normalize=0" in mixed.filter_complex


def test_volume_clamped() -> None:
    settings = ExportSettings(music_track="bed.mp3", music_volume=5.0)
    mixed = export.build_mixed_audio_filtergraph(settings, "C:/x/bed.mp3", 5.0)
    assert "volume=1.000" in mixed.filter_complex

    settings = ExportSettings(music_track="bed.mp3", music_volume=-1.0)
    mixed = export.build_mixed_audio_filtergraph(settings, "C:/x/bed.mp3", 5.0)
    assert "volume=0.000" in mixed.filter_complex


def test_ducking_amount_clamped() -> None:
    settings = ExportSettings(music_track="bed.mp3", ducking_amount_db=-100)
    mixed = export.build_mixed_audio_filtergraph(settings, "C:/x/bed.mp3", 5.0)
    # Clamped to -60 dB = 0.001 linear.
    assert "threshold=0.0010" in mixed.filter_complex


# --------------------------------------------------------------------------
# Export arg assembly (no ffmpeg run — inspect the built argv)
# --------------------------------------------------------------------------


def test_export_args_include_music_input(
    monkeypatch: pytest.MonkeyPatch, tmp_path, initialised_db: int
) -> None:
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
    _confirm_licence(track)
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


# --------------------------------------------------------------------------
# The licence gate (M1)
# --------------------------------------------------------------------------


def _export_request(tmp_path, track, **kwargs):
    source = tmp_path / "src.mp4"
    source.write_bytes(b"fake")
    return export.ExportRequest(
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
        **kwargs,
    )


def _capture_ffmpeg(monkeypatch: pytest.MonkeyPatch) -> dict:
    """Replace the ffmpeg call with a recorder that fakes the output file."""
    captured: dict = {}

    def fake_run(args, **kwargs):
        captured["args"] = args
        from pathlib import Path as _Path

        _Path(args[-1]).write_bytes(b"rendered")

    monkeypatch.setattr(export.ffmpeg, "run", fake_run)
    return captured


def test_an_unknown_licence_blocks_the_export(
    monkeypatch: pytest.MonkeyPatch, tmp_path, initialised_db: int
) -> None:
    """A track whose rights are unknown never reaches the renderer.

    This is the honest default: AutoClip cannot tell whether a file in a
    folder may be published, so it says so instead of guessing.
    """
    from autoclip.music.licensing import LicenseBlocked

    monkeypatch.setattr(export.ffmpeg, "run", lambda *a, **k: pytest.fail("ffmpeg ran"))

    track = tmp_path / "bed.mp3"
    track.write_bytes(b"fake")
    music_store.upsert_track(track)

    settings = ExportSettings(music_track=str(track))
    with pytest.raises(LicenseBlocked) as caught:
        export.export_clip(_export_request(tmp_path, track), work_dir=tmp_path, settings=settings)

    assert caught.value.state == LicenseState.UNKNOWN
    assert "licence" in str(caught.value).lower()


def test_a_user_confirmed_licence_allows_the_export(
    monkeypatch: pytest.MonkeyPatch, tmp_path, initialised_db: int
) -> None:
    """A user's own confirmation is enough to export.

    It is an attestation, not a verification, and the warning it produces
    says so — but the user is the one who knows.
    """
    captured = _capture_ffmpeg(monkeypatch)

    track = tmp_path / "bed.mp3"
    track.write_bytes(b"fake")
    _confirm_licence(track)

    settings = ExportSettings(music_track=str(track))
    export.export_clip(_export_request(tmp_path, track), work_dir=tmp_path, settings=settings)

    # The export went through, with the bed in the graph.
    joined = " ".join(str(a) for a in captured["args"])
    assert "bed.mp3" in joined
    assert "amix" in joined


def test_an_incompatible_licence_blocks_the_export(
    monkeypatch: pytest.MonkeyPatch, tmp_path, initialised_db: int
) -> None:
    from autoclip.music.licensing import LicenseBlocked

    monkeypatch.setattr(export.ffmpeg, "run", lambda *a, **k: pytest.fail("ffmpeg ran"))

    track = tmp_path / "bed.mp3"
    track.write_bytes(b"fake")
    _confirm_licence(track, state=LicenseState.INCOMPATIBLE)

    settings = ExportSettings(music_track=str(track))
    with pytest.raises(LicenseBlocked):
        export.export_clip(_export_request(tmp_path, track), work_dir=tmp_path, settings=settings)


def test_an_expired_licence_blocks_the_export(
    monkeypatch: pytest.MonkeyPatch, tmp_path, initialised_db: int
) -> None:
    from autoclip.music.licensing import LicenseBlocked

    monkeypatch.setattr(export.ffmpeg, "run", lambda *a, **k: pytest.fail("ffmpeg ran"))

    track = tmp_path / "bed.mp3"
    track.write_bytes(b"fake")
    _confirm_licence(track, state=LicenseState.EXPIRED)

    settings = ExportSettings(music_track=str(track))
    with pytest.raises(LicenseBlocked):
        export.export_clip(_export_request(tmp_path, track), work_dir=tmp_path, settings=settings)


def test_the_licence_gate_indexes_an_unindexed_track(
    monkeypatch: pytest.MonkeyPatch, tmp_path, initialised_db: int
) -> None:
    """A track the user pointed at directly still gets a place to record rights.

    Without this, a track chosen by absolute path would be blocked with no
    way to clear the block except hunting for its id.
    """
    from autoclip.music.licensing import LicenseBlocked

    monkeypatch.setattr(export.ffmpeg, "run", lambda *a, **k: pytest.fail("ffmpeg ran"))

    track = tmp_path / "bed.mp3"
    track.write_bytes(b"fake")

    settings = ExportSettings(music_track=str(track))
    with pytest.raises(LicenseBlocked):
        export.export_clip(_export_request(tmp_path, track), work_dir=tmp_path, settings=settings)

    indexed = music_store.get_track(music_store.track_id_for(track))
    assert indexed is not None
    assert indexed.path == str(track.resolve())


# --------------------------------------------------------------------------
# The timeline-driven ducking (M1)
# --------------------------------------------------------------------------


def _gain_at(expression: str, t: float) -> float:
    """Evaluate the FFmpeg expression the export builds.

    The generator emits a tiny, fixed grammar — ``if(lt(t,a),b,c)`` over
    arithmetic — so the shape of the ducking can be evaluated directly
    instead of being matched as a string. That way the *shape* is tested,
    not its wording.
    """
    python = expression.replace("if(", "_if(").replace("lt(", "_lt(")
    return float(
        eval(
            python,
            {"__builtins__": {}},
            {
                "t": t,
                "_if": lambda cond, yes, no: yes if cond else no,
                "_lt": lambda a, b: 1.0 if a < b else 0.0,
            },
        )
    )


def test_the_ducking_filter_starts_and_ends_at_full_level() -> None:
    """The bed must be back at full level when the speech interval ends.

    Otherwise the filter's own enable window would cut the bed off
    mid-recovery, and the clip would end on a step.
    """
    interval = SpeechInterval(start_ms=1000, end_ms=2000)
    filters = export.build_ducking_filters([interval], duck_db=-12.0, attack_ms=120, release_ms=350)
    assert len(filters) == 1

    expression = filters[0].split("volume='", 1)[1].split("'", 1)[0]
    assert _gain_at(expression, 1.0) == pytest.approx(1.0)
    assert _gain_at(expression, 2.0) == pytest.approx(1.0)


def test_the_ducking_filter_drops_to_the_requested_depth() -> None:
    interval = SpeechInterval(start_ms=1000, end_ms=2000)
    filters = export.build_ducking_filters([interval], duck_db=-12.0, attack_ms=120, release_ms=350)
    expression = filters[0].split("volume='", 1)[1].split("'", 1)[0]

    floor = 10 ** (-12.0 / 20.0)
    assert _gain_at(expression, 1.5) == pytest.approx(floor, abs=0.01)


def test_the_ducking_filter_only_acts_inside_its_interval() -> None:
    """Each filter is enabled for its own interval only."""
    interval = SpeechInterval(start_ms=1000, end_ms=2000)
    filters = export.build_ducking_filters([interval], duck_db=-12.0, attack_ms=120, release_ms=350)
    assert "between(t,1.0000,2.0000)" in filters[0]
    assert "eval=frame" in filters[0]


def test_a_short_interval_gets_a_triangle() -> None:
    """An interval shorter than the attack and release still starts and ends at 1.0."""
    interval = SpeechInterval(start_ms=1000, end_ms=1100)
    filters = export.build_ducking_filters([interval], duck_db=-12.0, attack_ms=120, release_ms=350)
    expression = filters[0].split("volume='", 1)[1].split("'", 1)[0]

    assert _gain_at(expression, 1.0) == pytest.approx(1.0)
    assert _gain_at(expression, 1.1) == pytest.approx(1.0)
    assert _gain_at(expression, 1.05) < 0.9


def test_the_timeline_drives_the_ducking_when_it_is_available() -> None:
    """With a timeline, the graph uses the envelope rather than the compressor."""
    settings = ExportSettings(music_track="bed.mp3", music_ducking=True)
    intervals = [SpeechInterval(start_ms=1000, end_ms=2000)]

    mixed = export.build_mixed_audio_filtergraph(settings, "C:/x/bed.mp3", 5.0, intervals)
    graph = mixed.filter_complex

    assert "sidechaincompress" not in graph
    assert "volume=volume=" in graph
    assert "between(t,1.0000,2.0000)" in graph
    # The speech chain is untouched: only the bed is shaped.
    assert "[0:a]loudnorm" in graph
    assert "amix=inputs=2" in graph


def test_without_a_timeline_the_compressor_is_still_the_fallback() -> None:
    """No timeline at all means the ducking keys on the audio instead."""
    settings = ExportSettings(music_track="bed.mp3", music_ducking=True)
    mixed = export.build_mixed_audio_filtergraph(settings, "C:/x/bed.mp3", 5.0, None)
    assert "sidechaincompress" in mixed.filter_complex


def test_a_timeline_with_no_speech_does_not_duck_at_all() -> None:
    """A timeline that found no speech means the bed plays at full level.

    This is not the same answer as "there is no timeline". The compressor
    fallback exists for a timeline that failed; a timeline that succeeded
    and found nothing knows that this clip has no talking, and the bed
    should not be pulled down by whatever else the source contains.
    """
    settings = ExportSettings(music_track="bed.mp3", music_ducking=True)
    mixed = export.build_mixed_audio_filtergraph(settings, "C:/x/bed.mp3", 5.0, [])

    assert "sidechaincompress" not in mixed.filter_complex
    assert "volume=volume=" not in mixed.filter_complex
    # The bed is still mixed in, at full level.
    assert "amix=inputs=2" in mixed.filter_complex
    assert "[1:a]atrim" in mixed.filter_complex


#: The leading bracketed labels of one filter chain — its inputs.
_LEADING_LABELS = re.compile(r"^((?:\[[^\]]*\])+)")

#: A chain's filters, closed by its output label(s). A filter may emit more
#: than one output — `asplit` does — so there may be more than one.
_CHAIN_TAIL = re.compile(r"[^[]*(\[[^\]]*\])*")


def _graph_problems(graph: str) -> list[str]:
    """The ways a filtergraph can be malformed regardless of the ffmpeg build.

    Two defects are checked, both of which render on a recent ffmpeg and
    fail on an older one — so neither can be left to the ffmpeg that
    happens to be installed:

    * a filter output consumed **twice**. A filter output may be consumed
      only once; naming the same label twice is refused by ffmpeg 7 with
      "Invalid stream specifier" and accepted by ffmpeg 9.
    * a filter **after** an output label. A label closes its chain, so
      the filters that follow it have no input and the chain's own output
      is left unconnected — "Filter 'volume:default' has output 1 (bed)
      unconnected".
    """
    problems: list[str] = []
    used: list[str] = []

    for chain in graph.split(";"):
        chain = chain.strip()
        if not chain:
            continue

        leading = _LEADING_LABELS.match(chain)
        if not leading:
            problems.append(f"a chain does not start with an input label: {chain!r}")
            continue

        used.extend(label for label in re.findall(r"\[([^\]]*)\]", leading.group(1)) if label)

        tail = chain[leading.end() :]
        if not _CHAIN_TAIL.fullmatch(tail):
            problems.append(f"a filter follows an output label: {chain!r}")

    repeated = sorted({label for label in used if used.count(label) > 1})
    if repeated:
        problems.append(f"these filter outputs are consumed more than once: {repeated}")

    return problems


@pytest.mark.parametrize(
    ("ducking", "intervals"),
    [
        (False, []),
        (True, []),
        (True, [SpeechInterval(start_ms=1000, end_ms=2000)]),
    ],
)
def test_every_graph_is_well_formed_for_any_ffmpeg(ducking: bool, intervals: list) -> None:
    """Every graph AutoClip builds must be well-formed for any ffmpeg."""
    settings = ExportSettings(music_track="bed.mp3", music_ducking=ducking)
    mixed = export.build_mixed_audio_filtergraph(settings, "C:/x/bed.mp3", 5.0, intervals)

    problems = _graph_problems(mixed.filter_complex)

    assert not problems, "the filter graph is malformed: " + "; ".join(problems)


def test_the_sidechain_fallback_splits_the_speech_it_keys_on() -> None:
    """The compressor needs its own copy of the speech."""
    settings = ExportSettings(music_track="bed.mp3", music_ducking=True)
    # None is "there is no timeline to follow", which is what puts the
    # compressor in the graph at all.
    mixed = export.build_mixed_audio_filtergraph(settings, "C:/x/bed.mp3", 5.0, None)

    assert "asplit=2" in mixed.filter_complex
    # The key and the mix input are different labels.
    assert "[sp_key]" in mixed.filter_complex
    assert "[sp_mix]" in mixed.filter_complex


def test_ducking_can_be_switched_off_entirely() -> None:
    settings = ExportSettings(music_track="bed.mp3", music_ducking=False)
    intervals = [SpeechInterval(start_ms=1000, end_ms=2000)]
    mixed = export.build_mixed_audio_filtergraph(settings, "C:/x/bed.mp3", 5.0, intervals)
    graph = mixed.filter_complex
    assert "volume=volume=" not in graph
    assert "sidechaincompress" not in graph
    assert "amix=inputs=2" in graph
