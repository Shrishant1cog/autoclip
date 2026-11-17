"""Thumbnail rendering for clips published to YouTube.

A 9:16 clip is a phone-shaped strip. Dropped into YouTube's 16:9 frame it
leaves most of the canvas empty, so the layout here is the one that works:
the clip sits sharp on the right, a blurred and darkened copy of the same
frame fills the rest, and the title carries the left side.

Everything is drawn locally with ffmpeg — no model, no network, and the same
input always produces the same thumbnail.
"""

from __future__ import annotations

import logging
import tempfile
from pathlib import Path

from . import ffmpeg

log = logging.getLogger(__name__)

#: YouTube's recommended thumbnail size.
CANVAS_W = 1280
CANVAS_H = 720

#: Gap between the clip panel and the right edge of the canvas.
PANEL_MARGIN = 72
#: Gap between the text block and the left edge of the canvas.
TEXT_MARGIN = 72
#: Width of the accent bar to the left of the title.
ACCENT_BAR_W = 10

TITLE_FONT_SIZE = 58
EYEBROW_FONT_SIZE = 26

#: Matches the accent of the ``bold_pop`` caption style.
DEFAULT_ACCENT = "0xFFE500"

FONT_DIR = Path(__file__).resolve().parent.parent / "assets" / "fonts"
TITLE_FONT = FONT_DIR / "Anton-Regular.ttf"
EYEBROW_FONT = FONT_DIR / "Inter-Variable.ttf"


class ThumbnailError(RuntimeError):
    """A thumbnail could not be rendered."""


def wrap_title(title: str, *, max_chars: int = 19, max_lines: int = 3) -> list[str]:
    """Break a title into at most ``max_lines`` lines of readable length.

    The last line is truncated with an ellipsis rather than dropping words, so
    a long title still reads as a title and not as a cut-off sentence.
    """
    words = title.split()
    if not words:
        return []

    lines: list[str] = []
    current = ""
    for word in words:
        candidate = f"{current} {word}".strip()
        if len(candidate) <= max_chars or not current:
            current = candidate
            continue
        lines.append(current)
        current = word
    if current:
        lines.append(current)

    if len(lines) <= max_lines:
        return lines

    kept = lines[: max_lines - 1]
    remainder = " ".join(lines[max_lines - 1 :])
    if len(remainder) > max_chars:
        remainder = remainder[: max_chars - 1].rstrip() + "…"
    kept.append(remainder)
    return kept


def _eyebrow_text(eyebrow: str) -> str:
    return " ".join(eyebrow.upper().split())[:60]


def render_thumbnail(
    video: Path,
    *,
    title: str,
    output: Path,
    eyebrow: str = "",
    accent: str = DEFAULT_ACCENT,
    at_s: float | None = None,
) -> Path:
    """Render one 1280x720 thumbnail for ``video`` and return its path.

    Preconditions:
        video is a decodable file with a video stream.
    """
    video = Path(video)
    if not video.is_file():
        raise ThumbnailError(f"The clip is missing: {video}")

    info = ffmpeg.probe(video)
    if not info.has_video or not info.width or not info.height:
        raise ThumbnailError(f"{video.name} has no video stream to draw a thumbnail from.")

    duration = info.duration_s or 0.0
    if at_s is None:
        # A quarter of the way in: past any cold open, before the clip winds
        # down, and late enough that the burned-in caption is on screen.
        at_s = max(0.0, min(duration * 0.25, max(0.0, duration - 0.2)))

    panel_h = CANVAS_H
    panel_w = round(CANVAS_H * info.width / info.height)
    if panel_w > 620:
        panel_w = 620
        panel_h = max(1, round(620 * info.height / info.width))
    panel_x = CANVAS_W - panel_w - 8 - PANEL_MARGIN
    panel_y = max(0, (CANVAS_H - panel_h) // 2)

    title_lines = wrap_title(title) or ["Untitled clip"]
    eyebrow_text = _eyebrow_text(eyebrow)

    # Each line is drawn by its own filter with an explicit y, because
    # drawtext's own line spacing follows the font's vertical metrics and
    # leaves a ragged gap that Anton's tall caps make worse.
    line_step = round(TITLE_FONT_SIZE * 1.14)
    block_height = len(title_lines) * line_step
    title_y = max(140, (CANVAS_H - block_height) // 2 + 12)

    output.parent.mkdir(parents=True, exist_ok=True)
    tmp_dir = Path(tempfile.mkdtemp(prefix="autoclip-thumb-"))

    try:
        graph = [
            "[0:v]split=2[bgsrc][fgsrc]",
            (
                f"[bgsrc]scale={CANVAS_W}:{CANVAS_H}:force_original_aspect_ratio=increase,"
                f"crop={CANVAS_W}:{CANVAS_H},boxblur=24:2,"
                "eq=brightness=-0.20:saturation=1.15[bg]"
            ),
            f"[fgsrc]scale=-2:{panel_h},pad=iw+8:ih+8:4:4:{accent}[fg]",
            f"[bg][fg]overlay={panel_x}:{panel_y}[base]",
            (
                f"[base]drawbox=x={TEXT_MARGIN}:y={title_y - 8}:w={ACCENT_BAR_W}:"
                f"h={block_height}:color={accent}@1.0:t=fill[bar]"
            ),
        ]

        chain = "bar"
        if eyebrow_text:
            eyebrow_file = tmp_dir / "eyebrow.txt"
            eyebrow_file.write_text(eyebrow_text, encoding="utf-8")
            graph.append(
                f"[{chain}]drawtext=fontfile={ffmpeg.escape_filter_path(EYEBROW_FONT)}:"
                f"textfile={ffmpeg.escape_filter_path(eyebrow_file)}:"
                f"fontcolor={accent}:fontsize={EYEBROW_FONT_SIZE}:borderw=2:"
                "bordercolor=black@0.8:x=96:y=56:shadowcolor=black@0.5:shadowx=2:shadowy=2"
                "[eyebrow]"
            )
            chain = "eyebrow"

        for index, line in enumerate(title_lines):
            line_file = tmp_dir / f"title-{index}.txt"
            line_file.write_text(line, encoding="utf-8")
            label = "out" if index == len(title_lines) - 1 else f"title{index}"
            graph.append(
                f"[{chain}]drawtext=fontfile={ffmpeg.escape_filter_path(TITLE_FONT)}:"
                f"textfile={ffmpeg.escape_filter_path(line_file)}:"
                f"fontcolor=white:fontsize={TITLE_FONT_SIZE}:borderw=4:"
                f"bordercolor=black@0.85:"
                f"x={TEXT_MARGIN + ACCENT_BAR_W + 24}:y={title_y + index * line_step}:"
                "shadowcolor=black@0.55:shadowx=3:shadowy=3"
                f"[{label}]"
            )
            chain = label

        ffmpeg.run(
            [
                "-i",
                str(video),
                "-ss",
                f"{at_s:.3f}",
                "-filter_complex",
                ";".join(graph),
                "-map",
                "[out]",
                "-frames:v",
                "1",
                "-q:v",
                "3",
                str(output),
            ]
        )
    finally:
        for leftover in tmp_dir.glob("*"):
            leftover.unlink(missing_ok=True)
        tmp_dir.rmdir()

    if not output.is_file() or output.stat().st_size == 0:
        raise ThumbnailError(f"ffmpeg produced no thumbnail for {video.name}.")

    log.info("Rendered thumbnail %s for %s.", output.name, video.name)
    return output


def thumbnail_path_for(video: Path) -> Path:
    """The conventional thumbnail path for an exported clip."""
    return Path(video).with_suffix(".jpg")
