"""Watch AutoClip jobs and print a completion snapshot on a timer.

Polls the local AutoClip API and prints one block per cycle: every job's
status, stage and completion percentage, plus an overall figure. Used to keep
an eye on long-running jobs (a 3-hour YouTube download plus transcription)
without watching the browser.

Examples
--------
    python scripts/watch_jobs.py                 # watch until every job finishes
    python scripts/watch_jobs.py --duration 600  # watch for 10 minutes, then exit
    python scripts/watch_jobs.py --once          # single snapshot and exit
"""

from __future__ import annotations

import argparse
import contextlib
import json
import sys
import time
import urllib.error
import urllib.request
from datetime import datetime

TERMINAL = {"done", "failed", "cancelled"}


def fetch_jobs(base_url: str, limit: int) -> list[dict]:
    url = f"{base_url.rstrip('/')}/api/jobs?limit={limit}"
    with urllib.request.urlopen(url, timeout=10) as response:  # noqa: S310 - local API
        payload = json.load(response)
    return payload if isinstance(payload, list) else []


def snapshot(base_url: str, limit: int) -> tuple[str, bool]:
    """Return a printable snapshot and whether every job has finished."""
    jobs = fetch_jobs(base_url, limit)
    if not jobs:
        return "No jobs yet.", True

    active = [job for job in jobs if job.get("status") not in TERMINAL]
    finished = len(jobs) - len(active)
    overall = (
        sum(float(job.get("progress") or 0.0) for job in active) / len(active) * 100
        if active
        else 100.0
    )

    stamp = datetime.now().strftime("%H:%M:%S")
    lines = [
        f"[{stamp}] {len(active)} active / {len(jobs)} total  "
        f"({finished} finished)  overall {overall:.1f}%"
    ]
    for job in jobs:
        source = job.get("source") or {}
        title = (source.get("title") or job.get("source_id") or "")[:46]
        progress = float(job.get("progress") or 0.0) * 100
        stage = job.get("current_stage") or "-"
        error = job.get("error") or ""
        lines.append(
            f"    {job['id'][:8]}  {job.get('status', '?'):<9} {stage:<12} "
            f"{progress:5.1f}%  {title}"
        )
        if error:
            lines.append(f"             error: {error.splitlines()[0][:120]}")

    return "\n".join(lines), not active


def main(argv: list[str] | None = None) -> int:
    # Windows consoles default to cp1252, which chokes on emoji in video titles.
    for stream in (sys.stdout, sys.stderr):
        with contextlib.suppress(AttributeError, OSError):
            stream.reconfigure(encoding="utf-8", errors="replace")  # type: ignore[union-attr]

    parser = argparse.ArgumentParser(description="Watch AutoClip job progress.")
    parser.add_argument("--url", default="http://127.0.0.1:8000", help="AutoClip base URL.")
    parser.add_argument("--interval", type=float, default=30.0, help="Seconds between snapshots.")
    parser.add_argument(
        "--duration",
        type=float,
        default=0.0,
        help="Stop after this many seconds (0 watches until every job finishes).",
    )
    parser.add_argument("--limit", type=int, default=100, help="How many jobs to show.")
    parser.add_argument("--once", action="store_true", help="Print one snapshot and exit.")
    args = parser.parse_args(argv)

    deadline = time.monotonic() + args.duration if args.duration else None
    while True:
        try:
            report, all_done = snapshot(args.url, args.limit)
        except (urllib.error.URLError, OSError, ValueError) as exc:
            report, all_done = f"Could not reach AutoClip at {args.url}: {exc}", False

        print(report, flush=True)

        if args.once or all_done:
            return 0
        if deadline is not None and time.monotonic() >= deadline:
            print("[watcher] window elapsed; re-run to continue watching.", flush=True)
            return 0
        time.sleep(args.interval)


if __name__ == "__main__":
    raise SystemExit(main())
