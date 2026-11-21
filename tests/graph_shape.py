"""Structural checks on an ffmpeg filter graph.

Two defects make a graph render on a recent ffmpeg and fail on an older one,
so neither can be left to the ffmpeg that happens to be installed:

* a filter output consumed **twice**. A filter output may be consumed only
  once; naming the same label twice is refused by ffmpeg 7 with *"Invalid
  stream specifier"* and accepted by ffmpeg 9.
* a filter **after** an output label. A label closes its chain, so the
  filters that follow it have no input and the chain's own output is left
  unconnected — *"Filter 'volume:default' has output 1 (bed) unconnected"*.

The check is a parser rather than a set of string assertions, so it applies
to every graph the product builds — the music graph, the video graph, and any
shape they grow into later.
"""

from __future__ import annotations

import re

#: The leading bracketed labels of one filter chain — its inputs.
_LEADING_LABELS = re.compile(r"^((?:\[[^\]]*\])+)")

#: A chain's filters, closed by its output label(s). A filter may emit more
#: than one output — `asplit` does — so there may be more than one.
_CHAIN_TAIL = re.compile(r"[^[]*(\[[^\]]*\])*")


def graph_problems(graph: str) -> list[str]:
    """The ways a filtergraph can be malformed regardless of the ffmpeg build."""
    problems: list[str] = []
    used: list[str] = []

    for chain in graph.split(";"):
        chain = chain.strip()
        if not chain:
            continue

        leading = _LEADING_LABELS.match(chain)
        if not leading:
            problems.append(f"a chain does not start with an input label: {chain!r}")
            continue

        used.extend(label for label in re.findall(r"\[([^\]]*)\]", leading.group(1)) if label)

        tail = chain[leading.end() :]
        if not _CHAIN_TAIL.fullmatch(tail):
            problems.append(f"a filter follows an output label: {chain!r}")

    repeated = sorted({label for label in used if used.count(label) > 1})
    if repeated:
        problems.append(f"these filter outputs are consumed more than once: {repeated}")

    return problems
