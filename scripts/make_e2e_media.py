"""Cut a short real-media segment so the end-to-end pipeline tests can run.

The 24 tests in ``tests/test_pipeline_e2e.py`` are skipped unless
``AUTOCLIP_E2E_MEDIA`` points at a real video. That gate is deliberate: the
pipeline's risky parts (ffmpeg segment tiling, whisper timing, MediaPipe face
tracking, libass caption burn-in) are exactly the parts that pass on synthetic
colour bars and fail on real footage.

This script finds a suitable source in your AutoClip media library, cuts a
short segment out of it, and optionally runs the suite against it — so the
"skip" count in a normal test run can be driven to zero with one command.

Examples
--------
    python scripts/make_e2e_media.py                 # cut the segment only
    python scripts/make_e2e_media.py --run           # cut it and run the tests
    python scripts/make_e2e_media.py --source D:\\clips\\talk.mp4 --start 120
    python scripts/make_e2e_media.py --list          # show candidates, cut nothing
"""

from __future__ import annotations

import argparse
import contextlib
import os
import subprocess
import sys
from pathlib import Path

from autoclip import paths
from autoclip.pipeline import ffmpeg

#: The tests are slow because transcription dominates. Three minutes of real
#: dialogue is the sweet spot: long enough to prove the pipeline works,
#: short enough to finish in about seven minutes.
DEFAULT_SECONDS = 180.0

#: Where the segment lands when no ``--output`` is given. Kept out of the
#: media library so it is never mistaken for a real ingest.
DEFAULT_OUTPUT = Path(os.environ.get("TEMP", ".")) / "opencode" / "e2e-media.mp4"

#: A candidate must have audio and video, and be long enough to cut from.
MIN_SOURCE_SECONDS = 300.0

VIDEO_SUFFIXES = {".mp4", ".webm", ".mkv", ".mov", ".m4v"}


def _candidate_sources() -> list[Path]:
    """Every ingestable video in the AutoClip media library."""
    media_dir = paths.media_dir()
    if not media_dir.exists():
        return []
    found: list[Path] = []
    for entry in sorted(media_dir.iterdir()):
        if not entry.is_dir():
            continue
        for child in sorted(entry.iterdir()):
            if child.suffix.lower() in VIDEO_SUFFIXES and child.is_file():
                found.append(child)
    return found


def _describe(path: Path) -> str | None:
    """One-line summary of a source, or ``None`` if it is not usable."""
    try:
        info = ffmpeg.probe(path)
    except (ffmpeg.FFmpegError, OSError, ValueError):
        return None
    if not info.has_video or not info.has_audio:
        return None
    if info.duration_s < MIN_SOURCE_SECONDS:
        return None
    return (
        f"{info.duration_s:8.1f}s  {info.width or '?'}x{info.height or '?'}  "
        f"{path.stat().st_size / 1e6:7.1f}MB  {path}"
    )


def _pick_source(explicit: str | None) -> Path:
    if explicit:
        path = Path(explicit).expanduser().resolve()
        if not path.exists():
            raise SystemExit(f"No such file: {path}")
        return path

    candidates = [p for p in _candidate_sources() if _describe(p)]
    if not candidates:
        raise SystemExit(
            "No usable source found in the media library. Ingest a video first, "
            "or pass --source /path/to/video.mp4"
        )

    # Longest wins: the more of the timeline there is, the better the odds of
    # finding a stretch with a face and a voice in it.
    def duration(path: Path) -> float:
        return ffmpeg.probe(path).duration_s

    return max(candidates, key=duration)


def _default_start(source: Path) -> float:
    """Skip the opening minute — intros are usually title cards and silence."""
    return 60.0


def cut(source: Path, output: Path, start: float, seconds: float) -> Path:
    """Cut ``seconds`` of ``source`` starting at ``start`` into ``output``."""
    output.parent.mkdir(parents=True, exist_ok=True)
    if output.exists():
        output.unlink()

    ffmpeg.run(
        [
            "-ss",
            f"{start:.3f}",
            "-i",
            str(source),
            "-t",
            f"{seconds:.3f}",
            "-c:v",
            "libx264",
            "-preset",
            "veryfast",
            "-crf",
            "26",
            "-c:a",
            "aac",
            "-b:a",
            "128k",
            "-movflags",
            "+faststart",
            str(output),
        ]
    )
    return output


def run_tests(output: Path, extra: list[str]) -> int:
    """Run the e2e suite with ``AUTOCLIP_E2E_MEDIA`` pointing at ``output``."""
    env = {**os.environ, "AUTOCLIP_E2E_MEDIA": str(output)}
    command = [
        sys.executable,
        "-m",
        "pytest",
        "tests/test_pipeline_e2e.py",
        "-q",
        "-rs",
        "-p",
        "no:randomly",
        *extra,
    ]
    print(f"\n$ {' '.join(command)}", flush=True)
    return subprocess.run(command, env=env, check=False).returncode


def main(argv: list[str] | None = None) -> int:
    # Windows consoles default to cp1252, which chokes on emoji in paths.
    for stream in (sys.stdout, sys.stderr):
        with contextlib.suppress(AttributeError, OSError):
            stream.reconfigure(encoding="utf-8", errors="replace")  # type: ignore[union-attr]

    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument(
        "--source", help="Video to cut from (default: pick from the media library)."
    )
    parser.add_argument("--output", default=str(DEFAULT_OUTPUT), help="Where to write the segment.")
    parser.add_argument("--start", type=float, default=None, help="Start offset in seconds.")
    parser.add_argument(
        "--seconds", type=float, default=DEFAULT_SECONDS, help="Length of the segment."
    )
    parser.add_argument("--run", action="store_true", help="Run the e2e tests against the segment.")
    parser.add_argument("--list", action="store_true", help="List usable sources and exit.")
    parser.add_argument("pytest_args", nargs="*", help="Extra arguments passed through to pytest.")
    args = parser.parse_args(argv)

    if args.list:
        print("Usable sources in the media library:")
        for path in _candidate_sources():
            summary = _describe(path)
            if summary:
                print(f"  {summary}")
        return 0

    source = _pick_source(args.source)
    start = args.start if args.start is not None else _default_start(source)
    output = Path(args.output).expanduser().resolve()

    info = ffmpeg.probe(source)
    if start + args.seconds > info.duration_s:
        start = max(0.0, info.duration_s - args.seconds)
        print(f"Source is only {info.duration_s:.0f}s long; starting at {start:.0f}s instead.")

    print(f"Cutting {args.seconds:.0f}s from {source} at {start:.0f}s...", flush=True)
    cut(source, output, start, args.seconds)

    written = ffmpeg.probe(output)
    print(f"Wrote {output}")
    print(
        f"  {written.duration_s:.1f}s  {written.width}x{written.height}  "
        f"audio={written.has_audio}  {output.stat().st_size / 1e6:.1f}MB"
    )

    if not args.run:
        print("\nNext: run the tests with")
        print(f'  $env:AUTOCLIP_E2E_MEDIA="{output}"; pytest -m e2e -q')
        print("or re-run this script with --run")
        return 0

    return run_tests(output, args.pytest_args)


if __name__ == "__main__":
    raise SystemExit(main())
