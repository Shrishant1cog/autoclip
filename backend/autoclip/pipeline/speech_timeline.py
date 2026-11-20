"""One speech timeline, shared by everything that needs to know when someone speaks.

This module exists because two consumers need the same answer — the music
ducking and the webcam layout — and two detectors answering the same question
differently is how a bed ducks under a word that the layout ignores.

The timeline is built once per job, from three sources that already exist:

* **Word timestamps** from the transcript. These are the strongest signal:
  a word with a measured start and end is speech, whatever the audio looks
  like.
* **A local VAD** over the extracted audio, which catches speech the
  transcript missed — a shout, a laugh, a word at the edge of a clip.
* **The transcript's own structure**, for speaker labels.

The VAD rule the specification approves:

* a frame with confidence **≥ 0.75** counts as speech when **at least one
  transcript word overlaps it**; or
* **nine consecutive 30 ms frames** at confidence **≥ 0.90** count as speech
  on their own — 270 ms of near-certain speech is speech even when no word
  was recognised.

Intervals are then merged. The merge happens on **millisecond** timestamps,
before any frame quantisation, and the rule is exact: a gap of **349 ms
merges**, a gap of **350 ms does not**. The 30 ms frame grid is a detector's
resolution, not the timeline's resolution, and using it to decide the merge
would smear the boundary by up to a frame.

Every interval carries the confidence that produced it and the speaker it
belongs to, so a downstream stage can ask "how sure are we" and "who is
talking" without running another detector.
"""

from __future__ import annotations

import json
import logging
import math
from dataclasses import asdict, dataclass, field
from pathlib import Path

import numpy as np

from .transcript import Transcript

log = logging.getLogger(__name__)

__all__ = [
    "FRAME_MS",
    "SpeechInterval",
    "SpeechTimeline",
    "build_timeline",
    "merge_intervals",
    "speech_frames",
]

#: The VAD frame length. 30 ms is the frame the specification names, and it
#: is short enough to place a speech onset accurately.
FRAME_MS = 30

#: The analysis rate the VAD runs at. 16 kHz mono is what the prepare stage
#: already produces, so the timeline reads the file the pipeline made.
VAD_RATE = 16_000

#: Confidence at which a frame counts as speech when a word overlaps it.
WORD_OVERLAP_CONFIDENCE = 0.75

#: Confidence at which nine consecutive frames count as speech on their own.
CONTINUOUS_CONFIDENCE = 0.90

#: How many consecutive frames make the continuous window: 9 x 30 ms = 270 ms.
CONTINUOUS_FRAMES = 9

#: The merge gap, in milliseconds. A gap of 349 ms merges; 350 ms does not.
MERGE_GAP_MS = 350

#: A frame quieter than this is silence, whatever else it is.
SILENCE_FLOOR_DB = -60.0

#: The level a frame must reach to count as speech on its own account,
#: independent of the recording's own noise floor.
ABSOLUTE_SPEECH_DB = -50.0

#: How many dB above the absolute level is full confidence.
ABSOLUTE_SPAN_DB = 15.0

#: The smallest level range used as the denominator of the relative measure,
#: so a recording with almost no dynamic range does not divide by ~0.
MIN_SPAN_DB = 12.0


def _as_int(value: object, default: int = 0) -> int:
    """Read an integer out of untrusted JSON."""
    if isinstance(value, bool):
        return default
    if isinstance(value, int):
        return value
    if isinstance(value, float):
        return int(value)
    if isinstance(value, str):
        try:
            return int(value)
        except ValueError:
            return default
    return default


def _as_float(value: object, default: float = 0.0) -> float:
    """Read a number out of untrusted JSON."""
    if isinstance(value, bool):
        return default
    if isinstance(value, (int, float)):
        return float(value)
    if isinstance(value, str):
        try:
            return float(value)
        except ValueError:
            return default
    return default


@dataclass
class SpeechInterval:
    """A stretch of speech, in milliseconds from the start of the audio."""

    start_ms: int
    end_ms: int
    #: How confident the detector was, 0–1.
    confidence: float = 0.0
    #: "word" when a transcript word overlaps it, "vad" when the continuous
    #: window alone produced it.
    source: str = "vad"
    #: Speaker label from the transcript, when one is known.
    speaker: str | None = None

    @property
    def duration_ms(self) -> int:
        return max(0, self.end_ms - self.start_ms)

    def to_dict(self) -> dict[str, object]:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict[str, object]) -> SpeechInterval:
        speaker = data.get("speaker")
        return cls(
            start_ms=_as_int(data.get("start_ms"), 0),
            end_ms=_as_int(data.get("end_ms"), 0),
            confidence=_as_float(data.get("confidence"), 0.0),
            source=str(data.get("source", "vad")),
            speaker=str(speaker) if isinstance(speaker, str) else None,
        )


@dataclass
class SpeechTimeline:
    """Every stretch of speech in one source video."""

    intervals: list[SpeechInterval] = field(default_factory=list)
    #: The audio the timeline was measured from.
    duration_s: float = 0.0
    #: Which detector produced it, for the diagnostics.
    detector: str = "energy-vad"

    def to_dict(self) -> dict[str, object]:
        return {
            "detector": self.detector,
            "duration_s": round(self.duration_s, 3),
            "intervals": [interval.to_dict() for interval in self.intervals],
        }

    @classmethod
    def from_dict(cls, data: dict[str, object]) -> SpeechTimeline:
        raw = data.get("intervals")
        items = raw if isinstance(raw, list) else []
        intervals = [SpeechInterval.from_dict(item) for item in items if isinstance(item, dict)]
        return cls(
            intervals=intervals,
            duration_s=_as_float(data.get("duration_s"), 0.0),
            detector=str(data.get("detector", "energy-vad")),
        )

    def save(self, path: Path) -> Path:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(self.to_dict(), ensure_ascii=False), encoding="utf-8")
        return path

    @classmethod
    def load(cls, path: Path) -> SpeechTimeline:
        return cls.from_dict(json.loads(Path(path).read_text(encoding="utf-8")))

    # -- queries ---------------------------------------------------------

    def speech_seconds(self) -> float:
        """How much of the timeline is speech, in seconds."""
        return sum(interval.duration_ms for interval in self.intervals) / 1000.0

    def density(self) -> float:
        """The share of the timeline that is speech, 0–1."""
        if self.duration_s <= 0:
            return 0.0
        return min(1.0, self.speech_seconds() / self.duration_s)

    def overlapping(self, start_s: float, end_s: float) -> list[SpeechInterval]:
        """The intervals that overlap a time range."""
        start_ms = int(round(start_s * 1000))
        end_ms = int(round(end_s * 1000))
        return [
            interval
            for interval in self.intervals
            if interval.start_ms < end_ms and interval.end_ms > start_ms
        ]

    def slice(self, start_s: float, end_s: float) -> list[SpeechInterval]:
        """The intervals inside a time range, clipped to it."""
        start_ms = int(round(start_s * 1000))
        end_ms = int(round(end_s * 1000))
        out: list[SpeechInterval] = []
        for interval in self.overlapping(start_s, end_s):
            out.append(
                SpeechInterval(
                    start_ms=max(start_ms, interval.start_ms),
                    end_ms=min(end_ms, interval.end_ms),
                    confidence=interval.confidence,
                    source=interval.source,
                    speaker=interval.speaker,
                )
            )
        return out


# --------------------------------------------------------------------------
# Merging
# --------------------------------------------------------------------------


def merge_intervals(
    intervals: list[SpeechInterval], *, gap_ms: int = MERGE_GAP_MS
) -> list[SpeechInterval]:
    """Merge intervals whose gap is shorter than ``gap_ms``.

    The comparison is exact and happens in integer milliseconds. A gap of
    349 ms merges; a gap of 350 ms does not. The intervals are assumed to be
    in millisecond units precisely so that this boundary is not a matter of
    floating-point luck.

    Overlapping intervals always merge. A gap *equal* to ``gap_ms`` does not.
    """
    if not intervals:
        return []

    ordered = sorted(intervals, key=lambda interval: (interval.start_ms, interval.end_ms))
    merged: list[SpeechInterval] = [ordered[0]]

    for interval in ordered[1:]:
        current = merged[-1]
        gap = interval.start_ms - current.end_ms
        if gap < gap_ms:
            # Overlapping or close enough to be one stretch of speech.
            if interval.end_ms > current.end_ms:
                current.end_ms = interval.end_ms
            current.confidence = max(current.confidence, interval.confidence)
            if current.speaker is None:
                current.speaker = interval.speaker
            if current.source != interval.source and interval.source == "word":
                # A word-backed interval is the stronger claim.
                current.source = "word"
            continue
        merged.append(interval)

    return merged


# --------------------------------------------------------------------------
# The detector
# --------------------------------------------------------------------------


def _read_frames(path: Path) -> np.ndarray:
    """Read the prepared 16 kHz mono WAV into float samples."""
    import wave

    with wave.open(str(path), "rb") as handle:
        frames = handle.readframes(handle.getnframes())
        channels = handle.getnchannels()
        width = handle.getsampwidth()
        sample_rate = handle.getframerate()

    if width != 2:
        # The prepare stage writes 16-bit PCM. Anything else is unexpected;
        # fall back to a mono float reading through ffmpeg.
        return _read_frames_via_ffmpeg(path)

    samples = np.frombuffer(frames, dtype="<i2").astype(np.float32) / 32768.0
    if channels > 1:
        usable = samples.size - (samples.size % channels)
        samples = samples[:usable].reshape(-1, channels).mean(axis=1)
    if sample_rate != VAD_RATE:
        # The timeline's frame length is defined in time, not in samples, so a
        # different rate is resampled by the caller; this is only a guard.
        log.debug("Audio is %d Hz, expected %d Hz.", sample_rate, VAD_RATE)
    return samples


def _read_frames_via_ffmpeg(path: Path) -> np.ndarray:
    import subprocess

    from . import ffmpeg

    command = [
        ffmpeg.ffmpeg_path(),
        "-hide_banner",
        "-nostdin",
        "-nostats",
        *ffmpeg.protocol_args(),
        "-i",
        str(path),
        "-vn",
        "-f",
        "f32le",
        "-ac",
        "1",
        "-ar",
        str(VAD_RATE),
        "-",
    ]
    result = subprocess.run(command, capture_output=True, check=False)
    if result.returncode != 0:
        raise RuntimeError(f"Could not read audio from {path.name}.")
    return np.frombuffer(result.stdout, dtype=np.float32).copy()


def speech_frames(samples: np.ndarray, *, frame_ms: int = FRAME_MS) -> list[float]:
    """Per-frame speech confidence, 0–1.

    The detector is energy-based and local: the noise floor is estimated from
    the track itself (the quietest tenth of the frames), and a frame's
    confidence is the stronger of two measures — how far the frame sits above
    that floor, and how far it sits above an absolute level that counts as
    speech on its own account. The second measure is what keeps a recording
    with no silence from being written off as room tone.

    It is deliberately
    simple and deterministic — the same audio always gives the same timeline,
    which is what makes the boundary tests meaningful.

    A frame that is silent, or that sits at the noise floor, gets zero.
    """
    if samples.size == 0:
        return []

    frame_length = max(1, int(round(VAD_RATE * frame_ms / 1000)))
    usable = samples.size - (samples.size % frame_length)
    if usable <= 0:
        return []
    frames = samples[:usable].reshape(-1, frame_length)
    rms = np.sqrt(np.mean(np.square(frames), axis=1))

    if rms.size == 0 or float(rms.max()) <= 1e-9:
        return [0.0] * int(rms.size)

    levels_db = np.maximum(20.0 * np.log10(np.maximum(rms, 1e-9)), -70.0)

    # The noise floor is the 10th percentile of frame level: a recording with
    # silence in it has a real floor, and one without has a floor equal to
    # its signal.
    floor_db = float(np.percentile(levels_db, 10))
    peak_db = float(levels_db.max())
    if peak_db <= SILENCE_FLOOR_DB:
        return [0.0] * int(levels_db.size)

    # Two measures, and the stronger one wins.
    #
    # The *relative* measure asks how far the frame sits above the
    # recording's own noise floor, which is what adapts to a quiet room or a
    # noisy one. It fails when the recording has no silence at all: then the
    # floor is the signal, and every frame scores zero.
    #
    # The *absolute* measure asks how far the frame sits above a level that
    # is speech on its own account, regardless of the recording. It is what
    # keeps a continuous signal from being mistaken for a room tone.
    span_db = max(peak_db - floor_db, MIN_SPAN_DB)
    relative = (levels_db - floor_db) / span_db
    absolute = (levels_db - ABSOLUTE_SPEECH_DB) / ABSOLUTE_SPAN_DB
    confidence = np.clip(np.maximum(relative, absolute), 0.0, 1.0)

    # A gentle curve: linear in the first part, flattening near the top, so a
    # frame at 0.75 and a frame at 0.90 are meaningfully different.
    confidence = np.power(confidence, 0.75)
    return [round(float(value), 4) for value in confidence]


def _word_overlaps(word_start_ms: int, word_end_ms: int, frame_start_ms: int) -> bool:
    """Whether a word overlaps a frame at all."""
    return word_start_ms < frame_start_ms + FRAME_MS and word_end_ms > frame_start_ms


def build_timeline(
    audio: Path | None,
    transcript: Transcript | None,
    *,
    frame_ms: int = FRAME_MS,
) -> SpeechTimeline:
    """Build the speech timeline for one source video.

    ``audio`` is the prepared 16 kHz mono WAV; ``transcript`` may be empty,
    in which case only the continuous-window rule can produce intervals.
    """
    words = list(transcript.words) if transcript else []
    duration_s = 0.0
    frames: list[float] = []

    if audio is not None and Path(audio).is_file():
        samples = _read_frames(Path(audio))
        frames = speech_frames(samples, frame_ms=frame_ms)
        duration_s = len(samples) / VAD_RATE

    if not frames:
        return SpeechTimeline(intervals=[], duration_s=duration_s)

    frame_starts = [index * frame_ms for index in range(len(frames))]
    word_ranges = [
        (int(round(word.start * 1000)), int(round(word.end * 1000)), word) for word in words
    ]

    intervals: list[SpeechInterval] = []

    # Rule one: a confident frame with a transcript word over it.
    for index, confidence in enumerate(frames):
        if confidence < WORD_OVERLAP_CONFIDENCE:
            continue
        start = frame_starts[index]
        overlapping = [
            word
            for word_start, word_end, word in word_ranges
            if _word_overlaps(word_start, word_end, start)
        ]
        if not overlapping:
            continue
        speaker = next((word.speaker for word in overlapping if word.speaker), None)
        intervals.append(
            SpeechInterval(
                start_ms=start,
                end_ms=start + frame_ms,
                confidence=confidence,
                source="word",
                speaker=speaker,
            )
        )

    # Rule two: nine consecutive near-certain frames, with no word needed.
    run_start: int | None = None
    for index, confidence in enumerate(frames + [0.0]):
        if confidence >= CONTINUOUS_CONFIDENCE:
            if run_start is None:
                run_start = index
            continue
        if run_start is not None:
            run_length = index - run_start
            if run_length >= CONTINUOUS_FRAMES:
                start = frame_starts[run_start]
                intervals.append(
                    SpeechInterval(
                        start_ms=start,
                        end_ms=start + run_length * frame_ms,
                        confidence=max(frames[run_start:index]),
                        source="vad",
                    )
                )
            run_start = None

    merged = merge_intervals(intervals)

    # Attach speakers to the merged intervals, using the words they cover.
    for interval in merged:
        if interval.speaker is not None:
            continue
        speakers: dict[str, float] = {}
        for word_start, word_end, word in word_ranges:
            if word_start < interval.end_ms and word_end > interval.start_ms and word.speaker:
                speakers[word.speaker] = speakers.get(word.speaker, 0.0) + (word_end - word_start)
        if speakers:
            interval.speaker = max(speakers, key=lambda key: speakers[key])

    return SpeechTimeline(intervals=merged, duration_s=duration_s)


def envelope_points(
    timeline: SpeechTimeline,
    *,
    start_s: float = 0.0,
    end_s: float | None = None,
    duck_db: float = -12.0,
    attack_ms: int = 120,
    release_ms: int = 350,
    step_ms: int = 100,
) -> list[tuple[float, float]]:
    """The gain envelope for a music bed, as ``(seconds, gain)`` points.

    This is the preview the UI draws and the shape the renderer applies. The
    gain is 1.0 when the bed is at full level and ``10 ** (duck_db / 20)``
    while speech is present, with a smooth attack and a smooth recovery.

    The recovery is deliberately *inside* the interval's tail rather than
    after it, so a merged interval does not pump between the words it
    contains.
    """
    if end_s is None:
        end_s = timeline.duration_s
    if end_s <= start_s:
        return [(start_s, 1.0)]

    ducked = 10 ** (duck_db / 20.0)
    attack_ms = max(1, attack_ms)
    release_ms = max(1, release_ms)

    intervals = timeline.slice(start_s, end_s)

    points: list[tuple[float, float]] = []
    current = start_s
    step_s = max(0.01, step_ms / 1000.0)

    def gain_at(moment: float) -> float:
        # The timeline's coordinates are milliseconds; the moment is seconds.
        # Everything below is compared in milliseconds so the two cannot be
        # mixed up.
        moment_ms = moment * 1000.0
        for interval in intervals:
            if not (interval.start_ms <= moment_ms < interval.end_ms):
                continue
            attack_end = interval.start_ms + attack_ms
            release_start = max(attack_end, interval.end_ms - release_ms)
            if moment_ms < attack_end:
                progress = (moment_ms - interval.start_ms) / attack_ms
                progress = max(0.0, min(1.0, progress))
                return 1.0 + (ducked - 1.0) * progress
            if moment_ms >= release_start:
                span = max(1e-6, interval.end_ms - release_start)
                progress = (moment_ms - release_start) / span
                progress = max(0.0, min(1.0, progress))
                return ducked + (1.0 - ducked) * progress
            return ducked
        return 1.0

    while current < end_s:
        points.append((round(current, 3), round(gain_at(current), 4)))
        current += step_s
    points.append((round(end_s, 3), round(gain_at(end_s - 1e-6), 4)))
    return points


def _rms_dbfs(value: float) -> float:
    if value <= 1e-9:
        return -70.0
    return max(-70.0, 20.0 * math.log10(value))
