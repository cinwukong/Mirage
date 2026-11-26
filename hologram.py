"""
Mirage hologram: a small animated "reactor" that pops up in a corner of the screen while
Mirage is listening, thinking or speaking. The window has no frame, stays on top, has a
see-through background and lets mouse clicks pass through it.
"""

import math
import queue
import sys
import threading
import time
import tkinter as tk
from pathlib import Path

LOGO_PATH = Path(__file__).resolve().parent / "assets" / "logo.png"

KEY = "#010203"  # this exact colour becomes fully transparent on Windows

COLORS = {
    "awaiting": "#f2d17e",   # gold: listening for your command
    "thinking": "#d9a93f",   # deep gold, spinning faster
    "acting": "#ff9a76",     # coral: using your mouse and keyboard (Esc stops it)
    "speaking": "#c9b2ff",   # lavender
    "listening": "#b794ff",
    "loading": "#9d8db5",
    "muted": "#6b5a80",
    "error": "#e2574c",
}
ACTIVE = ("awaiting", "thinking", "speaking", "acting")
BUSY = ("thinking", "acting")
SIZES = {"small": 150, "medium": 210, "large": 290}
LOGO_STEPS = 9  # pre-rendered logo sizes used for the "pulse" (resizing every frame is too slow)


def _mix(c1, c2, f):
    a = [int(c1[i:i + 2], 16) for i in (1, 3, 5)]
    b = [int(c2[i:i + 2], 16) for i in (1, 3, 5)]
    return "#" + "".join(f"{round(x + (y - x) * f):02x}" for x, y in zip(a, b))


def _dim(c, f):
    """Darker version of a colour, but never so dark it reads as a black ring."""
    return _mix(c, "#0b1020", f)


class Hologram:
    def __init__(self, root, get_cfg):
        self.root = root
        self.get_cfg = get_cfg
        self.status = "listening"
        self.level = 0.0
        self.smooth = 0.0
        self.visible = False
        self.appear_t = 0.0
        self.hide_at = None
        self.scale = 1.0
        self.sub_text, self.sub_who, self.sub_until = "", "mirage", 0.0
        self.scaling = 1.0
        self.win = None
        self._logo_src = None
        self._logo_frames = {}   # (size, step) -> PhotoImage
        try:
            from PIL import Image
            self._logo_src = Image.open(LOGO_PATH).convert("RGBA")
            # Hard edges: half-transparent edge pixels would show as a dark fringe on the
            # see-through background, so make every pixel either fully solid or fully clear.
            a = self._logo_src.getchannel("A").point(lambda v: 255 if v >= 110 else 0)
            self._logo_src.putalpha(a)
        except Exception:
            self._logo_src = None
        self._build()
        self._tick()

    # ---------------------------------------------------------------- window
    def _build(self):
        w = tk.Toplevel(self.root)
        w.withdraw()
        w.overrideredirect(True)
        w.configure(bg=KEY)
        try:
            w.attributes("-topmost", True)
        except tk.TclError:
            pass
        if sys.platform.startswith("win"):
            try:
                w.attributes("-transparentcolor", KEY)
                w.attributes("-alpha", 0.93)
            except tk.TclError:
                pass
        self.canvas = tk.Canvas(w, bg=KEY, highlightthickness=0, bd=0)
        self.canvas.pack(fill="both", expand=True)
        self.win = w
        self._click_through_done = False

    def _make_click_through(self):
        """Windows only: let clicks go to whatever is under the hologram, and never take focus."""
        if self._click_through_done or not sys.platform.startswith("win"):
            return
        try:
            import ctypes
            user32 = ctypes.windll.user32
            hwnd = user32.GetParent(self.win.winfo_id()) or self.win.winfo_id()
            GWL_EXSTYLE = -20
            WS_EX_LAYERED, WS_EX_TRANSPARENT = 0x00080000, 0x00000020
            WS_EX_TOOLWINDOW, WS_EX_NOACTIVATE = 0x00000080, 0x08000000
            style = user32.GetWindowLongW(hwnd, GWL_EXSTYLE)
            user32.SetWindowLongW(hwnd, GWL_EXSTYLE, style | WS_EX_LAYERED | WS_EX_TRANSPARENT
                                  | WS_EX_TOOLWINDOW | WS_EX_NOACTIVATE)
            self._click_through_done = True
        except Exception:
            pass

    def _place(self):
        cfg = self.get_cfg()
        try:
            scaling = float(self.root.tk.call("tk", "scaling")) / 1.333
        except Exception:
            scaling = 1.0
        scaling = max(1.0, scaling)
        self.scaling = scaling
        size = int(SIZES.get(cfg.get("hologram_size", "medium"), 210) * scaling)
        if self._use_logo():
            art_w, art_h = int(size * 1.55), int(size * 0.95)
        else:
            art_w = art_h = size
        w, h = art_w, art_h
        if cfg.get("subtitles_enabled", True):
            w = max(art_w, int(440 * scaling))
            h = art_h + int(78 * scaling)
        margin = int(24 * scaling)
        taskbar = int(56 * scaling)
        sw, sh = self.win.winfo_screenwidth(), self.win.winfo_screenheight()
        corner = cfg.get("hologram_corner", "bottom-right")
        x = margin if "left" in corner else sw - w - margin
        y = margin if "top" in corner else sh - h - margin - taskbar
        self.win.geometry(f"{w}x{h}+{x}+{y}")
        self.size, self.w, self.h = size, art_w, art_h   # w/h = the animated part
        self.win_w, self.win_h = w, h
        self.ox = (w - art_w) / 2                          # centre the animation horizontally

    def _use_logo(self):
        return self._logo_src is not None and self.get_cfg().get("hologram_style", "logo") == "logo"

    def _logo_frame(self, width, step):
        key = (width, step)
        img = self._logo_frames.get(key)
        if img is None:
            from PIL import Image, ImageTk
            f = 0.92 + 0.16 * step / (LOGO_STEPS - 1)
            w = max(8, int(width * f))
            h = max(4, int(w * self._logo_src.height / self._logo_src.width))
            img = ImageTk.PhotoImage(self._logo_src.resize((w, h), Image.LANCZOS), master=self.root)
            if len(self._logo_frames) > 40:
                self._logo_frames.clear()
            self._logo_frames[key] = img
        return img

    # ---------------------------------------------------------------- state
    def set_blocked(self, blocked):
        """Something runs full screen: stay hidden (a window popping up can knock a game out of full screen)."""
        self.blocked = bool(blocked)
        if self.blocked:
            self._hide_now()

    def set_status(self, status):
        self.status = status
        if not self.get_cfg().get("hologram_enabled", True):
            self._hide_now()
            return
        if status in ACTIVE:
            self.hide_at = None
            if not self.visible:
                self._show()
        elif self.visible and self.hide_at is None:
            # linger a moment (longer if a subtitle is still being read), then fade out
            self.hide_at = max(time.time() + 1.2, self.sub_until)

    def set_subtitle(self, text, who="mirage"):
        """Show a line of text under the hologram for long enough to read it."""
        cfg = self.get_cfg()
        if not cfg.get("hologram_enabled", True) or not cfg.get("subtitles_enabled", True) or not text:
            return
        now = time.time()
        read = 1.8 + 0.055 * len(text) if who == "mirage" else 1.2 + 0.03 * len(text)
        self.sub_text, self.sub_who = text, who
        self.sub_until = now + min(14.0, read)
        if not self.visible:
            self._show()
        if self.status not in ACTIVE:
            self.hide_at = self.sub_until
        elif self.hide_at is not None:
            self.hide_at = max(self.hide_at, self.sub_until)

    def set_level(self, level):
        self.level = level

    def preview(self, seconds=3.0):
        """Show briefly (used by the settings page)."""
        self._hide_now()
        self._show()
        if self.get_cfg().get("subtitles_enabled", True):
            self.sub_text, self.sub_who = "This is how my subtitles look.", "mirage"
            self.sub_until = time.time() + seconds
        self.hide_at = time.time() + seconds

    def _show(self):
        if self.visible or getattr(self, "blocked", False):
            return
        self._place()
        self.visible = True
        self.appear_t = time.time()
        self.win.deiconify()
        self.win.lift()
        self._make_click_through()

    def _hide_now(self):
        self.visible = False
        self.hide_at = None
        self.sub_text = ""
        if self.win is not None:
            self.win.withdraw()

    # ---------------------------------------------------------------- drawing
    def _tick(self):
        try:
            if self.visible:
                now = time.time()
                fade = 1.0
                if self.hide_at is not None:
                    left = self.hide_at - now
                    if left <= 0:
                        self._hide_now()
                    else:
                        fade = min(1.0, left / 0.35)
                if self.visible:
                    pop = min(1.0, (now - self.appear_t) / 0.22)
                    pop = 1 - (1 - pop) ** 3  # ease-out
                    if sys.platform.startswith("win"):
                        try:
                            self.win.attributes("-alpha", 0.93 * fade)
                        except tk.TclError:
                            pass
                    k = (0.55 + 0.45 * pop) * (0.85 + 0.15 * fade)
                    if self._use_logo():
                        self._draw_logo(now, k)
                    else:
                        self._draw(now, k)
                    self._draw_subtitle(now)
        except tk.TclError:
            return
        self.root.after(33, self._tick)

    def _level(self, t):
        target = 0.0
        if self.status == "awaiting":
            target = min(1.0, self.level * 5)
        elif self.status == "speaking":
            target = 0.45 + 0.35 * abs(math.sin(t * 9)) * abs(math.sin(t * 3.7))
        elif self.status in BUSY:
            target = 0.15
        self.smooth = self.smooth * 0.7 + target * 0.3
        return self.smooth

    def _draw_logo(self, t, scale):
        """The purple headband in the middle, elliptical rings around it, a voice wave under it."""
        c = self.canvas
        c.delete("all")
        W, H = self.w, self.h
        cx, cy = self.ox + W / 2, H * 0.43
        color = COLORS.get(self.status, COLORS["listening"])
        bright = _mix(color, "#ffffff", 0.45)
        dim = _dim(color, 0.45)
        lv = self._level(t)
        speed = 3.0 if self.status in BUSY else 1.0

        # elliptical rings of rotating arc segments, wider than the headband
        for k, n, ext, direction, col, width in ((1.00, 3, 55, 1, color, 2), (0.90, 4, 30, -1, bright, 1)):
            rx, ry = W * 0.46 * k * scale, H * 0.36 * k * scale
            for i in range(n):
                start = (direction * t * 45 * speed + i * 360 / n) % 360
                c.create_arc(cx - rx, cy - ry, cx + rx, cy + ry, start=start, extent=ext,
                             style="arc", outline=col, width=max(width, int(self.size * 0.012 * width)))
        rx, ry = W * 0.43 * scale, H * 0.33 * scale
        c.create_oval(cx - rx, cy - ry, cx + rx, cy + ry, outline=dim, width=1)
        if self.status in BUSY:
            rx, ry = W * 0.39 * scale, H * 0.30 * scale
            c.create_arc(cx - rx, cy - ry, cx + rx, cy + ry, start=(t * 380) % 360, extent=45,
                         style="arc", outline=bright, width=max(2, int(self.size * 0.018)))

        # the logo, pulsing with the voice
        step = max(0, min(LOGO_STEPS - 1, int(round(lv * (LOGO_STEPS - 1)))))
        breathe = 1 + 0.02 * math.sin(t * 2.4)
        img = self._logo_frame(int(W * 0.66 * scale * breathe), step)
        c.create_image(cx, cy, image=img)

        # voice wave under the logo
        bars = 25
        base_y = H * 0.90
        span = W * 0.56 * scale
        bw = max(2, int(span / bars * 0.45))
        for i in range(bars):
            x = cx - span / 2 + span * i / (bars - 1)
            edge = 1 - abs(i - (bars - 1) / 2) / ((bars - 1) / 2)  # taller in the middle
            wob = 0.5 + 0.5 * math.sin(t * 8 + i * 0.9)
            h = H * (0.015 + 0.11 * lv * wob * (0.35 + 0.65 * edge))
            c.create_line(x, base_y - h, x, base_y + h, fill=color, width=bw, capstyle="round")

    def _draw_subtitle(self, t):
        if not self.sub_text or t > self.sub_until + 0.5:
            return
        c = self.canvas
        sc = self.scaling
        font = ("Segoe UI" if sys.platform.startswith("win") else "Helvetica", int(12 * sc) or 12, "bold")
        text = self.sub_text if len(self.sub_text) <= 220 else self.sub_text[:217] + "…"
        if self.sub_who == "you":
            text, fill = "You: " + text, "#cbd5e1"
        else:
            fill = "#f3e8ff"
        x, y = self.win_w / 2, self.h + 4 * sc
        width = self.win_w - 24 * sc
        # dark outline so the text is readable on any background
        for dx, dy in ((-2, 0), (2, 0), (0, -2), (0, 2), (-1, -1), (1, 1), (-1, 1), (1, -1)):
            c.create_text(x + dx, y + dy, text=text, width=width, anchor="n", justify="center",
                          font=font, fill="#0b0b14")
        c.create_text(x, y, text=text, width=width, anchor="n", justify="center", font=font, fill=fill)

    def _draw(self, t, scale):
        c = self.canvas
        c.delete("all")
        s = self.size
        cx, cy = self.ox + s / 2, s / 2
        R = s * 0.40 * scale
        color = COLORS.get(self.status, COLORS["listening"])
        bright = _mix(color, "#ffffff", 0.45)
        dim = _dim(color, 0.45)
        dimmer = _dim(color, 0.65)

        target = 0.0
        if self.status == "awaiting":
            target = min(1.0, self.level * 5)
        elif self.status == "speaking":
            target = 0.45 + 0.35 * abs(math.sin(t * 9)) * abs(math.sin(t * 3.7))
        self.smooth = self.smooth * 0.7 + target * 0.3
        lv = self.smooth

        # outer tick ring (slowly rotating)
        rot = t * 12
        for i in range(72):
            a = math.radians(i * 5 + rot)
            long = i % 6 == 0
            r1 = R * (1.02 if long else 1.04)
            r2 = R * 1.10
            c.create_line(cx + r1 * math.cos(a), cy + r1 * math.sin(a),
                          cx + r2 * math.cos(a), cy + r2 * math.sin(a),
                          fill=color if long else dim, width=2 if long else 1)

        # thin full circles
        for k, col in ((0.96, dim), (0.62, dimmer)):
            r = R * k
            c.create_oval(cx - r, cy - r, cx + r, cy + r, outline=col, width=1)

        # rotating arc segments, two rings in opposite directions
        speed = 3.0 if self.status in BUSY else 1.0
        r = R * 0.86
        for i in range(3):
            c.create_arc(cx - r, cy - r, cx + r, cy + r, start=(t * 40 * speed + i * 120) % 360,
                         extent=70, style="arc", outline=color, width=max(2, int(s * 0.018)))
        r = R * 0.74
        for i in range(4):
            c.create_arc(cx - r, cy - r, cx + r, cy + r, start=(-t * 65 * speed + i * 90) % 360,
                         extent=38, style="arc", outline=bright, width=max(1, int(s * 0.010)))

        # thinking: fast scanning arc
        if self.status in BUSY:
            r = R * 0.66
            c.create_arc(cx - r, cy - r, cx + r, cy + r, start=(t * 420) % 360, extent=50,
                         style="arc", outline=bright, width=max(2, int(s * 0.02)))

        # level bars around the core (voice / mic activity)
        core = R * (0.34 + 0.08 * lv)
        bars = 36
        for i in range(bars):
            a = math.radians(i * 360 / bars - t * 20)
            wobble = 0.5 + 0.5 * math.sin(t * 7 + i * 1.7)
            h = R * (0.03 + 0.17 * lv * wobble)
            r1, r2 = core * 1.12, core * 1.12 + h
            c.create_line(cx + r1 * math.cos(a), cy + r1 * math.sin(a),
                          cx + r2 * math.cos(a), cy + r2 * math.sin(a),
                          fill=color, width=max(1, int(s * 0.012)))

        # core
        pulse = 1 + 0.04 * math.sin(t * 3)
        r = core * pulse
        c.create_oval(cx - r, cy - r, cx + r, cy + r, outline=bright, width=2, fill=dim)
        r2 = r * 0.72
        c.create_oval(cx - r2, cy - r2, cx + r2, cy + r2, outline="", fill=color)
        r3 = r * 0.30
        c.create_oval(cx - r3 - r * 0.18, cy - r3 - r * 0.2, cx + r3 - r * 0.18, cy + r3 - r * 0.2,
                      outline="", fill=_mix(color, "#ffffff", 0.75))


class HologramThread:
    """Runs the hologram in its own thread with its own Tk, so it works next to any main window.
    Call methods by name: holo.call("set_status", "thinking")."""

    def __init__(self, get_cfg):
        self.get_cfg = get_cfg
        self.q = queue.Queue()
        self.ready = threading.Event()
        threading.Thread(target=self._run, daemon=True, name="mirage-hologram").start()

    def _run(self):
        try:
            root = tk.Tk()
            root.withdraw()
            holo = Hologram(root, self.get_cfg)
        except Exception as e:
            print(f"Hologram unavailable: {e}")
            return
        self.ready.set()

        def pump():
            for _ in range(200):
                try:
                    fn, args = self.q.get_nowait()
                except queue.Empty:
                    break
                try:
                    getattr(holo, fn)(*args)
                except Exception as e:
                    print(f"Hologram {fn} failed: {e}")
            root.after(30, pump)

        pump()
        root.mainloop()

    def call(self, fn, *args):
        self.q.put((fn, args))
