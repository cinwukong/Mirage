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
from contextlib import closing
from datetime import datetime
from pathlib import Path

ME = ("me", "user", "the user", "myself", "i")


def _skills():
    import skills
    return skills


def _keys(text: str, drop_short=True) -> set:
    sk = _skills()
    return {sk._stem(w) for w in re.findall(r"[a-z0-9']+", (text or "").lower())
            if w not in sk.STOPWORDS and (len(w) > 2 or not drop_short)}


def _norm(text: str) -> str:
    return re.sub(r"\s+", " ", text or "").strip().rstrip(".").strip()


class Memories:
    def __init__(self, path):
        self.path = Path(path)
        self.lock = threading.RLock()  # one writer at a time (the worker, the learner and the page all use it)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self._db() as db:
            db.execute("CREATE TABLE IF NOT EXISTS facts (id INTEGER PRIMARY KEY, t REAL, text TEXT, topic TEXT, "
                       "noticed INTEGER DEFAULT 0)")
            db.execute("CREATE TABLE IF NOT EXISTS todos (id INTEGER PRIMARY KEY, t REAL, text TEXT, done INTEGER DEFAULT 0)")
            db.execute("CREATE TABLE IF NOT EXISTS meta (key TEXT PRIMARY KEY, value TEXT)")

    def _db(self):
        """A connection that commits and closes when the block ends."""
        lock, path = self.lock, self.path

        class _Conn:
            def __enter__(self):
                lock.acquire()
                self.db = sqlite3.connect(str(path), timeout=10)
                self.db.row_factory = sqlite3.Row
                return self.db

            def __exit__(self, kind, *rest):
                try:
                    if kind is None:
                        self.db.commit()
                    self.db.close()
                finally:
                    lock.release()
        return _Conn()

    # ---- facts ----
    def _topic_for(self, fact, topic):
        if topic:
            t = topic.strip()
            if t.lower() in ME:
                return "Me"
            known = {x.lower(): x for x in self.topics()}
            return known.get(t.lower()) or _skills().topic_title(t)
        return _skills().fact_subject(fact, {x.lower(): x for x in self.topics()})

    def remember(self, fact: str, topic: str = None, noticed: bool = False, t: float = None) -> bool:
        """Keep a fact. topic: who or what it's about ("Me", "Emma"), worked out when not given. noticed: Mirage
        picked it up from a conversation rather than being told. False if it was refused (passwords, codes, card
        numbers are never kept); saying the same thing twice keeps it once."""
        sk = _skills()
        fact = _norm(sk.redact(fact))
        if not fact or sk.SECRET_FACT.search(fact):
            return False
        if any(f["text"].lower() == fact.lower() for f in self.facts(10000)):
            return True
        topic = self._topic_for(fact, topic)  # reads the database itself, so before the connection below
        with self._db() as db:
            db.execute("INSERT INTO facts (t, text, topic, noticed) VALUES (?, ?, ?, ?)",
                       (t or time.time(), fact, topic, int(bool(noticed))))
        return True

    def facts(self, limit=400) -> list:
        """Everything remembered, oldest first: [{id, when, text, topic, noticed}]."""
        with self._db() as db:
            rows = db.execute("SELECT * FROM (SELECT * FROM facts ORDER BY t DESC, id DESC LIMIT ?) ORDER BY t, id",
                              (limit,)).fetchall()
        return [{"id": r["id"], "when": datetime.fromtimestamp(r["t"]).strftime("%Y-%m-%d %H:%M"), "text": r["text"],
                 "topic": r["topic"], "noticed": bool(r["noticed"])} for r in rows]

    def topics(self) -> list:
        with self._db() as db:
            return [r[0] for r in db.execute("SELECT DISTINCT topic FROM facts WHERE topic IS NOT NULL AND topic != ''")]

    def me_facts(self, limit=30) -> list:
        return [f for f in self.facts() if f["topic"] == "Me"][-limit:]

    def relevant_facts(self, query: str, limit=8, skip=()) -> list:
        """Remembered facts that share words with a question, best first."""
        keys = _keys(query)
        if not keys:
            return []
        scored = []
        for f in self.facts():
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
        for f in self.facts():
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
        sk = _skills()
        keys = [w for w in re.findall(r"[a-z0-9']+", words.lower()) if w not in sk.STOPWORDS]
        if not keys:
            return 0
        gone = [f["id"] for f in self.facts(10000) if all(k in f["text"].lower() for k in keys)]
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
        sk = _skills()
        keys = [w for w in re.findall(r"[a-z0-9']+", words.lower()) if w not in sk.STOPWORDS]
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
        items = [("Memory", f["text"]) for f in self.facts()] + [("To-do", text) for i, text, d in self.todo_entries()]
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
                    if not re.match(r"^\s*- \d{4}-\d{2}-\d{2} \d{2}:\d{2} ", line):
                        continue
                    f = sk.parse_fact(line)
                    text = _norm(f["text"])
                    try:
                        t = datetime.strptime(f["when"], "%Y-%m-%d %H:%M").timestamp()
                    except ValueError:
                        t = None
                    before = len(self.facts(10000))
                    if text and self.remember(text, f["topic"], f["noticed"], t) and len(self.facts(10000)) > before:
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
