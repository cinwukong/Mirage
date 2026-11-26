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
                  "memory", "reminders.json", ".webview", "voices", "voice_model", "voice_cache", "speech"}


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
    "kokoro_voice": "af_bella",    # Mirage's own voice (Kokoro), see speech.VOICES
    "voice_pitch": 0,              # semitones, -6 to 6
    "voice_robot": 0,              # 0 to 100: how robotic the hologram sounds
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
    "builtins_off": [],                  # built-in command groups you turned off (see BUILTIN_GROUPS)
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
                spoken = self._speak_kokoro(text)
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

    def _speak_kokoro(self, text) -> bool:
        engine = self.engine
        sp = engine.speech
        if not sp.ready() and engine.speech_mod.installed():
            sp.load_async(then=engine.speech_loaded)
            sp.wait_loaded(60)  # it's loading (a few seconds); wait rather than switch voices
        if not sp.ready():
            if not self._lv_warned:
                self._lv_warned = True
                engine.emit("system", "Mirage's own voice isn't installed yet (Settings > Voice), so I'm using the Windows voice."
                            if not engine.speech_mod.installed() else "My voice didn't load, so I'm using the Windows voice. " + sp.detail)
            return False
        try:
            voice, speed, pitch, robot = engine.voice_settings()
            sp.speak(text, voice, speed, pitch, robot, float(engine.cfg.get("voice_volume", 1.0)))
            self._lv_warned = False
            return True
        except Exception as e:
            log(f"Mirage's voice failed: {e}")
            sp.last_error = f"{type(e).__name__}: {e}"
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
        import skills
        self.skills = skills
        try:
            if skills.fix_vault_setting(self.cfg, log):
                save_config(self.cfg)
        except Exception as e:
            log(f"Couldn't repair the vault setting: {e}")
        self.memory = skills.Memory(lambda: self.cfg)
        self.reminders = skills.Reminders(self._reminder_due)
        self._last_reply = None
        import speech
        self.speech_mod = speech
        self.speech = speech.Speech(log=log, on_change=lambda: self.emit("speech"))
        self.speech.load_async(then=self.speech_loaded)
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
        if self.cfg.get("voice_engine") == "mirage" and any(
                k in changes and changes[k] != old.get(k) for k in ("kokoro_voice", "voice_rate", "voice_pitch", "voice_robot", "voice_engine")):
            self.warm_voice()
        if "weather_city" in changes:
            self.cfg["weather_location"] = None
        if "github_token" in changes:
            global GITHUB_TOKEN
            GITHUB_TOKEN = (changes["github_token"] or "").strip()

    COMMON_LINES = ["Mirage online.", "Yes?", "Done.", "Playing.", "Paused.", "Got it. I'll remember that.",
                    "Hello. This is how I sound.", "It's already playing.", "It's already paused.", "Here I am.",
                    "How long should the timer be?", "Something went wrong.", "Opening it."]

    def voice_settings(self):
        c = self.cfg
        return (c.get("kokoro_voice") or self.speech_mod.DEFAULT_VOICE,
                max(0.5, min(2.0, int(c.get("voice_rate", 185)) / 185)),
                int(c.get("voice_pitch", 0) or 0), int(c.get("voice_robot", 0) or 0))

    def warm_voice(self):
        """Prepare the lines Mirage says most with the current voice settings, so they play instantly."""
        if self.speech.ready() and self.cfg.get("voice_engine") == "mirage":
            self.speech.warm_up(*self.voice_settings(), self.COMMON_LINES)

    def speech_loaded(self):
        """Mirage's own voice and ears are ready: switch the microphone over to them and tidy up."""
        if self.cfg.get("voice_engine") == "windows" and not self.cfg.get("_speech_switched"):
            self.update_config({"voice_engine": "mirage", "_speech_switched": True})  # first time: use the new voice
        self.warm_voice()
        if getattr(self, "_on_vosk", False):
            self._restart_audio.set()  # hear with Parakeet from now on
        threading.Thread(target=self.speech_mod.remove_old_engines, args=(log,), daemon=True).start()
        self.emit("speech")

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
            item = self.cmd_q.get()
            if item is None:
                break
            self.set_status("thinking")
            text = item
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
        self.set_status("loading", "Preparing speech recognition…")
        if self.speech_mod.installed():
            self.speech.wait_loaded(90)
        model = None
        first = True
        while self.running:
            self._restart_audio.clear()
            audio_q: "queue.Queue" = queue.Queue()
            parakeet = self.speech.ready()
            if not parakeet and model is None:
                try:  # the basic recognizer, until Mirage's own ears are installed
                    ensure_model(lambda msg: self.set_status("loading", msg))
                    from vosk import Model, KaldiRecognizer, SetLogLevel
                    SetLogLevel(-1)
                    model = Model(str(MODEL_DIR))
                except Exception as e:
                    log(f"Speech recognition failed to load: {e}")
                    self.mic_error = True
                    self.set_status("error", f"Speech recognition failed to load: {e}")
                    self._restart_audio.wait(30)
                    continue
            self._on_vosk = not parakeet

            def callback(indata, frames, t, status):
                audio_q.put(bytes(indata))

            try:
                import sounddevice as sd
                device = resolve_input_device(self.cfg.get("input_device"))
                rec = None
                if not parakeet:
                    from vosk import KaldiRecognizer
                    rec = KaldiRecognizer(model, SAMPLE_RATE)
                with sd.RawInputStream(samplerate=SAMPLE_RATE, blocksize=2000, dtype="int16",
                                       channels=1, device=device, callback=callback):
                    self.mic_error = False
                    self.set_status(self.idle_status())
                    log(f"Listening on: {self.cfg.get('input_device') or 'default microphone'}"
                        f" ({'Parakeet' if parakeet else 'basic recognizer'})")
                    if first:
                        first = False
                        self.voice.say("Mirage online.")
                    if parakeet:
                        self._listen_parakeet(audio_q)
                    else:
                        self._listen(rec, audio_q)
            except Exception as e:
                log(f"Microphone error: {e}")
                self.mic_error = True
                self.set_status("error", f"Microphone problem: {e}")
                self._restart_audio.wait(5)

    def _listen_parakeet(self, audio_q):
        """Cut the mic into pieces of speech; a separate thread writes each down and looks for the wake word."""
        import numpy as np
        listener = self.speech_mod.Listener(self.speech)
        pieces: "queue.Queue" = queue.Queue()
        stop = threading.Event()
        threading.Thread(target=self._ears, args=(pieces, stop), daemon=True, name="mirage-ears").start()
        try:
            while self.running and not self._restart_audio.is_set():
                try:
                    data = audio_q.get(timeout=0.5)
                except queue.Empty:
                    continue
                if self.mic_muted:
                    self.emit("level", 0.0)
                    listener.reset()
                    continue
                x = np.frombuffer(data, dtype="<i2").astype(np.float32) / 32768
                self.emit("level", float(np.max(np.abs(x))) if len(x) else 0.0)
                if self.voice.speaking.is_set():
                    listener.reset()  # don't listen to ourselves
                    continue
                if self.status == "awaiting" and time.time() > self.awaiting_until:
                    self.set_status(self.idle_status())
                for piece in listener.feed(x):
                    pieces.put(piece)
        finally:
            stop.set()
            pieces.put(None)

    def _ears(self, pieces, stop):
        timeout = lambda: float(self.cfg.get("command_timeout_seconds", 6))
        while not stop.is_set():
            piece = pieces.get()
            if piece is None:
                break
            try:
                heard = self.speech.transcribe(piece)
            except Exception as e:
                log(f"Hearing failed: {e}")
                continue
            if not heard:
                continue
            found, command = self.speech_mod.strip_wake(heard, self.cfg.get("wake_words", []))
            if found:
                log(f"Heard: {heard!r}")
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
            elif time.time() < self.awaiting_until and command:
                log(f"Heard: {heard!r}")
                self.awaiting_until = 0
                self.cmd_q.put(command)

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
        if link and "spotify" not in (self.cfg.get("builtins_off") or []):
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
        sk, mem = self.skills, self.memory
        off = set(self.cfg.get("builtins_off") or [])

        def on(group):
            return group not in off

        # ---- your own voice commands come first, so they win over anything built in ----
        plain = re.sub(r"[^\w\s']", "", text).strip()
        for cmd in self.cfg.get("voice_commands") or []:
            phrase = re.sub(r"[^\w\s']", "", (cmd.get("phrase") or "").lower()).strip()
            if phrase and plain == phrase:
                return say(self.run_voice_command(cmd))

        if text in ("never mind", "nevermind", "cancel", "nothing", "stop"):
            return

        # ---- Mirage itself ----
        if on("mirage"):
            if re.fullmatch(r"(shut ?down|exit|quit|go to sleep|goodbye)( yourself| mirage)?|turn (yourself|mirage) off|"
                            r"turn off (yourself|mirage)", text):
                say("Shutting down. Goodbye.")
                time.sleep(2.5)
                self.emit("quit")
                self.stop()
                return
            if re.fullmatch(r"(open|show) (your )?(settings|yourself|yourselves|the app|your window|mirage|the interface)|"
                            r"show (yourself|yourselves|up)", text):
                self.emit("show_window")
                return say("Here I am.")
            if re.fullmatch(r"(mute (the |your )?(mic|microphone)|stop listening)", text):
                say("Microphone muted. Unmute me in the app.")
                self.set_muted(True)
                return

        # ---- memory ----
        if on("memory"):
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
        if on("todos"):
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

        # ---- timers (before reminders, so "remind me in 10 minutes" with nothing to remind is a timer) ----
        if on("timers") and re.search(r"\b(set (a )?timer|timer for|start a timer)\b|^remind me in [\w\s]+$", text) \
                and not re.search(r"\bremind me in .+ (to|that|about) ", text):
            secs = parse_duration(text)
            if secs <= 0:
                return say("How long should the timer be?")
            return say(a.set_timer(secs))

        # ---- reminders ----
        if on("reminders"):
            if re.search(r"\b(?:what are|list|read|tell me) (?:all )?my reminders\b|\bdo i have any reminders\b", text):
                items = self.reminders.upcoming()
                if not items:
                    return say("You have no reminders.")
                parts = [f"{r['text']} {sk.say_time(datetime.fromisoformat(r['when']))}" for r in items[:4]]
                return say("Your reminders: " + "; ".join(parts) + ".")
            if re.search(r"\b(?:cancel|clear|delete|remove) (?:all )?(?:of )?my reminders\b", text):
                n = self.reminders.clear()
                return say(f"Cleared {n} reminder{'s' if n != 1 else ''}." if n else "You had no reminders.")
            if re.match(r"^(?:please )?remind me\b", text):
                when, rest = sk.parse_when(text)
                what = re.sub(r"^.*?\bremind me\b\s*", "", rest)
                what = re.sub(r"^(?:to|that|about|of)\s+", "", what).strip() or "your reminder"
                what = re.sub(r"\bmy\b", "your", what)
                if when is None:
                    return say("When should I remind you? Say for example: remind me at 5 pm to stretch.")
                self.reminders.add(when, what)
                self.emit("reminders_changed")
                return say(f"Okay, I'll remind you {sk.say_time(when)}.")

        # ---- Roblox Studio ----
        if on("roblox"):
            if re.fullmatch(r"(?:start |run |begin )?(?:a )?play ?test(?:ing)?(?: the game| my game)?|test (?:the|my) game", text):
                return say(sk.studio_key("f5") or "Starting playtest.")
            if re.fullmatch(r"(?:stop|end|exit) (?:the )?play ?test(?:ing)?", text):
                return say(sk.studio_key("shift", "f5") or "Stopped.")
            if re.fullmatch(r"save (?:the |my )?(?:game|place)(?: in studio)?", text):
                return say(sk.studio_key("ctrl", "s") or "Saved.")

        # ---- Spotify ----
        if on("spotify"):
            import spotify
            m = re.fullmatch(r"(play|put on|start|switch to|change to|go to|open|"
                             r"(?:switch|change) (?:the )?(?:playlist|music) to) (.+?)", text)
            if m:
                verb, target = m.group(1), m.group(2).strip()
                # "open discord" is the app even if a playlist is called discord
                known = verb in ("open", "start", "go to") and (
                    target in {k.lower() for k in self.cfg.get("websites", {})}
                    or target in {k.lower() for k in self.cfg.get("apps", {}).get(SYSTEM, {})}
                    or target in {k.lower() for k in self.cfg.get("roblox_games", {})})
                name, link = self.saved_playlist(target)
                if link and not known:
                    return say(self.play_playlist(name, link))
                if re.search(r"\bplaylist\b", text) and name and not known:
                    return say(spotify.search(name + " playlist").rstrip(".") + ". Save it under Shortcuts, "
                               "Spotify playlists, and next time I'll start it for you.")
            if re.fullmatch(r"(?:stop|pause|stop playing|pause playing)(?: the| my)? (?:music|song|spotify|playlist)|"
                            r"(?:turn off|shut off) (?:the )?music", text):
                if spotify.playing() is False:
                    return say("It's already paused.")
                r = a.media("pause")
                return say("Paused." if r == "Done." else r)
            if re.fullmatch(r"(?:play|resume|start|unpause|continue)(?: the| my)? (?:music|song|spotify|playlist)|play spotify", text):
                state = spotify.playing()
                if state is True:
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

        # ---- play songs and videos ----
        if on("play"):
            m = re.match(r"^(?:play|put on) (.+?)(?: on (youtube|spotify))?$", text)
            if m and m.group(1) not in ("music",) and not text.startswith(("play test", "playtest")):
                return say(self.play(m.group(1), m.group(2)))

        # ---- media keys ----
        if on("media"):
            m = re.match(r"^(?:please )?(?:turn (?:the )?)?(volume up|volume down|louder|quieter|turn it up|turn it down|"
                         r"unmute|mute|next song|next track|skip(?: this)?(?: song| track)?|previous song|previous track|"
                         r"last song|pause|resume|unpause)\b", text)
            if m:
                word = m.group(1)
                action = ("volume up" if word in ("volume up", "louder", "turn it up") else
                          "volume down" if word in ("volume down", "quieter", "turn it down") else
                          "next" if word.startswith(("next", "skip")) else
                          "previous" if word.startswith(("previous", "last")) else
                          "resume" if word == "unpause" else word)
                return say(a.media(action))

        # ---- searching ----
        if on("search"):
            m = re.match(r"^(?:search youtube for|youtube) (.+)$", text) or re.match(r"^search (?:for )?(.+) on youtube$", text)
            if m:
                return say(a.youtube(m.group(1)))
            m = re.match(r"^(?:search|google|look up|search for|search google for) (.+)$", text)
            if m:
                return say(a.google(m.group(1)))

        # ---- opening apps, websites and games ----
        if on("open"):
            m = re.match(r"^(?:open|launch|start|go to) (.+)$", text)
            if m:
                target = m.group(1).strip()
                game = re.sub(r"^(?:my game|the game|game) |(?: in studio| in roblox studio)$", "", target).strip()
                reply = sk.open_roblox_game(self.cfg, game) or a.open_website(target) or a.open_app(target)
                if reply or not self.brain.available():
                    return say(reply or f"I don't know how to open {target}. Add it on the Shortcuts page.")

        # ---- typing ----
        if on("typing"):
            m = re.match(r"^(?:type|write) (.+)$", text)
            if m:
                return say(a.type_text(m.group(1)))

        # ---- looking at the screen ----
        if on("screen") and re.search(r"\b(?:what'?s|what is) on (?:my|the) screen\b|\blook at (?:my|the|this) screen\b|"
                                      r"\bwhat am i looking at\b|\b(?:read|check|see) (?:my|the) screen\b", text):
            if not self.brain.available():
                return say("I need my AI brain to look at your screen. Set it up under Settings, Brain.")
            return say(self.brain.ask(text, screen=True))

        # ---- weather ----
        if on("weather") and re.search(r"^(?:what'?s|what is|how'?s|how is|tell me) (?:the )?(?:weather|temperature)\b|"
                                       r"^weather\b|\bweather (?:today|tomorrow|like|forecast)\b|\bhow (?:hot|cold|warm) is it\b|"
                                       r"\b(?:will|is) it (?:going to )?(?:rain|snow)\b|\bdo i need (?:an umbrella|a jacket)\b", text) \
                and not re.search(r"\bin (?!the |a |an )[a-z]", text) and not re.search(r"\bnext (?:week|month)\b", text):
            # weather somewhere else, or further ahead, goes to Claude
            try:
                return say(sk.weather_report(self.cfg, "tomorrow" if "tomorrow" in text else "today"))
            except Exception as e:
                log(f"Weather failed: {e}")
                return say("I couldn't get the weather right now.")

        # ---- time and date ----
        if on("time"):
            if re.fullmatch(r"(?:what time is it|what'?s the time|what is the time|tell me the time|time)(?: now| right now)?", text):
                return say(a.tell_time())
            if re.fullmatch(r"(?:what day is it|what'?s the date|what is the date|what'?s today|what day is today|"
                            r"what'?s today'?s date|date)(?: today)?", text):
                return say(a.tell_date())

        # ---- screenshot, lock, close ----
        if on("screenshot") and re.search(r"\b(?:take|grab|save|make) (?:a )?screen ?shot\b|^screen ?shot$", text):
            return say(a.screenshot())
        if on("pc"):
            if re.search(r"\block (?:the |my )?(?:computer|pc|screen)\b", text):
                return say(a.lock())
            if re.fullmatch(r"close (?:this |the )?(?:window|app|program)", text):
                return say(a.close_window())

        if on("greetings") and re.fullmatch(r"(hello|hi|hey)( there)?", text):
            return say("Hello. What can I do for you?")

        if on("facts"):
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


# Built-in command groups, shown on the Shortcuts page where each can be turned off
BUILTIN_GROUPS = [
    ("mirage", "Mirage itself", ["shut down", "show yourself", "mute the mic"]),
    ("memory", "Memory", ["remember that my favourite colour is purple", "forget about the door", "what do you know about Bullet Train"]),
    ("todos", "To-do list", ["add fix the door to my to-do list", "what's on my to-do list", "check off fix the door"]),
    ("timers", "Timers", ["set a timer for 10 minutes", "remind me in 5 minutes"]),
    ("reminders", "Reminders", ["remind me at 5 pm to stretch", "what are my reminders", "clear my reminders"]),
    ("roblox", "Roblox Studio", ["playtest", "stop playtest", "save the game"]),
    ("spotify", "Spotify", ["play chill (a saved playlist)", "stop the music", "play music", "what's playing"]),
    ("play", "Play songs and videos", ["play lofi beats", "play never gonna give you up on spotify"]),
    ("media", "Media keys", ["volume up", "next song", "pause", "mute"]),
    ("search", "Search", ["search for cheap headphones", "search youtube for roblox tutorials"]),
    ("open", "Open apps, sites and games", ["open youtube", "open discord", "open limbless"]),
    ("typing", "Typing", ["type hello everyone"]),
    ("screen", "Look at the screen", ["what's on my screen"]),
    ("weather", "Weather", ["what's the weather", "will it rain tomorrow"]),
    ("time", "Time and date", ["what time is it", "what's the date"]),
    ("screenshot", "Screenshots", ["take a screenshot"]),
    ("pc", "Lock and close", ["lock the computer", "close this window"]),
    ("greetings", "Greetings", ["hello"]),
    ("facts", "Quick facts (when Claude is off)", ["who is Sun Wukong"]),
]


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
