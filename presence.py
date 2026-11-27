"""
Knowing when to speak up.

- Presence: is a game (or anything) running full screen, how long since you last touched the mouse or keyboard,
  quiet hours, "do not disturb".
- Nudges: Mirage speaking up on its own, rarely and only at a good moment (you're at the PC, not in a game,
  not in quiet hours, Mirage isn't busy):
    * dates in what Mirage remembers ("Emma's birthday is on 3 March"): the day before and on the day
    * once a day in the afternoon, if your to-do list has things on it
    * optional: a break after a long stretch at the PC
  Each nudge is said once. Your own reminders and timers aren't nudges: they always come through.
"""

import ctypes
import json
import os
import re
import sys
import time
from datetime import date, datetime, timedelta
from pathlib import Path

WINDOWS = sys.platform.startswith("win")

# --------------------------------------------------------------------------- #
# Presence (Windows)
# --------------------------------------------------------------------------- #
QUNS = {1: "not present", 2: "busy", 3: "full screen game", 4: "presentation", 5: "accepts notifications",
        6: "quiet time", 7: "app"}


def notification_state() -> int:
    """Windows' own idea of whether now is a good time: 2 busy (full screen), 3 full screen Direct3D game,
    4 presentation, 5 fine. 0 if unknown."""
    if not WINDOWS:
        return 0
    try:
        state = ctypes.c_int(0)
        if ctypes.windll.shell32.SHQueryUserNotificationState(ctypes.byref(state)) == 0:
            return state.value
    except Exception:
        pass
    return 0


def fullscreen_app():
    """The name of the app filling the whole screen (a game, a video), or "" if none."""
    if not WINDOWS:
        return ""
    try:
        import pc
        state = notification_state()
        w = None
        with pc._DpiAware():
            h = pc.user32.GetForegroundWindow()
            if not h:
                return ""
            w = pc.Win(h)
            if w.pid == os.getpid() or w.exe in ("explorer", "searchhost", "shellexperiencehost", "startmenuexperiencehost",
                                                  "lockapp", "applicationframehost"):
                return ""
            r = pc._rect(h)
            _, mon, _ = pc._monitor_of(h)
            covers = r.left <= mon.left and r.top <= mon.top and r.right >= mon.right and r.bottom >= mon.bottom
        if state in (2, 3, 4) or covers:
            return w.app or w.exe or "a full-screen app"
    except Exception:
        pass
    return ""


def idle_seconds() -> float:
    """How long since you last used the mouse or keyboard."""
    if not WINDOWS:
        return 0.0
    try:
        class LASTINPUTINFO(ctypes.Structure):
            _fields_ = [("cbSize", ctypes.c_uint), ("dwTime", ctypes.c_uint)]
        li = LASTINPUTINFO()
        li.cbSize = ctypes.sizeof(li)
        if ctypes.windll.user32.GetLastInputInfo(ctypes.byref(li)):
            now = ctypes.windll.kernel32.GetTickCount() & 0xFFFFFFFF
            return ((now - li.dwTime) & 0xFFFFFFFF) / 1000.0
    except Exception:
        pass
    return 0.0


def in_quiet_hours(cfg, now=None) -> bool:
    if not cfg.get("quiet_hours", True):
        return False
    now = now or datetime.now()
    start, end = int(cfg.get("quiet_from", 23)), int(cfg.get("quiet_to", 8))
    h = now.hour + now.minute / 60
    return (start <= h < end) if start < end else (h >= start or h < end)


# --------------------------------------------------------------------------- #
# Dates in what Mirage remembers
# --------------------------------------------------------------------------- #
MONTHS = {m: i + 1 for i, m in enumerate(["january", "february", "march", "april", "may", "june", "july", "august",
                                         "september", "october", "november", "december"])}
MONTHS.update({m[:3]: n for m, n in list(MONTHS.items())})
MONTHS["sept"] = 9
_M = r"(january|february|march|april|may|june|july|august|september|october|november|december|jan|feb|mar|apr|jun|" \
     r"jul|aug|sept|sep|oct|nov|dec)\.?"
DAY_MONTH = re.compile(r"\b(\d{1,2})(?:st|nd|rd|th)?(?: of)? " + _M + r"(?:,? (\d{4}))?\b", re.I)
MONTH_DAY = re.compile(r"\b" + _M + r" (\d{1,2})(?:st|nd|rd|th)?\b(?:,? (\d{4}))?", re.I)
ISO = re.compile(r"\b(\d{4})-(\d{2})-(\d{2})\b")
YEARLY = re.compile(r"\b(?:birthday|bday|anniversary|name day|namnsdag)\b", re.I)
EVENT = re.compile(r"\b(?:birthday|bday|anniversary|exam|test|quiz|deadline|due|appointment|dentist|doctor|trip|"
                   r"flight|concert|party|game jam|release|launch|match|tournament|meeting|interview|holiday|"
                   r"vacation|starts?|begins?|moving|wedding|visit(?:ing)?|presentation|recital|show)\b", re.I)


def find_date(text: str, saved_on: date = None):
    """(date, yearly) for the first date mentioned in a fact, or None."""
    saved_on = saved_on or date.today()
    yearly = bool(YEARLY.search(text))
    m = ISO.search(text)
    if m:
        try:
            return date(int(m.group(1)), int(m.group(2)), int(m.group(3))), yearly
        except ValueError:
            return None
    def month_of(word):
        w = word.lower().rstrip(".")
        return MONTHS.get(w) or MONTHS.get(w[:3])

    m = DAY_MONTH.search(text)
    day = month = year = None
    if m:
        day, month, year = int(m.group(1)), month_of(m.group(2)), m.group(3)
    else:
        m = MONTH_DAY.search(text)
        if m:
            month, day, year = month_of(m.group(1)), int(m.group(2)), m.group(3)
    if not month:
        return None
    if month == 2 and day == 29:
        day = 28  # leap-day birthdays get the 28th in other years
    try:
        if year:
            return date(int(year), month, day), yearly
        d = date(saved_on.year, month, day)
        if not yearly and d < saved_on - timedelta(days=1):
            d = date(saved_on.year + 1, month, day)  # "the exam is on 3 March", said in November: next March
        return d, yearly
    except ValueError:
        return None


def next_occurrence(d: date, yearly: bool, today: date):
    if not yearly:
        return d
    try:
        n = d.replace(year=today.year)
    except ValueError:  # 29 February
        n = date(today.year, 3, 1)
    if n < today:
        try:
            n = d.replace(year=today.year + 1)
        except ValueError:
            n = date(today.year + 1, 3, 1)
    return n


# --------------------------------------------------------------------------- #
# Nudges
# --------------------------------------------------------------------------- #
NUDGE_GAP = 20 * 60  # seconds between two nudges


class Nudger:
    """Works out what's worth saying, and when. engine provides memory, cfg, status and a way to speak."""

    def __init__(self, engine, state_path=None, log=print):
        self.e = engine
        self.log = log
        self.path = Path(state_path) if state_path else None
        self.said = {}            # nudge key -> date it was said
        self.last_todo_day = ""
        self.active_since = None  # start of the current stretch at the PC (for break reminders)
        self.last_break = 0.0
        self.last_nudge = 0.0     # nudges are spaced out, so a busy day isn't a stream of them
        self.gaming = ""
        self._load()

    def _load(self):
        try:
            data = json.loads(self.path.read_text(encoding="utf-8")) if self.path and self.path.exists() else {}
            self.said = data.get("said", {})
            self.last_todo_day = data.get("last_todo_day", "")
        except Exception:
            self.said = {}

    def _save(self):
        if not self.path:
            return
        cutoff = (date.today() - timedelta(days=400)).isoformat()
        self.said = {k: v for k, v in self.said.items() if v >= cutoff}
        try:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            self.path.write_text(json.dumps({"said": self.said, "last_todo_day": self.last_todo_day}), encoding="utf-8")
        except Exception as ex:
            self.log(f"Couldn't save nudge state: {ex}")

    # ---- what's worth saying ----
    def candidates(self, now=None):
        """[(key, text)] of nudges due now, most important first."""
        now = now or datetime.now()
        today = now.date()
        out = []
        cfg = self.e.cfg
        sk = self.e.skills
        # dates in memory
        for f in self.e.memory.facts():
            text = f["text"]
            if not EVENT.search(text):
                continue
            try:
                saved = datetime.strptime(f["when"][:10], "%Y-%m-%d").date() if f["when"] else today
            except ValueError:
                saved = today
            found = find_date(text, saved)
            if not found:
                continue
            d = next_occurrence(found[0], found[1], today)
            spoken = sk.spoken_fact(text).rstrip(".")
            if spoken.startswith(("You ", "Your ")):
                spoken = spoken[0].lower() + spoken[1:]
            if d == today:
                out.append((f"fact:{f['id']}:{d}:today", f"Don't forget, it's today: {spoken}."))
            elif d == today + timedelta(days=1):
                out.append((f"fact:{f['id']}:{d}:tomorrow", f"Heads up for tomorrow: {spoken}."))
        # the to-do list, once a day in the afternoon or evening
        if cfg.get("nudge_todos", True) and 15 <= now.hour < 21 and self.last_todo_day != today.isoformat():
            todos = self.e.memory.todos()
            if todos:
                n = len(todos)
                out.append(("todos", f"Quick nudge: you've got {n} thing{'s' if n != 1 else ''} on your to-do list"
                                     + (f", like {todos[0]}." if todos[0] else ".")))
        rank = lambda k: 0 if k.endswith(":today") else 1 if k.endswith(":tomorrow") else 2
        return sorted([(k, t) for k, t in out if k not in self.said], key=lambda kt: rank(kt[0]))

    def break_due(self, idle, now_ts=None) -> bool:
        """A long stretch at the PC without a pause (only if break reminders are on)."""
        now_ts = now_ts or time.time()
        if idle > 300:  # five minutes away counts as a break
            self.active_since = None
            return False
        if self.active_since is None:
            self.active_since = now_ts
        minutes = float(self.e.cfg.get("break_minutes", 90) or 90)
        return bool(self.e.cfg.get("break_reminders", False)) and now_ts - self.active_since >= minutes * 60 \
            and now_ts - self.last_break >= minutes * 60

    def good_moment(self, idle=None, gaming=None, now=None) -> str:
        """"" if Mirage may speak up now, otherwise why not."""
        e, cfg = self.e, self.e.cfg
        if not cfg.get("nudges", True):
            return "turned off"
        if in_quiet_hours(cfg, now):
            return "quiet hours"
        if float(cfg.get("dnd_until", 0) or 0) > time.time():
            return "do not disturb"
        if gaming if gaming is not None else self.gaming:
            return "full screen"
        if (idle if idle is not None else idle_seconds()) > 120:
            return "not at the PC"
        if e.mic_muted:
            return "mic muted"
        if e.status not in ("listening",) or not e.cmd_q.empty() or e.voice.speaking.is_set() or e.hands.active \
                or e._confirming:
            return "busy"
        last = e.chats.last_time() if getattr(e, "chats", None) else 0
        if time.time() - last < 90:
            return "just talked"
        return ""

    def tick(self):
        """Called every minute or so: say the most important nudge, if now is a good moment."""
        idle = idle_seconds()
        if self.break_due(idle):
            if not self.good_moment(idle):
                self.last_break = time.time()
                self.active_since = time.time()
                self.e.speak_up("You've been at it for a while. Maybe stand up and stretch for a minute?")
                return True
        if time.time() - self.last_nudge < NUDGE_GAP:
            return False
        found = self.candidates()
        if not found or self.good_moment(idle):
            return False
        key, text = found[0]
        self.last_nudge = time.time()
        self.said[key] = date.today().isoformat()
        if key == "todos":
            self.last_todo_day = date.today().isoformat()
        self._save()
        self.e.speak_up(text)
        return True


DND_ON = re.compile(r"(?:(?:turn on |start |go into )?(?:quiet mode|do not disturb|dnd)(?: mode)?(?: on)?|"
                    r"(?:please )?don'?t disturb me|stay quiet|keep quiet|no talking|leave me alone|i'?m busy|"
                    r"(?:be quiet|stop talking|don'?t talk(?: to me)?)(?= (?:for|until|till) ))(?: (?:for|until|till) (.+))?")
DND_OFF = re.compile(r"(?:you can (?:talk|speak|speak up) again|(?:quiet mode|do not disturb|dnd)(?: mode)? off|"
                     r"(?:turn off|stop|end) (?:quiet mode|do not disturb|dnd)|i'?m (?:back|free)(?: now)?)")


def dnd_until(text: str, parse_duration, parse_when, now=None):
    """When "do not disturb" should end, from "for 2 hours" / "until 5 pm". None means an hour."""
    now = now or datetime.now()
    if not text:
        return now + timedelta(hours=1)
    secs = parse_duration(text)
    if secs > 0:
        return now + timedelta(seconds=secs)
    if re.fullmatch(r"(?:tomorrow|the morning|tomorrow morning)", text.strip()):
        return (now + timedelta(days=1)).replace(hour=8, minute=0, second=0, microsecond=0)
    when, _ = parse_when("remind me at " + text + " to x")
    if when:
        return when
    return now + timedelta(hours=1)
