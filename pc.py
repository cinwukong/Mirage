"""
Mirage's hands on the PC (Windows).

- Windows: find an open window by what you call it, switch to it, snap it to half the screen, move it to the
  other monitor, minimise, maximise or close it.
- For the brain: list the controls in the active window (buttons, links, text boxes… through Windows UI
  Automation, the same thing screen readers use), a screenshot with those controls numbered, and clicking,
  typing, pressing keys and scrolling.

Safety, enforced here rather than left to the brain:
- Esc stops it at once, and so does moving the mouse yourself.
- It never types into a password box.
- Clicking something like Send, Delete or Buy, or pressing Enter in a chat box, asks you first.
"""

import base64
import ctypes
import io
import os
import re
import struct
import sys
import threading
import time
from difflib import SequenceMatcher

WINDOWS = sys.platform.startswith("win")


class Stopped(Exception):
    """You pressed Esc or took the mouse back."""


# --------------------------------------------------------------------------- #
# Win32
# --------------------------------------------------------------------------- #
if WINDOWS:
    from ctypes import wintypes

    user32 = ctypes.WinDLL("user32", use_last_error=True)
    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    dwmapi = ctypes.WinDLL("dwmapi")
    version = ctypes.WinDLL("version")

    HWND, BOOL, UINT, DWORD, LONG = wintypes.HWND, wintypes.BOOL, wintypes.UINT, wintypes.DWORD, wintypes.LONG
    ULONG_PTR = ctypes.c_size_t
    WNDENUMPROC = ctypes.WINFUNCTYPE(BOOL, HWND, wintypes.LPARAM)
    MONITORENUMPROC = ctypes.WINFUNCTYPE(BOOL, wintypes.HMONITOR, wintypes.HDC, ctypes.POINTER(wintypes.RECT),
                                         wintypes.LPARAM)

    def _sig(fn, res, *args):
        fn.restype, fn.argtypes = res, list(args)

    _sig(user32.EnumWindows, BOOL, WNDENUMPROC, wintypes.LPARAM)
    _sig(user32.IsWindowVisible, BOOL, HWND)
    _sig(user32.IsIconic, BOOL, HWND)
    _sig(user32.IsZoomed, BOOL, HWND)
    _sig(user32.GetWindowTextLengthW, ctypes.c_int, HWND)
    _sig(user32.GetWindowTextW, ctypes.c_int, HWND, wintypes.LPWSTR, ctypes.c_int)
    _sig(user32.GetClassNameW, ctypes.c_int, HWND, wintypes.LPWSTR, ctypes.c_int)
    _sig(user32.GetWindow, HWND, HWND, UINT)
    _sig(user32.GetWindowLongPtrW, ctypes.c_ssize_t, HWND, ctypes.c_int)
    _sig(user32.GetWindowThreadProcessId, DWORD, HWND, ctypes.POINTER(DWORD))
    _sig(user32.GetForegroundWindow, HWND)
    _sig(user32.SetForegroundWindow, BOOL, HWND)
    _sig(user32.BringWindowToTop, BOOL, HWND)
    _sig(user32.ShowWindow, BOOL, HWND, ctypes.c_int)
    _sig(user32.PostMessageW, BOOL, HWND, UINT, wintypes.WPARAM, wintypes.LPARAM)
    _sig(user32.GetWindowRect, BOOL, HWND, ctypes.POINTER(wintypes.RECT))
    _sig(user32.SetWindowPos, BOOL, HWND, HWND, ctypes.c_int, ctypes.c_int, ctypes.c_int, ctypes.c_int, UINT)
    _sig(user32.MonitorFromWindow, wintypes.HMONITOR, HWND, DWORD)
    _sig(user32.EnumDisplayMonitors, BOOL, wintypes.HDC, ctypes.c_void_p, MONITORENUMPROC, wintypes.LPARAM)
    _sig(user32.AttachThreadInput, BOOL, DWORD, DWORD, BOOL)
    _sig(user32.GetCursorPos, BOOL, ctypes.POINTER(wintypes.POINT))
    _sig(user32.SetCursorPos, BOOL, ctypes.c_int, ctypes.c_int)
    _sig(user32.GetAsyncKeyState, ctypes.c_short, ctypes.c_int)
    _sig(user32.VkKeyScanW, ctypes.c_short, wintypes.WCHAR)
    try:
        _sig(user32.SetThreadDpiAwarenessContext, ctypes.c_void_p, ctypes.c_void_p)
    except AttributeError:  # Windows older than 10 (1607)
        pass
    _sig(kernel32.GetCurrentThreadId, DWORD)
    _sig(kernel32.OpenProcess, wintypes.HANDLE, DWORD, BOOL, DWORD)
    _sig(kernel32.CloseHandle, BOOL, wintypes.HANDLE)
    _sig(kernel32.QueryFullProcessImageNameW, BOOL, wintypes.HANDLE, DWORD, wintypes.LPWSTR, ctypes.POINTER(DWORD))
    _sig(dwmapi.DwmGetWindowAttribute, ctypes.c_long, HWND, DWORD, ctypes.c_void_p, DWORD)
    _sig(version.GetFileVersionInfoSizeW, DWORD, wintypes.LPCWSTR, ctypes.POINTER(DWORD))
    _sig(version.GetFileVersionInfoW, BOOL, wintypes.LPCWSTR, DWORD, DWORD, ctypes.c_void_p)
    _sig(version.VerQueryValueW, BOOL, ctypes.c_void_p, wintypes.LPCWSTR, ctypes.POINTER(ctypes.c_void_p),
         ctypes.POINTER(UINT))

    class MONITORINFO(ctypes.Structure):
        _fields_ = [("cbSize", DWORD), ("rcMonitor", wintypes.RECT), ("rcWork", wintypes.RECT), ("dwFlags", DWORD)]

    _sig(user32.GetMonitorInfoW, BOOL, wintypes.HMONITOR, ctypes.POINTER(MONITORINFO))

    class KEYBDINPUT(ctypes.Structure):
        _fields_ = [("wVk", wintypes.WORD), ("wScan", wintypes.WORD), ("dwFlags", DWORD), ("time", DWORD),
                    ("dwExtraInfo", ULONG_PTR)]

    class MOUSEINPUT(ctypes.Structure):
        _fields_ = [("dx", LONG), ("dy", LONG), ("mouseData", DWORD), ("dwFlags", DWORD), ("time", DWORD),
                    ("dwExtraInfo", ULONG_PTR)]

    class HARDWAREINPUT(ctypes.Structure):
        _fields_ = [("uMsg", DWORD), ("wParamL", wintypes.WORD), ("wParamH", wintypes.WORD)]

    class _U(ctypes.Union):
        _fields_ = [("ki", KEYBDINPUT), ("mi", MOUSEINPUT), ("hi", HARDWAREINPUT)]

    class INPUT(ctypes.Structure):
        _fields_ = [("type", DWORD), ("u", _U)]

    _sig(user32.SendInput, UINT, UINT, ctypes.POINTER(INPUT), ctypes.c_int)

SW_MAXIMIZE, SW_MINIMIZE, SW_RESTORE = 3, 6, 9
WM_CLOSE = 0x0010
GW_OWNER = 4
GWL_EXSTYLE = -20
WS_EX_TOOLWINDOW, WS_EX_NOACTIVATE = 0x80, 0x08000000
DWMWA_EXTENDED_FRAME_BOUNDS, DWMWA_CLOAKED = 9, 14
SWP_NOZORDER, SWP_NOACTIVATE = 0x0004, 0x0010
MONITOR_DEFAULTTONEAREST = 2
KEYEVENTF_EXTENDEDKEY, KEYEVENTF_KEYUP, KEYEVENTF_UNICODE = 0x1, 0x2, 0x4
MOUSEEVENTF_MOVE, MOUSEEVENTF_LEFTDOWN, MOUSEEVENTF_LEFTUP = 0x1, 0x2, 0x4
MOUSEEVENTF_RIGHTDOWN, MOUSEEVENTF_RIGHTUP, MOUSEEVENTF_WHEEL, MOUSEEVENTF_HWHEEL = 0x8, 0x10, 0x800, 0x1000
VK_ESCAPE = 0x1B
PER_MONITOR_AWARE_V2 = -4

SKIP_CLASSES = {"Progman", "WorkerW", "Shell_TrayWnd", "Shell_SecondaryTrayWnd", "Windows.UI.Core.CoreWindow"}
# What people call apps whose program file is named something else
ALIASES = {
    "chrome": ["chrome", "google chrome", "google", "browser"], "msedge": ["edge", "microsoft edge", "browser"],
    "firefox": ["firefox", "browser"], "brave": ["brave", "browser"], "opera": ["opera", "browser"],
    "explorer": ["file explorer", "explorer", "files", "folder"], "robloxstudiobeta": ["roblox studio", "studio"],
    "robloxplayerbeta": ["roblox"], "code": ["vs code", "visual studio code", "code"], "devenv": ["visual studio"],
    "windowsterminal": ["terminal"], "cmd": ["command prompt", "cmd"], "powershell": ["powershell"],
    "obs64": ["obs", "obs studio"], "notepad": ["notepad"], "spotify": ["spotify", "music"],
    "discord": ["discord"], "steamwebhelper": ["steam"], "steam": ["steam"], "whatsapp": ["whatsapp"],
    "applicationframehost": [], "systemsettings": ["settings"], "taskmgr": ["task manager"],
    "winword": ["word"], "excel": ["excel"], "powerpnt": ["powerpoint"], "olk": ["outlook", "mail"],
    "outlook": ["outlook", "mail"], "telegram": ["telegram"], "vlc": ["vlc"], "blender": ["blender"],
}
FILLER = re.compile(r"\b(?:the|my|a|an|window|windows|app|application|program)\b")
THIS = re.compile(r"^(?:this|it|that|here|current|active|this one|the one i'?m (?:on|in|using))?$")

MESSAGING = re.compile(r"discord|whatsapp|telegram|slack|teams|signal|messenger|skype|outlook|olk|thunderbird|mail|"
                       r"gmail|instagram|twitter|x\.com|reddit|facebook|snapchat|chat", re.I)
RISKY = re.compile(r"\b(?:send|post|publish|tweet|delete|remove|erase|discard|uninstall|buy|purchase|pay|"
                   r"payment|checkout|check out|place order|order now|subscribe|donate|transfer|confirm|"
                   r"sign out|log out|format|empty recycle bin|reset|unfriend|block|report|submit)\b", re.I)
NAVIGATION = ("link", "menu item", "list item", "tab", "tree item")
SECRET = re.compile(r"password|passcode|\bpin\b|security code|verification code|one.time code|2fa|cvv|cvc|"
                    r"card number|social security", re.I)


def _norm(text: str) -> str:
    return re.sub(r"\s+", " ", re.sub(r"[^a-z0-9åäöéü ]", " ", (text or "").lower())).strip()


class _DpiAware:
    """Real pixels for everything in the block, so positions from Windows, screenshots and clicks agree."""

    def __enter__(self):
        self.old = None
        if WINDOWS:
            try:
                self.old = user32.SetThreadDpiAwarenessContext(ctypes.c_void_p(PER_MONITOR_AWARE_V2))
            except Exception:
                pass
        return self

    def __exit__(self, *a):
        if WINDOWS and self.old:
            try:
                user32.SetThreadDpiAwarenessContext(ctypes.c_void_p(self.old))
            except Exception:
                pass


# --------------------------------------------------------------------------- #
# Windows (the on-screen kind)
# --------------------------------------------------------------------------- #
_describe_cache: dict = {}


def _file_description(path: str) -> str:
    """The app's own name for itself, like "Google Chrome" for chrome.exe."""
    if path in _describe_cache:
        return _describe_cache[path]
    desc = ""
    try:
        size = version.GetFileVersionInfoSizeW(path, None)
        if size:
            buf = ctypes.create_string_buffer(size)
            if version.GetFileVersionInfoW(path, 0, size, buf):
                p, n = ctypes.c_void_p(), UINT()
                if version.VerQueryValueW(buf, "\\VarFileInfo\\Translation", ctypes.byref(p), ctypes.byref(n)) and n.value >= 4:
                    lang, cp = struct.unpack("<HH", ctypes.string_at(p.value, 4))
                    key = f"\\StringFileInfo\\{lang:04x}{cp:04x}\\FileDescription"
                    if version.VerQueryValueW(buf, key, ctypes.byref(p), ctypes.byref(n)) and n.value:
                        desc = ctypes.wstring_at(p.value, n.value).rstrip("\0").strip()
    except Exception:
        desc = ""
    _describe_cache[path] = desc
    return desc


class Win:
    def __init__(self, hwnd):
        self.hwnd = hwnd
        n = user32.GetWindowTextLengthW(hwnd)
        buf = ctypes.create_unicode_buffer(n + 1)
        user32.GetWindowTextW(hwnd, buf, n + 1)
        self.title = buf.value
        pid = DWORD()
        user32.GetWindowThreadProcessId(hwnd, ctypes.byref(pid))
        self.pid = pid.value
        self.path = ""
        h = kernel32.OpenProcess(0x1000, False, self.pid)  # PROCESS_QUERY_LIMITED_INFORMATION
        if h:
            try:
                size = DWORD(1024)
                pbuf = ctypes.create_unicode_buffer(1024)
                if kernel32.QueryFullProcessImageNameW(h, 0, pbuf, ctypes.byref(size)):
                    self.path = pbuf.value
            finally:
                kernel32.CloseHandle(h)
        self.exe = os.path.splitext(os.path.basename(self.path))[0].lower()
        desc = _file_description(self.path) if self.path else ""
        if self.exe == "applicationframehost" or not desc or desc.lower() in ("", "electron"):
            desc = desc if desc and desc.lower() != "electron" else ""
        # the name to say out loud: "Google Chrome", "Discord"; modern Windows apps go by their title
        tail = re.split(r"\s+[-—–|]\s+", self.title)[-1].strip() if self.title else ""
        self.app = (self.title if self.exe == "applicationframehost" else desc or tail or self.exe).strip()
        self.names = {_norm(x) for x in [self.app, self.exe, desc, tail] + ALIASES.get(self.exe, []) if x}

    def __repr__(self):
        return f"<{self.app}: {self.title!r}>"


def _is_app_window(h) -> bool:
    if not user32.IsWindowVisible(h) or user32.GetWindowTextLengthW(h) == 0 or user32.GetWindow(h, GW_OWNER):
        return False
    ex = user32.GetWindowLongPtrW(h, GWL_EXSTYLE)
    if ex & WS_EX_TOOLWINDOW or (ex & WS_EX_NOACTIVATE and not user32.IsIconic(h)):
        return False
    buf = ctypes.create_unicode_buffer(256)
    user32.GetClassNameW(h, buf, 256)
    if buf.value in SKIP_CLASSES:
        return False
    cloaked = ctypes.c_int(0)  # hidden by Windows: other virtual desktops, suspended store apps
    dwmapi.DwmGetWindowAttribute(h, DWMWA_CLOAKED, ctypes.byref(cloaked), ctypes.sizeof(cloaked))
    return not cloaked.value


def app_windows(include_mine=False) -> list:
    """Open windows from the top down (the one you used last first)."""
    if not WINDOWS:
        return []
    found = []

    def cb(h, _):
        try:
            if _is_app_window(h):
                found.append(h)
        except Exception:
            pass
        return True
    user32.EnumWindows(WNDENUMPROC(cb), 0)
    out = []
    for h in found:
        try:
            w = Win(h)
        except Exception:
            continue
        if w.pid == os.getpid() and not include_mine:
            continue
        out.append(w)
    return out


def current():
    """The window you're using. When that's Mirage's own window (you typed to it), the one behind it."""
    if not WINDOWS:
        return None
    h = user32.GetForegroundWindow()
    if h:
        try:
            w = Win(h)
            if w.pid != os.getpid() and _is_app_window(h):
                return w
        except Exception:
            pass
    wins = app_windows()
    return wins[0] if wins else None


def find(name: str):
    """The open window that best matches what you called it ("discord", "the chrome window", "studio")."""
    q = re.sub(r"\s+", " ", FILLER.sub(" ", _norm(name))).strip()
    if THIS.match(q):
        return current()
    best, best_score = None, 0.0
    for w in app_windows():
        title = f" {_norm(w.title)} "
        if q in w.names:
            s = 3.0
        elif f" {q} " in title:
            s = 2.0
        elif any((len(q) >= 3 and q in n) or (len(n) >= 3 and f" {n} " in f" {q} ") for n in w.names if n):
            s = 1.5
        else:
            s = max([SequenceMatcher(None, q, n).ratio() for n in w.names if n] + [0.0])
            s = 1.0 if s >= 0.8 else 0.0
        if s > best_score:  # windows come top-down, so ties go to the one used last
            best, best_score = w, s
    return best


def _rect(h):
    r = wintypes.RECT()
    user32.GetWindowRect(h, ctypes.byref(r))
    return r


def _monitors():
    mons = []

    def cb(hm, hdc, lprc, data):
        mi = MONITORINFO()
        mi.cbSize = ctypes.sizeof(MONITORINFO)
        user32.GetMonitorInfoW(hm, ctypes.byref(mi))
        mons.append((hm, mi.rcMonitor, mi.rcWork))
        return True
    user32.EnumDisplayMonitors(None, None, MONITORENUMPROC(cb), 0)
    return sorted(mons, key=lambda m: (m[1].left, m[1].top))


def _monitor_of(h):
    hm = user32.MonitorFromWindow(h, MONITOR_DEFAULTTONEAREST)
    mi = MONITORINFO()
    mi.cbSize = ctypes.sizeof(MONITORINFO)
    user32.GetMonitorInfoW(hm, ctypes.byref(mi))
    return hm, mi.rcMonitor, mi.rcWork


def _place(h, x, y, w, hgt):
    """Move a window so its visible edges (not the invisible resize border) land on the given rectangle."""
    r = _rect(h)
    f = wintypes.RECT()
    if dwmapi.DwmGetWindowAttribute(h, DWMWA_EXTENDED_FRAME_BOUNDS, ctypes.byref(f), ctypes.sizeof(f)) == 0:
        dl, dt, dr, db = f.left - r.left, f.top - r.top, r.right - f.right, r.bottom - f.bottom
    else:
        dl = dt = dr = db = 0
    user32.SetWindowPos(h, None, x - dl, y - dt, w + dl + dr, hgt + dt + db, SWP_NOZORDER | SWP_NOACTIVATE)


def focus(w) -> bool:
    h = w.hwnd
    if user32.IsIconic(h):
        user32.ShowWindow(h, SW_RESTORE)
    fg = user32.GetForegroundWindow()
    me = kernel32.GetCurrentThreadId()
    other = user32.GetWindowThreadProcessId(fg, None) if fg else 0
    # Windows only lets the app you're using hand over focus; borrowing its input queue for a moment allows it
    attached = bool(other and other != me and user32.AttachThreadInput(other, me, True))
    try:
        user32.BringWindowToTop(h)
        user32.SetForegroundWindow(h)
    finally:
        if attached:
            user32.AttachThreadInput(other, me, False)
    if user32.GetForegroundWindow() != h:
        _send([_mouse(MOUSEEVENTF_MOVE)])  # counts as our input, which also allows it
        user32.SetForegroundWindow(h)
    return user32.GetForegroundWindow() == h


def window_action(action: str, name: str = "") -> str:
    """switch / minimize / maximize / restore / close / left / right / other screen / list / desktop."""
    if not WINDOWS:
        return "I can only manage windows on Windows."
    with _DpiAware():
        action = action.lower().strip()
        if action in ("list", "what's open"):
            return list_text()
        if action in ("desktop", "minimize all", "show desktop"):
            keys("win+d")
            return "Done."
        w = find(name)
        if not w:
            return f"I can't find a window called {name}." if name and not THIS.match(_norm(name)) else "There's no window to do that with."
        h = w.hwnd
        if action in ("switch", "focus", "show", "open"):
            ok = focus(w)
            return f"Here's {w.app}." if ok else f"Windows wouldn't let me bring {w.app} to the front."
        if action in ("minimize", "minimise", "hide"):
            user32.ShowWindow(h, SW_MINIMIZE)
            return "Done."
        if action in ("maximize", "maximise", "full screen", "fullscreen"):
            user32.ShowWindow(h, SW_MAXIMIZE)
            focus(w)
            return "Done."
        if action in ("restore", "unminimize"):
            user32.ShowWindow(h, SW_RESTORE)
            focus(w)
            return "Done."
        if action == "close":
            user32.PostMessageW(h, WM_CLOSE, 0, 0)
            return f"Closing {w.app}."
        if action in ("left", "right", "top", "bottom"):
            if user32.IsZoomed(h) or user32.IsIconic(h):
                user32.ShowWindow(h, SW_RESTORE)
            _, mon, work = _monitor_of(h)
            x, y, W, H = work.left, work.top, work.right - work.left, work.bottom - work.top
            box = {"left": (x, y, W // 2, H), "right": (x + W // 2, y, W - W // 2, H),
                   "top": (x, y, W, H // 2), "bottom": (x, y + H // 2, W, H - H // 2)}[action]
            _place(h, *box)
            focus(w)
            return "Done."
        if action in ("other screen", "other monitor", "next screen", "next monitor", "move"):
            mons = _monitors()
            if len(mons) < 2:
                return "You only have one screen."
            hm, mon, work = _monitor_of(h)
            i = next((k for k, m in enumerate(mons) if m[1].left == mon.left and m[1].top == mon.top), 0)
            _, mon2, work2 = mons[(i + 1) % len(mons)]
            was_max = user32.IsZoomed(h)
            if was_max or user32.IsIconic(h):
                user32.ShowWindow(h, SW_RESTORE)
            r = _rect(h)
            sx = (work2.right - work2.left) / max(1, work.right - work.left)
            sy = (work2.bottom - work2.top) / max(1, work.bottom - work.top)
            nx = work2.left + int((r.left - work.left) * sx)
            ny = work2.top + int((r.top - work.top) * sy)
            nw = min(work2.right - work2.left, int((r.right - r.left) * sx))
            nh = min(work2.bottom - work2.top, int((r.bottom - r.top) * sy))
            user32.SetWindowPos(h, None, nx, ny, nw, nh, SWP_NOZORDER | SWP_NOACTIVATE)
            if was_max:
                user32.ShowWindow(h, SW_MAXIMIZE)
            focus(w)
            return "Done."
        return f"I don't know how to {action} a window."


def side_by_side(a: str, b: str) -> str:
    wa, wb = find(a), find(b)
    missing = [n for n, w in ((a, wa), (b, wb)) if not w]
    if missing:
        return f"I can't find {' or '.join(missing)}."
    if wa.hwnd == wb.hwnd:
        return "That's the same window."
    with _DpiAware():
        _, _, work = _monitor_of(wa.hwnd)
        for w, side in ((wa, 0), (wb, 1)):
            if user32.IsZoomed(w.hwnd) or user32.IsIconic(w.hwnd):
                user32.ShowWindow(w.hwnd, SW_RESTORE)
            W = work.right - work.left
            _place(w.hwnd, work.left + side * (W // 2), work.top, W // 2 if side == 0 else W - W // 2,
                   work.bottom - work.top)
        focus(wb)
        focus(wa)
    return "Done."


def list_text() -> str:
    apps = []
    for w in app_windows():
        if w.app and w.app not in apps:
            apps.append(w.app)
    if not apps:
        return "Nothing's open."
    return "Open: " + (", ".join(apps[:-1]) + " and " + apps[-1] if len(apps) > 1 else apps[0]) + "."


# --------------------------------------------------------------------------- #
# Keyboard and mouse
# --------------------------------------------------------------------------- #
def _key(vk=0, scan=0, flags=0):
    i = INPUT()
    i.type = 1
    i.u.ki = KEYBDINPUT(vk, scan, flags, 0, 0)
    return i


def _mouse(flags, data=0):
    i = INPUT()
    i.type = 0
    i.u.mi = MOUSEINPUT(0, 0, data & 0xFFFFFFFF, flags, 0, 0)
    return i


def _send(items):
    arr = (INPUT * len(items))(*items)
    return user32.SendInput(len(items), arr, ctypes.sizeof(INPUT))


VK = {"ctrl": 0x11, "control": 0x11, "shift": 0x10, "alt": 0x12, "win": 0x5B, "windows": 0x5B, "cmd": 0x5B,
      "enter": 0x0D, "return": 0x0D, "esc": 0x1B, "escape": 0x1B, "tab": 0x09, "space": 0x20,
      "backspace": 0x08, "delete": 0x2E, "del": 0x2E, "insert": 0x2D, "home": 0x24, "end": 0x23,
      "pageup": 0x21, "page up": 0x21, "pagedown": 0x22, "page down": 0x22, "up": 0x26, "down": 0x28,
      "left": 0x25, "right": 0x27, "capslock": 0x14, "printscreen": 0x2C, "menu": 0x5D,
      "volumeup": 0xAF, "volumedown": 0xAE, "volumemute": 0xAD, "playpause": 0xB3, "nexttrack": 0xB0,
      "prevtrack": 0xB1, "plus": 0xBB, "minus": 0xBD, "comma": 0xBC, "period": 0xBE}
VK.update({f"f{n}": 0x6F + n for n in range(1, 25)})
EXTENDED = {0x2E, 0x2D, 0x24, 0x23, 0x21, 0x22, 0x26, 0x28, 0x25, 0x27, 0x5B, 0x5D, 0xAF, 0xAE, 0xAD, 0xB3, 0xB0, 0xB1}


def _vk(name: str):
    n = name.strip().lower()
    if n in VK:
        return VK[n]
    if len(n) == 1:
        code = user32.VkKeyScanW(n)
        if code != -1:
            return code & 0xFF
    return None


def parse_keys(combo: str) -> list:
    """"ctrl+shift+t" -> virtual key codes, or raise ValueError."""
    parts = [p for p in re.split(r"\s*\+\s*", combo.strip().lower()) if p]
    codes = [_vk(p) for p in parts]
    if not parts or None in codes:
        raise ValueError(f"I don't know the key {parts[codes.index(None)] if None in codes else combo!r}.")
    return codes


def keys(combo: str):
    codes = parse_keys(combo)
    down = [_key(c, 0, KEYEVENTF_EXTENDEDKEY if c in EXTENDED else 0) for c in codes]
    up = [_key(c, 0, (KEYEVENTF_EXTENDEDKEY if c in EXTENDED else 0) | KEYEVENTF_KEYUP) for c in reversed(codes)]
    _send(down)
    time.sleep(0.03)
    _send(up)


def type_unicode(text: str, stop=None, delay=0.008):
    """Type any text (å, ä, ö, emoji…) whatever the keyboard layout. stop() -> True stops part way."""
    for ch in text:
        if stop and stop():
            raise Stopped("stopped")
        if ch == "\n":
            _send([_key(0x0D), _key(0x0D, 0, KEYEVENTF_KEYUP)])
        elif ch == "\t":
            _send([_key(0x09), _key(0x09, 0, KEYEVENTF_KEYUP)])
        else:
            units = ch.encode("utf-16-le")
            for k in range(0, len(units), 2):
                u = struct.unpack("<H", units[k:k + 2])[0]
                _send([_key(0, u, KEYEVENTF_UNICODE), _key(0, u, KEYEVENTF_UNICODE | KEYEVENTF_KEYUP)])
        time.sleep(delay)


def cursor():
    p = wintypes.POINT()
    user32.GetCursorPos(ctypes.byref(p))
    return p.x, p.y


def click_at(x, y, button="left", double=False):
    user32.SetCursorPos(int(x), int(y))
    time.sleep(0.05)
    down, up = (MOUSEEVENTF_RIGHTDOWN, MOUSEEVENTF_RIGHTUP) if button == "right" else (MOUSEEVENTF_LEFTDOWN, MOUSEEVENTF_LEFTUP)
    for _ in range(2 if double else 1):
        _send([_mouse(down), _mouse(up)])
        time.sleep(0.06)


def wheel(direction: str, clicks: int = 5):
    d = direction.lower()
    flag = MOUSEEVENTF_HWHEEL if d in ("left", "right") else MOUSEEVENTF_WHEEL
    sign = 1 if d in ("up", "right") else -1
    for _ in range(max(1, min(30, int(clicks)))):
        _send([_mouse(flag, sign * 120)])
        time.sleep(0.02)


# --------------------------------------------------------------------------- #
# Seeing the controls (UI Automation)
# --------------------------------------------------------------------------- #
CONTROL_TYPES = {50000: "button", 50002: "checkbox", 50003: "dropdown", 50004: "text box", 50005: "link",
                 50007: "list item", 50011: "menu item", 50013: "option", 50019: "tab", 50024: "tree item",
                 50031: "split button", 50030: "document", 50020: "text", 50026: "group"}
CLICKABLE = [50000, 50002, 50003, 50004, 50005, 50007, 50011, 50013, 50019, 50024, 50031]
P_NAME, P_TYPE, P_RECT, P_ENABLED, P_OFFSCREEN, P_PASSWORD, P_VALUE = 30005, 30003, 30001, 30010, 30022, 30019, 30045
_tls = threading.local()


def _need_comtypes():
    """comtypes talks to Windows UI Automation. Normally the update installs it; if not, install it now."""
    try:
        import comtypes  # noqa: F401
        return
    except ImportError:
        pass
    import importlib
    import subprocess
    py = sys.executable
    if py.lower().endswith("pythonw.exe"):
        py = py[:-len("pythonw.exe")] + "python.exe"
    subprocess.run([py, "-m", "pip", "install", "--disable-pip-version-check", "comtypes"], capture_output=True,
                   creationflags=0x08000000)
    importlib.invalidate_caches()
    try:
        import site
        if site.getusersitepackages() not in sys.path:
            sys.path.append(site.getusersitepackages())
    except Exception:
        pass


def _uia():
    """The UI Automation client for this thread."""
    if getattr(_tls, "uia", None) is None:
        _need_comtypes()
        import comtypes
        import comtypes.client
        try:
            comtypes.CoInitializeEx(comtypes.COINIT_APARTMENTTHREADED)
        except OSError:
            pass
        comtypes.client.GetModule("UIAutomationCore.dll")
        from comtypes.gen import UIAutomationClient as UIA
        _tls.mod = UIA
        _tls.uia = comtypes.client.CreateObject(UIA.CUIAutomation, interface=UIA.IUIAutomation)
    return _tls.uia


class Control:
    __slots__ = ("n", "name", "kind", "box", "password", "value")

    def __init__(self, n, name, kind, box, password=False, value=""):
        self.n, self.name, self.kind, self.box, self.password, self.value = n, name, kind, box, password, value

    @property
    def center(self):
        l, t, r, b = self.box
        return (l + r) // 2, (t + b) // 2

    def label(self):
        name = self.name or (f"(has: {self.value[:40]})" if self.value else "(no name)")
        return f"[{self.n}] {self.kind} \"{name[:80]}\""


def controls(w, limit=120) -> list:
    """The things you can click or type into in a window, top to bottom."""
    uia = _uia()
    root = uia.ElementFromHandle(w.hwnd)
    cr = uia.CreateCacheRequest()
    for p in (P_NAME, P_TYPE, P_RECT, P_ENABLED, P_PASSWORD, P_VALUE):
        cr.AddProperty(p)
    cond = None
    for ct in CLICKABLE:
        c = uia.CreatePropertyCondition(P_TYPE, ct)
        cond = c if cond is None else uia.CreateOrCondition(cond, c)
    cond = uia.CreateAndCondition(cond, uia.CreatePropertyCondition(P_OFFSCREEN, False))
    win = _rect(w.hwnd)
    out, seen = [], set()
    for attempt in range(2):  # browsers switch their accessibility on when first asked, so ask twice
        found = root.FindAllBuildCache(4, cond, cr)  # TreeScope_Descendants
        if found.Length >= 8 or attempt:
            break
        time.sleep(0.4)
    items = []
    for i in range(found.Length):
        try:
            el = found.GetElement(i)
            r = el.CachedBoundingRectangle
            box = (r.left, r.top, r.right, r.bottom)
            if box[2] - box[0] < 4 or box[3] - box[1] < 4 or not el.CachedIsEnabled:
                continue
            if box[2] < win.left or box[0] > win.right or box[3] < win.top or box[1] > win.bottom:
                continue
            name = re.sub(r"\s+", " ", el.CachedName or "").strip()
            kind = CONTROL_TYPES.get(el.CachedControlType, "control")
            value = ""
            if kind in ("text box", "dropdown"):
                try:
                    value = str(el.GetCachedPropertyValue(P_VALUE) or "")
                except Exception:
                    value = ""
            if not name and kind not in ("text box", "dropdown"):
                continue
            key = (name, kind, box)
            if key in seen:
                continue
            seen.add(key)
            items.append((box, name, kind, bool(el.CachedIsPassword), value))
        except Exception:
            continue
    items.sort(key=lambda it: (it[0][1] // 24, it[0][0]))
    for box, name, kind, pw, value in items[:limit]:
        out.append(Control(len(out) + 1, name, kind, box, pw, value))
    return out


def focused_info():
    """(kind, name, is_password) of the control that has the keyboard."""
    try:
        el = _uia().GetFocusedElement()
        return CONTROL_TYPES.get(el.CurrentControlType, "control"), el.CurrentName or "", bool(el.CurrentIsPassword)
    except Exception:
        return "", "", False


def name_at(x, y) -> str:
    """The name of whatever is at a spot on the screen ("Send", "Delete"…)."""
    uia = _uia()
    mod = sys.modules.get("comtypes.gen.UIAutomationClient")
    for P in (getattr(mod, "tagPOINT", None), wintypes.POINT):
        if P is None:
            continue
        try:
            return uia.ElementFromPoint(P(int(x), int(y))).CurrentName or ""
        except Exception:
            continue
    return ""


def screenshot(rect, marks=(), max_side=1280):
    """(JPEG base64, image size, scale) of a screen area, with the numbered controls drawn on it."""
    from PIL import ImageDraw, ImageFont, ImageGrab
    l, t, r, b = rect
    img = ImageGrab.grab(bbox=(l, t, r, b), all_screens=True).convert("RGB")
    s = min(1.0, max_side / max(img.size))
    if s < 1:
        img = img.resize((int(img.width * s), int(img.height * s)))
    if marks:
        d = ImageDraw.Draw(img)
        try:
            font = ImageFont.load_default(size=13)
        except TypeError:
            font = ImageFont.load_default()
        for c in marks:
            x0, y0, x1, y1 = [(v - o) * s for v, o in zip(c.box, (l, t, l, t))]
            d.rectangle((x0, y0, x1, y1), outline=(255, 60, 200), width=1)
            tag = str(c.n)
            tw = 7 * len(tag) + 4
            d.rectangle((x0, y0, x0 + tw, y0 + 15), fill=(255, 60, 200))
            d.text((x0 + 2, y0 + 1), tag, fill=(255, 255, 255), font=font)
    buf = io.BytesIO()
    img.save(buf, format="JPEG", quality=80)
    return base64.b64encode(buf.getvalue()).decode(), img.size, s


# --------------------------------------------------------------------------- #
# Hands: what the brain uses, with the safety checks
# --------------------------------------------------------------------------- #
class Hands:
    def __init__(self, log=print, confirm=None, on_start=None, on_end=None):
        self.log = log
        self.confirm = confirm or (lambda question: False)   # ask the user; True means yes
        self.on_start, self.on_end = on_start or (lambda: None), on_end or (lambda: None)
        self.active = False
        self.stop_reason = ""
        self._stop = threading.Event()
        self._own_keys_until = 0.0
        self._last_pos = None
        self.seen = None         # the window the last list/look was of
        self.items = []          # its numbered controls
        self.shot = None         # (screen rect, image size, scale) of the last screenshot

    # ---- start, stop ----
    def begin(self):
        if self.active:
            return
        self.active = True
        self._stop.clear()
        self.stop_reason = ""
        self._last_pos = cursor() if WINDOWS else None
        threading.Thread(target=self._watch, daemon=True, name="mirage-esc").start()
        self.on_start()

    def end(self):
        if self.active:
            self.active = False
            self.on_end()

    def halt(self, reason="you asked me to stop"):
        if self.active:
            self.stop_reason = reason
            self._stop.set()

    def stopped(self):
        return self._stop.is_set()

    def _watch(self):
        """Esc stops everything."""
        if not WINDOWS:
            return
        while self.active and not self._stop.is_set():
            if user32.GetAsyncKeyState(VK_ESCAPE) & 0x8000 and time.time() > self._own_keys_until:
                self.halt("you pressed Esc")
                self.log("PC control stopped: Esc.")
                break
            time.sleep(0.03)

    def _check(self):
        if self._stop.is_set():
            raise Stopped(self.stop_reason)
        if WINDOWS and self._last_pos is not None:
            x, y = cursor()
            if abs(x - self._last_pos[0]) + abs(y - self._last_pos[1]) > 60:
                self.halt("you moved the mouse")
                raise Stopped(self.stop_reason)

    def _settle(self):
        time.sleep(0.15)
        self._last_pos = cursor()

    # ---- seeing ----
    def _target_window(self):
        w = current()
        if not w:
            raise RuntimeError("There's no window open.")
        return w

    def list_controls(self) -> str:
        with _DpiAware():
            w = self._target_window()
            self.seen = w
            try:
                self.items = controls(w)
            except Exception as e:
                self.log(f"Couldn't read the controls: {e}")
                self.items = []
            return self._describe(w)

    def _describe(self, w):
        head = f"Window: {w.app} - {w.title}"[:160]
        if not self.items:
            return head + "\nNo controls could be read here (a game or a custom app?). Use look_at_screen and click x,y."
        kind, name, pw = focused_info()
        foc = f"\nKeyboard focus: {kind} \"{name[:60]}\"" if kind else ""
        return head + foc + "\nControls (number, type, name):\n" + "\n".join(c.label() for c in self.items)

    def look(self, max_side=1280):
        """(text, JPEG base64): the active window's screen with its controls numbered."""
        with _DpiAware():
            w = self._target_window()
            self.seen = w
            try:
                self.items = controls(w)
            except Exception as e:
                self.log(f"Couldn't read the controls: {e}")
                self.items = []
            _, mon, _ = _monitor_of(w.hwnd)
            rect = (mon.left, mon.top, mon.right, mon.bottom)
            data, size, s = screenshot(rect, self.items, max_side)
            self.shot = (rect, size, s)
            text = self._describe(w) + (f"\nThe screenshot is {size[0]}x{size[1]}; numbered boxes are those controls. "
                                        "For anything without a number, click x,y on a 0-1000 scale across the screenshot.")
            return text, data

    # ---- doing ----
    def _point(self, target: str):
        """(x, y, what it is) for a control number or an "x,y" spot (0-1000 across the last screenshot)."""
        t = str(target).strip().strip("[]#")
        if re.fullmatch(r"\d+", t):
            n = int(t)
            c = next((c for c in self.items if c.n == n), None)
            if not c:
                raise ValueError(f"There's no control {n}. Use list_controls to see the current numbers.")
            return c.center[0], c.center[1], c
        m = re.fullmatch(r"\(?\s*(\d+(?:\.\d+)?)\s*[, ]\s*(\d+(?:\.\d+)?)\s*\)?", t)
        if not m:
            raise ValueError("target is a control number like 12, or x,y like 500,300.")
        if not self.shot:
            raise ValueError("Use look_at_screen first, so x,y means something.")
        (l, tp, r, b), _, _ = self.shot
        x = l + float(m.group(1)) / 1000 * (r - l)
        y = tp + float(m.group(2)) / 1000 * (b - tp)
        return int(x), int(y), None

    def click(self, target: str, how: str = "click") -> str:
        self.begin()
        self._check()
        with _DpiAware():
            x, y, c = self._point(target)
            name = c.name if c else name_at(x, y)
            if name and RISKY.search(name):
                if not self.confirm(f"Should I click {name[:60]}?"):
                    return f"The user said no, so I didn't click {name[:60]}."
                self._last_pos = cursor()
            self._check()
            click_at(x, y, "right" if "right" in how else "left", "double" in how)
            self._settle()
        what = f"{c.kind} \"{c.name[:50]}\"" if c else f"the spot at {target}" + (f" ({name[:40]})" if name else "")
        return f"Clicked {what}. Check the result before saying it's done."

    def type(self, text: str) -> str:
        self.begin()
        self._check()
        with _DpiAware():
            kind, name, pw = focused_info()
            if pw or SECRET.search(name or ""):
                return ("That's a password or code box. I never type those: ask the user to type it themselves.")
            if "\n" in text:
                w = current()
                if w and MESSAGING.search(f"{w.exe} {w.title}") and kind not in NAVIGATION:
                    if not self.confirm("Should I send that message?"):
                        text = text.replace("\n", " ")
                    self._last_pos = cursor()
            type_unicode(text, stop=self.stopped)
            self._settle()
        return f"Typed into {kind or 'the focused place'} \"{name[:40]}\"." if name else "Typed it."

    def press(self, combo: str) -> str:
        self.begin()
        self._check()
        with _DpiAware():
            codes = parse_keys(combo)
            c = combo.lower().replace(" ", "")
            if "enter" in c or "return" in c or c == "space":
                kind, name, _ = focused_info()
                w = current()
                chat = w and "enter" in c and MESSAGING.search(f"{w.exe} {w.title}") and kind not in NAVIGATION
                if chat or (name and RISKY.search(name) and kind in ("button", "split button", "link", "menu item")):
                    question = f"Should I press Enter to send it in {w.app}?" if chat else f"Should I press {name[:50]}?"
                    if not self.confirm(question):
                        return "The user said no, so I didn't."
                    self._last_pos = cursor()
            if c in ("shift+delete", "shift+del"):
                if not self.confirm("Should I delete that permanently?"):
                    return "The user said no."
                self._last_pos = cursor()
            if VK_ESCAPE in codes:
                self._own_keys_until = time.time() + 0.5
            self._check()
            keys(combo)
            self._settle()
        return f"Pressed {combo}."

    def scroll(self, direction: str, amount: int = 5, target: str = "") -> str:
        self.begin()
        self._check()
        with _DpiAware():
            if target:
                x, y, _ = self._point(target)
                user32.SetCursorPos(x, y)
            wheel(direction, amount)
            self._settle()
        return f"Scrolled {direction}."

    def window(self, action: str, name: str = "") -> str:
        self.begin()
        self._check()
        out = window_action(action, name)
        self._settle()
        return out
