"""Run owned servers, a duplicate match and cleanup; never stop other servers.

Example: .venv/bin/python tools/run_local_match.py --deals 200 --seed 7
"""

import argparse
import json
import os
from pathlib import Path
import socket
import subprocess
import sys
import tempfile
from threading import Event
from time import monotonic
from urllib.request import urlopen

ROOT = Path(__file__).resolve().parents[1]


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--deals", type=int, default=200)
    parser.add_argument("--seed", default="7")
    parser.add_argument("--opponent", choices=("random", "calling_station", "always_pot", "always_half"), default="random")
    parser.add_argument("--json", type=Path)
    parser.add_argument("--require-win", action="store_true")
    parser.add_argument("--max-thinking", type=float)
    args = parser.parse_args()
    # Reserve two distinct ephemeral ports, then release just before spawning.
    sockets = [socket.socket(), socket.socket()]
    for sock in sockets:
        sock.bind(("127.0.0.1", 0))
    ports = [sock.getsockname()[1] for sock in sockets]
    processes = []
    with tempfile.TemporaryDirectory(prefix="poker-match-", dir="/tmp") as tmp:
        logs = []
        try:
            for sock, port, script in zip(sockets, ports, ("agent.py", f"baseline-bots/baseline_{args.opponent}.py")):
                sock.close()
                log = open(Path(tmp) / f"{port}.log", "w+")
                logs.append(log)
                env = dict(os.environ, PORT=str(port), AGENT_TOKEN="")
                process = subprocess.Popen([sys.executable, script], cwd=ROOT, env=env,
                                           stdout=log, stderr=subprocess.STDOUT)
                processes.append(process)
                deadline = monotonic() + 15
                while True:
                    try:
                        with urlopen(f"http://127.0.0.1:{port}/", timeout=0.5) as response:
                            assert response.status == 200
                        break
                    except OSError:
                        if process.poll() is not None or monotonic() >= deadline:
                            log.seek(0)
                            raise RuntimeError(f"Server failed startup: {log.read()}")
                        Event().wait(0.05)
            out = args.json.resolve() if args.json else Path(tmp) / "result.json"
            env = dict(os.environ, AGENT1_TOKEN="", AGENT2_TOKEN="")
            subprocess.run([sys.executable, "judge_engine.py", "--agent1", str(ports[0]),
                            "--agent2", str(ports[1]), "--deals", str(args.deals),
                            "--seed", args.seed, "--json", str(out)],
                           cwd=ROOT, env=env, check=True)
            report = json.loads(out.read_text())
            # Judge exit status alone is not a compatibility check.
            for stats in report["agent_stats"]["agent1"]:
                assert stats["errors"] == 0 and not stats["forfeited"] and not stats["timed_out"], stats
                if args.max_thinking is not None:
                    assert stats["time_seconds"] <= args.max_thinking, stats
            if args.require_win:
                assert report["verdict"] == "AGENT1_WIN", report["verdict"]
        finally:
            for process in processes:
                if process.poll() is None:
                    process.terminate()
            for process in processes:
                try:
                    process.wait(timeout=5)
                except subprocess.TimeoutExpired:
                    process.kill()
                    process.wait()
            for log in logs:
                log.close()
            for sock in sockets:
                sock.close()


if __name__ == "__main__":
    main()
