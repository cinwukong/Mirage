"""The corner subtitles (captions.Captions): they follow Mirage's voice, scroll, and never cut text off."""
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from captions import Captions  # noqa: E402

LONG = ("Sure. The Eiffel Tower was built for the 1889 World's Fair in Paris and was meant to stand for only twenty "
        "years. Gustave Eiffel's company designed and built it, and many artists of the time hated it. It was saved "
        "because it turned out to be useful as a radio antenna. Today it is one of the most visited monuments in the "
        "world, with around seven million visitors a year. At night it sparkles for five minutes every hour.")


def measure(text):
    return 7 * len(text)  # every character 7 px wide: lines of about 40 characters in 280 px


def make(rows=3):
    return Captions(measure, width=280, rows=rows)


def run(c, start, end, step=0.1, seen=None):
    t = start
    while t <= end:
        c.tick(t)
        if seen is not None:
            seen.extend(text for pos, text, bright in c.lines() if 0 <= pos < c.rows and bright > 0)
        t += step


class LongReplies(unittest.TestCase):
    def test_a_long_reply_is_shown_in_full_over_time(self):
        c = make()
        c.show(LONG, now=0.0)
        seen = []
        run(c, 0.0, c.done_at + 1, seen=seen)
        shown = " ".join(dict.fromkeys(seen))  # every line that was readable, in order, once
        self.assertEqual(shown.split(), LONG.split())

    def test_never_more_than_the_box_at_once(self):
        c = make(rows=3)
        c.show(LONG, now=0.0)
        for t in range(0, 60):
            c.tick(t / 2)
            readable = [x for x in c.lines() if 0 <= x[0] < 3]
            self.assertLessEqual(len(readable), 3)


def readable(c):
    return [(text, bright) for pos, text, bright in c.lines() if 0 <= pos < c.rows]


class FollowingTheVoice(unittest.TestCase):
    def setUp(self):
        self.c = make()
        self.c.show(LONG, follow_voice=True, now=0.0)
        self.c.tick(0.0)

    def test_first_piece_shows_at_once_and_waits_for_the_voice(self):
        first = readable(self.c)
        self.assertTrue(first and first[0][0].startswith("Sure."))
        run(self.c, 0.0, 5.0)  # the voice is slow to start: nothing moves on by itself
        self.assertEqual(self.c.current, 0)

    def test_a_piece_appears_when_the_voice_starts_saying_it(self):
        pieces = self.c.pieces
        self.c.spoken(LONG, 1, now=1.0)
        run(self.c, 1.0, 2.0)
        texts = " ".join(t for t, b in readable(self.c) if b == 1.0)
        self.assertIn(pieces[1].split()[-1], texts)  # the piece being said is bright and in view
        self.assertTrue(any(b == 0.5 for t, b in readable(self.c)) or len(readable(self.c)) == 3)

    def test_the_piece_being_said_is_always_in_the_box(self):
        for i in range(len(self.c.pieces)):
            self.c.spoken(LONG, i, now=float(i))
            run(self.c, float(i), i + 0.9)
            bright = [t for t, b in readable(self.c) if b == 1.0]
            self.assertTrue(bright, f"piece {i} not visible")

    def test_news_about_another_reply_is_ignored(self):
        self.c.spoken("Something else entirely.", 2, now=1.0)
        run(self.c, 1.0, 2.0)
        self.assertEqual(self.c.current, 0)

    def test_a_voice_that_never_starts_falls_back_to_speaking_pace(self):
        run(self.c, 0.0, 6.5)
        self.assertEqual(self.c.current, 0)  # still waiting for the voice for a few seconds
        run(self.c, 6.5, 120.0, step=0.5)
        self.assertEqual(self.c.current, len(self.c.pieces) - 1)
        self.assertLess(self.c.done_at, 120.0)

    def test_a_voice_without_progress_runs_at_speaking_pace_from_when_it_starts(self):
        c = make()
        c.show(LONG, follow_voice=True, wpm=180, now=0.0)
        c.started(LONG, now=2.0)
        run(c, 0.0, 2.1)
        self.assertEqual(c.current, 0)
        words_first = len(c.pieces[0].split())
        run(c, 2.1, 2.0 + words_first * 60 / 180 + 0.5)
        self.assertGreaterEqual(c.current, 1)
        self.assertGreater(c.done_at, 2.0 + len(LONG.split()) * 60 / 180)


class Interruptions(unittest.TestCase):
    def test_talking_over_mirage_stops_the_subtitles_moving_on(self):
        c = make()
        c.show(LONG, follow_voice=True, now=0.0)
        c.spoken(LONG, 1, now=1.0)
        c.stop(now=2.0)
        run(c, 2.0, 20.0)
        self.assertEqual(c.current, 1)       # stays where the voice was cut off
        self.assertLess(c.done_at, 5.0)      # and goes away soon after

    def test_falling_back_to_another_voice_part_way_carries_on_from_there(self):
        c = make()
        c.show(LONG, follow_voice=True, now=0.0)
        c.spoken(LONG, 0, now=0.5)
        c.started(LONG, now=3.0)             # Mirage's voice failed; the Windows voice says the rest
        run(c, 3.0, 120.0, step=0.5)
        self.assertEqual(c.current, len(c.pieces) - 1)

    def test_blank_text_shows_nothing_and_never_breaks(self):
        c = make()
        c.show("   ", now=0.0)
        c.tick(0.1)
        self.assertEqual(c.lines(), [])


class SubtitlesOnly(unittest.TestCase):
    def test_reading_pace_moves_on_by_itself(self):
        c = make()
        c.show(LONG, now=0.0)
        run(c, 0.0, 1.0)
        self.assertEqual(c.current, 0)
        run(c, 1.0, c.done_at)
        self.assertEqual(c.current, len(c.pieces) - 1)

    def test_your_own_words_are_one_line_marked_you(self):
        c = make()
        c.show("what's the weather", who="you", now=0.0)
        c.tick(0.0)
        self.assertEqual(readable(c), [("You: what's the weather", 1.0)])


if __name__ == "__main__":
    unittest.main()
