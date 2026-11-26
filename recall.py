"""
Mirage's longer memory.

- ChatLog: every exchange, kept on this PC (not in the notes vault, which may sync to the cloud), searchable
  by words and by day: "what did we talk about yesterday?"
- Learner: when a conversation has gone quiet, Mirage's own brain reads it and saves the lasting things it
  learned about you (likes, people, projects, plans), filed by topic and tagged #noticed. Corrections replace
  the old fact. Passwords, codes, card numbers and the like are never kept.
- INTERVIEW: the questions for "get to know me".
"""

import json
import os
import re
import sqlite3
import threading
import time
from datetime import datetime, timedelta
from pathlib import Path

if os.environ.get("LOCALAPPDATA"):
    HOME = Path(os.environ["LOCALAPPDATA"]) / "Mirage"
else:
    HOME = Path(__file__).resolve().parent


class ChatLog:
    def __init__(self, path=None, redact=lambda t: t):
        self.path = Path(path or HOME / "chats.db")
        self.redact = redact
        self.lock = threading.Lock()
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self._db() as db:
            db.execute("CREATE TABLE IF NOT EXISTS chats (id INTEGER PRIMARY KEY, t REAL, you TEXT, mirage TEXT, "
                       "learned INTEGER DEFAULT 0)")
            db.execute("CREATE INDEX IF NOT EXISTS chats_t ON chats(t)")

    def _db(self):
        db = sqlite3.connect(str(self.path), timeout=10)
        db.row_factory = sqlite3.Row
        return db

    def add(self, you: str, mirage: str):
        you, mirage = self.redact(you or "").strip(), self.redact(mirage or "").strip()
        if not you:
            return
        with self.lock, self._db() as db:
            db.execute("INSERT INTO chats (t, you, mirage) VALUES (?, ?, ?)", (time.time(), you, mirage))

    def last_time(self) -> float:
        with self._db() as db:
            r = db.execute("SELECT MAX(t) FROM chats").fetchone()
        return r[0] or 0.0

    def recent(self, n=4, within=3 * 3600):
        with self._db() as db:
            rows = db.execute("SELECT * FROM chats WHERE t > ? ORDER BY t DESC LIMIT ?", (time.time() - within, n)).fetchall()
        return [dict(r) for r in reversed(rows)]

    def pending(self, limit=24):
        """Exchanges the learner hasn't read yet, oldest first (only the last two days)."""
        with self._db() as db:
            rows = db.execute("SELECT * FROM chats WHERE learned = 0 AND t > ? ORDER BY t LIMIT ?",
                              (time.time() - 2 * 86400, limit)).fetchall()
        return [dict(r) for r in rows]

    def mark_learned(self, ids):
        if ids:
            with self.lock, self._db() as db:
                db.executemany("UPDATE chats SET learned = 1 WHERE id = ?", [(i,) for i in ids])

    def clear(self):
        with self.lock, self._db() as db:
            db.execute("DELETE FROM chats")

    def count(self):
        with self._db() as db:
            return db.execute("SELECT COUNT(*) FROM chats").fetchone()[0]

    def search(self, query="", when="", limit=20):
        """Exchanges matching the words (any order) and/or a time: 'today', 'yesterday', 'this week',
        'last week', 'this month', a weekday, or YYYY-MM-DD. Newest first, best matches first."""
        start, end = period(when)
        sql, args = "SELECT * FROM chats WHERE t >= ? AND t < ?", [start, end]
        words = [w for w in re.findall(r"[\wåäö']+", (query or "").lower()) if len(w) > 2 and w not in COMMON]
        if words:
            sql += " AND (" + " OR ".join(["lower(you) LIKE ? OR lower(mirage) LIKE ?"] * len(words)) + ")"
            for w in words:
                stem = w[:-1] if len(w) > 4 and w.endswith("s") else w
                args += [f"%{stem}%", f"%{stem}%"]
        with self._db() as db:
            rows = [dict(r) for r in db.execute(sql + " ORDER BY t DESC LIMIT 400", args).fetchall()]
        if words:
            def score(r):
                text = f"{r['you']} {r['mirage']}".lower()
                return sum(1 for w in words if (w[:-1] if len(w) > 4 and w.endswith("s") else w) in text)
            rows.sort(key=lambda r: (score(r), r["t"]), reverse=True)
        return rows[:limit]

    def by_day(self, query="", limit=200):
        """For the Memory page: [{day, items: [{time, you, mirage}]}], newest day first."""
        rows = self.search(query, "", limit) if query else self.search("", "all", limit)
        days = {}
        for r in sorted(rows, key=lambda r: -r["t"]):
            d = datetime.fromtimestamp(r["t"])
            days.setdefault(d.strftime("%Y-%m-%d"), []).append(
                {"id": r["id"], "time": d.strftime("%H:%M"), "you": r["you"], "mirage": r["mirage"]})
        return [{"day": day_label(k), "items": v} for k, v in days.items()]


COMMON = set("the and you your for with that this what when where how did does was were are have has had about "
             "from they them then than there here talk talked said say tell told mirage".split())


def period(when: str):
    """(start, end) timestamps for a spoken time span. "" or "all" means everything."""
    w = (when or "").lower().strip()
    now = datetime.now()
    today = now.replace(hour=0, minute=0, second=0, microsecond=0)
    if w in ("", "all", "ever", "any time", "anytime"):
        return 0.0, time.time() + 60
    if w in ("today", "earlier", "earlier today", "this morning", "tonight"):
        return today.timestamp(), time.time() + 60
    if w == "yesterday":
        return (today - timedelta(days=1)).timestamp(), today.timestamp()
    if w in ("this week", "week"):
        start = today - timedelta(days=today.weekday())
        return start.timestamp(), time.time() + 60
    if w == "last week":
        start = today - timedelta(days=today.weekday() + 7)
        return start.timestamp(), (start + timedelta(days=7)).timestamp()
    if w in ("this month", "month"):
        return today.replace(day=1).timestamp(), time.time() + 60
    m = re.fullmatch(r"(?:last |past )?(\d+) days?(?: ago)?", w)
    if m:
        return (today - timedelta(days=int(m.group(1)))).timestamp(), time.time() + 60
    days = ["monday", "tuesday", "wednesday", "thursday", "friday", "saturday", "sunday"]
    m = re.fullmatch(r"(?:on |last )?(\w+?)s?", w)
    if m and m.group(1) in days:
        back = (today.weekday() - days.index(m.group(1))) % 7 or 7
        start = today - timedelta(days=back)
        return start.timestamp(), (start + timedelta(days=1)).timestamp()
    try:
        d = datetime.strptime(w[:10], "%Y-%m-%d")
        return d.timestamp(), (d + timedelta(days=1)).timestamp()
    except ValueError:
        return 0.0, time.time() + 60


def day_label(day: str) -> str:
    d = datetime.strptime(day, "%Y-%m-%d").date()
    today = datetime.now().date()
    if d == today:
        return "Today"
    if d == today - timedelta(days=1):
        return "Yesterday"
    if (today - d).days < 7:
        return d.strftime("%A")
    return d.strftime("%d %B %Y").lstrip("0")


def chats_text(rows, limit_chars=2500) -> str:
    """Exchanges as text for the brain."""
    out = []
    for r in rows:
        d = datetime.fromtimestamp(r["t"])
        out.append(f"[{d:%a %d %b %H:%M}] User: {r['you']}" + (f"\n  Mirage: {r['mirage'][:220]}" if r.get("mirage") else ""))
    text = "\n".join(out)
    return text[:limit_chars] if text else "No matching conversations."


# --------------------------------------------------------------------------- #
# Learning from conversations
# --------------------------------------------------------------------------- #
LEARN_PROMPT = """You keep the long-term memory of Mirage, a voice assistant, about its user.
Read the conversation and pick out facts about the user that will still be true and useful in a month:
who they are, what they like and dislike, their games and projects, the people and pets in their life,
their plans and important dates, and how they want Mirage to behave.

Rules:
- Only things the user said or clearly confirmed. Skip guesses, small talk, and one-off requests like
  opening apps, timers, weather or music.
- Skip anything already in "Already known", unless the user corrected it: then put the old fact's exact
  wording in "replaces".
- Never include passwords, PIN codes, login codes, card or bank numbers, ID numbers, addresses, phone
  numbers or health details.
- Write dates as real dates ("on 3 December 2026"), not "tomorrow" or "next week": today is {today}.
  Birthdays don't need a year.
- Write each fact as one short sentence about "the user", for example "The user's favourite colour is
  purple" or "Emma is the user's sister". Facts about something else name it: "Bullet Train is a Roblox
  murder-mystery game the user is making".
- topic: "Me" for facts about the user themselves, otherwise the person, pet, game or project the fact is
  about, in a few words.
- If there's nothing new about the user, return an empty list.

Example. Conversation:
User: my dog bruno hates thunder, he hid under my bed all night
User: open youtube
Answer: {"facts": [{"topic": "Bruno", "fact": "Bruno is the user's dog", "replaces": ""},
                   {"topic": "Bruno", "fact": "Bruno is scared of thunder", "replaces": ""}]}"""

LEARN_SCHEMA = {
    "type": "object",
    "properties": {"facts": {"type": "array", "maxItems": 6, "items": {
        "type": "object",
        "properties": {"topic": {"type": "string"}, "fact": {"type": "string"}, "replaces": {"type": "string"}},
        "required": ["topic", "fact", "replaces"]}}},
    "required": ["facts"],
}


def ask_for_facts(llm, conversation: str, known: list) -> list:
    """The brain's list of {topic, fact, replaces} for a conversation."""
    known_text = "\n".join(f"- {k}" for k in known[-60:]) or "(nothing yet)"
    today = datetime.now().strftime("%A %d %B %Y")
    messages = [{"role": "system", "content": LEARN_PROMPT.replace("{today}", today)},
                {"role": "user", "content": f"Already known:\n{known_text}\n\nConversation:\n{conversation}\n\n"
                                            "Return the new facts as JSON."}]
    msg = llm.chat(messages, json_schema=LEARN_SCHEMA, max_tokens=500, timeout=90)
    raw = re.sub(r"<think>.*?</think>", "", msg.get("content") or "", flags=re.S).strip()
    raw = raw[raw.find("{"):raw.rfind("}") + 1] if "{" in raw else "{}"
    try:
        facts = json.loads(raw).get("facts") or []
    except Exception:
        raise RuntimeError(f"the brain's answer wasn't JSON: {raw[:200]!r}")
    out = []
    for f in facts:
        if isinstance(f, dict) and str(f.get("fact") or "").strip():
            out.append({"topic": str(f.get("topic") or "Me").strip()[:40] or "Me",
                        "fact": str(f["fact"]).strip()[:240], "replaces": str(f.get("replaces") or "").strip()})
    return out


def save_facts(memory, facts, log=print, sensitive=None, noticed=True) -> list:
    """File the brain's facts: skip secrets and repeats, replace corrected ones. Returns what was saved."""
    saved = []
    for f in facts:
        text = f["fact"].rstrip(".")
        if sensitive is not None and sensitive.search(text):
            log(f"Memory: left out something sensitive ({f['topic']}).")
            continue
        old = memory.find_fact(f["replaces"], 0.5) if f.get("replaces") else None
        if old:
            memory.replace_fact(old["line"], text, f["topic"], noticed)
            log(f"Memory: corrected {old['text']!r} -> {text!r}")
            saved.append(text)
            continue
        if memory.find_fact(text, 0.7):
            continue  # already known
        if memory.remember(text, f["topic"], noticed):
            log(f"Memory: {'noticed' if noticed else 'saved'} {text!r} ({f['topic']})")
        saved.append(text)
    return saved


INTERVIEW = [
    ("name", "First, what should I call you?", r"\b(?:name|call(?:ed)?|goes by)\b"),
    ("days", "What do you spend most of your days on? School, work, something else?", r"\b(?:school|work|job|student|class|grade)\b"),
    ("fun", "What do you like doing for fun?", r"\b(?:likes|enjoys|loves|hobby|hobbies|plays)\b"),
    ("projects", "Are you working on anything right now, like a game or a project?", r"\b(?:making|building|working on|project|developing)\b"),
    ("music", "What kind of music do you like?", r"\b(?:music|artist|band|song|rap|rock|pop|listens)\b"),
    ("people", "Who are the important people in your life I should know about?", r"\b(?:brother|sister|mom|mum|dad|mother|father|friend|girlfriend|boyfriend)\b"),
    ("style", "Last one. How should I talk to you? Short and to the point, chatty, funny?", r"\b(?:mirage should|wants mirage|prefers mirage|talk to)\b"),
]
INTERVIEW_STOP = re.compile(r"(?:stop|that'?s enough|enough|quit|end|i'?m done|done|cancel|no more)(?: (?:now|please|mirage))*")
INTERVIEW_SKIP = re.compile(r"(?:skip|next|pass|i don'?t know|dunno|no idea|nothing|none|not really|no)(?: (?:it|that|one|please|question))*")
