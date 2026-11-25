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
UPDATE_REPO = "cinwukong/Mirage"
UPDATE_BRANCH = "main"
# Files and folders on this PC that an update must never overwrite or delete
KEEP_ON_UPDATE = {"config.json", "model", "mirage.log", "mirage.ico", "__pycache__", ".git", "model.zip",
                  "memory", "reminders.json", ".webview", "voices", "voice_model", "voice_cache"}


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
    "voice_engine": "windows",     # "windows", "mirage" (Mirage's own AI voice) or "voicestudio"
    "mirage_voice": "",            # which of Mirage's own voices to use (id in the voices folder)
    "mirage_voice_quality": "balanced",  # fast, balanced, best
    "voice_id": "",                # "" = system default voice
    "voicestudio_url": "http://localhost:3900",
    "voicestudio_voice": "",       # VoiceStudio voice/profile id ("" = its default)
    "voice_rate": 185,
    "voice_volume": 1.0,
    "speak_replies": True,
    "wake_sound": True,
    "close_to_tray": True,
    "hologram_enabled": True,
    "hologram_corner": "bottom-right",   # top-left, top-right, bottom-left, bottom-right
    "hologram_size": "medium",           # small, medium, large
    "hologram_style": "logo",            # "logo" (purple headband) or "orb"
    "subtitles_enabled": True,           # show Mirage's replies as text under the hologram
    "subtitles_show_you": False,         # also show what you said
    "hearing": "vosk",                   # "vosk" (fast) or "whisper" (accurate)
    "whisper_model": "base.en",          # tiny.en, base.en, small.en
    "vault_path": "",                    # Obsidian vault folder ("" = Mirage's own memory folder)
    "daily_log": False,                  # write a daily log note of what you and Mirage said
    "weather_city": "",
    "weather_location": None,            # filled in automatically from weather_city
    "music_service": "youtube",          # what "play ..." uses: youtube or spotify
    "roblox_games": {},                  # name -> .rbxl file path or place id
    "spotify_playlists": {},             # name -> Spotify link (playlist, album, artist…)
    "brain": "claude_code",              # "claude_code", "api" or "off"
    "claude_model": "haiku",             # haiku (fast), sonnet (balanced), opus (smartest)
    "claude_power": False,               # let Claude Code run commands and edit files
    "voice_commands": [],                # your own shortcuts: {"phrase", "action", "target"}
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
        self._lv_warned = False
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
            elif cfg.get("voice_engine") == "mirage":
                spoken = self._speak_local(text, cfg)
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

    def _speak_local(self, text, cfg) -> bool:
        engine = self.engine
        lv, vl = engine.local_voice, engine.voice_local
        if not lv.ready() and vl.installed():
            lv.load_async(then=engine.voice_loaded)
            if lv._loader is not None:
                lv._loader.join(90)  # it's loading (takes up to a minute); wait rather than switch voices
        if not lv.ready():
            if not self._lv_warned:
                self._lv_warned = True
                engine.emit("system", "Mirage's own voice isn't installed yet (Settings > Voice), so I'm using the Windows voice."
                            if not vl.installed() else "My voice didn't load, so I'm using the Windows voice. " + lv.detail)
            return False
        try:
            voice = vl.get_voice(cfg.get("mirage_voice"))
            speed = max(0.5, min(2.0, int(cfg.get("voice_rate", 185)) / 185))
            lv.speak(text, voice, speed, cfg.get("mirage_voice_quality", "balanced"), float(cfg.get("voice_volume", 1.0)))
            self._lv_warned = False
            return True
        except Exception as e:
            log(f"Built-in voice failed: {e}")
            lv.last_error = f"{type(e).__name__}: {e}"
            if not self._lv_warned:
                self._lv_warned = True
                engine.emit("system", f"My voice had a problem ({e}), so I'm using the Windows voice for now.")
            return False

    def say(self, text: str, show: bool = True, force: bool = False):
        """force: speak even when replies are set to subtitles only (for "play a test sentence")."""
        if not text:
            return
        log(f"MIRAGE: {text}")
        if show:
            self.engine._last_reply = text
            self.engine.emit("reply", text)
        if force or self.engine.cfg.get("speak_replies", True):
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
        import hearing
        import skills
        self.skills = skills
        self.hearing = hearing
        try:
            if skills.fix_vault_setting(self.cfg, log):
                save_config(self.cfg)
        except Exception as e:
            log(f"Couldn't repair the vault setting: {e}")
        self.memory = skills.Memory(lambda: self.cfg)
        self.reminders = skills.Reminders(self._reminder_due)
        self.whisper = hearing.Whisper(log=log)
        self._last_reply = None
        if self.cfg.get("hearing") == "whisper" and hearing.whisper_installed():
            self.whisper.load_async(self.cfg.get("whisper_model", "base.en"))
        import voice_local
        self.voice_local = voice_local
        self.local_voice = voice_local.LocalVoice(log=log, on_change=lambda: self.emit("mirage_voice"),
                                                  whisper=self.whisper)
        if self.cfg.get("voice_engine") == "mirage":
            self.local_voice.load_async(then=self.voice_loaded)
        self.voice = Voice(self)
        self.actions = Actions(self)
        import brains
        self.brains = {"claude_code": brains.ClaudeCodeBrain(self), "api": brains.ApiBrain(self),
                       "off": brains.OffBrain()}

    # ---- events / status ----
    @property
    def brain(self):
        return self.brains.get(self.cfg.get("brain", "claude_code"), self.brains["off"])

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
            self.brains["api"].reload()
        if "claude_model" in changes or "claude_power" in changes:
            threading.Thread(target=self.brains["claude_code"].reset, daemon=True).start()
        if self.cfg.get("hearing") == "whisper" and ("hearing" in changes or "whisper_model" in changes):
            if self.hearing.whisper_installed():
                self.whisper.load_async(self.cfg.get("whisper_model", "base.en"),
                                        lambda ok, msg: self.emit("whisper_status", (ok, msg)))
        if "voice_engine" in changes and changes["voice_engine"] != old.get("voice_engine"):
            if changes["voice_engine"] == "mirage":
                self.local_voice.load_async(then=self.voice_loaded)
            else:  # give the graphics card's memory back
                threading.Thread(target=self.local_voice.unload, daemon=True).start()
        if self.cfg.get("voice_engine") == "mirage" and any(
                k in changes and changes[k] != old.get(k) for k in ("mirage_voice", "voice_rate", "mirage_voice_quality")):
            self.warm_voice()
        if "weather_city" in changes:
            self.cfg["weather_location"] = None
        if "github_token" in changes:
            global GITHUB_TOKEN
            GITHUB_TOKEN = (changes["github_token"] or "").strip()

    def warm_voice(self):
        """Prepare the lines Mirage says most in the current voice, speed and quality."""
        if self.local_voice.ready():
            self.local_voice.warm_up(self.voice_local.get_voice(self.cfg.get("mirage_voice")),
                                     max(0.5, min(2.0, int(self.cfg.get("voice_rate", 185)) / 185)),
                                     self.cfg.get("mirage_voice_quality", "balanced"))

    def voice_loaded(self):
        """Once Mirage's own voice is ready, make sure there's a voice picked to speak with."""
        vl = self.voice_local
        if vl.get_voice(self.cfg.get("mirage_voice")):
            self.warm_voice()
            return
        voices = vl.list_voices()
        if not voices:  # first time: bring over the voices made in VoiceStudio
            for v in vl.voicestudio_voices():
                if v["demo"]:
                    continue
                try:
                    vl.import_voicestudio(v["vs_id"])
                except Exception as e:
                    log(f"Couldn't bring over the VoiceStudio voice {v['name']}: {e}")
            voices = vl.list_voices()
            if voices:
                self.emit("system", "Brought over your VoiceStudio voices: " + ", ".join(v["name"] for v in voices) + ".")
        if not voices:
            try:
                self.local_voice.design_preview(vl.DEFAULT_DESIGN, seed=7, play=False)
                voices = [self.local_voice.design_save("Mirage")]
            except Exception as e:
                log(f"Couldn't make a starting voice: {e}")
                return
        pick = next((v for v in voices if v.get("vs_id") and v["vs_id"] == self.cfg.get("voicestudio_voice")), voices[0])
        self.update_config({"mirage_voice": pick["id"]})  # also prepares its common lines
        self.emit("mirage_voice")

    @property
    def wake_re(self):
        words = tuple(w.lower().strip() for w in self.cfg.get("wake_words", []) if w.strip()) or ("mirage",)
        if self._wake_cache[0] != words:
            pattern = r"\b(" + "|".join(re.escape(w) for w in sorted(words, key=len, reverse=True)) + r")\b"
            self._wake_cache = (words, re.compile(pattern))
        return self._wake_cache[1]

    # ---- background threads ----
    def _whisper_on(self):
        return self.cfg.get("hearing") == "whisper" and self.whisper.ready(self.cfg.get("whisper_model", "base.en"))

    def _worker(self):
        while self.running:
            item = self.cmd_q.get()
            if item is None:
                break
            self.set_status("thinking")
            text = item
            if isinstance(item, tuple):  # ("audio", pcm, vosk_text, had_wake_word)
                _, pcm, fallback, had_wake = item
                try:
                    heard = self.whisper.transcribe(pcm)
                    found, cleaned = self.hearing.strip_wake(heard, self.cfg.get("wake_words", []))
                    log(f"Whisper heard: {heard!r}")
                    text = cleaned if cleaned else fallback
                    if had_wake and not found and fallback:
                        # Whisper didn't write the wake word; trust it only if it's close in length
                        text = cleaned if len(cleaned.split()) <= len(fallback.split()) + 2 else fallback
                except Exception as e:
                    log(f"Whisper failed, using fast recognizer text: {e}")
                    text = fallback
                if not text:
                    self.set_status(self.idle_status())
                    continue
            self._last_reply = None
            try:
                self.handle(text)
                self.memory.log_exchange(text, self._last_reply or "")
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
        utter = bytearray()
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
                utter.clear()
                continue
            if self.status == "awaiting" and time.time() > self.awaiting_until:
                self.set_status(self.idle_status())
            utter.extend(data)
            if len(utter) > SAMPLE_RATE * 2 * 25:  # keep at most ~25 s of one utterance
                del utter[:len(utter) - SAMPLE_RATE * 2 * 25]
            if not rec.AcceptWaveform(data):
                continue
            pcm = bytes(utter)
            utter.clear()
            text = json.loads(rec.Result()).get("text", "").strip()
            if not text:
                continue

            m = self.wake_re.search(text)
            if m:
                command = text[m.end():].strip()
                if command:
                    self.awaiting_until = 0
                    self.cmd_q.put(("audio", pcm, command, True) if self._whisper_on() else command)
                else:
                    self.emit("wake")
                    if self.cfg.get("wake_sound", True):
                        beep()
                    self.awaiting_until = time.time() + timeout() + 2
                    self.set_status("awaiting")
                    self.voice.say("Yes?", show=False)
            elif time.time() < self.awaiting_until:
                self.awaiting_until = 0
                self.cmd_q.put(("audio", pcm, text, False) if self._whisper_on() else text)

    def saved_playlist(self, name):
        lists = {k.lower(): v for k, v in (self.cfg.get("spotify_playlists") or {}).items()}
        name = re.sub(r"^(?:my|the) |(?: playlist| on spotify)+$", "", name.lower().strip()).strip()
        return (name, lists[name]) if name in lists else (name, None)

    def play_playlist(self, name, link):
        import spotify
        uri = spotify.to_uri(link)
        if not uri:
            return f"The Spotify link saved for {name} doesn't look right. Copy it again with Share, Copy link."
        return spotify.open_and_play(uri) or f"Playing {name}."

    def play(self, query, service=None):
        """Play something on YouTube or Spotify (the music setting decides unless told)."""
        name, link = self.saved_playlist(query)
        if link:
            return self.play_playlist(name, link)
        service = (service or self.cfg.get("music_service") or "youtube").lower()
        if service == "spotify":
            try:
                if SYSTEM == "Windows":
                    os.startfile("spotify:search:" + urllib.parse.quote(query))
                else:
                    webbrowser.open("https://open.spotify.com/search/" + urllib.parse.quote(query))
                return f"Here's {query} on Spotify."
            except Exception:
                return "I couldn't open Spotify."
        return self.actions.youtube(query)

    def run_voice_command(self, cmd):
        """Run one of the user's own shortcuts. Returns what to say."""
        action, target = cmd.get("action", "open"), (cmd.get("target") or "").strip()
        a = self.actions
        if action == "say":
            return target
        if action == "type":
            return a.type_text(target)
        if action == "keys":
            try:
                import pyautogui
                keys = [k.strip().lower() for k in re.split(r"[+ ]+", target) if k.strip()]
                pyautogui.hotkey(*keys) if len(keys) > 1 else pyautogui.press(keys[0])
                return ""
            except Exception as e:
                return f"I couldn't press those keys: {e}"
        if action == "run":
            try:
                subprocess.Popen(target, shell=True, cwd=str(Path.home()))
                return "Done."
            except Exception as e:
                return f"That didn't run: {e}"
        # open: website, app, file, folder or link
        if re.match(r"^https?://", target) or re.match(r"^[\w.-]+\.[a-z]{2,}(/|$)", target):
            webbrowser.open(target if target.startswith("http") else "https://" + target)
            return "Opening it."
        try:
            if SYSTEM == "Windows":
                os.startfile(target) if (Path(target).exists() or ":" in target) else \
                    subprocess.Popen(f'start "" "{target}"', shell=True)
            else:
                subprocess.Popen(["xdg-open", target])
            return "Opening it."
        except Exception as e:
            return f"I couldn't open that: {e}"

    def _reminder_due(self, r):
        log(f"Reminder due: {r['text']}")
        beep(); beep()
        self.emit("reminder", r["text"])
        self.voice.say(f"Reminder: {r['text']}")

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

        sk, mem = self.skills, self.memory

        # ---- memory ----
        for cmd in self.cfg.get("voice_commands") or []:
            phrase = re.sub(r"[^\w\s']", "", (cmd.get("phrase") or "").lower()).strip()
            if phrase and re.sub(r"[^\w\s']", "", text).strip() == phrase:
                return say(self.run_voice_command(cmd))

        m = re.match(r"^(?:please )?(?:remember|don'?t forget|note) (?:that )?(.+)$", text)
        if m and not text.startswith("remember to remind"):
            mem.remember(m.group(1))
            return say("Got it. I'll remember that.")
        m = re.match(r"^forget (?:that |about )?(.+)$", text)
        if m:
            n = mem.forget(m.group(1))
            return say("Forgotten." if n else "I couldn't find that in my memory.")
        if re.fullmatch(r"what do you (?:remember|know)(?: about me)?", text):
            lines = [sk.clean_md(l) for l in mem.memory_lines(3)]
            return say("You told me: " + "; ".join(lines) + "." if lines else "You haven't asked me to remember anything yet.")
        m = re.match(r"^(?:what do you (?:remember|know) about|what did i (?:say|tell you) about|"
                     r"search (?:in )?my notes (?:for|about)|search notes for|look in my notes for|"
                     r"find (?:in )?my notes(?: about)?|check my notes (?:for|about)) (.+)$", text)
        if m:
            if self.brain.available():
                return say(self.brain.ask(text))
            hits = mem.search(m.group(1), 3)
            if not hits:
                return say(f"I couldn't find anything about {m.group(1)} in your notes.")
            parts = [sk.clean_md(line) for note, line in hits[:2]]
            return say("From your notes: " + ". ".join(p.rstrip(".") for p in parts)[:320] + ".")

        # ---- to-do list ----
        m = re.match(r"^(?:add|put) (.+?) (?:to|on) (?:my |the )?(?:to ?do|to-do|todo)(?: list)?$", text)
        if m:
            mem.add_todo(m.group(1))
            return say(f"Added {m.group(1)} to your to-do list.")
        if re.search(r"\b(?:what'?s|what is|read|show me|tell me|go through) (?:on )?(?:my|the) (?:to ?do|to-do|todo)", text) \
                or re.fullmatch(r"(?:my )?(?:to ?do|to-do|todo)(?: list)?", text):
            items = mem.todos()
            if not items:
                return say("Your to-do list is empty.")
            more = f", and {len(items) - 5} more" if len(items) > 5 else ""
            return say(f"You have {len(items)} thing{'s' if len(items) != 1 else ''} to do: "
                       + "; ".join(items[:5]) + more + ".")
        m = re.match(r"^(?:mark|check off|tick off|cross off|complete) (.+?)(?: as done| as complete| off)?"
                     r"(?: on my (?:to ?do|to-do|todo) list)?$", text) or re.match(r"^i (?:finished|did|completed) (.+)$", text)
        if m:
            done = mem.complete_todo(m.group(1))
            return say(f"Nice. Checked off {done}." if done else "I couldn't find that on your to-do list.")

        # ---- reminders ----
        if re.search(r"\b(?:what are|list|read|tell me) (?:all )?my reminders\b|\bdo i have any reminders\b", text):
            items = self.reminders.upcoming()
            if not items:
                return say("You have no reminders.")
            parts = [f"{r['text']} {sk.say_time(datetime.fromisoformat(r['when']))}" for r in items[:4]]
            return say("Your reminders: " + "; ".join(parts) + ".")
        if re.search(r"\b(?:cancel|clear|delete|remove) (?:all )?(?:of )?my reminders\b", text):
            n = self.reminders.clear()
            return say(f"Cleared {n} reminder{'s' if n != 1 else ''}." if n else "You had no reminders.")
        if re.search(r"\bremind me\b", text):
            when, rest = sk.parse_when(text)
            what = re.sub(r"^.*?\bremind me\b\s*", "", rest)
            what = re.sub(r"^(?:to|that|about|of)\s+", "", what).strip() or "your reminder"
            what = re.sub(r"\bmy\b", "your", what)
            if when is None:
                return say("When should I remind you? Say for example: remind me at 5 pm to stretch.")
            self.reminders.add(when, what)
            self.emit("reminders_changed")
            return say(f"Okay, I'll remind you {sk.say_time(when)}.")

        # ---- screen ----
        if re.search(r"\b(?:what'?s|what is) on (?:my|the) screen\b|\blook at (?:my|the|this) screen\b|"
                     r"\bwhat am i looking at\b|\b(?:read|check|see) (?:my|the) screen\b|\bon my screen\b", text):
            if not self.brain.available():
                return say("I need my AI brain to look at your screen. Add an API key in settings.")
            return say(self.brain.ask(text, screen=True))

        # ---- weather ----
        if re.search(r"\bweather\b|\btemperature (?:outside|today|tomorrow)\b|\bhow (?:hot|cold|warm) is it\b|"
                     r"\b(?:will|is) it (?:going to )?(?:rain|snow)\b|\bdo i need (?:an umbrella|a jacket)\b", text):
            try:
                return say(sk.weather_report(self.cfg, "tomorrow" if "tomorrow" in text else "today"))
            except Exception as e:
                log(f"Weather failed: {e}")
                return say("I couldn't get the weather right now.")

        # ---- Roblox Studio ----
        if re.fullmatch(r"(?:start |run |begin )?(?:a )?play ?test(?:ing)?(?: the game| my game)?|test (?:the|my) game", text):
            return say(sk.studio_key("f5") or "Starting playtest.")
        if re.fullmatch(r"(?:stop|end|exit) (?:the )?play ?test(?:ing)?", text):
            return say(sk.studio_key("shift", "f5") or "Stopped.")
        if re.fullmatch(r"save (?:the |my )?(?:game|place)(?: in studio)?", text):
            return say(sk.studio_key("ctrl", "s") or "Saved.")

        # ---- Spotify ----
        import spotify
        m = re.fullmatch(r"(?:play|put on|start|switch to|change to|go to|open|"
                         r"(?:switch|change) (?:the )?(?:playlist|music) to) (.+?)", text)
        if m:
            name, link = self.saved_playlist(m.group(1))
            if link:
                return say(self.play_playlist(name, link))
            if re.search(r"\bplaylist\b", text) and name:
                return say(spotify.search(name + " playlist").rstrip(".") + ". Save it under Shortcuts, "
                           "Spotify playlists, and next time I'll start it for you.")
        if re.fullmatch(r"(?:stop|pause|stop playing|pause playing)(?: the| my)? (?:music|song|spotify|playlist)|"
                        r"pause|(?:turn off|shut off) (?:the )?music", text):
            # a bare "pause" may be for a video, so only the music commands check Spotify first
            if text != "pause" and spotify.playing() is False:
                return say("It's already paused.")
            r = a.media("pause")
            return say("Paused." if r == "Done." else r)
        if re.fullmatch(r"(?:play|resume|start|unpause|continue)(?: the| my)? (?:music|song|spotify|playlist)|"
                        r"resume|unpause|play spotify", text):
            state = spotify.playing()
            if state is True and text not in ("resume", "unpause"):
                return say("It's already playing.")
            if state is None and self.cfg.get("music_service") == "spotify" and SYSTEM == "Windows":
                os.startfile("spotify:")
                if not spotify._wait_until(spotify.running, 15):
                    return say("Spotify didn't open.")
                time.sleep(2.5)
            r = a.media("play")
            return say("Playing." if r == "Done." else r)
        if re.fullmatch(r"what(?:'s| is) (?:playing|this song)|what song is (?:this|playing)|"
                        r"which song is this|what(?:'s| is) the song", text):
            song = spotify.now_playing()
            return say(f"This is {song}." if song else "Nothing's playing on Spotify.")

        # ---- music ----
        m = re.match(r"^(?:play|put on) (.+?)(?: on (youtube|spotify))?$", text)
        if m and m.group(1) not in ("music",) and not text.startswith(("play test", "playtest")):
            return say(self.play(m.group(1), m.group(2)))
        m = re.match(r"^(?:search youtube for|youtube) (.+)$", text) or re.match(r"^search (?:for )?(.+) on youtube$", text)
        if m:
            return say(a.youtube(m.group(1)))
        m = re.match(r"^(?:search|google|look up|search for|search google for) (.+)$", text)
        if m:
            return say(a.google(m.group(1)))

        m = re.match(r"^(?:open|launch|start|go to) (.+)$", text)
        if m:
            target = m.group(1).strip()
            game = re.sub(r"^(?:my game|the game|game) |(?: in studio| in roblox studio)$", "", target).strip()
            reply = sk.open_roblox_game(self.cfg, game) or a.open_website(target) or a.open_app(target)
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

        m = re.match(r"^(?:who|what) (?:is|was|are|were) (?:a |an |the )?(.+)$", text) or \
            re.match(r"^(?:tell me about|what do you know about) (.+)$", text)
        if m and not self.brain.available():
            try:
                fact = sk.wiki_summary(m.group(1))
                if fact:
                    return say(fact)
            except Exception as e:
                log(f"Wikipedia failed: {e}")

        say(self.brain.ask(text))



# --------------------------------------------------------------------------- #
# Updates from GitHub
# --------------------------------------------------------------------------- #
def _version_tuple(v: str):
    return tuple(int(x) for x in re.findall(r"\d+", v)[:3]) or (0,)


GITHUB_TOKEN = ""  # set from config by the app/engine


def _github_get(url: str, timeout=15, accept="application/vnd.github+json") -> bytes:
    """GET from GitHub. Uses the saved key if there is one; if GitHub rejects it, tries again
    without it (works for public repositories)."""
    import urllib.error
    import urllib.request

    def fetch(with_key):
        headers = {"User-Agent": "Mirage-updater", "Accept": accept}
        if with_key:
            headers["Authorization"] = f"Bearer {GITHUB_TOKEN}"
        with urllib.request.urlopen(urllib.request.Request(url, headers=headers), timeout=timeout) as r:
            return r.read()

    if not GITHUB_TOKEN:
        return fetch(False)
    try:
        return fetch(True)
    except urllib.error.HTTPError as e:
        if e.code not in (401, 403, 404):
            raise
        log(f"GitHub rejected the saved key (HTTP {e.code}); trying without it.")
        return fetch(False)


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
                return None, False, "Can't see the Mirage repo. If it's private, paste your GitHub key below."
            return None, False, f"GitHub refused the key (error {e.code}). Clear it and paste it again."
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
