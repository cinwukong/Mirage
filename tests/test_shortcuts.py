"""Your own shortcuts (shortcuts.py): the "+ New shortcut" dialog and how Mirage matches what you say to them."""
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import shortcuts  # noqa: E402


class PhraseTest(unittest.TestCase):
    def test_a_typed_phrase_matches_how_mirage_hears_it(self):
        self.assertEqual(shortcuts.phrase("  Mirage, Good   Morning! "), "good morning")

    def test_apostrophes_stay(self):
        self.assertEqual(shortcuts.phrase("Let's GO."), "let's go")

    def test_nothing_left_is_empty(self):
        self.assertEqual(shortcuts.phrase("mirage..."), "")


class CheckTest(unittest.TestCase):
    def test_a_complete_shortcut_is_fine(self):
        self.assertIsNone(shortcuts.check({"phrase": "good morning", "action": "open", "target": "https://example.com"}))

    def test_it_needs_a_phrase(self):
        self.assertIn("phrase", shortcuts.check({"phrase": "Mirage!", "action": "say", "target": "Hi"}))

    def test_it_needs_something_to_do(self):
        self.assertIsNotNone(shortcuts.check({"phrase": "hello", "action": "open", "target": "   "}))

    def test_words_mirage_needs_are_kept_free(self):
        # your shortcuts run before anything else, so "stop" would stop Mirage from stopping
        self.assertIsNotNone(shortcuts.check({"phrase": "Stop", "action": "say", "target": "No"}))

    def test_keys_must_be_key_names(self):
        self.assertIsNone(shortcuts.check({"phrase": "save it", "action": "keys", "target": "Ctrl+Shift+S"}))
        self.assertIsNotNone(shortcuts.check({"phrase": "save it", "action": "keys", "target": "ctrl + + s"}))

    def test_unknown_actions_are_refused(self):
        self.assertIsNotNone(shortcuts.check({"phrase": "hi", "action": "explode", "target": "x"}))


class PutTest(unittest.TestCase):
    def test_a_new_shortcut_is_added_with_a_clean_phrase(self):
        cmds, replaced = shortcuts.put([], {"phrase": "Mirage, Work!", "action": "open", "target": " C:\\Work "})
        self.assertEqual(cmds, [{"phrase": "work", "action": "open", "target": "C:\\Work"}])
        self.assertFalse(replaced)

    def test_the_same_phrase_replaces_the_old_one_in_place(self):
        old = [{"phrase": "music", "action": "open", "target": "spotify:"},
               {"phrase": "Work", "action": "say", "target": "old"}]
        cmds, replaced = shortcuts.put(old, {"phrase": "work", "action": "open", "target": "C:\\Work"})
        self.assertTrue(replaced)
        self.assertEqual(cmds, [{"phrase": "music", "action": "open", "target": "spotify:"},
                                {"phrase": "work", "action": "open", "target": "C:\\Work"}])
        self.assertEqual(old[1]["target"], "old")  # the list you passed in is left alone


class FindTest(unittest.TestCase):
    CMDS = [{"phrase": "Good morning!", "action": "say", "target": "Morning."},
            {"phrase": "work", "action": "open", "target": "C:\\Work"}]

    def test_what_you_said_finds_its_shortcut(self):
        self.assertEqual(shortcuts.find(self.CMDS, "good morning")["target"], "Morning.")

    def test_only_the_whole_phrase_counts(self):
        self.assertIsNone(shortcuts.find(self.CMDS, "work out at five"))

    def test_nothing_said_finds_nothing(self):
        self.assertIsNone(shortcuts.find(self.CMDS, "  "))
        self.assertIsNone(shortcuts.find(None, "work"))



class WithoutTest(unittest.TestCase):
    def test_the_shortcut_with_that_phrase_is_left_out(self):
        cmds = [{"phrase": "Good morning!", "action": "say", "target": "Morning."},
                {"phrase": "work", "action": "open", "target": "C:\\Work"}]
        self.assertEqual(shortcuts.without(cmds, "good morning"), [{"phrase": "work", "action": "open", "target": "C:\\Work"}])
        self.assertEqual(len(cmds), 2)  # the list you passed in is left alone

    def test_no_phrase_leaves_everything(self):
        cmds = [{"phrase": "work", "action": "open", "target": "C:\\Work"}]
        self.assertEqual(shortcuts.without(cmds, ""), cmds)
        self.assertEqual(shortcuts.without(None, "work"), [])


if __name__ == "__main__":
    unittest.main()
