"""The shared speech timeline.

Two things are being tested here, and they are the two that matter:

* the **merge boundary**, which is exact: a gap of 349 ms merges, a gap of
  350 ms does not. The intervals are in integer milliseconds precisely so
  that this is not a matter of floating-point luck;
* the **detector rules** the specification approves — a confident frame with
  a word over it, or nine consecutive near-certain frames.

The detector is deterministic, so a synthetic signal gives a predictable
answer, and the tests can assert on the timeline rather than on "it looks
right".
"""

from __future__ import annotations

import math
import wave
from pathlib import Path

import numpy as np
import pytest
from autoclip.pipeline.speech_timeline import (
    CONTINUOUS_FRAMES,
    FRAME_MS,
    SpeechInterval,
    SpeechTimeline,
    build_timeline,
    envelope_points,
    merge_intervals,
    speech_frames,
)
from autoclip.pipeline.transcript import Transcript, Word


def _interval(start_ms: int, end_ms: int, **kwargs) -> SpeechInterval:
    return SpeechInterval(start_ms=start_ms, end_ms=end_ms, **kwargs)


# --------------------------------------------------------------------------
# The merge boundary
# --------------------------------------------------------------------------


def test_a_349_ms_gap_merges():
    """One millisecond short of the threshold: still one stretch of speech."""
    intervals = [_interval(0, 1000), _interval(1349, 2000)]
    merged = merge_intervals(intervals)
    assert len(merged) == 1
    assert merged[0].start_ms == 0
    assert merged[0].end_ms == 2000


def test_a_350_ms_gap_does_not_merge():
    """Exactly the threshold: two stretches of speech."""
    intervals = [_interval(0, 1000), _interval(1350, 2000)]
    merged = merge_intervals(intervals)
    assert len(merged) == 2
    assert merged[0].end_ms == 1000
    assert merged[1].start_ms == 1350


def test_a_gap_over_350_ms_does_not_merge():
    intervals = [_interval(0, 1000), _interval(1400, 2000)]
    merged = merge_intervals(intervals)
    assert len(merged) == 2


def test_the_boundary_is_measured_in_milliseconds_not_frames():
    """A 349 ms gap is not 12 frames (360 ms), and the merge must still happen.

    If the merge were done on the 30 ms frame grid, this gap would be
    rounded up to 12 frames and the intervals would *not* merge. They do.
    """
    gap_ms = 349
    frames = math.ceil(gap_ms / FRAME_MS)
    assert frames * FRAME_MS == 360  # the frame grid would have lost this one
    merged = merge_intervals([_interval(0, 1000), _interval(1000 + gap_ms, 2000)])
    assert len(merged) == 1


def test_overlapping_intervals_merge():
    merged = merge_intervals([_interval(0, 1000), _interval(500, 1500)])
    assert len(merged) == 1
    assert merged[0].end_ms == 1500


def test_continuous_speech_does_not_fragment():
    """Speech with no pause at all stays one interval."""
    intervals = [_interval(index * 30, index * 30 + 30) for index in range(200)]
    merged = merge_intervals(intervals)
    assert len(merged) == 1
    assert merged[0].start_ms == 0
    assert merged[0].end_ms == 200 * 30


def test_merging_keeps_the_strongest_claim():
    merged = merge_intervals(
        [
            _interval(0, 1000, confidence=0.4, source="vad"),
            _interval(500, 1500, confidence=0.9, source="word"),
        ]
    )
    assert len(merged) == 1
    assert merged[0].confidence == 0.9
    assert merged[0].source == "word"


def test_merging_is_order_independent():
    ordered = merge_intervals([_interval(0, 1000), _interval(1349, 2000)])
    reversed_order = merge_intervals([_interval(1349, 2000), _interval(0, 1000)])
    assert len(ordered) == len(reversed_order) == 1
    assert ordered[0].to_dict() == reversed_order[0].to_dict()


def test_merging_an_empty_list_gives_an_empty_list():
    assert merge_intervals([]) == []


# --------------------------------------------------------------------------
# The detector
# --------------------------------------------------------------------------


def _tone(
    *,
    duration_s: float = 1.0,
    frequency: float = 220.0,
    amplitude: float = 0.5,
    sample_rate: int = 16_000,
) -> np.ndarray:
    count = int(duration_s * sample_rate)
    times = np.arange(count, dtype=np.float32) / sample_rate
    return (amplitude * np.sin(2 * np.pi * frequency * times)).astype(np.float32)


def _write_wav(path: Path, samples: np.ndarray, sample_rate: int = 16_000) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    pcm = np.clip(samples, -1.0, 1.0)
    data = (pcm * 32767.0).astype("<i2").tobytes()
    with wave.open(str(path), "wb") as handle:
        handle.setnchannels(1)
        handle.setsampwidth(2)
        handle.setframerate(sample_rate)
        handle.writeframes(data)
    return path


def test_silence_produces_no_confidence():
    frames = speech_frames(np.zeros(16_000, dtype=np.float32))
    assert frames
    assert max(frames) == 0.0


def test_a_loud_tone_is_confident():
    frames = speech_frames(_tone(duration_s=1.0, amplitude=0.6))
    assert max(frames) >= 0.9


def test_frames_are_thirty_milliseconds_long():
    samples = _tone(duration_s=1.0)
    frames = speech_frames(samples)
    # 16 000 samples a second, 480 samples a frame: 33 whole frames, with
    # the 16 ms remainder dropped.
    assert len(frames) == 33
    assert FRAME_MS == 30


def test_a_word_backed_frame_becomes_an_interval(tmp_path: Path):
    """A confident frame with a transcript word over it is speech."""
    audio = _write_wav(tmp_path / "a.wav", _tone(duration_s=1.0, amplitude=0.8))
    transcript = Transcript(words=[Word(text="hello", start=0.1, end=0.5)])

    timeline = build_timeline(audio, transcript)

    assert timeline.intervals
    first = timeline.intervals[0]
    assert first.source == "word"
    assert first.start_ms < 500
    assert first.confidence >= 0.75


def test_nine_confident_frames_make_an_interval_without_a_word(tmp_path: Path):
    """270 ms of near-certain speech is speech even with no transcript."""
    audio = _write_wav(tmp_path / "a.wav", _tone(duration_s=1.0, amplitude=0.8))

    timeline = build_timeline(audio, Transcript(words=[]))

    assert timeline.intervals
    assert timeline.intervals[0].source == "vad"
    assert timeline.intervals[0].duration_ms >= CONTINUOUS_FRAMES * FRAME_MS


def test_a_word_without_enough_confidence_is_not_speech(tmp_path: Path):
    """A transcript word over near-silence does not create an interval.

    The word rule needs both halves: a confident frame *and* a word over it.
    """
    samples = np.zeros(16_000, dtype=np.float32)
    audio = _write_wav(tmp_path / "a.wav", samples)
    transcript = Transcript(words=[Word(text="hello", start=0.1, end=0.5)])

    timeline = build_timeline(audio, transcript)

    assert timeline.intervals == []


def test_the_timeline_is_deterministic(tmp_path: Path):
    audio = _write_wav(tmp_path / "a.wav", _tone(duration_s=0.5, amplitude=0.7))
    transcript = Transcript(words=[Word(text="hi", start=0.0, end=0.3)])
    first = build_timeline(audio, transcript)
    second = build_timeline(audio, transcript)
    assert first.to_dict() == second.to_dict()


def test_the_timeline_survives_a_round_trip(tmp_path: Path):
    audio = _write_wav(tmp_path / "a.wav", _tone(duration_s=0.5, amplitude=0.7))
    transcript = Transcript(words=[Word(text="hi", start=0.0, end=0.3)])
    timeline = build_timeline(audio, transcript)

    path = timeline.save(tmp_path / "timeline.json")
    loaded = SpeechTimeline.load(path)

    assert loaded.to_dict() == timeline.to_dict()


def test_a_missing_audio_file_gives_an_empty_timeline(tmp_path: Path):
    timeline = build_timeline(tmp_path / "nope.wav", Transcript(words=[]))
    assert timeline.intervals == []


def test_the_timeline_carries_the_speaker(tmp_path: Path):
    audio = _write_wav(tmp_path / "a.wav", _tone(duration_s=1.0, amplitude=0.8))
    transcript = Transcript(words=[Word(text="hello", start=0.1, end=0.5, speaker="SPEAKER_00")])
    timeline = build_timeline(audio, transcript)
    assert timeline.intervals
    assert timeline.intervals[0].speaker == "SPEAKER_00"


# --------------------------------------------------------------------------
# Queries and the envelope
# --------------------------------------------------------------------------


def test_slicing_clips_the_intervals_to_the_range():
    timeline = SpeechTimeline(
        intervals=[_interval(0, 1000), _interval(2000, 3000)],
        duration_s=4.0,
    )
    clipped = timeline.slice(0.5, 2.5)
    assert len(clipped) == 2
    assert clipped[0].start_ms == 500
    assert clipped[0].end_ms == 1000
    assert clipped[1].start_ms == 2000
    assert clipped[1].end_ms == 2500


def test_a_relative_slice_is_measured_from_the_clip():
    """A render's clock starts at the clip, not at the source.

    The timeline is measured against the whole video. Handing its raw times
    to a filtergraph whose clock starts at the clip puts the ducking in the
    wrong place — and, for any clip that is not at the start of the video,
    in a place that does not exist at all.
    """
    timeline = SpeechTimeline(
        intervals=[_interval(62_000, 63_000)],
        duration_s=120.0,
    )

    relative = timeline.relative_slice(60.0, 70.0)

    assert len(relative) == 1
    assert relative[0].start_ms == 2000
    assert relative[0].end_ms == 3000


def test_a_relative_slice_stays_inside_the_clip():
    timeline = SpeechTimeline(
        intervals=[_interval(59_000, 61_000)],
        duration_s=120.0,
    )

    relative = timeline.relative_slice(60.0, 65.0)

    assert relative[0].start_ms == 0
    assert relative[0].end_ms == 1000


def test_density_is_the_share_of_speech():
    timeline = SpeechTimeline(intervals=[_interval(0, 1000)], duration_s=4.0)
    assert timeline.density() == pytest.approx(0.25)


def test_the_envelope_drops_under_speech_and_recovers_after_it():
    timeline = SpeechTimeline(intervals=[_interval(1000, 2000)], duration_s=4.0)
    points = envelope_points(timeline, duck_db=-12.0, attack_ms=120, release_ms=350)
    gains = {round(t, 2): gain for t, gain in points}

    assert gains[0.0] == pytest.approx(1.0)
    # Well inside the speech, the bed is ducked.
    assert gains[1.5] < 0.5
    # After the interval, it is back.
    assert gains[3.0] == pytest.approx(1.0)


def test_the_envelope_recovers_inside_the_interval_not_after_it():
    """The recovery finishes at the end of the interval.

    This is what stops the bed pumping between two words that the transcript
    considers one stretch of speech: the recovery is inside the merged
    interval, so there is no gap for it to happen in.
    """
    timeline = SpeechTimeline(intervals=[_interval(1000, 2000)], duration_s=4.0)
    points = envelope_points(timeline, duck_db=-12.0, attack_ms=100, release_ms=300, step_ms=10)
    before_end = [(t, gain) for t, gain in points if t < 2.0]

    # The last sample before the interval ends is already nearly recovered.
    last_t, last_gain = before_end[-1]
    assert last_t < 2.0
    assert last_gain > 0.9
    # And there is no dip afterwards: the bed stays up.
    after = [gain for t, gain in points if t >= 2.0]
    assert all(gain == pytest.approx(1.0) for gain in after)


def test_a_clip_without_speech_has_a_flat_envelope():
    timeline = SpeechTimeline(intervals=[], duration_s=4.0)
    points = envelope_points(timeline)
    assert all(gain == pytest.approx(1.0) for _, gain in points)


def test_the_envelope_respects_the_ducking_depth():
    timeline = SpeechTimeline(intervals=[_interval(1000, 2000)], duration_s=4.0)
    points = envelope_points(timeline, duck_db=-24.0, attack_ms=50, release_ms=100)
    ducked = min(gain for _, gain in points)
    assert ducked == pytest.approx(10 ** (-24.0 / 20.0), rel=0.2)


# --------------------------------------------------------------------------
# The audio reader
# --------------------------------------------------------------------------


def test_the_reader_handles_a_16_bit_mono_wav(tmp_path: Path):
    audio = _write_wav(tmp_path / "a.wav", _tone(duration_s=0.2, amplitude=0.8))
    from autoclip.pipeline.speech_timeline import _read_frames

    samples = _read_frames(audio)
    assert samples.shape == (3200,)
    assert float(np.max(np.abs(samples))) > 0.7


def test_a_wav_with_the_wrong_bit_depth_still_reads(tmp_path: Path):
    path = tmp_path / "odd.wav"
    with wave.open(str(path), "wb") as handle:
        handle.setnchannels(1)
        handle.setsampwidth(1)
        handle.setframerate(16_000)
        handle.writeframes(bytes([128] * 16_000))

    from autoclip.pipeline.speech_timeline import _read_frames

    samples = _read_frames(path)
    assert samples.size == 16_000
