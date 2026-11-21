"""The eight-case ducking matrix, asserted against real renders.

The matrix is the specification's own list of the cases the music bed has to
survive: continuous speech, a short pause, a long pause, more than one
speaker, a sound effect, a music-heavy source, a low-volume source, and no
speech at all.

Each case is a **render**, not a string check. The filter-level tests can
only see that certain characters are in the graph; they cannot see that the
graph ducks where it should and stays out of the way where it should. So
each case renders the same clip twice — once with the ducking on and once
with it off — and measures the bed's own frequency band in a window of each.

The measurement is a **difference**, not a level. The bed sits at 440 Hz and
the source's voice at 1000 Hz, so a bandpass at 440 Hz reads the bed on its
own. Subtracting the flat render from the ducked one leaves the ducking, as
a number: the ratio of the two is the bed's level relative to what it would
have been with the ducking switched off.

The thresholds are deliberately loose about the depth and tight about the
shape. A ducked window has to be at least 6 dB down — the configured duck is
12 dB, and the measured depth lands a little shallower because the bandpass
picks up some of the speech's skirt. An un-ducked window has to be within
0.26 dB of full level. What matters is *which* windows are ducked and which
are not, not the exact number of decibels.
"""

from __future__ import annotations

import subprocess
from pathlib import Path

import numpy as np
import pytest
from autoclip.config import ExportSettings
from autoclip.pipeline import captions, export, ffmpeg
from autoclip.pipeline.reframe.croppath import centre_crop
from autoclip.pipeline.speech_timeline import SpeechInterval, merge_intervals

pytestmark = pytest.mark.slow

SOURCE_W, SOURCE_H = 1280, 720
CLIP_START_S, CLIP_END_S = 0.0, 8.0

#: The bed's own frequency. The source's voice is at 1000 Hz, so a bandpass
#: here reads the bed and almost none of the speech.
BED_HZ = 440
VOICE_HZ = 1000
SFX_HZ = 2000
SOURCE_MUSIC_HZ = 220

#: A ducked window must be at least this much quieter than the flat render.
#: 0.5 is -6 dB, half the configured duck.
DUCKED_MAX = 0.5

#: An un-ducked window must be within this much of the flat render. 0.95 is
#: -0.26 dB.
FLAT_MIN = 0.95


def _run(args: list[str]) -> None:
    subprocess.run(args, check=True, capture_output=True)


def _band_rms(path: Path, start_s: float, end_s: float, band_hz: float) -> float:
    """The RMS of the audio between two times, inside one frequency band."""
    raw = subprocess.run(
        [
            ffmpeg.ffmpeg_path(),
            "-hide_banner",
            "-loglevel",
            "error",
            "-ss",
            f"{start_s:.3f}",
            "-t",
            f"{end_s - start_s:.3f}",
            "-i",
            str(path),
            "-vn",
            "-af",
            f"bandpass=f={band_hz}:width_type=h:w=60",
            "-f",
            "s16le",
            "-ac",
            "1",
            "-ar",
            "48000",
            "-",
        ],
        check=True,
        capture_output=True,
    ).stdout
    samples = np.frombuffer(raw, dtype="<i2").astype(np.float32) / 32768.0
    if samples.size == 0:
        return 0.0
    return float(np.sqrt(np.mean(np.square(samples))))


def _interval(start_ms: int, end_ms: int, speaker: str | None = None) -> SpeechInterval:
    return SpeechInterval(start_ms=start_ms, end_ms=end_ms, speaker=speaker)


class _Media:
    """The source clips and the bed, generated once for the module."""

    def __init__(self, root: Path) -> None:
        self.root = root
        self.bed = root / "bed.wav"
        _run(
            [
                ffmpeg.ffmpeg_path(),
                "-hide_banner",
                "-loglevel",
                "error",
                "-y",
                "-f",
                "lavfi",
                "-i",
                f"sine=frequency={BED_HZ}:duration=2:sample_rate=48000",
                str(self.bed),
            ]
        )

        #: A voice and nothing else.
        self.voice = self._source("voice.mp4", None)

        #: A voice with a loud sound effect at 6 s.
        self.with_sfx = self._source(
            "with-sfx.mp4",
            f"sine=frequency={SFX_HZ}:duration=0.4:sample_rate=48000,adelay=6000",
            gain="1.0",
        )

        #: A voice with its own loud music — a game with a soundtrack.
        self.with_music = self._source(
            "with-music.mp4",
            f"sine=frequency={SOURCE_MUSIC_HZ}:duration=10:sample_rate=48000",
            gain="0.9",
        )

        #: The same voice, far too quiet to hear.
        self.quiet = self._source("quiet.mp4", None, voice_gain="0.02")

    def _source(
        self, name: str, extra: str | None, *, gain: str = "1.0", voice_gain: str = "1.0"
    ) -> Path:
        """Ten seconds of video, with a voice tone and whatever else."""
        path = self.root / name
        args = [
            ffmpeg.ffmpeg_path(),
            "-hide_banner",
            "-loglevel",
            "error",
            "-y",
            "-f",
            "lavfi",
            "-i",
            f"testsrc2=size={SOURCE_W}x{SOURCE_H}:rate=30:duration=10",
            "-f",
            "lavfi",
            "-i",
            f"sine=frequency={VOICE_HZ}:duration=10:sample_rate=48000",
        ]
        if extra:
            args += ["-f", "lavfi", "-i", extra]
        args += ["-c:v", "libx264", "-pix_fmt", "yuv420p", "-c:a", "aac", "-shortest"]
        if extra:
            graph = (
                f"[1:a]volume={voice_gain}[a];"
                f"[2:a]volume={gain}[b];"
                f"[a][b]amix=inputs=2:normalize=0[aout]"
            )
            args += ["-filter_complex", graph, "-map", "0:v", "-map", "[aout]"]
        elif voice_gain != "1.0":
            args += ["-filter:a", f"volume={voice_gain}"]
            args += ["-map", "0:v", "-map", "1:a"]
        else:
            args += ["-map", "0:v", "-map", "1:a"]
        args += [str(path)]
        _run(args)
        return path


@pytest.fixture(scope="module")
def media(tmp_path_factory) -> _Media:
    return _Media(tmp_path_factory.mktemp("media"))


@pytest.fixture(scope="module")
def renderer(media, tmp_path_factory):
    """Renders clips, and remembers the flat reference for each source.

    The database is set up per render rather than once per module: the
    shared ``autoclip_home`` fixture points at a throwaway directory for
    every test, so the schema has to be brought up to date each time.
    """
    work = tmp_path_factory.mktemp("work")
    flats: dict[Path, Path] = {}

    def render(
        source: Path,
        name: str,
        *,
        intervals: list[SpeechInterval] | None,
        ducking: bool = True,
    ) -> Path:
        from autoclip import db
        from autoclip.music import store as music_store
        from autoclip.music.licensing import LicenseRecord, LicenseState

        db.init()
        track = music_store.upsert_track(media.bed)
        music_store.set_license(
            LicenseRecord(
                track_id=track.id,
                state=LicenseState.USER_CONFIRMED,
                source="test",
                evidence="A test fixture.",
            )
        )

        destination = work / name
        request = export.ExportRequest(
            source=source,
            destination=destination,
            start_s=CLIP_START_S,
            end_s=CLIP_END_S,
            crop_path=centre_crop(SOURCE_W, SOURCE_H, CLIP_END_S - CLIP_START_S),
            words=[],
            style=captions.get_style("bold_pop"),
            burn_captions=False,
            speech_intervals=intervals,
        )
        export.export_clip(
            request,
            work_dir=work / "scratch",
            settings=ExportSettings(
                music_track=str(media.bed),
                music_volume=0.5,
                music_ducking=ducking,
                ducking_amount_db=-12.0,
            ),
        )
        return destination

    def flat(source: Path, name: str) -> Path:
        """The reference render: the same clip with the ducking switched off."""
        if source not in flats:
            flats[source] = render(source, f"flat-{name}.mp4", intervals=None, ducking=False)
        return flats[source]

    return render, flat


def _assert_window(
    flat: Path, ducked: Path, start_s: float, end_s: float, *, ducked_expected: bool
) -> None:
    """The bed must be down in this window, or it must not be."""
    before = _band_rms(flat, start_s, end_s, BED_HZ)
    after = _band_rms(ducked, start_s, end_s, BED_HZ)
    assert before > 0.0, "the flat render has no bed in its own band"
    ratio = after / before

    if ducked_expected:
        assert ratio <= DUCKED_MAX, (
            f"the bed was not ducked between {start_s}s and {end_s}s: "
            f"{after:.5f} against a flat {before:.5f} (ratio {ratio:.3f})"
        )
    else:
        assert ratio >= FLAT_MIN, (
            f"the bed was ducked between {start_s}s and {end_s}s when it should not "
            f"have been: {after:.5f} against a flat {before:.5f} (ratio {ratio:.3f})"
        )


def test_continuous_speech_ducks_the_whole_stretch(media, renderer) -> None:
    """One long stretch of speech: the bed is down for all of it."""
    render, flat = renderer
    source = media.voice
    ducked = render(
        source,
        "continuous.mp4",
        intervals=[_interval(1000, 7000)],
    )
    reference = flat(source, "voice")

    _assert_window(reference, ducked, 2.0, 6.0, ducked_expected=True)
    # And it is back once the speech has finished.
    _assert_window(reference, ducked, 7.3, 8.0, ducked_expected=False)


def test_a_short_pause_does_not_let_the_bed_recover(media, renderer) -> None:
    """A pause shorter than the merge gap is one stretch of speech.

    The timeline merges intervals whose gap is under 350 ms, so the bed
    ducks once across the whole thing. It must not recover in the gap —
    that is what stops the music swelling between two words the transcript
    considers one sentence.
    """
    render, flat = renderer
    source = media.voice
    # Two intervals 300 ms apart: inside the merge gap, so one interval.
    merged = merge_intervals([_interval(1000, 2000), _interval(2300, 3000)])
    assert len(merged) == 1, "the two intervals should have merged"

    ducked = render(source, "short-pause.mp4", intervals=merged)
    reference = flat(source, "voice")

    # The gap itself: the bed has to stay down through it.
    _assert_window(reference, ducked, 2.05, 2.25, ducked_expected=True)
    _assert_window(reference, ducked, 1.4, 1.9, ducked_expected=True)


def test_a_long_pause_lets_the_bed_come_back(media, renderer) -> None:
    """A pause longer than the merge gap is a real gap: the bed returns."""
    render, flat = renderer
    source = media.voice
    ducked = render(
        source,
        "long-pause.mp4",
        intervals=[_interval(1000, 2000), _interval(5000, 6000)],
    )
    reference = flat(source, "voice")

    _assert_window(reference, ducked, 2.6, 4.4, ducked_expected=False)
    _assert_window(reference, ducked, 1.3, 1.9, ducked_expected=True)
    _assert_window(reference, ducked, 5.3, 5.9, ducked_expected=True)


def test_a_change_of_speaker_does_not_break_the_ducking(media, renderer) -> None:
    """Two speakers, two stretches: both are ducked, and the gap between is not.

    A speaker change is not a pause. The ducking is about someone talking,
    not about who it is, so the bed follows the speech and not the speaker.
    """
    render, flat = renderer
    source = media.voice
    ducked = render(
        source,
        "multi-speaker.mp4",
        intervals=[
            _interval(1000, 2000, speaker="A"),
            _interval(3000, 4000, speaker="B"),
        ],
    )
    reference = flat(source, "voice")

    _assert_window(reference, ducked, 1.3, 1.9, ducked_expected=True)
    _assert_window(reference, ducked, 2.4, 2.9, ducked_expected=False)
    _assert_window(reference, ducked, 3.3, 3.9, ducked_expected=True)


def test_a_sound_effect_does_not_duck_the_bed(media, renderer) -> None:
    """A loud sound effect is not speech, and must not pull the bed down.

    The bed is ducked against the *timeline*, not against loudness. A
    transient in the source — a door slam, an explosion — is not somebody
    talking, and the music should not move for it.
    """
    render, flat = renderer
    source = media.with_sfx
    ducked = render(source, "sfx.mp4", intervals=[_interval(1000, 2000)])
    reference = flat(source, "with-sfx")

    _assert_window(reference, ducked, 1.3, 1.9, ducked_expected=True)
    # The sound effect is at 6 s, well outside the speech.
    _assert_window(reference, ducked, 6.05, 6.35, ducked_expected=False)


def test_only_the_added_music_is_ducked(media, renderer) -> None:
    """The source's own music is untouched; only the added bed is shaped.

    This is the guarantee that the ducking is on the music AutoClip adds
    and nothing else. The source carries its own 220 Hz music; that music
    must come out exactly as it went in, whether or not the bed moved.
    """
    render, flat = renderer
    source = media.with_music
    ducked = render(source, "music-heavy.mp4", intervals=[_interval(2000, 4000)])
    reference = flat(source, "with-music")

    # The added bed is down under the speech...
    _assert_window(reference, ducked, 2.4, 3.6, ducked_expected=True)
    # ...and back to full level outside it.
    _assert_window(reference, ducked, 5.0, 6.0, ducked_expected=False)

    # The source's own music is not touched at all, in either window.
    for start_s, end_s in ((2.4, 3.6), (5.0, 6.0)):
        before = _band_rms(reference, start_s, end_s, SOURCE_MUSIC_HZ)
        after = _band_rms(ducked, start_s, end_s, SOURCE_MUSIC_HZ)
        assert after == pytest.approx(before, rel=0.25), (
            f"the source's own music changed between {start_s}s and {end_s}s: "
            f"{after:.5f} against {before:.5f}"
        )


def test_a_quiet_voice_is_still_ducked_against(media, renderer) -> None:
    """A quiet speaker is still a speaker.

    The ducking follows the timeline, so it does not matter how loud the
    voice is. A level-keyed duck would leave the music on top of a quiet
    speaker; the timeline does not.
    """
    render, flat = renderer
    source = media.quiet
    ducked = render(source, "low-volume.mp4", intervals=[_interval(2000, 4000)])
    reference = flat(source, "quiet")

    _assert_window(reference, ducked, 2.4, 3.6, ducked_expected=True)
    _assert_window(reference, ducked, 5.0, 6.0, ducked_expected=False)


def test_no_speech_means_no_ducking(media, renderer) -> None:
    """A clip with no talking gets its music at full level.

    The timeline was consulted and it found no speech in this clip, so
    there is nothing to duck under. The bed plays through — whatever else
    the source contains is not somebody talking.

    This is the case that the "no timeline" fallback used to swallow: an
    empty list and an absent timeline meant the same thing, and a clip
    with no speech fell back to keying the ducking on the audio itself.
    """
    render, flat = renderer
    source = media.with_sfx
    ducked = render(source, "no-speech.mp4", intervals=[])
    reference = flat(source, "with-sfx")

    # At the sound effect, where the source is loudest.
    _assert_window(reference, ducked, 6.05, 6.35, ducked_expected=False)
    # And in the quiet stretch.
    _assert_window(reference, ducked, 3.0, 4.0, ducked_expected=False)
