"""Caption grouping and ASS generation."""

from __future__ import annotations

import pysubs2
import pytest
from autoclip.pipeline import captions
from autoclip.pipeline.transcript import Word


def words_from(spec: list[tuple[str, float, float]]) -> list[Word]:
    return [Word(text=t, start=s, end=e) for t, s, e in spec]


def evenly_spaced(texts: list[str], *, step: float = 0.4) -> list[Word]:
    return [
        Word(text=text, start=i * step, end=i * step + step * 0.8) for i, text in enumerate(texts)
    ]


class TestGrouping:
    def test_respects_the_word_ceiling(self) -> None:
        groups = captions.group_words(evenly_spaced([f"w{i}" for i in range(12)]), max_words=4)

        assert all(len(g.words) <= 4 for g in groups)
        assert sum(len(g.words) for g in groups) == 12

    def test_breaks_on_a_long_pause(self) -> None:
        words = words_from([("one", 0.0, 0.3), ("two", 0.3, 0.6), ("three", 2.0, 2.3)])

        groups = captions.group_words(words, max_words=10, max_gap_s=0.4)

        assert len(groups) == 2
        assert groups[1].words[0].text == "three"

    def test_breaks_after_sentence_punctuation(self) -> None:
        words = words_from([("Hello.", 0.0, 0.3), ("Next", 0.4, 0.7), ("thing", 0.8, 1.0)])

        groups = captions.group_words(words, max_words=10)

        assert len(groups) == 2
        assert groups[0].text == "Hello."

    def test_trailing_sentence_end_does_not_make_an_empty_group(self) -> None:
        words = words_from([("Hello", 0.0, 0.3), ("world.", 0.4, 0.7)])

        groups = captions.group_words(words, max_words=10)

        assert len(groups) == 1
        assert all(g.words for g in groups)

    def test_every_word_appears_exactly_once(self) -> None:
        words = evenly_spaced([f"w{i}" for i in range(37)])

        grouped = [w for g in captions.group_words(words, max_words=4) for w in g.words]

        assert [w.text for w in grouped] == [w.text for w in words]

    def test_empty_input_gives_no_groups(self) -> None:
        assert captions.group_words([]) == []

    def test_group_times_span_its_words(self) -> None:
        groups = captions.group_words(evenly_spaced(["a", "b", "c"]), max_words=3)

        assert groups[0].start == 0.0
        assert groups[0].end == pytest.approx(0.8 + 0.32, abs=0.01)


class TestCaptionLifetime:
    """A caption is read, not watched.

    Whisper's word timings are alignment estimates, and one of them can be
    stretched across seconds of silence. A real Hindi clip produced a caption
    held on screen for 7.8 seconds, and a four-word cue for 12.6 — long after
    the words had been read.

    The caption's lifetime is the renderer's business, not the recogniser's:
    the text is still shown, but it does not sit on screen through a stretch
    of silence the recogniser mis-measured.
    """

    #: The words of the clip that was flagged, in clip-relative seconds. The
    #: last one is the stretched one: a single word held for 7.84 seconds.
    STRETCHED = [
        ("ने,", 9.08, 9.42),
        ("नहीं,", 9.64, 11.76),
        ("साइड", 11.76, 13.62),
        ("में", 13.81, 20.65),
    ]

    def _words(self) -> list[Word]:
        return words_from(self.STRETCHED)

    def test_a_stretched_word_is_not_held_on_screen_for_long(self) -> None:
        style = captions.get_style("bold_pop")

        spans = captions.caption_spans(self._words(), style)

        assert spans
        assert all(stop - begin <= captions.MAX_CAPTION_S + 1e-6 for begin, stop in spans)

    def test_the_rendered_events_are_bounded(self) -> None:
        """The ASS that gets burned in — not just the helper that describes it."""
        style = captions.get_style("bold_pop")

        subs = captions.build_ass(self._words(), style, width=1080, height=1920)

        limit = pysubs2.make_time(s=captions.MAX_CAPTION_S)
        assert subs.events
        assert all(event.end - event.start <= limit for event in subs.events)

    def test_every_preset_is_bounded(self) -> None:
        """The group styles hold a whole cue at once, so they need the bound too."""
        words = self._words()

        for key in captions.PRESETS:
            style = captions.get_style(key)
            subs = captions.build_ass(words, style, width=1080, height=1920)

            limit = pysubs2.make_time(s=captions.MAX_CAPTION_S)
            assert all(event.end - event.start <= limit for event in subs.events), key

    def test_the_srt_sidecar_is_bounded(self) -> None:
        words = self._words()

        groups = captions.group_words(words, max_words=8)

        assert all(group.end - group.start <= captions.MAX_CAPTION_S + 1e-6 for group in groups)

    def test_every_word_is_still_captioned(self) -> None:
        """Bounding the caption must not drop any of the words."""
        words = self._words()

        groups = captions.group_words(words, max_words=8)

        captioned = [w.text for group in groups for w in group.words]
        assert captioned == [w.text for w in words]

    def test_a_group_breaks_when_it_would_cover_too_long(self) -> None:
        """The stretched word does not drag the words before it with it."""
        words = self._words()

        groups = captions.group_words(words, max_words=8)

        # "में" starts well after the first word, so it gets its own cue
        # rather than being held on screen with the three before it.
        assert len(groups) > 1
        assert groups[0].words[-1].text != "में"

    def test_normal_captions_are_not_split(self) -> None:
        """A caption of four ordinary words still reads as one caption."""
        words = words_from(
            [("one", 0.0, 0.3), ("two", 0.4, 0.7), ("three", 0.8, 1.1), ("four", 1.2, 1.5)]
        )

        groups = captions.group_words(words, max_words=4)

        assert len(groups) == 1
        assert groups[0].text == "one two three four"

    def test_the_spans_agree_with_the_rendered_events(self) -> None:
        """The diagnostic measures the captions that are actually drawn."""
        style = captions.get_style("bold_pop")
        words = self._words()

        spans = captions.caption_spans(words, style)
        subs = captions.build_ass(words, style, width=1080, height=1920)

        assert len(spans) == len(subs.events)
        for (begin, stop), event in zip(spans, subs.events, strict=True):
            assert event.start == pysubs2.make_time(s=round(begin, 3))
            assert event.end == pysubs2.make_time(s=round(stop, 3))


class TestColour:
    def test_hex_converts_to_rgb(self) -> None:
        colour = captions.hex_to_ass("#FFE500")

        assert (colour.r, colour.g, colour.b) == (255, 229, 0)

    def test_leading_hash_is_optional(self) -> None:
        assert captions.hex_to_ass("FFFFFF").r == 255

    def test_bad_hex_raises(self) -> None:
        with pytest.raises(ValueError):
            captions.hex_to_ass("#FFF")


class TestPresets:
    def test_all_four_presets_exist(self) -> None:
        assert set(captions.PRESETS) == {
            "bold_pop",
            "karaoke_fill",
            "clean_lower",
            "boxed",
        }

    @pytest.mark.parametrize("key", list(captions.PRESETS))
    def test_every_preset_ships_its_font(self, key: str) -> None:
        # A missing font file means libass silently substitutes, and the caption
        # looks nothing like the preview.
        assert captions.get_style(key).font_path.exists()

    def test_unknown_style_raises(self) -> None:
        with pytest.raises(ValueError, match="Unknown caption style"):
            captions.get_style("neon-explosion")


class TestAssGeneration:
    @pytest.fixture
    def words(self) -> list[Word]:
        return evenly_spaced(["the", "quick", "brown", "fox", "jumps", "over."])

    @pytest.mark.parametrize("key", list(captions.PRESETS))
    def test_every_preset_produces_events(self, key: str, words: list[Word]) -> None:
        subs = captions.build_ass(words, captions.get_style(key), width=1080, height=1920)

        assert len(subs.events) > 0
        assert captions.STYLE_NAME in subs.styles

    def test_resolution_is_recorded(self, words: list[Word]) -> None:
        subs = captions.build_ass(words, captions.get_style("bold_pop"), width=1080, height=1920)

        assert subs.info["PlayResX"] == "1080"
        assert subs.info["PlayResY"] == "1920"

    def test_font_size_scales_with_height(self, words: list[Word]) -> None:
        tall = captions.build_ass(words, captions.get_style("bold_pop"), width=1080, height=1920)
        square = captions.build_ass(words, captions.get_style("bold_pop"), width=1080, height=1080)

        assert (
            tall.styles[captions.STYLE_NAME].fontsize > square.styles[captions.STYLE_NAME].fontsize
        )

    def test_time_offset_rebases_to_clip_relative(self, words: list[Word]) -> None:
        offset = captions.build_ass(
            words,
            captions.get_style("clean_lower"),
            width=1080,
            height=1920,
            time_offset_s=100.0,
        )

        # Absolute times were 0-2.7s, so everything clamps to zero rather than
        # going negative.
        assert offset.events[0].start == 0

    def test_offset_preserves_relative_spacing(self) -> None:
        words = [Word(text=t, start=100.0 + i, end=100.5 + i) for i, t in enumerate("abc")]

        subs = captions.build_ass(
            words,
            captions.get_style("clean_lower"),
            width=1080,
            height=1920,
            time_offset_s=100.0,
        )

        assert subs.events[0].start == pytest.approx(0, abs=20)

    def test_all_caps_is_applied(self, words: list[Word]) -> None:
        subs = captions.build_ass(words, captions.get_style("bold_pop"), width=1080, height=1920)

        assert "QUICK" in " ".join(e.text for e in subs.events)

    def test_clean_lower_preserves_case(self, words: list[Word]) -> None:
        subs = captions.build_ass(words, captions.get_style("clean_lower"), width=1080, height=1920)

        assert "quick" in " ".join(e.text for e in subs.events)

    def test_karaoke_emits_kf_tags(self, words: list[Word]) -> None:
        subs = captions.build_ass(
            words, captions.get_style("karaoke_fill"), width=1080, height=1920
        )

        assert any("\\kf" in event.text for event in subs.events)

    def test_bold_pop_emits_one_event_per_word(self, words: list[Word]) -> None:
        # Per-word highlighting has no per-glyph timeline in libass, so each
        # word needs its own event showing the whole group.
        subs = captions.build_ass(words, captions.get_style("bold_pop"), width=1080, height=1920)

        assert len(subs.events) == len(words)

    def test_clean_lower_emits_one_event_per_group(self, words: list[Word]) -> None:
        style = captions.get_style("clean_lower")
        groups = captions.group_words(words, max_words=style.max_words)

        subs = captions.build_ass(words, style, width=1080, height=1920)

        assert len(subs.events) == len(groups)

    def test_boxed_uses_an_opaque_border_style(self, words: list[Word]) -> None:
        subs = captions.build_ass(words, captions.get_style("boxed"), width=1080, height=1920)

        assert subs.styles[captions.STYLE_NAME].borderstyle == 3

    def test_events_never_start_before_zero(self, words: list[Word]) -> None:
        subs = captions.build_ass(
            words,
            captions.get_style("bold_pop"),
            width=1080,
            height=1920,
            time_offset_s=1.0,
        )

        assert all(event.start >= 0 for event in subs.events)

    def test_written_file_is_valid_ass(self, words: list[Word], tmp_path) -> None:
        path = captions.write_ass(
            tmp_path / "out.ass",
            words,
            captions.get_style("bold_pop"),
            width=1080,
            height=1920,
        )

        reloaded = pysubs2.load(str(path), encoding="utf-8")

        assert len(reloaded.events) > 0

    def test_srt_sidecar_is_written(self, words: list[Word], tmp_path) -> None:
        path = captions.write_srt(tmp_path / "out.srt", words)

        assert path.exists()
        assert len(pysubs2.load(str(path), encoding="utf-8").events) > 0
