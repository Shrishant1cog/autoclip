"""Recount the feature-coverage matrix and fail if its summary table is stale.

The matrix summary must be derived from the rows, never typed by hand. Run:

    .venv\\Scripts\\python.exe scripts/verify_matrix_counts.py            # check
    .venv\\Scripts\\python.exe scripts/verify_matrix_counts.py --write    # update

Exit code 0 when consistent, 1 when the summary disagrees with the rows.
"""

from __future__ import annotations

import argparse
import re
import sys
from collections import Counter
from pathlib import Path

MATRIX = Path(__file__).resolve().parent.parent / "docs" / "feature-coverage-matrix.md"

#: Canonical label for the summary, and the substring that identifies it in a
#: row's Status cell. Order matters: earlier patterns win, because a cell can
#: read "Blocked — source missing" or "⚠ Partial (broken)".
ORDER = [
    ("Implemented", "Implemented"),
    ("Partial", "Partial"),
    ("Missing", "Missing"),
    ("In progress", "In progress"),
    ("Unverified (external)", "Unverified"),
    ("Blocked — source missing", "Blocked"),
    ("Not yet started", "Not yet started"),
    ("NOT APPLICABLE", "NOT APPLICABLE"),
]

ROW_ID = re.compile(r"^[A-Z]{2,3}-\d+")


def classify(cell: str) -> str:
    for label, needle in ORDER:
        if needle in cell:
            return label
    return f"OTHER:{cell}"


def count_rows(text: str) -> tuple[Counter[str], int]:
    counts: Counter[str] = Counter()
    rows = 0
    for line in text.splitlines():
        if not line.startswith("|"):
            continue
        cells = [c.strip() for c in line.strip("|").split("|")]
        if not cells or not ROW_ID.match(cells[0]):
            continue
        # Nine-column tables put Status at index 4; five-column tables at 3.
        status = cells[4] if len(cells) >= 9 else cells[3]
        counts[classify(status)] += 1
        rows += 1
    return counts, rows


def parse_summary(text: str) -> dict[str, int]:
    """Read the existing summary table back out of the document."""
    in_summary = False
    found: dict[str, int] = {}
    for line in text.splitlines():
        if line.strip().lower().startswith("## summary"):
            in_summary = True
            continue
        if in_summary and line.startswith("## "):
            break
        if not in_summary or not line.startswith("|"):
            continue
        cells = [c.strip() for c in line.strip("|").split("|")]
        if len(cells) != 2:
            continue
        label, value = cells
        value = value.replace("*", "").replace(",", "").strip()
        if value.isdigit():
            found[label] = int(value)
    return found


def render(counts: Counter[str], rows: int) -> str:
    lines = ["| Status | Count |", "|---|---|"]
    for label, _ in ORDER:
        # Only non-zero statuses are listed; a zero row adds noise, and the
        # checker below compares the same filtered set.
        if counts.get(label, 0):
            lines.append(f"| {label} | {counts[label]} |")
    for label in sorted(k for k in counts if k.startswith("OTHER:")):
        lines.append(f"| {label[6:]} | {counts[label]} |")
    lines.append(f"| **Total rows** | **{rows}** |")
    return "\n".join(lines)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--write", action="store_true", help="rewrite the summary table")
    args = parser.parse_args()

    text = MATRIX.read_text(encoding="utf-8")
    counts, rows = count_rows(text)
    actual = parse_summary(text)

    expected = {label: counts[label] for label, _ in ORDER if counts.get(label, 0)}
    expected["**Total rows**"] = rows

    mismatched = [
        (label, actual.get(label, 0), want)
        for label, want in expected.items()
        if actual.get(label, 0) != want
    ]
    # A row that exists in the summary but has no rows behind it is also stale.
    mismatched += [
        (label, have, 0)
        for label, have in actual.items()
        if label not in expected and label != "**Total rows**"
    ]

    if not mismatched:
        print(f"matrix summary is consistent ({rows} rows)")
        return 0

    print("matrix summary is STALE:")
    for label, have, want in mismatched:
        print(f"  {label}: table says {have}, rows say {want}")

    if args.write:
        new_counts_block = render(counts, rows)
        pattern = re.compile(r"## Summary\n.*?(\n## |\Z)", re.S)
        replacement = f"## Summary\n\n{new_counts_block}\n\\1"
        updated = pattern.sub(replacement, text, count=1)
        MATRIX.write_text(updated, encoding="utf-8")
        print("rewrote docs/feature-coverage-matrix.md summary")
        return 0

    return 1


if __name__ == "__main__":
    sys.exit(main())
