#!/usr/bin/env python
"""Detect YouTube uploads that duplicate a video already queued or published.

This is the standalone version of ``autoclip duplicates``. It reads the local
AutoClip database (never the network), and by default **skips** every queued row
that would create a second copy, so the upload worker never sends it.

Examples
--------
    python scripts/detect_duplicate_uploads.py
    python scripts/detect_duplicate_uploads.py --dry-run
    python scripts/detect_duplicate_uploads.py --include-failed
    python scripts/detect_duplicate_uploads.py --by-title

The worker also runs the same same-clip check before every upload, so automation
is protected even when this script is never run. Identical-file hashing is
script-only because it is too expensive to do on every upload.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

# Allow running this file directly from a checkout without installing the
# package (the venv created by the launcher has it editable, but a plain
# `python scripts/...` should work too).
ROOT = Path(__file__).resolve().parents[1]
if str(ROOT / "backend") not in sys.path:
    sys.path.insert(0, str(ROOT / "backend"))

from autoclip import db  # noqa: E402
from autoclip.youtube import duplicates as dup  # noqa: E402


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Detect YouTube uploads that duplicate an already queued or published clip."
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Only report duplicates; do not skip them.",
    )
    parser.add_argument(
        "--by-title",
        action="store_true",
        help="Also flag repeated titles across different clips.",
    )
    parser.add_argument(
        "--include-failed",
        action="store_true",
        help="Treat failed uploads as duplicate candidates (they may be retried).",
    )
    parser.add_argument(
        "--no-hash",
        action="store_true",
        help="Skip byte-for-byte file comparison.",
    )
    parser.add_argument("--json", action="store_true", help="Print JSON instead of text.")
    args = parser.parse_args(argv)

    db.init()
    groups = dup.find_duplicates(
        include_failed=args.include_failed,
        by_title=args.by_title,
        check_files=not args.no_hash,
    )

    skipped = in_flight = 0
    if not args.dry_run and groups:
        skipped, in_flight = dup.skip_duplicates(groups)

    if args.json:
        print(
            json.dumps(
                {
                    "groups": dup.as_json(groups),
                    "total_groups": len(groups),
                    "duplicate_rows": sum(len(group.duplicates) for group in groups),
                    "skipped": skipped,
                    "left_in_flight": in_flight,
                },
                indent=2,
            )
        )
        return 0

    if not groups:
        print("No duplicate uploads found. Nothing to skip.")
        return 0

    for group in groups:
        keep = group.keep.video_id or group.keep.id[:8]
        for row in group.duplicates:
            print(
                f"[{group.reason}] keep={keep} ({group.keep.status}) "
                f"duplicate={row.video_id or row.id[:8]} ({row.status}) "
                f"{(row.title or '(no metadata yet)')[:60]}"
            )

    total = sum(len(group.duplicates) for group in groups)
    print(f"\n{len(groups)} duplicate group(s), {total} extra upload row(s).")

    if args.dry_run:
        print("Dry run: nothing was changed.")
    else:
        print(f"Skipped {skipped} queued upload(s).")
        if in_flight:
            print(
                f"{in_flight} upload(s) were already in flight and left alone; "
                "run again after they finish."
            )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
