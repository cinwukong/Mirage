"""
Spotify control for Mirage, no Spotify account linking needed.

- Play, pause, next and previous use the media keys, but Mirage first checks whether Spotify is
  playing (its window title is the song while playing and just "Spotify ..." while paused), so
  "stop the music" never starts it again by accident.
- Playlists you save on the Shortcuts page open in the Spotify app, and Mirage presses the big
  green play button on the playlist page for you.
"""

import os
import re
import sys
import time
import urllib.parse

WIN = sys.platform.startswith("win")
GREEN = (30, 215, 96)  # Spotify's play button


def to_uri(link: str) -> str:
    """open.spotify.com links -> spotify:playlist:ID (also albums, artists, tracks)."""
    link = (link or "").strip()
    m = re.search(r"open\.spotify\.com/(?:intl-\w+/)?(playlist|album|artist|track|show|episode)/([A-Za-z0-9]+)", link)
    if m:
        return f"spotify:{m.group(1)}:{m.group(2)}"
    if link.startswith("spotify:"):
        return link
    return ""


# --------------------------------------------------------------------------- #
# Finding Spotify's window (Windows)
# --------------------------------------------------------------------------- #
def _user32():
    import ctypes
    u = ctypes.windll.user32
    try:
        u.SetThreadDpiAwarenessContext(ctypes.c_void_p(-4))  # real pixels, so clicks land where we look
    except Exception:
        pass
    return u


def _spotify_window():
    """(hwnd, title) of Spotify's main window, or (None, None)."""
    if not WIN:
        return None, None
    import ctypes
    from ctypes import wintypes
    u = _user32()
    k = ctypes.windll.kernel32
    found = []

    @ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.HWND, wintypes.LPARAM)
    def each(hwnd, _):
        if not u.IsWindowVisible(hwnd):
            return True
        n = u.GetWindowTextLengthW(hwnd)
        if n <= 0:
            return True
        buf = ctypes.create_unicode_buffer(n + 1)
        u.GetWindowTextW(hwnd, buf, n + 1)
        pid = wintypes.DWORD()
        u.GetWindowThreadProcessId(hwnd, ctypes.byref(pid))
        h = k.OpenProcess(0x1000, False, pid.value)
        if h:
            path = ctypes.create_unicode_buffer(520)
            size = wintypes.DWORD(520)
            if k.QueryFullProcessImageNameW(h, 0, path, ctypes.byref(size)):
                if os.path.basename(path.value).lower() == "spotify.exe":
                    found.append((hwnd, buf.value))
            k.CloseHandle(h)
        return True

    u.EnumWindows(each, 0)
    return found[0] if found else (None, None)


def running() -> bool:
    return _spotify_window()[0] is not None


def playing():
    """True/False, or None if Spotify isn't open (or this isn't Windows)."""
    hwnd, title = _spotify_window()
    if hwnd is None:
        return None
    return not title.lower().startswith("spotify")


def now_playing() -> str:
    hwnd, title = _spotify_window()
    return title if hwnd is not None and not title.lower().startswith("spotify") else ""


def _wait_until(test, seconds):
    end = time.time() + seconds
    while time.time() < end:
        if test():
            return True
        time.sleep(0.3)
    return test()


# --------------------------------------------------------------------------- #
# Pressing the green play button on the page that's open
# --------------------------------------------------------------------------- #
def _find_play_button(hwnd):
    """Screen position of the big green play button in Spotify's window, or None."""
    import ctypes
    from ctypes import wintypes
    from PIL import ImageGrab
    u = _user32()
    r = wintypes.RECT()
    u.GetWindowRect(hwnd, ctypes.byref(r))
    w, h = r.right - r.left, r.bottom - r.top
    if w < 300 or h < 300:
        return None
    # the main page only: skip the library on the left, the side panel on the right and the player at the bottom
    box = (r.left + int(w * 0.22), r.top + 60, r.right - int(w * 0.22), r.bottom - int(h * 0.16))
    spot = locate_button(ImageGrab.grab(bbox=box, all_screens=True))
    return (box[0] + spot[0], box[1] + spot[1]) if spot else None


def locate_button(img):
    """Where the round green play button is in a picture of Spotify's page, or None.
    Looks for green shapes that are round and button-sized (album art is bigger and square)."""
    img = img.convert("RGB")
    step = 2
    small = img.resize((img.width // step, img.height // step))
    w, h = small.size
    data = small.load()
    mask = bytearray(w * h)
    for y in range(h):
        for x in range(w):
            r, g, b = data[x, y]
            if abs(r - GREEN[0]) < 45 and abs(g - GREEN[1]) < 45 and abs(b - GREEN[2]) < 45:
                mask[y * w + x] = 1
    best = None
    seen = bytearray(w * h)
    for start in range(w * h):
        if not mask[start] or seen[start]:
            continue
        stack, seen[start] = [start], 1
        n, x0, y0, x1, y1 = 0, w, h, 0, 0
        while stack:
            i = stack.pop()
            n += 1
            x, y = i % w, i // w
            x0, y0, x1, y1 = min(x0, x), min(y0, y), max(x1, x), max(y1, y)
            for j in (i - 1, i + 1, i - w, i + w):
                if 0 <= j < w * h and mask[j] and not seen[j] and abs(j % w - x) <= 1:
                    seen[j] = 1
                    stack.append(j)
        bw, bh = (x1 - x0 + 1) * step, (y1 - y0 + 1) * step
        fill = n / ((x1 - x0 + 1) * (y1 - y0 + 1))
        # a round button 30-130 pixels across: about as tall as wide, filled like a circle (not a square)
        if 30 <= bw <= 130 and 30 <= bh <= 130 and abs(bw - bh) <= 0.2 * max(bw, bh) and 0.5 <= fill <= 0.86:
            if best is None or n > best[0]:
                best = (n, (x0 + x1 + 1) * step // 2, (y0 + y1 + 1) * step // 2)
    return best[1:] if best else None


def _click(x, y):
    import ctypes
    from ctypes import wintypes
    u = _user32()
    old = wintypes.POINT()
    u.GetCursorPos(ctypes.byref(old))
    u.SetCursorPos(int(x), int(y))
    u.mouse_event(0x0002, 0, 0, 0, 0)  # left down
    u.mouse_event(0x0004, 0, 0, 0, 0)  # left up
    time.sleep(0.05)
    u.SetCursorPos(old.x, old.y)


def open_and_play(uri: str) -> str:
    """Open a playlist/album/etc. in the Spotify app and start it. Returns what Mirage should say."""
    if not WIN:
        import webbrowser
        webbrowser.open("https://open.spotify.com/" + "/".join(uri.split(":")[1:3]))
        return "Opened it in Spotify."
    os.startfile(uri)
    if not _wait_until(running, 15):
        return "Spotify didn't open."
    hwnd, _ = _spotify_window()
    u = _user32()
    u.ShowWindow(hwnd, 9)  # restore if minimised
    time.sleep(1.8)  # let the page load
    spot = None
    for _ in range(12):
        hwnd, _ = _spotify_window()
        spot = _find_play_button(hwnd) if hwnd else None
        if spot:
            break
        time.sleep(0.5)
    if not spot:
        return "I opened it in Spotify, but couldn't find the play button. Press play there."
    was = now_playing()
    _click(*spot)
    if _wait_until(lambda: playing() and now_playing() != was, 4):
        return ""
    if not playing():  # that playlist was already playing and the click paused it
        _click(*spot)
        time.sleep(0.8)
    return "" if playing() else "I opened it in Spotify, but it didn't start. Press play there."


def search(query: str) -> str:
    if WIN:
        os.startfile("spotify:search:" + urllib.parse.quote(query))
    else:
        import webbrowser
        webbrowser.open("https://open.spotify.com/search/" + urllib.parse.quote(query))
    return f"Here's {query} on Spotify."
