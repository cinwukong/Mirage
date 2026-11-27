"""
Making Mirage releases that installed copies will accept as updates (see updater.py). Needs only Python.

  python release_tool.py keygen KEYFILE
      Makes a new update key. KEYFILE holds the secret half: keep it out of the repository (for GitHub Actions,
      store its contents as a secret). It prints the public half, which goes into UPDATE_KEYS in updater.py.

  python release_tool.py pack APP_FOLDER OUT_FOLDER [--key KEYFILE]
      Zips Mirage's code (the folder with mirage.py and version.txt) and writes, into OUT_FOLDER:
        mirage-app-<version>.zip, mirage-update.json (its name, size and SHA-256) and mirage-update.json.sig.
      Upload all three to the GitHub release tagged v<version>. The secret key comes from --key or, if that's
      not given, from the MIRAGE_UPDATE_KEY environment variable (the hex text from KEYFILE).

  python release_tool.py verify OUT_FOLDER
      Checks a packed release against the keys in updater.py, the way an installed Mirage will.
"""

import hashlib
import json
import os
import sys
import zipfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import ed25519  # noqa: E402

SKIP_DIRS = {"__pycache__", ".git", ".github", "installer", "dist", "build", ".venv", "venv", ".idea", ".vscode"}
SKIP_NAMES = {"config.json", "reminders.json", "mirage.log", "selftest.txt", ".gitignore", "model.zip"}
SKIP_SUFFIXES = {".pyc", ".pyo", ".bat", ".tmp", ".new", ".part", ".log"}


def _secret(keyfile=None) -> bytes:
    text = Path(keyfile).read_text(encoding="ascii") if keyfile else os.environ.get("MIRAGE_UPDATE_KEY", "")
    try:
        key = bytes.fromhex(text.strip())
    except ValueError:
        key = b""
    if len(key) != 32:
        sys.exit("No update key: pass --key KEYFILE or set MIRAGE_UPDATE_KEY (64 hex characters).")
    return key


def keygen(keyfile):
    path = Path(keyfile)
    if path.exists():
        sys.exit(f"{path} already exists; not overwriting a key.")
    secret = os.urandom(32)
    path.write_text(secret.hex() + "\n", encoding="ascii")
    print(f"Secret key written to {path}. Keep it private and out of the repository.")
    print("Public key, for UPDATE_KEYS in updater.py:")
    print(ed25519.public_key(secret).hex())


def _app_files(app: Path):
    for p in sorted(app.rglob("*")):
        rel = p.relative_to(app)
        if p.is_dir() or any(part in SKIP_DIRS for part in rel.parts) or p.name in SKIP_NAMES \
                or p.suffix.lower() in SKIP_SUFFIXES:
            continue
        yield p, rel


def pack(app_folder, out_folder, keyfile=None):
    app, out = Path(app_folder).resolve(), Path(out_folder).resolve()
    if not (app / "mirage.py").exists() or not (app / "version.txt").exists():
        sys.exit(f"{app} doesn't look like Mirage's code (no mirage.py or version.txt).")
    secret = _secret(keyfile)
    public = ed25519.public_key(secret).hex()
    sys.path.insert(0, str(app))
    try:
        import updater
        if public not in updater.UPDATE_KEYS:
            print(f"Warning: this key ({public}) isn't in UPDATE_KEYS in {app / 'updater.py'}, so installed copies "
                  "of this version won't accept updates signed with it.")
    except Exception as e:
        print(f"Warning: couldn't read UPDATE_KEYS ({e}).")
    version = (app / "version.txt").read_text(encoding="utf-8").strip()
    out.mkdir(parents=True, exist_ok=True)
    zname = f"mirage-app-{version}.zip"
    zpath = out / zname
    with zipfile.ZipFile(zpath, "w", zipfile.ZIP_DEFLATED) as zf:
        for p, rel in _app_files(app):
            if out in p.parents:
                continue
            info = zipfile.ZipInfo(rel.as_posix(), date_time=(2020, 1, 1, 0, 0, 0))  # same files, same zip
            info.compress_type = zipfile.ZIP_DEFLATED
            info.external_attr = 0o644 << 16
            zf.writestr(info, p.read_bytes())
    blob = zpath.read_bytes()
    manifest = json.dumps({"name": "mirage", "version": version, "file": zname, "size": len(blob),
                           "sha256": hashlib.sha256(blob).hexdigest()}, indent=2).encode("utf-8")
    (out / "mirage-update.json").write_bytes(manifest)
    (out / "mirage-update.json.sig").write_text(ed25519.sign(secret, manifest).hex() + "\n", encoding="ascii")
    print(f"Packed Mirage {version} into {out}: {zname}, mirage-update.json, mirage-update.json.sig")
    print(f"Upload all three to the GitHub release tagged v{version}.")


def verify(out_folder, app_folder=None):
    out = Path(out_folder)
    sys.path.insert(0, str(Path(app_folder).resolve() if app_folder else Path(__file__).resolve().parent))
    import updater
    data = (out / "mirage-update.json").read_bytes()
    m = updater.verify_manifest(data, (out / "mirage-update.json.sig").read_text(encoding="ascii"))
    blob = (out / m["file"]).read_bytes()
    if len(blob) != m["size"] or hashlib.sha256(blob).hexdigest() != m["sha256"]:
        sys.exit("The zip doesn't match the signed manifest.")
    print(f"OK: Mirage {m['version']}, signed with a key in UPDATE_KEYS, zip matches.")


def main(argv):
    if len(argv) >= 2 and argv[0] == "keygen":
        return keygen(argv[1])
    if len(argv) >= 3 and argv[0] == "pack":
        key = argv[argv.index("--key") + 1] if "--key" in argv else None
        return pack(argv[1], argv[2], key)
    if len(argv) >= 2 and argv[0] == "verify":
        return verify(argv[1])
    print(__doc__)
    return 1


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]) or 0)
