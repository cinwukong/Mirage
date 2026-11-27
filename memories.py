"""
Mirage's memory: what it remembers about you, and your to-do list, kept in Mirage's own data folder
(%LOCALAPPDATA%\\Mirage\\memory.db) and shown on the Memory page. Nothing is written to notes or any other app.

Older versions wrote these as markdown notes (Documents\\Mirage\\Mirage\\Memory.md and To-do.md, or an Obsidian
vault). import_notes() brings them in once; the notes themselves are left where they are.
"""

import re
import sqlite3
import threading
import time
from contextlib import contextmanager
from datetime import datetime
from pathlib import Path

ME = {"me", "user", "the user", "myself", "i"}
ADDED, KNOWN, REFUSED = 1, 0, -1


def _skills():
    import skills  # imported when first needed: skills is a big module and only its text helpers are used here
    return skills


def _words(text: str) -> list:
    """The words of a text that carry meaning (no "the", "my", "please"...)."""
    sk = _skills()
    return [w for w in re.findall(r"[a-z0-9']+", (text or "").lower()) if w not in sk.STOPWORDS]


def _keys(text: str, drop_short=True) -> set:
    """Word stems for matching ("games" finds "game")."""
    stem = _skills()._stem
    return {stem(w) for w in _words(text) if len(w) > 2 or not drop_short}


def _norm(text: str) -> str:
    return re.sub(r"\s+", " ", text or "").strip().rstrip(".").strip()


def old_note_folders(vault_path, notes_dir, app_dir) -> list:
    """Where older versions may have written Memory.md and To-do.md: the Obsidian vault picked in Settings (its
    Mirage folder; a setting that pointed inside the vault still finds it), Documents\\Mirage, and the "memory"
    folder Mirage used before 3.0."""
    folders = []
    if (vault_path or "").strip():
        p = Path(vault_path.strip())
        p = p.parent if p.name == ".obsidian" else p
        for parent in [p, *p.parents]:  # the vault is the folder with Obsidian's settings in it
            if (parent / ".obsidian").is_dir():
                p = parent
                break
        folders += [p / "Mirage", p]
    folders += [Path(notes_dir) / "Mirage", Path(app_dir) / "memory" / "Mirage", Path(app_dir) / "memory"]
    return folders


class Memories:
    def __init__(self, path):
        self.path = Path(path)
        self.lock = threading.RLock()  # one at a time: the worker, the learner and the Memory page all use it
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self._db() as db:
            db.execute("CREATE TABLE IF NOT EXISTS facts (id INTEGER PRIMARY KEY, t REAL, text TEXT, topic TEXT, "
                       "noticed INTEGER DEFAULT 0)")
            db.execute("CREATE TABLE IF NOT EXISTS todos (id INTEGER PRIMARY KEY, t REAL, text TEXT, done INTEGER DEFAULT 0)")
            db.execute("CREATE TABLE IF NOT EXISTS meta (key TEXT PRIMARY KEY, value TEXT)")

    @contextmanager
    def _db(self):
        """A connection, used by one caller at a time, that commits and closes when the block ends (the lock is let
        go even if the database can't be opened)."""
        with self.lock:
            db = sqlite3.connect(str(self.path), timeout=10)
            try:
                db.row_factory = sqlite3.Row
                yield db
                db.commit()
            finally:
                db.close()

    @staticmethod
    def _fact(r) -> dict:
        return {"id": r["id"], "when": datetime.fromtimestamp(r["t"]).strftime("%Y-%m-%d %H:%M"), "text": r["text"],
                "topic": r["topic"], "noticed": bool(r["noticed"])}

    # ---- facts ----
    def _topic_for(self, fact, topic):
        known = {x.lower(): x for x in self.topics()}
        if topic:
            t = topic.strip()
            return "Me" if t.lower() in ME else known.get(t.lower()) or _skills().topic_title(t)
        return _skills().fact_subject(fact, known)

    def _add_fact(self, fact: str, topic=None, noticed=False, t=None) -> int:
        """ADDED, KNOWN (the same fact is already kept) or REFUSED (a secret, or nothing)."""
        sk = _skills()
        fact = _norm(sk.redact(fact))
        if not fact or sk.SECRET_FACT.search(fact):
            return REFUSED
        with self._db() as db:  # the check and the save together, so two threads can't both save it
            if db.execute("SELECT 1 FROM facts WHERE lower(text) = lower(?)", (fact,)).fetchone():
                return KNOWN
            db.execute("INSERT INTO facts (t, text, topic, noticed) VALUES (?, ?, ?, ?)",
                       (t or time.time(), fact, self._topic_for(fact, topic), int(bool(noticed))))
        return ADDED

    def remember(self, fact: str, topic: str = None, noticed: bool = False, t: float = None) -> bool:
        """Keep a fact. topic: who or what it's about ("Me", "Emma"), worked out when not given. noticed: Mirage
        picked it up from a conversation rather than being told. False if it was refused (passwords, codes, card
        numbers are never kept); saying the same thing twice keeps it once."""
        return self._add_fact(fact, topic, noticed, t) != REFUSED

    def facts(self, limit=400) -> list:
        """What's remembered, oldest first: [{id, when, text, topic, noticed}]. limit: the newest so many (None: all)."""
        with self._db() as db:
            if limit is None:
                rows = db.execute("SELECT * FROM facts ORDER BY t, id").fetchall()
            else:
                rows = db.execute("SELECT * FROM (SELECT * FROM facts ORDER BY t DESC, id DESC LIMIT ?) ORDER BY t, id",
                                  (limit,)).fetchall()
        return [self._fact(r) for r in rows]

    NAME_FACT = "The user wants to be called "

    def name(self) -> str:
        """What Mirage calls you ("" if you haven't said)."""
        with self._db() as db:
            r = db.execute("SELECT text FROM facts WHERE text LIKE ? ORDER BY t DESC, id DESC LIMIT 1",
                           (self.NAME_FACT + "%",)).fetchone()
        return r["text"][len(self.NAME_FACT):].strip() if r else ""

    def set_name(self, name: str) -> bool:
        """Call you this from now on: the old name is forgotten. An empty name just forgets it."""
        name = " ".join(str(name or "").split())[:40]
        with self._db() as db:
            db.execute("DELETE FROM facts WHERE text LIKE ?", (self.NAME_FACT + "%",))
        return self.remember(self.NAME_FACT + name, topic="Me") if name else True

    def topics(self) -> list:
        with self._db() as db:
            return [r[0] for r in db.execute("SELECT DISTINCT topic FROM facts WHERE topic IS NOT NULL AND topic != ''")]

    def me_facts(self, limit=30) -> list:
        """The newest facts about you yourself, oldest first."""
        with self._db() as db:
            rows = db.execute("SELECT * FROM (SELECT * FROM facts WHERE topic = 'Me' ORDER BY t DESC, id DESC LIMIT ?) "
                              "ORDER BY t, id", (limit,)).fetchall()
        return [self._fact(r) for r in rows]

    def relevant_facts(self, query: str, limit=8, skip=()) -> list:
        """Remembered facts that share words with a question, best first."""
        keys = _keys(query)
        if not keys:
            return []
        scored = []
        for f in self.facts(None):
            if f["id"] in skip:
                continue
            hits = len(keys & _keys(f["text"] + " " + (f["topic"] or ""), drop_short=False))
            if hits:
                scored.append((hits / len(keys), f["when"], f))
        scored.sort(key=lambda x: (x[0], x[1]), reverse=True)  # best match first, newer first on ties
        return [f for score, _, f in scored if score >= 0.34][:limit]

    def find_fact(self, text: str, cutoff=0.6):
        """The remembered fact that best matches some wording (for corrections), or None."""
        want = _keys(text, drop_short=False)
        best, best_score = None, 0.0
        for f in self.facts(None):
            have = _keys(f["text"], drop_short=False)
            if want and have:
                score = len(want & have) / len(want | have)
                if score > best_score:
                    best, best_score = f, score
        return best if best_score >= cutoff else None

    def replace_fact(self, old_id: int, fact: str, topic=None, noticed=True) -> bool:
        """A correction: the old fact goes, the new one is kept."""
        self.delete_fact(old_id)
        return self.remember(fact, topic, noticed)

    def delete_fact(self, fact_id) -> bool:
        with self._db() as db:
            return db.execute("DELETE FROM facts WHERE id = ?", (int(fact_id),)).rowcount > 0

    def forget(self, words: str) -> int:
        """Forget the facts that contain all of the given words. Returns how many."""
        keys = _words(words)
        if not keys:
            return 0
        gone = [f["id"] for f in self.facts(None) if all(k in f["text"].lower() for k in keys)]
        with self._db() as db:
            db.executemany("DELETE FROM facts WHERE id = ?", [(i,) for i in gone])
        return len(gone)

    # ---- to-do list ----
    def add_todo(self, item: str, done=False, t: float = None) -> bool:
        item = _norm(item)
        if item:
            with self._db() as db:
                db.execute("INSERT INTO todos (t, text, done) VALUES (?, ?, ?)", (t or time.time(), item, int(done)))
        return bool(item)

    def todo_entries(self) -> list:
        """[(id, text, done)] for every to-do item, oldest first."""
        with self._db() as db:
            return [(r["id"], r["text"], bool(r["done"])) for r in db.execute("SELECT * FROM todos ORDER BY t, id")]

    def todos(self, done=False) -> list:
        return [text for i, text, d in self.todo_entries() if d == done]

    def toggle_todo(self, todo_id):
        with self._db() as db:
            db.execute("UPDATE todos SET done = 1 - done WHERE id = ?", (int(todo_id),))

    def delete_todo(self, todo_id):
        with self._db() as db:
            db.execute("DELETE FROM todos WHERE id = ?", (int(todo_id),))

    def complete_todo(self, words: str):
        """Check off the open to-do that best matches the words. Returns its text, or None."""
        keys = _words(words)
        if not keys:
            return None
        best, best_hits = None, 0
        for i, text, done in self.todo_entries():
            if not done:
                hits = sum(k in text.lower() for k in keys)
                if hits > best_hits:
                    best, best_hits = (i, text), hits
        if best is None or best_hits < max(1, len(keys) // 2):
            return None
        with self._db() as db:
            db.execute("UPDATE todos SET done = 1 WHERE id = ?", (best[0],))
        return best[1]

    # ---- searching ----
    def search(self, query: str, limit=5) -> list:
        """What matches the words best, from memories and the to-do list: [("Memory" or "To-do", text)]."""
        keys = _keys(query, drop_short=False)
        if not keys:
            return []
        items = [("Memory", f["text"]) for f in self.facts(None)] + [("To-do", text) for i, text, d in self.todo_entries()]
        scored = []
        for source, text in items:
            hits = len(keys & _keys(text, drop_short=False))
            if hits and hits / len(keys) >= 0.5:
                scored.append((hits / len(keys), source, text))
        scored.sort(key=lambda x: -x[0])
        return [(source, text) for score, source, text in scored[:limit]]

    # ---- the one-time import of older versions' notes ----
    def import_notes(self, folders) -> tuple:
        """Bring in Memory.md and To-do.md from the notes folders older versions wrote to. Happens once; the notes
        are left as they are. Returns (facts, to-dos) brought in."""
        with self._db() as db:
            if db.execute("SELECT value FROM meta WHERE key = 'notes_imported'").fetchone():
                return 0, 0
        sk = _skills()
        n_facts = n_todos = 0
        seen = set()
        for folder in folders:
            folder = Path(folder)
            mem, todo = folder / "Memory.md", folder / "To-do.md"
            if mem.is_file() and mem.resolve() not in seen:
                seen.add(mem.resolve())
                for line in mem.read_text(encoding="utf-8", errors="ignore").splitlines():
                    if not re.match(r"^\s*[-*] \S", line) or re.match(r"^\s*[-*] \[[ xX]\]", line):
                        continue  # memories are list lines, with or without the date Mirage wrote
                    f = sk.parse_fact(line)
                    try:
                        t = datetime.strptime(f["when"], "%Y-%m-%d %H:%M").timestamp() if f["when"] else None
                    except ValueError:
                        t = None
                    if self._add_fact(_norm(f["text"]), f["topic"], f["noticed"], t) == ADDED:
                        n_facts += 1
            if todo.is_file() and todo.resolve() not in seen:
                seen.add(todo.resolve())
                have = {x.lower() for i, x, d in self.todo_entries()}
                for line in todo.read_text(encoding="utf-8", errors="ignore").splitlines():
                    m = re.match(r"^\s*- \[([ xX])\]\s*(.+)$", line)
                    if not m:
                        continue
                    text = _norm(sk.clean_md(line))
                    if text and text.lower() not in have:
                        have.add(text.lower())
                        self.add_todo(text, done=m.group(1) != " ")
                        n_todos += 1
        with self._db() as db:
            db.execute("INSERT OR REPLACE INTO meta (key, value) VALUES ('notes_imported', ?)",
                       (datetime.now().isoformat(timespec="seconds"),))
        return n_facts, n_todos
