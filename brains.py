"""
Mirage's brains: what answers when no shortcut matches.

- LocalBrain: Mirage's own AI on this PC (llama.cpp). Free and private; "think hard" can go to Claude.
- ClaudeCodeBrain: Claude Code through the Claude Agent SDK. Uses the user's Claude login,
  keeps a conversation going, and can use Mirage's own skills as tools.
- ApiBrain: Claude through an Anthropic API key (pay per use).
- OffBrain: no brain; Mirage only does its built-in shortcuts.

Shortcuts never reach a brain, so simple commands cost nothing.
"""

import asyncio
import base64
import io
import os
import sys
import threading
import time
from datetime import datetime
from pathlib import Path

PERSONA = (
    "You are Mirage, a voice assistant living on the user's Windows PC, in the spirit of JARVIS. "
    "Your replies are spoken aloud and shown as subtitles, so answer in one to three short sentences "
    "unless the user asks for detail. Never use markdown, bullet points, code blocks, emojis or URLs "
    "in what you say. Be calm, confident and a little playful. "
    "Input comes from speech recognition and can contain misheard words; interpret it sensibly. "
    "Use Mirage's tools (remember, notes, to-dos, reminders, weather, opening things, media, the screen) "
    "whenever they help. {remember} If you did something, say briefly what you did."
)
REMEMBER_ALWAYS = ("When the user tells you something about themselves or their projects that is worth keeping, "
                   "save it with remember.")
REMEMBER_ASKED = ("Only use remember when the user asks you to remember something; Mirage notices other lasting "
                  "facts about the user by itself after the conversation.")


PC_GUIDE = (
    "You can use the user's mouse and keyboard. list_controls shows the numbered controls of the window they're "
    "using (quick); look_at_screen shows the screen with those numbers drawn on. Click by number; use x,y (0-1000 "
    "across the screenshot) only for things without a number. To type, click the text box first, then type_text. "
    "Use manage_window to switch to an app first. After acting, check with list_controls or look_at_screen before "
    "saying it worked. Never type passwords, PINs or payment details: ask the user to do that. Mirage asks the user "
    "before anything that sends, posts, deletes or buys, so you don't need to ask first. The user can press Esc to stop "
    "you. Work step by step until the task is done, then say in one sentence what you did."
)


def pc_allowed(engine) -> bool:
    import pc
    return pc.WINDOWS and bool(engine.cfg.get("pc_control", True))


def persona(engine) -> str:
    """Who Mirage is, plus the personality the user wrote in Settings."""
    extra = (engine.cfg.get("personality") or "").strip()
    learns = engine.cfg.get("auto_learn", True) and engine.cfg.get("brain") == "local"
    base = PERSONA.replace("{remember}", REMEMBER_ASKED if learns else REMEMBER_ALWAYS)
    return (base + (f"\n\n{PC_GUIDE}" if pc_allowed(engine) else "")
            + (f"\n\nYour personality, as the user describes it: {extra}" if extra else ""))


def brain_status(engine, label):
    """While Mirage has the mouse and keyboard the hologram says so (and how to stop it)."""
    if engine.hands.active:
        engine.set_status("acting", "Using your PC. Press Esc to stop.")
    else:
        engine.set_status("thinking", label)


def _log(msg):
    try:
        from mirage import log
        log(msg)
    except Exception:
        print(msg)


def context_block(engine, text: str, fresh: bool = False) -> str:
    """What the brain should know for this request: about the user, related memories and notes, to-dos, and
    (fresh: the brain has just started) what was said in the last little while."""
    sk, mem = engine.skills, engine.memory
    parts = [f"Current time: {datetime.now():%A %Y-%m-%d %H:%M}."]
    try:
        me = mem.me_facts(30)
        if me:
            parts.append("What you know about the user:\n" + "\n".join(f"- {f['text']}" for f in me))
        shown = {f["line"] for f in me}
        rel = mem.relevant_facts(text, 8, skip=shown)
        shown |= {f["line"] for f in rel}
        latest = [f for f in mem.facts()[-12:] if f["line"] not in shown][-6:]
        more = rel + latest
        if more:
            parts.append("Other things you remember:\n" + "\n".join(
                f"- {f['text']}" + (f" ({f['topic']})" if f["topic"] and f["topic"] not in f["text"] else "") for f in more))
        notes = [(n, l) for n, l in mem.search(text, 8) if n != "Memory" and "(from [[Memory]])" not in l][:6]
        if notes:
            parts.append("Possibly relevant lines from the user's notes:\n"
                         + "\n".join(f"- [{n}] {sk.clean_md(l)}" for n, l in notes))
        playlists = list((engine.cfg.get("spotify_playlists") or {}).keys())
        if playlists:
            parts.append("The user's saved Spotify playlists: " + ", ".join(playlists))
        todos = mem.todos()[:12]
        if todos:
            parts.append("Open to-do items: " + "; ".join(todos))
        if fresh and getattr(engine, "chats", None) and engine.cfg.get("chat_history", True):
            recent = engine.chats.recent(4, within=2 * 3600)
            if recent:
                parts.append("Your conversation with the user a little earlier:\n" + engine.recall.chats_text(recent, 1200))
    except Exception as e:
        _log(f"Context failed: {e}")
    return "\n\n".join(parts)


def screenshot_jpeg_b64(max_side=1400) -> str:
    import pyautogui
    img = pyautogui.screenshot()
    img.thumbnail((max_side, max_side))
    buf = io.BytesIO()
    img.convert("RGB").save(buf, format="JPEG", quality=80)
    return base64.b64encode(buf.getvalue()).decode()


# --------------------------------------------------------------------------- #
# The skills both brains can use
# --------------------------------------------------------------------------- #
class Skills:
    """Mirage's abilities as plain functions returning text. Shared by both brains."""

    def __init__(self, engine):
        self.e = engine

    def run(self, name, args):
        e, a, sk = self.e, self.e.actions, self.e.skills
        _log(f"Brain tool: {name} {args}")
        if name == "remember":
            import re
            fact = re.sub(r"^(?:the )?user\b", "The user", args["fact"].strip(), flags=re.I)
            fact = re.sub(r"\b(?:to|with|about) me\b", lambda m: m.group(0).replace("me", "Mirage"), fact)
            if not e.memory.remember(fact):
                return "Not saved: Mirage never keeps passwords, codes or card numbers."
            e.emit("memory_changed")
            return "Saved to memory."
        if name == "search_chats":
            if not getattr(e, "chats", None):
                return "There's no chat history."
            rows = e.chats.search(args.get("query") or "", args.get("when") or "", 15)
            return e.recall.chats_text(list(reversed(rows)))
        if name == "search_notes":
            hits = e.memory.search(args["query"], 8)
            return "\n".join(f"[{n}] {sk.clean_md(l)}" for n, l in hits) or "Nothing found in the notes."
        if name == "add_todo":
            e.memory.add_todo(args["item"])
            e.emit("memory_changed")
            return "Added to the to-do list."
        if name == "list_todos":
            return "; ".join(e.memory.todos()) or "The to-do list is empty."
        if name == "complete_todo":
            done = e.memory.complete_todo(args["item"])
            e.emit("memory_changed")
            return f"Checked off: {done}" if done else "No matching to-do item."
        if name == "set_reminder":
            when = datetime.fromisoformat(args["when"])
            e.reminders.add(when, args["text"])
            e.emit("reminders_changed")
            return f"Reminder set {sk.say_time(when)}."
        if name == "list_reminders":
            items = e.reminders.upcoming()
            return "; ".join(f"{r['text']} {sk.say_time(datetime.fromisoformat(r['when']))}" for r in items) or "No reminders."
        if name == "get_weather":
            return sk.weather_report(e.cfg, args.get("day") or "today")
        if name == "open_website":
            return a.open_website(args["site"]) or a.google(args["site"])
        if name == "open_app":
            return sk.open_roblox_game(e.cfg, args["name"]) or a.open_app(args["name"])
        if name == "play_media":
            return e.play(args["query"], args.get("service"))
        if name == "media_control":
            return a.media(args["action"]) or "Done."
        if name == "set_timer":
            return a.set_timer(int(args["seconds"]), args.get("label", ""))
        if name == "take_screenshot":
            return a.screenshot()
        if name in PC_NAMES or (name == "type_text" and pc_allowed(e)):
            import pc
            if not pc_allowed(e):
                return "Using the mouse and keyboard is turned off in Mirage's settings."
            h = e.hands
            try:
                if name == "list_controls":
                    return h.list_controls()
                if name == "click":
                    return h.click(args["target"], args.get("how") or "click")
                if name == "type_text":
                    return h.type(args["text"])
                if name == "press_keys":
                    return h.press(args["keys"])
                if name == "scroll":
                    return h.scroll(args.get("direction") or "down", int(args.get("amount") or 5), args.get("target") or "")
                if name == "manage_window":
                    return h.window(args.get("action") or "switch", args.get("name") or "")
            except pc.Stopped as s:
                return f"STOPPED: {s}. Stop now, do nothing else, and tell the user you stopped."
            except ValueError as v:
                return str(v)
        if name == "type_text":
            return a.type_text(args["text"]) or "Typed."
        if name == "roblox_studio":
            keys = {"playtest": ("f5",), "stop_playtest": ("shift", "f5"), "save": ("ctrl", "s")}[args["action"]]
            return sk.studio_key(*keys) or "Done."
        return f"Unknown tool {name}"


TOOL_SPECS = [
    ("remember", "Save a fact about the user or their projects to long-term memory.", {"fact": str}),
    ("search_notes", "Search the user's notes (Obsidian vault) and Mirage's memory.", {"query": str}),
    ("search_chats", "Search your past conversations with the user. query: words to look for (may be empty); "
                     "when: 'today', 'yesterday', 'this week', 'last week', a weekday, YYYY-MM-DD, or empty for any time.",
     {"query": str, "when": str}),
    ("add_todo", "Add an item to the user's to-do list.", {"item": str}),
    ("list_todos", "List the user's open to-do items.", {}),
    ("complete_todo", "Check off a to-do item, matched by its words.", {"item": str}),
    ("set_reminder", "Set a reminder that survives restarts. 'when' is local time as YYYY-MM-DDTHH:MM.",
     {"when": str, "text": str}),
    ("list_reminders", "List upcoming reminders.", {}),
    ("get_weather", "Weather for the user's city. day is 'today' or 'tomorrow'.", {"day": str}),
    ("open_website", "Open a website by name or URL in the browser.", {"site": str}),
    ("open_app", "Open an app, program or Roblox game on the PC by name.", {"name": str}),
    ("play_media", "Play music or a video. service is 'youtube' or 'spotify' (optional). If the user names one of "
                   "their saved Spotify playlists, pass its name as query and it starts in Spotify.", {"query": str, "service": str}),
    ("media_control", "Media keys: 'volume up', 'volume down', 'mute', 'pause', 'play', 'next', 'previous'.",
     {"action": str}),
    ("set_timer", "Start a countdown timer.", {"seconds": int, "label": str}),
    ("take_screenshot", "Save a screenshot to the Pictures folder.", {}),
    ("type_text", "Type text where the keyboard focus is (click the text box first). \\n presses Enter.", {"text": str}),
    ("roblox_studio", "Control Roblox Studio. action: 'playtest', 'stop_playtest' or 'save'.", {"action": str}),
]

PC_TOOL_SPECS = [
    ("list_controls", "List the numbered buttons, links, text boxes and other controls of the window the user is using. "
                      "Quick: use it before clicking and to check what happened.", {}),
    ("click", "Click a control by its number from list_controls or look_at_screen, or a spot 'x,y' on a 0-1000 scale "
              "across the last screenshot. how: 'click' (default), 'double click' or 'right click'.",
     {"target": str, "how": str}),
    ("press_keys", "Press a key or shortcut: 'enter', 'esc', 'tab', 'ctrl+t', 'ctrl+l', 'alt+tab', 'ctrl+shift+n'…",
     {"keys": str}),
    ("scroll", "Scroll 'up', 'down', 'left' or 'right' by amount notches (default 5), over a control number or x,y "
               "if target is given.", {"direction": str, "amount": int, "target": str}),
    ("manage_window", "Do something with an open window. action: 'switch', 'minimize', 'maximize', 'restore', 'close', "
                      "'left', 'right', 'other screen' or 'list'. name: what the user calls it, like 'discord' "
                      "(leave empty for the one they're using).", {"action": str, "name": str}),
]
PC_NAMES = {n for n, _, _ in PC_TOOL_SPECS}
OPTIONAL = {"set_timer": {"label"}, "play_media": {"service"}, "get_weather": {"day"}, "click": {"how"},
            "search_chats": {"query", "when"},
            "scroll": {"amount", "target"}, "manage_window": {"name"}}


def tool_specs(engine):
    return TOOL_SPECS + (PC_TOOL_SPECS if pc_allowed(engine) else [])


def json_schema(name, schema):
    pytype = {str: "string", int: "integer"}
    return {"type": "object", "properties": {k: {"type": pytype.get(v, "string")} for k, v in schema.items()},
            "required": [k for k in schema if k not in OPTIONAL.get(name, ())]}


def look_tool(engine, max_side=1280):
    """(text, JPEG base64) for look_at_screen: with Mirage's hands, the controls are numbered on the picture."""
    if pc_allowed(engine):
        try:
            return engine.hands.look(max_side)
        except Exception as ex:
            _log(f"Numbered screenshot failed: {ex}")
    return "This is the user's screen right now.", screenshot_jpeg_b64(max_side)


# --------------------------------------------------------------------------- #
# Claude Code
# --------------------------------------------------------------------------- #
class ClaudeCodeBrain:
    SAFE_TOOLS = ["Read", "Glob", "Grep", "WebSearch", "WebFetch", "TodoWrite", "Task"]
    POWER_TOOLS = ["Bash", "PowerShell", "Write", "Edit", "MultiEdit", "NotebookEdit"]

    def __init__(self, engine):
        self.e = engine
        self.skills = Skills(engine)
        self.loop = None
        self.client = None
        self.client_key = None
        self.last_used = 0.0
        self.lock = threading.Lock()

    # ---- installation / login ----
    @staticmethod
    def installed():
        try:
            import importlib
            importlib.invalidate_caches()
            import claude_agent_sdk  # noqa: F401
            return True
        except Exception:
            return False

    @staticmethod
    def cli_path():
        try:
            import claude_agent_sdk
            name = "claude.exe" if sys.platform.startswith("win") else "claude"
            p = Path(claude_agent_sdk.__file__).parent / "_bundled" / name
            return p if p.exists() else None
        except Exception:
            return None

    @staticmethod
    def logged_in():
        home = Path.home() / ".claude"
        return (home / ".credentials.json").exists() or bool(os.environ.get("CLAUDE_CODE_OAUTH_TOKEN"))

    def available(self):
        return self.installed()

    def reset(self):
        """Forget the current conversation (e.g. after changing model or permissions)."""
        if self.loop and self.client:
            client, self.client = self.client, None
            try:
                asyncio.run_coroutine_threadsafe(client.disconnect(), self.loop).result(10)
            except Exception:
                pass

    # ---- running ----
    def _ensure_loop(self):
        if self.loop is None:
            self.loop = asyncio.new_event_loop()
            threading.Thread(target=self.loop.run_forever, daemon=True, name="claude-code").start()

    def ask(self, text: str, screen: bool = False) -> str:
        if not self.installed():
            return "Claude Code isn't set up yet. Install it in Settings, under Brain."
        self._ensure_loop()
        with self.lock:
            fut = asyncio.run_coroutine_threadsafe(self._ask(text, screen), self.loop)
            try:
                reply = fut.result(timeout=240)
                return "Okay, I stopped." if self.e.hands.stopped() else reply
            except Exception as e:
                fut.cancel()
                self.reset()
                return self._explain(e)
            finally:
                self.e.hands.end()

    def _explain(self, e):
        msg = str(e)
        low = msg.lower()
        _log(f"Claude Code error: {msg}")
        if any(k in low for k in ("login", "log in", "logged in", "authenticat", "unauthorized", "401", "oauth")):
            return "I need you to log in to Claude Code first. It's in Settings, under Brain."
        if "git" in low and "bash" in low:
            return "Claude Code needs Git for Windows. Install it from git-scm.com, then try again."
        if "rate" in low and "limit" in low or "usage limit" in low:
            return "You've hit your Claude usage limit for now. Shortcuts still work."
        if isinstance(e, TimeoutError) or "timeout" in low:
            return "That took too long, so I stopped."
        return "Claude Code ran into a problem. The details are in the log."

    def _options(self):
        from claude_agent_sdk import ClaudeAgentOptions, PermissionResultAllow, PermissionResultDeny
        cfg = self.e.cfg
        power = bool(cfg.get("claude_power", False))

        async def permit(tool_name, tool_input, context):
            if tool_name.startswith("mcp__mirage__") or tool_name in self.SAFE_TOOLS:
                return PermissionResultAllow()
            if power:
                return PermissionResultAllow()
            return PermissionResultDeny(
                message="Mirage isn't allowed to run commands or change files. The user can turn on "
                        "'Let Claude run commands and edit files' in Mirage's settings.")

        allowed = self.SAFE_TOOLS + [f"mcp__mirage__{n}" for n, _, _ in tool_specs(self.e)] + ["mcp__mirage__look_at_screen"]
        if power:
            allowed += self.POWER_TOOLS
        return ClaudeAgentOptions(
            system_prompt=persona(self.e),
            model=cfg.get("claude_model") or "haiku",
            mcp_servers={"mirage": self._mcp_server()},
            allowed_tools=allowed,
            disallowed_tools=[] if power else list(self.POWER_TOOLS),
            can_use_tool=permit,
            cwd=str(Path.home()),
            max_turns=16,
        ), (cfg.get("claude_model"), power)

    def _mcp_server(self):
        from claude_agent_sdk import create_sdk_mcp_server, tool
        tools = []
        for name, desc, schema in tool_specs(self.e):
            def make(n):
                async def handler(args):
                    try:
                        out = await asyncio.to_thread(self.skills.run, n, args)
                        return {"content": [{"type": "text", "text": str(out or "Done.")}]}
                    except Exception as e:
                        return {"content": [{"type": "text", "text": f"That failed: {e}"}], "is_error": True}
                return handler
            tools.append(tool(name, desc, json_schema(name, schema))(make(name)))

        async def look(args):
            try:
                text, data = await asyncio.to_thread(look_tool, self.e, 1400)
                return {"content": [{"type": "image", "data": data, "mimeType": "image/jpeg"},
                                    {"type": "text", "text": text}]}
            except Exception as e:
                return {"content": [{"type": "text", "text": f"Couldn't capture the screen: {e}"}], "is_error": True}
        tools.append(tool("look_at_screen", "Take a screenshot to see what's on the user's screen.", {})(look))
        return create_sdk_mcp_server(name="mirage", version="2.0.0", tools=tools)

    async def _client_for_now(self):
        from claude_agent_sdk import ClaudeSDKClient
        options, key = self._options()
        idle = time.time() - self.last_used > 20 * 60
        if self.client is not None and (key != self.client_key or idle):
            try:
                await self.client.disconnect()
            except Exception:
                pass
            self.client = None
        if self.client is None:
            cli = self.cli_path()
            if cli:
                options.cli_path = str(cli)
            self.client = ClaudeSDKClient(options=options)
            await self.client.connect()
            self.client_key = key
        return self.client

    async def _ask(self, text, screen):
        from claude_agent_sdk import AssistantMessage, ResultMessage, TextBlock, ToolUseBlock
        client = await self._client_for_now()
        self.last_used = time.time()
        prompt = f"<context>\n{context_block(self.e, text)}\n</context>\n\n"
        if screen:
            prompt += "(The user is asking about their screen: use look_at_screen first.)\n"
        prompt += text
        await client.query(prompt)
        texts, result = [], None
        async for msg in client.receive_response():
            if isinstance(msg, AssistantMessage):
                for b in msg.content:
                    if isinstance(b, TextBlock) and b.text.strip():
                        texts.append(b.text.strip())
                    elif isinstance(b, ToolUseBlock):
                        brain_status(self.e, _tool_label(b.name))
            elif isinstance(msg, ResultMessage):
                result = msg
        self.last_used = time.time()
        if result is not None and result.is_error:
            raise RuntimeError("; ".join(result.errors or []) or result.result or result.subtype)
        reply = (result.result if result is not None and result.result else (texts[-1] if texts else "")).strip()
        return _speakable(reply) or "Done."


def _tool_label(name):
    n = name.replace("mcp__mirage__", "")
    return {"WebSearch": "Searching the web…", "WebFetch": "Reading a web page…", "Read": "Reading a file…",
            "Glob": "Looking for files…", "Grep": "Searching files…", "Bash": "Running a command…",
            "PowerShell": "Running a command…", "Write": "Writing a file…", "Edit": "Editing a file…",
            "search_notes": "Checking your notes…", "remember": "Saving to memory…",
            "look_at_screen": "Looking at your screen…", "get_weather": "Checking the weather…",
            "list_controls": "Looking at the window…", "search_chats": "Thinking back…",
            "set_reminder": "Setting a reminder…"}.get(n, "Working on it…")


def _speakable(text: str) -> str:
    """Strip markdown that would sound silly when read aloud."""
    import re
    t = re.sub(r"```.*?```", " ", text, flags=re.S)
    t = re.sub(r"`([^`]*)`", r"\1", t)
    t = re.sub(r"\*\*([^*]+)\*\*|__([^_]+)__", lambda m: m.group(1) or m.group(2), t)
    t = re.sub(r"^\s*[-*•]\s+", "", t, flags=re.M)
    t = re.sub(r"^\s*#+\s*", "", t, flags=re.M)
    t = re.sub(r"\[([^\]]+)\]\([^)]+\)", r"\1", t)
    return re.sub(r"\s+", " ", t).strip()


# --------------------------------------------------------------------------- #
# Anthropic API key
# --------------------------------------------------------------------------- #
class ApiBrain:
    def __init__(self, engine):
        self.e = engine
        self.skills = Skills(engine)
        self.client = None
        self.history = []
        self.reload()

    def reload(self):
        key = self.e.cfg.get("anthropic_api_key") or os.environ.get("ANTHROPIC_API_KEY", "")
        self.client = None
        if key:
            try:
                import anthropic
                self.client = anthropic.Anthropic(api_key=key)
            except Exception as e:
                _log(f"API brain unavailable: {e}")

    def available(self):
        return self.client is not None

    def reset(self):
        self.history = []

    def _tools(self):
        out = [{"name": name, "description": desc, "input_schema": json_schema(name, schema)}
               for name, desc, schema in tool_specs(self.e)]
        out.append({"name": "look_at_screen", "description": "See the user's screen.",
                    "input_schema": {"type": "object", "properties": {}}})
        return out

    def ask(self, text: str, screen: bool = False) -> str:
        try:
            return self._ask(text, screen)
        finally:
            self.e.hands.end()

    def _ask(self, text: str, screen: bool = False) -> str:
        if not self.client:
            return "Add an Anthropic API key in Settings, under Brain."
        content = [{"type": "text", "text": text}]
        if screen:
            try:
                content.insert(0, {"type": "image", "source": {"type": "base64", "media_type": "image/jpeg",
                                                               "data": screenshot_jpeg_b64()}})
            except Exception as e:
                _log(f"Screenshot failed: {e}")
        messages = self.history[-10:] + [{"role": "user", "content": content}]
        while messages and messages[0]["role"] != "user":
            messages.pop(0)
        system = persona(self.e) + "\n\n" + context_block(self.e, text, fresh=not self.history)
        spoken = []
        rounds = 6
        try:
            step = 0
            while step < rounds:
                step += 1
                resp = self.client.messages.create(
                    model=self.e.cfg.get("anthropic_model") or "claude-haiku-5-5",
                    max_tokens=500, system=system, tools=self._tools(), messages=messages)
                spoken = [b.text for b in resp.content if b.type == "text"]
                uses = [b for b in resp.content if b.type == "tool_use"]
                if not uses or self.e.hands.stopped():
                    break
                messages.append({"role": "assistant", "content": resp.content})
                results = []
                for b in uses:
                    if b.name in PC_NAMES:
                        rounds = 25  # using the PC takes many small steps
                    brain_status(self.e, _tool_label(b.name))
                    if b.name == "look_at_screen":
                        try:
                            note, data = look_tool(self.e, 1400)
                            out = [{"type": "image", "source": {"type": "base64", "media_type": "image/jpeg", "data": data}},
                                   {"type": "text", "text": note}]
                        except Exception as ex:
                            out = f"Couldn't capture the screen: {ex}"
                    else:
                        try:
                            out = str(self.skills.run(b.name, b.input or {}) or "Done.")
                        except Exception as ex:
                            out = f"That failed: {ex}"
                    results.append({"type": "tool_result", "tool_use_id": b.id, "content": out})
                messages.append({"role": "user", "content": results})
        except Exception as e:
            _log(f"API error: {e}")
            return "I couldn't reach my brain right now."
        if self.e.hands.stopped():
            return "Okay, I stopped."
        reply = _speakable(" ".join(spoken)) or "Done."
        self.history += [{"role": "user", "content": text}, {"role": "assistant", "content": reply}]
        self.history = self.history[-12:]
        return reply


# --------------------------------------------------------------------------- #
# Mirage's own brain (llama.cpp on this PC)
# --------------------------------------------------------------------------- #
THINK_HARD = r"^(?:please |okay |ok )?think (?:hard|carefully|deeply|really hard)(?: about (?:this|it))?[,.:]?\s*(.*)$"


class LocalBrain:
    def __init__(self, engine):
        import local_brain
        self.e = engine
        self.lb = local_brain
        self.skills = Skills(engine)
        self.history = []
        self.llm = local_brain.LocalLLM(log=_log, on_change=lambda: engine.emit("local_brain"))

    def key(self):
        k = self.e.cfg.get("local_model") or self.lb.DEFAULT_MODEL
        return k if k in self.lb.MODELS else self.lb.DEFAULT_MODEL

    def available(self):
        return self.lb.installed(self.key())

    def reset(self):
        self.history = []

    def reload(self):
        if self.llm.running() and self.llm.key != self.key():
            self.llm.stop()

    def stop(self):
        self.llm.stop()

    def _tools(self):
        out = [{"type": "function", "function": {"name": name, "description": desc, "parameters": json_schema(name, schema)}}
               for name, desc, schema in tool_specs(self.e)]
        out.append({"type": "function", "function": {"name": "look_at_screen", "description":
                    "See what's on the user's screen right now.", "parameters": {"type": "object", "properties": {}}}})
        return out

    def _ensure_running(self):
        if self.llm.running() and self.llm.key == self.key():
            return True, ""
        self.e.set_status("thinking", "Waking up my brain…")
        return self.llm.start(self.key(), float(self.e.cfg.get("brain_idle_minutes", 5)))

    def ask(self, text: str, screen: bool = False) -> str:
        try:
            return self._ask(text, screen)
        finally:
            self.e.hands.end()

    @staticmethod
    def _forget_old_looks(messages):
        """Only the newest screenshot and list of controls stay in full: older ones fill up the brain's memory."""
        pics = [m for m in messages if m["role"] == "user" and isinstance(m["content"], list)
                and any(c.get("type") == "image_url" for c in m["content"])]
        for m in pics[:-1]:
            m["content"] = "(an earlier screenshot)"
        lists = [m for m in messages if m["role"] == "tool" and str(m.get("content", "")).startswith("Window: ")]
        for m in lists[:-1]:
            m["content"] = m["content"].split("\n")[0] + "\n(an earlier list of controls; the numbers may have changed)"

    def _ask(self, text: str, screen: bool = False) -> str:
        import json
        import re
        think = False
        if re.match(THINK_HARD, text, re.I):  # the model understands "think hard about…" as it is
            think = True
            cc = self.e.brains.get("claude_code")
            if self.e.cfg.get("think_hard_claude", True) and cc and cc.installed() and cc.logged_in():
                self.e.set_status("thinking", "Asking Claude…")
                return cc.ask(text, screen)
        if not self.available():
            return "My brain isn't installed yet. Install it in Settings, under Brain."
        ok, msg = self._ensure_running()
        if not ok:
            return msg
        model = self.lb.MODELS[self.key()]
        system = persona(self.e) + "\n\n" + context_block(self.e, text, fresh=not self.history)
        if think and model["think"] == "token":
            system = "<|think|>" + system
        content = text
        if screen:
            try:
                content = [{"type": "image_url", "image_url": {"url": "data:image/jpeg;base64," + screenshot_jpeg_b64(1280)}},
                           {"type": "text", "text": text}]
            except Exception as e:
                _log(f"Screenshot failed: {e}")
        messages = [{"role": "system", "content": system}] + self.history[-10:] + [{"role": "user", "content": content}]
        tools = self._tools()
        reply = ""
        rounds, attempt = 7, 0
        try:
            while attempt < rounds:
                attempt += 1
                if think and not self.e.hands.active:
                    self.e.set_status("thinking", "Thinking it through…")
                try:
                    msg = self.llm.chat(messages, tools, think)
                except Exception as e:
                    if not self.llm.running() and attempt == 1:  # it crashed: start it again once
                        ok, why = self._ensure_running()
                        if ok:
                            continue
                    raise
                calls = msg.get("tool_calls") or []
                if not calls or self.e.hands.stopped():
                    reply = msg.get("content") or ""
                    break
                messages.append({"role": "assistant", "content": msg.get("content") or "", "tool_calls": calls})
                screen_after = None
                for c in calls:
                    fn = c.get("function", {})
                    name = fn.get("name", "")
                    try:
                        args = fn.get("arguments") or "{}"
                        args = json.loads(args) if isinstance(args, str) else args
                    except Exception:
                        args = {}
                    if name in PC_NAMES:
                        rounds = max(rounds, 25)  # using the PC takes many small steps
                    brain_status(self.e, _tool_label(name))
                    if name == "look_at_screen":
                        try:
                            note, screen_after = look_tool(self.e, 1280)
                            out = note + "\nThe screenshot is in the next message."
                        except Exception as ex:
                            out = f"Couldn't capture the screen: {ex}"
                    else:
                        try:
                            out = str(self.skills.run(name, args) or "Done.")
                        except Exception as ex:
                            out = f"That failed: {ex}"
                    messages.append({"role": "tool", "tool_call_id": c.get("id") or name, "content": out})
                if screen_after:
                    messages.append({"role": "user", "content": [
                        {"type": "image_url", "image_url": {"url": "data:image/jpeg;base64," + screen_after}},
                        {"type": "text", "text": "This is my screen right now."}]})
                self._forget_old_looks(messages)
                if self.e.hands.stopped():
                    break
        except Exception as e:
            _log(f"Local brain error: {e}")
            return "My brain had a problem answering that. " + str(e)[:120]
        if self.e.hands.stopped():
            why = self.e.hands.stop_reason
            return f"Okay, I stopped{', ' + why if why else ''}."
        reply = re.sub(r"<think>.*?</think>", " ", reply, flags=re.S)
        reply = _speakable(reply) or "Done."
        self.history += [{"role": "user", "content": text}, {"role": "assistant", "content": reply}]
        self.history = self.history[-12:]
        return reply


class OffBrain:
    def available(self):
        return False

    def reset(self):
        pass

    def reload(self):
        pass

    def ask(self, text, screen=False):
        return "I don't know that one. Turn on a brain in Settings, or add a shortcut for it."
