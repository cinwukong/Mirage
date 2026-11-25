"""
Mirage hologram: a small animated "reactor" that pops up in a corner of the screen while
Mirage is listening, thinking or speaking. The window has no frame, stays on top, has a
see-through background and lets mouse clicks pass through it.
"""

import math
import sys
import time
import tkinter as tk

KEY = "#010203"  # this exact colour becomes fully transparent on Windows

COLORS = {
    "awaiting": "#34d399",
    "thinking": "#a78bfa",
    "speaking": "#22d3ee",
    "listening": "#22d3ee",
    "loading": "#94a3b8",
    "muted": "#64748b",
    "error": "#f87171",
}
ACTIVE = ("awaiting", "thinking", "speaking")
SIZES = {"small": 150, "medium": 210, "large": 290}


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
        self.win = None
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
        size = int(SIZES.get(cfg.get("hologram_size", "medium"), 210) * scaling)
        margin = int(24 * scaling)
        taskbar = int(56 * scaling)
        sw, sh = self.win.winfo_screenwidth(), self.win.winfo_screenheight()
        corner = cfg.get("hologram_corner", "bottom-right")
        x = margin if "left" in corner else sw - size - margin
        y = margin if "top" in corner else sh - size - margin - taskbar
        self.win.geometry(f"{size}x{size}+{x}+{y}")
        self.size = size

    # ---------------------------------------------------------------- state
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
            self.hide_at = time.time() + 1.2  # linger a moment, then fade out

    def set_level(self, level):
        self.level = level

    def preview(self, seconds=3.0):
        """Show briefly (used by the settings page)."""
        self._place()
        self._show()
        self.hide_at = time.time() + seconds

    def _show(self):
        self._place()
        self.visible = True
        self.appear_t = time.time()
        self.win.deiconify()
        self.win.lift()
        self._make_click_through()

    def _hide_now(self):
        self.visible = False
        self.hide_at = None
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
                    self._draw(now, (0.55 + 0.45 * pop) * (0.85 + 0.15 * fade))
        except tk.TclError:
            return
        self.root.after(33, self._tick)

    def _draw(self, t, scale):
        c = self.canvas
        c.delete("all")
        s = self.size
        cx = cy = s / 2
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
        speed = 3.0 if self.status == "thinking" else 1.0
        r = R * 0.86
        for i in range(3):
            c.create_arc(cx - r, cy - r, cx + r, cy + r, start=(t * 40 * speed + i * 120) % 360,
                         extent=70, style="arc", outline=color, width=max(2, int(s * 0.018)))
        r = R * 0.74
        for i in range(4):
            c.create_arc(cx - r, cy - r, cx + r, cy + r, start=(-t * 65 * speed + i * 90) % 360,
                         extent=38, style="arc", outline=bright, width=max(1, int(s * 0.010)))

        # thinking: fast scanning arc
        if self.status == "thinking":
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
