"""
Mirage's own brain: an open AI model running on this PC with llama.cpp. No account, no usage limits.

- Engine: llama.cpp's llama-server (MIT), the build for NVIDIA cards when there is one.
- Model: Qwen3.5 9B (Apache-2.0) by default, or the lighter Gemma 4 E4B (Apache-2.0). Both can call
  Mirage's tools and look at images (the screen).
- The server goes to sleep after a few idle minutes, which hands the graphics memory back (for games),
  and wakes up by itself on the next question.

Everything lives in %LOCALAPPDATA%\\Mirage\\brain.
"""

import json
import os
import re
import shutil
import socket
import subprocess
import sys
import threading
import time
import traceback
import urllib.request
import zipfile
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent
if sys.platform.startswith("win") and os.environ.get("LOCALAPPDATA"):
    HOME = Path(os.environ["LOCALAPPDATA"]) / "Mirage" / "brain"
else:
    HOME = BASE_DIR / "brain"
ENGINE_DIR = HOME / "llama"
MODELS_DIR = HOME / "models"
WIN = sys.platform.startswith("win")
NO_WINDOW = 0x08000000 if WIN else 0
SERVER = ENGINE_DIR / ("llama-server.exe" if WIN else "llama-server")
# Models come from a fixed commit of each Hugging Face repository and are checked against their SHA-256, so a
# re-uploaded file can't break new installs or slip in unnoticed. Moving to newer files is a deliberate change here.
HF = "https://huggingface.co/{repo}/resolve/{revision}/{file}"
LLAMA_REPO = "ggml-org/llama.cpp"
# The llama.cpp build Mirage is tested with: newer builds rename options now and then (Mirage passes several), so
# moving to a newer one is a deliberate change too. SHA-256 values are the ones GitHub lists for the release files.
LLAMA_TAG = "b12780"
ENGINE_FILES = {
    f"llama-{LLAMA_TAG}-bin-win-cuda-13.5-x64.zip": "f5bc07864b61e067cf64fe35ba583ffaf3e05d64673caec5d3e2637680ae530c",
    "cudart-llama-bin-win-cuda-13.5-x64.zip": "c2bf4cc202bfbaaa7a0b75f5082457c3811326947bb216059b72839d844e9cba",
    f"llama-{LLAMA_TAG}-bin-win-cuda-12.4-x64.zip": "78d9b262d0ec2f65dc6a71a998aea85d0a45dcc3826ceacdc33293ad88209f71",
    "cudart-llama-bin-win-cuda-12.4-x64.zip": "8c79a9b226de4b3cacfd1f83d24f962d0773be79f1e7b75c6af4ded7e32ae1d6",
    f"llama-{LLAMA_TAG}-bin-win-vulkan-x64.zip": "113ab081025931f43f63e5adee78eccdecb2019dbe874a34a6a3e85e468db647",
    f"llama-{LLAMA_TAG}-bin-win-cpu-x64.zip": "22cc5a9b647e9a947796abc1fdc5fa7c797e496dbbd9c5de0f3221474ea1907d",
}

MODELS = {
    "qwen3.5-9b": {
        "name": "Qwen3.5 9B", "blurb": "Smarter", "repo": "unsloth/Qwen3.5-9B-GGUF",
        "revision": "3885219b6810b007914f3a7950a8d1b469d598a5",
        "file": "Qwen3.5-9B-Q4_K_M.gguf", "size": 5680522464,
        "sha256": "03b74727a860a56338e042c4420bb3f04b2fec5734175f4cb9fa853daf52b7e8",
        "mmproj": "mmproj-F16.gguf", "mmproj_size": 918166080,
        "mmproj_sha256": "f70dc3509053962b0d0d3ee8a7eacebf5d60aa560cad78254ae8698516ae029f",
        "sampling": {"temperature": 0.7, "top_p": 0.8, "top_k": 20},
        "think": "kwargs",   # thinking is switched with chat_template_kwargs.enable_thinking
    },
    "gemma4-e4b": {
        "name": "Gemma 4 E4B", "blurb": "Lighter and faster", "repo": "unsloth/gemma-4-E4B-it-GGUF",
        "revision": "bfc15c382204943c3a8fff0c750b94ae2364d7a3",
        "file": "gemma-4-E4B-it-Q4_K_M.gguf", "size": 4977171584,
        "sha256": "85a896a047553e842f25297ee5b031d64ff30147d9c4af17b1e4b394cd1fab87",
        "mmproj": "mmproj-F16.gguf", "mmproj_size": 990372672,
        "mmproj_sha256": "ddf46c21d7078e95338cfc22306b19b276a29a5ad089023449dd54d4b6170a51",
        "sampling": {"temperature": 1.0, "top_p": 0.95, "top_k": 64},
        "think": "token",    # thinking is switched on with <|think|> at the start of the system prompt
    },
}
DEFAULT_MODEL = "qwen3.5-9b"


def _driver_cuda():
    """The CUDA version the NVIDIA driver supports (asked from the driver), or None without an NVIDIA card."""
    try:
        import ctypes
        lib = ctypes.WinDLL("nvcuda.dll") if WIN else ctypes.CDLL("libcuda.so.1")
        v = ctypes.c_int(0)
        if lib.cuDriverGetVersion(ctypes.byref(v)) == 0 and v.value > 0:
            return v.value // 1000 + (v.value % 1000) / 100
    except Exception:
        pass
    return None


def model_dir(key):
    return MODELS_DIR / key


def engine_ready():
    return SERVER.exists()


def model_ready(key):
    m = MODELS.get(key)
    if not m:
        return False
    d = model_dir(key)
    f, mm = d / m["file"], d / m["mmproj"]
    return f.exists() and f.stat().st_size == m["size"] and mm.exists() and mm.stat().st_size == m["mmproj_size"]


def installed(key):
    return engine_ready() and model_ready(key)


def download_mb(key):
    m = MODELS[key]
    mb = 0 if model_ready(key) else (m["size"] + m["mmproj_size"]) / 1e6
    return int(mb + (0 if engine_ready() else 750))


# --------------------------------------------------------------------------- #
# Installing
# --------------------------------------------------------------------------- #
def _engine_downloads(log=lambda m: None):
    """[(file name, url, sha256)] of the llama.cpp build that fits this PC: the NVIDIA build (plus its CUDA runtime)
    for the newest CUDA the driver supports, otherwise Vulkan, which runs on any graphics card (or the processor)."""
    cuda = _driver_cuda()
    if cuda and cuda >= 13.5 - 1e-6:
        names = [f"llama-{LLAMA_TAG}-bin-win-cuda-13.5-x64.zip", "cudart-llama-bin-win-cuda-13.5-x64.zip"]
    elif cuda and cuda >= 12.4 - 1e-6:
        names = [f"llama-{LLAMA_TAG}-bin-win-cuda-12.4-x64.zip", "cudart-llama-bin-win-cuda-12.4-x64.zip"]
    else:
        if cuda:
            log(f"Brain install: the NVIDIA driver only supports CUDA {cuda}; using the Vulkan build")
        names = [f"llama-{LLAMA_TAG}-bin-win-vulkan-x64.zip"]
    base = f"https://github.com/{LLAMA_REPO}/releases/download/{LLAMA_TAG}/"
    return [(n, base + n, ENGINE_FILES[n]) for n in names]


def install(key, progress=lambda m: None, log=lambda m: None):
    """Download the engine (once) and a model. Returns (ok, message)."""
    m = MODELS[key]
    need = download_mb(key) * 1e6 * 1.15
    free = shutil.disk_usage(HOME.parent if HOME.parent.exists() else Path.home()).free
    if free < need + 1e9:
        return False, f"Not enough free disk space: this needs about {need / 1e9:.0f} GB and there's {free / 1e9:.1f} GB free."
    from download import fetch
    try:
        if not engine_ready():
            progress("Finding the right engine for your PC…")
            files = _engine_downloads(log)
            log(f"Brain install: engine files {[n for n, _, _ in files]}")
            tmp = HOME / "download"
            for name, url, sha in files:
                z = tmp / name
                fetch(url, z, progress, "the brain's engine", sha256=sha)
                progress("Unpacking the engine…")
                with zipfile.ZipFile(z) as zf:
                    for info in zf.infolist():
                        target = (ENGINE_DIR / Path(info.filename).name)
                        if info.is_dir() or ".." in Path(info.filename).parts:
                            continue
                        ENGINE_DIR.mkdir(parents=True, exist_ok=True)
                        with zf.open(info) as src, open(target, "wb") as dst:
                            shutil.copyfileobj(src, dst)
                z.unlink()
            shutil.rmtree(tmp, ignore_errors=True)
            if not engine_ready():
                return False, "The engine didn't unpack properly. Try again."
        d = model_dir(key)
        for file, size, sha, label in ((m["file"], m["size"], m["sha256"], m["name"]),
                                       (m["mmproj"], m["mmproj_size"], m["mmproj_sha256"], "its eyes")):
            f = d / file
            if f.exists() and f.stat().st_size == size:
                continue
            fetch(HF.format(repo=m["repo"], revision=m["revision"], file=file), f, progress, label, size, sha)
        if not model_ready(key):
            return False, "The model didn't download completely. Try again."
    except Exception as e:
        log("Brain install failed:\n" + traceback.format_exc())
        return False, f"Install failed: {e}"
    return True, "Installed."


def remove_model(key):
    shutil.rmtree(model_dir(key), ignore_errors=True)


# --------------------------------------------------------------------------- #
# Running it
# --------------------------------------------------------------------------- #
def _free_port():
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


def _kill_with_us(proc):
    """Windows: tie the server to Mirage, so it closes even if Mirage crashes."""
    if not WIN:
        return None
    try:
        import ctypes
        from ctypes import wintypes
        k = ctypes.windll.kernel32
        job = k.CreateJobObjectW(None, None)

        class LIMITS(ctypes.Structure):
            _fields_ = [("PerProcessUserTimeLimit", ctypes.c_int64), ("PerJobUserTimeLimit", ctypes.c_int64),
                        ("LimitFlags", wintypes.DWORD), ("MinimumWorkingSetSize", ctypes.c_size_t),
                        ("MaximumWorkingSetSize", ctypes.c_size_t), ("ActiveProcessLimit", wintypes.DWORD),
                        ("Affinity", ctypes.c_size_t), ("PriorityClass", wintypes.DWORD),
                        ("SchedulingClass", wintypes.DWORD)]

        class IO(ctypes.Structure):
            _fields_ = [(n, ctypes.c_uint64) for n in ("r", "w", "o", "rb", "wb", "ob")]

        class EXT(ctypes.Structure):
            _fields_ = [("Basic", LIMITS), ("Io", IO), ("ProcessMemoryLimit", ctypes.c_size_t),
                        ("JobMemoryLimit", ctypes.c_size_t), ("PeakProcessMemoryUsed", ctypes.c_size_t),
                        ("PeakJobMemoryUsed", ctypes.c_size_t)]

        info = EXT()
        info.Basic.LimitFlags = 0x2000  # kill everything in the job when Mirage's handle closes
        k.SetInformationJobObject(job, 9, ctypes.byref(info), ctypes.sizeof(info))
        h = k.OpenProcess(0x1F0FFF, False, proc.pid)
        k.AssignProcessToJobObject(job, h)
        k.CloseHandle(h)
        return job
    except Exception:
        return None


class LocalLLM:
    def __init__(self, log=print, on_change=lambda: None):
        self.log = log
        self.on_change = on_change
        self.proc = None
        self.port = None
        self.key = None
        self.state = "off"   # off | installing | starting | ready | error
        self.detail = ""
        self.lock = threading.Lock()
        self._job = None
        self._log_file = None

    def _set(self, state, detail=""):
        self.state, self.detail = state, detail
        try:
            self.on_change()
        except Exception:
            pass

    def running(self):
        return self.proc is not None and self.proc.poll() is None

    def stop(self):
        with self.lock:
            p, self.proc = self.proc, None
            if p and p.poll() is None:
                try:
                    p.terminate()
                    p.wait(5)
                except Exception:
                    try:
                        p.kill()
                    except Exception:
                        pass
            if self.state in ("ready", "starting"):
                self._set("off", "")

    def start(self, key, idle_minutes=5, timeout=180):
        """Start the server for a model (or keep the one that's running). Returns (ok, message)."""
        with self.lock:
            if self.running() and self.key == key:
                return True, "Running"
            if self.running():
                self.proc.terminate()
                try:
                    self.proc.wait(5)
                except Exception:
                    self.proc.kill()
            if not installed(key):
                return False, "Mirage's brain isn't installed yet (Settings > Brain)."
            m = MODELS[key]
            d = model_dir(key)
            self.port = _free_port()
            self.token = os.urandom(16).hex()  # only Mirage may talk to it, not web pages in a browser
            args = [str(SERVER), "-m", str(d / m["file"]), "--mmproj", str(d / m["mmproj"]),
                    "--no-mmproj-offload",          # the eyes run on the processor, keeping graphics memory free
                    "--host", "127.0.0.1", "--port", str(self.port), "-c", "16384", "-np", "1",
                    "--jinja", "--no-webui", "--reasoning-format", "deepseek", "--api-key", self.token,
                    "--sleep-idle-seconds", str(max(60, int(idle_minutes * 60)))]
            HOME.mkdir(parents=True, exist_ok=True)
            self._log_file = open(HOME / "server.log", "w", encoding="utf-8", errors="replace")
            self._set("starting", f"Starting {m['name']}…")
            self.log("Brain: " + " ".join(f'"{a}"' if " " in a else a for a in args).replace(self.token, "…"))
            self.proc = subprocess.Popen(args, cwd=str(ENGINE_DIR), stdout=self._log_file, stderr=subprocess.STDOUT,
                                         creationflags=NO_WINDOW)
            self._job = _kill_with_us(self.proc)
            self.key = key
        end = time.time() + timeout
        while time.time() < end:
            if self.proc is None or self.proc.poll() is not None:
                tail = self.server_log_tail()
                self._set("error", "The brain stopped while starting. " + tail[-200:])
                return False, "The brain didn't start: " + (tail[-300:] or "unknown error")
            try:
                with urllib.request.urlopen(f"http://127.0.0.1:{self.port}/health", timeout=2) as r:
                    if r.status == 200:
                        self._set("ready", f"{MODELS[key]['name']} is ready")
                        return True, "Ready"
            except Exception:
                pass
            time.sleep(0.5)
        self._set("error", "The brain took too long to start.")
        return False, "The brain took too long to start."

    def server_log_tail(self, n=1500):
        try:
            return (HOME / "server.log").read_text(encoding="utf-8", errors="replace")[-n:]
        except Exception:
            return ""

    def uses_gpu(self):
        """Whether the engine runs on the graphics card: an NVIDIA (CUDA) or Vulkan build with a card to use."""
        names = [p.name.lower() for p in ENGINE_DIR.glob("ggml-*")] if ENGINE_DIR.exists() else []
        if any("cuda" in n for n in names):
            return _driver_cuda() is not None
        if any("vulkan" in n for n in names):
            return True
        t = self.server_log_tail(20000)
        return "CUDA" in t or "Vulkan" in t or "offloaded" in t and "layers to GPU" in t

    def chat(self, messages, tools=None, think=False, max_tokens=700, timeout=180, json_schema=None):
        """One OpenAI-style chat request. Returns the assistant message dict.
        json_schema: make the answer JSON of that shape (llama.cpp enforces it with a grammar)."""
        m = MODELS[self.key]
        body = {"messages": messages, "max_tokens": max_tokens if not think else max_tokens * 4, "stream": False}
        body.update(m["sampling"])
        if json_schema:
            body["response_format"] = {"type": "json_schema", "json_schema": {"name": "answer", "schema": json_schema}}
            body["temperature"] = 0.2
        if m["think"] == "kwargs":
            body["chat_template_kwargs"] = {"enable_thinking": bool(think)}
        if tools:
            body["tools"] = tools
            body["tool_choice"] = "auto"
        data = json.dumps(body).encode("utf-8")
        req = urllib.request.Request(f"http://127.0.0.1:{self.port}/v1/chat/completions", data=data,
                                     headers={"Content-Type": "application/json", "Authorization": f"Bearer {self.token}"})
        try:
            with urllib.request.urlopen(req, timeout=timeout) as r:
                out = json.loads(r.read().decode("utf-8"))
        except urllib.error.HTTPError as e:
            raise RuntimeError(f"{e.code}: {e.read().decode('utf-8', 'replace')[:300]}")
        return out["choices"][0]["message"]
