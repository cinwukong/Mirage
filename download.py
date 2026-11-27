"""
Downloading Mirage's big files (its voice, hearing and brain).

- A broken download carries on where it stopped next time (a .part file next to the target).
- Every file is checked against the size and SHA-256 it must have before it's used, so a file that changed upstream
  or was tampered with is never installed. A leftover .part that can't be right is thrown away instead of getting
  stuck (a server answers "416" when asked to resume past the end of a file).
"""

import hashlib
import os
import time
import urllib.error
import urllib.request
from pathlib import Path


class BadDownload(IOError):
    pass


def fetch(url, dest, progress=lambda m: None, label="the file", size=None, sha256=None):
    """Download url to dest. size (bytes) and sha256 (hex) are checked when given; a wrong file is deleted."""
    dest = Path(dest)
    dest.parent.mkdir(parents=True, exist_ok=True)
    part = dest.with_name(dest.name + ".part")
    for attempt in (1, 2):
        try:
            _fetch(url, part, progress, label, size, sha256)
            break
        except urllib.error.HTTPError as e:
            if e.code == 416 and attempt == 1:  # the saved piece is already as long as the file, or longer
                part.unlink(missing_ok=True)
                continue
            raise
    os.replace(part, dest)


def _fetch(url, part, progress, label, size, sha256):
    have = part.stat().st_size if part.exists() else 0
    if size and have > size:
        part.unlink()
        have = 0
    h = hashlib.sha256()
    if have:  # the piece from last time counts towards the checksum
        with open(part, "rb") as f:
            for block in iter(lambda: f.read(1 << 22), b""):
                h.update(block)
    if not (size and have == size):
        headers = {"User-Agent": "Mirage"}
        if have:
            headers["Range"] = f"bytes={have}-"
        with urllib.request.urlopen(urllib.request.Request(url, headers=headers), timeout=60) as r:
            if have and r.status != 206:  # the server started from the beginning
                have, h = 0, hashlib.sha256()
            total = size or (int(r.headers.get("Content-Length") or 0) + have)
            done, last = have, 0.0
            with open(part, "ab" if have else "wb") as f:
                while True:
                    block = r.read(1 << 20)
                    if not block:
                        break
                    f.write(block)
                    h.update(block)
                    done += len(block)
                    if time.time() - last > 0.5:
                        last = time.time()
                        progress(f"Downloading {label}: {done / 1e9:.1f} of {total / 1e9:.1f} GB" if total > 2e9 else
                                 f"Downloading {label}: {done / 1e6:.0f} of {total / 1e6:.0f} MB")
    got = part.stat().st_size
    if size and got < size:  # stopped early: keep the piece, the next try carries on from here
        raise BadDownload(f"{label} stopped downloading part way ({got / 1e6:.0f} of {size / 1e6:.0f} MB). "
                          "Try again: it carries on where it stopped.")
    if size and got > size:
        part.unlink(missing_ok=True)
        raise BadDownload(f"{label} isn't the size Mirage expects, so it wasn't installed. Try again later, or "
                          "update Mirage.")
    if sha256 and h.hexdigest() != sha256.lower():
        part.unlink(missing_ok=True)
        raise BadDownload(f"{label} isn't the file Mirage expects (its checksum doesn't match), so it wasn't "
                          "installed. Try again later, or update Mirage.")
