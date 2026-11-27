"""
Mirage launcher.

    Mirage.exe                       the installed app (it runs this file with its own Python)
    pythonw mirage_app.py            open Mirage
    pythonw mirage_app.py --tray     start hidden in the tray
    python  mirage_app.py --enable-startup
    python  mirage_app.py --selftest check that every part loads (writes selftest.txt)

If a part Mirage needs is missing (for example right after an update), a small window offers
to install it instead of crashing.
"""

import os
import subprocess
import sys
import threading
import traceback
from pathlib import Path

BASE = Path(__file__).resolve().parent
sys.path.insert(0, str(BASE))


def _log(msg):
    try:
        from mirage import log
        log(msg)
    except Exception:
        pass


def selftest() -> int:
    """Import every part of Mirage and check the packages it needs (used when building the installer)."""
    import importlib
    import paths
    out, failed = [], 0
    for name in ["paths", "mirage", "skills", "speech", "local_brain", "brains", "recall", "presence", "pc", "spotify",
                 "hologram", "ui_web", "apps", "download", "updater", "captions", "diagnostics", "webview", "sounddevice", "numpy", "sherpa_onnx", "PIL", "pystray", "vosk",
                 "pyttsx3", "anthropic", "tkinter"] + (["comtypes", "comtypes.client"] if sys.platform.startswith("win") else []):
        try:
            importlib.import_module(name)
            out.append(f"ok   {name}")
        except Exception as e:
            failed += 1
            out.append(f"FAIL {name}: {type(e).__name__}: {e}")
    out.append(f"python {sys.version.split()[0]} at {sys.executable}; bundled={paths.BUNDLED}")
    report = Path(os.environ.get("MIRAGE_SELFTEST_OUT") or (paths.DATA / "selftest.txt"))
    report.parent.mkdir(parents=True, exist_ok=True)
    report.write_text("\n".join(out) + "\n", encoding="utf-8")
    return 1 if failed else 0


def repair(problem: str):
    """Small window that installs Mirage's packages, then restarts Mirage."""
    import tkinter as tk
    root = tk.Tk()
    root.title("Mirage")
    root.configure(bg="#120a1c")
    root.geometry("520x260")
    root.resizable(False, False)
    try:
        root.iconbitmap(str(BASE / "assets" / "mirage.ico"))
    except Exception:
        pass
    font = ("Segoe UI", 11)
    tk.Label(root, text="Mirage needs to finish setting up", bg="#120a1c", fg="#ece3ff",
             font=("Segoe UI", 15)).pack(pady=(26, 6))
    msg = tk.Label(root, text="Some parts are missing, usually right after an update.\n"
                              "Install them now? This takes a minute or two.",
                   bg="#120a1c", fg="#9d8db5", font=font, justify="center")
    msg.pack(pady=(0, 16))
    status = tk.Label(root, text="", bg="#120a1c", fg="#f2d17e", font=("Segoe UI", 10), wraplength=470)
    btn = tk.Button(root, text="Install and start Mirage", bg="#d9a93f", fg="#1a0f05", activebackground="#f2d17e",
                    relief="flat", font=("Segoe UI", 11, "bold"), padx=18, pady=6)
    btn.pack()
    status.pack(pady=12)

    def work():
        flags = 0x08000000 if sys.platform.startswith("win") else 0
        import paths
        p = subprocess.Popen(paths.pip("install", "--disable-pip-version-check", "-r", str(BASE / "requirements.txt")),
                             stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True, creationflags=flags)
        last = ""
        for line in p.stdout:
            line = line.strip()
            if line:
                last = line
                short = line if len(line) < 90 else line[:87] + "…"
                root.after(0, lambda s=short: status.config(text=s))
        if p.wait() == 0:
            root.after(0, lambda: status.config(text="Done. Starting Mirage…", fg="#5fd4a0"))
            root.after(800, restart)
        else:
            root.after(0, lambda: (status.config(text="Install failed: " + last[:200], fg="#e2574c"),
                                   btn.config(state="normal", text="Try again")))

    def start():
        btn.config(state="disabled", text="Installing…")
        threading.Thread(target=work, daemon=True).start()

    def restart():
        import paths
        subprocess.Popen(paths.launch_args("--restarted"), cwd=str(BASE))
        root.destroy()

    btn.config(command=start)
    _log(f"Starting the repair window: {problem}")
    root.mainloop()


def went_back(message: str):
    """An update didn't start, and the old version is back on disk: say so, then start the old version."""
    _log(message)
    try:
        from tkinter import messagebox
        messagebox.showwarning("Mirage", message + "\n\nThe details are in the log.")
    except Exception:
        pass
    import paths
    subprocess.Popen(paths.launch_args("--restarted"), cwd=str(BASE))


def main():
    if "--selftest" in sys.argv:
        os._exit(selftest())
    try:
        import updater
        note = updater.starting()  # the first start after an update that crashed last time puts the old version back
    except Exception as e:
        updater, note = None, ""
        _log(f"Update check at start failed: {e}")
    if note:
        went_back(note)
        os._exit(0)
    try:
        import webview  # noqa: F401
        import ui_web
    except ImportError as e:
        if updater and updater.failed(f"missing part: {e}"):
            went_back(f"The update couldn't start (a part is missing: {e}), so Mirage went back to the previous version.")
            os._exit(0)
        repair(str(e))
        return
    try:
        ui_web.main()
    except Exception:
        err = traceback.format_exc()
        _log("Fatal error:\n" + err)
        if updater and updater.failed(err):
            went_back("The update crashed while starting, so Mirage went back to the previous version.")
            os._exit(0)
        try:
            from tkinter import messagebox
            messagebox.showerror("Mirage stopped", err[-1500:])
        except Exception:
            pass
        raise
    finally:
        os._exit(0)


if __name__ == "__main__":
    main()
