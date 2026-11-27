"""Mirage's own memory (memories.Memories): facts and to-dos kept in Mirage's data folder, and the one-time import
of the notes older versions wrote as markdown."""
import shutil
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from memories import Memories  # noqa: E402

OLD_MEMORY = """# Mirage memory
Things Mirage remembers about you. Lines tagged #noticed it picked up from your conversations. Part of [[Mirage]].

- 2026-11-26 20:30 — The user wants to be called Luca · [[Me]]
- 2026-11-26 21:02 — my favourite colour is purple · [[Me]]
- 2026-11-26 21:40 — [[Skyline]] is a city-building game the user is making · [[Skyline]] #noticed
- 2026-11-26 22:01 — Emma is the [[Me|user's]] sister · [[Emma]] #noticed
"""
OLD_TODO = """# To-do

Part of [[Mirage]].

- [ ] buy milk
- [x] call the dentist
- [ ] finish the [[Skyline]] menu
"""


class Facts(unittest.TestCase):
    def setUp(self):
        self.dir = Path(tempfile.mkdtemp())
        self.m = Memories(self.dir / "memory.db")

    def tearDown(self):
        shutil.rmtree(self.dir, ignore_errors=True)

    def test_what_you_tell_it_is_remembered_and_filed_under_you(self):
        self.assertTrue(self.m.remember("my favourite colour is purple"))
        f = self.m.facts()
        self.assertEqual([x["text"] for x in f], ["my favourite colour is purple"])
        self.assertEqual(f[0]["topic"], "Me")
        self.assertEqual([x["text"] for x in self.m.me_facts()], ["my favourite colour is purple"])

    def test_it_never_keeps_secrets(self):
        self.assertFalse(self.m.remember("my bank password is hunter2"))
        self.assertEqual(self.m.facts(), [])

    def test_saying_it_twice_keeps_it_once(self):
        self.m.remember("my dog is called Bruno")
        self.m.remember("My dog is called Bruno.")
        self.assertEqual(len(self.m.facts()), 1)

    def test_forgetting_by_words_and_by_the_list(self):
        self.m.remember("my favourite colour is purple")
        self.m.remember("my dog is called Bruno")
        self.assertEqual(self.m.forget("colour"), 1)
        self.assertEqual([x["text"] for x in self.m.facts()], ["my dog is called Bruno"])
        self.assertTrue(self.m.delete_fact(self.m.facts()[0]["id"]))
        self.assertEqual(self.m.facts(), [])

    def test_a_correction_replaces_the_old_fact(self):
        self.m.remember("The user's favourite colour is purple", noticed=True)
        old = self.m.find_fact("favourite colour purple", 0.5)
        self.m.replace_fact(old["id"], "The user's favourite colour is green", noticed=True)
        self.assertEqual([x["text"] for x in self.m.facts()], ["The user's favourite colour is green"])
        self.assertTrue(self.m.facts()[0]["noticed"])

    def test_facts_that_share_words_with_a_question_come_up(self):
        self.m.remember("my dog is called Bruno")
        self.m.remember("my favourite colour is purple")
        rel = self.m.relevant_facts("what is my dog called")
        self.assertEqual([x["text"] for x in rel], ["my dog is called Bruno"])

    def test_it_is_still_there_after_a_restart(self):
        self.m.remember("my dog is called Bruno")
        self.m.add_todo("buy milk")
        again = Memories(self.dir / "memory.db")
        self.assertEqual([x["text"] for x in again.facts()], ["my dog is called Bruno"])
        self.assertEqual(again.todos(), ["buy milk"])


class Robustness(unittest.TestCase):
    def setUp(self):
        self.dir = Path(tempfile.mkdtemp())
        self.m = Memories(self.dir / "memory.db")

    def tearDown(self):
        shutil.rmtree(self.dir, ignore_errors=True)

    def test_two_threads_saving_the_same_fact_keep_it_once(self):
        import threading
        go = threading.Barrier(8)

        def save():
            go.wait()
            self.m.remember("my dog is called Bruno")
        threads = [threading.Thread(target=save) for _ in range(8)]
        for t in threads:
            t.start()
        for t in threads:
            t.join(10)
        self.assertEqual(len(self.m.facts()), 1)

    def test_old_facts_about_you_are_never_forgotten_by_the_brain(self):
        self.m.remember("my name is Luca", topic="Me", t=1.0)
        for i in range(450):
            self.m.remember(f"the project note number {i} is done", topic="Projects", t=2.0 + i)
        self.assertIn("my name is Luca", [f["text"] for f in self.m.me_facts()])
        self.assertIsNotNone(self.m.find_fact("my name is Luca"))

    def test_a_database_that_fails_to_open_once_doesnt_lock_mirage_up(self):
        import sqlite3
        import memories
        real = sqlite3.connect
        calls = {"n": 0}

        def flaky(*a, **k):
            calls["n"] += 1
            if calls["n"] == 1:
                raise sqlite3.OperationalError("database is locked (test)")
            return real(*a, **k)
        memories.sqlite3.connect = flaky
        try:
            with self.assertRaises(sqlite3.OperationalError):
                self.m.facts()
        finally:
            memories.sqlite3.connect = real
        import threading
        done = []
        t = threading.Thread(target=lambda: done.append(self.m.remember("my dog is called Bruno")), daemon=True)
        t.start()
        t.join(5)  # another thread (the worker, the page) must still get in
        self.assertEqual(done, [True])

    def test_hand_written_lines_in_old_notes_come_across_too(self):
        notes = self.dir / "notes"
        notes.mkdir()
        (notes / "Memory.md").write_text("# Mirage memory\n\n- my cat is called Sixten\n", encoding="utf-8")
        self.assertEqual(self.m.import_notes([notes]), (1, 0))

    def test_a_vault_setting_pointing_inside_the_vault_still_finds_the_notes(self):
        import memories
        vault = self.dir / "Vault"
        (vault / ".obsidian").mkdir(parents=True)
        (vault / "Mirage").mkdir()
        (vault / "Projects" / "Games").mkdir(parents=True)
        self.assertIn(vault / "Mirage", memories.old_note_folders(str(vault / "Projects" / "Games"), self.dir, self.dir))


class Todos(unittest.TestCase):
    def setUp(self):
        self.dir = Path(tempfile.mkdtemp())
        self.m = Memories(self.dir / "memory.db")

    def tearDown(self):
        shutil.rmtree(self.dir, ignore_errors=True)

    def test_adding_checking_off_and_deleting(self):
        self.m.add_todo("buy milk")
        self.m.add_todo("call the dentist")
        self.assertEqual(self.m.complete_todo("dentist"), "call the dentist")
        self.assertEqual(self.m.todos(), ["buy milk"])
        self.assertEqual(self.m.todos(done=True), ["call the dentist"])
        entries = {text: (i, done) for i, text, done in self.m.todo_entries()}
        self.m.toggle_todo(entries["call the dentist"][0])
        self.assertEqual(sorted(self.m.todos()), ["buy milk", "call the dentist"])
        self.m.delete_todo(entries["buy milk"][0])
        self.assertEqual(self.m.todos(), ["call the dentist"])

    def test_checking_off_something_not_on_the_list(self):
        self.m.add_todo("buy milk")
        self.assertIsNone(self.m.complete_todo("walk the cat"))

    def test_search_finds_memories_and_todos(self):
        self.m.remember("my dog is called Bruno")
        self.m.add_todo("take Bruno to the vet")
        self.assertEqual(sorted(src for src, text in self.m.search("bruno")), ["Memory", "To-do"])


class ImportOldNotes(unittest.TestCase):
    def setUp(self):
        self.dir = Path(tempfile.mkdtemp())
        self.notes = self.dir / "Documents" / "Mirage" / "Mirage"
        self.notes.mkdir(parents=True)
        (self.notes / "Memory.md").write_text(OLD_MEMORY, encoding="utf-8")
        (self.notes / "To-do.md").write_text(OLD_TODO, encoding="utf-8")
        (self.notes / "Topics").mkdir()
        (self.notes / "Topics" / "Me.md").write_text("- 2026-11-26 21:02 — my favourite colour is purple (from [[Memory]])\n",
                                                     encoding="utf-8")
        self.m = Memories(self.dir / "memory.db")

    def tearDown(self):
        shutil.rmtree(self.dir, ignore_errors=True)

    def test_memories_come_across_as_plain_text_with_topic_time_and_noticed(self):
        self.assertEqual(self.m.import_notes([self.notes]), (4, 3))
        f = {x["text"]: x for x in self.m.facts()}
        self.assertEqual(list(f), ["The user wants to be called Luca", "my favourite colour is purple",
                                   "Skyline is a city-building game the user is making", "Emma is the user's sister"])
        self.assertEqual(f["Emma is the user's sister"]["topic"], "Emma")
        self.assertTrue(f["Emma is the user's sister"]["noticed"])
        self.assertFalse(f["my favourite colour is purple"]["noticed"])
        self.assertEqual(f["The user wants to be called Luca"]["when"], "2026-11-26 20:30")

    def test_todos_come_across_with_whether_they_are_done(self):
        self.m.import_notes([self.notes])
        self.assertEqual(self.m.todos(), ["buy milk", "finish the Skyline menu"])
        self.assertEqual(self.m.todos(done=True), ["call the dentist"])

    def test_it_only_happens_once(self):
        self.m.import_notes([self.notes])
        self.assertEqual(self.m.import_notes([self.notes]), (0, 0))
        self.assertEqual(len(self.m.facts()), 4)

    def test_the_notes_are_left_where_they_are(self):
        self.m.import_notes([self.notes])
        self.assertTrue((self.notes / "Memory.md").exists())

    def test_no_old_notes_is_fine(self):
        fresh = Memories(self.dir / "fresh.db")
        self.assertEqual(fresh.import_notes([self.dir / "nowhere"]), (0, 0))


if __name__ == "__main__":
    unittest.main()


class YourName(unittest.TestCase):
    """What Mirage calls you (Settings, General, and the first-run setup)."""
    def setUp(self):
        self.dir = Path(tempfile.mkdtemp())
        self.m = Memories(self.dir / "memory.db")

    def tearDown(self):
        shutil.rmtree(self.dir, ignore_errors=True)

    def test_no_name_until_you_give_one(self):
        self.assertEqual(self.m.name(), "")

    def test_the_name_you_give_is_the_one_used(self):
        self.m.set_name("  Luca ")
        self.assertEqual(self.m.name(), "Luca")
        self.assertIn("The user wants to be called Luca", [f["text"] for f in self.m.me_facts()])

    def test_a_new_name_replaces_the_old_one(self):
        self.m.set_name("Luca")
        self.m.remember("my favourite colour is purple")
        self.m.set_name("Lu")
        self.assertEqual(self.m.name(), "Lu")
        texts = [f["text"] for f in self.m.facts(None)]
        self.assertNotIn("The user wants to be called Luca", texts)
        self.assertIn("my favourite colour is purple", texts)

    def test_an_empty_name_forgets_it(self):
        self.m.set_name("Luca")
        self.m.set_name("")
        self.assertEqual(self.m.name(), "")
