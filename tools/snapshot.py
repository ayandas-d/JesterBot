"""Freeze the live bot without changing it: python tools/snapshot.py [--tag]."""

import argparse
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import re
import shutil
import subprocess

ROOT = Path(__file__).resolve().parents[1]


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def snapshot(root=ROOT, tag=False):
    root = Path(root)
    parent = root / "league/champions"
    parent.mkdir(parents=True, exist_ok=True)
    commit = subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=root, text=True).strip()
    dirty = bool(subprocess.check_output(["git", "status", "--porcelain", "--", "agent.py", "bot", "game.py", "evaluator.py"], cwd=root))
    while True:
        numbers = [int(p.name[1:]) for p in parent.iterdir() if re.fullmatch(r"v[1-9]\d*", p.name)]
        destination = parent / f"v{max(numbers, default=0) + 1}"
        try:
            destination.mkdir()
            break
        except FileExistsError:
            continue
    try:
        for name in ("agent.py", "game.py", "evaluator.py"):
            shutil.copy2(root / name, destination / name)
        # Freeze the public engine too: no local runtime import can fall back
        # to live source when an older champion is launched later.
        shutil.copytree(root / "bot", destination / "bot",
                        ignore=shutil.ignore_patterns("__pycache__", "*.pyc", "*.pyo"))
        paths = sorted(p for p in destination.rglob("*") if p.is_file())
        if any(p.is_symlink() for p in destination.rglob("*")):
            raise ValueError("snapshots must not contain symlinks")
        meta = {"version": destination.name, "commit_sha": commit,
                "created_at": datetime.now(timezone.utc).isoformat(), "runtime_dirty": dirty,
                "files": {str(p.relative_to(destination)): digest(p) for p in paths}}
        (destination / "META.json").write_text(json.dumps(meta, indent=2) + "\n")
    except BaseException:
        shutil.rmtree(destination)
        raise
    if tag:
        subprocess.run(["git", "tag", "-a", f"champion-{destination.name}", commit,
                        "-m", f"Champion {destination.name}: runtime snapshot of {commit}"], cwd=root, check=True)
    return destination


def verify(path):
    path = Path(path)
    meta = json.loads((path / "META.json").read_text())
    if any(p.is_symlink() for p in path.rglob("*")):
        raise ValueError("snapshots must not contain symlinks")
    actual = {str(p.relative_to(path)) for p in path.rglob("*") if p.is_file()
              and p != path / "META.json" and "__pycache__" not in p.parts and p.suffix not in (".pyc", ".pyo")}
    if actual != set(meta["files"]):
        raise ValueError("snapshot file manifest has changed")
    for name, expected in meta["files"].items():
        file = path / name
        if not file.resolve().is_relative_to(path.resolve()) or file.is_symlink() or digest(file) != expected:
            raise ValueError(f"snapshot file changed: {name}")
    return meta


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--tag", action="store_true")
    args = parser.parse_args()
    path = snapshot(tag=args.tag)
    print(path)
    print(json.dumps(verify(path), indent=2))


if __name__ == "__main__":
    main()
