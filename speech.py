"""
Mirage's speech: its voice (Kokoro) and its ears (NVIDIA Parakeet, with Silero to tell when you're talking),
all running on this PC through sherpa-onnx. Installed once from Settings (about 850 MB), no other apps needed.

- Voice: Kokoro-82M (Apache-2.0), 28 English voices. Short lines are saved so they play instantly.
- Ears: Parakeet TDT 0.6B v2 (CC-BY-4.0) writes down everything said to Mirage. It also listens for the wake word,
  which is far more reliable than a separate wake word detector (tested: it tells "mirage" from "my rage").
"""

import collections
import hashlib
import json
import math
import os
import re
import shutil
import subprocess
import sys
import tarfile
import threading
import time
import traceback
import urllib.request
import wave
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent
if sys.platform.startswith("win") and os.environ.get("LOCALAPPDATA"):
    HOME = Path(os.environ["LOCALAPPDATA"]) / "Mirage"
else:
    HOME = BASE_DIR
MODELS = HOME / "speech"
CACHE_DIR = HOME / "voice_lines"
NO_WINDOW = 0x08000000 if sys.platform.startswith("win") else 0
RELEASES = "https://github.com/k2-fsa/sherpa-onnx/releases/download/"
PARTS = [  # (what, download, folder or file it unpacks to, files that must be there, size in MB)
    ("voice", RELEASES + "tts-models/kokoro-multi-lang-v1_0.tar.bz2", "kokoro-multi-lang-v1_0",
     ["model.onnx", "voices.bin", "tokens.txt", "lexicon-us-en.txt", "lexicon-gb-en.txt", "espeak-ng-data/phontab"], 349),
    ("ears", RELEASES + "asr-models/sherpa-onnx-nemo-parakeet-tdt-0.6b-v2-int8.tar.bz2",
     "sherpa-onnx-nemo-parakeet-tdt-0.6b-v2-int8", ["encoder.int8.onnx", "decoder.int8.onnx", "joiner.int8.onnx", "tokens.txt"], 482),
    ("vad", RELEASES + "asr-models/silero_vad.onnx", "silero_vad.onnx", [], 1),
]
TOTAL_MB = sum(p[4] for p in PARTS)

# Kokoro's English voices (speaker number, id, how it's shown). The best-rated ones are marked.
VOICES = [
    (2, "af_bella", "Bella · American woman (best)"), (3, "af_heart", "Heart · American woman (best)"),
    (0, "af_alloy", "Alloy · American woman"), (1, "af_aoede", "Aoede · American woman"),
    (4, "af_jessica", "Jessica · American woman"), (5, "af_kore", "Kore · American woman"),
    (6, "af_nicole", "Nicole · American woman, soft"), (7, "af_nova", "Nova · American woman"),
    (8, "af_river", "River · American woman"), (9, "af_sarah", "Sarah · American woman"),
    (10, "af_sky", "Sky · American woman"), (11, "am_adam", "Adam · American man"),
    (12, "am_echo", "Echo · American man"), (13, "am_eric", "Eric · American man"),
    (14, "am_fenrir", "Fenrir · American man, deep"), (15, "am_liam", "Liam · American man"),
    (16, "am_michael", "Michael · American man"), (17, "am_onyx", "Onyx · American man, deep"),
    (18, "am_puck", "Puck · American man"), (19, "am_santa", "Santa · American man"),
    (20, "bf_alice", "Alice · British woman"), (21, "bf_emma", "Emma · British woman"),
    (22, "bf_isabella", "Isabella · British woman"), (23, "bf_lily", "Lily · British woman"),
    (24, "bm_daniel", "Daniel · British man"), (25, "bm_fable", "Fable · British man"),
    (26, "bm_george", "George · British man"), (27, "bm_lewis", "Lewis · British man"),
]
VOICE_IDS = {v[1]: v[0] for v in VOICES}
DEFAULT_VOICE = "af_bella"

# Words Kokoro's own list doesn't have, in its sound symbols
EXTRA_WORDS = """spotify s p ˈ ɑ t ɪ f ˌ I
roblox ɹ ˈ O b l ɑ k s
github ɡ ˈ ɪ t h ˌ ʌ b
playtest p l ˈ A t ˌ ɛ s t
playtesting p l ˈ A t ˌ ɛ s t ɪ ŋ
what's w ˈ ʌ t s
that's ð ˈ æ t s
here's h ˈ ɪ ɹ z
there's ð ˈ ɛ ɹ z
where's w ˈ ɛ ɹ z
who's h ˈ u z
how's h ˈ W z
o'clock ə k l ˈ ɑ k
"""

WAKE_SOUNDS = ["mirage", "mirages", "mirage's", "mirrage", "miraj", "mirag"]


def _pip(*args):
    import paths
    return paths.pip(*args)


def part_ready(part) -> bool:
    what, url, name, needed, mb = part
    target = MODELS / name
    if not needed:
        return target.is_file() and target.stat().st_size > 1000
    return all((target / f).exists() for f in needed)


def package_ready() -> bool:
    import importlib
    import importlib.util
    importlib.invalidate_caches()
    try:
        return importlib.util.find_spec("sherpa_onnx") is not None and importlib.util.find_spec("numpy") is not None
    except Exception:
        return False


def installed() -> bool:
    return package_ready() and all(part_ready(p) for p in PARTS)


# --------------------------------------------------------------------------- #
# Installing
# --------------------------------------------------------------------------- #
def _download(url, dest, progress, label, mb):
    tmp = dest.with_name(dest.name + ".part")
    req = urllib.request.Request(url, headers={"User-Agent": "Mirage"})
    with urllib.request.urlopen(req, timeout=60) as r, open(tmp, "wb") as f:
        total = int(r.headers.get("Content-Length") or mb * 1e6)
        done, last = 0, 0.0
        while True:
            block = r.read(1 << 20)
            if not block:
                break
            f.write(block)
            done += len(block)
            if time.time() - last > 0.5:
                last = time.time()
                progress(f"Downloading {label}: {done / 1e6:.0f} of {total / 1e6:.0f} MB")
    os.replace(tmp, dest)


def install(progress=lambda m: None, log=lambda m: None):
    """Install sherpa-onnx and download the voice, ears and speech detector. Returns (ok, message)."""
    free = shutil.disk_usage(HOME if HOME.exists() else Path.home()).free
    if free < 2.5e9:
        return False, f"Not enough free disk space: this needs about 2 GB and there's {free / 1e9:.1f} GB free."
    if not package_ready():
        progress("Installing the speech engine…")
        r = subprocess.run(_pip("install", "--disable-pip-version-check", "sherpa-onnx", "numpy"),
                           capture_output=True, text=True, creationflags=NO_WINDOW)
        if r.returncode != 0:
            err = next((l for l in reversed(r.stdout.splitlines() + r.stderr.splitlines()) if "ERROR" in l), "pip failed")
            log("Speech install: pip failed:\n" + r.stdout[-1500:] + r.stderr[-1500:])
            return False, f"Install failed: {err.strip()[:200]}"
        try:
            import site
            us = site.getusersitepackages()
            if os.path.isdir(us) and us not in sys.path:
                site.addsitedir(us)
        except Exception:
            pass
    MODELS.mkdir(parents=True, exist_ok=True)
    labels = {"voice": "Mirage's voice", "ears": "Mirage's hearing", "vad": "the speech detector"}
    for part in PARTS:
        what, url, name, needed, mb = part
        if part_ready(part):
            continue
        label = labels[what]
        try:
            if url.endswith(".tar.bz2"):
                archive = MODELS / (name + ".tar.bz2")
                _download(url, archive, progress, label, mb)
                progress(f"Unpacking {label}…")
                shutil.rmtree(MODELS / name, ignore_errors=True)
                with tarfile.open(archive, "r:bz2") as tar:
                    try:
                        tar.extractall(MODELS, filter="data")
                    except TypeError:  # an older Python without extraction filters
                        for m in tar.getmembers():
                            if m.name.startswith(("/", "..")) or ".." in Path(m.name).parts:
                                raise ValueError("unsafe archive")
                        tar.extractall(MODELS)
                archive.unlink()
            else:
                _download(url, MODELS / name, progress, label, mb)
        except Exception as e:
            log(f"Speech install: {what} failed: {e}")
            return False, f"Couldn't download {label}: {e}"
        if not part_ready(part):
            return False, f"{label[0].upper() + label[1:]} didn't unpack properly. Try again."
        log(f"Speech install: {what} ready")
    return True, "Installed."


def remove_old_engines(log=lambda m: None):
    """Delete the big voice engine and Whisper that Mirage 2.1-2.3 used (about 6 GB), once."""
    marker = HOME / ".old-engines-removed"
    if marker.exists():
        return
    old = [HOME / "voice_model", HOME / "voice_cache", BASE_DIR / "voice_model", BASE_DIR / "voice_cache", BASE_DIR / "voices"]
    if not any(d.exists() for d in old):  # never had the old engine: nothing to clean (and other apps' files stay)
        try:
            HOME.mkdir(parents=True, exist_ok=True)
            marker.write_text("nothing to remove")
        except Exception:
            pass
        return
    freed = 0
    for d in (HOME / "voice_model", HOME / "voice_cache", BASE_DIR / "voice_model", BASE_DIR / "voice_cache", BASE_DIR / "voices"):
        if d.exists():
            for root, _, files in os.walk(d):
                freed += sum(os.path.getsize(os.path.join(root, f)) for f in files if os.path.exists(os.path.join(root, f)))
            shutil.rmtree(d, ignore_errors=True)
    hub = Path.home() / ".cache" / "huggingface" / "hub"
    for d in hub.glob("models--Systran--faster-whisper-*") if hub.exists() else []:
        shutil.rmtree(d, ignore_errors=True)
    # packages only Mirage's old voice and Whisper used
    r = subprocess.run(_pip("uninstall", "-y", "omnivoice", "torch", "transformers", "accelerate",
                        "faster-whisper", "ctranslate2"), capture_output=True, text=True, creationflags=NO_WINDOW)
    log(f"Removed the old voice engine and Whisper ({freed / 1e9:.1f} GB of models; pip: "
        f"{'ok' if r.returncode == 0 else r.stderr.strip()[-200:]})")
    HOME.mkdir(parents=True, exist_ok=True)
    marker.write_text(time.strftime("%Y-%m-%d %H:%M"))


# --------------------------------------------------------------------------- #
# Turning text into something Kokoro can say
# --------------------------------------------------------------------------- #
ONES = "zero one two three four five six seven eight nine ten eleven twelve thirteen fourteen fifteen sixteen " \
       "seventeen eighteen nineteen".split()
TENS = "_ _ twenty thirty forty fifty sixty seventy eighty ninety".split()
ORD = {"one": "first", "two": "second", "three": "third", "five": "fifth", "eight": "eighth", "nine": "ninth",
       "twelve": "twelfth"}


def number_words(n: int) -> str:
    if n < 0:
        return "minus " + number_words(-n)
    if n < 20:
        return ONES[n]
    if n < 100:
        return TENS[n // 10] + ("" if n % 10 == 0 else " " + ONES[n % 10])
    if n < 1000:
        return ONES[n // 100] + " hundred" + ("" if n % 100 == 0 else " and " + number_words(n % 100))
    for size, word in ((10 ** 12, "trillion"), (10 ** 9, "billion"), (10 ** 6, "million"), (1000, "thousand")):
        if n >= size:
            rest = n % size
            return number_words(n // size) + " " + word + ("" if not rest else (" and " if rest < 100 else " ") + number_words(rest))
    return str(n)


def ordinal_words(n: int) -> str:
    words = number_words(n).split()
    last = words[-1]
    words[-1] = ORD.get(last) or (last[:-1] + "ieth" if last.endswith("y") else last + "th")
    return " ".join(words)


def _num(m):
    raw = m.group(0)
    s = raw.replace(",", "")
    if "." in s:
        whole, frac = s.split(".", 1)
        return number_words(int(whole or 0)) + " point " + " ".join(ONES[int(d)] for d in frac)
    n = int(s)
    if "," not in raw and 1100 <= n <= 2099 and len(s) == 4 and n % 100 != 0 and not (2000 <= n <= 2009):  # years
        return number_words(n // 100) + " " + (("oh " + ONES[n % 100]) if n % 100 < 10 else number_words(n % 100))
    return number_words(n)


def _time(m):
    h, mi = int(m.group(1)), int(m.group(2))
    ampm = (" " + " ".join(m.group(3).replace(".", "").upper())) if m.group(3) else ""
    if mi == 0:
        return number_words(h) + (ampm if ampm else " o'clock")
    return number_words(h) + (" oh " + ONES[mi] if mi < 10 else " " + number_words(mi)) + ampm


COMMON = """minute hour second day week month year degree reminder timer note task file folder app website video
playlist screenshot song track album artist message setting option window game friend thing item result question answer
idea step change update voice word line link page tab program player level point percent dollar krona euro click key
open close play pause start stop save delete add remove set check find search look make take call name install load
download upload move finish ask tell need want like work turn type print read write listen talk remember forget
complete test fix build run send show hide mute schedule plan follow cancel""".split()


def _last_sound(ph):
    toks = [t for t in ph.split() if t not in ("ˈ", "ˌ", "ː")]
    return toks[-1] if toks else ""


class Words:
    """Kokoro skips words it doesn't know, so unknown words are rewritten into ones it does. Plurals and other forms
    missing from its list (reminders, opened, minutes…) are worked out from the plain word and learned for next time."""

    def __init__(self, lexicons, learned_file=None):
        self.say = {}
        for path in lexicons:
            try:
                with open(path, encoding="utf-8") as f:
                    for line in f:
                        w, _, ph = line.rstrip("\n").partition(" ")
                        if w and ph:
                            self.say.setdefault(w.lower(), ph)
            except OSError:
                pass
        self.known = self.say.keys()
        self.learned_file = learned_file
        self.new = {}      # learned, not yet written to the learned words file
        self.pending = {}  # learned, not yet loaded into the voice: word -> plain word to say meanwhile

    def forms(self, word):
        """Ways to say plural, past and -ing forms, from the plain word: {"reminders": "ɹ ə m ˈ I n d ə ɹ z", …}."""
        ph = self.say.get(word)
        if not ph or not re.fullmatch(r"[a-z]{2,14}", word):
            return {}
        last, out = _last_sound(ph), {}
        cons_y = word.endswith("y") and word[-2] not in "aeiou"
        plural = word + "es" if word.endswith(("s", "x", "z", "ch", "sh")) else word[:-1] + "ies" if cons_y else word + "s"
        out[plural] = ph + (" ɪ z" if last in ("s", "z", "ʃ", "ʒ", "ʧ", "ʤ") else " s" if last in ("p", "t", "k", "f", "θ") else " z")
        past = word + "d" if word.endswith("e") else word[:-1] + "ied" if cons_y else word + "ed"
        out[past] = ph + (" ɪ d" if last in ("t", "d") else " t" if last in ("p", "k", "f", "θ", "s", "ʃ", "ʧ") else " d")
        out[(word[:-1] if word.endswith("e") and not word.endswith("ee") else word) + "ing"] = ph + " ɪ ŋ"
        return {k: v for k, v in out.items() if k not in self.say}

    def learn(self, word):
        """If word is a form of one Kokoro knows, learn how to say it. Returns the plain word to use meanwhile."""
        for base in (word[:-1], word[:-2], word[:-3] + "y", word[:-3], word[:-3] + "e", word[:-1] if word.endswith("d") else ""):
            if base and base in self.say:
                ph = self.forms(base).get(word)
                if ph:
                    self.say[word] = ph
                    self.new[word] = ph
                    return base
        return None

    def seed(self):
        """Forms of the words Mirage says most, learned up front."""
        for w in COMMON:
            for k, v in self.forms(w).items():
                self.say[k] = v
                self.new[k] = v

    def save_learned(self):
        if not self.learned_file or not self.new:
            return False
        try:
            with open(self.learned_file, "a", encoding="utf-8") as f:
                f.writelines(f"{k} {v}\n" for k, v in self.new.items())
            self.new = {}
            return True
        except OSError:
            return False

    def split(self, word):
        """Break an unknown word into known pieces: roblox -> rob lox, spotify -> spot if y."""
        n = len(word)
        best = [None] * (n + 1)
        best[0] = []
        for i in range(n):
            if best[i] is None:
                continue
            for j in range(min(n, i + 14), i, -1):
                piece = word[i:j]
                if (piece in self.known and (len(piece) >= 2 or piece in ("a", "i"))) and \
                        (best[j] is None or len(best[j]) > len(best[i]) + 1):
                    best[j] = best[i] + [piece]
        return best[n]

    def fix(self, word):
        low = word.lower()
        if not re.search(r"[a-z]", low):
            return word
        if low in self.pending:  # just learned: the voice can say it after it reloads, the plain word until then
            return self.pending[low]
        if low in self.say:
            return word
        base = self.learn(low)
        if base:
            self.pending[low] = base
            return base
        if low.endswith(("'s", "’s")) and low[:-2] in self.known:
            base = low[:-2]
            return base + "s" if base + "s" in self.known else base + " is" if base in (
                "it", "he", "she", "what", "that", "there", "here", "who", "where", "how", "when", "why") else base
        if low.endswith("s") and low[:-1] in self.known:
            return low[:-1] + " s" if len(low) <= 3 else low
        parts = re.findall(r"[A-Z]?[a-z]+|[A-Z]+(?![a-z])|\d+", word)
        if len(parts) > 1 and all(p.lower() in self.known for p in parts):
            return " ".join(parts)
        pieces = self.split(low.replace("'", ""))
        if pieces and len(pieces) <= max(2, len(low) // 3):
            return " ".join(pieces)
        return " ".join(low.replace("'", ""))  # spell it out

    def speakable(self, text: str) -> str:
        t = text
        t = re.sub(r"https?://\S+", "a link", t)
        t = re.sub(r"[*_`#>|~]", " ", t)                      # leftover markdown
        t = t.replace("&", " and ").replace("@", " at ").replace("+", " plus ")
        t = re.sub(r"(\d+(?:[.,]\d+)?)\s*°\s*([CF])\b", lambda m: m.group(1) + " degrees " +
                   ("Celsius" if m.group(2) == "C" else "Fahrenheit"), t)
        t = re.sub(r"(\d+(?:[.,]\d+)?)\s*°", r"\1 degrees", t)
        t = re.sub(r"(\d+(?:\.\d+)?)\s*%", r"\1 percent", t)
        t = re.sub(r"([$€£])(\d[\d,]*)(?:\.(\d{2}))?\b", lambda m: m.group(2) + " " +
                   {"$": "dollars", "€": "euros", "£": "pounds"}[m.group(1)] +
                   (" and " + str(int(m.group(3))) + " cents" if m.group(3) and int(m.group(3)) else ""), t)
        t = re.sub(r"(\d+(?:\.\d+)?)\s*(kr|sek)\b", r"\1 kronor", t, flags=re.I)
        t = re.sub(r"\b(\d{1,2}):(\d{2})\s*([ap]\.?m\.?)?", _time, t, flags=re.I)
        t = re.sub(r"\b(\d+)(st|nd|rd|th)\b", lambda m: ordinal_words(int(m.group(1))), t)
        t = re.sub(r"(?<![\d.])-(\d)", r"minus \1", t)
        t = re.sub(r"\d[\d,]*(?:\.\d+)?", _num, t)
        t = re.sub(r"[A-Za-z][A-Za-z'’]*", lambda m: self.fix(m.group(0)), t)
        t = re.sub(r"\s+", " ", t).strip()
        return t


def split_sentences(text, max_len=220):
    text = re.sub(r"\s+", " ", text).strip()
    parts = [p for p in re.split(r"(?<=[.!?;:])\s+", text) if p]
    chunks, cur = [], ""
    for p in parts:
        while len(p) > max_len:
            cut = max(p.rfind(", ", 0, max_len), p.rfind(" ", 0, max_len))
            cut = cut if cut > 40 else max_len
            chunks.append((cur + " " + p[:cut + 1]).strip())
            cur, p = "", p[cut + 1:].strip()
        if not cur:
            cur = p
        elif len(cur) < 40 or len(cur) + len(p) < 120:
            cur += " " + p
        else:
            chunks.append(cur)
            cur = p
    if cur:
        chunks.append(cur)
    return chunks or [text]


# --------------------------------------------------------------------------- #
# Sound effects for the voice
# --------------------------------------------------------------------------- #
def resample(x, sr, new_sr):
    """Band-limited resampling with numpy (windowed sinc), for mono float32 audio."""
    import numpy as np
    if sr == new_sr or len(x) == 0:
        return x.astype(np.float32)
    g = math.gcd(int(sr), int(new_sr))
    up, down = int(new_sr) // g, int(sr) // g
    if up > 64 or down > 64:  # awkward ratios: plain interpolation is fine for speech
        n = int(round(len(x) * new_sr / sr))
        return np.interp(np.linspace(0, len(x) - 1, n), np.arange(len(x)), x).astype(np.float32)
    cutoff = 0.98 / max(up, down)
    half = 8 * max(up, down)
    t = np.arange(-half, half + 1)
    h = np.sinc(cutoff * t) * cutoff * np.kaiser(len(t), 8.0)
    y = np.zeros(len(x) * up, dtype=np.float64)
    y[::up] = x
    y = np.convolve(y, h * up, mode="same")[::down]
    return y.astype(np.float32)


def robotize(x, sr, amount):
    """Mix in a ring-modulated, slightly metallic copy: 0 is off, 100 is fully robotic."""
    import numpy as np
    if amount <= 0:
        return x
    k = min(1.0, amount / 100.0)
    t = np.arange(len(x)) / sr
    ring = x * np.sin(2 * np.pi * 55 * t)
    d = int(sr * 0.006)
    comb = ring.copy()
    comb[d:] += 0.5 * ring[:-d]
    y = (1 - k * 0.7) * x + k * 0.9 * comb
    peak = float(np.max(np.abs(y))) or 1.0
    return (y / max(peak, 1.0)).astype(np.float32)


def _wav_bytes(x, sr):
    import io
    import numpy as np
    buf = io.BytesIO()
    with wave.open(buf, "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(sr)
        w.writeframes((np.clip(x, -1, 1) * 32767).astype("<i2").tobytes())
    return buf.getvalue()


def play(x, sr):
    try:
        import sounddevice as sd
        sd.play(x, sr)
        sd.wait()
    except Exception:
        if sys.platform.startswith("win"):
            import winsound
            winsound.PlaySound(_wav_bytes(x, sr), winsound.SND_MEMORY)


# --------------------------------------------------------------------------- #
# The engine
# --------------------------------------------------------------------------- #
class Speech:
    def __init__(self, log=print, on_change=lambda: None):
        self.log = log
        self.on_change = on_change
        self.tts = None
        self.asr = None
        self.words = None
        self.state = "off"  # off | installing | loading | ready | error
        self.detail = ""
        self.last_error = ""
        self.tts_lock = threading.Lock()
        self.asr_lock = threading.Lock()
        self._loader = None
        self._cache = {}
        self._warm_run = 0
        self.played = collections.deque(maxlen=6)  # what the voice played lately, for EchoMeter

    def ready(self):
        return self.tts is not None and self.asr is not None

    def _set(self, state, detail=""):
        self.state, self.detail = state, detail
        try:
            self.on_change()
        except Exception:
            pass

    def status(self):
        return {"installed": installed(), "state": self.state, "detail": self.detail, "last_error": self.last_error,
                "size_mb": TOTAL_MB, "voices": [[v[1], v[2]] for v in VOICES]}

    # ---- loading ----
    def load_async(self, then=None):
        if self.ready():
            if then:
                then()
            return
        if (self._loader and self._loader.is_alive()) or not installed():
            return
        self._loader = threading.Thread(target=self._load, args=(then,), daemon=True, name="speech-load")
        self._loader.start()

    def wait_loaded(self, seconds):
        if self._loader is not None:
            self._loader.join(seconds)
        return self.ready()

    def _load(self, then=None):
        self._set("loading", "Loading Mirage's voice and hearing…")
        try:
            import sherpa_onnx as so
            threads = max(1, min(4, (os.cpu_count() or 4) // 2))
            t0 = time.time()
            extra = MODELS / "lexicon-mirage.txt"
            extra.write_text(EXTRA_WORDS, encoding="utf-8")
            learned = MODELS / "lexicon-learned.txt"
            words = Words(self._lexicons(), learned)
            if not learned.exists():
                words.seed()
                learned.write_text("", encoding="utf-8")
                words.save_learned()
            self.threads = threads
            tts = self._make_tts()
            e = MODELS / PARTS[1][2]
            asr = so.OfflineRecognizer.from_transducer(
                encoder=str(e / "encoder.int8.onnx"), decoder=str(e / "decoder.int8.onnx"),
                joiner=str(e / "joiner.int8.onnx"), tokens=str(e / "tokens.txt"), num_threads=threads,
                model_type="nemo_transducer")
            self.tts, self.asr, self.words = tts, asr, words
            self.log(f"Speech loaded in {time.time() - t0:.1f} s ({threads} threads).")
            self._set("ready", "Ready")
            if then:
                then()
        except Exception as e:
            self.log("Speech failed to load:\n" + traceback.format_exc())
            self.last_error = f"{type(e).__name__}: {e}"
            self._set("error", f"Couldn't load Mirage's voice and hearing: {e}")

    def _lexicons(self):
        v = MODELS / PARTS[0][2]
        return [p for p in (v / "lexicon-us-en.txt", MODELS / "lexicon-mirage.txt", MODELS / "lexicon-learned.txt") if p.exists()]

    def _make_tts(self):
        import sherpa_onnx as so
        v = MODELS / PARTS[0][2]
        return so.OfflineTts(so.OfflineTtsConfig(
            model=so.OfflineTtsModelConfig(
                kokoro=so.OfflineTtsKokoroModelConfig(
                    model=str(v / "model.onnx"), voices=str(v / "voices.bin"), tokens=str(v / "tokens.txt"),
                    data_dir=str(v / "espeak-ng-data"), lexicon=",".join(str(p) for p in self._lexicons()), lang="en-us"),
                num_threads=self.threads),
            max_num_sentences=1))

    def _learned_words(self):
        """New words were learned: save them and reload the voice in the background so it can say them."""
        if getattr(self, "_reloading", False):
            return
        self._reloading = True

        def work():
            try:
                time.sleep(2)
                pending = dict(self.words.pending)
                self.words.save_learned()
                tts = self._make_tts()
                with self.tts_lock:
                    self.tts = tts
                for k in pending:
                    self.words.pending.pop(k, None)
                self._cache = {k: v for k, v in self._cache.items() if not any(w in k[-1] for w in pending)}
                self.log(f"Voice learned: {', '.join(pending)}")
            except Exception as e:
                self.log(f"Couldn't reload the voice with new words: {e}")
            finally:
                self._reloading = False
        threading.Thread(target=work, daemon=True, name="voice-learn").start()

    # ---- hearing ----
    def make_vad(self, silence=0.55):
        import sherpa_onnx as so
        cfg = so.VadModelConfig(silero_vad=so.SileroVadModelConfig(
            model=str(MODELS / PARTS[2][2]), min_silence_duration=silence, min_speech_duration=0.2,
            threshold=0.5, max_speech_duration=20), sample_rate=16000)
        return so.VoiceActivityDetector(cfg, buffer_size_in_seconds=40)

    def transcribe(self, samples, rate=16000) -> str:
        """Speech -> text. Mirage's listener pads each piece of speech, which helps with single words like "Mirage"."""
        with self.asr_lock:
            s = self.asr.create_stream()
            s.accept_waveform(rate, samples)
            self.asr.decode_stream(s)
            return s.result.text.strip()

    # ---- the voice ----
    def synth(self, text, voice=DEFAULT_VOICE, speed=1.0, pitch=0, robot=0):
        """Text -> (float32 audio, sample rate), with pitch and robot effects."""
        import numpy as np
        if self.tts is None:
            raise RuntimeError("Mirage's voice isn't loaded.")
        sid = VOICE_IDS.get(voice, VOICE_IDS[DEFAULT_VOICE])
        lift = 2 ** (max(-6, min(6, int(pitch))) / 12)
        said = self.words.speakable(text)
        if self.words.pending:
            self._learned_words()
        if not re.search(r"[a-z]", said, re.I):
            return np.zeros(1, dtype=np.float32), 24000
        with self.tts_lock:
            a = self.tts.generate(said, sid=sid, speed=max(0.5, min(2.5, speed / lift)))
        x, sr = np.asarray(a.samples, dtype=np.float32), a.sample_rate
        if abs(lift - 1) > 1e-3:  # made slower or faster by the pitch ratio above, then squeezed back: higher or lower voice
            x = resample(x, int(round(sr * lift)), sr) if lift < 1 else resample(x, sr, int(round(sr / lift)))
        return robotize(x, sr, robot), sr

    def _cache_file(self, key):
        return CACHE_DIR / (hashlib.sha1("|".join(map(str, key)).encode("utf-8")).hexdigest()[:20] + ".wav")

    def line(self, text, voice, speed, pitch, robot):
        """Audio for one sentence: kept in memory and saved to disk when it's short, so repeats are instant."""
        import numpy as np
        key = (voice, round(speed, 2), int(pitch), int(robot), text.strip().lower())
        got = self._cache.get(key)
        short = len(text) <= 80
        f = self._cache_file(key) if short else None
        if got is None and f is not None and f.exists():
            try:
                with wave.open(str(f), "rb") as w:
                    sr = w.getframerate()
                    got = (np.frombuffer(w.readframes(w.getnframes()), dtype="<i2").astype(np.float32) / 32767, sr)
                os.utime(f)
            except Exception:
                got = None
        if got is None:
            got = self.synth(text, voice, speed, pitch, robot)
            if f is not None:
                try:
                    CACHE_DIR.mkdir(parents=True, exist_ok=True)
                    f.write_bytes(_wav_bytes(*got))
                    files = sorted(CACHE_DIR.glob("*.wav"), key=lambda p: p.stat().st_mtime)
                    for old in files[:max(0, len(files) - 1500)]:
                        old.unlink()
                except Exception:
                    pass
        if short:
            if len(self._cache) > 100:
                self._cache.clear()
            self._cache[key] = got
        return got

    def speak(self, text, voice=DEFAULT_VOICE, speed=1.0, pitch=0, robot=0, volume=1.0, stop=None):
        """Say text out loud; the next sentence is made while the current one plays. stop() -> True cuts it short."""
        import numpy as np
        try:
            import sounddevice as sd
        except Exception:
            sd = None
        playing = False
        for chunk in split_sentences(text):
            if stop and stop():
                break
            x, sr = self.line(chunk, voice, speed, pitch, robot)
            x = np.clip(x * max(0.0, min(1.0, volume)), -1, 1)
            if sd is None:
                play(x, sr)
                continue
            if playing:
                sd.wait()
            if stop and stop():
                break
            self._played(x, sr)
            sd.play(x, sr)
            playing = True
            if stop and stop():  # cut off while this was starting
                sd.stop()
                break
        if playing:
            sd.wait()
        if self.played and self.played[-1][2] > time.time():
            self.played[-1][2] = time.time()  # cut short
        self.last_error = ""

    def _played(self, x, sr):
        """Remember what this sentence sounds like and when it played, for EchoMeter."""
        import numpy as np
        if self.played and self.played[-1][2] > time.time():
            self.played[-1][2] = time.time()
        n = int(len(x) * 16000 / sr)
        x16 = np.interp(np.arange(n) * (sr / 16000), np.arange(len(x)), x).astype(np.float32)
        t = time.time()
        self.played.append([t, x16, t + len(x) / sr])

    def warm_up(self, voice, speed, pitch, robot, lines):
        """Prepare the lines Mirage says most for the current voice settings, in the background."""
        self._warm_run += 1
        run = self._warm_run

        def work():
            time.sleep(3)
            for t in lines:
                if self.tts is None or run != self._warm_run:
                    return
                try:
                    self.line(t, voice, speed, pitch, robot)
                except Exception as e:
                    self.log(f"Couldn't prepare {t!r}: {e}")
                    return
        threading.Thread(target=work, daemon=True, name="voice-warmup").start()


class Listener:
    """Cuts the microphone stream into pieces of speech, with a little audio kept from just before each one starts
    (the speech detector reacts a moment late) and a little silence after, which helps the ears with short words."""

    PRE, POST = 0.35, 0.3

    def __init__(self, speech, silence=0.55):
        import numpy as np
        self.np = np
        self.vad = speech.make_vad(silence)
        self.buf = np.zeros(0, dtype=np.float32)
        self.offset = 0  # stream position of buf[0]

    def reset(self):
        self.vad.reset()
        self.buf = self.np.zeros(0, dtype=self.np.float32)
        self.offset = 0

    def feed(self, samples):
        """float32 16 kHz audio in; finished pieces of speech out."""
        np = self.np
        self.buf = np.concatenate([self.buf, samples])
        self.vad.accept_waveform(samples)
        out = []
        while not self.vad.empty():
            seg = self.vad.front
            start = max(0, seg.start - int(16000 * self.PRE))
            end = seg.start + len(seg.samples)
            a = start - self.offset
            piece = self.buf[max(0, a):end - self.offset] if a > -len(self.buf) else np.asarray(seg.samples, np.float32)
            out.append(np.concatenate([piece, np.zeros(int(16000 * self.POST), np.float32)]))
            self.vad.pop()
        keep = 16000 * 25  # keep the last 25 s, enough for the longest piece
        if len(self.buf) > keep:
            cut = len(self.buf) - keep
            self.buf = self.buf[cut:]
            self.offset += cut
        return out

    def speaking(self):
        return self.vad.is_speech_detected()

    def recent(self, seconds):
        """The last few seconds of microphone audio."""
        return self.buf[-int(16000 * seconds):]


class EchoMeter:
    """Tells whether the microphone hears Mirage's own voice, which happens with speakers but not a headset.
    It lines up the last second of mic audio with what was played just before (GCC-PHAT cross-correlation):
    Mirage's voice coming back through the room shows up as one sharp peak; your own voice doesn't."""

    WINDOW, MAX_LAG = 1.0, 0.8   # seconds of mic audio compared; how late the echo may arrive
    EARLY = 0.15                 # the mic's clock can run a little behind the speaker's

    def __init__(self, speech):
        import numpy as np
        self.np = np
        self.speech = speech
        self.mic = np.zeros(0, dtype=np.float32)
        self.mic_end = 0.0
        self.next = 0.0
        self.streak, self.score = 0, 0.0
        self.clear = 0  # checks in a row where the voice played and the mic didn't carry it (a headset)

    def _reference(self, start, n):
        """What the voice played from time start, n samples at 16 kHz (silence where nothing played)."""
        np = self.np
        ref = np.zeros(n, dtype=np.float32)
        for t0, x, end in list(self.speech.played):
            a = int(round((t0 - start) * 16000))
            stop = min(len(x), int(round((end - t0) * 16000)))
            lo, hi = max(0, a), min(n, a + stop)
            if lo < hi:
                ref[lo:hi] = x[lo - a:hi - a]
        return ref

    def feed(self, x, t_end):
        """A block of 16 kHz mic audio that ended at t_end. Returns how clearly the mic carries Mirage's voice
        (a peak-to-noise ratio: about 4 for nothing, well over 10 for speakers), or None when it can't tell."""
        np = self.np
        w = int(16000 * self.WINDOW)
        self.mic = np.concatenate([self.mic, x])[-w:]
        self.mic_end = t_end
        if t_end < self.next or len(self.mic) < w:
            return None
        self.next = t_end + 0.5
        lag, early = int(16000 * self.MAX_LAG), int(16000 * self.EARLY)
        ref = self._reference(t_end - self.WINDOW - self.MAX_LAG, w + lag + early)
        if np.mean(np.abs(ref[lag:lag + w]) > 0.01) < 0.5:  # the voice wasn't playing most of that time
            return None
        n = 1 << int(np.ceil(np.log2(len(ref) + w)))
        cross = np.conj(np.fft.rfft(self.mic, n)) * np.fft.rfft(ref, n)
        c = np.fft.irfft(cross / (np.abs(cross) + 1e-12), n)[:lag + early + 1]  # c[k]: mic lines up with ref[k:]
        spread = float(np.std(c))
        return float(np.max(c)) / spread if spread > 0 else None

    def hears_voice(self, x, t_end) -> bool:
        """True once the mic clearly carries the voice: one strong match, or two good ones in a row."""
        r = self.feed(x, t_end)
        if r is None:
            return False
        self.streak = self.streak + 1 if r >= 8 else 0
        self.clear = self.clear + 1 if r < 6 else 0
        self.score = r
        return r >= 12 or self.streak >= 2


def strip_wake(text: str, extra_words=()):
    """'Mirage, open YouTube.' -> (True, 'open youtube'). The wake word counts in the first few words."""
    t = text.lower().strip()
    words = sorted(set(WAKE_SOUNDS) | {w.lower() for w in extra_words if w.strip()}, key=len, reverse=True)
    m = re.search(r"\b(" + "|".join(re.escape(w) for w in words) + r")\b", t)
    found = bool(m and len(t[:m.start()].split()) <= 4)
    if found:
        t = t[m.end():]
    t = re.sub(r"\bp\.\s?m\.?", "pm", t)
    t = re.sub(r"\ba\.\s?m\.?", "am", t)
    t = re.sub(r"[^\w\s':%.-]", " ", t)
    t = re.sub(r"(?<!\d)\.(?!\d)", " ", t)
    return found, re.sub(r"\s+", " ", t).strip(" -")
