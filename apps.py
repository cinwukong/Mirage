"""
Finding and starting apps, without the command shell.

A name Mirage hears or the brain asks for is only started if it is:
- one of your own apps (Shortcuts page, or the defaults in config.json), started exactly as you entered it,
- a shortcut in your Start menu ("discord" -> Discord.lnk),
- a program Windows has registered under App Paths ("chrome" -> chrome.exe),
- a Store app alias in WindowsApps (Spotify, WhatsApp...).
Anything else isn't started, and names with quotes, slashes or symbols never are. So text on a web page, in a note
or in a window title can't trick the brain into running a command this way.
"""

import os
import re
import sys
import time
from pathlib import Path

WIN = sys.platform.startswith("win")
# letters, digits, spaces and a few harmless marks: no quotes, slashes, colons, & | % ^ < > or anything a shell reads
PLAIN = re.compile(r"[^\W_][\w .'+-]{0,60}")
EXE_NAME = re.compile(r"[a-z0-9][a-z0-9._-]{0,40}")
NOT_APPS = re.compile(r"\b(?:uninstall|uninstaller|readme|read me|help|manual|documentation|release notes|license|"
                      r"licence|website|on the web|support|changelog)\b", re.I)
_menu = {"at": 0.0, "items": []}


def norm(name: str) -> str:
    return re.sub(r"\s+", " ", re.sub(r"[^\w ]", " ", (name or "").lower())).strip()


def _start_menu_items():
    """[(normalised name, shortcut path)] from your Start menu and the shared one (looked up at most every 2 min)."""
    if _menu["items"] and time.time() - _menu["at"] < 120:
        return _menu["items"]
    roots = [Path(os.environ.get("APPDATA", "")) / "Microsoft" / "Windows" / "Start Menu" / "Programs",
             Path(os.environ.get("PROGRAMDATA", r"C:\ProgramData")) / "Microsoft" / "Windows" / "Start Menu" / "Programs"]
    items = []
    for root in roots:
        if not root.is_dir():
            continue
        try:
            for p in root.rglob("*"):
                if p.suffix.lower() in (".lnk", ".url") and not NOT_APPS.search(p.stem):
                    items.append((norm(p.stem), p))
        except OSError:
            continue
    _menu.update(at=time.time(), items=items)
    return items


def start_menu(name: str):
    """The Start menu shortcut that best matches: same name, then a name that starts or ends with it
    ("chrome" -> "Google Chrome"), then one that contains it as a word. Shorter names win ties."""
    q = norm(name)
    if not q:
        return None
    best, best_rank = None, 0
    for n, p in _start_menu_items():
        if n == q:
            rank = 3
        elif len(q) < 3:
            continue
        elif n.startswith(q + " ") or n.endswith(" " + q):
            rank = 2
        elif f" {q} " in f" {n} ":
            rank = 1
        else:
            continue
        if rank > best_rank or (rank == best_rank and len(n) < len(norm(best.stem))):
            best, best_rank = p, rank
    return best


def app_path(name: str):
    """A program registered under App Paths (how Windows finds chrome.exe, winword.exe...)."""
    if not WIN or not EXE_NAME.fullmatch(name):
        return None
    import winreg
    exe = name if name.endswith(".exe") else name + ".exe"
    for hive in (winreg.HKEY_CURRENT_USER, winreg.HKEY_LOCAL_MACHINE):
        for view in (0, winreg.KEY_WOW64_32KEY):
            try:
                with winreg.OpenKey(hive, r"Software\Microsoft\Windows\CurrentVersion\App Paths" + "\\" + exe,
                                    0, winreg.KEY_READ | view) as k:
                    value, _ = winreg.QueryValueEx(k, "")
            except OSError:
                continue
            value = os.path.expandvars(str(value).strip().strip('"'))
            if value and Path(value).is_file():
                return value
    return None


def store_alias(name: str):
    """A Store app's alias in %LOCALAPPDATA%\\Microsoft\\WindowsApps (spotify.exe, whatsapp.exe...)."""
    if not EXE_NAME.fullmatch(name):
        return None
    p = Path(os.environ.get("LOCALAPPDATA", "")) / "Microsoft" / "WindowsApps" / (name + ".exe")
    return str(p) if p.exists() else None


def find(name: str, configured: dict):
    """What to start for a name, or None. configured: your own apps, {lowercase name: target}."""
    key = (name or "").lower().strip()
    if not key:
        return None
    if key in configured:
        return configured[key]  # yours: a program name, a path or a link like discord:
    if not PLAIN.fullmatch(key):
        return None
    return start_menu(key) or app_path(key) or store_alias(key.replace(" ", ""))


def start(target):
    """Start a program, file, folder, shortcut or link. Windows treats the whole text as one name: it's never read as
    a command line, so nothing in it can run as a command."""
    os.startfile(str(target))
