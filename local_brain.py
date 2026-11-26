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
HF = "https://huggingface.co/{repo}/resolve/main/{file}"
LLAMA_REPO = "ggml-org/llama.cpp"
FALLBACK_TAG = "b12755"  # a build known to have Windows downloads, used if GitHub's list can't be read

MODELS = {
    "qwen3.5-9b": {
        "name": "Qwen3.5 9B", "blurb": "Smarter", "repo": "unsloth/Qwen3.5-9B-GGUF",
        "file": "Qwen3.5-9B-Q4_K_M.gguf", "size": 5680522464,
        "mmproj": "mmproj-F16.gguf", "mmproj_size": 918166080,
        "sampling": {"temperature": 0.7, "top_p": 0.8, "top_k": 20},
        "think": "kwargs",   # thinking is switched with chat_template_kwargs.enable_thinking
    },
    "gemma4-e4b": {
        "name": "Gemma 4 E4B", "blurb": "Lighter and faster", "repo": "unsloth/gemma-4-E4B-it-GGUF",
        "file": "gemma-4-E4B-it-Q4_K_M.gguf", "size": 4977171584,
        "mmproj": "mmproj-F16.gguf", "mmproj_size": 990372672,
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
def _get_json(url):
    req = urllib.request.Request(url, headers={"User-Agent": "Mirage", "Accept": "application/vnd.github+json"})
    with urllib.request.urlopen(req, timeout=30) as r:
        return json.loads(r.read().decode("utf-8"))


def _engine_downloads(log):
    """[(file name, url)] for the newest llama.cpp build that fits this PC: the NVIDIA build (plus its CUDA
    runtime) when there's an NVIDIA card, otherwise Vulkan (any graphics card) or the processor build."""
    cuda = _driver_cuda()
    try:
        releases = _get_json(f"https://api.github.com/repos/{LLAMA_REPO}/releases?per_page=12")
    except Exception as e:
        log(f"Brain install: couldn't list llama.cpp builds ({e}); using {FALLBACK_TAG}")
        releases = []
    for rel in releases:
        assets = {a["name"]: a["browser_download_url"] for a in rel.get("assets", [])}
        if cuda:
            builds = []
            for n in assets:
                m = re.fullmatch(r"llama-b\d+-bin-win-cuda-(\d+)\.(\d+)-x64\.zip", n)
                if m:
                    ver = float(f"{m.group(1)}.{m.group(2)}")
                    rt = f"cudart-llama-bin-win-cuda-{m.group(1)}.{m.group(2)}-x64.zip"
                    if rt in assets and ver <= cuda + 1e-6:
                        builds.append((ver, n, rt))
            if builds:
                ver, n, rt = max(builds)
                return [(n, assets[n]), (rt, assets[rt])]
        for pat in (r"llama-b\d+-bin-win-vulkan-x64\.zip", r"llama-b\d+-bin-win-cpu-x64\.zip"):
            hit = next((n for n in assets if re.fullmatch(pat, n)), None)
            if hit and not cuda:
                return [(hit, assets[hit])]
    base = f"https://github.com/{LLAMA_REPO}/releases/download/{FALLBACK_TAG}/"
    if cuda:
        names = [f"llama-{FALLBACK_TAG}-bin-win-cuda-12.4-x64.zip", "cudart-llama-bin-win-cuda-12.4-x64.zip"]
    else:
        names = [f"llama-{FALLBACK_TAG}-bin-win-cpu-x64.zip"]
    return [(n, base + n) for n in names]


def _download(url, dest, progress, label, size=None):
    """Download with resume: a broken download carries on where it stopped next time."""
    dest.parent.mkdir(parents=True, exist_ok=True)
    part = dest.with_name(dest.name + ".part")
    have = part.stat().st_size if part.exists() else 0
    headers = {"User-Agent": "Mirage"}
    if have:
        headers["Range"] = f"bytes={have}-"
    req = urllib.request.Request(url, headers=headers)
    with urllib.request.urlopen(req, timeout=60) as r:
        if have and r.status != 206:  # the server started over
            have = 0
        total = size or (int(r.headers.get("Content-Length") or 0) + have)
        done, last = have, 0.0
        with open(part, "ab" if have else "wb") as f:
            while True:
                block = r.read(1 << 20)
                if not block:
                    break
                f.write(block)
                done += len(block)
                if time.time() - last > 0.5:
                    last = time.time()
                    progress(f"Downloading {label}: {done / 1e9:.1f} of {total / 1e9:.1f} GB" if total > 2e9 else
                             f"Downloading {label}: {done / 1e6:.0f} of {total / 1e6:.0f} MB")
    if size and part.stat().st_size != size:
        raise IOError(f"{label} downloaded incompletely ({part.stat().st_size} of {size} bytes); try again")
    os.replace(part, dest)


def install(key, progress=lambda m: None, log=lambda m: None):
    """Download the engine (once) and a model. Returns (ok, message)."""
    m = MODELS[key]
    need = download_mb(key) * 1e6 * 1.15
    free = shutil.disk_usage(HOME.parent if HOME.parent.exists() else Path.home()).free
    if free < need + 1e9:
        return False, f"Not enough free disk space: this needs about {need / 1e9:.0f} GB and there's {free / 1e9:.1f} GB free."
    try:
        if not engine_ready():
            progress("Finding the right engine for your PC…")
            files = _engine_downloads(log)
            log(f"Brain install: engine files {[n for n, _ in files]}")
            tmp = HOME / "download"
            for name, url in files:
                z = tmp / name
                _download(url, z, progress, "the brain's engine")
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
        for file, size, label in ((m["file"], m["size"], m["name"]), (m["mmproj"], m["mmproj_size"], "its eyes")):
            f = d / file
            if f.exists() and f.stat().st_size == size:
                continue
            _download(HF.format(repo=m["repo"], file=file), f, progress, label, size)
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
