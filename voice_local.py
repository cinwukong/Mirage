"""
Mirage's own voice: the OmniVoice text-to-speech model running inside Mirage.

No VoiceStudio needed. Install it once from Settings > Voice (PyTorch and OmniVoice, then a
one-time download of the 3.3 GB voice model). After that Mirage speaks with voices you design
from a description, clone from a short recording, or bring over from VoiceStudio.

Voices live in the "voices" folder next to this file: one .json per voice, plus the recording
the voice is based on (.wav) and a cached version of it the model reads quickly (.pt).
"""

import json
import math
import os
import random
import re
import shutil
import sqlite3
import subprocess
import sys
import tempfile
import threading
import time
import traceback
import uuid
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent
MODEL_ID = "k2-fsa/OmniVoice"
VOICES_DIR = BASE_DIR / "voices"
OLD_MODEL_DIR = BASE_DIR / "voice_model"   # where 2.1.0 kept it
# The 3.3 GB model lives outside Mirage's folder, which may be on a synced desktop (OneDrive)
if sys.platform.startswith("win") and os.environ.get("LOCALAPPDATA"):
    MODEL_DIR = Path(os.environ["LOCALAPPDATA"]) / "Mirage" / "voice_model"
else:
    MODEL_DIR = OLD_MODEL_DIR
DONE = ".mirage-complete"
MODEL_BYTES = 3.27e9
OMNIVOICE_VERSION = "0.2.1"
SAMPLE_RATE = 24000
SAMPLE_TEXT = "Hello, I'm Mirage. Tell me what you need, and I'll take care of it."
QUALITY_STEPS = {"fast": 12, "balanced": 20, "best": 32}
NO_WINDOW = 0x08000000 if sys.platform.startswith("win") else 0
# PyTorch builds for NVIDIA cards, newest first, with the CUDA version the driver must support
CUDA_BUILDS = [("cu132", 13.2), ("cu130", 13.0), ("cu128", 12.8), ("cu126", 12.6)]
if sys.version_info >= (3, 15):  # PyTorch only makes builds for this Python with CUDA 13
    CUDA_BUILDS = [b for b in CUDA_BUILDS if b[1] >= 13.0]
TORCH_DEPS = ["filelock", "fsspec", "jinja2", "markupsafe", "networkx", "sympy", "mpmath",
              "typing-extensions", "setuptools"]

# What the model understands when designing a voice from a description: one word per row.
DESIGN_OPTIONS = {
    "gender": ["male", "female"],
    "age": ["child", "teenager", "young adult", "middle-aged", "elderly"],
    "pitch": ["very low pitch", "low pitch", "moderate pitch", "high pitch", "very high pitch"],
    "accent": ["american accent", "british accent", "australian accent", "canadian accent",
               "indian accent", "chinese accent", "japanese accent", "korean accent",
               "russian accent", "portuguese accent"],
    "style": ["whisper"],
}
DEFAULT_DESIGN = "male, young adult, low pitch"


def clean_instruct(text) -> str:
    """Keep only the description words the model knows (one of each kind), in a fixed order."""
    if not text:
        return ""
    items = [p.strip().lower() for p in re.split(r"[,;\n]", str(text)) if p.strip()]
    out = []
    for allowed in DESIGN_OPTIONS.values():
        hit = next((i for i in items if i in allowed), None)
        if hit:
            out.append(hit)
    return ", ".join(out)


def _gb(n) -> str:
    return f"{n / 1e9:.1f} GB"


def _python() -> str:
    p = Path(sys.executable)
    if p.name.lower() == "pythonw.exe":
        p = p.with_name("python.exe")
    return str(p)


# --------------------------------------------------------------------------- #
# Is it installed?
# --------------------------------------------------------------------------- #
def packages_installed() -> bool:
    import importlib
    import importlib.util
    importlib.invalidate_caches()
    try:
        return all(importlib.util.find_spec(m) is not None
                   for m in ("torch", "omnivoice", "transformers", "accelerate", "soundfile", "pydub", "audioop"))
    except Exception:
        return False


def model_downloaded() -> bool:
    return (MODEL_DIR / DONE).exists() and (MODEL_DIR / "model.safetensors").exists()


def migrate_model(log=print):
    """Move a model downloaded by Mirage 2.1.0 out of Mirage's own folder."""
    global MODEL_DIR
    if MODEL_DIR == OLD_MODEL_DIR or not (OLD_MODEL_DIR / DONE).exists():
        return
    try:
        if (MODEL_DIR / DONE).exists():
            shutil.rmtree(OLD_MODEL_DIR, ignore_errors=True)
            return
        MODEL_DIR.parent.mkdir(parents=True, exist_ok=True)
        if MODEL_DIR.exists():
            shutil.rmtree(MODEL_DIR)
        # a rename only (instant on the same drive); never a half-finished copy. The Mirage that is
        # closing may still hold the files for a moment, so try a few times.
        for attempt in range(5):
            try:
                os.rename(OLD_MODEL_DIR, MODEL_DIR)
                break
            except OSError:
                if attempt == 4:
                    raise
                time.sleep(1.5)
        log(f"Moved the voice model to {MODEL_DIR}")
    except Exception as e:
        log(f"Couldn't move the voice model ({e}); using it where it is.")
        MODEL_DIR = OLD_MODEL_DIR


def installed() -> bool:
    return packages_installed() and model_downloaded()


_nvidia_cache = None


def nvidia_info(cached=False):
    """(highest CUDA version the driver supports, card name), or (None, "") without an NVIDIA card."""
    global _nvidia_cache
    if cached and _nvidia_cache is not None:
        return _nvidia_cache
    _nvidia_cache = _nvidia_query()
    return _nvidia_cache


def _driver_cuda():
    """The CUDA version the installed NVIDIA driver supports, asked from the driver itself."""
    try:
        import ctypes
        lib = ctypes.WinDLL("nvcuda.dll") if sys.platform.startswith("win") else ctypes.CDLL("libcuda.so.1")
        v = ctypes.c_int(0)
        if lib.cuDriverGetVersion(ctypes.byref(v)) == 0 and v.value > 0:
            return v.value // 1000 + (v.value % 1000) / 100  # 13000 -> 13.0, 12080 -> 12.8
    except Exception:
        pass
    return None


NVIDIA_NOTE = ""  # what nvidia-smi said, for the log


def _nvidia_query():
    global NVIDIA_NOTE
    cuda = _driver_cuda()
    exe = shutil.which("nvidia-smi")
    if not exe and sys.platform.startswith("win"):
        guess = Path(os.environ.get("SystemRoot", r"C:\Windows")) / "System32" / "nvidia-smi.exe"
        exe = str(guess) if guess.exists() else None
    name = ""
    if exe:
        try:
            q = subprocess.run([exe, "--query-gpu=name,driver_version", "--format=csv,noheader"], capture_output=True,
                               text=True, timeout=20, creationflags=NO_WINDOW).stdout.strip().splitlines()
            if q:
                name = q[0].split(",")[0].strip()
                NVIDIA_NOTE = q[0].strip()
            if cuda is None:
                out = subprocess.run([exe], capture_output=True, text=True, timeout=20, creationflags=NO_WINDOW).stdout
                m = re.search(r"CUDA[ A-Za-z]*Version\s*:\s*(\d+\.\d+)", out)
                cuda = float(m.group(1)) if m else None
                if not m:
                    NVIDIA_NOTE += " | " + next((l.strip(" |") for l in out.splitlines() if "Driver" in l), "")[:160]
        except Exception as e:
            NVIDIA_NOTE += f" | nvidia-smi: {e}"
    return cuda, name


def cuda_build_for(driver_cuda):
    """The newest PyTorch graphics-card build this driver can run, or None."""
    for tag, need in CUDA_BUILDS:
        if driver_cuda is not None and driver_cuda + 1e-6 >= need:
            return tag
    return None


def gpu_report(torch=None):
    """Why the voice does or doesn't run on the graphics card, in plain words."""
    driver_cuda, gpu = nvidia_info(cached=True)
    rep = {"nvidia": bool(gpu or driver_cuda), "gpu": gpu, "driver_cuda": driver_cuda, "torch": "", "torch_cuda": "",
           "using_gpu": False, "can_switch": False, "reason": ""}
    if torch is not None:
        rep["torch"] = torch.__version__
        rep["torch_cuda"] = getattr(torch.version, "cuda", None) or ""
        rep["using_gpu"] = bool(torch.cuda.is_available())
    if rep["using_gpu"]:
        return rep
    if not rep["nvidia"]:
        rep["reason"] = "No NVIDIA graphics card was found, so the voice runs on the processor."
    elif not cuda_build_for(driver_cuda):
        need = min(b[1] for b in CUDA_BUILDS)
        if driver_cuda is None:
            rep["reason"] = (f"Mirage found your {gpu or 'NVIDIA card'} but couldn't tell which CUDA version its driver "
                             "supports, so the voice runs on the processor. Updating the driver in the NVIDIA app usually helps.")
        else:
            rep["reason"] = (f"Your NVIDIA driver is too old for the graphics card version of PyTorch (it supports CUDA "
                             f"{driver_cuda}, and {need} or newer is needed). Update the driver in the NVIDIA app, "
                             "then restart Mirage.")
    elif torch is not None and not rep["torch_cuda"]:
        rep["reason"] = f"PyTorch was installed without graphics card support. Switch to use your {gpu or 'NVIDIA card'}."
        rep["can_switch"] = True
    elif torch is not None:
        rep["reason"] = "PyTorch has graphics card support but can't reach the card. Restarting the PC usually fixes this."
        rep["can_switch"] = True
    return rep


def torch_info():
    """(installed torch version or None, whether it can use the graphics card). Runs outside Mirage
    so PyTorch isn't loaded (and locked) by the app while it's being installed."""
    try:
        r = subprocess.run([_python(), "-c", "import torch; print(torch.__version__); print(int(torch.cuda.is_available()))"],
                           capture_output=True, text=True, timeout=180, creationflags=NO_WINDOW)
        lines = r.stdout.strip().splitlines()
        if r.returncode == 0 and len(lines) >= 2:
            return lines[-2].strip(), lines[-1].strip() == "1"
    except Exception:
        pass
    return None, False


# --------------------------------------------------------------------------- #
# Installing
# --------------------------------------------------------------------------- #
def _pip(args, progress, label):
    """Run pip, reporting download progress. Returns (ok, last error line)."""
    base = [_python(), "-m", "pip", "install", "--disable-pip-version-check"]
    for bar in (["--progress-bar", "raw"], []):
        proc = subprocess.Popen(base + bar + list(args), stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                                text=True, encoding="utf-8", errors="replace", creationflags=NO_WINDOW)
        lines, current, last = [], "", 0.0
        for line in proc.stdout:
            line = line.rstrip()
            m = re.match(r"Progress (\d+) of (\d+)", line)
            if m:
                done, total = int(m.group(1)), int(m.group(2))
                if total > 20e6 and time.time() - last > 0.5:
                    last = time.time()
                    progress(f"{label}: downloading {current} ({_gb(done)} of {_gb(total)})")
                continue
            if line.strip():
                lines.append(line)
            m = re.match(r"\s*Downloading (?:https?://\S+/)?([A-Za-z0-9_.]+?)-\d", line)
            if m:
                current = m.group(1).replace("_", "-")
        proc.wait()
        text = "\n".join(lines)
        if proc.returncode == 0:
            return True, ""
        if bar and ("invalid choice" in text or "no such option" in text):
            continue  # an older pip without the progress option: run again without it
        err = next((l for l in reversed(lines) if "ERROR" in l), lines[-1] if lines else "unknown error")
        return False, err.strip()[:240]
    return False, "pip failed"


def install(progress=lambda msg: None, log=lambda msg: None):
    """Install everything the built-in voice needs. Returns (ok, message)."""
    free = shutil.disk_usage(BASE_DIR).free
    if free < 8e9:
        return False, f"Not enough free disk space: the voice needs about 7 GB and there's {_gb(free)} free."

    progress("Checking your graphics card…")
    cuda, gpu = nvidia_info()
    have, have_cuda = torch_info()
    log(f"Voice install: NVIDIA card {gpu or 'not found'} (driver CUDA {cuda}; {NVIDIA_NOTE}); PyTorch {have or 'not installed'}"
        f"{' with' if have_cuda else ' without'} graphics card support; Python {sys.version.split()[0]}")

    if not have or (cuda and not have_cuda):
        if have:  # a version without graphics card support is installed; swap it out
            subprocess.run([_python(), "-m", "pip", "uninstall", "-y", "torch"], capture_output=True, creationflags=NO_WINDOW)
        progress("Getting ready to install PyTorch…")
        ok, err = _pip(TORCH_DEPS, progress, "PyTorch")
        if not ok:
            return False, f"Install failed: {err}"
        done = False
        if cuda:
            for tag, need in CUDA_BUILDS:
                if cuda + 1e-6 < need:
                    continue
                progress(f"Installing PyTorch for your {gpu or 'NVIDIA card'} (about 3 GB)…")
                done, err = _pip(["torch", "--index-url", f"https://download.pytorch.org/whl/{tag}"],
                                 progress, "PyTorch")
                log(f"Voice install: PyTorch {tag} " + ("installed" if done else f"failed: {err}"))
                if done:
                    break
        if not done:
            progress("Installing PyTorch (about 250 MB)…")
            ok, err = _pip(["torch"], progress, "PyTorch")
            log("Voice install: PyTorch for the processor " + ("installed" if ok else f"failed: {err}"))
            if not ok:
                return False, f"Install failed: {err}"

    progress("Installing the voice engine…")
    pkgs = ["torch", "transformers>=5.3", "accelerate", "soundfile", "pydub", "huggingface_hub>=1", "numpy"]
    if sys.version_info >= (3, 13):
        pkgs.append("audioop-lts")  # pydub needs audioop, which newer Pythons no longer include
    ok, err = _pip(pkgs, progress, "Voice engine")
    log("Voice install: packages " + ("installed" if ok else f"failed: {err}"))
    if ok:
        # OmniVoice also lists packages for its demo website and for training; Mirage needs neither
        ok, err = _pip(["--no-deps", f"omnivoice=={OMNIVOICE_VERSION}"], progress, "Voice engine")
    if not ok:
        return False, f"Install failed: {err}"

    if not model_downloaded():
        ok, err = download_model(progress)
        if not ok:
            return False, err

    _, has_gpu = torch_info()
    try:  # pip may have put the packages in a per-user folder Python only looks in from the next start
        import site
        user_site = site.getusersitepackages()
        if os.path.isdir(user_site) and user_site not in sys.path:
            site.addsitedir(user_site)
    except Exception:
        pass
    if not packages_installed():
        return True, "Installed. Restart Mirage to use it."
    return True, "Installed. " + ("It runs on your graphics card." if has_gpu else
                                  "It runs on the processor, so replies take a few seconds. Pick Fast quality for quicker replies.")


def _folder_size(path: Path) -> int:
    total = 0
    for root, _, files in os.walk(path):
        for f in files:
            try:
                total += os.path.getsize(os.path.join(root, f))
            except OSError:
                pass
    return total


def download_model(progress=lambda msg: None):
    """Download the voice model into Mirage's folder. Returns (ok, message)."""
    MODEL_DIR.mkdir(parents=True, exist_ok=True)
    code = ("import sys; from huggingface_hub import snapshot_download; "
            "snapshot_download(sys.argv[1], local_dir=sys.argv[2])")
    # plain downloads (not Xet) so the files grow steadily and the progress shown is real
    env = dict(os.environ, HF_HUB_DISABLE_TELEMETRY="1", HF_HUB_DISABLE_PROGRESS_BARS="1",
               HF_HUB_DISABLE_SYMLINKS_WARNING="1", HF_HUB_DISABLE_XET="1")
    proc = subprocess.Popen([_python(), "-c", code, MODEL_ID, str(MODEL_DIR)], stdout=subprocess.PIPE,
                            stderr=subprocess.STDOUT, text=True, encoding="utf-8", errors="replace",
                            creationflags=NO_WINDOW, env=env)
    out = []
    reader = threading.Thread(target=lambda: out.extend(proc.stdout), daemon=True)
    reader.start()
    start = time.time()
    while proc.poll() is None:
        size = _folder_size(MODEL_DIR)
        mins = int(time.time() - start) // 60
        progress(f"Downloading the voice model: {_gb(min(size, MODEL_BYTES))} of {_gb(MODEL_BYTES)}"
                 + (f" ({mins} min)" if mins else ""))
        time.sleep(1.5)
    reader.join(2)
    if proc.returncode != 0 or not (MODEL_DIR / "model.safetensors").exists():
        lines = [l.strip() for l in out if l.strip()]
        err = next((l for l in reversed(lines) if "Error" in l), lines[-1] if lines else "unknown error")
        return False, f"The voice model didn't download: {err[:200]}"
    (MODEL_DIR / DONE).write_text(time.strftime("%Y-%m-%d %H:%M"))
    return True, "Voice model downloaded."


# --------------------------------------------------------------------------- #
# Audio helpers
# --------------------------------------------------------------------------- #
def _torch_resample(waveform, orig_freq, new_freq, lowpass_filter_width=6, rolloff=0.99, **_):
    """Band-limited (windowed sinc) resampling of a (..., time) tensor."""
    import torch
    import torch.nn.functional as F
    orig, new = int(orig_freq), int(new_freq)
    if orig == new:
        return waveform
    g = math.gcd(orig, new)
    orig, new = orig // g, new // g
    shape = waveform.shape
    x = waveform.reshape(-1, shape[-1])
    dtype = x.dtype if x.is_floating_point() else torch.float32
    x = x.to(dtype)
    base = min(orig, new) * rolloff
    width = math.ceil(lowpass_filter_width * orig / base)
    idx = torch.arange(-width, width + orig, dtype=torch.float64, device=x.device)[None, None] / orig
    t = torch.arange(0, -new, -1, dtype=torch.float64, device=x.device)[:, None, None] / new + idx
    t = (t * base).clamp(-lowpass_filter_width, lowpass_filter_width)
    window = torch.cos(t * math.pi / lowpass_filter_width / 2) ** 2
    t = t * math.pi
    kernel = torch.where(t == 0, torch.ones_like(t), torch.sin(t) / t) * window * (base / orig)
    length = x.shape[-1]
    y = F.conv1d(F.pad(x, (width, width + orig))[:, None], kernel.to(dtype), stride=orig)
    y = y.transpose(1, 2).reshape(x.shape[0], -1)[..., :math.ceil(new * length / orig)]
    return y.reshape(*shape[:-1], y.shape[-1])


def resample(audio, sr, new_sr):
    """numpy float32 mono -> numpy float32 mono at new_sr."""
    import numpy as np
    if sr == new_sr:
        return audio.astype(np.float32)
    import torch
    return _torch_resample(torch.from_numpy(audio.astype(np.float32)), sr, new_sr).numpy()


def ensure_torchaudio():
    """OmniVoice imports torchaudio only to resample audio. Use the real one if it loads; if not,
    put in a small stand-in so Mirage doesn't need a torchaudio built for this exact PyTorch."""
    if "torchaudio" in sys.modules:
        return
    try:
        import torchaudio  # noqa: F401
        return
    except Exception:
        for k in [k for k in sys.modules if k == "torchaudio" or k.startswith("torchaudio.")]:
            sys.modules.pop(k, None)
    import importlib.machinery
    import types
    ta = types.ModuleType("torchaudio")
    fn = types.ModuleType("torchaudio.functional")
    ta.__spec__ = importlib.machinery.ModuleSpec("torchaudio", None)
    fn.__spec__ = importlib.machinery.ModuleSpec("torchaudio.functional", None)
    fn.resample = _torch_resample
    ta.functional = fn
    ta.__version__ = "0+mirage"
    sys.modules["torchaudio"] = ta
    sys.modules["torchaudio.functional"] = fn


def read_audio(path):
    """Any WAV/MP3/FLAC/OGG file -> (mono float32 numpy, sample rate)."""
    import soundfile as sf
    try:
        data, sr = sf.read(str(path), dtype="float32", always_2d=True)
    except Exception:
        raise ValueError("Mirage can't read that file. Use a WAV, MP3, FLAC or OGG recording.")
    return data.mean(axis=1), sr


def prepare_reference(path, max_seconds=15.0, allow_trim=True):
    """Load a recording for cloning: mono, 24 kHz, quiet edges cut, not too quiet."""
    import numpy as np
    audio, sr = read_audio(path)
    audio = resample(audio, sr, SAMPLE_RATE)
    peak = float(np.max(np.abs(audio))) if audio.size else 0.0
    if peak < 1e-4:
        raise ValueError("That recording is silent.")
    loud = np.nonzero(np.abs(audio) > peak * 0.03)[0]
    pad = int(0.15 * SAMPLE_RATE)
    audio = audio[max(0, loud[0] - pad): loud[-1] + pad]
    secs = len(audio) / SAMPLE_RATE
    if secs < 2:
        raise ValueError("That recording is too short. Use 5 to 15 seconds of clear speech.")
    if secs > max_seconds:
        if not allow_trim:
            raise ValueError(f"That recording is {secs:.0f} seconds. Use one under {max_seconds:.0f} seconds "
                             "(10 to 15 is best), or leave the transcript empty and Mirage will cut it.")
        audio = audio[: int(max_seconds * SAMPLE_RATE)]
    return (audio / max(peak, 1e-4) * 0.9).astype(np.float32)


def write_wav(path, audio, sr=SAMPLE_RATE):
    import soundfile as sf
    sf.write(str(path), audio, sr, subtype="PCM_16")


def split_sentences(text, max_len=220):
    """Break a reply into pieces so the first one can play while the next is made."""
    text = re.sub(r"\s+", " ", text).strip()
    parts = [p for p in re.split(r"(?<=[.!?;:])\s+", text) if p]
    chunks, cur = [], ""
    for p in parts:
        while len(p) > max_len:  # a very long sentence: break at a comma or space
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


def transcribe(audio_16k, whisper=None):
    """Write down what's said in a clip with Mirage's Whisper (installed under Settings > Listening)."""
    model = getattr(whisper, "model", None)
    if model is None:
        try:
            from faster_whisper import WhisperModel
        except Exception:
            raise ValueError("Type what's said in the recording, or install Whisper (Settings > Listening) "
                             "and Mirage will write it down for you.")
        model = WhisperModel("base.en", device="cpu", compute_type="int8")
    segments, _ = model.transcribe(audio_16k, language="en", beam_size=5, vad_filter=False,
                                   condition_on_previous_text=False)
    text = " ".join(s.text.strip() for s in segments).strip()
    if not text:
        raise ValueError("Couldn't make out any words in that recording.")
    return text


# --------------------------------------------------------------------------- #
# Voices
# --------------------------------------------------------------------------- #
def list_voices():
    out = []
    if VOICES_DIR.is_dir():
        for f in VOICES_DIR.glob("*.json"):
            try:
                v = json.loads(f.read_text(encoding="utf-8"))
                if v.get("id") == f.stem:
                    out.append(v)
            except Exception:
                pass
    return sorted(out, key=lambda v: v.get("created", 0))


def get_voice(vid):
    if not vid or not re.fullmatch(r"[\w-]+", vid):
        return None
    f = VOICES_DIR / f"{vid}.json"
    try:
        return json.loads(f.read_text(encoding="utf-8")) if f.exists() else None
    except Exception:
        return None


def save_voice(v):
    VOICES_DIR.mkdir(exist_ok=True)
    (VOICES_DIR / f"{v['id']}.json").write_text(json.dumps(v, indent=2, ensure_ascii=False), encoding="utf-8")


def delete_voice(vid):
    v = get_voice(vid)
    if not v:
        return False
    for ext in (".json", ".wav", ".pt"):
        try:
            (VOICES_DIR / f"{vid}{ext}").unlink()
        except FileNotFoundError:
            pass
    return True


def rename_voice(vid, name):
    v = get_voice(vid)
    if v and name.strip():
        v["name"] = name.strip()[:60]
        save_voice(v)
    return v


def new_voice(name, kind, **fields):
    slug = re.sub(r"[^a-z0-9]+", "-", name.lower()).strip("-")[:24] or "voice"
    v = {"id": f"{slug}-{uuid.uuid4().hex[:6]}", "name": name.strip()[:60] or "Voice", "kind": kind,
         "instruct": "", "ref_text": "", "audio": "", "language": "English", "seed": None,
         "created": time.time()}
    v.update(fields)
    return v


# --------------------------------------------------------------------------- #
# Bringing voices over from VoiceStudio (reads its saved voices; VoiceStudio can be closed)
# --------------------------------------------------------------------------- #
def voicestudio_dirs():
    """Folders holding VoiceStudio's saved voices (omnivoice.db). Where it is depends on how
    VoiceStudio was installed, so look in the usual places and in app folders named like it."""
    if sys.platform.startswith("win"):
        roots = [Path(os.environ[k]) for k in ("APPDATA", "LOCALAPPDATA") if os.environ.get(k)]
        roots += [r / "Programs" for r in roots]
    elif sys.platform == "darwin":
        roots = [Path.home() / "Library" / "Application Support"]
    else:
        roots = [Path.home(), Path.home() / ".config", Path.home() / ".local" / "share"]
    cands = [Path(os.environ["OMNIVOICE_DATA_DIR"])] if os.environ.get("OMNIVOICE_DATA_DIR") else []
    cands += [r / "OmniVoice" for r in roots] + [Path.home() / ".omnivoice"]
    for r in roots:
        try:
            tops = [d for d in r.iterdir() if d.is_dir() and re.search(r"voice|omni", d.name, re.I)]
        except OSError:
            continue
        for top in tops:
            for base, dirs, files in os.walk(top):
                depth = len(Path(base).relative_to(top).parts)
                if "omnivoice.db" in files:
                    cands.append(Path(base))
                dirs[:] = [] if depth >= 3 else [d for d in dirs if d.lower() not in ("models", "cache", "hf_cache", "engines", "node_modules", "logs")]
    out, seen = [], set()
    for c in cands:
        try:
            key = str(c.resolve()).lower()
        except OSError:
            continue
        if key not in seen and (c / "omnivoice.db").is_file():
            seen.add(key)
            out.append(c)
    # the most recently used one first, so its copy of a voice wins over an older install's
    return sorted(out, key=lambda c: max((c / f).stat().st_mtime for f in ("omnivoice.db", "omnivoice.db-wal")
                                         if (c / f).exists()), reverse=True)


def _vs_rows():
    """Every saved VoiceStudio voice, each tagged with the folder it came from."""
    rows, seen = [], set()
    for base in voicestudio_dirs():
        try:
            for r in _vs_read(base / "omnivoice.db"):
                if r.get("id") not in seen:
                    seen.add(r.get("id"))
                    r["_base"] = base
                    rows.append(r)
        except Exception:
            pass
    return rows


def _vs_read(db):
    def read(path, uri):
        con = sqlite3.connect(path, uri=uri, timeout=3)
        con.row_factory = sqlite3.Row
        try:
            return [dict(r) for r in con.execute("SELECT * FROM voice_profiles ORDER BY name")]
        finally:
            con.close()

    try:
        return read(db.resolve().as_uri() + "?mode=ro", True)
    except Exception:
        # VoiceStudio keeps recent changes in side files; read a copy with them included
        with tempfile.TemporaryDirectory() as tmp:
            for suffix in ("", "-wal", "-shm"):
                src = db.with_name(db.name + suffix)
                if src.exists():
                    shutil.copy2(src, Path(tmp) / (db.name + suffix))
            return read(str(Path(tmp) / db.name), False)


def _vs_audio_path(row):
    rel = row.get("locked_audio_path") if row.get("is_locked") and row.get("locked_audio_path") else row.get("ref_audio_path")
    if not rel:
        return None
    p = Path(rel)
    base = row.get("_base") or Path(".")
    for cand in ([p] if p.is_absolute() else []) + [base / "voices" / rel, base / rel, base / "voices" / p.name]:
        if cand.exists() and cand.is_file():
            return cand
    return None


def voicestudio_voices():
    """Voices saved in VoiceStudio: [{vs_id, name, kind, demo, has_audio}]."""
    out = []
    try:
        rows = _vs_rows()
    except Exception:
        return []
    for r in rows:
        out.append({"vs_id": r.get("id"), "name": r.get("name") or "Voice", "kind": r.get("kind") or "clone",
                    "demo": bool(r.get("is_demo")), "has_audio": _vs_audio_path(r) is not None,
                    "instruct": r.get("instruct") or ""})
    return out


def import_voicestudio(vs_id):
    """Copy one VoiceStudio voice into Mirage. Returns the Mirage voice (updated if it was imported before)."""
    row = next((r for r in _vs_rows() if r.get("id") == vs_id), None)
    if not row:
        raise ValueError("That VoiceStudio voice wasn't found.")
    existing = next((v for v in list_voices() if v.get("vs_id") == vs_id), None)
    lang = row.get("language") or "English"
    text = (row.get("ref_text") or "").strip()
    if len(text) in (100, 200):
        text = ""  # VoiceStudio sometimes stored a cut-off transcript; Mirage writes a fresh one
    v = existing or new_voice(row.get("name") or "Voice", "design" if row.get("kind") == "design" else "clone")
    v.update({"name": row.get("name") or v["name"], "instruct": clean_instruct(row.get("instruct")),
              "language": None if lang.lower() == "auto" else lang, "seed": row.get("seed"),
              "source": "VoiceStudio", "vs_id": vs_id, "ref_text": text, "audio": ""})
    src = _vs_audio_path(row)
    if src:
        try:
            audio = prepare_reference(src, max_seconds=20 if text else 15, allow_trim=not text)
        except ValueError:  # too long for its transcript: cut it and write a new transcript
            audio = prepare_reference(src, max_seconds=15)
            v["ref_text"] = ""
        VOICES_DIR.mkdir(exist_ok=True)
        write_wav(VOICES_DIR / f"{v['id']}.wav", audio)
        v["audio"] = f"{v['id']}.wav"
    elif not v["instruct"]:
        raise ValueError(f"“{v['name']}” has no recording or description Mirage can use.")
    try:
        (VOICES_DIR / f"{v['id']}.pt").unlink()  # made again from the new recording
    except FileNotFoundError:
        pass
    save_voice(v)
    return v


# --------------------------------------------------------------------------- #
# The engine
# --------------------------------------------------------------------------- #
class LocalVoice:
    def __init__(self, log=print, on_change=lambda: None, whisper=None):
        self.log = log
        self.on_change = on_change
        self.whisper = whisper
        self.model = None
        self.torch = None
        self.state = "off"  # off | installing | loading | ready | error
        self.detail = ""
        self.gpu = False
        self.lock = threading.RLock()  # one generation at a time
        self._prompts = {}
        self._cache = {}
        self._preview = None
        self._loader = None
        self.last_error = ""
        self.gpu_info = None
        migrate_model(log)

    # ---- status ----
    def ready(self):
        return self.model is not None

    def status(self):
        return {"installed": installed(), "packages": packages_installed(), "model": model_downloaded(),
                "state": self.state, "detail": self.detail, "gpu": self.gpu, "gpu_info": self.gpu_info,
                "last_error": self.last_error}

    def _set(self, state, detail=""):
        self.state, self.detail = state, detail
        try:
            self.on_change()
        except Exception:
            pass

    # ---- loading ----
    def load_async(self, then=None):
        if self.model is not None:
            if then:
                then()
            return
        if (self._loader and self._loader.is_alive()) or not installed():
            return
        self._loader = threading.Thread(target=self._load, args=(then,), daemon=True, name="voice-load")
        self._loader.start()

    def _load(self, then=None):
        self._set("loading", "Loading the voice model…")
        try:
            ensure_torchaudio()
            import torch
            from omnivoice import OmniVoice
            if torch.cuda.is_available():
                device, dtype, where = "cuda:0", torch.float16, "your graphics card (" + torch.cuda.get_device_name(0) + ")"
            else:
                device, dtype, where = "cpu", torch.float32, "the processor"
            self.gpu_info = gpu_report(torch)
            self.log(f"Voice: PyTorch {self.gpu_info['torch']} (CUDA build {self.gpu_info['torch_cuda'] or 'none'}), "
                     f"NVIDIA {self.gpu_info['gpu'] or 'none'} driver CUDA {self.gpu_info['driver_cuda']} ({NVIDIA_NOTE})")
            t0 = time.time()
            model = OmniVoice.from_pretrained(str(MODEL_DIR), device_map=device, dtype=dtype)
            model.eval()
            with self.lock:
                self.torch, self.model, self.gpu = torch, model, device != "cpu"
                self._prompts.clear()
                self._cache.clear()
            self.log(f"Voice model loaded on {device} in {time.time() - t0:.0f} s.")
            self._set("ready", f"Ready on {where}")
            if then:
                then()
        except Exception as e:
            self.log("Voice model failed to load:\n" + traceback.format_exc())
            self.last_error = f"{type(e).__name__}: {e}"
            self._set("error", f"Couldn't load the voice model: {e}")

    def unload(self):
        with self.lock:
            self.model = None
            self._prompts.clear()
            self._cache.clear()
            import gc
            gc.collect()
            try:
                if self.torch is not None and self.torch.cuda.is_available():
                    self.torch.cuda.empty_cache()
            except Exception:
                pass
        if self.state in ("ready", "error"):
            self._set("off", "")

    # ---- making speech ----
    def _prompt_for(self, voice):
        """The voice's recording turned into what the model reads, made once and kept."""
        vid = voice.get("id")
        if vid in self._prompts:
            return self._prompts[vid]
        wav = VOICES_DIR / voice["audio"] if voice.get("audio") else None
        if not wav or not wav.exists():
            return None
        from omnivoice import VoiceClonePrompt
        pt = VOICES_DIR / f"{vid}.pt"
        prompt = None
        if pt.exists() and pt.stat().st_mtime >= wav.stat().st_mtime:
            try:
                prompt = VoiceClonePrompt.load(str(pt))
            except Exception as e:
                self.log(f"Remaking voice file for {voice.get('name')}: {e}")
        if prompt is None:
            text = voice.get("ref_text") or ""
            if not text:
                audio, sr = read_audio(wav)
                text = transcribe(resample(audio, sr, 16000), self.whisper)
                voice["ref_text"] = text
                if get_voice(vid):
                    save_voice(voice)
            prompt = self.model.create_voice_clone_prompt(ref_audio=str(wav), ref_text=text)
            if get_voice(vid):
                prompt.save(str(pt))
        self._prompts[vid] = prompt
        return prompt

    def synthesize(self, text, voice=None, speed=1.0, quality="balanced"):
        """Text -> (float32 numpy audio, sample rate)."""
        import numpy as np
        with self.lock:
            if self.model is None:
                raise RuntimeError("The voice model isn't loaded.")
            voice = voice or {"id": "_default", "instruct": DEFAULT_DESIGN, "seed": 7}
            kw = {"text": text, "language": voice.get("language", "English"),
                  "num_step": QUALITY_STEPS.get(quality, QUALITY_STEPS["balanced"])}
            if speed and abs(speed - 1.0) > 0.02:
                kw["speed"] = float(speed)
            prompt = self._prompt_for(voice)
            if prompt is not None:
                kw["voice_clone_prompt"] = prompt
            else:
                kw["instruct"] = clean_instruct(voice.get("instruct")) or DEFAULT_DESIGN
                if voice.get("seed") is not None:
                    self.torch.manual_seed(int(voice["seed"]))
            with self.torch.inference_mode():
                audio = self.model.generate(**kw)[0]
            return np.asarray(audio, dtype=np.float32).reshape(-1), int(self.model.sampling_rate)

    def speak(self, text, voice=None, speed=1.0, quality="balanced", volume=1.0):
        """Say text out loud. The next sentence is made while the current one plays."""
        import numpy as np
        try:
            import sounddevice as sd
        except Exception:
            sd = None
        playing = False
        for chunk in split_sentences(text):
            key = ((voice or {}).get("id"), round(speed, 2), quality, chunk)
            got = self._cache.get(key)
            if got is None:
                got = self.synthesize(chunk, voice, speed, quality)
                if len(chunk) <= 40:  # remember short, repeated lines like "Yes?"
                    if len(self._cache) > 80:
                        self._cache.clear()
                    self._cache[key] = got
            audio, sr = got
            audio = np.clip(audio * max(0.0, min(1.0, volume)), -1, 1)
            if sd is not None:
                if playing:
                    sd.wait()
                sd.play(audio, sr)
                playing = True
            else:
                _play_blocking(audio, sr)
        if playing:
            sd.wait()
        self.last_error = ""

    # ---- designing, cloning, importing ----
    def design_preview(self, instruct, seed=None, play=True):
        instruct = clean_instruct(instruct) or DEFAULT_DESIGN
        seed = int(seed) if seed is not None else random.randint(1, 2 ** 31 - 1)
        audio, sr = self.synthesize(SAMPLE_TEXT, {"id": "_preview", "instruct": instruct, "seed": seed}, quality="best")
        self._preview = {"instruct": instruct, "seed": seed, "audio": audio, "sr": sr}
        if play:
            play_audio(audio, sr)
        return instruct, seed

    def design_save(self, name):
        p = self._preview
        if not p:
            raise ValueError("Make a preview first.")
        v = new_voice(name or "My voice", "design", instruct=p["instruct"], seed=p["seed"], ref_text=SAMPLE_TEXT)
        VOICES_DIR.mkdir(exist_ok=True)
        write_wav(VOICES_DIR / f"{v['id']}.wav", resample(p["audio"], p["sr"], SAMPLE_RATE))
        v["audio"] = f"{v['id']}.wav"
        save_voice(v)
        self._preview = None
        return v

    def clone_save(self, path, name, transcript=""):
        transcript = (transcript or "").strip()
        audio = prepare_reference(path, max_seconds=20 if transcript else 15, allow_trim=not transcript)
        if not transcript:
            transcript = transcribe(resample(audio, SAMPLE_RATE, 16000), self.whisper)
        v = new_voice(name or Path(path).stem, "clone", ref_text=transcript)
        VOICES_DIR.mkdir(exist_ok=True)
        write_wav(VOICES_DIR / f"{v['id']}.wav", audio)
        v["audio"] = f"{v['id']}.wav"
        save_voice(v)
        if self.model is not None:
            with self.lock:
                self._prompt_for(v)
        return v

    def forget(self, vid):
        """Drop anything kept in memory for a voice (after it was changed or deleted)."""
        with self.lock:
            self._prompts.pop(vid, None)
            for k in [k for k in self._cache if k[0] == vid]:
                self._cache.pop(k, None)


def _play_blocking(audio, sr):
    import io
    import numpy as np
    if sys.platform.startswith("win"):
        import wave
        import winsound
        buf = io.BytesIO()
        with wave.open(buf, "wb") as w:
            w.setnchannels(1)
            w.setsampwidth(2)
            w.setframerate(sr)
            w.writeframes((np.clip(audio, -1, 1) * 32767).astype("<i2").tobytes())
        winsound.PlaySound(buf.getvalue(), winsound.SND_MEMORY)


def play_audio(audio, sr):
    try:
        import sounddevice as sd
        sd.play(audio, sr)
        sd.wait()
    except Exception:
        _play_blocking(audio, sr)


# --------------------------------------------------------------------------- #
# Switching PyTorch to the graphics card version (runs in its own window while Mirage is closed,
# because Windows won't let PyTorch's files be replaced while Mirage has them open)
# --------------------------------------------------------------------------- #
def _pid_alive(pid):
    if sys.platform.startswith("win"):
        import ctypes
        k = ctypes.windll.kernel32
        h = k.OpenProcess(0x1000, False, int(pid))  # query-only access
        if not h:
            return False
        code = ctypes.c_ulong()
        k.GetExitCodeProcess(h, ctypes.byref(code))
        k.CloseHandle(h)
        return code.value == 259  # still running
    try:
        os.kill(int(pid), 0)
        return True
    except OSError:
        return False


def switch_to_gpu(wait_pid=None):
    print("Mirage: switching the voice to your graphics card.\n")
    if wait_pid:
        print("Waiting for Mirage to close…")
        for _ in range(120):
            if not _pid_alive(wait_pid):
                break
            time.sleep(0.5)
    cuda, gpu = nvidia_info()
    tag = cuda_build_for(cuda)
    py = _python()
    if not tag:
        print(f"Your NVIDIA driver supports CUDA {cuda}; 13.0 or newer is needed. Update the driver, then try again.")
    else:
        subprocess.run([py, "-m", "pip", "uninstall", "-y", "torch"])
        ok = False
        for t, need in CUDA_BUILDS:
            if cuda + 1e-6 < need:
                continue
            print(f"\nDownloading PyTorch for your {gpu or 'NVIDIA card'} ({t}, about 3 GB)…")
            r = subprocess.run([py, "-m", "pip", "install", "--disable-pip-version-check", "torch",
                                "--index-url", f"https://download.pytorch.org/whl/{t}"])
            if r.returncode == 0:
                ok = True
                break
        if not ok:
            print("\nCouldn't get the graphics card version, so the processor version goes back on.")
            subprocess.run([py, "-m", "pip", "install", "--disable-pip-version-check", "torch"])
    ver, has_gpu = torch_info()
    print(f"\nPyTorch {ver}: " + ("the voice now runs on your graphics card." if has_gpu else "the voice runs on the processor."))
    pyw = Path(sys.executable).with_name("pythonw.exe")
    flags = 0x00000008 | 0x00000200 if sys.platform.startswith("win") else 0
    subprocess.Popen([str(pyw if pyw.exists() else sys.executable), str(BASE_DIR / "mirage_app.py"), "--restarted"],
                     cwd=str(BASE_DIR), creationflags=flags, close_fds=True)
    print("Starting Mirage again…")
    if has_gpu:
        time.sleep(4)
    else:
        input("\nPress Enter to close this window.")


if __name__ == "__main__" and len(sys.argv) > 1 and sys.argv[1] == "--gpu":
    switch_to_gpu(sys.argv[2] if len(sys.argv) > 2 else None)
