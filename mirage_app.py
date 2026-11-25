"""
MIRAGE - desktop app.

    python mirage_app.py           open the window
    python mirage_app.py --tray    start hidden in the system tray
"""

import math
import os
import queue
import subprocess
import sys
import threading
import time
import traceback
import webbrowser
from datetime import datetime
from pathlib import Path
import tkinter as tk

import customtkinter as ctk

import mirage as M
import hologram

# --------------------------------------------------------------------------- #
# Look & feel
# --------------------------------------------------------------------------- #
BG = "#080c14"
PANEL = "#0f1522"
PANEL_2 = "#161e2e"
BORDER = "#222c40"
TEXT = "#e6edf7"
MUTED = "#8592a8"
ACCENT = "#22d3ee"
ACCENT_DARK = "#0e7490"
YOU_BUBBLE = "#164e63"
MIRAGE_BUBBLE = "#1b2436"
DANGER = "#f87171"

STATUS_STYLE = {
    "loading":   ("#94a3b8", "Starting up…"),
    "listening": ("#22d3ee", "Listening for “mirage”"),
    "awaiting":  ("#34d399", "I'm listening…"),
    "thinking":  ("#a78bfa", "Thinking…"),
    "speaking":  ("#fbbf24", "Speaking…"),
    "muted":     ("#64748b", "Microphone muted"),
    "error":     ("#f87171", "Something's wrong"),
}

FONT = "Segoe UI" if M.SYSTEM == "Windows" else "Helvetica"
ICON_PATH = M.BASE_DIR / "mirage.ico"


def mix(c1: str, c2: str, f: float) -> str:
    """Blend colour c1 towards c2 by f (0..1)."""
    a = [int(c1[i:i + 2], 16) for i in (1, 3, 5)]
    b = [int(c2[i:i + 2], 16) for i in (1, 3, 5)]
    return "#" + "".join(f"{round(x + (y - x) * f):02x}" for x, y in zip(a, b))


def make_icon_image(size=64):
    from PIL import Image, ImageDraw
    img = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    d = ImageDraw.Draw(img)
    s = size
    d.ellipse((0, 0, s - 1, s - 1), fill=(8, 12, 20, 255))
    d.ellipse((s * .08, s * .08, s * .92, s * .92), outline=(34, 211, 238, 255), width=max(2, s // 16))
    d.ellipse((s * .30, s * .30, s * .70, s * .70), fill=(34, 211, 238, 255))
    d.ellipse((s * .40, s * .36, s * .54, s * .50), fill=(207, 250, 254, 255))
    return img


class SmoothScrollFrame(ctk.CTkScrollableFrame):
    """CTkScrollableFrame with calmer scrolling.

    The stock version scrolls a few pixels per wheel event and redraws each time, which on
    Windows shows up as flicker and half-drawn, duplicated rows. This one adds up wheel movement,
    scrolls at most ~60 times a second and forces a full redraw after each step."""

    STEP = 70  # pixels per wheel notch

    def _set_scroll_increments(self):
        self._parent_canvas.configure(xscrollincrement=1, yscrollincrement=1)

    def _mouse_wheel_all(self, event):
        if not self.winfo_ismapped() or not self._check_if_valid_scroll(event.widget):
            return
        if self._parent_canvas.yview() == (0.0, 1.0):
            return
        if sys.platform == "darwin":
            px = -event.delta * 6
        elif sys.platform.startswith("linux"):
            px = -self.STEP if event.num == 4 else self.STEP
        else:
            px = int(-event.delta / 120 * self.STEP)
        self._wheel_pending = getattr(self, "_wheel_pending", 0) + px
        if not getattr(self, "_wheel_job", None):
            self._wheel_job = self.after(16, self._flush_wheel)

    def _flush_wheel(self):
        self._wheel_job = None
        px, self._wheel_pending = self._wheel_pending, 0
        if px:
            self._parent_canvas.yview_scroll(px, "units")
            self._parent_canvas.update_idletasks()


def make_scroll_area(parent, **kw):
    opts = dict(fg_color=BG, scrollbar_button_color=BORDER)
    opts.update(kw)
    return SmoothScrollFrame(parent, **opts)

# --------------------------------------------------------------------------- #
# Start with Windows (HKCU Run key)
# --------------------------------------------------------------------------- #
RUN_KEY = r"Software\Microsoft\Windows\CurrentVersion\Run"


def _startup_command():
    exe = Path(sys.executable)
    pyw = exe.with_name("pythonw.exe")
    if pyw.exists():
        exe = pyw
    return f'"{exe}" "{Path(__file__).resolve()}" --tray'


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


def set_startup(enabled: bool):
    if M.SYSTEM != "Windows":
        return
    import winreg
    with winreg.OpenKey(winreg.HKEY_CURRENT_USER, RUN_KEY, 0, winreg.KEY_SET_VALUE) as k:
        if enabled:
            winreg.SetValueEx(k, "Mirage", 0, winreg.REG_SZ, _startup_command())
        else:
            try:
                winreg.DeleteValue(k, "Mirage")
            except FileNotFoundError:
                pass


# --------------------------------------------------------------------------- #
# The app
# --------------------------------------------------------------------------- #
class MirageApp(ctk.CTk):
    def __init__(self, events: "queue.Queue", start_hidden=False):
        ctk.set_appearance_mode("dark")
        ctk.set_default_color_theme("blue")
        super().__init__(fg_color=BG)
        self.events = events
        self.title("Mirage")
        self.geometry("1000x680")
        self.minsize(860, 580)
        self._set_window_icon()

        self.engine = M.Engine(on_event=lambda k, d: self.events.put((k, d)))
        self.status, self.status_detail = "loading", ""
        self.level = 0.0
        self.smooth = 0.0
        self.messages = []
        self._after_ids = {}
        self.tray = None
        self._told_about_tray = False

        self.grid_columnconfigure(1, weight=1)
        self.grid_rowconfigure(0, weight=1)
        # Make Ctrl+A select everything in text boxes (Tk's default jumps to the start instead)
        self.bind_class("Entry", "<Control-a>", self._select_all)
        self.bind_class("Entry", "<Control-A>", self._select_all)
        self._build_sidebar()
        self.content = ctk.CTkFrame(self, fg_color=BG, corner_radius=0)
        self.content.grid(row=0, column=1, sticky="nsew")
        self.content.grid_columnconfigure(0, weight=1)
        self.content.grid_rowconfigure(0, weight=1)
        self.pages = {
            "home": self._build_home(),
            "settings": self._build_settings(),
            "shortcuts": self._build_shortcuts(),
        }
        self.show_page("home")

        self.hologram = hologram.Hologram(self, lambda: self.engine.cfg)
        self._start_tray()
        self.protocol("WM_DELETE_WINDOW", self.on_close)
        self.after(50, self._poll_events)
        self.after(33, self._animate)
        self.engine.start()
        if self.engine.cfg.get("check_updates_on_start", True) and M.update_repo(self.engine.cfg):
            self.after(4000, self._check_updates)
        if start_hidden and self.tray:
            self.withdraw()

    @staticmethod
    def _select_all(event):
        event.widget.select_range(0, "end")
        event.widget.icursor("end")
        return "break"

    # ------------------------------------------------------------------ #
    # Window chrome
    # ------------------------------------------------------------------ #
    def _set_window_icon(self):
        try:
            if not ICON_PATH.exists():
                make_icon_image(256).save(ICON_PATH, sizes=[(16, 16), (32, 32), (48, 48), (256, 256)])
            if M.SYSTEM == "Windows":
                self.iconbitmap(str(ICON_PATH))
                # customtkinter resets the icon shortly after start; set it again
                self.after(300, lambda: self.iconbitmap(str(ICON_PATH)))
        except Exception as e:
            M.log(f"Icon not set: {e}")

    def _build_sidebar(self):
        bar = ctk.CTkFrame(self, fg_color=PANEL, corner_radius=0, width=220)
        bar.grid(row=0, column=0, sticky="nsw")
        bar.grid_propagate(False)
        bar.grid_columnconfigure(0, weight=1)

        ctk.CTkLabel(bar, text="MIRAGE", text_color=ACCENT,
                     font=ctk.CTkFont(FONT, 26, "bold")).grid(row=0, column=0, padx=24, pady=(28, 0), sticky="w")
        ctk.CTkLabel(bar, text="your voice assistant", text_color=MUTED,
                     font=ctk.CTkFont(FONT, 12)).grid(row=1, column=0, padx=24, pady=(0, 26), sticky="w")

        self.nav_buttons = {}
        for i, (key, label) in enumerate((("home", "Home"), ("settings", "Settings"), ("shortcuts", "Shortcuts"))):
            b = ctk.CTkButton(bar, text=label, anchor="w", height=40, corner_radius=10,
                              font=ctk.CTkFont(FONT, 14), fg_color="transparent",
                              hover_color=PANEL_2, text_color=TEXT,
                              command=lambda k=key: self.show_page(k))
            b.grid(row=2 + i, column=0, padx=14, pady=3, sticky="ew")
            self.nav_buttons[key] = b

        bar.grid_rowconfigure(10, weight=1)

        self.mute_btn = ctk.CTkButton(bar, text="Mute microphone", height=40, corner_radius=10,
                                      font=ctk.CTkFont(FONT, 13), fg_color=PANEL_2, hover_color=BORDER,
                                      text_color=TEXT, command=self.toggle_mute)
        self.mute_btn.grid(row=11, column=0, padx=14, pady=(0, 10), sticky="ew")

        st = ctk.CTkFrame(bar, fg_color="transparent")
        st.grid(row=12, column=0, padx=22, pady=(0, 22), sticky="ew")
        self.side_dot = tk.Canvas(st, width=12, height=12, bg=PANEL, highlightthickness=0)
        self.side_dot.pack(side="left")
        self.side_status = ctk.CTkLabel(st, text="Starting up…", text_color=MUTED, font=ctk.CTkFont(FONT, 12))
        self.side_status.pack(side="left", padx=8)

    def show_page(self, name):
        for key, frame in self.pages.items():
            frame.grid_forget()
        self.pages[name].grid(row=0, column=0, sticky="nsew")
        for key, b in self.nav_buttons.items():
            b.configure(fg_color=PANEL_2 if key == name else "transparent",
                        text_color=ACCENT if key == name else TEXT)
        self.current_page = name

    # ------------------------------------------------------------------ #
    # Home page: orb + conversation
    # ------------------------------------------------------------------ #
    def _build_home(self):
        page = ctk.CTkFrame(self.content, fg_color=BG, corner_radius=0)
        page.grid_columnconfigure(0, weight=1)
        page.grid_rowconfigure(1, weight=1)

        top = ctk.CTkFrame(page, fg_color=BG)
        top.grid(row=0, column=0, sticky="ew", pady=(16, 0))
        self.orb = tk.Canvas(top, width=260, height=210, bg=BG, highlightthickness=0)
        self.orb.pack()
        self.status_label = ctk.CTkLabel(top, text="Starting up…", text_color=TEXT,
                                         font=ctk.CTkFont(FONT, 18, "bold"))
        self.status_label.pack()
        self.detail_label = ctk.CTkLabel(top, text="", text_color=MUTED, font=ctk.CTkFont(FONT, 12),
                                         wraplength=600)
        self.detail_label.pack(pady=(0, 8))

        self.chat = make_scroll_area(page, fg_color=PANEL, corner_radius=16)
        self.chat.grid(row=1, column=0, sticky="nsew", padx=24, pady=(4, 10))
        self.empty_hint = ctk.CTkLabel(
            self.chat, text='Say "mirage" followed by a command — or type one below.\n'
                            'Try: "mirage what time is it" or "mirage open youtube".',
            text_color=MUTED, font=ctk.CTkFont(FONT, 13), justify="center")
        self.empty_hint.pack(pady=40)

        bottom = ctk.CTkFrame(page, fg_color="transparent")
        bottom.grid(row=2, column=0, sticky="ew", padx=24, pady=(0, 20))
        bottom.grid_columnconfigure(0, weight=1)
        self.entry = ctk.CTkEntry(bottom, placeholder_text="Type a command for Mirage…", height=44,
                                  corner_radius=12, fg_color=PANEL, border_color=BORDER,
                                  font=ctk.CTkFont(FONT, 14))
        self.entry.grid(row=0, column=0, sticky="ew")
        self.entry.bind("<Return>", lambda e: self.send_typed())
        ctk.CTkButton(bottom, text="Send", width=90, height=44, corner_radius=12,
                      fg_color=ACCENT_DARK, hover_color=ACCENT, font=ctk.CTkFont(FONT, 14, "bold"),
                      command=self.send_typed).grid(row=0, column=1, padx=(10, 0))
        return page

    def send_typed(self):
        text = self.entry.get().strip()
        if text:
            self.entry.delete(0, "end")
            self.engine.submit_text(text)

    def add_message(self, who: str, text: str):
        if self.empty_hint is not None:
            self.empty_hint.destroy()
            self.empty_hint = None
        row = ctk.CTkFrame(self.chat, fg_color="transparent")
        row.pack(fill="x", padx=10, pady=5)
        if who == "system":
            ctk.CTkLabel(row, text=text, text_color=MUTED, font=ctk.CTkFont(FONT, 12),
                         wraplength=560).pack()
        else:
            side = "e" if who == "you" else "w"
            name = "You" if who == "you" else "Mirage"
            ctk.CTkLabel(row, text=f"{name}  ·  {datetime.now():%H:%M}", text_color=MUTED,
                         font=ctk.CTkFont(FONT, 11)).pack(anchor=side, padx=6)
            bubble = ctk.CTkFrame(row, corner_radius=14,
                                  fg_color=YOU_BUBBLE if who == "you" else MIRAGE_BUBBLE)
            bubble.pack(anchor=side)
            ctk.CTkLabel(bubble, text=text, text_color=TEXT, font=ctk.CTkFont(FONT, 14),
                         wraplength=520, justify="left").pack(padx=14, pady=9)
        self.messages.append(row)
        while len(self.messages) > 150:
            self.messages.pop(0).destroy()
        self.after(30, lambda: self.chat._parent_canvas.yview_moveto(1.0))

    def _animate(self):
        try:
            if self.state() == "normal" and self.current_page == "home":
                self._draw_orb()
        except tk.TclError:
            return
        self.after(33, self._animate)

    def _draw_orb(self):
        c = self.orb
        c.delete("all")
        t = time.time()
        color = STATUS_STYLE.get(self.status, STATUS_STYLE["listening"])[0]
        target = 0.0 if self.status == "muted" else min(1.0, self.level * 5)
        self.smooth = self.smooth * 0.75 + target * 0.25
        cx, cy = 130, 105
        breathe = 3 * math.sin(t * 2.2)
        r = 46 + breathe + self.smooth * 22
        # outer rings
        for i in range(4):
            rr = r + 16 + i * 13 + self.smooth * 10 * (i + 1)
            fade = 0.55 + i * 0.13
            c.create_oval(cx - rr, cy - rr, cx + rr, cy + rr,
                          outline=mix(color, BG, min(fade, 0.95)), width=2)
        # glow
        for i in range(6, 0, -1):
            gr = r + i * 4
            c.create_oval(cx - gr, cy - gr, cx + gr, cy + gr, outline="",
                          fill=mix(color, BG, 0.80 + i * 0.03))
        # core
        c.create_oval(cx - r, cy - r, cx + r, cy + r, outline="", fill=mix(color, BG, 0.35))
        ir = r * 0.62
        c.create_oval(cx - ir, cy - ir, cx + ir, cy + ir, outline="", fill=mix(color, "#ffffff", 0.15))
        hr = r * 0.22
        c.create_oval(cx - hr - r * 0.18, cy - hr - r * 0.22, cx + hr - r * 0.18, cy + hr - r * 0.22,
                      outline="", fill=mix(color, "#ffffff", 0.65))
        if self.status in ("thinking", "loading"):
            ar = r + 10
            c.create_arc(cx - ar, cy - ar, cx + ar, cy + ar, start=(t * 240) % 360, extent=80,
                         style="arc", outline=color, width=3)

    # ------------------------------------------------------------------ #
    # Settings page
    # ------------------------------------------------------------------ #
    def _card(self, parent, title, subtitle=""):
        card = ctk.CTkFrame(parent, fg_color=PANEL, corner_radius=16)
        card.pack(fill="x", padx=24, pady=8)
        card.grid_columnconfigure(0, weight=1, minsize=290)
        ctk.CTkLabel(card, text=title, text_color=TEXT, font=ctk.CTkFont(FONT, 16, "bold")).grid(
            row=0, column=0, columnspan=2, sticky="w", padx=20, pady=(16, 0 if subtitle else 8))
        if subtitle:
            ctk.CTkLabel(card, text=subtitle, text_color=MUTED, font=ctk.CTkFont(FONT, 12)).grid(
                row=1, column=0, columnspan=2, sticky="w", padx=20, pady=(0, 8))
        card._next_row = 2
        return card

    def _row(self, card, label, desc=""):
        r = card._next_row
        card._next_row += 1
        box = ctk.CTkFrame(card, fg_color="transparent")
        box.grid(row=r, column=0, sticky="w", padx=20, pady=8)
        ctk.CTkLabel(box, text=label, text_color=TEXT, font=ctk.CTkFont(FONT, 14)).pack(anchor="w")
        if desc:
            ctk.CTkLabel(box, text=desc, text_color=MUTED, font=ctk.CTkFont(FONT, 12),
                         wraplength=290, justify="left").pack(anchor="w")
        holder = ctk.CTkFrame(card, fg_color="transparent")
        holder.grid(row=r, column=1, sticky="e", padx=20, pady=8)
        return holder

    def _save_later(self, key, value, delay=400):
        if key in self._after_ids:
            self.after_cancel(self._after_ids[key])
        self._after_ids[key] = self.after(delay, lambda: self._save_now(key, value))

    def _save_now(self, key, value):
        self._after_ids.pop(key, None)
        self.engine.update_config({key: value})
        self.saved_label.configure(text="✓ Saved")
        self.after(1500, lambda: self.saved_label.configure(text=""))

    def _build_settings(self):
        page = ctk.CTkFrame(self.content, fg_color=BG, corner_radius=0)
        page.grid_columnconfigure(0, weight=1)
        page.grid_rowconfigure(1, weight=1)
        head = ctk.CTkFrame(page, fg_color="transparent")
        head.grid(row=0, column=0, sticky="ew", padx=24, pady=(24, 4))
        ctk.CTkLabel(head, text="Settings", text_color=TEXT, font=ctk.CTkFont(FONT, 24, "bold")).pack(side="left")
        self.saved_label = ctk.CTkLabel(head, text="", text_color="#34d399", font=ctk.CTkFont(FONT, 13))
        self.saved_label.pack(side="right")
        ctk.CTkLabel(head, text="Changes save automatically", text_color=MUTED,
                     font=ctk.CTkFont(FONT, 12)).pack(side="right", padx=12)

        # Settings are split into tabs so no page needs a long scroll (long scrolling lists
        # redraw badly on Windows).
        page.grid_rowconfigure(1, weight=0)
        page.grid_rowconfigure(2, weight=1)
        self.settings_tabs = ctk.CTkSegmentedButton(
            page, values=["Microphone", "Voice", "Wake word & AI", "Hologram", "App"], height=34,
            font=ctk.CTkFont(FONT, 13), selected_color=ACCENT_DARK, selected_hover_color=ACCENT,
            unselected_color=PANEL, unselected_hover_color=PANEL_2, fg_color=PANEL,
            command=self._show_settings_tab)
        self.settings_tabs.grid(row=1, column=0, sticky="w", padx=24, pady=(6, 4))
        self.settings_sections = {}
        for name in ("Microphone", "Voice", "Wake word & AI", "Hologram", "App"):
            self.settings_sections[name] = make_scroll_area(page)
        cfg = self.engine.cfg

        # --- Microphone ---
        body = self.settings_sections["Microphone"]
        card = self._card(body, "Microphone", "What Mirage listens with.")
        h = self._row(card, "Input device", "Pick the mic Mirage should listen to.")
        self.mic_menu = ctk.CTkOptionMenu(h, width=260, dynamic_resizing=False, fg_color=PANEL_2,
                                          button_color=BORDER, button_hover_color=ACCENT_DARK,
                                          command=self._on_mic_change)
        self.mic_menu.pack(side="left")
        ctk.CTkButton(h, text="↻", width=36, fg_color=PANEL_2, hover_color=BORDER,
                      command=self._refresh_mics).pack(side="left", padx=(8, 0))
        self._refresh_mics()

        h = self._row(card, "Input level", "Talk — the bar should move.")
        self.level_bar = ctk.CTkProgressBar(h, width=300, height=12, progress_color=ACCENT, fg_color=PANEL_2)
        self.level_bar.set(0)
        self.level_bar.pack()

        h = self._row(card, "Mute microphone", "Mirage stops listening until you turn this off.")
        self.mute_switch = ctk.CTkSwitch(h, text="", progress_color=ACCENT_DARK,
                                         command=lambda: self.engine.set_muted(bool(self.mute_switch.get())))
        self.mute_switch.pack()

        # --- Voice ---
        body = self.settings_sections["Voice"]
        card = self._card(body, "Voice", "How Mirage sounds when it talks back.")
        h = self._row(card, "Voice engine",
                      "Windows = built-in voices. VoiceStudio = realistic AI voices "
                      "(VoiceStudio must be open).")
        self.engine_switch = ctk.CTkSegmentedButton(
            h, values=["Windows", "VoiceStudio"], selected_color=ACCENT_DARK,
            selected_hover_color=ACCENT, unselected_color=PANEL_2, command=self._on_engine_change)
        self.engine_switch.set("VoiceStudio" if cfg.get("voice_engine") == "voicestudio" else "Windows")
        self.engine_switch.pack()

        h = self._row(card, "Windows voice")
        self.voice_menu = ctk.CTkOptionMenu(h, width=260, dynamic_resizing=False, values=["Loading voices…"],
                                            fg_color=PANEL_2, button_color=BORDER,
                                            button_hover_color=ACCENT_DARK, command=self._on_voice_change)
        self.voice_menu.pack()
        self.after(200, self._fill_voices)

        h = self._row(card, "VoiceStudio voice",
                      "Voices you clone or design in VoiceStudio show up here. Press ↻ after adding one.")
        self.vs_menu = ctk.CTkOptionMenu(h, width=260, dynamic_resizing=False, values=["(checking…)"],
                                         fg_color=PANEL_2, button_color=BORDER,
                                         button_hover_color=ACCENT_DARK, command=self._on_vs_voice_change)
        self.vs_menu.pack(side="left")
        ctk.CTkButton(h, text="↻", width=36, fg_color=PANEL_2, hover_color=BORDER,
                      command=self._check_voicestudio).pack(side="left", padx=(8, 0))

        h = self._row(card, "VoiceStudio connection")
        self.vs_status = ctk.CTkLabel(h, text="", font=ctk.CTkFont(FONT, 13), wraplength=180, justify="right")
        self.vs_status.pack(side="left")
        ctk.CTkButton(h, text="Get VoiceStudio", width=120, fg_color=PANEL_2, hover_color=BORDER,
                      command=lambda: webbrowser.open("https://github.com/debpalash/VoiceStudio/releases/latest")
                      ).pack(side="left", padx=(8, 0))
        self._vs_ids = {}
        self.after(400, self._check_voicestudio)

        h = self._row(card, "Speaking speed")
        self.rate_value = ctk.CTkLabel(h, text=str(cfg["voice_rate"]), width=40, text_color=MUTED)
        rate = ctk.CTkSlider(h, from_=100, to=300, number_of_steps=40, width=250, button_color=ACCENT,
                             progress_color=ACCENT_DARK,
                             command=lambda v: (self.rate_value.configure(text=str(int(v))),
                                                self._save_later("voice_rate", int(v))))
        rate.set(cfg["voice_rate"])
        rate.pack(side="left")
        self.rate_value.pack(side="left", padx=(8, 0))

        h = self._row(card, "Volume")
        self.vol_value = ctk.CTkLabel(h, text=f"{int(cfg['voice_volume'] * 100)}%", width=40, text_color=MUTED)
        vol = ctk.CTkSlider(h, from_=0, to=100, number_of_steps=20, width=250, button_color=ACCENT,
                            progress_color=ACCENT_DARK,
                            command=lambda v: (self.vol_value.configure(text=f"{int(v)}%"),
                                               self._save_later("voice_volume", round(v / 100, 2))))
        vol.set(cfg["voice_volume"] * 100)
        vol.pack(side="left")
        self.vol_value.pack(side="left", padx=(8, 0))

        h = self._row(card, "Speak replies out loud", "Turn off to only see replies in the chat.")
        self._switch(h, "speak_replies")

        h = self._row(card, "Test")
        ctk.CTkButton(h, text="Play test sentence", fg_color=ACCENT_DARK, hover_color=ACCENT,
                      command=lambda: self.engine.voice.say(
                          "Hello. This is how I sound.", show=False)).pack()

        # --- Wake word ---
        body = self.settings_sections["Wake word & AI"]
        card = self._card(body, "Wake word", "What you say to get Mirage's attention.")
        h = self._row(card, "Wake words",
                      "Separate with commas. Add spellings it might mishear, "
                      "remove ones that trigger by accident.")
        self.wake_entry = ctk.CTkEntry(h, width=300, fg_color=PANEL_2, border_color=BORDER)
        self.wake_entry.insert(0, ", ".join(cfg["wake_words"]))
        self.wake_entry.pack()
        self.wake_entry.bind("<Return>", lambda e: self._save_wake())
        self.wake_entry.bind("<FocusOut>", lambda e: self._save_wake())

        h = self._row(card, "Beep when activated", "Plays a short beep when Mirage hears its name.")
        self._switch(h, "wake_sound")

        h = self._row(card, "Time to give a command",
                      'How long Mirage waits after you say just "mirage".')
        self.timeout_value = ctk.CTkLabel(h, text=f"{cfg['command_timeout_seconds']} s", width=40, text_color=MUTED)
        to = ctk.CTkSlider(h, from_=3, to=15, number_of_steps=12, width=250, button_color=ACCENT,
                           progress_color=ACCENT_DARK,
                           command=lambda v: (self.timeout_value.configure(text=f"{int(v)} s"),
                                              self._save_later("command_timeout_seconds", int(v))))
        to.set(cfg["command_timeout_seconds"])
        to.pack(side="left")
        self.timeout_value.pack(side="left", padx=(8, 0))

        # --- AI ---
        card = self._card(body, "AI brain (optional)",
                          "With an Anthropic API key Mirage can answer questions and understand free-form requests.")
        h = self._row(card, "API key", "Pay-per-use. Short voice replies cost very little.")
        self.key_entry = ctk.CTkEntry(h, width=230, show="•", fg_color=PANEL_2, border_color=BORDER,
                                      placeholder_text="sk-ant-…")
        if cfg.get("anthropic_api_key"):
            self.key_entry.insert(0, cfg["anthropic_api_key"])
        self.key_entry.pack(side="left")
        self.key_entry.bind("<Return>", lambda e: self._save_key())
        self.key_entry.bind("<FocusOut>", lambda e: self._save_key())
        ctk.CTkButton(h, text="Get key", width=70, fg_color=PANEL_2, hover_color=BORDER,
                      command=lambda: webbrowser.open("https://console.anthropic.com/settings/keys")
                      ).pack(side="left", padx=(8, 0))
        h = self._row(card, "Status")
        self.ai_status = ctk.CTkLabel(h, text="", font=ctk.CTkFont(FONT, 13))
        self.ai_status.pack()
        self._update_ai_status()

        # --- Hologram ---
        body = self.settings_sections["Hologram"]
        card = self._card(body, "Hologram", "A see-through orb that pops up in a corner of your screen "
                                            "while Mirage listens, thinks and speaks.")
        h = self._row(card, "Show hologram", "Pops up when you say \"mirage\" and fades away after.")
        self._switch(h, "hologram_enabled")
        h = self._row(card, "Corner")
        corners = {"Bottom right": "bottom-right", "Bottom left": "bottom-left",
                   "Top right": "top-right", "Top left": "top-left"}
        corner_menu = ctk.CTkOptionMenu(
            h, width=200, values=list(corners), fg_color=PANEL_2, button_color=BORDER,
            button_hover_color=ACCENT_DARK,
            command=lambda v: (self.engine.update_config({"hologram_corner": corners[v]}),
                               self.hologram.preview()))
        corner_menu.set(next((k for k, v in corners.items() if v == cfg.get("hologram_corner")), "Bottom right"))
        corner_menu.pack()
        h = self._row(card, "Size")
        sizes = {"Small": "small", "Medium": "medium", "Large": "large"}
        size_btn = ctk.CTkSegmentedButton(
            h, values=list(sizes), selected_color=ACCENT_DARK, selected_hover_color=ACCENT,
            unselected_color=PANEL_2,
            command=lambda v: (self.engine.update_config({"hologram_size": sizes[v]}), self.hologram.preview()))
        size_btn.set(next((k for k, v in sizes.items() if v == cfg.get("hologram_size")), "Medium"))
        size_btn.pack()
        h = self._row(card, "Preview", "Shows the hologram for a few seconds.")
        ctk.CTkButton(h, text="Show me", width=100, fg_color=ACCENT_DARK, hover_color=ACCENT,
                      command=lambda: self.hologram.preview(4)).pack()

        # --- App ---
        body = self.settings_sections["App"]
        card = self._card(body, "App")
        h = self._row(card, "Start with Windows", "Mirage starts hidden in the tray when you log in.")
        self.startup_switch = ctk.CTkSwitch(h, text="", progress_color=ACCENT_DARK, command=self._on_startup)
        self.startup_switch.pack()
        if M.SYSTEM != "Windows":
            self.startup_switch.configure(state="disabled")
        elif get_startup():
            self.startup_switch.select()

        h = self._row(card, "Keep running when closed",
                      "Closing the window hides Mirage in the tray (bottom-right of the taskbar) "
                      "so it keeps listening.")
        self._switch(h, "close_to_tray")

        h = self._row(card, "Updates", f"You have version {M.VERSION}.")
        self.update_btn = ctk.CTkButton(h, text="Check for updates", width=150, fg_color=ACCENT_DARK,
                                        hover_color=ACCENT, command=self._on_update_button)
        self.update_btn.pack(anchor="e")
        self.update_status = ctk.CTkLabel(h, text="", text_color=MUTED, font=ctk.CTkFont(FONT, 12),
                                          wraplength=280, justify="right")
        self.update_status.pack(anchor="e")
        self._latest_version = None

        h = self._row(card, "GitHub key", "Only needed if the Mirage repo is private. "
                                          "Leave empty for a public repo.")
        self.gh_entry = ctk.CTkEntry(h, width=120, show="•", fg_color=PANEL_2, border_color=BORDER,
                                     placeholder_text="github_pat_…")
        if cfg.get("github_token"):
            self.gh_entry.insert(0, cfg["github_token"])
        self.gh_entry.pack(side="left")
        self.gh_entry.bind("<Return>", lambda e: self._save_gh_token())
        self.gh_entry.bind("<FocusOut>", lambda e: self._save_gh_token())
        ctk.CTkButton(h, text="Paste", width=54, fg_color=PANEL_2, hover_color=BORDER,
                      command=self._paste_gh_token).pack(side="left", padx=(8, 0))
        ctk.CTkButton(h, text="Clear", width=54, fg_color=PANEL_2, hover_color=BORDER,
                      command=lambda: (self.gh_entry.delete(0, "end"), self._save_gh_token())
                      ).pack(side="left", padx=(8, 0))
        ctk.CTkButton(h, text="Create", width=64, fg_color=PANEL_2, hover_color=BORDER,
                      command=lambda: webbrowser.open("https://github.com/settings/personal-access-tokens/new")
                      ).pack(side="left", padx=(8, 0))

        h = self._row(card, "Files")
        ctk.CTkButton(h, text="Open log", width=100, fg_color=PANEL_2, hover_color=BORDER,
                      command=lambda: self._open_path(M.LOG_PATH)).pack(side="left")
        ctk.CTkButton(h, text="Open folder", width=100, fg_color=PANEL_2, hover_color=BORDER,
                      command=lambda: self._open_path(M.BASE_DIR)).pack(side="left", padx=(8, 0))

        h = self._row(card, "Quit Mirage", "Stops listening completely.")
        ctk.CTkButton(h, text="Quit", width=100, fg_color="#7f1d1d", hover_color="#b91c1c",
                      command=self.quit_app).pack()
        self.settings_tabs.set("Microphone")
        self._show_settings_tab("Microphone")
        return page

    def _show_settings_tab(self, name):
        for key, area in self.settings_sections.items():
            if key == name:
                area.grid(row=2, column=0, sticky="nsew", pady=(0, 12))
            else:
                area.grid_forget()

    def _switch(self, holder, key):
        sw = ctk.CTkSwitch(holder, text="", progress_color=ACCENT_DARK)
        sw.configure(command=lambda: self.engine.update_config({key: bool(sw.get())}))
        if self.engine.cfg.get(key):
            sw.select()
        sw.pack()
        return sw

    def _refresh_mics(self):
        names = M.list_input_devices()
        values = ["System default"] + names
        self.mic_menu.configure(values=values)
        current = self.engine.cfg.get("input_device")
        self.mic_menu.set(current if current in names else "System default")

    def _on_mic_change(self, value):
        self.engine.update_config({"input_device": None if value == "System default" else value})
        self.add_message("system", f"Now listening with: {value}")

    def _fill_voices(self):
        if not self.engine.voice.ready.is_set():
            self.after(300, self._fill_voices)
            return
        voices = self.engine.voice.voices
        self._voice_ids = {"System default": ""}
        for vid, name in voices:
            self._voice_ids[name] = vid
        self.voice_menu.configure(values=list(self._voice_ids))
        cur = self.engine.cfg.get("voice_id", "")
        name = next((n for n, v in self._voice_ids.items() if v == cur), "System default")
        self.voice_menu.set(name)

    def _on_voice_change(self, name):
        if not hasattr(self, "_voice_ids") or name not in self._voice_ids:
            return
        self.engine.update_config({"voice_id": self._voice_ids[name]})
        self.engine.voice.say("This is my new voice.", show=False)

    def _on_engine_change(self, value):
        self.engine.update_config({"voice_engine": "voicestudio" if value == "VoiceStudio" else "windows"})
        self.engine.voice._vs_warned = False
        if value == "VoiceStudio":
            self._check_voicestudio()
        self.engine.voice.say("This is how I sound now.", show=False)

    def _check_voicestudio(self):
        self.vs_status.configure(text="● Checking…", text_color=MUTED)
        url = self.engine.cfg.get("voicestudio_url") or "http://localhost:3900"
        threading.Thread(target=lambda: self.events.put(("vs_checked", M.voicestudio_check(url))),
                         daemon=True).start()

    def _apply_vs_check(self, result):
        ok, voices, err = result
        if ok:
            self.vs_status.configure(text="● Connected", text_color="#34d399")
        else:
            self.vs_status.configure(text="● " + err, text_color=DANGER if
                                     self.engine.cfg.get("voice_engine") == "voicestudio" else MUTED)
        self._vs_ids = {"VoiceStudio default": ""}
        for vid, name in voices:
            label = name if name not in self._vs_ids else f"{name} ({vid})"
            self._vs_ids[label] = vid
        for p in M.VOICESTUDIO_PRESETS:
            if p not in self._vs_ids.values():
                self._vs_ids[f"Preset: {p}"] = p
        self.vs_menu.configure(values=list(self._vs_ids))
        cur = self.engine.cfg.get("voicestudio_voice", "")
        label = next((n for n, v in self._vs_ids.items() if v == cur), None)
        if label is None and cur:
            self._vs_ids[cur] = cur
            self.vs_menu.configure(values=list(self._vs_ids))
            label = cur
        self.vs_menu.set(label or "VoiceStudio default")

    def _on_vs_voice_change(self, label):
        if label not in self._vs_ids:
            return
        self.engine.update_config({"voicestudio_voice": self._vs_ids[label]})
        if self.engine.cfg.get("voice_engine") == "voicestudio":
            self.engine.voice.say("This is my new voice.", show=False)

    def _save_wake(self):
        words = [w.strip().lower() for w in self.wake_entry.get().split(",") if w.strip()]
        if not words:
            words = ["mirage"]
            self.wake_entry.delete(0, "end")
            self.wake_entry.insert(0, "mirage")
        if words != self.engine.cfg.get("wake_words"):
            self._save_now("wake_words", words)

    def _save_key(self):
        key = self.key_entry.get().strip()
        if key != (self.engine.cfg.get("anthropic_api_key") or ""):
            self._save_now("anthropic_api_key", key)
            self._update_ai_status()

    def _update_ai_status(self):
        if self.engine.brain.client:
            self.ai_status.configure(text="● Connected", text_color="#34d399")
        elif self.engine.cfg.get("anthropic_api_key"):
            self.ai_status.configure(text="● Key saved, but couldn't connect", text_color=DANGER)
        else:
            self.ai_status.configure(text="● Off — built-in commands only", text_color=MUTED)

    def _on_startup(self):
        try:
            set_startup(bool(self.startup_switch.get()))
            self.saved_label.configure(text="✓ Saved")
            self.after(1500, lambda: self.saved_label.configure(text=""))
        except Exception as e:
            M.log(f"Startup setting failed: {e}")
            self.add_message("system", f"Couldn't change the startup setting: {e}")

    # ---- updates ----
    def _on_update_button(self):
        if self._latest_version:
            self._install_update()
        else:
            self._check_updates(quiet=False)

    def _check_updates(self, quiet=True):
        repo = M.update_repo(self.engine.cfg)
        if not quiet:
            self.update_btn.configure(state="disabled", text="Checking…")
        threading.Thread(target=lambda: self.events.put(("update_checked", (quiet, M.check_for_update(repo)))),
                         daemon=True).start()

    def _apply_update_check(self, quiet, result):
        latest, newer, err = result
        self.update_btn.configure(state="normal")
        if err:
            self.update_btn.configure(text="Check for updates")
            if not quiet:
                self.update_status.configure(text=err, text_color=DANGER)
            return
        if newer:
            self._latest_version = latest
            self.update_btn.configure(text=f"Install {latest}", fg_color="#15803d", hover_color="#16a34a")
            self.update_status.configure(text=f"Version {latest} is available!", text_color="#34d399")
            self.add_message("system", f"An update is available (version {latest}). "
                                       "Go to Settings → App → Install to update.")
        else:
            self.update_btn.configure(text="Check for updates")
            if not quiet:
                self.update_status.configure(text="✓ You're up to date.", text_color="#34d399")

    def _paste_gh_token(self):
        try:
            text = self.clipboard_get().strip()
        except tk.TclError:
            text = ""
        self.gh_entry.delete(0, "end")
        self.gh_entry.insert(0, text)
        self._save_gh_token()

    def _save_gh_token(self):
        token = self.gh_entry.get().strip()
        if token != (self.engine.cfg.get("github_token") or ""):
            self._save_now("github_token", token)
            self._latest_version = None
            self._check_updates(quiet=False)

    def _install_update(self):
        repo = M.update_repo(self.engine.cfg)
        self.update_btn.configure(state="disabled", text="Updating…")

        def work():
            try:
                M.apply_update(repo, progress=lambda m: self.events.put(("update_progress", m)))
                self.events.put(("update_done", None))
            except Exception as e:
                M.log(f"Update failed: {e}")
                self.events.put(("update_failed", str(e)))
        threading.Thread(target=work, daemon=True).start()

    def restart(self):
        """Start a fresh copy of Mirage, then close this one."""
        exe = Path(sys.executable)
        if exe.name.lower() == "python.exe" and exe.with_name("pythonw.exe").exists():
            exe = exe.with_name("pythonw.exe")
        args = [str(exe), str(Path(__file__).resolve()), "--restarted"]
        if self.state() == "withdrawn":
            args.append("--tray")
        flags = 0x00000008 | 0x00000200 if M.SYSTEM == "Windows" else 0  # DETACHED | NEW_GROUP
        subprocess.Popen(args, cwd=str(M.BASE_DIR), creationflags=flags, close_fds=True)
        self.quit_app()

    def _open_path(self, path: Path):
        try:
            if not path.exists() and path.suffix == ".log":
                path.write_text("", encoding="utf-8")
            if M.SYSTEM == "Windows":
                os.startfile(str(path))
            elif M.SYSTEM == "Darwin":
                subprocess.Popen(["open", str(path)])
            else:
                subprocess.Popen(["xdg-open", str(path)])
        except Exception as e:
            M.log(f"Couldn't open {path}: {e}")

    # ------------------------------------------------------------------ #
    # Shortcuts page
    # ------------------------------------------------------------------ #
    def _build_shortcuts(self):
        page = ctk.CTkFrame(self.content, fg_color=BG, corner_radius=0)
        page.grid_columnconfigure(0, weight=1)
        page.grid_rowconfigure(1, weight=1)
        ctk.CTkLabel(page, text="Shortcuts", text_color=TEXT, font=ctk.CTkFont(FONT, 24, "bold")).grid(
            row=0, column=0, sticky="w", padx=24, pady=(24, 4))
        body = make_scroll_area(page)
        body.grid(row=1, column=0, sticky="nsew", pady=(0, 12))

        self.site_list = self._shortcut_card(
            body, "Websites", 'Say "mirage open <name>" to open the site.',
            "name, e.g. roblox", "https://…", kind="websites")
        self.app_list = self._shortcut_card(
            body, "Apps", 'Say "mirage open <name>". Use a program name, a full path to an .exe, '
                          'or a link like discord:',
            "name, e.g. studio", r"C:\path\to\app.exe", kind="apps")

        card = self._card(body, "Things you can say")
        examples = [
            ("mirage open youtube / discord / roblox studio", "opens a website or app"),
            ("mirage play lofi music", "plays it on YouTube"),
            ("mirage search how to script a door in roblox", "Google search"),
            ("mirage set a timer for 10 minutes", "timer with a spoken alert"),
            ("mirage what time is it", "time and date"),
            ("mirage volume up · mute · pause · next song", "media controls"),
            ("mirage take a screenshot", "saved to Pictures\\Mirage"),
            ("mirage type hello world", "types into the active window"),
            ("mirage lock my computer · close window", "PC controls"),
            ("mirage mute microphone", "stops listening"),
            ("mirage show yourself", "opens this window"),
            ("mirage shut down", "quits Mirage (not your PC)"),
        ]
        for i, (say, what) in enumerate(examples):
            ctk.CTkLabel(card, text=f"“{say}”", text_color=TEXT, font=ctk.CTkFont(FONT, 13)).grid(
                row=2 + i, column=0, sticky="w", padx=20, pady=3)
            ctk.CTkLabel(card, text=what, text_color=MUTED, font=ctk.CTkFont(FONT, 12)).grid(
                row=2 + i, column=1, sticky="e", padx=20, pady=3)
        ctk.CTkFrame(card, fg_color="transparent", height=8).grid(row=99, column=0)
        return page

    def _shortcut_items(self, kind):
        if kind == "websites":
            return self.engine.cfg["websites"]
        return self.engine.cfg["apps"].setdefault(M.SYSTEM, {})

    def _save_shortcuts(self, kind):
        if kind == "websites":
            self.engine.update_config({"websites": self.engine.cfg["websites"]})
        else:
            self.engine.update_config({"apps": self.engine.cfg["apps"]})

    def _shortcut_card(self, parent, title, subtitle, name_hint, target_hint, kind):
        card = self._card(parent, title, subtitle)
        add = ctk.CTkFrame(card, fg_color="transparent")
        add.grid(row=2, column=0, columnspan=2, sticky="ew", padx=20, pady=(4, 8))
        add.grid_columnconfigure(1, weight=1)
        name_e = ctk.CTkEntry(add, width=180, placeholder_text=name_hint, fg_color=PANEL_2, border_color=BORDER)
        name_e.grid(row=0, column=0)
        target_e = ctk.CTkEntry(add, placeholder_text=target_hint, fg_color=PANEL_2, border_color=BORDER)
        target_e.grid(row=0, column=1, sticky="ew", padx=8)
        listing = ctk.CTkFrame(card, fg_color="transparent")
        listing.grid(row=3, column=0, columnspan=2, sticky="ew", padx=20, pady=(0, 14))
        listing.grid_columnconfigure(1, weight=1)

        def render():
            for w in listing.winfo_children():
                w.destroy()
            for i, (name, target) in enumerate(sorted(self._shortcut_items(kind).items())):
                ctk.CTkLabel(listing, text=name, text_color=TEXT, font=ctk.CTkFont(FONT, 13, "bold"),
                             width=170, anchor="w").grid(row=i, column=0, sticky="w", pady=2)
                ctk.CTkLabel(listing, text=target, text_color=MUTED, font=ctk.CTkFont(FONT, 12),
                             anchor="w").grid(row=i, column=1, sticky="w", padx=8)
                ctk.CTkButton(listing, text="✕", width=30, height=26, fg_color=PANEL_2,
                              hover_color="#7f1d1d", command=lambda n=name: remove(n)).grid(row=i, column=2)

        def add_item():
            name = name_e.get().strip().lower()
            target = target_e.get().strip()
            if not name or not target:
                return
            self._shortcut_items(kind)[name] = target
            self._save_shortcuts(kind)
            name_e.delete(0, "end")
            target_e.delete(0, "end")
            render()

        def remove(name):
            self._shortcut_items(kind).pop(name, None)
            self._save_shortcuts(kind)
            render()

        ctk.CTkButton(add, text="Add", width=70, fg_color=ACCENT_DARK, hover_color=ACCENT,
                      command=add_item).grid(row=0, column=2)
        target_e.bind("<Return>", lambda e: add_item())
        render()
        return listing

    # ------------------------------------------------------------------ #
    # Tray, mute, show/hide, quit
    # ------------------------------------------------------------------ #
    def _start_tray(self):
        try:
            import pystray
            menu = pystray.Menu(
                pystray.MenuItem("Open Mirage", lambda i, it: self.events.put(("show_window", None)), default=True),
                pystray.MenuItem("Mute microphone", lambda i, it: self.events.put(("toggle_mute", None)),
                                 checked=lambda it: self.engine.mic_muted),
                pystray.Menu.SEPARATOR,
                pystray.MenuItem("Quit Mirage", lambda i, it: self.events.put(("quit", None))),
            )
            self.tray = pystray.Icon("Mirage", make_icon_image(64), "Mirage", menu)
            self.tray.run_detached()
        except Exception as e:
            M.log(f"Tray icon unavailable: {e}")
            self.tray = None

    def toggle_mute(self):
        self.engine.set_muted(not self.engine.mic_muted)

    def _apply_muted(self, muted):
        self.mute_btn.configure(text="Unmute microphone" if muted else "Mute microphone",
                                fg_color="#7f1d1d" if muted else PANEL_2,
                                hover_color="#b91c1c" if muted else BORDER)
        if muted:
            self.mute_switch.select()
        else:
            self.mute_switch.deselect()
        if self.tray:
            try:
                self.tray.update_menu()
            except Exception:
                pass

    def show_window(self):
        self.deiconify()
        self.state("normal")
        self.lift()
        self.attributes("-topmost", True)
        self.after(200, lambda: self.attributes("-topmost", False))
        self.focus_force()

    def on_close(self):
        if self.engine.cfg.get("close_to_tray", True) and self.tray:
            self.withdraw()
            if not self._told_about_tray:
                self._told_about_tray = True
                try:
                    self.tray.notify("Mirage is still listening. Click the tray icon to open it again.",
                                     "Mirage")
                except Exception:
                    pass
        else:
            self.quit_app()

    def quit_app(self):
        try:
            self.engine.stop()
            if self.tray:
                self.tray.stop()
        finally:
            M.log("Mirage stopped.")
            try:
                self.destroy()
            finally:
                os._exit(0)

    # ------------------------------------------------------------------ #
    # Events from the engine (arrive on other threads -> queue)
    # ------------------------------------------------------------------ #
    def _poll_events(self):
        for _ in range(300):
            try:
                kind, data = self.events.get_nowait()
            except queue.Empty:
                break
            try:
                self._handle_event(kind, data)
            except Exception as e:
                M.log(f"UI event error ({kind}): {e}")
        self.after(50, self._poll_events)

    def _handle_event(self, kind, data):
        if kind == "status":
            self.status, self.status_detail = data
            color, text = STATUS_STYLE.get(self.status, ("#94a3b8", self.status))
            self.status_label.configure(text=text)
            self.detail_label.configure(text=self.status_detail,
                                        text_color=DANGER if self.status == "error" else MUTED)
            self.side_status.configure(text=text)
            self.side_dot.delete("all")
            self.side_dot.create_oval(2, 2, 11, 11, fill=color, outline="")
            self.hologram.set_status(self.status)
        elif kind == "level":
            self.level = data
            self.hologram.set_level(data)
            if self.current_page == "settings":
                self.level_bar.set(min(1.0, data * 4))
        elif kind == "heard":
            self.add_message("you", data)
        elif kind == "reply":
            self.add_message("mirage", data)
        elif kind == "system":
            self.add_message("system", data)
        elif kind == "update_checked":
            self._apply_update_check(*data)
        elif kind == "update_progress":
            self.update_status.configure(text=data, text_color=MUTED)
        elif kind == "update_done":
            self.update_status.configure(text="Updated! Restarting…", text_color="#34d399")
            self.after(800, self.restart)
        elif kind == "update_failed":
            self.update_btn.configure(state="normal", text="Try again")
            self.update_status.configure(text=f"Update failed: {data}", text_color=DANGER)
        elif kind == "vs_checked":
            self._apply_vs_check(data)
        elif kind == "muted":
            self._apply_muted(data)
        elif kind == "toggle_mute":
            self.toggle_mute()
        elif kind == "show_window":
            self.show_window()
        elif kind == "quit":
            self.quit_app()


def main():
    events: "queue.Queue" = queue.Queue()
    if "--enable-startup" in sys.argv:
        set_startup(True)
        print("Mirage will start with Windows.")
        return
    lock = M.acquire_instance(on_show=lambda: events.put(("show_window", None)))
    if lock is None and "--restarted" in sys.argv:
        for _ in range(40):  # the old copy is still closing; wait for it
            time.sleep(0.25)
            lock = M.acquire_instance(on_show=lambda: events.put(("show_window", None)))
            if lock:
                break
    if lock is None:
        M.log("Mirage is already running - showing its window.")
        return
    try:
        app = MirageApp(events, start_hidden="--tray" in sys.argv)
        app.mainloop()
    except Exception:
        err = traceback.format_exc()
        M.log("Fatal error:\n" + err)
        try:
            from tkinter import messagebox
            messagebox.showerror("Mirage crashed", err[-1500:])
        except Exception:
            pass
        raise
    finally:
        os._exit(0)


if __name__ == "__main__":
    main()
