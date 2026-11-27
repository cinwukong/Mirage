"""
The Diagnostics page: facts about this PC, and the report you copy when asking for help.

report() keeps what helps find a problem (errors, tracebacks, which microphone, what failed to load) and leaves out
what's private: what you said, Mirage's replies, what it remembered or typed, your name in folder paths, and keys.
system_info() only reads (Windows' registry and system calls); it never changes anything.
"""

import os
import re
import shutil
import sys
from pathlib import Path

LOG_LINES = 300
_STAMP = re.compile(r"^(\[\d\d:\d\d:\d\d\] )(.*)$")
# log lines whose whole text after the label is private
_PRIVATE = re.compile(r"^(YOU:|MIRAGE:|Heard:|Speaking up:|Reminder due:|Memory:|Conversation ended:|Talked over by:|"
                      r"Learning from the conversation failed:|Interview:)\s*.*$")
_TOOL = re.compile(r"^(Brain tool: \w+|Claude Code: refused \w+)\b.*$")
_QUOTED = re.compile(r"'(?:[^'\\]|\\.)*'|\"(?:[^\"\\]|\\.)*\"")
_KEYS = re.compile(r"\b(?:sk-ant-[\w-]+|github_pat_\w+|gh[pousr]_\w+)|(?<=Bearer )\S+|(?<=--api-key )\S+")
_USER_DIR = re.compile(r"(?i)([a-z]:\\Users\\)[^\\/\"'\n]+")


def _looks_like_path(s: str) -> bool:
    return bool(re.match(r"^[a-zA-Z]:\\|^\\\\|^~\\", s)) or ("\\" in s and s.lower().endswith((".py", ".dll", ".exe", ".onnx", ".gguf")))


def _redact_numbers(text: str) -> str:
    try:
        from skills import redact  # card, account and ID numbers
        return redact(text)
    except Exception:  # if that can't run, hide every long number rather than let one through
        return re.sub(r"\d(?:[ -]?\d){7,}", "[number hidden]", text)


def clean_line(line: str, home: str) -> str:
    """One log line with the private parts taken out."""
    if home:
        line = re.sub(re.escape(home), "~", line, flags=re.I)
    line = _USER_DIR.sub(r"\1<you>", line)
    m = _STAMP.match(line)
    stamp, body = (m.group(1), m.group(2)) if m else ("", line)
    p = _PRIVATE.match(body)
    if p:
        body = f"{p.group(1)} (left out)"
    else:
        t = _TOOL.match(body)
        if t:
            body = f"{t.group(1)} (details left out)"
        else:  # quoted text is what was heard, said, typed or a window's title; file paths stay (errors need them)
            body = _QUOTED.sub(lambda q: q.group(0) if _looks_like_path(q.group(0)[1:-1]) else "'…'", body)
    return stamp + _redact_numbers(_KEYS.sub("[key hidden]", body))


def clean_log(lines, home: str) -> list:
    """Log lines cleaned. A log entry can run over several lines (a reply with line breaks, a traceback): the
    follow-on lines of a private entry are left out with it; those of an error stay, cleaned."""
    out, private = [], True  # lines before the first time-stamped one may be the end of something private
    for line in lines:
        m = _STAMP.match(line)
        if m:
            private = bool(_PRIVATE.match(m.group(2)) or _TOOL.match(m.group(2)))
            out.append(clean_line(line, home))
        elif not private:
            out.append(clean_line(line, home))
    return out


def report(info: dict, log_text: str, home: str = None) -> str:
    """The text to paste when asking for help: the facts first, then the end of the log, cleaned."""
    home = str(Path.home()) if home is None else home
    head = ["Mirage diagnostic report (what you said, Mirage's replies and your name are left out)", ""]
    head += [f"{k}: {clean_line(str(v), home)}" for k, v in info.items()]
    lines = clean_log((log_text or "").splitlines()[-LOG_LINES:], home)
    return "\n".join(head + ["", f"Log (last {len(lines)} lines):"] + lines) + "\n"


# --------------------------------------------------------------------------- #
# This PC (read only)
# --------------------------------------------------------------------------- #
def _reg(path, name, hive=None):
    try:
        import winreg
        with winreg.OpenKey(hive or winreg.HKEY_LOCAL_MACHINE, path) as k:
            return winreg.QueryValueEx(k, name)[0]
    except OSError:
        return None


def windows_version() -> str:
    try:
        build = sys.getwindowsversion().build
    except AttributeError:
        return sys.platform
    cv = r"SOFTWARE\Microsoft\Windows NT\CurrentVersion"
    edition = (_reg(cv, "EditionID") or "").replace("Core", "Home")
    name = "Windows 11" if build >= 22000 else "Windows 10"  # ProductName still says 10 on Windows 11
    shown = _reg(cv, "DisplayVersion") or ""
    return " ".join(x for x in (name, edition, shown, f"(build {build})") if x)


def processor() -> str:
    name = _reg(r"HARDWARE\DESCRIPTION\System\CentralProcessor\0", "ProcessorNameString") or "unknown"
    name = re.sub(r"\s+", " ", name).strip()
    return f"{name}, {os.cpu_count() or '?'} threads"


def memory():
    """(total GB, free GB) of RAM, or None."""
    try:
        import ctypes

        class MS(ctypes.Structure):
            _fields_ = [("dwLength", ctypes.c_ulong), ("dwMemoryLoad", ctypes.c_ulong),
                        ("ullTotalPhys", ctypes.c_ulonglong), ("ullAvailPhys", ctypes.c_ulonglong),
                        ("ullTotalPageFile", ctypes.c_ulonglong), ("ullAvailPageFile", ctypes.c_ulonglong),
                        ("ullTotalVirtual", ctypes.c_ulonglong), ("ullAvailVirtual", ctypes.c_ulonglong),
                        ("ullAvailExtendedVirtual", ctypes.c_ulonglong)]
        ms = MS()
        ms.dwLength = ctypes.sizeof(MS)
        if ctypes.windll.kernel32.GlobalMemoryStatusEx(ctypes.byref(ms)):
            return ms.ullTotalPhys / 2 ** 30, ms.ullAvailPhys / 2 ** 30
    except Exception:
        pass
    return None


def _nvidia_memory():
    """{card name: (total GB, used GB)} from the NVIDIA driver, if there is one."""
    out = {}
    try:
        import ctypes
        lib = ctypes.WinDLL(os.path.join(os.environ.get("SystemRoot", r"C:\Windows"), "System32", "nvml.dll"))

        class MEM(ctypes.Structure):
            _fields_ = [("total", ctypes.c_ulonglong), ("free", ctypes.c_ulonglong), ("used", ctypes.c_ulonglong)]
        if lib.nvmlInit_v2() != 0:
            return out
        try:
            n = ctypes.c_uint(0)
            lib.nvmlDeviceGetCount_v2(ctypes.byref(n))
            for i in range(n.value):
                h = ctypes.c_void_p()
                if lib.nvmlDeviceGetHandleByIndex_v2(i, ctypes.byref(h)) != 0:
                    continue
                name = ctypes.create_string_buffer(96)
                lib.nvmlDeviceGetName(h, name, 96)
                mem = MEM()
                if lib.nvmlDeviceGetMemoryInfo(h, ctypes.byref(mem)) == 0:
                    out[name.value.decode("utf-8", "replace")] = (mem.total / 2 ** 30, mem.used / 2 ** 30)
        finally:
            lib.nvmlShutdown()
    except Exception:
        pass
    return out


def graphics() -> list:
    """["NVIDIA GeForce RTX 4070, 12.0 GB (3.1 GB in use)", ...] for each graphics card Windows knows."""
    cards = []
    try:
        import winreg
        base = r"SYSTEM\CurrentControlSet\Control\Class\{4d36e968-e325-11ce-bfc1-08002be10318}"
        with winreg.OpenKey(winreg.HKEY_LOCAL_MACHINE, base) as k:
            for i in range(winreg.QueryInfoKey(k)[0]):
                sub = winreg.EnumKey(k, i)
                if not sub.isdigit():
                    continue
                name = _reg(base + "\\" + sub, "DriverDesc")
                if not name or re.search(r"basic display|remote|virtual|indirect", name, re.I):
                    continue
                size = _reg(base + "\\" + sub, "HardwareInformation.qwMemorySize") or \
                    _reg(base + "\\" + sub, "HardwareInformation.MemorySize")
                if isinstance(size, bytes):
                    size = int.from_bytes(size[:8], "little")
                cards.append((name, (size or 0) / 2 ** 30))
    except Exception:
        pass
    nv = _nvidia_memory()
    out = []
    for name, gb in dict(cards).items():
        total, used = next(((t, u) for n, (t, u) in nv.items()
                            if n.lower() in name.lower() or name.lower() in n.lower()), (None, None))
        gb = total or gb
        text = name + (f", {gb:.1f} GB" if gb else "")
        if used is not None:
            text += f" ({used:.1f} GB in use)"
        out.append(text)
    return out or ["unknown"]


def mirage_memory():
    """How much memory Mirage itself uses now, in GB, or None."""
    try:
        import ctypes
        from ctypes import wintypes

        class PMC(ctypes.Structure):
            _fields_ = [("cb", wintypes.DWORD), ("PageFaultCount", wintypes.DWORD)] + \
                       [(n, ctypes.c_size_t) for n in ("PeakWorkingSetSize", "WorkingSetSize", "QuotaPeakPagedPoolUsage",
                                                        "QuotaPagedPoolUsage", "QuotaPeakNonPagedPoolUsage",
                                                        "QuotaNonPagedPoolUsage", "PagefileUsage", "PeakPagefileUsage")]
        pmc = PMC()
        pmc.cb = ctypes.sizeof(PMC)
        k32 = ctypes.windll.kernel32
        k32.GetCurrentProcess.restype = wintypes.HANDLE
        psapi = ctypes.windll.psapi
        psapi.GetProcessMemoryInfo.argtypes = [wintypes.HANDLE, ctypes.POINTER(PMC), wintypes.DWORD]
        if psapi.GetProcessMemoryInfo(k32.GetCurrentProcess(), ctypes.byref(pmc), pmc.cb):
            return pmc.WorkingSetSize / 2 ** 30
    except Exception:
        pass
    return None


def system_info(data_dir) -> dict:
    """This PC, as {label: text}, for the Diagnostics page and the report."""
    info = {"Windows": windows_version(), "Processor": processor()}
    mem = memory()
    if mem:
        info["Memory"] = f"{mem[0]:.1f} GB ({mem[1]:.1f} GB free)"
    for i, card in enumerate(graphics()):
        info["Graphics" if i == 0 else f"Graphics {i + 1}"] = card
    try:
        free = shutil.disk_usage(str(data_dir)).free / 2 ** 30
        info["Free disk space"] = f"{free:.0f} GB on {Path(str(data_dir)).drive or '/'}"
    except OSError:
        pass
    own = mirage_memory()
    if own is not None:
        info["Mirage uses"] = f"{own * 1024:.0f} MB of memory"
    info["Python"] = sys.version.split()[0]
    return info
