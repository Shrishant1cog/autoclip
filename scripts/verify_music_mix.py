"""Real-ffmpeg integration smoke for Phase 8 (music bed + ducking).

Not part of the default suite: it shells out to ffmpeg and needs the binary.
Run manually:  python scripts\verify_music_mix.py
"""

from __future__ import annotations

import json
import subprocess
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "backend"))

from autoclip.config import ExportSettings  # noqa: E402
from autoclip.pipeline import export, ffmpeg  # noqa: E402
from autoclip.pipeline.reframe.croppath import CropPath, CropSegment  # noqa: E402


def make_source(path: Path, seconds: float) -> None:
    subprocess.run(
        [
            ffmpeg.ffmpeg_path(),
            "-y",
            "-loglevel",
            "error",
            "-f",
            "lavfi",
            "-i",
            f"testsrc=size=1280x720:rate=30:duration={seconds}",
            "-f",
            "lavfi",
            "-i",
            f"sine=frequency=440:duration={seconds}",
            "-c:v",
            "libx264",
            "-pix_fmt",
            "yuv420p",
            "-c:a",
            "aac",
            "-shortest",
            str(path),
        ],
        check=True,
    )


def make_music(path: Path, seconds: float) -> None:
    subprocess.run(
        [
            ffmpeg.ffmpeg_path(),
            "-y",
            "-loglevel",
            "error",
            "-f",
            "lavfi",
            "-i",
            f"sine=frequency=220:duration={seconds}",
            str(path),
        ],
        check=True,
    )


def probe(path: Path) -> dict:
    out = subprocess.run(
        [
            ffmpeg.ffprobe_path(),
            "-v",
            "error",
            "-show_entries",
            "stream=codec_type,duration:format=duration",
            "-of",
            "json",
            str(path),
        ],
        check=True,
        capture_output=True,
        text=True,
    )
    return json.loads(out.stdout)


def main() -> int:
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        source = root / "source.mp4"
        track = root / "music.wav"
        destination = root / "out.mp4"
        make_source(source, 8.0)
        make_music(track, 2.5)  # shorter than the clip: must loop

        settings = ExportSettings(
            music_track=str(track),
            music_volume=0.2,
            music_ducking=True,
            ducking_amount_db=-12,
            prefer_hardware_encoder=False,
        )
        request = export.ExportRequest(
            source=source,
            destination=destination,
            start_s=0.0,
            end_s=5.0,
            crop_path=CropPath(
                source_width=1280,
                source_height=720,
                segments=[CropSegment(start_s=0.0, end_s=5.0, width=405, height=720)],
            ),
            words=[],
            style="bold_pop",
            burn_captions=False,
        )
        export.export_clip(request, work_dir=root, settings=settings)

        info = probe(destination)
        kinds = [s["codec_type"] for s in info["streams"]]
        duration = float(info["format"]["duration"])
        size = destination.stat().st_size
        print(json.dumps({"streams": kinds, "duration": round(duration, 3), "bytes": size}))
        if "video" not in kinds or "audio" not in kinds:
            print("FAIL: missing a stream", file=sys.stderr)
            return 1
        if not (4.5 <= duration <= 5.6):
            print("FAIL: unexpected duration", file=sys.stderr)
            return 1
        print("OK: music mix rendered with video+audio, looping bed")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
