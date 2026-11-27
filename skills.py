"""
Mirage skills: helpers for memory (topics, secrets), reminders, weather, quick facts and
Roblox Studio helpers. Everything here works without the AI brain; the brain can also use it.
"""

import json
import os
import re
import threading
import time
import urllib.parse
from datetime import datetime, timedelta
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent

STOPWORDS = set("""a an the and or but if of to in on at for with about from by as is are was were be been
i me my mine you your it its this that these those what which who whom do does did have has had not no
so than then there here can could would should will just please tell remember note search notes
find say said know any some""".split())


def _http_json(url, timeout=8):
    import urllib.request
    req = urllib.request.Request(url, headers={"User-Agent": "Mirage-assistant/1.0"})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return json.loads(r.read().decode("utf-8"))


# --------------------------------------------------------------------------- #
# Spoken numbers and times
# --------------------------------------------------------------------------- #
_ONES = {"zero": 0, "oh": 0, "one": 1, "two": 2, "three": 3, "four": 4, "five": 5, "six": 6, "seven": 7,
         "eight": 8, "nine": 9, "ten": 10, "eleven": 11, "twelve": 12, "thirteen": 13, "fourteen": 14,
         "fifteen": 15, "sixteen": 16, "seventeen": 17, "eighteen": 18, "nineteen": 19}
_TENS = {"twenty": 20, "thirty": 30, "forty": 40, "fifty": 50}


def _read_number(tokens, i):
    """Read a spoken number like 'twenty three' or '23' starting at tokens[i]. Returns (value, next_i)."""
    if i >= len(tokens):
        return None, i
    t = tokens[i]
    if t.isdigit():
        return int(t), i + 1
    if t in _TENS:
        v = _TENS[t]
        if i + 1 < len(tokens) and tokens[i + 1] in _ONES and 0 < _ONES[tokens[i + 1]] < 10:
            return v + _ONES[tokens[i + 1]], i + 2
        return v, i + 1
    if t in _ONES:
        return _ONES[t], i + 1
    return None, i


def _normalize_time_text(text):
    t = " " + text.lower().replace("p.m.", "pm").replace("a.m.", "am") + " "
    t = t.replace("o'clock", " ").replace("oclock", " ")
    t = re.sub(r"(\d)(am|pm)\b", r"\1 \2", t)
    t = re.sub(r"\b(\d{1,2})[:.](\d{2})\b", r"\1 \2", t)
    t = re.sub(r"[,!?]", " ", t)
    return re.sub(r"\s+", " ", t).strip()


def parse_clock(t):
    """Find a clock time in normalized text: 'at five pm', 'at 17 30', 'at nine thirty', 'at noon'.
    Returns (hour, minute, has_ampm, phrase) or None."""
    m = re.search(r"\bat (noon|midday|midnight)\b", t)
    if m:
        return (0 if m.group(1) == "midnight" else 12), 0, True, m.group(0)
    tokens = t.split()
    for i, tok in enumerate(tokens):
        if tok != "at":
            continue
        h, j = _read_number(tokens, i + 1)
        if h is None or h > 23:
            continue
        mi = 0
        if j < len(tokens) and (tokens[j] in _TENS or tokens[j] in ("ten", "fifteen", "five") or tokens[j].isdigit()):
            mm, k = _read_number(tokens, j)
            if mm is not None and mm < 60:
                mi, j = mm, k
        elif j < len(tokens) and tokens[j] == "oh":
            mm, k = _read_number(tokens, j + 1)
            if mm is not None and mm < 10:
                mi, j = mm, k
        ampm = None
        if j < len(tokens) and tokens[j] in ("am", "pm"):
            ampm = tokens[j]
            j += 1
        if ampm == "pm" and h < 12:
            h += 12
        if ampm == "am" and h == 12:
            h = 0
        return h, mi, ampm is not None, " ".join(tokens[i:j])
    return None


def parse_when(text, now=None):
    """'in 20 minutes', 'at 5 pm', 'tomorrow at nine thirty' -> (datetime or None, text_without_time)."""
    from mirage import parse_duration  # reuse the timer parser
    now = now or datetime.now()
    t = _normalize_time_text(text)
    m = re.search(r"\bin ((?:[\w-]+ ){1,5}?(?:hours?|minutes?|mins?|seconds?|secs?))\b"
                  r"(?: and ((?:[\w-]+ ){1,3}?(?:minutes?|mins?|seconds?)))?", t)
    if m:
        secs = parse_duration(m.group(0))
        if secs > 0:
            return now + timedelta(seconds=secs), re.sub(r"\s+", " ", t[:m.start()] + " " + t[m.end():]).strip()
    tomorrow = bool(re.search(r"\btomorrow\b", t))
    clock = parse_clock(t)
    if clock:
        h, mi, has_ampm, phrase = clock
        day = now.date() + timedelta(days=1 if tomorrow else 0)
        when = datetime(day.year, day.month, day.day, h, mi)
        if not tomorrow and not has_ampm and h < 12 and when <= now:
            pm = when + timedelta(hours=12)  # "at 5" means the next 5 o'clock still ahead
            when = pm if pm > now else when + timedelta(days=1)
        if when <= now:
            when += timedelta(days=1)
        rest = t.replace(phrase, " ", 1)
        rest = re.sub(r"\btomorrow\b", " ", rest, count=1)
        return when, re.sub(r"\s+", " ", rest).strip()
    if tomorrow:
        day = now.date() + timedelta(days=1)
        return datetime(day.year, day.month, day.day, 9, 0), re.sub(r"\btomorrow\b", " ", t, count=1).strip()
    return None, t


def say_time(dt, now=None):
    now = now or datetime.now()
    hm = dt.strftime("%H:%M")
    if dt.date() == now.date():
        return f"at {hm}"
    if dt.date() == now.date() + timedelta(days=1):
        return f"tomorrow at {hm}"
    return dt.strftime("on %A %d %B at %H:%M")


# --------------------------------------------------------------------------- #
# Who or what a remembered fact is about (memories.py files facts by it)
# --------------------------------------------------------------------------- #
_BAD_FILENAME = re.compile(r'[\\/:*?"<>|#^\[\]]')
_SUBJECT_VERBS = r"(?: is | are | was | were | has | have | had | will | should | needs | need | uses | " \
                 r"means | likes | loves | hates | wants | lives | works | goes | starts | ends | costs )"


def topic_title(phrase: str) -> str:
    words = [w for w in re.split(r"\s+", _BAD_FILENAME.sub(" ", phrase).strip()) if w]
    small = {"of", "the", "and", "a", "an", "in", "on", "to", "for"}
    return " ".join(w if (i and w in small) else (w[:1].upper() + w[1:]) for i, w in enumerate(words))


def fact_subject(fact: str, known=None):
    """Who/what a remembered fact is about: 'Me' for facts about the user, a topic title, or None.
    known: {lowercase title: Title} of notes that already exist; those win when they're mentioned."""
    f = fact.lower().strip()
    if re.match(r"^(?:my|i|i'm|im|i've|me|mine)\b", f):
        return "Me"
    m = re.match(r"^(?:the |a |an |our )?(.{3,60}?)" + _SUBJECT_VERBS, f + " ")
    if not m:
        return None
    subj = m.group(1).strip(" ,")
    if subj.endswith("'s") or subj.endswith("’s"):
        subj = subj[:-2]
    # an existing note mentioned in the subject wins ("the villain of skyline" -> Skyline)
    for low in sorted(known or {}, key=len, reverse=True):
        if re.search(r"(?<!\w)" + re.escape(low) + r"(?!\w)", subj):
            return known[low]
    # "the boss of my game" -> "my game"
    m2 = re.search(r"\b(?:of|in|on|from|for|at)\s+(?:the\s+)?(.+)$", subj)
    if m2:
        subj = m2.group(1)
    words = subj.split()
    if 1 <= len(words) <= 3 and not all(w in STOPWORDS for w in words) \
            and words[0] not in ("it", "this", "that", "they", "he", "she", "there", "we", "you"):
        return topic_title(subj)
    return None


def _stem(w: str) -> str:
    """Rough word stem so "games" finds "game" and "playing" finds "play"."""
    for end in ("'s", "ing", "es", "s"):
        if w.endswith(end) and len(w) - len(end) >= 3:
            return w[:-len(end)]
    return w


# Things that must never end up in memory or the chat history
_SECRETS = [
    (re.compile(r"\b(password|passcode|pass code|pin code|pin|login code|verification code|security code)"
                r"(\s*(?:is|was|:|=)\s*)\S+", re.I), r"\1\2[hidden]"),
    (re.compile(r"\b\d(?:[ -]?\d){11,18}\b"), "[number hidden]"),     # card and account numbers
    (re.compile(r"\b\d{6}(?:\d{2})?[-+]?\d{4}\b"), "[number hidden]"),  # personal ID numbers (personnummer)
]
SECRET_FACT = re.compile(r"password|passcode|\bpin\b|pin code|login code|bank ?id|card number|account number|"
                         r"social security|personnummer|\[hidden\]|\[number hidden\]", re.I)
# what Mirage won't pick up by itself (you can still tell it to remember these, except secrets)
SENSITIVE_FACT = re.compile(SECRET_FACT.pattern + r"|home address|lives at|phone number|diagnos|medication|\billness\b",
                            re.I)


def redact(text: str) -> str:
    for pat, rep in _SECRETS:
        text = pat.sub(rep, text or "")
    return text


def parse_fact(line: str) -> dict:
    m = re.match(r"^- (\d{4}-\d{2}-\d{2} \d{2}:\d{2}) — (.+)$", line.strip())
    when, body = (m.group(1), m.group(2)) if m else ("", line.strip()[2:])
    topic = None
    t = re.search(r"·\s*\[\[([^\]|]+)", body) or re.search(r"\[\[([^\]|]+)", body)
    if t:
        topic = t.group(1).strip()
    elif re.match(r"(?:my|i|i'm|im|i've|i'd|me|mine)\b", clean_md(line).lower()):
        topic = "Me"  # saved before Mirage linked facts to topics
    return {"line": line.strip(), "when": when, "text": clean_md(line), "topic": topic, "noticed": "#noticed" in body}


_ADVERB = r"(?:really |also |usually |often |always |never |mostly |sometimes |still |just |only )?"


def _you_verb(m):
    adverb, verb = m.group(1) or "", m.group(2)
    v = verb.lower()
    special = {"is": "are", "was": "were", "has": "have", "does": "do", "doesn't": "don't", "isn't": "aren't",
               "wasn't": "weren't", "hasn't": "haven't"}
    if v in special:
        new = special[v]
    elif v.endswith("ies") and len(v) > 4:
        new = verb[:-3] + "y"
    elif v.endswith(("ches", "shes", "sses", "xes", "zes", "oes")):
        new = verb[:-2]
    elif v.endswith("s") and not v.endswith(("ss", "us")) and len(v) > 2:
        new = verb[:-1]
    else:
        new = verb
    return f"you {adverb}{new}"


def spoken_fact(text: str) -> str:
    """"The user's favourite colour is purple" -> "Your favourite colour is purple", "The user plays drums" ->
    "You play drums": facts are kept about "the user" and said to you."""
    t = re.sub(r"\bthe user's\b", "your", text, flags=re.I)
    t = re.sub(r"\bthe user (" + _ADVERB + r")([a-z']+)\b", _you_verb, t, flags=re.I)
    t = re.sub(r"\bthe user\b", "you", t, flags=re.I)
    return t[:1].upper() + t[1:] if t else t


def clean_md(line: str) -> str:
    """Turn a markdown line into something nice to read aloud."""
    s = re.sub(r"\s*#noticed\b", "", line)
    s = re.sub(r"\s*·\s*\[\[[^\]]+\]\]\s*$", "", s)
    s = re.sub(r"\s*·\s*\[\[Me\]\]", "", s)
    s = re.sub(r"\s*\(from \[\[Memory\]\]\)", "", s)
    s = re.sub(r"^\s*[-*+]\s+(\[[ xX]\]\s*)?", "", s)
    s = re.sub(r"^#+\s*", "", s)
    s = re.sub(r"\[\[([^\]|]+)\|?([^\]]*)\]\]", lambda m: m.group(2) or m.group(1), s)
    s = re.sub(r"[*_`>]", "", s)
    s = re.sub(r"^\d{4}-\d{2}-\d{2} \d{2}:\d{2} — ", "", s)
    return s.strip()


# --------------------------------------------------------------------------- #
# Reminders that survive restarts
# --------------------------------------------------------------------------- #
class Reminders:
    def __init__(self, on_due):
        import paths
        self.path = paths.DATA / "reminders.json"
        self.on_due = on_due
        self.lock = threading.Lock()
        self.items = self._load()
        threading.Thread(target=self._loop, daemon=True, name="mirage-reminders").start()

    def _load(self):
        try:
            return json.loads(self.path.read_text(encoding="utf-8"))
        except Exception:
            return []

    def _save(self):
        tmp = self.path.with_suffix(".tmp")
        tmp.write_text(json.dumps(self.items, indent=2), encoding="utf-8")
        os.replace(tmp, self.path)

    def add(self, when: datetime, text: str):
        with self.lock:
            item = {"id": int(time.time() * 1000), "when": when.isoformat(timespec="seconds"),
                    "text": text.strip() or "something"}
            self.items.append(item)
            self.items.sort(key=lambda r: r["when"])
            self._save()
        return item

    def upcoming(self):
        with self.lock:
            return list(self.items)

    def remove(self, rid):
        with self.lock:
            self.items = [r for r in self.items if r["id"] != rid]
            self._save()

    def clear(self):
        with self.lock:
            n = len(self.items)
            self.items = []
            self._save()
        return n

    def _loop(self):
        while True:
            time.sleep(5)
            now = datetime.now()
            due = []
            with self.lock:
                for r in list(self.items):
                    try:
                        if datetime.fromisoformat(r["when"]) <= now:
                            due.append(r)
                            self.items.remove(r)
                    except Exception:
                        self.items.remove(r)
                if due:
                    self._save()
            for r in due:
                try:
                    self.on_due(r)
                except Exception:
                    pass


# --------------------------------------------------------------------------- #
# Weather (Open-Meteo: free, no key)
# --------------------------------------------------------------------------- #
WEATHER_CODES = {
    0: "clear skies", 1: "mostly clear", 2: "partly cloudy", 3: "overcast", 45: "fog", 48: "icy fog",
    51: "light drizzle", 53: "drizzle", 55: "heavy drizzle", 56: "freezing drizzle", 57: "freezing drizzle",
    61: "light rain", 63: "rain", 65: "heavy rain", 66: "freezing rain", 67: "freezing rain",
    71: "light snow", 73: "snow", 75: "heavy snow", 77: "snow grains", 80: "light showers",
    81: "showers", 82: "heavy showers", 85: "snow showers", 86: "heavy snow showers",
    95: "thunderstorms", 96: "thunderstorms with hail", 99: "thunderstorms with hail",
}


def geocode(city: str):
    q = urllib.parse.quote(city)
    data = _http_json(f"https://geocoding-api.open-meteo.com/v1/search?name={q}&count=1&language=en&format=json")
    res = (data.get("results") or [None])[0]
    if not res:
        return None
    name = res.get("name", city)
    if res.get("country"):
        name += f", {res['country']}"
    return {"lat": res["latitude"], "lon": res["longitude"], "name": name}


def weather_report(cfg: dict, when="today") -> str:
    loc = cfg.get("weather_location")
    if not loc:
        city = (cfg.get("weather_city") or "").strip()
        if not city:
            return "Tell me your city first: it's in Settings, under Skills."
        loc = geocode(city)
        if not loc:
            return f"I couldn't find {city}."
        cfg["weather_location"] = loc  # remember it so we don't look it up every time
    url = (f"https://api.open-meteo.com/v1/forecast?latitude={loc['lat']}&longitude={loc['lon']}"
           "&current=temperature_2m,apparent_temperature,weather_code,wind_speed_10m"
           "&daily=weather_code,temperature_2m_max,temperature_2m_min,precipitation_probability_max"
           "&timezone=auto&forecast_days=2")
    d = _http_json(url)
    place = loc["name"].split(",")[0]
    if when == "tomorrow":
        i = 1
        code = d["daily"]["weather_code"][i]
        return (f"Tomorrow in {place}: {WEATHER_CODES.get(code, 'mixed weather')}, "
                f"{round(d['daily']['temperature_2m_min'][i])} to {round(d['daily']['temperature_2m_max'][i])} degrees, "
                f"{d['daily']['precipitation_probability_max'][i]} percent chance of rain.")
    cur = d["current"]
    rain = d["daily"]["precipitation_probability_max"][0]
    return (f"It's {round(cur['temperature_2m'])} degrees and {WEATHER_CODES.get(cur['weather_code'], 'mixed')} "
            f"in {place}, feels like {round(cur['apparent_temperature'])}. "
            f"Today: {round(d['daily']['temperature_2m_min'][0])} to {round(d['daily']['temperature_2m_max'][0])}, "
            f"{rain} percent chance of rain.")


# --------------------------------------------------------------------------- #
# Quick facts (Wikipedia)
# --------------------------------------------------------------------------- #
def wiki_summary(topic: str, sentences=2) -> str:
    q = urllib.parse.quote(topic)
    found = _http_json(f"https://en.wikipedia.org/w/api.php?action=opensearch&search={q}&limit=1&format=json")
    titles = found[1] if len(found) > 1 else []
    if not titles:
        return ""
    title = urllib.parse.quote(titles[0].replace(" ", "_"))
    data = _http_json(f"https://en.wikipedia.org/api/rest_v1/page/summary/{title}")
    text = data.get("extract", "")
    parts = re.split(r"(?<=[.!?])\s+", text)
    return " ".join(parts[:sentences]).strip()


# --------------------------------------------------------------------------- #
# Roblox Studio helpers
# --------------------------------------------------------------------------- #
def focus_window(title_part: str) -> bool:
    try:
        import pyautogui
        import pygetwindow as gw
        wins = [w for w in gw.getAllWindows() if title_part.lower() in (w.title or "").lower()]
        if not wins:
            return False
        w = wins[0]
        if w.isMinimized:
            w.restore()
        pyautogui.press("alt")  # lets Windows hand focus to another window
        w.activate()
        time.sleep(0.4)
        return True
    except Exception:
        return False


def studio_key(*keys) -> str:
    if not focus_window("Roblox Studio"):
        return "Roblox Studio isn't open."
    import pyautogui
    pyautogui.hotkey(*keys) if len(keys) > 1 else pyautogui.press(keys[0])
    return ""


def open_roblox_game(cfg: dict, name: str) -> str:
    import subprocess
    import webbrowser
    games = {k.lower(): v for k, v in cfg.get("roblox_games", {}).items()}
    key = name.lower().strip()
    if not key:
        return ""
    target = games.get(key)
    if target is None and len(key) >= 3:  # loose match: "open skyline" -> "skyline game"
        target = next((v for k, v in games.items() if key in k or k in key), None)
    if target is None:
        return ""
    if str(target).isdigit():
        webbrowser.open(f"https://www.roblox.com/games/{target}")
        return f"Opening {name} on Roblox."
    if Path(target).exists():
        if os.name == "nt":
            os.startfile(target)
        else:
            subprocess.Popen(["xdg-open", target])
        return f"Opening {name} in Roblox Studio."
    return f"I couldn't find the file for {name}."
