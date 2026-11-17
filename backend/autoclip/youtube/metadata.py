"""AI-written YouTube metadata for an exported clip.

The prompt is fed the clip's own subtitle text, its working title, and the
reason the model picked it. The reply is treated as untrusted input: every
field is length-checked and sanitised before it reaches YouTube, and a failure
falls back to deterministic metadata built from the clip rather than blocking
the upload.
"""

from __future__ import annotations

import json
import logging
import re
from dataclasses import dataclass, field

from ..pipeline.transcript import Word
from ..providers.base import LLMProvider, ProviderError, extract_json_object

log = logging.getLogger(__name__)

TITLE_LIMIT = 100
DESCRIPTION_LIMIT = 5000
TAGS_CHAR_BUDGET = 450
MAX_TRANSCRIPT_CHARS = 6000
#: Clips this long or shorter can surface in YouTube's Shorts feed.
SHORTS_MAX_S = 180

SYSTEM_PROMPT = """You write YouTube metadata for short vertical clips.
Reply with ONE JSON object and nothing else. Never invent facts that are not in
the transcript. Match the language of the transcript. No clickbait that the
clip does not deliver, no all-caps shouting, no emoji spam."""

USER_TEMPLATE = """Write the upload metadata for this clip.

Working title: {title}
Why it was chosen: {reason}
Hook line: {hook}
Duration: {duration:.0f} seconds
Transcript language: {language}
{shorts_note}
Transcript of the clip:
---
{transcript}
---

Return JSON with exactly these keys:
{{
  "title": "at most 100 characters, front-load the hook",
  "description": "1-2 sentences summarising the moment, then a blank line, then 3-5 hashtags",
  "tags": ["8", "to", "12", "lowercase", "keywords", "without", "hash", "symbols"]
}}
{shorts_rule}"""


@dataclass
class ClipMetadata:
    title: str
    description: str
    tags: list[str] = field(default_factory=list)


async def generate_metadata(
    provider: LLMProvider,
    *,
    title: str,
    hook: str,
    reason: str,
    words: list[Word],
    duration_s: float,
    language: str = "",
) -> ClipMetadata:
    """Ask the model for metadata, falling back to a local template on failure."""
    transcript = " ".join(word.text for word in words).strip()
    short = duration_s <= SHORTS_MAX_S
    prompt = USER_TEMPLATE.format(
        title=title or "Untitled clip",
        reason=reason or "A self-contained moment.",
        hook=hook or "",
        duration=duration_s,
        language=language or "unknown",
        shorts_note=(
            "This is a Short: include #Shorts in the hashtag line."
            if short
            else "This is longer than a Short: do not use #Shorts."
        ),
        transcript=transcript[:MAX_TRANSCRIPT_CHARS],
        shorts_rule=(
            'The description hashtag line must include "#Shorts".'
            if short
            else "Do not mention Shorts in the title, description, or tags."
        ),
    )

    try:
        raw = await provider.generate_text(SYSTEM_PROMPT, prompt, temperature=0.5)
        payload = extract_json_object(raw)
    except (ProviderError, ValueError, json.JSONDecodeError) as exc:
        log.warning("Metadata generation failed (%s); using the fallback.", exc)
        return fallback_metadata(
            title=title, hook=hook, reason=reason, words=words, duration_s=duration_s
        )

    return sanitize_metadata(
        payload, title=title, hook=hook, reason=reason, words=words, duration_s=duration_s
    )


def sanitize_metadata(
    payload: dict,
    *,
    title: str,
    hook: str = "",
    reason: str = "",
    words: list[Word] | None = None,
    duration_s: float = 0.0,
) -> ClipMetadata:
    """Clamp a model reply to YouTube's limits, falling back field by field."""
    words = words or []
    fallback = fallback_metadata(
        title=title, hook=hook, reason=reason, words=words, duration_s=duration_s
    )

    raw_title = payload.get("title")
    clean_title = _clean_title(raw_title) if isinstance(raw_title, str) else ""
    if not clean_title:
        clean_title = fallback.title

    short = duration_s <= SHORTS_MAX_S

    raw_tags = payload.get("tags")
    tags = _clean_tags(raw_tags if isinstance(raw_tags, list) else [])
    if not tags:
        tags = fallback.tags
    if short and "shorts" not in {tag.lower() for tag in tags}:
        tags = _fit_tags([*tags, "shorts"])

    raw_description = payload.get("description")
    description = raw_description.strip() if isinstance(raw_description, str) else ""
    if not description:
        description = fallback.description
    description = _clean_description(description, tags=tags, short=short)

    return ClipMetadata(title=clean_title, description=description, tags=tags)


def fallback_metadata(
    *,
    title: str,
    hook: str = "",
    reason: str = "",
    words: list[Word] | None = None,
    duration_s: float = 0.0,
) -> ClipMetadata:
    """Deterministic metadata used when the model is unavailable or unusable."""
    words = words or []
    spoken = " ".join(word.text for word in words).strip()

    candidate_title = _clean_title(title)
    if not candidate_title and spoken:
        candidate_title = _clean_title(" ".join(spoken.split()[:12]))
    if not candidate_title:
        candidate_title = "Untitled clip"

    summary = (hook or reason or spoken).strip()
    if len(summary) > 400:
        summary = summary[:397].rstrip() + "…"

    # The clip's own title and hook describe the moment far better than the
    # transcript does, so their words lead the tag list and the transcript
    # only fills in the gaps.
    tags = _clean_tags(_keywords(f"{title} {hook} {reason}", limit=8) + _keywords(spoken, limit=12))
    if duration_s <= SHORTS_MAX_S:
        tags = _fit_tags([*tags, "shorts"])

    description = _clean_description(
        summary or "A self-contained moment from the full video.",
        tags=tags,
        short=duration_s <= SHORTS_MAX_S,
    )
    return ClipMetadata(title=candidate_title, description=description, tags=tags)


def _clean_title(value: str) -> str:
    title = " ".join(str(value).split()).strip().strip('"“”')
    if len(title) > TITLE_LIMIT:
        clipped = title[:TITLE_LIMIT].rsplit(" ", 1)[0].rstrip(" ,.;:-")
        title = clipped or title[:TITLE_LIMIT]
    return title


def _clean_description(value: str, *, tags: list[str], short: bool) -> str:
    description = value.strip()
    description = re.sub(r"\n{3,}", "\n\n", description)

    hashtags = " ".join(f"#{tag.replace(' ', '')}" for tag in tags[:5])
    needs_hashtags = "#" not in description
    if needs_hashtags and hashtags:
        description = f"{description}\n\n{hashtags}".strip()
    if short and "#shorts" not in description.lower():
        description = f"{description}\n\n#Shorts".strip()

    if len(description) > DESCRIPTION_LIMIT:
        description = description[: DESCRIPTION_LIMIT - 1].rstrip() + "…"
    return description


def _clean_tags(values: list) -> list[str]:
    tags: list[str] = []
    seen: set[str] = set()
    for value in values:
        if not isinstance(value, str):
            continue
        tag = value.strip().lstrip("#").strip().lower()
        tag = re.sub(r"[,;]+", " ", tag)
        tag = " ".join(tag.split())
        if not tag or len(tag) > 30 or tag in seen:
            continue
        seen.add(tag)
        tags.append(tag)
        if len(tags) >= 15:
            break
    return _fit_tags(tags)


def _fit_tags(tags: list[str]) -> list[str]:
    """Drop tags past YouTube's 500-character total."""
    fitted: list[str] = []
    used = 0
    for tag in tags:
        cost = len(tag) + (2 if fitted else 0)
        if used + cost > TAGS_CHAR_BUDGET:
            continue
        fitted.append(tag)
        used += cost
    return fitted


def _keywords(text: str, *, limit: int) -> list[str]:
    stop = {
        "the",
        "and",
        "for",
        "you",
        "your",
        "that",
        "this",
        "with",
        "from",
        "are",
        "was",
        "were",
        "have",
        "has",
        "had",
        "not",
        "but",
        "what",
        "when",
        "who",
        "how",
        "why",
        "all",
        "can",
        "will",
        "just",
        "like",
        "get",
        "got",
        "out",
        "into",
        "then",
        "than",
        "them",
        "they",
        "our",
        "his",
        "her",
        "its",
        "it's",
        "i'm",
        "don't",
        "didn't",
        "here",
        "there",
    }
    counts: dict[str, int] = {}
    for word in re.findall(r"[A-Za-z][A-Za-z'-]{2,}", text.lower()):
        if word in stop:
            continue
        counts[word] = counts.get(word, 0) + 1
    ranked = sorted(counts, key=lambda w: (-counts[w], w))
    return ranked[:limit]
