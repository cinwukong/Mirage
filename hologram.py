"""
Mirage hologram: a small orb (or the purple headband) that pops up in a corner of the screen while
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
    "awaiting": "#e3b860",   # gold: listening for your command
    "thinking": "#e3b860",   # gold, with an arc going round
    "acting": "#ff9a76",     # coral: using your mouse and keyboard (Esc stops it)
    "speaking": "#b9a2f5",   # light purple
    "listening": "#b9a2f5",
    "loading": "#8f84a3",
    "muted": "#6f6680",
    "error": "#f07167",
}
PANEL = "#14101c"        # what the orb and the subtitles sit on (the app's dark ground)
LINE = "#2e2640"         # its edge
RING_IDLE = "#3a2f52"    # the orb's ring while nothing is happening
CORE = ("#3e2b78", "#8a6be3", "#d4c4ff")        # the orb: dark edge, purple, the light on its top left
CORE_OFF = ("#2a2633", "#4f485d", "#a49cb1")    # ... grey while the microphone is off
ACTIVE = ("awaiting", "thinking", "speaking", "acting")
BUSY = ("thinking", "acting")
SIZES = {"small": 150, "medium": 210, "large": 290}
LOGO_STEPS = 9  # pre-rendered logo sizes used for the "pulse" (resizing every frame is too slow)


def _mix(c1, c2, f):
    a = [int(c1[i:i + 2], 16) for i in (1, 3, 5)]
    b = [int(c2[i:i + 2], 16) for i in (1, 3, 5)]
    return "#" + "".join(f"{round(x + (y - x) * f):02x}" for x, y in zip(a, b))


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
        self.sub_who, self.sub_until = "mirage", 0.0
        self.captions = None     # captions.Captions, made in _place (it needs the font and the box width)
        self.scaling = 1.0
        self.motion = True       # False when Windows' animation effects are off: then nothing moves
        self.cap_h = 0
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
        self.canvas.pack(side="top", fill="x")
        # the subtitles get their own strip under the animation, so lines scrolling out of it are cut off cleanly
        self.cap = tk.Canvas(w, bg=KEY, highlightthickness=0, bd=0)
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
        self.motion = animations_on()
        size = int(SIZES.get(cfg.get("hologram_size", "medium"), 210) * scaling)
        if self._use_logo():
            art_w, art_h = int(size * 1.55), int(size * 0.95)
        else:
            art_w = art_h = size
        w, h = art_w, art_h
        cap_h = 0
        if cfg.get("subtitles_enabled", True):
            import tkinter.font as tkfont
            from captions import Captions, ROWS
            w = max(art_w, int(440 * scaling))
            self.cap_font = tkfont.Font(root=self.root, family="Segoe UI" if sys.platform.startswith("win") else "Helvetica",
                                        size=int(12 * scaling) or 12, weight="bold")
            self.line_h = self.cap_font.metrics("linespace") + 1
            cap_h = ROWS * self.line_h + int(16 * scaling)
            width = w - int(24 * scaling)
            if self.captions is None or self.captions.width != width:
                self.captions = Captions(self.cap_font.measure, width)
            h = art_h + cap_h
        margin = int(24 * scaling)
        taskbar = int(56 * scaling)
        sw, sh = self.win.winfo_screenwidth(), self.win.winfo_screenheight()
        corner = cfg.get("hologram_corner", "bottom-right")
        x = margin if "left" in corner else sw - w - margin
        y = margin if "top" in corner else sh - h - margin - taskbar
        self.win.geometry(f"{w}x{h}+{x}+{y}")
        self.canvas.config(width=w, height=art_h)
        if cap_h:
            self.cap.config(width=w, height=cap_h)
            self.cap.pack(side="top", fill="x")
        else:
            self.cap.pack_forget()
        self.size, self.w, self.h = size, art_w, art_h   # w/h = the animated part
        self.cap_h = cap_h
        self.win_w, self.win_h = w, h
        self.ox = (w - art_w) / 2                          # centre the animation horizontally

    def _use_logo(self):
        return self._logo_src is not None and self.get_cfg().get("hologram_style", "orb") == "logo"

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

    def set_subtitle(self, text, who="mirage", voiced=None):
        """Show text under the hologram: a reply follows Mirage's voice sentence by sentence (or goes at reading pace
        when replies are subtitles only), scrolling so nothing is cut off. voiced=False: text Mirage doesn't say."""
        cfg = self.get_cfg()
        if not cfg.get("hologram_enabled", True) or not cfg.get("subtitles_enabled", True) or not text:
            return
        if not self.visible:
            self._show()
        if self.captions is None:  # blocked (full screen) or not placed yet
            return
        if voiced is None:
            voiced = who == "mirage" and cfg.get("speak_replies", True)
        self.sub_who = who
        self.captions.show(text, who, follow_voice=voiced, wpm=0.9 * float(cfg.get("voice_rate", 185) or 185),
                           now=time.time())
        self._keep_for_caption()

    def caption_stop(self):
        """You talked over Mirage: the subtitle stops where the voice did and goes away soon."""
        if self.captions:
            self.captions.stop(now=time.time())
            self.sub_until = self.captions.done_at
            if self.hide_at is not None:
                self.hide_at = min(self.hide_at, self.sub_until)

    def caption_spoken(self, text, index):
        if self.captions:
            self.captions.spoken(text, index, now=time.time())
            self._keep_for_caption()

    def caption_started(self, text):
        if self.captions:
            self.captions.started(text, now=time.time())
            self._keep_for_caption()

    def _keep_for_caption(self):
        """Stay up until the caption has been said and read."""
        self.sub_until = self.captions.done_at
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
        if self.get_cfg().get("subtitles_enabled", True) and self.captions:
            self.sub_who = "mirage"
            self.captions.show("This is how my subtitles look.", now=time.time())
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
        if self.captions:
            self.captions.clear()
            self.cap.delete("all")
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
                    if self.captions and self.captions.tick(now):
                        self._draw_caption()
        except tk.TclError:
            return
        self.root.after(33, self._tick)

    def _level(self, t):
        target = 0.0
        if self.status == "awaiting":
            target = min(1.0, self.level * 5)
        elif self.status == "speaking":
            target = 0.45 + 0.35 * abs(math.sin(t * 9)) * abs(math.sin(t * 3.7)) if self.motion else 0.5
        elif self.status in BUSY:
            target = 0.15
        self.smooth = self.smooth * 0.7 + target * 0.3
        return self.smooth

    def _draw_logo(self, t, scale):
        """The purple headband (Mirage's logo), and a small voice meter under it. Still while nothing happens."""
        c = self.canvas
        c.delete("all")
        W, H = self.w, self.h
        cx, cy = self.ox + W / 2, H * 0.42
        lv = self._level(t)
        step = max(0, min(LOGO_STEPS - 1, int(round(lv * (LOGO_STEPS - 1))))) if self.motion else 0  # swells with the voice
        img = self._logo_frame(int(W * 0.74 * scale), step)
        c.create_image(cx, cy, image=img)
        self._draw_meter(c, cx, H * 0.88, W * 0.22 * scale, t, lv)

    def _draw_meter(self, c, cx, cy, span, t, lv):
        """Seven short bars: flat dots while idle, your voice or Mirage's while listening or speaking,
        a slow wave while it thinks or uses your PC."""
        color = COLORS.get(self.status, COLORS["listening"])
        bars, bw = 7, max(3, int(self.size * 0.022))
        for i in range(bars):
            x = cx - span / 2 + span * i / (bars - 1)
            edge = 1 - abs(i - (bars - 1) / 2) / ((bars - 1) / 2)  # taller in the middle
            if self.status in BUSY and self.motion:
                h = self.size * (0.012 + 0.03 * (0.5 + 0.5 * math.sin(t * 5 - i * 0.9)))
            elif self.status in ("awaiting", "speaking"):
                if self.motion:
                    wob = 0.6 + 0.4 * math.sin(t * 8 + i * 1.3)
                    h = self.size * (0.012 + 0.07 * lv * wob * (0.4 + 0.6 * edge))
                else:  # animations off: a still meter, just lit up
                    h = self.size * (0.012 + 0.03 * edge)
            else:
                h = 0
            fill = color if self.status in ACTIVE else RING_IDLE
            c.create_line(x, cy - h, x, cy + h, fill=fill, width=bw, capstyle="round")

    def _draw_caption(self):
        """The subtitle strip on a dark panel: the lines that have started, scrolled; the piece being said bright,
        older ones faded, a line leaving the top fades out. Redrawn only when it changes."""
        c = self.cap
        c.delete("all")
        if not self.captions:
            return
        lines = list(self.captions.lines())
        if not lines:
            return
        sc, lh = self.scaling, self.line_h
        x, top, inset = self.win_w / 2, int(8 * sc), int(4 * sc)
        rows = max([pos for pos, _, _ in lines if pos >= 0] or [0]) + 1  # the panel is as tall as the lines on it
        _round_rect(c, inset, 1, self.win_w - inset, min(self.cap_h - 1, 2 * top + rows * lh), int(12 * sc),
                    fill=PANEL, outline=LINE)
        full = "#cfc6dd" if self.sub_who == "you" else "#efe9f7"
        for pos, line, bright in lines:
            fade = bright * (min(1.0, 1.0 + pos) if pos < 0 else 1.0)  # leaving the top: fade it out
            if fade <= 0.05:
                continue
            c.create_text(x, top + pos * lh, text=line, anchor="n", font=self.cap_font, fill=_mix(PANEL, full, fade))

    def _draw(self, t, scale):
        """The orb, the same as on the app's Home page: a ring and a purple core on a dark disc.
        Still while idle; the ring follows your voice while it listens, an arc goes round while it thinks,
        and the core breathes while it speaks."""
        c = self.canvas
        c.delete("all")
        s = self.size
        cx, cy = self.ox + s / 2, s / 2
        R = s * 0.44 * scale
        st = self.status
        lv = self._level(t)
        c.create_oval(cx - R, cy - R, cx + R, cy + R, fill=PANEL, outline=LINE, width=1)

        width = max(2, int(s * 0.014))
        rr = R * 0.74 * (1 + 0.12 * lv if st == "awaiting" and self.motion else 1)
        ring = {"awaiting": COLORS["awaiting"], "speaking": COLORS["speaking"], "error": COLORS["error"]}.get(st, RING_IDLE)
        c.create_oval(cx - rr, cy - rr, cx + rr, cy + rr, outline=ring, width=width)
        if st in BUSY:
            start = (-t * 330) % 360 if self.motion else 90
            c.create_arc(cx - rr, cy - rr, cx + rr, cy + rr, start=start, extent=90, style="arc",
                         outline=COLORS[st], width=width + 1)

        k = 1 + (0.1 * lv if st == "speaking" and self.motion else 0)
        edge, body, light = CORE_OFF if st == "muted" else CORE
        r = R * 0.40 * k
        c.create_oval(cx - r, cy - r, cx + r, cy + r, fill=edge, outline="")
        r2, off = r * 0.80, r * 0.10
        c.create_oval(cx - r2 - off, cy - r2 - off, cx + r2 - off, cy + r2 - off, fill=body, outline="")
        r3, off3 = r * 0.30, r * 0.32
        c.create_oval(cx - r3 - off3, cy - r3 - off3, cx + r3 - off3, cy + r3 - off3, fill=light, outline="")


def _round_rect(c, x1, y1, x2, y2, r, **kw):
    """A rounded rectangle on a Tk canvas (a smoothed polygon)."""
    pts = [x1 + r, y1, x2 - r, y1, x2, y1, x2, y1 + r, x2, y2 - r, x2, y2, x2 - r, y2, x1 + r, y2,
           x1, y2, x1, y2 - r, x1, y1 + r, x1, y1]
    return c.create_polygon(pts, smooth=True, **kw)


def animations_on():
    """Windows' "Animation effects" setting (Settings, Accessibility, Visual effects). Off: the hologram stays still."""
    if not sys.platform.startswith("win"):
        return True
    try:
        import ctypes
        on = ctypes.c_int(1)
        SPI_GETCLIENTAREAANIMATION = 0x1042
        if ctypes.windll.user32.SystemParametersInfoW(SPI_GETCLIENTAREAANIMATION, 0, ctypes.byref(on), 0):
            return bool(on.value)
    except Exception:
        pass
    return True


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
