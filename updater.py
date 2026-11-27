"""
Mirage's updates: only signed releases, installed with a way back.

Where updates come from
- The newest GitHub Release of UPDATE_REPO, never a branch. A release is installed only if it carries
  mirage-update.json signed (Ed25519) with one of UPDATE_KEYS. The private half of that key stays with whoever
  publishes releases (release_tool.py makes the key and signs releases). The signed manifest names the app zip, its
  size and SHA-256, so neither the manifest nor the zip can be swapped, and an older release can't be replayed.
- With no key in UPDATE_KEYS, automatic updates are off and Mirage says so.

How an update is installed (the installed app only; running from source, you update with git)
1. Download, check the signature and checksum, unpack to <install folder>\\update.
2. Install new packages if requirements.txt changed, then check every part of the new version loads (--selftest).
   If anything fails, nothing in app\\ has changed.
3. Copy app\\ to app.old, then copy the new files over app\\ and remove code files the new version doesn't have.
   If that fails part way, app.old is copied back.
4. Restart. The new version has one start to reach its window; if it crashes before that, the next start puts
   app.old back by itself (see starting(), confirm() and failed(), called by mirage_app.py and ui_web.py).
"""

import hashlib
import io
import json
import os
import re
import shutil
import subprocess
import sys
import time
import urllib.error
import urllib.request
import zipfile
from pathlib import Path

import ed25519
import paths

UPDATE_REPO = "cinwukong/Mirage"   # "owner/name"; config.json "update_repo" can point elsewhere
# Hex Ed25519 public keys allowed to sign updates. Make one with: python release_tool.py keygen <secret key file>
UPDATE_KEYS: list = ["a83fe03a852b4af6492c2459b6369324e65105813a3b9e744f4224afcb04a630"]  # made 2026-11-27; secret half kept by the publisher
MANIFEST = "mirage-update.json"
SIGNATURE = MANIFEST + ".sig"
MAX_ZIP = 200 * 1024 * 1024
TOKEN = ""                          # GitHub key from config.json, only needed for a private repository

APP = paths.APP_DIR
STAGE = paths.RUNTIME / "update"
BACKUP = paths.RUNTIME / "app.old"
PENDING = paths.DATA / "update-pending.json"
# never removed or replaced in app\ (older Mirage kept settings and downloads next to its code)
KEEP = {"__pycache__", "config.json", "reminders.json", "mirage.log", "model", "model.zip", "memory", ".webview",
        "speech", "brain", "voices", "voice_model", "voice_cache", "selftest.txt"}
CODE = {".py", ".js", ".css", ".html"}  # code files the new version doesn't have are removed, so none can linger


class UpdateError(Exception):
    pass


def _log(msg):
    try:
        from mirage import log
        log(msg)
    except Exception:
        print(msg)


def read_version() -> str:
    try:
        return (APP / "version.txt").read_text(encoding="utf-8").strip() or "0.0.0"
    except Exception:
        return "0.0.0"


def version_tuple(v: str):
    return tuple(int(x) for x in re.findall(r"\d+", str(v))[:3]) or (0,)


def repo(cfg: dict) -> str:
    return (cfg.get("update_repo") or UPDATE_REPO or "").strip().strip("/")


def enabled() -> bool:
    """Updates can be installed from inside Mirage: a signing key is set up and this is the installed app."""
    return bool(UPDATE_KEYS) and paths.BUNDLED


def why_off() -> str:
    if not paths.BUNDLED:
        return "You run Mirage from source, so update it with git pull instead."
    if not UPDATE_KEYS:
        return ("Automatic updates are off in this copy of Mirage (it has no update key yet), so get new versions "
                "from the Releases page on GitHub.")
    return ""


# --------------------------------------------------------------------------- #
# GitHub
# --------------------------------------------------------------------------- #
def _get(url: str, accept="application/vnd.github+json", timeout=30, limit=None) -> bytes:
    """GET from GitHub. Uses the saved key if there is one; if GitHub rejects it, tries again without it (works
    for public repositories). The key is never sent on to the server a download is redirected to."""
    def fetch(with_key):
        req = urllib.request.Request(url, headers={"User-Agent": "Mirage-updater", "Accept": accept})
        if with_key:
            req.add_unredirected_header("Authorization", f"Bearer {TOKEN}")
        with urllib.request.urlopen(req, timeout=timeout) as r:
            data = r.read(limit + 1) if limit else r.read()
        if limit and len(data) > limit:
            raise UpdateError("A download was much bigger than it should be, so the update stopped.")
        return data

    if not TOKEN:
        return fetch(False)
    try:
        return fetch(True)
    except urllib.error.HTTPError as e:
        if e.code not in (401, 403, 404):
            raise
        _log(f"GitHub rejected the saved key (HTTP {e.code}); trying without it.")
        return fetch(False)


def latest_release(repo_name: str) -> dict:
    return json.loads(_get(f"https://api.github.com/repos/{repo_name}/releases/latest").decode("utf-8"))


def _asset(release: dict, name: str):
    return next((a for a in release.get("assets") or [] if a.get("name") == name), None)


def _download_asset(asset: dict, limit: int) -> bytes:
    """A release file, through the API (works for private repositories with a key, and public ones without)."""
    return _get(asset["url"], accept="application/octet-stream", timeout=120, limit=limit)


def release_version(release: dict) -> str:
    return re.sub(r"^[vV]", "", str(release.get("tag_name") or "")).strip()


# --------------------------------------------------------------------------- #
# Checking
# --------------------------------------------------------------------------- #
def check(repo_name: str):
    """(latest version or None, newer and installable: bool, what's wrong or "" when all is well)."""
    if not repo_name:
        return None, False, "Updates aren't set up (no GitHub repository)."
    try:
        rel = latest_release(repo_name)
    except urllib.error.HTTPError as e:
        if e.code == 404:
            return None, False, ("No releases found. If the Mirage repository is private, add your GitHub key."
                                 if not TOKEN else "No releases found, or GitHub refused the key.")
        if e.code in (401, 403):
            return None, False, f"GitHub refused the request (error {e.code}). Try again later."
        return None, False, f"Couldn't check GitHub (error {e.code})."
    except Exception as e:
        return None, False, f"Couldn't reach GitHub ({e.__class__.__name__})."
    latest = release_version(rel)
    if version_tuple(latest) <= version_tuple(read_version()):
        return latest, False, ""  # up to date
    if why_off():
        return latest, False, f"Version {latest} is out. " + why_off()
    if not (_asset(rel, MANIFEST) and _asset(rel, SIGNATURE)):
        return latest, False, (f"Version {latest} is out, but it isn't signed, so Mirage won't install it by itself. "
                               "Download the installer from the Releases page.")
    return latest, True, ""


def verify_manifest(data: bytes, signature_text: str, keys=None) -> dict:
    """The manifest as a dict, if one of the update keys signed exactly these bytes. Raises UpdateError otherwise."""
    keys = UPDATE_KEYS if keys is None else keys
    try:
        sig = bytes.fromhex(signature_text.strip())
    except ValueError:
        raise UpdateError("The update's signature is unreadable, so it wasn't installed.")
    if not any(ed25519.verify(bytes.fromhex(k), data, sig) for k in keys):
        raise UpdateError("The update isn't signed with Mirage's update key, so it wasn't installed.")
    try:
        m = json.loads(data.decode("utf-8"))
        ok = (m.get("name") == "mirage" and isinstance(m.get("version"), str)
              and re.fullmatch(r"[\w.-]+\.zip", str(m.get("file", ""))) and isinstance(m.get("size"), int)
              and 0 < m["size"] <= MAX_ZIP and re.fullmatch(r"[0-9a-f]{64}", str(m.get("sha256", ""))))
    except (ValueError, AttributeError):
        ok = False
    if not ok:
        raise UpdateError("The update's manifest is malformed, so it wasn't installed.")
    return m


# --------------------------------------------------------------------------- #
# Installing
# --------------------------------------------------------------------------- #
def apply(repo_name: str, progress=lambda m: None) -> list:
    """Download, check and install the newest signed release. Returns the files that changed. Raises UpdateError
    (or a network error) without having changed anything, except when putting app.old back also failed."""
    if why_off():
        raise UpdateError(why_off())
    progress("Checking the update…")
    rel = latest_release(repo_name)
    man, sig = _asset(rel, MANIFEST), _asset(rel, SIGNATURE)
    if not (man and sig):
        raise UpdateError("The newest release isn't signed, so Mirage won't install it.")
    m = verify_manifest(_download_asset(man, 64 * 1024), _download_asset(sig, 1024).decode("ascii", "replace"))
    current = read_version()
    if version_tuple(m["version"]) <= version_tuple(current):
        raise UpdateError("You already have this version, or a newer one.")
    if version_tuple(m["version"]) != version_tuple(release_version(rel)):
        raise UpdateError("The release and its signed manifest name different versions, so it wasn't installed.")
    z = _asset(rel, m["file"])
    if not z:
        raise UpdateError("The release is missing its app file.")
    progress("Downloading update…")
    blob = _download_asset(z, m["size"])
    if len(blob) != m["size"] or hashlib.sha256(blob).hexdigest() != m["sha256"]:
        raise UpdateError("The download doesn't match the signed checksum, so it wasn't installed.")
    progress("Checking the new version…")
    root = unpack(blob)
    try:
        if (root / "version.txt").read_text(encoding="utf-8").strip() != m["version"]:
            raise UpdateError("The update's files don't match its signed version, so it wasn't installed.")
        install_packages(root)
        selftest(root)
        progress("Installing update…")
        changed = swap_in(root)
        mark_pending(current, m["version"])
    finally:
        shutil.rmtree(STAGE, ignore_errors=True)
    _log(f"Updated {current} -> {m['version']}: {', '.join(changed) or 'no file changes'}")
    return changed


def unpack(blob: bytes) -> Path:
    """Unpack the app zip into STAGE, refusing anything that could land outside it. Returns the app folder in it."""
    shutil.rmtree(STAGE, ignore_errors=True)
    STAGE.mkdir(parents=True)
    with zipfile.ZipFile(io.BytesIO(blob)) as zf:
        for info in zf.infolist():
            name = info.filename.replace("\\", "/")
            if name.startswith("/") or ":" in name or ".." in name.split("/") or (info.external_attr >> 16) & 0o170000 == 0o120000:
                raise UpdateError(f"The update contains an unsafe path ({info.filename}), so it wasn't installed.")
        zf.extractall(STAGE)
    if (STAGE / "mirage_app.py").exists():
        return STAGE
    subs = [p for p in STAGE.iterdir() if p.is_dir()]
    if len(subs) == 1 and (subs[0] / "mirage_app.py").exists():
        return subs[0]
    raise UpdateError("The download doesn't look like Mirage, so it wasn't installed.")


def install_packages(root: Path):
    """Install the packages a new requirements.txt asks for, into Mirage's own Python."""
    new, old = root / "requirements.txt", APP / "requirements.txt"
    if not new.exists() or (old.exists() and new.read_bytes() == old.read_bytes()):
        return
    r = subprocess.run(paths.pip("install", "--disable-pip-version-check", "-r", str(new)), capture_output=True,
                       text=True, creationflags=paths.NO_WINDOW, timeout=1800)
    if r.returncode != 0:
        lines = [line for line in (r.stderr or r.stdout).splitlines() if line.strip()]
        raise UpdateError("The update needs new packages that didn't install, so nothing was changed: "
                          + (lines[-1] if lines else "pip failed")[:200])


def selftest(root: Path):
    """Run the new version's own self-check: every part has to load with Mirage's Python."""
    out = paths.DATA / "update-selftest.txt"
    out.unlink(missing_ok=True)
    env = dict(os.environ, MIRAGE_SELFTEST_OUT=str(out))
    try:
        r = subprocess.run([str(paths.python_console()), "-I", "-B", str(root / "mirage_app.py"), "--selftest"],
                           cwd=str(root), env=env, capture_output=True, text=True, timeout=300,
                           creationflags=paths.NO_WINDOW)
        code = r.returncode
    except subprocess.TimeoutExpired:
        code = -1
    if code != 0:
        try:
            first = next((line for line in out.read_text(encoding="utf-8").splitlines() if line.startswith("FAIL")),
                         "no report")
        except OSError:
            first = (r.stderr.strip().splitlines() or ["no report"])[-1] if code != -1 else "it took too long"
        raise UpdateError(f"The new version didn't pass its self-check, so nothing was changed ({first[:160]}).")


def _files(folder: Path) -> set:
    return {p.relative_to(folder) for p in folder.rglob("*")
            if p.is_file() and "__pycache__" not in p.parts and p.relative_to(folder).parts[0] not in KEEP}


def mirror(src: Path, dst: Path) -> list:
    """Make dst's code match src: copy files that differ, remove code files src doesn't have. Returns what changed."""
    changed, want = [], _files(src)
    for rel in sorted(want, key=str):
        data = (src / rel).read_bytes()
        dest = dst / rel
        if dest.exists() and dest.read_bytes() == data:
            continue
        dest.parent.mkdir(parents=True, exist_ok=True)
        tmp = dest.with_name(dest.name + ".new")
        tmp.write_bytes(data)
        os.replace(tmp, dest)
        changed.append(str(rel))
    for rel in sorted(_files(dst) - want, key=str):
        if rel.suffix.lower() in CODE:
            (dst / rel).unlink()
            changed.append(f"{rel} (removed)")
    return changed


def swap_in(root: Path) -> list:
    """Keep a copy of the current version in app.old, then put the new files in place; on failure, go back."""
    shutil.rmtree(BACKUP, ignore_errors=True)
    shutil.copytree(APP, BACKUP, ignore=shutil.ignore_patterns("__pycache__", *KEEP))
    try:
        return mirror(root, APP)
    except Exception as e:
        _log(f"Update failed while copying files ({e}); putting the old version back.")
        try:
            mirror(BACKUP, APP)
        except Exception as e2:
            raise UpdateError(f"The update failed and the old version couldn't be fully put back ({e2}). "
                              "Reinstall Mirage from the Releases page.")
        raise UpdateError(f"The update failed while copying files ({e}); the old version is back in place.")


# --------------------------------------------------------------------------- #
# The first start after an update
# --------------------------------------------------------------------------- #
def mark_pending(old: str, new: str):
    paths.DATA.mkdir(parents=True, exist_ok=True)
    PENDING.write_text(json.dumps({"from": old, "to": new, "starts": 0, "at": time.time()}), encoding="utf-8")


def _pending():
    try:
        return json.loads(PENDING.read_text(encoding="utf-8"))
    except FileNotFoundError:
        return None
    except (OSError, ValueError):
        PENDING.unlink(missing_ok=True)
        return None


def rollback(why: str) -> bool:
    """Put app.old back. True if it was."""
    info = _pending() or {}
    if not BACKUP.is_dir():
        PENDING.unlink(missing_ok=True)
        return False
    try:
        mirror(BACKUP, APP)
    except Exception as e:
        _log(f"Couldn't put the old version back after an update: {e}")
        return False
    PENDING.unlink(missing_ok=True)
    _log(f"Went back from {info.get('to', 'the update')} to {info.get('from', 'the previous version')}: {why}")
    return True


_this_start = None  # the pending update this process is the first start of (its "at" time)


def starting() -> str:
    """Call first thing at start. Normally "". If the update's first start never reached the window, the old version
    is put back and a message is returned (then restart, so the old code loads)."""
    global _this_start
    info = _pending()
    if not info:
        return ""
    if info.get("starts", 0) >= 1:
        to, back = info.get("to", "the update"), info.get("from", "the previous version")
        if rollback("its first start didn't get going"):
            return f"Mirage {to} didn't start properly, so Mirage went back to {back}."
        return ""
    info["starts"] = info.get("starts", 0) + 1
    _this_start = info.get("at")
    try:
        PENDING.write_text(json.dumps(info), encoding="utf-8")
    except OSError:
        pass
    return ""


def _ours(info) -> bool:
    """The pending update is the one this process started as (not one it has just installed for the next start)."""
    return bool(info) and _this_start is not None and info.get("at") == _this_start


def confirm():
    """The new version is up and running (or quit normally): keep it."""
    if _ours(_pending()):
        PENDING.unlink(missing_ok=True)
        _log("The update started fine.")


def failed(why: str) -> bool:
    """Starting crashed. Right after an update, put the old version back; True if that happened."""
    return _ours(_pending()) and rollback(why[-300:])
