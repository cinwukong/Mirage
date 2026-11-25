"""
MIRAGE engine - the listening / speaking / command brain.

Normally started by the app (mirage_app.py). Can also run on its own without a
window:  python mirage.py

Say "mirage" followed by a command, e.g. "mirage open youtube", or just
"mirage", wait for "Yes?", then say the command.
"""

import json
import os
import platform
import queue
import re
import socket
import subprocess
import sys
import threading
import time
import urllib.parse
import webbrowser
import zipfile
from array import array
from datetime import datetime
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent
CONFIG_PATH = BASE_DIR / "config.json"
MODEL_DIR = BASE_DIR / "model"
MODEL_URL = "https://alphacephei.com/vosk/models/vosk-model-small-en-us-0.15.zip"
LOG_PATH = BASE_DIR / "mirage.log"
SYSTEM = platform.system()  # "Windows", "Darwin", "Linux"
SAMPLE_RATE = 16000
INSTANCE_PORT = 47613

# Updates come from this GitHub repository ("owner/name"). Can be changed in config.json.
UPDATE_REPO = "cinwukong/mirage"
UPDATE_BRANCH = "main"
# Files and folders on this PC that an update must never overwrite or delete
KEEP_ON_UPDATE = {"config.json", "model", "mirage.log", "mirage.ico", "__pycache__", ".git", "model.zip"}


def read_version() -> str:
    try:
        return (BASE_DIR / "version.txt").read_text(encoding="utf-8").strip() or "0.0.0"
    except Exception:
        return "0.0.0"


VERSION = read_version()


# --------------------------------------------------------------------------- #
# Logging
# --------------------------------------------------------------------------- #
def log(msg: str) -> None:
    line = f"[{datetime.now():%H:%M:%S}] {msg}"
    try:
        print(line, flush=True)
    except Exception:
        pass
    try:
        if LOG_PATH.exists() and LOG_PATH.stat().st_size > 2_000_000:
            LOG_PATH.unlink()
        with open(LOG_PATH, "a", encoding="utf-8") as f:
            f.write(line + "\n")
    except Exception:
        pass


# --------------------------------------------------------------------------- #
# Config
# --------------------------------------------------------------------------- #
DEFAULT_CONFIG = {
    "wake_words": ["mirage", "mirages", "my rage", "mirror"],
    "command_timeout_seconds": 6,
    "input_device": None,          # None = system default microphone
    "voice_engine": "windows",     # "windows" (built-in voices) or "voicestudio"
    "voice_id": "",                # "" = system default voice
    "voicestudio_url": "http://localhost:3900",
    "voicestudio_voice": "",       # VoiceStudio voice/profile id ("" = its default)
    "voice_rate": 185,
    "voice_volume": 1.0,
    "speak_replies": True,
    "wake_sound": True,
    "close_to_tray": True,
    "anthropic_api_key": "",
    "anthropic_model": "claude-haiku-5-5",
    "update_repo": "",             # "" = use UPDATE_REPO
    "github_token": "",            # read-only key, needed because the repo is private
    "check_updates_on_start": True,
    "websites": {
        "youtube": "https://www.youtube.com",
        "google": "https://www.google.com",
        "gmail": "https://mail.google.com",
        "roblox": "https://www.roblox.com",
        "spotify": "https://open.spotify.com",
        "github": "https://github.com",
        "netflix": "https://www.netflix.com",
        "twitch": "https://www.twitch.tv",
        "reddit": "https://www.reddit.com",
        "chat gpt": "https://chatgpt.com",
        "claude": "https://claude.ai",
    },
    "apps": {
        "Windows": {
            "notepad": "notepad",
            "calculator": "calc",
            "file explorer": "explorer",
            "explorer": "explorer",
            "paint": "mspaint",
            "task manager": "taskmgr",
            "settings": "ms-settings:",
            "command prompt": "cmd",
            "discord": "discord:",
            "steam": "steam:",
            "spotify": "spotify:",
            "roblox studio": "roblox-studio:",
            "chrome": "chrome",
            "edge": "msedge",
        },
        "Darwin": {
            "notes": "Notes", "calculator": "Calculator", "finder": "Finder",
            "safari": "Safari", "chrome": "Google Chrome", "discord": "Discord",
            "spotify": "Spotify", "roblox studio": "RobloxStudio", "terminal": "Terminal",
        },
        "Linux": {
            "calculator": "gnome-calculator", "files": "nautilus",
            "terminal": "gnome-terminal", "firefox": "firefox",
        },
    },
}


def load_config() -> dict:
    defaults = json.loads(json.dumps(DEFAULT_CONFIG))
    if not CONFIG_PATH.exists():
        save_config(defaults)
        log("Created config.json with default settings.")
        return defaults
    try:
        cfg = json.loads(CONFIG_PATH.read_text(encoding="utf-8"))
    except Exception as e:
        log(f"config.json is invalid ({e}); using defaults.")
        return defaults
    for k, v in defaults.items():
        cfg.setdefault(k, v)
    cfg["apps"].setdefault(SYSTEM, {})
    return cfg


def save_config(cfg: dict) -> None:
    tmp = CONFIG_PATH.with_suffix(".tmp")
    tmp.write_text(json.dumps(cfg, indent=2), encoding="utf-8")
    os.replace(tmp, CONFIG_PATH)


# --------------------------------------------------------------------------- #
# Audio helpers
# --------------------------------------------------------------------------- #
def beep():
    try:
        if SYSTEM == "Windows":
            import winsound
            winsound.Beep(880, 110)
        else:
            sys.stdout.write("\a")
            sys.stdout.flush()
    except Exception:
        pass


def _default_hostapi():
    import sounddevice as sd
    try:
        return sd.query_devices(kind="input")["hostapi"]
    except Exception:
        return None


def list_input_devices() -> list:
    """Names of available microphones (one entry per device)."""
    try:
        import sounddevice as sd
        api = _default_hostapi()
        names = []
        for d in sd.query_devices():
            if d["max_input_channels"] > 0 and (api is None or d["hostapi"] == api):
                if d["name"] not in names:
                    names.append(d["name"])
        return names
    except Exception as e:
        log(f"Couldn't list microphones: {e}")
        return []


def resolve_input_device(name):
    if not name:
        return None
    import sounddevice as sd
    api = _default_hostapi()
    for i, d in enumerate(sd.query_devices()):
        if d["max_input_channels"] > 0 and d["name"] == name and (api is None or d["hostapi"] == api):
            return i
    log(f"Microphone '{name}' not found, using the default one.")
    return None


def ensure_model(progress=lambda msg: None):
    if MODEL_DIR.exists() and any(MODEL_DIR.iterdir()):
        return
    import urllib.request
    zip_path = BASE_DIR / "model.zip"
    progress("Downloading speech model (one time, about 40 MB)…")
    log("Downloading speech model...")
    urllib.request.urlretrieve(MODEL_URL, zip_path)
    progress("Unpacking speech model…")
    with zipfile.ZipFile(zip_path) as z:
        z.extractall(BASE_DIR)
        top = z.namelist()[0].split("/")[0]
    (BASE_DIR / top).rename(MODEL_DIR)
    zip_path.unlink()
    log("Speech model ready.")



# --------------------------------------------------------------------------- #
# VoiceStudio (local AI voices, https://github.com/debpalash/VoiceStudio)
# It serves an OpenAI-compatible speech API, by default on localhost:3900.
# --------------------------------------------------------------------------- #
VOICESTUDIO_PRESETS = ["alloy", "echo", "fable", "onyx", "nova", "shimmer"]


def _http(url, data=None, timeout=5.0):
    import urllib.request
    headers = {"Content-Type": "application/json"} if data is not None else {}
    body = json.dumps(data).encode() if data is not None else None
    req = urllib.request.Request(url, data=body, headers=headers, method="POST" if body else "GET")
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return r.read()


def voicestudio_check(base_url: str):
    """Returns (ok, [(id, name)], error_text)."""
    base = base_url.rstrip("/")
    try:
        _http(base + "/health", timeout=3)
    except Exception as e:
        return False, [], f"Not reachable at {base} ({e.__class__.__name__}). Is VoiceStudio open?"
    voices = []
    try:
        data = json.loads(_http(base + "/v1/audio/voices", timeout=5))
        items = data if isinstance(data, list) else (
            data.get("voices") or data.get("data") or data.get("profiles") or [])
        for it in items:
            if isinstance(it, str):
                voices.append((it, it))
            elif isinstance(it, dict):
                vid = it.get("id") or it.get("voice_id") or it.get("profile_id") or it.get("name")
                if vid:
                    voices.append((str(vid), str(it.get("name") or vid)))
    except Exception as e:
        log(f"Couldn't list VoiceStudio voices: {e}")
    return True, voices, ""


def voicestudio_speech(base_url: str, voice: str, text: str, speed: float) -> bytes:
    """Ask VoiceStudio to turn text into a WAV file (bytes)."""
    import urllib.error
    url = base_url.rstrip("/") + "/v1/audio/speech"
    payload = {"model": "tts-1", "voice": voice or "alloy", "input": text,
               "response_format": "wav", "speed": speed}
    try:
        return _http(url, payload, timeout=180)
    except urllib.error.HTTPError as e:
        if e.code in (400, 422):  # engine may not support speed; try without it
            payload.pop("speed")
            return _http(url, payload, timeout=180)
        raise


def wav_with_volume(wav: bytes, volume: float) -> bytes:
    """Scale 16-bit WAV audio by volume (0..1). Other formats are returned unchanged."""
    if volume >= 0.99:
        return wav
    import io
    import wave
    try:
        with wave.open(io.BytesIO(wav)) as w:
            params = w.getparams()
            frames = w.readframes(w.getnframes())
        if params.sampwidth != 2:
            return wav
        a = array("h", frames)
        for i in range(len(a)):
            a[i] = int(a[i] * volume)
        out = io.BytesIO()
        with wave.open(out, "wb") as w:
            w.setparams(params)
            w.writeframes(a.tobytes())
        return out.getvalue()
    except Exception:
        return wav


# --------------------------------------------------------------------------- #
# Speech output
# --------------------------------------------------------------------------- #
class Voice:
    """Text-to-speech on its own thread so listening never blocks."""

    def __init__(self, engine: "Engine"):
        self.engine = engine
        self.q: "queue.Queue" = queue.Queue()
        self.speaking = threading.Event()
        self.ready = threading.Event()
        self.voices: list = []  # [(id, name)]
        self._vs_cache: dict = {}
        self._vs_warned = False
        threading.Thread(target=self._run, daemon=True, name="mirage-tts").start()

    def _run(self):
        tts, default_voice, current = None, None, None
        try:
            import pyttsx3
            tts = pyttsx3.init()
            self.voices = [(v.id, v.name) for v in tts.getProperty("voices")]
            default_voice = current = tts.getProperty("voice")
        except Exception as e:
            log(f"Text-to-speech unavailable ({e}); replies will only be shown.")
        self.ready.set()
        while True:
            text = self.q.get()
            if text is None:
                break
            cfg = self.engine.cfg
            self.speaking.set()
            self.engine.set_status("speaking")
            spoken = False
            if cfg.get("voice_engine") == "voicestudio":
                spoken = self._speak_voicestudio(text, cfg)
            if tts and not spoken:
                try:
                    tts.setProperty("rate", int(cfg.get("voice_rate", 185)))
                    tts.setProperty("volume", max(0.0, min(1.0, float(cfg.get("voice_volume", 1.0)))))
                    want = cfg.get("voice_id") or default_voice
                    if want and want != current:
                        tts.setProperty("voice", want)
                        current = want
                    tts.say(text)
                    tts.runAndWait()
                except Exception as e:
                    log(f"TTS error: {e}")
            if self.q.empty():
                time.sleep(0.3)  # let the echo die out before listening again
                self.speaking.clear()
                self.engine.set_status(self.engine.idle_status())

    def _speak_voicestudio(self, text, cfg) -> bool:
        if SYSTEM != "Windows":
            return False
        try:
            import winsound
            url = cfg.get("voicestudio_url") or "http://localhost:3900"
            voice = cfg.get("voicestudio_voice") or ""
            speed = round(max(0.5, min(2.0, int(cfg.get("voice_rate", 185)) / 185)), 2)
            key = (url, voice, speed, text)
            wav = self._vs_cache.get(key)
            if wav is None:
                wav = voicestudio_speech(url, voice, text, speed)
                if len(text) <= 40:  # remember short, repeated lines like "Yes?"
                    if len(self._vs_cache) > 60:
                        self._vs_cache.clear()
                    self._vs_cache[key] = wav
            wav = wav_with_volume(wav, float(cfg.get("voice_volume", 1.0)))
            winsound.PlaySound(wav, winsound.SND_MEMORY)
            if self._vs_warned:
                self._vs_warned = False
                self.engine.emit("system", "VoiceStudio is back - using its voice again.")
            return True
        except Exception as e:
            log(f"VoiceStudio speech failed: {e}")
            if not self._vs_warned:
                self._vs_warned = True
                self.engine.emit("system", "Couldn't reach VoiceStudio, so I'm using the Windows voice for now. "
                                           "Make sure VoiceStudio is open.")
            return False

    def say(self, text: str, show: bool = True):
        if not text:
            return
        log(f"MIRAGE: {text}")
        if show:
            self.engine.emit("reply", text)
        if self.engine.cfg.get("speak_replies", True):
            self.speaking.set()
            self.q.put(text)


# --------------------------------------------------------------------------- #
# Actions Mirage can perform
# --------------------------------------------------------------------------- #
class Actions:
    def __init__(self, engine: "Engine"):
        self.engine = engine

    @property
    def cfg(self):
        return self.engine.cfg

    def say(self, text):
        self.engine.voice.say(text)

    def _keys(self):
        try:
            import pyautogui
            pyautogui.FAILSAFE = False
            return pyautogui
        except Exception as e:
            log(f"pyautogui unavailable: {e}")
            return None

    def open_website(self, name_or_url: str) -> str:
        sites = {k.lower(): v for k, v in self.cfg["websites"].items()}
        key = name_or_url.lower().strip()
        if key in sites:
            url = sites[key]
        elif re.match(r"^https?://", key):
            url = name_or_url
        elif "." in key and " " not in key:
            url = "https://" + key
        else:
            return ""
        webbrowser.open(url)
        return f"Opening {name_or_url}."

    def google(self, query: str) -> str:
        webbrowser.open("https://www.google.com/search?q=" + urllib.parse.quote_plus(query))
        return f"Searching for {query}."

    def youtube(self, query: str) -> str:
        webbrowser.open("https://www.youtube.com/results?search_query=" + urllib.parse.quote_plus(query))
        return f"Here's {query} on YouTube."

    def open_app(self, name: str) -> str:
        apps = {k.lower(): v for k, v in self.cfg["apps"].get(SYSTEM, {}).items()}
        key = name.lower().strip()
        target = apps.get(key)
        try:
            if SYSTEM == "Windows":
                subprocess.Popen(f'start "" "{target or key}"', shell=True)
            elif SYSTEM == "Darwin":
                subprocess.Popen(["open", "-a", target or name])
            else:
                subprocess.Popen([target or key])
            return f"Opening {name}."
        except Exception as e:
            log(f"open_app failed: {e}")
            return f"I couldn't open {name}. You can add it under Shortcuts in the app."

    def media(self, action: str) -> str:
        keys = {
            "volume up": ("volumeup", 5), "volume down": ("volumedown", 5),
            "mute": ("volumemute", 1), "unmute": ("volumemute", 1),
            "pause": ("playpause", 1), "play": ("playpause", 1), "resume": ("playpause", 1),
            "next": ("nexttrack", 1), "previous": ("prevtrack", 1),
        }
        if action not in keys:
            return ""
        pg = self._keys()
        if not pg:
            return "I can't control media keys on this computer."
        key, times = keys[action]
        for _ in range(times):
            pg.press(key)
        return "" if action in ("volume up", "volume down") else "Done."

    def type_text(self, text: str) -> str:
        pg = self._keys()
        if not pg:
            return "I can't type on this computer."
        time.sleep(0.5)
        pg.write(text, interval=0.02)
        return ""

    def screenshot(self) -> str:
        pg = self._keys()
        if not pg:
            return "I can't take screenshots on this computer."
        folder = Path.home() / "Pictures" / "Mirage"
        folder.mkdir(parents=True, exist_ok=True)
        path = folder / f"screenshot_{datetime.now():%Y-%m-%d_%H-%M-%S}.png"
        pg.screenshot(str(path))
        return "Screenshot saved in your Pictures folder."

    def close_window(self) -> str:
        pg = self._keys()
        if not pg:
            return "I can't do that on this computer."
        pg.hotkey("command", "q") if SYSTEM == "Darwin" else pg.hotkey("alt", "f4")
        return ""

    def lock(self) -> str:
        if SYSTEM == "Windows":
            subprocess.Popen("rundll32.exe user32.dll,LockWorkStation", shell=True)
        elif SYSTEM == "Darwin":
            subprocess.Popen(["pmset", "displaysleepnow"])
        else:
            subprocess.Popen(["loginctl", "lock-session"])
        return "Locking."

    def set_timer(self, seconds: int, label: str = "") -> str:
        def done():
            beep(); beep()
            self.say(f"Your {label + ' ' if label else ''}timer is done.")
        threading.Timer(seconds, done).start()
        return f"Timer set for {describe_duration(seconds)}."

    def tell_time(self) -> str:
        return f"It's {datetime.now().strftime('%H:%M')}."

    def tell_date(self) -> str:
        return f"Today is {datetime.now().strftime('%A, %B %d')}."


# --------------------------------------------------------------------------- #
# Spoken-number helpers
# --------------------------------------------------------------------------- #
NUM_WORDS = {
    "zero": 0, "a": 1, "an": 1, "one": 1, "two": 2, "three": 3, "four": 4, "five": 5,
    "six": 6, "seven": 7, "eight": 8, "nine": 9, "ten": 10, "eleven": 11,
    "twelve": 12, "thirteen": 13, "fourteen": 14, "fifteen": 15, "sixteen": 16,
    "seventeen": 17, "eighteen": 18, "nineteen": 19, "twenty": 20, "thirty": 30,
    "forty": 40, "fifty": 50, "sixty": 60, "ninety": 90,
}


def parse_duration(text: str) -> int:
    """'five minutes', 'one hour and thirty minutes', 'two and a half minutes', '90 seconds'."""
    tokens = text.replace("-", " ").split()
    seconds = 0.0
    for i, tok in enumerate(tokens):
        if not re.fullmatch(r"(hours?|minutes?|mins?|seconds?|secs?)", tok):
            continue
        unit = 3600 if tok.startswith("h") else 60 if tok.startswith("m") else 1
        j, n, found = i - 1, 0.0, False
        while j >= 0:
            w = tokens[j]
            if w == "half":
                n += 0.5; found = True
                if j - 1 >= 0 and tokens[j - 1] in ("a", "an"):
                    j -= 1
                if j - 1 >= 0 and tokens[j - 1] == "and":
                    j -= 1
            elif w.isdigit():
                n += int(w); found = True
            elif w in NUM_WORDS:
                n += NUM_WORDS[w]; found = True
            else:
                break
            j -= 1
        seconds += (n if found else 0) * unit
    return int(seconds)


def describe_duration(s: int) -> str:
    parts = []
    for name, size in (("hour", 3600), ("minute", 60), ("second", 1)):
        if s >= size:
            n, s = divmod(s, size)
            parts.append(f"{n} {name}{'s' if n != 1 else ''}")
    return " and ".join(parts) or "0 seconds"


# --------------------------------------------------------------------------- #
# Optional AI brain (Claude)
# --------------------------------------------------------------------------- #
class Brain:
    TOOLS = [
        {"name": "open_website", "description": "Open a website by name or URL.",
         "input_schema": {"type": "object", "properties": {"site": {"type": "string"}}, "required": ["site"]}},
        {"name": "open_app", "description": "Open an application on the computer.",
         "input_schema": {"type": "object", "properties": {"name": {"type": "string"}}, "required": ["name"]}},
        {"name": "google", "description": "Search Google.",
         "input_schema": {"type": "object", "properties": {"query": {"type": "string"}}, "required": ["query"]}},
        {"name": "youtube", "description": "Search YouTube / play a video or song.",
         "input_schema": {"type": "object", "properties": {"query": {"type": "string"}}, "required": ["query"]}},
        {"name": "media", "description": "Media/volume control.",
         "input_schema": {"type": "object", "properties": {"action": {"type": "string", "enum": [
             "volume up", "volume down", "mute", "pause", "play", "next", "previous"]}}, "required": ["action"]}},
        {"name": "set_timer", "description": "Set a countdown timer.",
         "input_schema": {"type": "object", "properties": {"seconds": {"type": "integer"},
                                                           "label": {"type": "string"}}, "required": ["seconds"]}},
        {"name": "screenshot", "description": "Take a screenshot.",
         "input_schema": {"type": "object", "properties": {}}},
        {"name": "type_text", "description": "Type text with the keyboard into the focused window.",
         "input_schema": {"type": "object", "properties": {"text": {"type": "string"}}, "required": ["text"]}},
    ]

    def __init__(self, engine: "Engine"):
        self.engine = engine
        self.client = None
        self.history: list = []
        self.reload()

    def reload(self):
        cfg = self.engine.cfg
        key = cfg.get("anthropic_api_key") or os.environ.get("ANTHROPIC_API_KEY", "")
        self.client = None
        if key:
            try:
                import anthropic
                self.client = anthropic.Anthropic(api_key=key)
                log("AI brain enabled.")
            except Exception as e:
                log(f"AI brain unavailable: {e}")

    def ask(self, text: str) -> str:
        if not self.client:
            return "Sorry, I don't know how to do that yet. Add an API key in settings to make me smarter."
        system = (
            "You are Mirage, a voice assistant running on the user's computer, like JARVIS. "
            "Your replies are spoken aloud, so keep them short (1-2 sentences), "
            "conversational, and never use markdown, lists or emojis. "
            f"The current time is {datetime.now():%A %Y-%m-%d %H:%M}. "
            "Use the tools when the user wants something done on the computer. "
            "The input may come from speech recognition and contain mis-heard words; "
            "interpret it sensibly."
        )
        self.history.append({"role": "user", "content": text})
        self.history = self.history[-10:]
        while self.history and self.history[0]["role"] != "user":
            self.history.pop(0)
        try:
            resp = self.client.messages.create(
                model=self.engine.cfg.get("anthropic_model") or "claude-haiku-5-5",
                max_tokens=300, system=system, tools=self.TOOLS, messages=self.history,
            )
        except Exception as e:
            log(f"AI error: {e}")
            self.history.pop()
            return "I couldn't reach my brain right now."

        spoken, did_something = [], False
        for block in resp.content:
            if block.type == "text":
                spoken.append(block.text)
            elif block.type == "tool_use":
                did_something = True
                self.run_tool(block.name, block.input)
        reply = " ".join(spoken).strip() or ("Done." if did_something else "")
        self.history.append({"role": "assistant", "content": reply or "Done."})
        return reply

    def run_tool(self, name: str, args: dict):
        a = self.engine.actions
        log(f"AI tool: {name} {args}")
        try:
            if name == "open_website":
                a.open_website(args["site"]) or a.google(args["site"])
            elif name == "open_app":
                a.open_app(args["name"])
            elif name == "google":
                a.google(args["query"])
            elif name == "youtube":
                a.youtube(args["query"])
            elif name == "media":
                a.media(args["action"])
            elif name == "set_timer":
                a.set_timer(int(args["seconds"]), args.get("label", ""))
            elif name == "screenshot":
                a.screenshot()
            elif name == "type_text":
                a.type_text(args["text"])
        except Exception as e:
            log(f"Tool {name} failed: {e}")


# --------------------------------------------------------------------------- #
# The engine
# --------------------------------------------------------------------------- #
class Engine:
    """
    Events sent to listeners as (kind, data):
      status (status, detail) | heard text | reply text | level 0..1 |
      wake | muted bool | show_window | quit
    Status values: loading, listening, awaiting, thinking, speaking, muted, error
    """

    def __init__(self, on_event=None):
        self.cfg = load_config()
        self._listeners = [on_event] if on_event else []
        self.status, self.status_detail = "loading", ""
        self.mic_muted = False
        self.mic_error = False
        self.error_detail = ""
        self.awaiting_until = 0.0
        self.running = True
        self._restart_audio = threading.Event()
        self.cmd_q: "queue.Queue" = queue.Queue()
        self._wake_cache = (None, None)
        global GITHUB_TOKEN
        GITHUB_TOKEN = (self.cfg.get("github_token") or "").strip()
        self.voice = Voice(self)
        self.actions = Actions(self)
        self.brain = Brain(self)

    # ---- events / status ----
    def emit(self, kind, data=None):
        for fn in self._listeners:
            try:
                fn(kind, data)
            except Exception as e:
                log(f"listener error: {e}")

    def set_status(self, status, detail=""):
        if status == "error":
            detail = detail or self.error_detail
            self.error_detail = detail
        if (status, detail) != (self.status, self.status_detail):
            self.status, self.status_detail = status, detail
            self.emit("status", (status, detail))

    def idle_status(self):
        if self.mic_error:
            return "error"
        if self.mic_muted:
            return "muted"
        if time.time() < self.awaiting_until:
            return "awaiting"
        return "listening"

    # ---- control from the app ----
    def start(self):
        threading.Thread(target=self._audio_loop, daemon=True, name="mirage-audio").start()
        threading.Thread(target=self._worker, daemon=True, name="mirage-worker").start()

    def stop(self):
        self.running = False
        self._restart_audio.set()
        self.cmd_q.put(None)
        self.voice.q.put(None)

    def submit_text(self, text: str):
        text = text.strip()
        if text:
            self.cmd_q.put(text)

    def set_muted(self, muted: bool):
        self.mic_muted = bool(muted)
        self.awaiting_until = 0
        log("Microphone muted." if muted else "Microphone on.")
        self.emit("muted", self.mic_muted)
        if not self.voice.speaking.is_set():
            self.set_status(self.idle_status())

    def update_config(self, changes: dict):
        old = dict(self.cfg)
        self.cfg.update(changes)
        try:
            save_config(self.cfg)
        except Exception as e:
            log(f"Couldn't save settings: {e}")
        if "input_device" in changes and changes["input_device"] != old.get("input_device"):
            self._restart_audio.set()
        if "anthropic_api_key" in changes or "anthropic_model" in changes:
            self.brain.reload()
        if "github_token" in changes:
            global GITHUB_TOKEN
            GITHUB_TOKEN = (changes["github_token"] or "").strip()

    @property
    def wake_re(self):
        words = tuple(w.lower().strip() for w in self.cfg.get("wake_words", []) if w.strip()) or ("mirage",)
        if self._wake_cache[0] != words:
            pattern = r"\b(" + "|".join(re.escape(w) for w in sorted(words, key=len, reverse=True)) + r")\b"
            self._wake_cache = (words, re.compile(pattern))
        return self._wake_cache[1]

    # ---- background threads ----
    def _worker(self):
        while self.running:
            text = self.cmd_q.get()
            if text is None:
                break
            self.set_status("thinking")
            try:
                self.handle(text)
            except Exception as e:
                log(f"Error handling '{text}': {e}")
                self.voice.say("Something went wrong.")
            if not self.voice.speaking.is_set():
                self.set_status(self.idle_status())

    def _audio_loop(self):
        try:
            self.set_status("loading", "Preparing speech recognition…")
            ensure_model(lambda msg: self.set_status("loading", msg))
            import sounddevice as sd
            from vosk import Model, KaldiRecognizer, SetLogLevel
            SetLogLevel(-1)
            model = Model(str(MODEL_DIR))
        except Exception as e:
            log(f"Speech recognition failed to load: {e}")
            self.mic_error = True
            self.set_status("error", f"Speech recognition failed to load: {e}")
            return

        first = True
        while self.running:
            self._restart_audio.clear()
            audio_q: "queue.Queue" = queue.Queue()

            def callback(indata, frames, t, status):
                audio_q.put(bytes(indata))

            try:
                device = resolve_input_device(self.cfg.get("input_device"))
                rec = KaldiRecognizer(model, SAMPLE_RATE)
                with sd.RawInputStream(samplerate=SAMPLE_RATE, blocksize=2000, dtype="int16",
                                       channels=1, device=device, callback=callback):
                    self.mic_error = False
                    self.set_status(self.idle_status())
                    log(f"Listening on: {self.cfg.get('input_device') or 'default microphone'}")
                    if first:
                        first = False
                        self.voice.say("Mirage online.")
                    self._listen(rec, audio_q)
            except Exception as e:
                log(f"Microphone error: {e}")
                self.mic_error = True
                self.set_status("error", f"Microphone problem: {e}")
                self._restart_audio.wait(5)

    def _listen(self, rec, audio_q):
        timeout = lambda: float(self.cfg.get("command_timeout_seconds", 6))
        while self.running and not self._restart_audio.is_set():
            try:
                data = audio_q.get(timeout=0.5)
            except queue.Empty:
                continue
            if self.mic_muted:
                self.emit("level", 0.0)
                rec.Reset()
                continue
            samples = array("h", data)
            self.emit("level", (max(max(samples), -min(samples)) / 32768) if samples else 0.0)
            if self.voice.speaking.is_set():
                rec.Reset()  # don't listen to ourselves
                continue
            if self.status == "awaiting" and time.time() > self.awaiting_until:
                self.set_status(self.idle_status())
            if not rec.AcceptWaveform(data):
                continue
            text = json.loads(rec.Result()).get("text", "").strip()
            if not text:
                continue

            m = self.wake_re.search(text)
            if m:
                command = text[m.end():].strip()
                if command:
                    self.awaiting_until = 0
                    self.cmd_q.put(command)
                else:
                    self.emit("wake")
                    if self.cfg.get("wake_sound", True):
                        beep()
                    self.awaiting_until = time.time() + timeout() + 2
                    self.set_status("awaiting")
                    self.voice.say("Yes?", show=False)
            elif time.time() < self.awaiting_until:
                self.awaiting_until = 0
                self.cmd_q.put(text)

    # ---- command router ----
    def handle(self, text: str):
        text = text.lower().strip().rstrip(".!?")
        log(f"YOU: {text}")
        self.emit("heard", text)
        a, say = self.actions, self.voice.say

        if re.fullmatch(r"(shut ?down|turn off|exit|quit|go to sleep|goodbye)( yourself| mirage)?", text):
            say("Shutting down. Goodbye.")
            time.sleep(2.5)
            self.emit("quit")
            self.stop()
            return
        if text in ("never mind", "nevermind", "cancel", "nothing", "stop"):
            return
        if re.fullmatch(r"(open|show) (your )?(settings|yourself|the app|your window|mirage|the interface)|show yourself", text):
            self.emit("show_window")
            return say("Here I am.")
        if re.fullmatch(r"(mute (the |your )?(mic|microphone)|stop listening)", text):
            say("Microphone muted. Unmute me in the app.")
            self.set_muted(True)
            return

        m = re.match(r"^(?:play|put on) (.+?)(?: on youtube)?$", text)
        if m and m.group(1) not in ("music",):
            return say(a.youtube(m.group(1)))
        m = re.match(r"^(?:search youtube for|youtube) (.+)$", text) or re.match(r"^search (?:for )?(.+) on youtube$", text)
        if m:
            return say(a.youtube(m.group(1)))
        m = re.match(r"^(?:search|google|look up|search for|search google for) (.+)$", text)
        if m:
            return say(a.google(m.group(1)))

        m = re.match(r"^(?:open|launch|start|go to) (.+)$", text)
        if m:
            target = m.group(1).strip()
            reply = a.open_website(target) or a.open_app(target)
            return say(reply)

        if re.search(r"\b(set (a )?timer|timer for|remind me in)\b", text):
            secs = parse_duration(text)
            if secs <= 0:
                return say("How long should the timer be?")
            return say(a.set_timer(secs))

        if re.search(r"\bwhat time\b|\bthe time\b", text):
            return say(a.tell_time())
        if re.search(r"\bwhat day\b|\bthe date\b|\bwhat'?s today\b", text):
            return say(a.tell_date())

        for phrase, action in (("volume up", "volume up"), ("louder", "volume up"),
                               ("turn it up", "volume up"), ("volume down", "volume down"),
                               ("quieter", "volume down"), ("turn it down", "volume down"),
                               ("unmute", "unmute"), ("mute", "mute"),
                               ("next song", "next"), ("next track", "next"), ("skip", "next"),
                               ("previous song", "previous"), ("previous track", "previous"),
                               ("pause", "pause"), ("resume", "resume"), ("play music", "play")):
            if phrase in text:
                return say(a.media(action))

        if "screenshot" in text or "screen shot" in text:
            return say(a.screenshot())
        m = re.match(r"^(?:type|write) (.+)$", text)
        if m:
            return say(a.type_text(m.group(1)))
        if re.search(r"\b(lock (the |my )?(computer|pc|screen))\b", text):
            return say(a.lock())
        if re.search(r"\bclose (this |the )?(window|app|program)\b", text):
            return say(a.close_window())
        if re.fullmatch(r"(hello|hi|hey)( there)?", text):
            return say("Hello. What can I do for you?")

        say(self.brain.ask(text))



# --------------------------------------------------------------------------- #
# Updates from GitHub
# --------------------------------------------------------------------------- #
def _version_tuple(v: str):
    return tuple(int(x) for x in re.findall(r"\d+", v)[:3]) or (0,)


GITHUB_TOKEN = ""  # set from config by the app/engine


def _github_get(url: str, timeout=15, accept="application/vnd.github+json") -> bytes:
    import urllib.request
    headers = {"User-Agent": "Mirage-updater", "Accept": accept}
    if GITHUB_TOKEN:
        headers["Authorization"] = f"Bearer {GITHUB_TOKEN}"
    req = urllib.request.Request(url, headers=headers)
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return r.read()


def update_repo(cfg: dict) -> str:
    return (cfg.get("update_repo") or UPDATE_REPO or "").strip().strip("/")


def check_for_update(repo: str):
    """Returns (latest_version or None, newer: bool, error_text)."""
    import urllib.error
    if not repo:
        return None, False, "Updates aren't set up yet (no GitHub repository)."
    try:
        latest = _github_get(f"https://api.github.com/repos/{repo}/contents/version.txt?ref={UPDATE_BRANCH}",
                             accept="application/vnd.github.raw").decode("utf-8").strip()
    except urllib.error.HTTPError as e:
        if e.code in (401, 403, 404):
            if not GITHUB_TOKEN:
                return None, False, "The Mirage repo is private: paste your GitHub key below first."
            return None, False, "GitHub refused the key. Check it can read cinwukong/mirage and hasn't expired."
        return None, False, f"Couldn't check GitHub (error {e.code})."
    except Exception as e:
        return None, False, f"Couldn't reach GitHub ({e.__class__.__name__})."
    return latest, _version_tuple(latest) > _version_tuple(read_version()), ""


def apply_update(repo: str, progress=lambda msg: None) -> list:
    """Download the repository and copy its files over this folder. Returns changed file names."""
    import io
    import shutil
    import tempfile
    progress("Downloading update…")
    data = _github_get(f"https://api.github.com/repos/{repo}/zipball/{UPDATE_BRANCH}", timeout=120)
    changed = []
    with tempfile.TemporaryDirectory() as tmp:
        tmp = Path(tmp)
        with zipfile.ZipFile(io.BytesIO(data)) as z:
            for name in z.namelist():  # refuse paths that try to escape the folder
                if name.startswith("/") or ".." in Path(name).parts:
                    raise RuntimeError(f"Unsafe path in update: {name}")
            z.extractall(tmp)
        roots = [p for p in tmp.iterdir() if p.is_dir()]
        if len(roots) != 1 or not (roots[0] / "mirage.py").exists():
            raise RuntimeError("The download doesn't look like Mirage.")
        root = roots[0]
        progress("Installing update…")
        for src in root.rglob("*"):
            rel = src.relative_to(root)
            if rel.parts[0] in KEEP_ON_UPDATE or src.is_dir():
                continue
            dest = BASE_DIR / rel
            new = src.read_bytes()
            if dest.exists() and dest.read_bytes() == new:
                continue
            dest.parent.mkdir(parents=True, exist_ok=True)
            tmp_dest = dest.with_name(dest.name + ".new")
            tmp_dest.write_bytes(new)
            os.replace(tmp_dest, dest)
            changed.append(str(rel))
    if "requirements.txt" in changed:
        progress("Installing new packages…")
        python = Path(sys.executable)
        if python.name.lower() == "pythonw.exe":
            python = python.with_name("python.exe")
        flags = 0x08000000 if SYSTEM == "Windows" else 0  # CREATE_NO_WINDOW
        subprocess.run([str(python), "-m", "pip", "install", "-r", str(BASE_DIR / "requirements.txt")],
                       creationflags=flags, check=False)
    log(f"Updated to {read_version()}: {', '.join(changed) or 'no file changes'}")
    return changed

# --------------------------------------------------------------------------- #
# Single instance: a second launch asks the running one to show its window
# --------------------------------------------------------------------------- #
def acquire_instance(on_show=None):
    s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    try:
        s.bind(("127.0.0.1", INSTANCE_PORT))
        s.listen(4)
    except OSError:
        try:
            c = socket.create_connection(("127.0.0.1", INSTANCE_PORT), timeout=1)
            c.sendall(b"show")
            c.close()
        except Exception:
            pass
        return None

    def accept_loop():
        while True:
            try:
                conn, _ = s.accept()
                data = conn.recv(16)
                conn.close()
            except OSError:
                break
            if data == b"show" and on_show:
                on_show()

    threading.Thread(target=accept_loop, daemon=True).start()
    return s


if __name__ == "__main__":
    if not acquire_instance():
        log("Mirage is already running.")
        sys.exit(0)
    engine = Engine()
    engine.start()
    try:
        while engine.running:
            time.sleep(0.5)
    except KeyboardInterrupt:
        engine.stop()
    log("Mirage stopped.")
