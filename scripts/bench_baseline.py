"""Repeatable performance baseline for AutoClip.

Run from the repository root:

    .venv\\Scripts\\python.exe scripts/bench_baseline.py

Every measurement is repeated and reported with min / median / max so the same
script can be run again after an upgrade and compared like for like. Results are
written to ``docs/BENCHMARK-BASELINE.json``.

This deliberately measures only work that is deterministic on any machine: no
network calls, no real-media pipeline. Pipeline-level numbers need a real source
video and are recorded separately in ``docs/performance-baseline.md`` (Lane C).
"""

from __future__ import annotations

import json
import os
import statistics
import subprocess
import sys
import tempfile
import time
from pathlib import Path


def timeit(fn, repeat: int = 5) -> dict[str, float]:
    samples: list[float] = []
    for _ in range(repeat):
        start = time.perf_counter()
        fn()
        samples.append((time.perf_counter() - start) * 1000.0)
    return {
        "min_ms": round(min(samples), 2),
        "median_ms": round(statistics.median(samples), 2),
        "max_ms": round(max(samples), 2),
        "samples_ms": [round(s, 2) for s in samples],
    }


def bench_imports() -> dict[str, object]:
    results: dict[str, object] = {}

    def import_app() -> None:
        # First import pays module compilation; later imports are cached.
        if "autoclip.app" in sys.modules:
            for name in [n for n in list(sys.modules) if n.startswith("autoclip")]:
                del sys.modules[name]
        import autoclip.app  # noqa: F401

    results["import_app_cold"] = timeit(import_app, repeat=3)

    def import_pipeline() -> None:
        if "autoclip.pipeline.runner" in sys.modules:
            for name in [n for n in list(sys.modules) if n.startswith("autoclip")]:
                del sys.modules[name]
        import autoclip.pipeline.runner  # noqa: F401

    results["import_pipeline_cold"] = timeit(import_pipeline, repeat=3)
    return results


def bench_db() -> dict[str, object]:
    from autoclip.db import connect, schema, store

    results: dict[str, object] = {}

    def open_existing() -> None:
        conn = connect()
        try:
            conn.execute("PRAGMA user_version").fetchone()
        finally:
            conn.close()

    results["db_open_existing"] = timeit(open_existing, repeat=20)

    def list_jobs() -> None:
        store.list_jobs()

    try:
        results["db_list_jobs"] = timeit(list_jobs, repeat=20)
    except Exception as exc:  # noqa: BLE001 - benchmark must not fail a run
        results["db_list_jobs"] = {"error": str(exc)}

    with tempfile.TemporaryDirectory() as tmp:
        db_path = Path(tmp) / "bench.db"

        def fresh_migrate() -> None:
            if db_path.exists():
                db_path.unlink()
            conn = connect(db_path)
            try:
                schema.migrate(conn)
            finally:
                conn.close()

        results["db_fresh_migrate"] = timeit(fresh_migrate, repeat=5)

    return results


def bench_filtergraph() -> dict[str, object]:
    from autoclip.config import ExportSettings
    from autoclip.pipeline import export

    settings = ExportSettings(music_ducking=True, music_volume=0.25, ducking_amount_db=-14.0)

    def build() -> None:
        export.build_mixed_audio_filtergraph(settings, Path("track.mp3"), 42.0)

    return {"music_filtergraph_build": timeit(build, repeat=100)}


def bench_ffmpeg_encode() -> dict[str, object]:
    """Encode 5 s of 1080x1920 at 30 fps - the export's real output shape."""
    results: dict[str, object] = {}
    with tempfile.TemporaryDirectory() as tmp:
        out = Path(tmp) / "bench.mp4"

        def encode() -> None:
            subprocess.run(
                [
                    "ffmpeg",
                    "-hide_banner",
                    "-loglevel",
                    "error",
                    "-y",
                    "-f",
                    "lavfi",
                    "-i",
                    "testsrc2=size=1080x1920:rate=30:duration=5",
                    "-f",
                    "lavfi",
                    "-i",
                    "sine=frequency=440:duration=5",
                    "-c:v",
                    "libx264",
                    "-preset",
                    "veryfast",
                    "-crf",
                    "23",
                    "-c:a",
                    "aac",
                    "-shortest",
                    str(out),
                ],
                check=True,
                capture_output=True,
            )
            results["output_bytes"] = out.stat().st_size

        try:
            results["encode_5s_1080x1920"] = timeit(encode, repeat=3)
        except Exception as exc:  # noqa: BLE001
            results["encode_5s_1080x1920"] = {"error": str(exc)}
    return results


def main() -> int:
    repo = Path(__file__).resolve().parent.parent
    backend = repo / "backend"
    if str(backend) not in sys.path:
        sys.path.insert(0, str(backend))

    report: dict[str, object] = {
        "generated_at_utc": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "platform": sys.platform,
        "python": sys.version.split()[0],
        "cpu_count": os.cpu_count(),
        "sections": {},
    }
    sections = report["sections"]
    assert isinstance(sections, dict)

    for name, fn in [
        ("imports", bench_imports),
        ("database", bench_db),
        ("filtergraph", bench_filtergraph),
        ("ffmpeg", bench_ffmpeg_encode),
    ]:
        print(f"--- {name} ---", flush=True)
        try:
            sections[name] = fn()
        except Exception as exc:  # noqa: BLE001
            sections[name] = {"error": f"{type(exc).__name__}: {exc}"}
        print(json.dumps(sections[name], indent=2), flush=True)

    out = repo / "docs" / "BENCHMARK-BASELINE.json"
    out.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    print(f"\nwrote {out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
