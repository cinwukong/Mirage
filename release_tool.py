"""
Making the update files for a Mirage release (see updater.py). Needs only Python; the build runs it.

  python release_tool.py pack APP_FOLDER OUT_FOLDER
      Zips Mirage's code (the folder with mirage.py and version.txt) and writes, into OUT_FOLDER:
        mirage-app-<version>.zip and mirage-update.json (its name, version, size and SHA-256).
      Both go on the GitHub release tagged v<version>; installed copies of Mirage update from them.

  python release_tool.py verify OUT_FOLDER
      Checks the zip against mirage-update.json, the way an installed Mirage will.
"""

import hashlib
import json
import sys
import zipfile
from pathlib import Path

SKIP_DIRS = {"__pycache__", ".git", ".github", "installer", "dist", "build", ".venv", "venv", ".idea", ".vscode"}
SKIP_NAMES = {"config.json", "reminders.json", "mirage.log", "selftest.txt", ".gitignore", "model.zip"}
SKIP_SUFFIXES = {".pyc", ".pyo", ".bat", ".tmp", ".new", ".part", ".log", ".key"}


def _app_files(app: Path):
    for p in sorted(app.rglob("*")):
        rel = p.relative_to(app)
        if p.is_dir() or any(part in SKIP_DIRS for part in rel.parts) or p.name in SKIP_NAMES \
                or p.suffix.lower() in SKIP_SUFFIXES:
            continue
        yield p, rel


def pack(app_folder, out_folder):
    app, out = Path(app_folder).resolve(), Path(out_folder).resolve()
    if not (app / "mirage.py").exists() or not (app / "version.txt").exists():
        sys.exit(f"{app} doesn't look like Mirage's code (no mirage.py or version.txt).")
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
    manifest = {"name": "mirage", "version": version, "file": zname, "size": len(blob),
                "sha256": hashlib.sha256(blob).hexdigest()}
    (out / "mirage-update.json").write_text(json.dumps(manifest, indent=2), encoding="utf-8")
    print(f"Packed Mirage {version} into {out}: {zname}, mirage-update.json")


def verify(out_folder):
    out = Path(out_folder)
    sys.path.insert(0, str(Path(__file__).resolve().parent))
    import updater
    m = updater.read_manifest((out / "mirage-update.json").read_bytes())
    blob = (out / m["file"]).read_bytes()
    if len(blob) != m["size"] or hashlib.sha256(blob).hexdigest() != m["sha256"]:
        sys.exit("The zip doesn't match mirage-update.json.")
    print(f"OK: Mirage {m['version']}, zip matches its manifest.")


def main(argv):
    if len(argv) >= 3 and argv[0] == "pack":
        return pack(argv[1], argv[2])
    if len(argv) >= 2 and argv[0] == "verify":
        return verify(argv[1])
    print(__doc__)
    return 1


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]) or 0)
