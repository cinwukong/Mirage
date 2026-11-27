"""What's new after an update (updater.whats_new): the notes for the versions you haven't seen yet, from CHANGES.md."""
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import updater  # noqa: E402

CHANGES = """# What's new in Mirage

## 3.1.0
- A new look.
- Settings in four groups.

## 3.0.2
- Subtitles scroll and follow my voice, so long replies are never cut off.
- A progress bar while updating.

## 3.0.1
- Safer: apps open without the command line.
"""


class WhatsNew(unittest.TestCase):
    def test_after_an_update_you_see_the_versions_you_skipped_newest_first(self):
        notes = updater.whats_new(CHANGES, seen="3.0.1", current="3.1.0")
        self.assertEqual([v for v, items in notes], ["3.1.0", "3.0.2"])
        self.assertEqual(notes[1][1], ["Subtitles scroll and follow my voice, so long replies are never cut off.",
                                       "A progress bar while updating."])

    def test_nothing_when_you_have_seen_this_version(self):
        self.assertEqual(updater.whats_new(CHANGES, seen="3.0.2", current="3.0.2"), [])

    def test_never_shows_notes_for_versions_you_dont_have_yet(self):
        notes = updater.whats_new(CHANGES, seen="3.0.1", current="3.0.2")
        self.assertEqual([v for v, items in notes], ["3.0.2"])

    def test_coming_from_before_mirage_kept_track_shows_just_this_version(self):
        notes = updater.whats_new(CHANGES, seen="", current="3.0.2")
        self.assertEqual([v for v, items in notes], ["3.0.2"])

    def test_a_missing_or_empty_changes_file_shows_nothing(self):
        self.assertEqual(updater.whats_new("", seen="3.0.1", current="3.0.2"), [])


if __name__ == "__main__":
    unittest.main()
