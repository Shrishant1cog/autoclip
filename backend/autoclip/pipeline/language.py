"""Choosing the language the subtitles are in.

The language spoken in a video and the language its captions are written in are
two different things more often than not: a Hindi gaming video with English
captions is the normal case, not the exception. This module decides, from the
language spoken in the video and the language the user asked for, which task the
recogniser should run and which language it should be pinned to.

The rules are short, and they live here rather than in the transcription call
because this is the part that has to be *right*:

* **The same language** — transcribe. Nothing is lost and nothing is invented.
* **A different language, target English** — translate. Whisper's translate
  task decodes the English words against the source audio, so every word keeps
  the timing of the speech it came from. That is what keeps the captions in
  step with the voice.
* **A different language, target something else** — transcribe with the target
  pinned. Whisper then speaks in the target language. What that is worth for a
  given pair is measured rather than promised, and the measurement lives in the
  application record.

The spoken language is usually not known before the transcription starts. When
it is not, the recogniser is asked for it first — one short pass over the
opening seconds — because guessing wrong would either throw the translation
away or promise English for a video that is not in English.
"""

from __future__ import annotations

from dataclasses import dataclass

__all__ = [
    "DEFAULT_SUBTITLE_LANGUAGE",
    "SOURCE_LANGUAGE",
    "SubtitlePlan",
    "normalise_target",
    "plan_subtitles",
]

#: The language the subtitles are in unless the user chooses another one.
DEFAULT_SUBTITLE_LANGUAGE = "en"

#: The target that means "the language spoken in the video".
SOURCE_LANGUAGE = "source"

#: Whisper's two tasks.
TRANSCRIBE = "transcribe"
TRANSLATE = "translate"


@dataclass(frozen=True)
class SubtitlePlan:
    """What the recogniser should do to produce the requested captions.

    ``language`` is the pin passed to the recogniser: empty means "let it
    decide", which is only ever right when the task cannot depend on the
    answer.
    """

    #: The language the recogniser is pinned to. Empty means "let it decide".
    language: str
    #: "transcribe" or "translate".
    task: str
    #: The language the subtitles will be in.
    target: str
    #: The language spoken in the video, when it is known.
    spoken: str

    @property
    def translated(self) -> bool:
        """True when the captions are a translation rather than a transcript."""
        return self.task == TRANSLATE

    @property
    def known(self) -> bool:
        """True when the language of the words is settled."""
        return bool(self.target)


def normalise_target(value: str | None) -> str:
    """Turn a settings value into a target the planner understands.

    An empty value means the default — English — because the default is a
    decision, and an unset field is not one.
    """
    code = (value or "").strip().lower()
    if not code:
        return DEFAULT_SUBTITLE_LANGUAGE
    if code == SOURCE_LANGUAGE:
        return SOURCE_LANGUAGE
    return code


def plan_subtitles(*, spoken: str, target: str) -> SubtitlePlan:
    """Decide how to produce captions in ``target`` from speech in ``spoken``.

    ``spoken`` may be empty, which means "not known yet". The plan then
    prefers the task that cannot be wrong: English is the one target that can
    be promised without knowing what is being spoken, because the translate
    task produces English whatever the audio turns out to be.
    """
    spoken_code = (spoken or "").strip().lower()
    target_code = normalise_target(target)

    if target_code == SOURCE_LANGUAGE:
        # The spoken language is the answer. Nothing is translated.
        return SubtitlePlan(
            language=spoken_code,
            task=TRANSCRIBE,
            target=spoken_code,
            spoken=spoken_code,
        )

    if not spoken_code:
        # Unknown speech. Translate, because English is what the translate
        # task guarantees; for any other target, pin the target and let the
        # recogniser work in it.
        task = TRANSLATE if target_code == DEFAULT_SUBTITLE_LANGUAGE else TRANSCRIBE
        return SubtitlePlan(
            language="" if task == TRANSLATE else target_code,
            task=task,
            target=target_code,
            spoken="",
        )

    if spoken_code == target_code:
        return SubtitlePlan(
            language=spoken_code,
            task=TRANSCRIBE,
            target=target_code,
            spoken=spoken_code,
        )

    if target_code == DEFAULT_SUBTITLE_LANGUAGE:
        # Translate into English, pinned to the language actually spoken, so
        # the recogniser does not decide that a second time.
        return SubtitlePlan(
            language=spoken_code,
            task=TRANSLATE,
            target=target_code,
            spoken=spoken_code,
        )

    # A target that is neither the spoken language nor English: Whisper is
    # pinned to the target and asked to transcribe in it.
    return SubtitlePlan(
        language=target_code,
        task=TRANSCRIBE,
        target=target_code,
        spoken=spoken_code,
    )
