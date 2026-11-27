"""
Mirage 2 app shell: the window (HTML interface in web/), the bridge between the interface and
the engine, the tray icon and the corner hologram.
"""

import os
import shutil
import subprocess
import sys
import threading
import time
from collections import deque
from datetime import datetime
from pathlib import Path

import mirage as M
import paths

WEB = M.BASE_DIR / "web"
ASSETS = M.BASE_DIR / "assets"
ICON = ASSETS / "mirage.ico"
LAUNCHER = M.BASE_DIR / "mirage_app.py"
RUN_KEY = r"Software\Microsoft\Windows\CurrentVersion\Run"


# --------------------------------------------------------------------------- #
# Start with Windows
# --------------------------------------------------------------------------- #
def startup_command() -> str:
    return " ".join(f'"{a}"' if " " in a or "\\" in a else a for a in paths.launch_args("--tray"))


def get_startup() -> bool:
    if M.SYSTEM != "Windows":
        return False
    import winreg
    try:
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, RUN_KEY) as k:
            winreg.QueryValueEx(k, "Mirage")
            return True
    except OSError:
        return False


def set_startup(enabled: bool) -> bool:
    if M.SYSTEM != "Windows":
        return False
    import winreg
    with winreg.OpenKey(winreg.HKEY_CURRENT_USER, RUN_KEY, 0, winreg.KEY_SET_VALUE) as k:
        if enabled:
            winreg.SetValueEx(k, "Mirage", 0, winreg.REG_SZ, startup_command())
        else:
            try:
                winreg.DeleteValue(k, "Mirage")
            except FileNotFoundError:
                pass
    return get_startup()


def login_command(cli) -> str:
    """The console command that logs in to Claude Code. One string on purpose: a list would turn the quotes round the
    path into \\", which cmd doesn't understand, and claude.exe would never start."""
    cmd = Path(os.environ.get("SystemRoot", r"C:\Windows")) / "System32" / "cmd.exe"
    return (f'"{cmd}" /c title Log in to Claude for Mirage && echo Log in with your Claude account, then type /exit '
            f'and close this window. && echo. && "{cli}"')


def open_path(path: Path):
    if M.SYSTEM == "Windows":
        os.startfile(str(path))
    elif M.SYSTEM == "Darwin":
        subprocess.Popen(["open", str(path)])
    else:
        subprocess.Popen(["xdg-open", str(path)])


# --------------------------------------------------------------------------- #
# The bridge: every public method here can be called from web/app.js
# (attributes start with "_" so the window doesn't try to expose them)
# --------------------------------------------------------------------------- #
def fresh_page_after_update():
    """The window keeps a cached copy of the page between runs. After an update, throw it away so the new page loads."""
    store = M.DATA_DIR / ".webview"
    marker = store / "page-version.txt"
    try:
        if marker.exists() and marker.read_text().strip() == M.VERSION:
            return
        for root, dirs, _ in os.walk(store):
            for d in list(dirs):
                if d in ("Cache", "Code Cache", "GPUCache", "Service Worker", "CacheStorage", "ScriptCache"):
                    shutil.rmtree(os.path.join(root, d), ignore_errors=True)
                    dirs.remove(d)
        store.mkdir(exist_ok=True)
        marker.write_text(M.VERSION)
    except Exception as e:
        M.log(f"Couldn't clear the page cache: {e}")


class Bridge:
    def __init__(self, app):
        self._app = app

    # ---- state ----
    def get_state(self):
        a = self._app
        e = a.engine
        # messages already waiting in the queue are part of "messages" below; don't send them twice
        kept = [ev for ev in list(a.events) if ev[0] not in ("heard", "reply", "system")]
        a.events.clear()
        a.events.extend(kept)
        return {
            "version": M.read_version(),
            "system": M.SYSTEM,
            "cfg": a.cfg_view(),
            "status": [e.status, e.status_detail],
            "muted": e.mic_muted,
            "messages": list(a.messages),
            "start_page": a.start_page,
            "options": a.options,
            "speech": a.speech_state(),
            "builtins": [[g, n, ex] for g, n, ex in M.BUILTIN_GROUPS],
            "claude": a.claude_state(),
            "local": a.local_state(),
            "startup": get_startup(),
            "update_available": a.update_available,
            "whats_new": a.whats_new_pending,
        }

    # ---- what's new ----
    def whats_new_seen(self):
        self._app.whats_new_pending = []
        self._app.engine.update_config({"seen_version": M.VERSION})

    def get_whats_new(self):
        """The notes for this version and the two before it (Settings, App, What's new)."""
        import updater
        mine = updater.version_tuple(M.VERSION)
        return [[v, notes] for v, notes in updater.read_changes(updater.changes_file())
                if updater.version_tuple(v) <= mine][:3]

    # ---- diagnostics ----
    def diagnostics(self):
        """Everything the Diagnostics page shows: this PC, and how Mirage's parts are doing."""
        import diagnostics
        a = self._app
        e = a.engine
        cfg = e.cfg
        sp, lb = a.speech_state(), a.local_state()
        brain = cfg.get("brain", "local")
        if brain == "local":
            model = next((m[1] for m in lb.get("models", []) if m[0] == lb.get("model")), lb.get("model"))
            if not lb.get("installed"):
                brain_text = f"Mirage's own brain ({model}): not installed"
            else:
                where = "on the processor" if lb.get("gpu") is False else "on the graphics card"
                brain_text = (f"Mirage's own brain ({model}): " + ("running " + where if lb.get("running") else
                              f"ready, sleeping until you ask something ({where})") +
                              (f". Last problem: {lb['detail']}" if lb.get("state") == "error" else ""))
        elif brain == "claude_code":
            c = a.claude_state()
            brain_text = "Claude Code: " + ("logged in" if c["logged_in"] else "installed, not logged in" if c["installed"]
                                            else "not installed")
        elif brain == "api":
            brain_text = "Claude with an API key: " + ("key added" if cfg.get("anthropic_api_key") else "no key yet")
        else:
            brain_text = "Off: only shortcuts work"
        mic = cfg.get("input_device") or "the Windows default microphone"
        mic_text = (f"{mic}: muted in Mirage" if e.mic_muted else f"{mic}: {e.error_detail}" if e.mic_error
                    else f"{mic}: listening")
        voice = {"mirage": "Mirage's own voice", "windows": "the Windows voice", "voicestudio": "VoiceStudio"}.get(
            cfg.get("voice_engine"), cfg.get("voice_engine"))
        if sp.get("installed"):
            ears = {"ready": "ready", "loading": "loading…", "error": f"problem: {sp.get('detail')}"}.get(sp.get("state"),
                                                                                                         sp.get("state"))
            hearing = f"Mirage's own voice and hearing: {ears}"
        else:
            hearing = "Mirage's own voice and hearing: not installed (using the basic recognizer)"
        return {"pc": diagnostics.system_info(M.DATA_DIR), "mic": mic_text, "hearing": hearing,
                "voice": f"Speaking with {voice}", "brain": brain_text, "version": M.VERSION}

    def diagnostic_report(self):
        """The text for "Copy report": the facts, then the end of the log, without anything private."""
        import diagnostics
        d = self.diagnostics()
        info = {"Mirage": d["version"], **d["pc"], "Microphone": d["mic"], "Hearing": d["hearing"],
                "Voice": d["voice"], "Brain": d["brain"]}
        try:
            log = M.LOG_PATH.read_text(encoding="utf-8", errors="replace")
        except OSError:
            log = ""
        return diagnostics.report(info, log)

    def test_mic(self):
        """Listen for four seconds and say how loud it was and what Mirage heard."""
        a = self._app
        e = a.engine

        def work():
            if e.mic_muted:
                a.push("progress", ["micTest", "The microphone is muted in Mirage: unmute it first.", "bad"])
                return
            a.push("progress", ["micTest", "Listening for 4 seconds: say something…", "wait"])
            samples = e.record(4.0)
            if not samples:
                a.push("progress", ["micTest", "No sound came in at all. Check the microphone is plugged in and "
                                               "picked under Listening.", "bad"])
                return
            peak = max(abs(min(samples)), abs(max(samples)))
            if peak < 0.02:
                a.push("progress", ["micTest", "It's almost silent. Pick another microphone, or turn its volume up "
                                               "in Windows' sound settings.", "bad"])
                return
            loud = "quiet but usable" if peak < 0.1 else "a good level" if peak < 0.9 else "very loud (it may distort)"
            heard = ""
            if e.speech.ready():
                try:
                    import numpy as np
                    heard = e.speech.transcribe(np.asarray(samples, dtype=np.float32))
                except Exception as ex:
                    M.log(f"Microphone test: couldn't write it down: {ex}")
            text = f"The sound came in at {loud}." + (f" I heard: “{heard}”" if heard else
                                                      " I didn't make out any words." if e.speech.ready() else "")
            a.push("progress", ["micTest", text, "ok"])
        threading.Thread(target=work, daemon=True).start()

    def poll(self):
        return self._app.drain()

    def set_config(self, changes):
        changes = dict(changes or {})
        mode = changes.pop("reply_mode", None)
        if mode:
            changes["speak_replies"] = mode in ("both", "voice")
            changes["subtitles_enabled"] = mode in ("both", "subtitles")
        if changes:
            self._app.engine.update_config(changes)
        if "voice_engine" in changes or "voicestudio_url" in changes:
            threading.Thread(target=self._app.refresh_vs, daemon=True).start()
        if "local_model" in changes or "brain" in changes:
            self._app.push("state", {"local": self._app.local_state()})
        return self._app.cfg_view()

    # ---- talking ----
    def send(self, text):
        self._app.engine.submit_text(str(text))

    def toggle_mute(self):
        e = self._app.engine
        e.set_muted(not e.mic_muted)

    def test_voice(self):
        self._app.engine.voice.say("Hello. This is how I sound.", show=False, force=True)

    # ---- Mirage's own voice and ears ----
    def install_speech(self):
        a = self._app
        sp = a.engine.speech
        if sp.state == "installing":
            return

        def work():
            sp._set("installing", "Starting…")
            try:
                ok, msg = a.engine.speech_mod.install(
                    lambda m: (setattr(sp, "detail", m), a.push("progress", ["speechState", m, "wait"])), log=M.log)
            except Exception as e:
                ok, msg = False, f"Install failed: {e}"
            sp._set("off" if ok else "error", msg)
            if ok:
                sp.load_async(then=a.engine.speech_loaded)
                a.push("toast", "Mirage's voice and hearing are installed.")
            else:
                a.push("toast", "That didn't install. The reason is next to the button.")
        threading.Thread(target=work, daemon=True).start()

    def speech_reload(self):
        e = self._app.engine
        e.speech.load_async(then=e.speech_loaded)

    def preview_voice(self, voice):
        """Say a line in one of the voices without picking it."""
        e = self._app.engine
        if not e.speech.ready():
            return

        def work():
            _, speed, pitch, robot = e.voice_settings()
            name = next((v[2].split(" ·")[0] for v in e.speech_mod.VOICES if v[1] == voice), "Mirage")
            try:
                e.speech.speak(f"Hi, I'm {name}. This is how I'd sound as Mirage.", voice, speed, pitch, robot,
                               float(e.cfg.get("voice_volume", 1.0)))
            except Exception as err:
                self._app.push("toast", f"Couldn't play it: {err}")
        threading.Thread(target=work, daemon=True).start()

    def preview_hologram(self):
        self._app.holo.call("preview", 4.0)

    def refresh_options(self):
        self._app.refresh_options()
        return self._app.options

    # ---- memory page ----
    def get_memory(self):
        e = self._app.engine
        mem, sk = e.memory, e.skills
        memories = []
        for f in reversed(mem.facts(400)):
            when = f["when"]
            try:
                when = datetime.strptime(when, "%Y-%m-%d %H:%M").strftime("%d %b, %H:%M").lstrip("0")
            except ValueError:
                pass
            text = sk.spoken_fact(f["text"])
            memories.append({"line": f["line"], "when": when, "text": text, "topic": f["topic"] or "Other",
                             "noticed": f["noticed"]})
        todos = [{"i": i, "text": t, "done": d} for i, t, d in mem.todo_entries()]
        todos.sort(key=lambda x: x["done"])
        reminders = [{"id": r["id"], "text": r["text"][:1].upper() + r["text"][1:],
                      "when": sk.say_time(datetime.fromisoformat(r["when"]))[0:1].upper()
                      + sk.say_time(datetime.fromisoformat(r["when"]))[1:]}
                     for r in e.reminders.upcoming()]
        where = mem.vault.name if mem.is_obsidian() else "Mirage's own folder"
        return {"where": where, "memories": memories, "todos": todos, "reminders": reminders,
                "chats_on": bool(e.chats and e.cfg.get("chat_history", True))}

    def get_chats(self, query=""):
        e = self._app.engine
        if not e.chats:
            return []
        return e.chats.by_day(str(query or "").strip(), 300)

    def memory_action(self, kind, payload):
        e = self._app.engine
        mem, sk = e.memory, e.skills
        if kind == "remember":
            mem.remember(str(payload))
            return {"message": "Remembered."}
        if kind == "forget":
            mem.delete_memory_line(str(payload))
            return {}
        if kind == "add_todo":
            mem.add_todo(str(payload))
            return {}
        if kind == "toggle_todo":
            mem.toggle_todo(int(payload))
            return {}
        if kind == "delete_todo":
            mem.delete_todo(int(payload))
            return {}
        if kind == "add_reminder":
            text = str(payload)
            when, rest = sk.parse_when(text if "remind" in text else "remind me " + text)
            if when is None:
                return {"error": "Add a time, like “in 20 minutes to stretch” or “at 5 pm to call mom”."}
            import re
            what = re.sub(r"^.*?\bremind me\b\s*", "", rest)
            what = re.sub(r"^(?:to|that|about|of)\s+", "", what).strip() or "your reminder"
            e.reminders.add(when, what)
            return {"message": f"Reminder set {sk.say_time(when)}."}
        if kind == "delete_reminder":
            e.reminders.remove(int(payload))
            return {}
        if kind == "clear_chats":
            if e.chats:
                e.chats.clear()
            return {"message": "Chat history deleted."}
        if kind == "interview":
            e.submit_text("get to know me")
            return {"message": "Mirage will ask you a few questions."}
        return {"error": f"Unknown action {kind}"}

    def open_vault(self):
        e = self._app.engine
        note = e.memory.folder / "Memory.md"
        if not note.exists():
            e.memory.remember("Mirage memory started")
        if e.memory.is_obsidian():
            import urllib.parse
            import webbrowser
            webbrowser.open("obsidian://open?path=" + urllib.parse.quote(str(note)))
        else:
            open_path(e.memory.folder)

    def browse_vault(self):
        import webview
        kind = getattr(getattr(webview, "FileDialog", None), "FOLDER", None) or getattr(webview, "FOLDER_DIALOG", 20)
        res = self._app.window.create_file_dialog(kind)
        if not res:
            return None
        path = str(self._app.engine.skills.vault_root(res[0]))
        self._app.engine.update_config({"vault_path": path})
        self._app.refresh_options()
        return self._app.cfg_view()

    def relink(self):
        n = self._app.engine.memory.relink()
        return f"Linked {n} older memor{'y' if n == 1 else 'ies'}." if n else "Your memories already have links."

    # ---- brain ----
    def test_brain(self):
        a = self._app

        def work():
            a.push("progress", ["brainTest", "Asking…", "wait"])
            t0 = time.time()
            try:
                reply = a.engine.brain.ask("Reply with one short friendly sentence saying you're ready.")
            finally:
                a.engine.set_status(a.engine.idle_status())
            ok = not any(w in reply.lower() for w in ("log in", "isn't set up", "problem", "add an anthropic", "couldn't"))
            a.push("progress", ["brainTest", f"{reply} ({time.time() - t0:.1f} s)" if ok else reply, "ok" if ok else "bad"])
        threading.Thread(target=work, daemon=True).start()

    def install_local_brain(self, key=None):
        a = self._app
        e = a.engine
        lb = e.brains["local"]
        key = key or lb.key()
        if lb.llm.state == "installing":
            return

        def work():
            lb.llm._set("installing", "Starting…")
            try:
                ok, msg = lb.lb.install(key, lambda m: (setattr(lb.llm, "detail", m),
                                                       a.push("progress", ["localState", m, "wait"])), log=M.log)
            except Exception as ex:
                ok, msg = False, f"Install failed: {ex}"
            lb.llm._set("off" if ok else "error", msg)
            if ok:
                e.update_config({"local_model": key, "brain": "local"})
                a.push("toast", "Mirage's brain is installed.")
                a.push("state", {"local": a.local_state(), "cfg": a.cfg_view()})
                self.test_brain()
            else:
                a.push("toast", "The brain didn't install. The reason is next to the button.")
        threading.Thread(target=work, daemon=True).start()

    def remove_local_model(self, key):
        lb = self._app.engine.brains["local"]
        if lb.llm.key == key:
            lb.stop()
        lb.lb.remove_model(key)
        return self._app.local_state()

    def install_claude(self):
        a = self._app

        def work():
            a.push("progress", ["claudeState", "Installing Claude Code (about 180 MB)…", "wait"])
            r = subprocess.run(paths.pip("install", "--disable-pip-version-check", "claude-agent-sdk"),
                               capture_output=True, text=True, creationflags=paths.NO_WINDOW)
            if r.returncode != 0:
                lines = [l for l in (r.stderr or r.stdout).splitlines() if l.strip()]
                a.push("progress", ["claudeState", "Install failed: " + (lines[-1] if lines else "unknown error")[:200], "bad"])
                return
            a.push("state", {"claude": a.claude_state()})
            a.push("toast", "Claude Code is installed. Now log in.")
        threading.Thread(target=work, daemon=True).start()

    def claude_login(self):
        import brains
        cli = brains.ClaudeCodeBrain.cli_path()
        if not cli:
            self._app.push("toast", "Install Claude Code first.")
            return
        if M.SYSTEM == "Windows":
            subprocess.Popen(login_command(cli), creationflags=0x00000010)  # new console window
        else:
            subprocess.Popen(["x-terminal-emulator", "-e", str(cli)])
        self._app.push("toast", "A window opened. Log in there, then come back.", )
        threading.Thread(target=self._app.watch_login, daemon=True).start()

    # ---- app ----
    def set_startup(self, enabled):
        try:
            return set_startup(bool(enabled))
        except Exception as e:
            self._app.push("toast", f"Couldn't change the startup setting: {e}")
            return get_startup()

    def check_updates(self):
        a = self._app

        def work():
            import updater
            a.push("progress", ["updState", "Checking…", "wait"])
            latest, newer, err = updater.check(updater.repo(a.engine.cfg))
            if err:
                a.push("progress", ["updState", err, "bad"])
            elif newer:
                a.update_available = latest
                a.push("state", {"update_available": latest})
            else:
                a.push("progress", ["updState", "You're up to date.", "ok"])
        threading.Thread(target=work, daemon=True).start()

    def install_update(self):
        a = self._app

        def work():
            import updater
            try:
                updater.apply(updater.repo(a.engine.cfg),
                              progress=lambda m, done=None: a.push("progress", ["updState", m, "wait", done]))
                a.push("progress", ["updState", "Updated. Restarting…", "ok", 1.0])
                time.sleep(0.8)
                a.restart()
            except Exception as e:
                M.log(f"Update failed: {e}")
                a.push("progress", ["updState", f"Update failed: {e}", "bad"])
        threading.Thread(target=work, daemon=True).start()

    def setup_name(self, name):
        """First-run setup: what to call you."""
        name = str(name or "").strip()[:40]
        if name:
            self._app.engine.memory.remember(f"The user wants to be called {name}", topic="Me")
        return True

    def open_url(self, url):
        import webbrowser
        url = str(url)
        if url.startswith("https://"):
            webbrowser.open(url)

    def open_path(self, which):
        open_path(M.LOG_PATH if which == "log" else M.DATA_DIR)

    def quit(self):
        threading.Thread(target=self._app.quit, daemon=True).start()


# --------------------------------------------------------------------------- #
# The app
# --------------------------------------------------------------------------- #
class App:
    def __init__(self, start_hidden=False):
        import hologram
        self.events = deque(maxlen=2000)
        self.level = None
        self.messages = deque(maxlen=150)
        self.start_page = "home"
        self.update_available = None
        self.window = None
        self.tray = None
        self.start_hidden = start_hidden
        self._hidden = start_hidden
        self.options = {"mics": [], "voices": [], "vaults": [], "vs": {"ok": False, "voices": []}}
        self.engine = M.Engine(on_event=self.on_engine_event)
        self.whats_new_pending = self._whats_new()
        self.holo = hologram.HologramThread(lambda: self.engine.cfg)
        self.bridge = Bridge(self)

    def _whats_new(self):
        """[[version, notes]] to show once after an update; [] otherwise."""
        cfg = self.engine.cfg
        if cfg.get("seen_version") == M.VERSION:
            return []
        try:
            import updater
            notes = updater.whats_new(updater.changes_file(), cfg.get("seen_version") or "", M.VERSION) \
                if cfg.get("setup_done", True) else []
        except Exception as e:
            M.log(f"What's new: {e}")
            notes = []
        if not notes:  # nothing to show (or a brand-new install): don't look again until the next version
            self.engine.update_config({"seen_version": M.VERSION})
        return [[v, n] for v, n in notes]

    # ---- config as the interface sees it ----
    def cfg_view(self):
        c = dict(self.engine.cfg)
        speak, subs = c.get("speak_replies", True), c.get("subtitles_enabled", True)
        c["reply_mode"] = "both" if speak and subs else ("subtitles" if subs else "voice")
        c.setdefault("voice_commands", [])
        return c

    def speech_state(self):
        e = self.engine
        return e.speech.status() if getattr(e, "speech", None) else {"installed": False, "state": "off", "voices": []}

    def local_state(self):
        e = self.engine
        lb = e.brains["local"]
        key = lb.key()
        return {"state": lb.llm.state, "detail": lb.llm.detail, "model": key, "engine": lb.lb.engine_ready(),
                "installed": lb.lb.installed(key), "download_mb": lb.lb.download_mb(key), "running": lb.llm.running(),
                "gpu": lb.llm.uses_gpu() if lb.lb.engine_ready() else None, "nvidia": self.nvidia(),
                "models": [[k, m["name"], m["blurb"], lb.lb.model_ready(k), round((m["size"] + m["mmproj_size"]) / 1e9, 1)]
                           for k, m in lb.lb.MODELS.items()]}

    def nvidia(self):
        try:
            return bool(self.engine.brains["local"].lb._driver_cuda())
        except Exception:
            return False

    def claude_state(self):
        import brains
        b = brains.ClaudeCodeBrain
        return {"installed": b.installed(), "logged_in": b.logged_in()}

    def refresh_options(self):
        e = self.engine
        e.voice.ready.wait(3)
        vaults = [("", "Documents › Mirage")]
        for name, path in e.skills.find_obsidian_vaults():
            vaults.append((path, f"{name} (Obsidian)"))
        cur = e.cfg.get("vault_path") or ""
        if cur and cur not in [v[0] for v in vaults]:
            vaults.append((cur, Path(cur).name))
        self.options.update({"mics": M.list_input_devices(), "voices": [list(v) for v in e.voice.voices],
                             "vaults": [list(v) for v in vaults]})
        self.refresh_vs()

    def refresh_vs(self):
        ok, voices, err = M.voicestudio_check(self.engine.cfg.get("voicestudio_url") or "http://localhost:3900")
        self.options["vs"] = {"ok": ok, "voices": [list(v) for v in voices], "err": err}
        self.push("state", {"options": self.options})

    def watch_login(self):
        """After the login window opens, notice when the login has worked."""
        import brains
        for _ in range(300):
            time.sleep(2)
            if brains.ClaudeCodeBrain.logged_in():
                self.push("state", {"claude": self.claude_state()})
                self.push("toast", "Logged in to Claude.")
                return

    # ---- events ----
    def push(self, kind, data=None):
        self.events.append([kind, data])

    def drain(self):
        out = []
        while self.events:
            out.append(self.events.popleft())
        if self.level is not None:
            out.append(["level", self.level])
            self.level = None
        return out

    def on_engine_event(self, kind, data):
        if kind == "level":
            self.level = data
            self.holo.call("set_level", data)
            return
        if kind == "speech_progress":  # the voice started saying piece data[1] of reply data[0]
            self.holo.call("caption_spoken", data[0], data[1])
            return
        if kind == "speech_started":  # the voice started a whole reply and won't say where it is
            self.holo.call("caption_started", data)
            return
        if kind == "status":
            self.holo.call("set_status", data[0])
            if data[0] == "acting" and data[1]:
                self.holo.call("set_subtitle", data[1], "mirage", False)  # how to stop it (not said out loud)
        elif kind in ("heard", "reply", "system"):
            who = {"heard": "you", "reply": "mirage", "system": "sys"}[kind]
            self.messages.append({"who": who, "text": data, "at": datetime.now().strftime("%H:%M")})
            if kind == "reply":
                self.holo.call("set_subtitle", data, "mirage")
            elif kind == "heard" and self.engine.cfg.get("subtitles_show_you"):
                self.holo.call("set_subtitle", data, "you")
        elif kind == "muted" and self.tray:
            try:
                self.tray.update_menu()
            except Exception:
                pass
        elif kind == "show_window":
            self.show()
            return
        elif kind == "quit":
            threading.Thread(target=self.quit, daemon=True).start()
            return
        elif kind == "reminder" and self.tray:
            try:
                self.tray.notify(data, "Mirage reminder")
            except Exception:
                pass
        elif kind == "gaming":
            self.holo.call("set_blocked", bool(data))  # no hologram over a full-screen game
        elif kind == "local_brain":
            if getattr(self, "engine", None) is not None:
                self.push("state", {"local": self.local_state()})
            return
        elif kind == "speech":
            if getattr(self, "engine", None) is not None:  # not while the engine is still starting
                self.push("state", {"speech": self.speech_state(), "cfg": self.cfg_view()})
            return
        self.push(kind, data)

    # ---- window ----
    def show(self):
        self._hidden = False
        if self.window:
            try:
                self.window.show()
                self.window.restore()
            except Exception:
                pass

    def on_closing(self):
        if self.engine.cfg.get("close_to_tray", True) and self.tray:
            self._hidden = True
            threading.Thread(target=self.window.hide, daemon=True).start()
            if not getattr(self, "_told_tray", False):
                self._told_tray = True
                try:
                    self.tray.notify("Mirage is still listening. Click the tray icon to open it.", "Mirage")
                except Exception:
                    pass
            return False
        threading.Thread(target=self.quit, daemon=True).start()
        return False

    def on_shown(self):
        """Dark, purple-and-gold title bar and Mirage's icon (Windows 10/11)."""
        if M.SYSTEM != "Windows":
            return
        try:
            import ctypes
            hwnd = self.window.native.Handle.ToInt32()
            dwm = ctypes.windll.dwmapi
            on = ctypes.c_int(1)
            dwm.DwmSetWindowAttribute(hwnd, 20, ctypes.byref(on), 4)                  # dark mode
            for attr, rgb in ((35, 0x001C0A12), (36, 0x00FFE3EC), (34, 0x003FA9D9)):  # caption, text, border
                c = ctypes.c_int(rgb)
                dwm.DwmSetWindowAttribute(hwnd, attr, ctypes.byref(c), 4)
        except Exception as e:
            M.log(f"Title bar styling skipped: {e}")

    def start_tray(self):
        try:
            import pystray
            from PIL import Image
            img = Image.open(ASSETS / "icon.png").resize((64, 64))
            menu = pystray.Menu(
                pystray.MenuItem("Open Mirage", lambda i, it: self.show(), default=True),
                pystray.MenuItem("Mute microphone", lambda i, it: self.bridge.toggle_mute(),
                                 checked=lambda it: self.engine.mic_muted),
                pystray.Menu.SEPARATOR,
                pystray.MenuItem("Quit Mirage", lambda i, it: threading.Thread(target=self.quit, daemon=True).start()),
            )
            self.tray = pystray.Icon("Mirage", img, "Mirage", menu)
            self.tray.run_detached()
        except Exception as e:
            M.log(f"Tray icon unavailable: {e}")
            self.tray = None

    def restart(self):
        args = paths.launch_args("--restarted", *(["--tray"] if getattr(self, "_hidden", self.start_hidden) else []))
        flags = 0x00000008 | 0x00000200 if M.SYSTEM == "Windows" else 0
        subprocess.Popen(args, cwd=str(M.BASE_DIR), creationflags=flags, close_fds=True)
        self.quit()  # doesn't confirm an update just installed: that's for its own first start (updater._ours)

    def quit(self):
        try:
            import updater
            updater.confirm()  # a normal quit counts as the update working
        except Exception:
            pass
        try:
            self.engine.stop()
            if self.tray:
                self.tray.stop()
            if self.window:
                self.window.destroy()
        finally:
            M.log("Mirage stopped.")
            os._exit(0)

    def run(self):
        import webview
        if M.SYSTEM == "Windows":
            try:
                import ctypes
                ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID("Mirage.Assistant")
            except Exception:
                pass
        self.refresh_options()
        fresh_page_after_update()
        self.window = webview.create_window(
            "Mirage", url=str(WEB / "index.html"), js_api=self.bridge,
            width=1120, height=760, min_size=(900, 620), background_color="#120a1c",
            hidden=self.start_hidden, text_select=False)
        self.window.events.closing += self.on_closing
        self.window.events.shown += self.on_shown
        self.start_tray()
        self.engine.start()
        import updater
        if self.engine.cfg.get("check_updates_on_start", True) and updater.enabled() and updater.repo(self.engine.cfg):
            threading.Timer(6, self.bridge.check_updates).start()
        # right after an update: still running 20 s after start means the new version works, so keep it
        t = threading.Timer(20, updater.confirm)
        t.daemon = True
        t.start()
        webview.start(http_server=True, debug=False, private_mode=False,
                      storage_path=str(M.DATA_DIR / ".webview"), icon=str(ICON))


def main():
    if "--enable-startup" in sys.argv:
        set_startup(True)
        print("Mirage will start with Windows.")
        return
    holder = {}
    lock = M.acquire_instance(on_show=lambda: holder["app"].show() if "app" in holder else None)
    if lock is None and "--restarted" in sys.argv:
        for _ in range(40):  # the old copy is still closing
            time.sleep(0.25)
            lock = M.acquire_instance(on_show=lambda: holder["app"].show() if "app" in holder else None)
            if lock:
                break
    if lock is None:
        M.log("Mirage is already running - showing its window.")
        return
    app = App(start_hidden="--tray" in sys.argv)
    holder["app"] = app
    app.run()
