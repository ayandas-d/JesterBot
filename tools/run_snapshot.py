"""Launch an immutable champion in a fresh interpreter, isolated from live bot/."""

import argparse
import os
from pathlib import Path
import re
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from tools.snapshot import ROOT, verify


def resolve_snapshot(version, root=ROOT):
    if not re.fullmatch(r"v[1-9]\d*", version):
        raise ValueError("champion must be named vN, e.g. v1")
    path = root / "league/champions" / version
    verify(path)
    return path


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("version")
    parser.add_argument("--port", type=int, default=int(os.environ.get("PORT", "5020")))
    parser.add_argument("--diagnostics", action="store_true", help="test-only stderr observer")
    parser.add_argument("--inspect", action="store_true", help="print isolated runtime import paths and exit")
    args = parser.parse_args()
    if not 1 <= args.port <= 65535:
        parser.error("port must be in 1..65535")
    path = resolve_snapshot(args.version)
    env = dict(os.environ, PORT=str(args.port), PYTHONDONTWRITEBYTECODE="1")
    env.pop("PYTHONPATH", None)
    os.chdir(path)
    if args.inspect:
        code = "import agent,sys,json; print(json.dumps({n:m.__file__ for n,m in sys.modules.items() if n in ('agent','game','evaluator','bot') or n.startswith('bot.')}))"
        command = [sys.executable, "-B", "-c", code]
    elif args.diagnostics:
        env["BOT_SOURCE_ROOT"] = str(path)
        command = [sys.executable, "-B", str(ROOT / "tools/serve_agent.py")]
    else:
        command = [sys.executable, "-B", str(path / "agent.py")]
    os.execve(sys.executable, command, env)


if __name__ == "__main__":
    main()
