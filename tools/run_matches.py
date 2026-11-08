"""Run the Task 6 matrix with isolated local servers and retained diagnostics."""

import argparse
from contextlib import contextmanager
import json
import os
from pathlib import Path
import signal
import socket
import subprocess
import sys
import tempfile
from threading import Event
from time import monotonic
from urllib.request import urlopen

ROOT = Path(__file__).resolve().parents[1]
OPPONENTS = {"baseline_random": "baseline-bots/baseline_random.py"}
OPPONENTS.update({name: f"tests/bots/{name}.py" for name in
                  ("nit_folder", "check_fold", "calling_station", "pot_maniac", "pot_odds_bot", "slow_tell")})


@contextmanager
def processes():
    owned = []
    try:
        yield owned
    finally:
        for process in owned:
            if process.poll() is None:
                try:
                    process.terminate()
                except ProcessLookupError:
                    pass
        for process in owned:
            try:
                process.wait(timeout=3)
            except subprocess.TimeoutExpired:
                try:
                    process.kill()
                except ProcessLookupError:
                    pass
                process.wait()


def health(process, port, deadline):
    while monotonic() < deadline:
        if process.poll() is not None:
            raise RuntimeError(f"server exited before readiness: {process.returncode}")
        try:
            with urlopen(f"http://127.0.0.1:{port}/", timeout=.3) as reply:
                if reply.status == 200:
                    return
        except OSError:
            pass
        Event().wait(.025)
    raise TimeoutError(f"server on {port} was not ready in time")


def read_diagnostics(path):
    return [json.loads(line.removeprefix("BOT_DIAGNOSTICS ")) for line in path.read_text().splitlines()
            if line.startswith("BOT_DIAGNOSTICS ")]


def acceptance(name, report, diagnostics, max_thinking=4.0):
    failures = []
    wanted = {"AGENT1_WIN"} if name in ("baseline_random", "nit_folder", "check_fold") else {"AGENT1_WIN", "CHOP"}
    if report["verdict"] not in wanted:
        failures.append(f"verdict {report['verdict']}")
    for player, halves in report["agent_stats"].items():
        for index, half in enumerate(halves, 1):
            if half["errors"] or half["forfeited"] or half["timed_out"] or half["skipped_calls"]:
                failures.append(f"{player} half{index} faults")
            if half["time_seconds"] > max_thinking:
                failures.append(f"{player} half{index} > {max_thinking}s")
    finals = [row for row in diagnostics if row["final"]]
    if len(finals) != 2:
        failures.append("missing half diagnostics")
    if any(row["safety_errors"] for row in finals):
        failures.append("internal safety fallback")
    if name == "check_fold":
        # With these blinds a perfect exploit wins 1.5 bb/duplicate deal.
        if report["mean_bb_per_deal"] < 1.4:
            failures.append("check-fold margin below 1.4 bb/deal")
        if any(row["exploit_raises"] == 0 for row in finals):
            failures.append("check-fold detector did not fire in both halves")
    if name == "calling_station" and any(not row["transitions"] for row in finals):
        failures.append("did not switch out of MANIAC in both halves")
    return failures


def run_match(name, seed, deals, directory, logs=False, bot_seed="7", timeout=180):
    directory.mkdir(parents=True, exist_ok=True)
    sockets = [socket.socket(), socket.socket()]
    handles = []
    try:
        for sock in sockets:
            sock.bind(("127.0.0.1", 0))
        ports = [sock.getsockname()[1] for sock in sockets]
        with processes() as owned:
            for i, script in enumerate(("tools/serve_agent.py", OPPONENTS[name])):
                sockets[i].close()
                handle = (directory / f"agent{i + 1}.log").open("w")
                handles.append(handle)
                env = dict(os.environ, PORT=str(ports[i]), AGENT_TOKEN="", BOT_SEED=bot_seed)
                process = subprocess.Popen([sys.executable, script], cwd=ROOT, env=env,
                                           stdout=handle, stderr=subprocess.STDOUT)
                owned.append(process)
                health(process, ports[i], monotonic() + 15)
            judge_log = (directory / "judge.log").open("w")
            handles.append(judge_log)
            command = [sys.executable, "judge_engine.py", "--agent1", str(ports[0]),
                       "--agent2", str(ports[1]), "--deals", str(deals), "--seed", str(seed),
                       "--json", str((directory / "match.json").resolve())]
            if logs:
                command.append("--logs")
            process = subprocess.Popen(command, cwd=ROOT,
                                       env=dict(os.environ, AGENT1_TOKEN="", AGENT2_TOKEN=""),
                                       stdout=judge_log, stderr=subprocess.STDOUT)
            owned.append(process)
            code = process.wait(timeout=timeout)
            if code:
                raise RuntimeError(f"judge exited {code}; see {directory / 'judge.log'}")
        for handle in handles:
            handle.flush()
        report = json.loads((directory / "match.json").read_text())
        diagnostics = read_diagnostics(directory / "agent1.log")
        failures = acceptance(name, report, diagnostics)
        finals = [row for row in diagnostics if row["final"]]
        return {
            "opponent": name, "seed": str(seed), "deals": deals, "verdict": report["verdict"],
            "bb_per_deal": report["mean_bb_per_deal"], "ci": report["ci"],
            "our_errors": [h["errors"] for h in report["agent_stats"]["agent1"]],
            "our_think_seconds": [h["time_seconds"] for h in report["agent_stats"]["agent1"]],
            "opponent_think_seconds": [h["time_seconds"] for h in report["agent_stats"]["agent2"]],
            "forfeits": {p: [h["forfeited"] for h in halves] for p, halves in report["agent_stats"].items()},
            "diagnostics": finals, "failures": failures, "passed": not failures,
            "log_directory": str(directory.resolve()),
        }
    finally:
        for handle in handles:
            handle.close()
        for sock in sockets:
            sock.close()


def row_text(row):
    if "verdict" not in row:
        return f"{row['opponent']:<16} {row['seed']:>5} ERROR: {row['failures']}"
    gates = "/".join(d["gate"] for d in row["diagnostics"])
    forfeits = sum(sum(halves) for halves in row["forfeits"].values())
    return (f"{row['opponent']:<16} {row['seed']:>5} {row['verdict']:<11} "
            f"{row['bb_per_deal']:>+8.3f} [{row['ci'][0]:>+7.3f},{row['ci'][1]:>+7.3f}] "
            f"{max(row['our_errors']):>3} {forfeits:>3} {row['our_think_seconds'][0]:5.2f}/{row['our_think_seconds'][1]:5.2f} "
            f"{gates:<15} {'PASS' if row['passed'] else 'FAIL: ' + ', '.join(row['failures'])}")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--deals", type=int, default=1000)
    parser.add_argument("--seeds", nargs="+", default=["7", "19", "41"])
    parser.add_argument("--opponents", nargs="+", choices=tuple(OPPONENTS), default=list(OPPONENTS))
    parser.add_argument("--logs", action="store_true", help="retain full judge hand histories in each match JSON")
    parser.add_argument("--output", type=Path, help="report directory (default: new directory under /tmp)")
    parser.add_argument("--bot-seed", default="7")
    parser.add_argument("--timeout", type=float, default=180)
    args = parser.parse_args()
    if args.deals < 1:
        parser.error("--deals must be positive")
    output = args.output or Path(tempfile.mkdtemp(prefix="heads-up-matches-", dir="/tmp"))
    output.mkdir(parents=True, exist_ok=True)
    # SIGTERM, Ctrl-C, startup errors, judge errors and timeouts all unwind
    # the same finally blocks; only processes launched by this tool are killed.
    signal.signal(signal.SIGTERM, lambda *_: sys.exit(143))
    rows = []
    print(f"Reports: {output.resolve()}", flush=True)
    print("Opponent          Seed Verdict        bb/deal CI                     Err Fft Think h1/h2 Gate            Status", flush=True)
    for name in args.opponents:
        for index, seed in enumerate(args.seeds):
            directory = output / f"{name}-{index}-{seed.replace('/', '_')}"
            try:
                row = run_match(name, seed, args.deals, directory, args.logs, args.bot_seed, args.timeout)
            except Exception as exc:
                row = {"opponent": name, "seed": seed, "passed": False, "failures": [str(exc)], "log_directory": str(directory)}
            rows.append(row)
            print(row_text(row), flush=True)
            (output / "summary.json").write_text(json.dumps(rows, indent=2) + "\n")
    print(f"Passed {sum(r['passed'] for r in rows)}/{len(rows)} matches. Reports: {output.resolve()}", flush=True)
    return 0 if all(row["passed"] for row in rows) else 1


if __name__ == "__main__":
    sys.exit(main())
