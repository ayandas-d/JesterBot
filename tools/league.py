"""Duplicate-format league runner. Quick: --quick; full: --full.

Holdouts require --group holdout --milestone NAME. Head-to-head:
  python tools/league.py --challenger live --head-to-head v1 --seeds 1 2 3
Parallel workers orchestrate isolated server/judge processes, never agents
inside a shared interpreter. --jobs 1 gives the least timing contention.
"""

import argparse
from concurrent.futures import ThreadPoolExecutor, as_completed
import csv
from datetime import datetime, timezone
import fcntl
import hashlib
import json
from math import sqrt
import os
from pathlib import Path
import re
import signal
import socket
from statistics import mean, stdev
import subprocess
import sys
import tempfile
from threading import Event
from time import monotonic
from urllib.request import urlopen

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from tools.run_matches import processes, read_diagnostics
from tools.run_snapshot import resolve_snapshot
from game import AgentConfig


def load_config(path=None):
    config = json.loads((Path(path) if path else ROOT / "league/config.json").read_text())
    training, holdout = config["training"], config["holdout"]
    if set(training["opponents"]) & set(holdout["opponents"]):
        raise ValueError("training and holdout opponents overlap")
    if set(map(str, training["seeds"])) & set(map(str, holdout["seeds"])):
        raise ValueError("training and holdout seeds overlap")
    return config


def champions():
    parent = ROOT / "league/champions"
    names = [p.name for p in parent.iterdir() if re.fullmatch(r"v[1-9]\d*", p.name)] if parent.exists() else []
    return sorted(names, key=lambda name: int(name[1:]))


def runtime_hashes(source):
    paths = [source / name for name in ("agent.py", "game.py", "evaluator.py")]
    paths += list((source / "bot").rglob("*.py"))
    return {str(p.relative_to(source)): hashlib.sha256(p.read_bytes()).hexdigest() for p in paths}


def command(name, config):
    if name == "live":
        return [sys.executable, "-B", str(ROOT / "tools/serve_agent.py")]
    if re.fullmatch(r"v[1-9]\d*", name):
        resolve_snapshot(name)
        return [sys.executable, "-B", str(ROOT / "tools/run_snapshot.py"), name, "--diagnostics"]
    script = (ROOT / config["opponents"][name]["script"]).resolve()
    if not script.is_relative_to(ROOT / "league/opponents") or not script.is_file():
        raise ValueError(f"invalid opponent script: {name}")
    return [sys.executable, "-B", str(script)]


def interval(values):
    if not values:
        return {"deals": 0, "mean_bb_per_deal": None, "ci": None}
    average = mean(values)
    width = 1.96 * stdev(values) / sqrt(len(values)) if len(values) > 1 else 0.0
    return {"deals": len(values), "mean_bb_per_deal": average, "ci": [average - width, average + width]}


def violations(report, diagnostics, opponent, config):
    issues, expected = [], []
    for player, halves in report["agent_stats"].items():
        intentional = player == "agent2" and opponent in config["safety"]["expected_fault_opponents"]
        for number, half in enumerate(halves, 1):
            for key in ("errors", "forfeited", "skipped_calls", "timed_out"):
                if half[key]:
                    item = f"{player}/half{number}/{key}={half[key]}"
                    (expected if intentional and key != "timed_out" else issues).append(item)
            # Four seconds is Jester's submission headroom requirement.
            # Deliberate-delay controls must fit their own tournament bank.
            limit = (config["safety"]["max_thinking_seconds"] if player == "agent1"
                     else AgentConfig().time_bank_seconds)
            if half["time_seconds"] > limit:
                issues.append(f"{player}/half{number}/think={half['time_seconds']:.3f}s")
    finals = [d for d in diagnostics if d["final"]]
    if len(finals) != 2:
        issues.append("challenger/missing half diagnostics")
    if any(d["safety_errors"] for d in finals):
        issues.append("challenger/internal safe fallback")
    return issues, expected


def ready(process, port, stop, timeout=15):
    deadline = monotonic() + timeout
    while monotonic() < deadline:
        if stop.is_set():
            raise InterruptedError("league cancelled")
        if process.poll() is not None:
            raise RuntimeError(f"server exited before startup: {process.returncode}")
        try:
            with urlopen(f"http://127.0.0.1:{port}/", timeout=.3) as reply:
                if reply.status == 200:
                    return
        except OSError:
            pass
        stop.wait(.025)
    raise TimeoutError("server startup exceeded 15 seconds")


def timing_audits(log, report, prefix="TIMING_AUDIT "):
    """Pair passive observations with the judge's external half reference."""
    records = [json.loads(line.removeprefix(prefix))
               for line in log.read_text().splitlines() if line.startswith(prefix)]
    for index, record in enumerate(records):
        if index < len(report["agent_stats"]["agent2"]):
            half = report["agent_stats"]["agent2"][index]
            record["judge_opponent_reference"] = {
                "charged_seconds": half["time_seconds"],
                "http_wall_seconds": half["wall_seconds"], "calls": half["calls"],
                "scope": "whole half; each HTTP request has 1 ms free grace",
            }
            references = report.get("timing_reference", {}).get("agent2", [])
            if index < len(references):
                record["judge_opponent_reference"]["checkpoints"] = references[index]
                for checkpoint in record.get("bank_checkpoints", []):
                    truth = references[index].get(str(checkpoint["hands"]))
                    if truth is not None:
                        checkpoint["judge_charged_seconds"] = truth["time_seconds"]
                        error = checkpoint["estimate"] - truth["time_seconds"]
                        checkpoint["absolute_error_seconds"] = abs(error)
                        checkpoint["relative_error"] = abs(error) / truth["time_seconds"] if truth["time_seconds"] else None
    return records


def run_one(challenger, opponent, seed, deals, directory, config, stop, logs=False, timeout=180,
            bot_seed="7", timing_reference=False, timing_mode="configured", force_fake_gate=False):
    directory.mkdir(parents=True, exist_ok=True)
    source = ROOT if challenger == "live" else resolve_snapshot(challenger)
    initial_runtime = runtime_hashes(source)
    sockets, handles = [socket.socket(), socket.socket()], []
    try:
        if stop.is_set():
            raise InterruptedError("league cancelled")
        for sock in sockets:
            sock.bind(("127.0.0.1", 0))
        ports = [sock.getsockname()[1] for sock in sockets]
        with processes() as owned:
            for i, name in enumerate((challenger, opponent)):
                sockets[i].close()
                handle = (directory / f"agent{i + 1}.log").open("w")
                handles.append(handle)
                env = dict(os.environ, PORT=str(ports[i]), AGENT_TOKEN="", BOT_SEED=bot_seed,
                           PYTHONDONTWRITEBYTECODE="1")
                env.pop("PYTHONPATH", None)
                env.pop("BOT_SOURCE_ROOT", None)
                if i == 0:
                    env["JESTER_TIMING_MODE"] = timing_mode
                    if force_fake_gate:
                        env["JESTER_FORCE_FAKE_GATE"] = "1"
                    else:
                        env.pop("JESTER_FORCE_FAKE_GATE", None)
                else:
                    env.pop("JESTER_TIMING_MODE", None)
                    env.pop("JESTER_FORCE_FAKE_GATE", None)
                process = subprocess.Popen(command(name, config), cwd=ROOT, env=env,
                                           stdout=handle, stderr=subprocess.STDOUT)
                owned.append(process)
                ready(process, ports[i], stop)
            handle = (directory / "judge.log").open("w")
            handles.append(handle)
            output = directory / "match.json"
            judge_script = ROOT / "tools/judge_timing_audit.py" if timing_reference else ROOT / "judge_engine.py"
            args = [sys.executable, "-B", str(judge_script), "--agent1", str(ports[0]),
                    "--agent2", str(ports[1]), "--seed", str(seed), "--deals", str(deals), "--json", str(output)]
            if logs:
                args.append("--logs")
            process = subprocess.Popen(args, cwd=ROOT, stdout=handle, stderr=subprocess.STDOUT,
                                       env=dict(os.environ, AGENT1_TOKEN="", AGENT2_TOKEN="", PYTHONDONTWRITEBYTECODE="1"))
            owned.append(process)
            deadline = monotonic() + timeout
            while process.poll() is None:
                if stop.wait(.1):
                    raise InterruptedError("league cancelled")
                if monotonic() > deadline:
                    raise TimeoutError(f"match exceeded {timeout} seconds")
            if process.returncode:
                raise RuntimeError(f"judge exited {process.returncode}")
        for handle in handles:
            handle.flush()
        report = json.loads(output.read_text())
        diagnostics = read_diagnostics(directory / "agent1.log")
        issues, expected = violations(report, diagnostics, opponent, config)
        if runtime_hashes(source) != initial_runtime:
            issues.append("challenger runtime source changed during match")
        times = [h["time_seconds"] for h in report["agent_stats"]["agent1"]]
        return {"opponent": opponent, "seed": seed, "verdict": report["verdict"],
                "points": report["points"]["agent1"], "bb_per_deal": report["mean_bb_per_deal"], "ci": report["ci"],
                "runtime_source_sha256": initial_runtime,
                "our_errors": [h["errors"] for h in report["agent_stats"]["agent1"]],
                "think_seconds": times, "think_max": max(times), "think_mean": mean(times),
                "forfeits": {p: [h["forfeited"] for h in halves] for p, halves in report["agent_stats"].items()},
                "safety_violations": issues, "expected_opponent_faults": expected,
                "timing_audit": timing_audits(directory / "agent1.log", report),
                "timing_diagnostics": timing_audits(directory / "agent1.log", report, "JESTER_TIMING "),
                "diagnostics": [d for d in diagnostics if d["final"]],
                "raw": report, "log_directory": str(directory)}
    finally:
        for handle in handles:
            handle.close()
        for sock in sockets:
            sock.close()


def summarize(rows):
    completed = [row for row in rows if "raw" in row]
    values = [value for row in completed for value in row["raw"]["paired_bb"]]
    per_opponent = {}
    for name in sorted({row["opponent"] for row in completed}):
        subset = [row for row in completed if row["opponent"] == name]
        per_opponent[name] = {**interval([v for row in subset for v in row["raw"]["paired_bb"]]),
                              "points": sum(row["points"] for row in subset), "matches": len(subset)}
    worst = min(per_opponent, key=lambda name: per_opponent[name]["mean_bb_per_deal"]) if per_opponent else None
    issues = [{"opponent": row["opponent"], "seed": row["seed"], "issues": row["safety_violations"]}
              for row in rows if row["safety_violations"]]
    return {**interval(values), "tournament_points": sum(row["points"] for row in completed),
            "completed_matches": len(completed), "requested_matches": len(rows),
            "worst_matchup": worst, "opponents": per_opponent, "safety_violations": issues,
            "expected_fault_matches": sum(bool(row.get("expected_opponent_faults")) for row in rows)}


def append_history(path, record):
    fields = ("timestamp", "label", "challenger", "commit", "group", "deals", "seeds", "matches",
              "points", "mean_bb_per_deal", "worst_matchup", "safety_violations", "complete", "result")
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a+", newline="") as handle:
        fcntl.flock(handle, fcntl.LOCK_EX)
        try:
            handle.seek(0, 2)
            writer = csv.DictWriter(handle, fieldnames=fields, lineterminator="\n")
            if handle.tell() == 0:
                writer.writeheader()
            writer.writerow(record)
            handle.flush()
        finally:
            fcntl.flock(handle, fcntl.LOCK_UN)


def plan(args, config):
    group = args.group
    if args.quick and (group != "training" or args.head_to_head or args.opponents or args.seeds or args.deals):
        raise ValueError("--quick is exactly 300 deals, three training seeds and the training opponent set")
    if args.full and (args.head_to_head or args.opponents or args.seeds or args.deals):
        raise ValueError("--full uses the entire configured group and all its seeds; omit --full for custom runs")
    if group == "holdout" and not args.milestone:
        raise ValueError("holdouts require an explicit --milestone NAME")
    opponents = args.opponents or list(config[group]["opponents"])
    if args.head_to_head:
        resolve_snapshot(args.head_to_head)
        opponents = [args.head_to_head]
    elif not args.opponents and group == "training" and config["champions"]["include_all"]:
        opponents += champions()
    historical = config.get("holdout_history", [])
    protected_names = set(config["holdout"]["opponents"]).union(*(set(v["opponents"]) for v in historical))
    protected_seeds = set(map(str, config["holdout"]["seeds"])).union(*(set(map(str, v["seeds"])) for v in historical))
    if set(opponents) & protected_names and not args.milestone:
        raise ValueError("holdout opponents require an explicit milestone, even with --opponents")
    seeds = args.seeds or list(config[group]["seeds"])
    if set(map(str, seeds)) & protected_seeds and not args.milestone:
        raise ValueError("holdout seeds require an explicit milestone")
    if args.quick:
        seeds = seeds[:config["quick"]["seed_count"]]
    if len(set(map(str, seeds))) != len(seeds):
        raise ValueError("duplicate seeds would double-count deals in the combined CI")
    if not opponents or not seeds or len(set(opponents)) != len(opponents):
        raise ValueError("select nonempty, distinct opponents and nonempty seeds")
    deals = config["quick"]["deals"] if args.quick else args.deals or config["full"]["deals"]
    if deals < 1 or args.jobs < 1:
        raise ValueError("deals and jobs must be positive")
    for name in [args.challenger, *opponents]:
        command(name, config)  # validate before spawning anything
    return opponents, list(map(str, seeds)), deals


def row_text(row):
    if "raw" not in row:
        return f"{row['opponent']:<18} seed={row['seed']} ERROR {row['safety_violations']}"
    forfeits = sum(sum(h) for h in row["forfeits"].values())
    return (f"{row['opponent']:<18} {row['seed']:>4} {row['verdict']:<11} {row['bb_per_deal']:+8.3f} "
            f"[{row['ci'][0]:+7.3f},{row['ci'][1]:+7.3f}] errors={sum(row['our_errors'])} "
            f"think max/mean={row['think_max']:.3f}/{row['think_mean']:.3f}s forfeits={forfeits} "
            f"{'VIOLATION' if row['safety_violations'] else 'OK'}")


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument("--quick", action="store_true")
    mode.add_argument("--full", action="store_true", help="default: 1,000 deals, all seeds in the selected group")
    parser.add_argument("--group", choices=("training", "holdout"), default="training")
    parser.add_argument("--milestone")
    parser.add_argument("--challenger", default="live", help="live or a champion version")
    parser.add_argument("--head-to-head", metavar="CHAMPION")
    parser.add_argument("--opponents", nargs="+")
    parser.add_argument("--seeds", nargs="+")
    parser.add_argument("--deals", type=int)
    parser.add_argument("--jobs", type=int, default=1, help="concurrent matches; use 1 for timing acceptance")
    parser.add_argument("--label", default="league")
    parser.add_argument("--logs", action="store_true")
    parser.add_argument("--timeout", type=float, default=180)
    parser.add_argument("--bot-seed", default="7")
    parser.add_argument("--timing-reference", action="store_true", help="test-only unchanged-judge prefix telemetry")
    parser.add_argument("--timing-mode", choices=("configured", "enabled", "disabled", "observe"), default="configured")
    parser.add_argument("--force-fake-gate", action="store_true", help="adversarial TEST ONLY: force an invalid timing model")
    args = parser.parse_args(argv)
    config = load_config()
    try:
        opponents, seeds, deals = plan(args, config)
    except (ValueError, KeyError, FileNotFoundError) as exc:
        parser.error(str(exc))
    if not re.fullmatch(r"[a-zA-Z0-9_-]+", args.label):
        parser.error("label must contain only letters, digits, hyphens and underscores")
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S%fZ")
    destination = ROOT / "league/results" / f"{stamp}_{args.label}.json"
    destination.parent.mkdir(parents=True, exist_ok=True)
    log_root = Path(tempfile.mkdtemp(prefix=f"league-{args.label}-", dir="/tmp"))
    commit = subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=ROOT, text=True).strip()
    if args.challenger != "live":
        commit = json.loads((resolve_snapshot(args.challenger) / "META.json").read_text())["commit_sha"]
    metadata = {"timestamp": stamp, "label": args.label, "challenger": args.challenger, "commit": commit,
                "group": args.group, "milestone": args.milestone, "opponents": opponents, "seeds": seeds,
                "deals": deals, "jobs": args.jobs, "bot_seed": args.bot_seed, "head_to_head": args.head_to_head,
                "log_directory": str(log_root), "ci_method": "pooled duplicate-pair returns, normal 95% CI"}
    metadata["config"] = config
    metadata["timing_probe"] = os.environ.get("JESTER_TIMING_PROBE") == "1"
    metadata["diagnostics_enabled"] = os.environ.get("JESTER_DIAG") == "1"
    metadata["timing_reference"] = args.timing_reference
    metadata["timing_mode"] = args.timing_mode
    metadata["force_fake_gate"] = args.force_fake_gate
    metadata["observer_source_sha256"] = {
        name: hashlib.sha256((ROOT / "tools" / name).read_bytes()).hexdigest()
        for name in ("serve_agent.py", "timing_probe.py", "judge_timing_audit.py")}
    metadata["opponent_source_sha256"] = {
        p.name: hashlib.sha256(p.read_bytes()).hexdigest() for p in sorted((ROOT / "league/opponents").glob("*.py"))}
    source = ROOT if args.challenger == "live" else resolve_snapshot(args.challenger)
    metadata["challenger_source_sha256"] = runtime_hashes(source)
    stop, rows = Event(), []
    def terminate(*_):
        raise KeyboardInterrupt("league received SIGTERM")
    signal.signal(signal.SIGTERM, terminate)
    print(f"{len(opponents) * len(seeds)} matches; jobs={args.jobs}; logs={log_root}; results={destination}", flush=True)
    executor = ThreadPoolExecutor(max_workers=args.jobs)
    interrupted = False
    futures = {}
    try:
        for name in opponents:
            for index, seed in enumerate(seeds):
                future = executor.submit(run_one, args.challenger, name, seed, deals,
                                         log_root / f"{name}-{index}", config, stop, args.logs, args.timeout, args.bot_seed,
                                         args.timing_reference, args.timing_mode, args.force_fake_gate)
                futures[future] = (name, seed)
        for future in as_completed(futures):
            name, seed = futures[future]
            try:
                row = future.result()
            except Exception as exc:
                row = {"opponent": name, "seed": seed, "safety_violations": [f"infrastructure: {exc}"]}
            rows.append(row)
            print(f"[{len(rows)}/{len(futures)}] {row_text(row)}", flush=True)
            destination.write_text(json.dumps({"metadata": metadata, "complete": False, "matches": rows}, indent=2) + "\n")
    except BaseException:
        interrupted = True
        stop.set()
        raise
    finally:
        if interrupted:
            stop.set()
        executor.shutdown(wait=True, cancel_futures=True)
        summary = summarize(rows)
        summary["requested_matches"] = len(futures)
        complete = summary["completed_matches"] == len(futures) and not interrupted
        document = {"metadata": metadata, "complete": complete, "summary": summary, "matches": rows}
        destination.write_text(json.dumps(document, indent=2) + "\n")
        append_history(ROOT / "league/history.csv", {
            "timestamp": stamp, "label": args.label, "challenger": args.challenger, "commit": commit,
            "group": args.group, "deals": deals, "seeds": ";".join(seeds), "matches": summary["completed_matches"],
            "points": summary["tournament_points"], "mean_bb_per_deal": summary["mean_bb_per_deal"],
            "worst_matchup": summary["worst_matchup"], "safety_violations": len(summary["safety_violations"]),
            "complete": complete, "result": str(destination.relative_to(ROOT)),
        })
    print(json.dumps(summary, indent=2), flush=True)
    print(f"Saved {destination}", flush=True)
    return 0 if complete and not summary["safety_violations"] else 1


if __name__ == "__main__":
    sys.exit(main())
