"""Word-level punctuation detection — the terminators each script actually uses.

Whisper emits the terminator of the language it transcribed: a full stop for
English, the danda for Hindi, the ideographic full stop for Japanese. A
detector that only knows Latin punctuation sees no sentence boundary at all in
those languages, which silently changes how clips are cut.
"""

from __future__ import annotations

import pytest
from autoclip.pipeline.transcript import Word


def word(text: str) -> Word:
    """A single word with the given text and placeholder timings."""
    return Word(text=text, start=0.0, end=1.0)


class TestSentenceEnd:
    @pytest.mark.parametrize(
        "text",
        [
            "Hello.",  # Latin full stop
            "Really!?",  # Latin question and exclamation marks
            "Wait…",  # Latin ellipsis
            "आई।",  # Devanagari danda
            "समाप्त॥",  # Devanagari double danda
            "هل صحيح؟",  # Arabic question mark
            "تم.۔",  # Arabic full stop
            "ተጠናቋል።",  # Ethiopic full stop
            "བྱུང་།",  # Tibetan shad
            "ပြီး။",  # Myanmar section mark
            "។",  # Khmer khan
            "完了。",  # Ideographic full stop
            "本当！",  # Fullwidth exclamation mark
            "本当？",  # Fullwidth question mark
            "Բարև։",  # Armenian full stop
            "Ⴛ",  # Georgian paragraph separator
            "᠃",  # Mongolian full stop
            "᭞",  # Balinese carik siki
        ],
    )
    def test_recognises_the_scripts_own_terminator(self, text: str) -> None:
        assert word(text).ends_sentence

    def test_a_closing_quote_after_the_terminator_still_counts(self) -> None:
        assert word('आई।"').ends_sentence

    def test_a_plain_word_is_not_a_sentence_end(self) -> None:
        assert not word("आई").ends_sentence

    def test_a_terminator_inside_a_word_does_not_count(self) -> None:
        assert not word("आई।और").ends_sentence


class TestClauseEnd:
    @pytest.mark.parametrize(
        "text",
        [
            ",",
            ";",
            ":",
            "—",
            "–",
            "،",  # Arabic comma
            "؛",  # Arabic semicolon
            "፣",  # Ethiopic comma
            "፤",  # Ethiopic semicolon
            "՝",  # Armenian comma
            "၊",  # Myanmar little section
            "៕",  # Khmer bariyoosan
            "、",  # Ideographic comma
            "，",  # Fullwidth comma
            "；",  # Fullwidth semicolon
            "：",  # Fullwidth colon
        ],
    )
    def test_recognises_the_scripts_own_clause_mark(self, text: str) -> None:
        assert word(f"शब्द{text}").ends_clause
        assert not word(f"शब्द{text}").ends_sentence

    def test_a_sentence_end_is_also_a_clause_end(self) -> None:
        assert word("आई।").ends_clause

    def test_the_tibetan_tsheg_is_not_a_clause_mark(self) -> None:
        # The tsheg separates syllables, not clauses. Treating it as a clause
        # end would split Tibetan speech into one word per segment.
        assert not word("བྱུང་").ends_clause
        assert not word("བྱུང་").ends_sentence
