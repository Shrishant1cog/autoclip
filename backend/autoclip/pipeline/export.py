"""Export stage — crop path plus captions plus audio normalisation to an MP4.

The whole render is a single ffmpeg pass. Per-shot crop segments are trimmed out
of the source, cropped independently, scaled to a common output size, and
concatenated in the filtergraph — which is what allows a wide two-shot and a
tight single to sit in one clip without a mid-stream frame-size change.
"""

from __future__ import annotations

import logging
import re
from collections.abc import Callable, Iterable
from dataclasses import dataclass, field
from pathlib import Path

from .. import resources
from ..config import ExportSettings
from ..system import report
from . import captions as captions_module
from . import ffmpeg
from .captions import CaptionStyle
from .reframe.croppath import CropPath, CropSegment, segment_crop_filter, series_expression
from .reframe.layout import LayoutPath, LayoutSlot
from .reframe.webcam import Rect, WebcamPath
from .speech_timeline import SpeechInterval
from .transcript import Word

log = logging.getLogger(__name__)

#: Output dimensions per aspect ratio. 1080-wide is the platform sweet spot:
#: high enough to avoid re-encode mush, low enough to upload quickly.
RATIOS: dict[str, tuple[int, int]] = {
    "9:16": (1080, 1920),
    "1:1": (1080, 1080),
    "16:9": (1920, 1080),
}

#: The colour behind a layout that does not fill the frame. The same near-
#: black the rest of the app uses, so a rendered clip sits on the page
#: rather than in a letterbox of someone else's brand.
CANVAS_COLOR = "0x101014"

#: How much the blurred background is softened when a layout leaves a gap.
BACKGROUND_BLUR = 24

#: Loudness targets. -14 LUFS integrated with -1.5 dBTP is what every major
#: platform normalises toward, so hitting it ourselves avoids their processing.
LOUDNESS_TRUE_PEAK = -1.5
LOUDNESS_RANGE = 11.0

#: The audio bitrate of the exported file.
#:
#: 128 kbps is the documented maximum for an Instagram Reel and the
#: recommended minimum for a YouTube upload, so one value serves both.
#: FFmpeg's AAC encoder lands just under the target — around 127 kbps
#: measured — which leaves the file inside the limit.
AUDIO_BITRATE = "128k"
AUDIO_SAMPLE_RATE = 48_000


class ExportError(RuntimeError):
    """Rendering a clip failed."""


@dataclass
class ExportRequest:
    source: Path
    destination: Path
    start_s: float
    end_s: float
    crop_path: CropPath
    words: list[Word]
    style: CaptionStyle
    ratio: str = "9:16"
    burn_captions: bool = True
    #: The speech intervals inside this clip, in clip-relative milliseconds.
    #: They come from the shared speech timeline, so the music ducking and the
    #: webcam layout agree on when someone is speaking.
    #:
    #: The three states are different answers, and the difference matters:
    #:
    #: * **None** — there is no timeline to follow, so the ducking falls back
    #:   to keying on the audio itself.
    #: * **An empty list** — the timeline was consulted and found no speech
    #:   in this clip, so the bed is not ducked at all.
    #: * **A non-empty list** — the speech in this clip.
    #:
    #: ``speech_timeline.ducking_intervals()`` produces the right one of the
    #: three; use it rather than slicing the timeline by hand.
    speech_intervals: list[SpeechInterval] | None = None
    #: The planned composition. None means "no webcam layout", which is the
    #: plain crop path this project has always used.
    layout: LayoutPath | None = None

    @property
    def duration_s(self) -> float:
        return self.end_s - self.start_s


def ratio_dimensions(ratio: str) -> tuple[int, int]:
    if ratio not in RATIOS:
        raise ExportError(f"Unknown ratio {ratio!r}. Available: {', '.join(RATIOS)}")
    return RATIOS[ratio]


def slugify_title(title: str, *, max_length: int = 50) -> str:
    """Filename-safe slug for a clip title."""
    slug = re.sub(r"[^\w\s-]", "", title, flags=re.UNICODE).strip().lower()
    slug = re.sub(r"[\s_-]+", "-", slug).strip("-")
    return slug[:max_length] or "clip"


def output_filename(title: str, ratio: str, *, suffix: str | None = None) -> str:
    """The file name for an exported clip.

    ``suffix`` distinguishes two clips whose titles slug to the same name.
    """
    stem = slugify_title(title)
    if suffix:
        stem = f"{stem}-{suffix}"
    return f"{stem}_{ratio.replace(':', 'x')}.mp4"


def unique_output_filename(
    title: str,
    ratio: str,
    *,
    rank: int,
    sibling_titles: Iterable[str],
) -> str:
    """A file name that is unique among the clips of one job.

    The model chooses the titles, and two clips of the same video can end up
    with the same one. The exports of a job live in one directory, so a name
    built from the title alone lets the second export overwrite the first:
    the clip is gone, and its subtitles with it. That is not a hypothetical —
    a real run produced two clips called "The language of love in videos",
    and the second export replaced the first.

    When the title is not shared, the name is the plain one: the user's own
    words are the best file name there is. When it is shared, the clip's
    rank is added — the rank is unique within the job, and the pipeline and
    the re-export both know it.
    """
    slug = slugify_title(title)
    shared = sum(1 for other in sibling_titles if slugify_title(other) == slug)
    if shared > 1:
        return output_filename(title, ratio, suffix=str(rank))
    return output_filename(title, ratio)


# --------------------------------------------------------------------------
# Filtergraph construction
# --------------------------------------------------------------------------


@dataclass(frozen=True)
class Composition:
    """How the webcam and the gameplay sit together in the render.

    Everything here is in output pixels, except ``webcam_source`` and
    ``webcam_path``, which are in the source video.
    """

    #: Where the gameplay goes. The crop path is scaled to this.
    gameplay_slot: LayoutSlot
    #: Where the webcam is drawn. None means there is no webcam.
    webcam_slot: LayoutSlot | None = None
    #: Which part of the source the webcam comes from.
    webcam_source: Rect | None = None
    #: Where the webcam's own frame was, over time. When it is here the
    #: crop follows the frame rather than sitting on one fixed rectangle,
    #: because a streamer changes the size of their webcam mid-clip.
    webcam_path: WebcamPath | None = None
    #: When the webcam is on screen, in clip-relative seconds.
    spans: list[tuple[float, float]] = field(default_factory=list)
    #: When the webcam is drawn larger, in clip-relative seconds. These come
    #: from the shared speech timeline.
    emphasis: list[tuple[float, float]] = field(default_factory=list)
    #: How much larger the webcam is drawn during speech.
    gain: float = 0.0


def composition_from_layout(layout: LayoutPath | None) -> Composition | None:
    """Pull the render facts out of a layout plan.

    The gameplay area is the same for the whole clip: the crop path is built
    for it, and a mid-clip change of size is not something one filtergraph
    can express. The webcam's *presence* does vary, and that is carried by
    the overlay's ``enable`` expression.
    """
    if layout is None:
        return None

    with_webcam = [segment for segment in layout.segments if segment.webcam_slot is not None]
    if not with_webcam:
        return None

    first = with_webcam[0]
    spans: list[tuple[float, float]] = []
    emphasis: list[tuple[float, float]] = []
    path: WebcamPath | None = None
    for segment in layout.segments:
        if segment.webcam_slot is None:
            continue
        spans.append((segment.start_s, segment.end_s))
        emphasis.extend(segment.speech_spans)
        if path is None and segment.webcam_path is not None:
            path = segment.webcam_path

    return Composition(
        gameplay_slot=first.gameplay_slot,
        webcam_slot=first.webcam_slot,
        webcam_source=first.webcam_source,
        webcam_path=path,
        spans=spans,
        emphasis=emphasis,
        gain=first.emphasis_gain,
    )


def build_video_filtergraph(
    request: ExportRequest,
    *,
    subtitle_name: str | None,
    fonts_name: str = "fonts",
) -> str:
    """Build the ``-filter_complex`` video chain for one clip."""
    out_w, out_h = ratio_dimensions(request.ratio)
    segments = request.crop_path.segments
    if not segments:
        raise ExportError("The crop path has no segments.")

    composition = composition_from_layout(request.layout)
    gameplay_slot = composition.gameplay_slot if composition else None
    target_w = gameplay_slot.width if gameplay_slot else out_w
    target_h = gameplay_slot.height if gameplay_slot else out_h

    parts: list[str] = []
    labels: list[str] = []

    # Each segment trims its own copy of the source, and each webcam segment
    # trims its own copy too — so the source is split once per consumer.
    #
    # A filter output may be consumed only once. ffmpeg 9 tolerates naming the
    # same output twice; ffmpeg 7 refuses it with "Invalid stream specifier",
    # and the export then fails on every strict ffmpeg for any clip whose
    # crop path has more than one segment. The split is what makes the graph
    # valid everywhere, and it costs one output per consumer.
    #
    # The copies are named apart from the chains that consume them: a chain
    # that read and wrote the same label would be ambiguous, and a label may
    # not be reused either.
    needs_webcam = composition is not None and composition.webcam_slot is not None
    game_sources = [f"[gsrc{index}]" for index in range(len(segments))]
    web_sources = [f"[wsrc{index}]" for index in range(len(segments))] if needs_webcam else []

    if len(segments) == 1 and not needs_webcam:
        # One segment, one consumer: the input is used as it is.
        game_sources = ["[0:v]"]
    else:
        split_labels = game_sources + web_sources
        parts.append(f"[0:v]split={len(split_labels)}{''.join(split_labels)}")

    for index, segment in enumerate(segments):
        label = f"v{index}"
        labels.append(f"[{label}]")

        if len(segments) == 1:
            # No trim needed; the input is already seeked to the clip.
            source_label = game_sources[0]
            prefix = ""
        else:
            source_label = f"[s{index}]"
            prefix = (
                f"{game_sources[index]}trim=start={segment.start_s:.4f}:end={segment.end_s:.4f},"
                f"setpts=PTS-STARTPTS{source_label}"
            )
            parts.append(prefix)

        if segment.fit:
            parts.extend(
                _fit_chain(
                    source_label,
                    index,
                    target_w,
                    target_h,
                    pre=_fit_pre_crop(segment, request.crop_path),
                )
            )
            continue

        chain = [segment_crop_filter(segment)]
        if segment.zoom > 0:
            chain.append(_zoom_filter(segment.zoom, target_w, target_h))
        chain.append(f"scale={target_w}:{target_h}:flags=lanczos")
        chain.append("setsar=1,format=yuv420p")

        parts.append(f"{source_label}{','.join(chain)}[{label}]")

    if len(segments) == 1:
        current = "[v0]"
    else:
        parts.append(f"{''.join(labels)}concat=n={len(segments)}:v=1:a=0[vcat]")
        current = "[vcat]"

    if composition is not None and composition.webcam_slot is not None:
        current = _compose_with_webcam(
            parts,
            current=current,
            composition=composition,
            segments=segments,
            web_sources=web_sources,
            out_w=out_w,
            out_h=out_h,
        )

    if request.burn_captions and subtitle_name is not None:
        # Bare relative names — ffmpeg runs with its cwd set to the render
        # workspace, so there is nothing here that needs escaping.
        parts.append(f"{current}ass=filename={subtitle_name}:fontsdir={fonts_name}[vout]")
    else:
        parts.append(f"{current}null[vout]")

    return ";".join(parts)


def _compose_with_webcam(
    parts: list[str],
    *,
    current: str,
    composition: Composition,
    segments: list[CropSegment],
    web_sources: list[str],
    out_w: int,
    out_h: int,
) -> str:
    """Put the webcam on top of the gameplay, and return the new label.

    The gameplay is scaled to its slot and the rest of the frame is filled
    with a blurred copy of itself — the same treatment the wide-shot
    fallback already uses, so a layout never produces plain black bars.
    """
    gameplay = composition.gameplay_slot
    webcam = composition.webcam_slot
    webcam_source = composition.webcam_source
    if webcam is None or webcam_source is None:
        return current

    # -- the gameplay, placed in its slot --------------------------------
    fills_frame = (
        gameplay.width == out_w and gameplay.height == out_h and gameplay.x == 0 and gameplay.y == 0
    )
    if fills_frame:
        parts.append(f"{current}null[laycanvas]")
    else:
        parts.append(f"{current}split=2[laybg][layfg]")
        parts.append(
            f"[laybg]scale={out_w}:{out_h}:force_original_aspect_ratio=increase,"
            f"crop={out_w}:{out_h},boxblur={BACKGROUND_BLUR}:2[laybgfull]"
        )
        parts.append(f"[layfg]scale={gameplay.width}:{gameplay.height}:flags=lanczos[layfg2]")
        parts.append(f"[laybgfull][layfg2]overlay=x={gameplay.x}:y={gameplay.y}[laycanvas]")

    # -- the webcam, cut from the same source ----------------------------
    parts.extend(
        _webcam_branch(
            composition=composition,
            segments=segments,
            web_sources=web_sources,
        )
    )

    enable = _presence_expression(composition.spans)
    parts.append(f"[laycanvas][laycam]overlay=x={webcam.x}:y={webcam.y}:enable='{enable}'[layout]")
    return "[layout]"


def _webcam_branch(
    *,
    composition: Composition,
    segments: list[CropSegment],
    web_sources: list[str],
) -> list[str]:
    """Cut the webcam region out of the source and scale it into its slot.

    The trims mirror the gameplay's, so the webcam stays in step with the
    clip even when the crop path has several segments.

    Each trim reads its own copy of the source: a filter output may be
    consumed only once, so the copies are made by the split in
    :func:`build_video_filtergraph` rather than by naming one output twice.

    The crop and the scale are applied once, to the joined webcam stream,
    rather than to every segment. They are per-frame operations, so the
    picture is the same — but the filter graph no longer grows with the
    number of segments, and the emphasis expression is evaluated against the
    clip's own timeline, which is the timeline the speech stretches are
    written in.
    """
    webcam = composition.webcam_slot
    if webcam is None:
        return []

    parts: list[str] = []

    if len(segments) == 1:
        current = web_sources[0]
    else:
        labels: list[str] = []
        for index, segment in enumerate(segments):
            label = f"ws{index}"
            labels.append(f"[{label}]")
            parts.append(
                f"{web_sources[index]}trim=start={segment.start_s:.4f}:end={segment.end_s:.4f},"
                f"setpts=PTS-STARTPTS[{label}]"
            )
        parts.append(f"{''.join(labels)}concat=n={len(segments)}:v=1:a=0[wcat]")
        current = "[wcat]"

    crop = _webcam_crop_filter(composition)
    parts.append(f"{current}{crop},{_webcam_scale_filter(composition)}[laycam]")
    return parts


def _webcam_scale_filter(composition: Composition) -> str:
    """The scale that puts the cropped webcam into its slot.

    While somebody is speaking the webcam is drawn a little larger. The
    zoom is done by the scale rather than by the crop when the crop is
    following a path: the window the crop takes is then the webcam's own
    frame, and making it smaller would show the inside of the streamer's
    background rather than their face.

    The zoom follows the speech, so it has to be worked out **per frame**.
    ffmpeg works a scale's width and height out once, when the graph is
    built, and ``t`` — the clock the speech is written against — is not a
    valid thing to ask for there: *"Expressions with frame variables 'n',
    't', 'pos' are not valid in init eval_mode."* ``eval=frame`` says to
    work it out on every frame instead. The frame is then larger than the
    slot, and the crop that follows takes the middle of it, so the face
    stays in the middle of the strip while the picture around it grows.
    """
    webcam = composition.webcam_slot
    if webcam is None:
        return "null"

    factor = None if _crop_carries_emphasis(composition) else _emphasis_factor(composition)
    if factor is None:
        return f"scale={webcam.width}:{webcam.height}:flags=lanczos"
    return (
        f"scale=w='{webcam.width}*({factor})':h='{webcam.height}*({factor})':"
        f"flags=lanczos:eval=frame,"
        f"crop={webcam.width}:{webcam.height}:"
        f"x='(iw-{webcam.width})/2':y='(ih-{webcam.height})/2'"
    )


def _crop_carries_emphasis(composition: Composition) -> bool:
    """True when the crop itself already magnifies the webcam during speech."""
    path = composition.webcam_path
    if path is not None and path.keyframes:
        # The path's crop keeps the webcam's own frame whole, so the zoom
        # has to happen in the scale instead.
        return False
    speech = _speech_term(composition.emphasis)
    return bool(speech) and composition.gain > 0


def _emphasis_factor(composition: Composition) -> str | None:
    """The expression for the emphasis factor, or ``None`` when there is none."""
    speech = _speech_term(composition.emphasis)
    if not speech or composition.gain <= 0:
        return None
    return f"1+{composition.gain:.4f}*({speech})"


def _webcam_crop_filter(composition: Composition) -> str:
    """The crop that takes the webcam region out of the source.

    When the webcam's own frame was measured over time, the crop follows
    it: the window moves with the frame, so a streamer who changes the size
    of their webcam is still framed correctly. The window keeps the size it
    had for most of the clip — a filter graph cannot change the size of its
    output halfway through — and it is kept inside the source.

    Without a path the crop is the region itself, and during speech the
    window is a little smaller, so the face is magnified when it is scaled
    up into the slot. The window stays centred on the region, and the scale
    that follows is a fixed size, so the overlay never has to be rebuilt
    while somebody is talking.
    """
    webcam_source = composition.webcam_source
    if webcam_source is None:
        return "null"

    path = composition.webcam_path
    if path is not None and path.keyframes:
        return _webcam_path_crop_filter(path)

    source_w = _even(webcam_source.width)
    source_h = _even(webcam_source.height)
    x = int(webcam_source.x)
    y = int(webcam_source.y)

    speech = _speech_term(composition.emphasis)
    if not speech or composition.gain <= 0:
        return f"crop={source_w}:{source_h}:{x}:{y}"

    factor = f"(1+{composition.gain:.4f}*({speech}))"
    width = f"floor({source_w}/{factor}/2)*2"
    height = f"floor({source_h}/{factor}/2)*2"
    # The offset is spelled out rather than taken from `out_w`, because ffmpeg
    # does not update `out_w` when the width is an expression: it would keep
    # the window still while somebody is speaking. The speech expression is
    # therefore written out four times here — once for the width, once for
    # the height, and once in each offset. That is affordable because the
    # crop is built once for the whole clip, not once per segment.
    crop_x = f"{x}+({source_w}-{width})/2"
    crop_y = f"{y}+({source_h}-{height})/2"
    return f"crop=w='{width}':h='{height}':x='{crop_x}':y='{crop_y}'"


def _webcam_path_crop_filter(path: WebcamPath) -> str:
    """The crop that follows the webcam's own frame over time.

    The window is as big as the frame was for most of the clip, and its
    centre follows the frame's centre. The position is clamped to the
    source, so a frame that runs off the edge of the picture gives a window
    that stops at the edge rather than one that runs off it.
    """
    width = _even(path.width)
    height = _even(path.height)

    limit_x = max(0, path.source_width - width)
    limit_y = max(0, path.source_height - height)

    x_expression = series_expression(
        [(keyframe.t, keyframe.cx - width / 2) for keyframe in path.keyframes]
    )
    y_expression = series_expression(
        [(keyframe.t, keyframe.cy - height / 2) for keyframe in path.keyframes]
    )

    # The commas inside the expressions are escaped, because the filtergraph
    # parser would otherwise read them as separators.
    x_expression = f"max(0\\,min({x_expression}\\,{limit_x}))"
    y_expression = f"max(0\\,min({y_expression}\\,{limit_y}))"
    return f"crop=w={width}:h={height}:x='{x_expression}':y='{y_expression}'"


def _even(value: float) -> int:
    number = int(value)
    if number % 2:
        number -= 1
    return max(2, number)


def _presence_expression(spans: list[tuple[float, float]]) -> str:
    """When the webcam is on screen."""
    if not spans:
        return "0"
    terms = [f"between(t,{start:.4f},{end:.4f})" for start, end in spans if end > start]
    if not terms:
        return "0"
    if len(terms) == 1:
        return terms[0]
    return "+".join(terms)


def _speech_term(spans: list[tuple[float, float]]) -> str:
    """An ffmpeg expression that is 1 while someone is speaking.

    The intervals come from the shared speech timeline, so the webcam
    emphasis and the music ducking agree about when somebody is talking.
    """
    terms = [f"between(t,{start:.4f},{end:.4f})" for start, end in spans if end > start]
    if not terms:
        return ""
    if len(terms) == 1:
        return terms[0]
    return "+".join(terms)


def _fit_pre_crop(segment: CropSegment, crop_path: CropPath) -> str:
    """The crop that runs before a fitted frame is scaled into its slot.

    A fitted frame is the whole source, and the whole source holds the
    webcam. When the plan has already taken the webcam out of the fitted
    frame, the crop is applied here so the webcam is not shown twice.
    """
    source_w = crop_path.source_width
    source_h = crop_path.source_height
    if segment.width >= source_w and segment.height >= source_h:
        return ""
    first = segment.keyframes[0] if segment.keyframes else None
    x = int(first.x) if first is not None else 0
    y = int(first.y) if first is not None else 0
    return f"crop={segment.width}:{segment.height}:{x}:{y},"


def _fit_chain(
    source_label: str, index: int, out_w: int, out_h: int, *, pre: str = ""
) -> list[str]:
    """Fit the whole frame into the output over a blurred copy of itself.

    Used when the subjects are spread wider than any crop can hold. Plain black
    bars would be honest but look cheap on a phone; a blurred fill is what
    viewers are used to seeing and keeps the frame full-bleed.

    ``pre`` is a chain that runs before the split — the crop that keeps a
    webcam out of the fitted frame, for instance.
    """
    return [
        f"{source_label}{pre}split=2[fitbg{index}][fitfg{index}]",
        (
            f"[fitbg{index}]scale={out_w}:{out_h}:force_original_aspect_ratio=increase,"
            f"crop={out_w}:{out_h},boxblur=24:2[bg{index}]"
        ),
        (
            f"[fitfg{index}]scale={out_w}:{out_h}:force_original_aspect_ratio=decrease:"
            f"flags=lanczos[fg{index}]"
        ),
        (f"[bg{index}][fg{index}]overlay=(W-w)/2:(H-h)/2,setsar=1,format=yuv420p[v{index}]"),
    ]


def _zoom_filter(zoom: float, out_w: int, out_h: int) -> str:
    """A slow push-in over the segment.

    Uses ``zoompan``, which is the only filter that can change apparent scale
    while holding a fixed output size. Off by default — at very small
    increments it can step visibly, and a locked frame beats a stuttering one.
    """
    end_zoom = 1.0 + zoom
    return f"zoompan=z='min(zoom+{zoom / 240:.6f},{end_zoom:.4f})':d=1:s={out_w}x{out_h}:fps=30"


def build_audio_filtergraph(settings: ExportSettings) -> str:
    """Speech-only loudness normalisation (no music bed configured)."""
    return f"loudnorm=I={settings.loudness_lufs}:TP={LOUDNESS_TRUE_PEAK}:LRA={LOUDNESS_RANGE}"


def _ducking_expression(
    start_s: float, end_s: float, floor: float, attack_s: float, release_s: float
) -> str:
    """An FFmpeg expression for the ducking gain over one speech interval.

    The shape is a smooth attack, a hold at the ducked level, and a smooth
    recovery that finishes *at* the end of the interval. A merged interval
    therefore recovers exactly once, no matter how many words it contains,
    and the gain is back at 1.0 by the time the filter is switched off — so
    there is no click at the boundary.

    An interval shorter than the attack and the release together gets a
    triangle: down over the first half, up over the second. It still starts
    and ends at 1.0.
    """
    total = max(1e-6, end_s - start_s)
    half = total / 2.0
    attack_end = start_s + min(attack_s, half)
    release_start = max(attack_end, end_s - min(release_s, half))
    # The recovery completes exactly at the interval's end.
    span = max(1e-6, end_s - release_start)

    if release_start <= attack_end + 1e-6:
        # The interval is shorter than the attack and the release together:
        # a single triangle is the honest shape.
        return (
            f"if(lt(t,{attack_end:.4f}),"
            f"1+({floor:.6f}-1)*(t-{start_s:.4f})/{max(1e-6, attack_end - start_s):.4f},"
            f"{floor:.6f}+(1-{floor:.6f})*(t-{release_start:.4f})/{span:.4f})"
        )

    return (
        f"if(lt(t,{attack_end:.4f}),"
        f"1+({floor:.6f}-1)*(t-{start_s:.4f})/{attack_s:.4f},"
        f"if(lt(t,{release_start:.4f}),"
        f"{floor:.6f},"
        f"{floor:.6f}+(1-{floor:.6f})*(t-{release_start:.4f})/{span:.4f}))"
    )


def build_ducking_filters(
    intervals: list[SpeechInterval],
    *,
    duck_db: float,
    attack_ms: int,
    release_ms: int,
) -> list[str]:
    """One ``volume`` filter per speech interval, chained onto the bed.

    Each filter is enabled only inside its own interval, so the filters do
    not interfere with each other and the chain stays flat - no nesting, no
    expression parser depth to worry about.
    """
    floor = 10 ** (duck_db / 20.0)
    attack_s = max(0.001, attack_ms / 1000.0)
    release_s = max(0.001, release_ms / 1000.0)

    filters: list[str] = []
    for interval in intervals:
        start_s = interval.start_ms / 1000.0
        end_s = interval.end_ms / 1000.0
        if end_s <= start_s:
            continue
        expression = _ducking_expression(start_s, end_s, floor, attack_s, release_s)
        filters.append(
            f"volume=volume='{expression}':eval=frame:enable='between(t,{start_s:.4f},{end_s:.4f})'"
        )
    return filters


@dataclass
class MixedAudio:
    """The pieces of the mixed-audio graph.

    A typed result rather than a dict, so the caller cannot pick up a value
    of the wrong shape without the type checker noticing.
    """

    #: The ``filter_complex`` string for the ffmpeg invocation.
    filter_complex: str
    #: The audio output label to map.
    map: str
    #: Extra input arguments for the music file.
    input_args: list[str]


def build_mixed_audio_filtergraph(
    settings: ExportSettings,
    music_path: Path,
    duration_s: float,
    speech_intervals: list[SpeechInterval] | None = None,
) -> MixedAudio:
    """Filter graph mixing a music bed under the speech, with optional ducking.

    Returns the pieces the ffmpeg invocation needs: the ``filter_complex``
    string, the audio output label to map, and extra input arguments. Speech
    drives a sidechain compressor over the bed when ducking is on — the
    classic "background drops when someone talks" behaviour. Loudness
    normalisation applies to the speech chain before the mix; the bed sits at
    ``music_volume`` of full scale, dropping by ``ducking_amount_db`` while
    speech is detected.

    Input layout: ``[0:a]`` is the speech (the source clip) and ``[1:a]`` is
    the music. The music is opened with ``-stream_loop -1`` so it covers clips
    longer than the track, then trimmed to the clip duration.

    When a **shared speech timeline** is supplied, the ducking follows it
    instead of keying on the audio: the bed's volume is shaped by an explicit
    envelope built from the same intervals the webcam layout uses. That is
    what keeps the two in agreement, and it is what stops the bed recovering
    between two words the transcript considers one stretch of speech.

    Only the bed is ever touched. The original voice and game audio go
    through the same chain whether or not there is music.
    """
    vol = min(max(settings.music_volume, 0.0), 1.0)
    duck_db = max(min(settings.ducking_amount_db, 0.0), -60.0)
    # Convert dB to a linear threshold for sidechaincompress (1.0 = no drop).
    duck_linear = 10 ** (duck_db / 20)
    duration = max(duration_s, 0.001)

    # Speech: loudness-normalise first, then it doubles as the ducking key.
    speech = (
        f"[0:a]loudnorm=I={settings.loudness_lufs}:TP={LOUDNESS_TRUE_PEAK}:LRA={LOUDNESS_RANGE}[sp]"
    )
    # Bed: trim to the clip, level it, format to match the speech for the mix.
    #
    # The chain carries **no output label**. A label ends a filter chain, so
    # a labelled bed followed by the ducking filters would leave the bed's
    # output unconnected and ffmpeg would refuse the whole graph. The label
    # is added where the bed is used instead.
    bed = (
        f"[1:a]atrim=0:{duration:.4f},asetpts=PTS-STARTPTS,"
        f"volume={vol:.3f},aformat=sample_rates={AUDIO_SAMPLE_RATE}:channel_layouts=stereo"
    )

    music_args = ["-stream_loop", "-1", "-i", str(music_path)]

    if not settings.music_ducking:
        complex_filter = (
            f"{speech};{bed}[bed];"
            f"[sp][bed]amix=inputs=2:duration=first:dropout_transition=0:normalize=0[aout]"
        )
        return MixedAudio(
            filter_complex=complex_filter,
            map="[aout]",
            input_args=music_args,
        )

    if speech_intervals is not None:
        # The timeline drives the ducking: an explicit envelope on the bed.
        filters = build_ducking_filters(
            speech_intervals,
            duck_db=duck_db,
            attack_ms=settings.ducking_attack_ms,
            release_ms=settings.ducking_release_ms,
        )
        if filters:
            bed_chain = ",".join([bed, *filters]) + "[bed]"
            complex_filter = (
                f"{speech};{bed_chain};"
                f"[sp][bed]amix=inputs=2:duration=first:dropout_transition=0:normalize=0[aout]"
            )
            return MixedAudio(
                filter_complex=complex_filter,
                map="[aout]",
                input_args=music_args,
            )

        # The timeline was consulted and found no speech in this clip. There
        # is nothing to duck under, so the bed plays at full level — the
        # same graph the ducking-off path builds.
        #
        # This is not the same answer as "there is no timeline". A timeline
        # that was never built knows nothing, and falls back to the
        # compressor below; a timeline that found nothing knows that this
        # clip has no talking, and the bed should not be pulled down by
        # whatever else the source happens to contain.
        complex_filter = (
            f"{speech};{bed}[bed];"
            f"[sp][bed]amix=inputs=2:duration=first:dropout_transition=0:normalize=0[aout]"
        )
        return MixedAudio(
            filter_complex=complex_filter,
            map="[aout]",
            input_args=music_args,
        )

    # No timeline: fall back to keying the ducking on the audio itself.
    #
    # The speech is split into two copies — one for the mix and one to key
    # the compressor — and both are put on the bed's channel layout first.
    # Two things make the explicit split necessary rather than decorative:
    #
    # * a filter output may be consumed only **once** in an ffmpeg
    #   filtergraph, so naming `[sp]` as both the sidechain key and the
    #   mix input is refused outright by some builds ("Invalid stream
    #   specifier: sp");
    # * `sidechaincompress` needs both of its inputs on the same channel
    #   layout, and the bed is stereo whether or not the source is.
    #
    # Newer ffmpeg builds accept the label being reused, which is exactly
    # why this stayed hidden: it renders on the machine it was written on
    # and fails on an older one.
    complex_filter = (
        f"{speech};"
        f"[sp]aformat=sample_rates={AUDIO_SAMPLE_RATE}:channel_layouts=stereo,"
        f"asplit=2[sp_mix][sp_key];"
        f"{bed}[bed];"
        # Bed ducks while speech plays; attack/release keep it musical.
        f"[bed][sp_key]sidechaincompress=threshold={duck_linear:.4f}:ratio=8:"
        f"attack=120:release=600:makeup=1[ducked];"
        f"[sp_mix][ducked]amix=inputs=2:duration=first:dropout_transition=0:normalize=0[aout]"
    )
    return MixedAudio(
        filter_complex=complex_filter,
        map="[aout]",
        input_args=music_args,
    )


def _source_has_audio(path: Path) -> bool:
    """Whether the clip source has an audio stream.

    When it does not, there is no speech for ducking to key on and no main
    input to mix into — adding a bed would fail the render. Assume audio when
    probing fails, matching the pre-music behaviour.
    """
    try:
        return ffmpeg.probe(path).has_audio
    except Exception:  # noqa: BLE001 - probe failure must not break export
        log.debug("Could not probe %s for audio; assuming present.", path, exc_info=True)
        return True


def encoder_args(settings: ExportSettings, *, threads: int = 0) -> list[str]:
    """Pick the video encoder and its quality settings.

    NVENC is materially faster where available. Its quality knob is ``-cq``
    rather than ``-crf``, and the two scales are close enough that reusing the
    configured value keeps output consistent between machines.

    ``threads`` caps the encoder's worker threads. Left unset, libx264 spawns
    one per core, which is the right choice for a single render and the wrong
    one when a second ffmpeg is already running.
    """
    if settings.prefer_hardware_encoder and report().ffmpeg.nvenc_works:
        args = [
            "-c:v",
            "h264_nvenc",
            "-preset",
            "p5",
            "-rc",
            "vbr",
            "-cq",
            str(settings.crf),
            "-b:v",
            "0",
            "-profile:v",
            "high",
        ]
    else:
        args = [
            "-c:v",
            "libx264",
            "-preset",
            "medium",
            "-crf",
            str(settings.crf),
            "-profile:v",
            "high",
        ]
    if threads and threads > 0:
        args += ["-threads", str(threads)]
    return args


# --------------------------------------------------------------------------
# Rendering
# --------------------------------------------------------------------------


def export_clip(
    request: ExportRequest,
    *,
    work_dir: Path,
    settings: ExportSettings | None = None,
    on_progress: Callable[[float], None] | None = None,
    cancelled: Callable[[], bool] | None = None,
    threads: int = 0,
    usage: resources.Usage | None = None,
) -> Path:
    """Render one clip to an MP4 and return the output path.

    Preconditions:
        request.source exists; request.crop_path segments span the clip duration
        in clip-relative seconds.
    """
    settings = settings or ExportSettings()
    out_w, out_h = ratio_dimensions(request.ratio)

    # Each clip renders in its own workspace so concurrent exports can't collide
    # on the shared `captions.ass` name that the relative-path scheme requires.
    workspace = work_dir / request.destination.stem
    workspace.mkdir(parents=True, exist_ok=True)

    subtitle_name: str | None = None
    fonts_name = "fonts"
    render_cwd: Path | None = None

    if request.burn_captions and request.words:
        ass_path = captions_module.write_ass(
            workspace / "captions.ass",
            request.words,
            request.style,
            width=out_w,
            height=out_h,
            time_offset_s=request.start_s,
        )
        render_cwd, subtitle_name, fonts_name = ffmpeg.relative_filter_workspace(
            ass_path, captions_module.FONT_DIR
        )

    filtergraph = build_video_filtergraph(
        request, subtitle_name=subtitle_name, fonts_name=fonts_name
    )

    request.destination.parent.mkdir(parents=True, exist_ok=True)

    # Optional music bed (Phase 8). A missing/misconfigured track degrades to
    # the plain speech graph rather than failing the export. The video graph
    # reads input 0; the music becomes input 1, so the mixed audio graph is
    # rewritten to read speech from input 1 as well.
    music_input_args: list[str] = []
    music_map = "0:a?"
    audio_filter_args: list[str] = ["-af", build_audio_filtergraph(settings)]
    if settings.music_track and _source_has_audio(request.source):
        from ..music import library as music_library
        from . import music as music_module

        track = music_module.resolve_track(settings.music_track)
        if track is not None:
            # The licence gate: a track whose rights are unknown, incompatible
            # or expired is not mixed in. The export stops with an
            # explanation rather than shipping a clip the user may not have
            # the right to publish.
            music_library.check_export_allowed_for_path(track)

            mixed = build_mixed_audio_filtergraph(
                settings,
                track,
                request.duration_s,
                request.speech_intervals,
            )
            filtergraph = f"{filtergraph};{mixed.filter_complex}"
            music_input_args = mixed.input_args
            music_map = mixed.map
            audio_filter_args = []
            log.info(
                "Mixing music bed %s (volume=%.2f, ducking=%s)",
                track.name,
                settings.music_volume,
                settings.music_ducking,
            )

    # Input and output paths are ordinary argv arguments, so they stay absolute
    # and need no escaping regardless of the working directory.
    args = [
        # Seeking before -i decodes from the nearest keyframe and is far faster
        # than an output-side seek; modern ffmpeg keeps it frame-accurate.
        "-ss",
        f"{request.start_s:.4f}",
        "-t",
        f"{request.duration_s:.4f}",
        "-i",
        str(request.source),
        *music_input_args,
        "-filter_complex",
        filtergraph,
        "-map",
        "[vout]",
        "-map",
        music_map,
    ]
    args.extend(audio_filter_args)
    args.extend(
        [
            *encoder_args(settings, threads=threads),
            "-pix_fmt",
            "yuv420p",
            "-c:a",
            "aac",
            "-b:a",
            AUDIO_BITRATE,
            "-ar",
            str(AUDIO_SAMPLE_RATE),
            "-movflags",
            "+faststart",
            # Meta documents that a Reel must carry no edit lists, and
            # ffmpeg's MP4 muxer writes one by default. Turning it off
            # costs nothing and makes the exported file acceptable to
            # Instagram without a second encode.
            "-use_editlist",
            "0",
            str(request.destination),
        ]
    )

    try:
        ffmpeg.run(
            args,
            total_duration_s=request.duration_s,
            on_progress=on_progress,
            cancelled=cancelled,
            cwd=render_cwd,
            threads=threads,
            usage=usage,
        )
    except ffmpeg.FFmpegError as exc:
        raise ExportError(f"Could not render {request.destination.name}.\n{exc}") from exc

    if not request.destination.exists() or request.destination.stat().st_size == 0:
        raise ExportError(f"ffmpeg reported success but {request.destination.name} is empty.")

    if usage is not None:
        usage.export_bytes += request.destination.stat().st_size

    if settings.write_srt and request.words:
        captions_module.write_srt(
            request.destination.with_suffix(".srt"),
            request.words,
            time_offset_s=request.start_s,
        )

    log.info(
        "Exported %s (%.1fs, %s)",
        request.destination.name,
        request.duration_s,
        request.ratio,
    )
    return request.destination
