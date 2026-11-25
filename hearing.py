"""
Accurate hearing with Whisper (faster-whisper, runs offline on the CPU).

Vosk keeps listening for the wake word all the time because it's light and fast. When you
talk to Mirage, the audio of what you said is handed to Whisper, which writes it down much
more accurately than Vosk does.
"""

import re
import subprocess
import sys
import threading
from pathlib import Path

WAKE_SOUNDS = ["mirage", "mirages", "mirage's", "my rage", "mirror", "marriage", "mira", "mirag"]


def whisper_installed() -> bool:
    try:
        import importlib
        importlib.invalidate_caches()
        import faster_whisper  # noqa: F401
        return True
    except Exception:
        return False


def install_whisper(progress=lambda msg: None) -> bool:
    """pip install faster-whisper into the Python that runs Mirage."""
    python = Path(sys.executable)
    if python.name.lower() == "pythonw.exe":
        python = python.with_name("python.exe")
    progress("Installing Whisper (this can take a few minutes)…")
    flags = 0x08000000 if sys.platform.startswith("win") else 0  # no console window
    pip = [str(python), "-m", "pip", "install", "--disable-pip-version-check"]
    # faster-whisper lists onnxruntime as a requirement, but only uses it for an optional
    # voice-detection filter that Mirage keeps off. onnxruntime doesn't exist for every Python
    # version (e.g. 3.15), so install faster-whisper without it and add the parts it really needs.
    steps = [
        pip + ["ctranslate2>=4,<5", "huggingface-hub>=0.21", "tokenizers>=0.13,<1", "av>=11", "tqdm", "numpy"],
        pip + ["--no-deps", "faster-whisper"],
    ]
    for cmd in steps:
        r = subprocess.run(cmd, capture_output=True, text=True, creationflags=flags)
        if r.returncode != 0:
            lines = [l for l in (r.stderr or r.stdout or "").strip().splitlines() if l.strip()]
            err = next((l for l in reversed(lines) if "ERROR" in l), lines[-1] if lines else "unknown error")
            progress(f"Install failed: {err[:200]}")
            return False
    ok = whisper_installed()
    progress("Whisper installed." if ok else "Installed, but Mirage can't load it yet. Restart Mirage.")
    return ok


class Whisper:
    def __init__(self, log=print):
        self.log = log
        self.model = None
        self.model_name = None
        self.loading = False
        self.lock = threading.Lock()

    def ready(self, name) -> bool:
        return self.model is not None and self.model_name == name

    def load_async(self, name, on_done=lambda ok, msg: None):
        """Load (and on first use, download) the Whisper model in the background."""
        if self.loading or self.ready(name):
            return

        def work():
            self.loading = True
            try:
                from faster_whisper import WhisperModel
                self.log(f"Loading Whisper model '{name}' (downloads once, ~75-500 MB)…")
                m = WhisperModel(name, device="cpu", compute_type="int8")
                with self.lock:
                    self.model, self.model_name = m, name
                self.log("Whisper ready.")
                on_done(True, "Whisper ready")
            except Exception as e:
                self.log(f"Whisper failed to load: {e}")
                on_done(False, str(e))
            finally:
                self.loading = False

        threading.Thread(target=work, daemon=True, name="whisper-load").start()

    def transcribe(self, pcm16: bytes, rate=16000) -> str:
        import numpy as np
        with self.lock:
            model = self.model
        if model is None or len(pcm16) < rate // 4:  # nothing loaded / under a quarter second
            return ""
        audio = np.frombuffer(pcm16, dtype=np.int16).astype(np.float32) / 32768.0
        segments, _ = model.transcribe(audio, language="en", beam_size=1, vad_filter=False,
                                       condition_on_previous_text=False,
                                       initial_prompt="Mirage, open YouTube. Mirage, remind me at 5 pm.")
        return " ".join(s.text for s in segments).strip()


def strip_wake(text: str, extra_words=()) -> tuple:
    """'Mirage, open YouTube.' -> (True, 'open youtube'). Looks for the wake word in the first few words."""
    t = text.lower().strip()
    words = sorted(set(WAKE_SOUNDS) | {w.lower() for w in extra_words}, key=len, reverse=True)
    m = re.search(r"\b(" + "|".join(re.escape(w) for w in words) + r")\b", t)
    if m and len(t[:m.start()].split()) <= 3:
        t = t[m.end():]
        found = True
    else:
        found = False
    t = re.sub(r"\bp\.\s?m\.?", "pm", t)
    t = re.sub(r"\ba\.\s?m\.?", "am", t)
    t = re.sub(r"[^\w\s':%.-]", " ", t)       # drop punctuation Whisper adds (keep 5:30, 20%, it's)
    t = re.sub(r"(?<!\d)\.(?!\d)", " ", t)     # full stops, but keep 5.30
    return found, re.sub(r"\s+", " ", t).strip()
