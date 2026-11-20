"""Local, deterministic music analysis.

No AI and no network: a track is decoded once with ffmpeg and measured with
ordinary signal processing. The same file always produces the same numbers,
which is what makes the metadata safe to cache and safe to reason about later.

What is measured, and why each number matters:

``bpm``
    Tempo, from the autocorrelation of a spectral-flux onset envelope. The
    confidence says how clear the periodicity was — a track with no pulse
    (a pad, an ambient drone) gets a low confidence and a meaningless BPM,
    and the confidence is what the selector weighs.

``energy``
    Loudness in a perceptual sense: RMS mapped onto 0–1. Used to match music
    to a clip's intensity.

``loudness_lufs``
    Integrated loudness measured by ffmpeg's ``ebur128``, which implements
    BS.1770 properly. This is what makes a bed sit correctly under speech.

``mood``
    A label derived from tempo, energy and spectral shape by a fixed rule set
    (see :func:`classify_mood`). It is a heuristic, not a judgement: the
    rules are written down so a user can see why a track was called "driving".

``rhythm``
    How steady the pulse is. A regular beat suits a montage; a loose one suits
    a talking clip.

``spectral``
    Centroid, rolloff and the percussive/harmonic balance. This is the
    "instrumental character" of the track, measured rather than guessed.

``quality``
    Clipping, DC offset, noise floor and dynamic range. A track that clips is
    a bad bed whatever its mood says.

The analysis is *cached* by the caller against the file's size and mtime, so
a track is measured once and not again.
"""

from __future__ import annotations

import json
import logging
import math
import re
import subprocess
from dataclasses import asdict, dataclass, field
from pathlib import Path

import numpy as np

from ..pipeline import ffmpeg

log = logging.getLogger(__name__)

__all__ = [
    "Analysis",
    "AnalysisError",
    "analyze_track",
    "classify_mood",
    "decode_audio",
    "measure_loudness",
]

#: Analysis sample rate. 22.05 kHz keeps the Nyquist limit at 11 kHz, which
#: covers everything that matters perceptually for tempo and spectral balance,
#: and keeps a five-minute track under 60 MB in memory.
ANALYSIS_RATE = 22_050

#: STFT window and hop for the onset detector.
_FFT_WINDOW = 1024
_FFT_HOP = 512

#: Tempo search range. Below 60 the autocorrelation picks up half- and
#: double-time ambiguity; above 180 it is usually not a musical tempo.
_MIN_BPM = 60.0
_MAX_BPM = 180.0

#: Loudness map: RMS dBFS at the bottom and top of the 0–1 energy scale.
_ENERGY_FLOOR_DB = -40.0
_ENERGY_CEILING_DB = -6.0

#: Mood vocabulary. Fixed, small, and explainable.
MOODS = ("calm", "mellow", "warm", "driving", "energetic", "uplifting", "dark", "tense")


class AnalysisError(RuntimeError):
    """A track could not be measured."""


@dataclass
class Analysis:
    """Everything measured about one track."""

    duration_s: float = 0.0
    sample_rate: int = 0
    channels: int = 0

    bpm: float = 0.0
    bpm_confidence: float = 0.0

    energy: float = 0.0
    rms_dbfs: float = -70.0
    peak_dbfs: float = -70.0
    loudness_lufs: float = -70.0

    mood: str = ""
    mood_scores: dict[str, float] = field(default_factory=dict)

    beat_regularity: float = 0.0
    groove_strength: float = 0.0

    spectral_centroid_hz: float = 0.0
    spectral_rolloff_hz: float = 0.0
    percussive_ratio: float = 0.0
    harmonic_ratio: float = 0.0
    stereo_width: float = 0.0

    clipping_ratio: float = 0.0
    dc_offset: float = 0.0
    noise_floor_dbfs: float = -70.0
    dynamic_range_db: float = 0.0

    def to_dict(self) -> dict[str, object]:
        return asdict(self)

    def to_json(self) -> str:
        return json.dumps(self.to_dict(), ensure_ascii=False, sort_keys=True)

    @classmethod
    def from_json(cls, raw: str) -> Analysis:
        if not raw:
            return cls()
        try:
            data = json.loads(raw)
        except (TypeError, ValueError):
            return cls()
        if not isinstance(data, dict):
            return cls()
        known = {key: value for key, value in data.items() if key in cls.__dataclass_fields__}
        scores = known.get("mood_scores")
        if not isinstance(scores, dict):
            known["mood_scores"] = {}
        return cls(**known)


# --------------------------------------------------------------------------
# Decoding
# --------------------------------------------------------------------------


def decode_audio(path: Path, *, sample_rate: int = ANALYSIS_RATE) -> np.ndarray:
    """Decode an audio file to float samples in ``[-1, 1]``.

    Returns an array shaped ``(channels, samples)``.

    The decode is asked for exactly two channels whatever the file has. A
    mono file is duplicated into both channels and a multi-channel file is
    downmixed, which means the sample count always divides by two and the
    duration is never wrong. It also means the stereo-width measurement
    reports zero for a mono source, which is the truth about it.

    FFmpeg is asked for raw 32-bit float so nothing is quantised twice; the
    pipeline's own protocol restrictions apply, so this reads local files
    only.
    """
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
        "-acodec",
        "pcm_f32le",
        "-ac",
        "2",
        "-ar",
        str(sample_rate),
        "-",
    ]
    try:
        result = subprocess.run(
            command,
            capture_output=True,
            check=False,
        )
    except OSError as exc:
        raise AnalysisError(f"Could not run ffmpeg to read {path.name}: {exc}") from exc

    if result.returncode != 0:
        tail = result.stderr.decode("utf-8", "replace").strip().splitlines()[-3:]
        raise AnalysisError(
            f"Could not decode {path.name}: " + (" ".join(tail) if tail else "ffmpeg failed")
        )

    raw = np.frombuffer(result.stdout, dtype=np.float32)
    if raw.size == 0:
        raise AnalysisError(f"{path.name} contains no audio.")

    # Two channels are kept apart so the stereo width can be measured; the
    # spectral work uses their average.
    channels = 2
    usable = raw.size - (raw.size % channels)
    data = raw[:usable].reshape(-1, channels)
    return np.ascontiguousarray(data.T.astype(np.float32))


_LUFS_PATTERN = re.compile(r"I:\s*(-?\d+(?:\.\d+)?)\s*LUFS", re.IGNORECASE)
_TRUE_PEAK_PATTERN = re.compile(r"Peak:\s*(-?\d+(?:\.\d+)?)\s*dBFS", re.IGNORECASE)


def measure_loudness(path: Path) -> tuple[float, float]:
    """Integrated loudness and true peak, in LUFS and dBFS.

    FFmpeg's ``ebur128`` implements BS.1770, which is the standard platforms
    measure against. Returns ``(-70.0, -70.0)`` when the measurement fails —
    an unmeasurable level must not fail the analysis of an otherwise fine
    track.
    """
    command = [
        ffmpeg.ffmpeg_path(),
        "-hide_banner",
        "-nostdin",
        "-nostats",
        *ffmpeg.protocol_args(),
        "-i",
        str(path),
        "-filter_complex",
        "ebur128=peak=true",
        "-f",
        "null",
        "-",
    ]
    try:
        result = subprocess.run(command, capture_output=True, check=False)
    except OSError:
        return (-70.0, -70.0)

    text = result.stderr.decode("utf-8", "replace")
    integrated = _LUFS_PATTERN.search(text)
    peak = _TRUE_PEAK_PATTERN.search(text)
    lufs = float(integrated.group(1)) if integrated else -70.0
    true_peak = float(peak.group(1)) if peak else -70.0
    return (lufs, true_peak)


# --------------------------------------------------------------------------
# Measurement
# --------------------------------------------------------------------------


def _dbfs(value: float) -> float:
    """Amplitude ratio to dBFS, with silence floored at -70 dBFS."""
    if value <= 1e-9:
        return -70.0
    return max(-70.0, 20.0 * math.log10(value))


def _frames(signal: np.ndarray, window: int, hop: int) -> np.ndarray:
    """Split ``signal`` into overlapping frames. The tail is dropped."""
    if signal.size < window:
        return np.empty((0, window), dtype=np.float32)
    count = 1 + (signal.size - window) // hop
    strides = (signal.strides[0] * hop, signal.strides[0])
    return np.lib.stride_tricks.as_strided(
        signal, shape=(count, window), strides=strides, writeable=False
    )


def _onset_envelope(signal: np.ndarray, sample_rate: int) -> np.ndarray:
    """Spectral-flux onset strength per STFT frame."""
    window = np.hanning(_FFT_WINDOW).astype(np.float32)
    frames = _frames(signal, _FFT_WINDOW, _FFT_HOP)
    if frames.shape[0] == 0:
        return np.zeros(0, dtype=np.float32)

    # rfft over the windowed frames; the magnitude is what we difference.
    spectrum = np.abs(np.fft.rfft(frames * window, axis=1))
    difference = np.diff(spectrum, axis=0)
    flux = np.maximum(difference, 0.0).sum(axis=1)
    if flux.size:
        # Subtract a local mean so the envelope reacts to *new* energy rather
        # than to a track that is simply loud throughout.
        kernel = np.ones(16, dtype=np.float32) / 16.0
        baseline = np.convolve(flux, kernel, mode="same")
        flux = np.maximum(flux - baseline, 0.0)
    return flux.astype(np.float32)


def _estimate_bpm(signal: np.ndarray, sample_rate: int) -> tuple[float, float]:
    """Tempo and how confident we are in it."""
    envelope = _onset_envelope(signal, sample_rate)
    if envelope.size < 16 or not envelope.any():
        return (0.0, 0.0)

    envelope = envelope - envelope.mean()
    correlation = np.correlate(envelope, envelope, mode="full")[envelope.size - 1 :]
    if correlation.size == 0 or correlation[0] <= 0:
        return (0.0, 0.0)
    correlation = correlation / correlation[0]

    frames_per_second = sample_rate / _FFT_HOP
    min_lag = max(1, int(round(60.0 * frames_per_second / _MAX_BPM)))
    max_lag = min(correlation.size - 1, int(round(60.0 * frames_per_second / _MIN_BPM)))
    if max_lag <= min_lag:
        return (0.0, 0.0)

    window = correlation[min_lag : max_lag + 1]
    if window.size == 0:
        return (0.0, 0.0)

    best = int(np.argmax(window))
    peak = float(window[best])
    # The mean of the search window is the "no periodicity" baseline, so the
    # ratio of peak to mean is a usable confidence.
    baseline = float(window.mean()) or 1e-9
    confidence = max(0.0, min(1.0, (peak / baseline - 1.0) / 3.0))

    lag = min_lag + best
    bpm = 60.0 * frames_per_second / lag

    # Fold into the 60–180 range: 200 BPM and 100 BPM are the same pulse, and
    # the lower reading is the one a listener would quote.
    while bpm < _MIN_BPM:
        bpm *= 2.0
    while bpm > _MAX_BPM:
        bpm /= 2.0

    return (round(bpm, 2), round(confidence, 4))


def _beat_regularity(signal: np.ndarray, sample_rate: int, bpm: float) -> tuple[float, float]:
    """How steady the pulse is, and how strong the pulse is.

    Regularity is the inverse of the spread of the detected beat intervals:
    a metronome is 1.0, a drifting performance is lower. Strength is the
    contrast of the onset envelope, which separates a track with a real beat
    from one that merely has loud passages.
    """
    envelope = _onset_envelope(signal, sample_rate)
    if envelope.size < 8 or bpm <= 0:
        return (0.0, 0.0)

    frames_per_second = sample_rate / _FFT_HOP
    period = 60.0 * frames_per_second / bpm
    if period < 2:
        return (0.0, 0.0)

    threshold = float(envelope.mean()) + 0.5 * float(envelope.std())
    peaks: list[float] = []
    index = 0
    size = envelope.size
    while index < size:
        if envelope[index] <= threshold:
            index += 1
            continue
        # Walk to the local maximum within half a beat.
        end = min(size, index + int(period / 2) + 1)
        best = index
        for candidate in range(index, end):
            if envelope[candidate] > envelope[best]:
                best = candidate
        peaks.append(float(best))
        index = best + max(1, int(period * 0.75))

    if len(peaks) < 3:
        return (0.0, 0.0)

    intervals = np.diff(np.asarray(peaks)) / frames_per_second
    if intervals.size == 0:
        return (0.0, 0.0)

    spread = float(intervals.std())
    mean_interval = float(intervals.mean()) or 1e-9
    regularity = max(0.0, min(1.0, 1.0 - (spread / mean_interval)))

    strength = float(envelope.std()) / (float(envelope.mean()) or 1e-9)
    groove = max(0.0, min(1.0, strength / 4.0))

    return (round(regularity, 4), round(groove, 4))


def _spectral_shape(signal: np.ndarray, sample_rate: int) -> dict[str, float]:
    """Centroid, rolloff and the percussive/harmonic balance.

    The percussive/harmonic split is a cheap median-filter comparison: a
    signal whose spectrum changes quickly from frame to frame is percussive,
    one whose spectrum is steady is harmonic.
    """
    window = np.hanning(_FFT_WINDOW).astype(np.float32)
    frames = _frames(signal, _FFT_WINDOW, _FFT_HOP)
    if frames.shape[0] == 0:
        return {
            "centroid_hz": 0.0,
            "rolloff_hz": 0.0,
            "percussive_ratio": 0.0,
            "harmonic_ratio": 0.0,
        }

    spectrum = np.abs(np.fft.rfft(frames * window, axis=1))
    magnitudes = spectrum.mean(axis=0)
    frequencies = np.fft.rfftfreq(_FFT_WINDOW, d=1.0 / sample_rate)
    total = float(magnitudes.sum())
    if total <= 0:
        return {
            "centroid_hz": 0.0,
            "rolloff_hz": 0.0,
            "percussive_ratio": 0.0,
            "harmonic_ratio": 0.0,
        }

    centroid = float((frequencies * magnitudes).sum() / total)
    cumulative = np.cumsum(magnitudes)
    rolloff_index = int(np.searchsorted(cumulative, 0.85 * total))
    rolloff = float(frequencies[min(rolloff_index, frequencies.size - 1)])

    # Percussiveness: how much the spectrum moves between adjacent frames.
    if spectrum.shape[0] > 2:
        movement = np.abs(np.diff(spectrum, axis=0)).mean()
        steadiness = spectrum.mean(axis=0).mean()
        ratio = float(movement / (steadiness or 1e-9))
        percussive = max(0.0, min(1.0, ratio / 8.0))
    else:
        percussive = 0.0

    return {
        "centroid_hz": round(centroid, 2),
        "rolloff_hz": round(rolloff, 2),
        "percussive_ratio": round(percussive, 4),
        "harmonic_ratio": round(1.0 - percussive, 4),
    }


def classify_mood(
    *,
    bpm: float,
    energy: float,
    centroid_hz: float,
    percussive_ratio: float,
) -> tuple[str, dict[str, float]]:
    """Label a track's mood by a fixed rule set.

    The rules are deliberately simple and written out, because a user who
    disagrees with a label should be able to see why it was applied. Every
    mood gets a score; the highest wins, and the scores are returned so the
    UI can show the alternatives.

    Six measurements drive the rules:

    * **quiet** / **loud** / **middle** — where the track's energy sits.
    * **slow** / **fast** — where its tempo sits.
    * **dark** / **bright** — where its spectral centre sits.
    * **pulse** — how percussive it is.

    And the moods combine them:

    =============  =========================================================
    **calm**       quiet and slow.
    **dark**       quiet, with a low spectral centre.
    **mellow**     quiet, with a middling tempo.
    **warm**       middle energy, slow, and bright.
    **energetic**  loud and fast.
    **driving**    loud and slow, with a pulse.
    **tense**      loud, with a pulse and a dark spectrum.
    **uplifting**  loud, with a middling energy and a bright spectrum.
    =============  =========================================================
    """
    scores = dict.fromkeys(MOODS, 0.0)

    quiet = 1.0 - _ramp(energy, 0.20, 0.55)
    loud = _ramp(energy, 0.45, 0.80)
    middle = max(0.0, 1.0 - abs(energy - 0.45) / 0.35)
    slow = 1.0 - _ramp(bpm, 60.0, 100.0)
    fast = _ramp(bpm, 70.0, 140.0)
    dark = 1.0 - _ramp(centroid_hz, 400.0, 2500.0)
    bright = _ramp(centroid_hz, 800.0, 3500.0)
    pulse = percussive_ratio

    scores["calm"] = 0.55 * quiet + 0.45 * slow
    scores["dark"] = 0.45 * quiet + 0.35 * dark + 0.20 * pulse
    scores["mellow"] = 0.45 * quiet + 0.35 * middle + 0.20 * slow
    scores["warm"] = 0.45 * middle + 0.30 * slow + 0.25 * bright
    scores["energetic"] = 0.55 * loud + 0.45 * fast
    scores["driving"] = 0.45 * loud + 0.30 * slow + 0.25 * pulse
    scores["tense"] = 0.40 * loud + 0.35 * pulse + 0.25 * dark
    scores["uplifting"] = 0.35 * loud + 0.30 * middle + 0.20 * fast + 0.15 * bright

    rounded = {mood: round(value, 4) for mood, value in scores.items()}
    best = max(rounded, key=lambda mood: (rounded[mood], mood))
    return (best, rounded)


def _ramp(value: float, low: float, high: float) -> float:
    """Map ``value`` onto 0–1 between ``low`` and ``high``."""
    if high <= low:
        return 0.0 if value < low else 1.0
    return max(0.0, min(1.0, (value - low) / (high - low)))


def analyze_track(path: Path, *, loudness: bool = True) -> Analysis:
    """Measure one track.

    Raises :class:`AnalysisError` when the file cannot be decoded at all —
    an unreadable file is a different thing from a quiet one.
    """
    path = Path(path)
    if not path.is_file():
        raise AnalysisError(f"{path} is not a file.")

    data = decode_audio(path)
    channels, samples = data.shape
    mono = data.mean(axis=0)
    duration = samples / ANALYSIS_RATE

    rms = float(np.sqrt(np.mean(np.square(mono)))) if mono.size else 0.0
    peak = float(np.max(np.abs(mono))) if mono.size else 0.0
    rms_db = _dbfs(rms)
    peak_db = _dbfs(peak)

    energy = _ramp(rms_db, _ENERGY_FLOOR_DB, _ENERGY_CEILING_DB)

    bpm, bpm_confidence = _estimate_bpm(mono, ANALYSIS_RATE)
    regularity, groove = _beat_regularity(mono, ANALYSIS_RATE, bpm)
    spectral = _spectral_shape(mono, ANALYSIS_RATE)

    mood, mood_scores = classify_mood(
        bpm=bpm,
        energy=energy,
        centroid_hz=spectral["centroid_hz"],
        percussive_ratio=spectral["percussive_ratio"],
    )

    # Frame-level statistics for the noise floor and dynamic range.
    if mono.size:
        frame_rms = np.sqrt(np.mean(np.square(_frames(mono, 1024, 1024)), axis=1))
    else:
        frame_rms = np.zeros(0)
    if frame_rms.size:
        percentile = np.percentile(frame_rms, [10, 95])
        noise_floor = _dbfs(float(percentile[0]))
        dynamic_range = _dbfs(float(percentile[1])) - noise_floor
    else:
        noise_floor = -70.0
        dynamic_range = 0.0

    if channels >= 2:
        left = data[0]
        right = data[1]
        stereo_width = float(
            np.mean(np.abs(left - right)) / (np.mean(np.abs(left + right)) or 1e-9)
        )
    else:
        stereo_width = 0.0

    clipping_ratio = float(np.mean(np.abs(mono) >= 0.999)) if mono.size else 0.0
    dc_offset = float(np.mean(mono)) if mono.size else 0.0

    lufs = -70.0
    true_peak = -70.0
    if loudness:
        lufs, true_peak = measure_loudness(path)
        if lufs <= -70.0:
            # ebur128 unavailable or unparseable: fall back to the RMS figure,
            # which is not LUFS but is better than nothing.
            lufs = rms_db
        if true_peak <= -70.0:
            true_peak = peak_db

    return Analysis(
        duration_s=round(duration, 3),
        sample_rate=ANALYSIS_RATE,
        channels=channels,
        bpm=bpm,
        bpm_confidence=bpm_confidence,
        energy=round(energy, 4),
        rms_dbfs=round(rms_db, 2),
        peak_dbfs=round(peak_db, 2),
        loudness_lufs=round(lufs, 2),
        mood=mood,
        mood_scores=mood_scores,
        beat_regularity=regularity,
        groove_strength=groove,
        spectral_centroid_hz=spectral["centroid_hz"],
        spectral_rolloff_hz=spectral["rolloff_hz"],
        percussive_ratio=spectral["percussive_ratio"],
        harmonic_ratio=spectral["harmonic_ratio"],
        stereo_width=round(stereo_width, 4),
        clipping_ratio=round(clipping_ratio, 6),
        dc_offset=round(dc_offset, 6),
        noise_floor_dbfs=round(noise_floor, 2),
        dynamic_range_db=round(dynamic_range, 2),
    )
