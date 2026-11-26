"""
Where Mirage keeps things, and how it runs Python.

- APP_DIR: Mirage's code (in the installed app: <install folder>\\app).
- DATA: your settings, reminders, log, downloaded voice and brain: %LOCALAPPDATA%\\Mirage. Kept apart from the code,
  so updating or reinstalling Mirage never touches them.
- NOTES: where Mirage writes notes when you haven't picked an Obsidian vault: Documents\\Mirage.
- BUNDLED: running in the installed app, with its own private Python (Mirage.exe), rather than a Python you
  installed yourself.
"""

import os
import sys
from pathlib import Path

APP_DIR = Path(__file__).resolve().parent
DATA = Path(os.environ["LOCALAPPDATA"]) / "Mirage" if os.environ.get("LOCALAPPDATA") else APP_DIR
RUNTIME = Path(sys.prefix)
BUNDLED = (RUNTIME / "mirage-runtime.txt").exists()
NO_WINDOW = 0x08000000 if sys.platform.startswith("win") else 0  # CREATE_NO_WINDOW


def _sibling(name):
    p = Path(sys.executable).with_name(name)
    return p if p.exists() else None


def python_console() -> Path:
    """python.exe, for running pip and other tools (never Mirage.exe or pythonw.exe)."""
    if BUNDLED and (RUNTIME / "python.exe").exists():
        return RUNTIME / "python.exe"
    exe = Path(sys.executable)
    if exe.name.lower() in ("pythonw.exe", "mirage.exe"):
        return _sibling("python.exe") or exe
    return exe


def app_exe() -> Path:
    """What starts Mirage without a console window: Mirage.exe in the installed app, otherwise pythonw.exe."""
    if BUNDLED and (RUNTIME / "Mirage.exe").exists():
        return RUNTIME / "Mirage.exe"
    exe = Path(sys.executable)
    if exe.name.lower() == "python.exe":
        return _sibling("pythonw.exe") or exe
    return exe


def launch_args(*extra) -> list:
    """The command that starts Mirage. Mirage.exe knows where its code is; pythonw needs the script."""
    if BUNDLED and (RUNTIME / "Mirage.exe").exists():
        return [str(RUNTIME / "Mirage.exe"), *extra]
    return [str(app_exe()), str(APP_DIR / "mirage_app.py"), *extra]


def pip(*args) -> list:
    """A pip command for Mirage's own Python. In the installed app it ignores anything from a Python you
    installed yourself (-I), so the two never mix."""
    return [str(python_console()), *(["-I"] if BUNDLED else []), "-m", "pip", *args]


def documents() -> Path:
    """Your Documents folder, wherever Windows (or OneDrive) put it."""
    if sys.platform.startswith("win"):
        try:
            import ctypes
            from ctypes import wintypes
            guid = (ctypes.c_ubyte * 16)(*bytes.fromhex("d0 9a d3 fd 8f 23 af 46 ad b4 6c 85 48 03 69 c7".replace(" ", "")))
            p = ctypes.c_wchar_p()
            if ctypes.windll.shell32.SHGetKnownFolderPath(ctypes.byref(guid), 0, None, ctypes.byref(p)) == 0:
                path = Path(p.value)
                ctypes.windll.ole32.CoTaskMemFree(p)
                return path
        except Exception:
            pass
    return Path.home() / "Documents"


NOTES = documents() / "Mirage"
