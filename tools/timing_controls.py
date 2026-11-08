"""Run or assess preregistered live timing controls using the real judge.

Examples:
  python tools/timing_controls.py --run positive negative known --jobs 2
  python tools/timing_controls.py --assess positive path/to/result.json
Each run owns a process group, including league servers and judges, and cleans
that group on failure/cancellation. All opponent/seed choices are training-only.
"""

import argparse
import json
import os
from pathlib import Path
import signal
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from tools.league import interval, violations

GROUPS = {
    "positive": (["strong_tell"], list(range(1, 21))),
    "negative": (["baseline_random", "calling_station", "pot_maniac"], list(range(1, 11))),
    "known": (["known_thinker", "variable_thinker"], list(range(1, 6))),
    "fake": (["fake_tell"], list(range(1, 21))),
    "fake-disabled": (["fake_tell"], list(range(1, 21))),
}


def assess(kind, document):
    opponents, seeds = GROUPS[kind]
    expected = {(name, str(seed)) for name in opponents for seed in seeds}
    actual = {(r["opponent"], r["seed"]) for r in document["matches"]}
    assert document["complete"] and actual == expected
    assert document["metadata"]["deals"] == 1000
    # Reassess immutable raw records with the explicit clock scopes. Older
    # runner summaries incorrectly applied Jester's 4 s ceiling to controls
    # whose stated requirement is their own 8 s bank. Never rewrite the raw
    # summaries or waive an error, timeout, forfeit, or Jester time violation.
    issues = []
    for row in document["matches"]:
        issues.extend(violations(row["raw"], row["diagnostics"], row["opponent"],
                                 document["metadata"]["config"])[0])
        issues.extend(v for v in row["safety_violations"]
                      if not v.startswith("agent2/half") or "/think=" not in v)
    assert not issues, issues
    diagnoses = [v for r in document["matches"] for v in r["timing_diagnostics"]]
    assert len(diagnoses) == 2 * len(expected), "Missing per-half timing diagnostics"
    opened = sum(v["gate"]["decision"] == "open" for v in diagnoses)
    report = {"halves": len(diagnoses), "opened": opened, "rate": opened / len(diagnoses),
              "safety_scope": "Jester <=4s; controls <=their 8s bank; zero faults on either side"}
    if kind == "positive":
        assert report["rate"] >= .80, report
    elif kind == "negative":
        assert report["rate"] <= .05, report
        if not opened:
            report["one_sided_95_percent_upper_bound"] = 1 - .05 ** (1 / len(diagnoses))
    elif kind == "known":
        errors = [v["relative_error"] for d in diagnoses for v in d["bank_checkpoints"]
                  if v["hands"] == 700]
        assert len(errors) == len(diagnoses) and all(v is not None for v in errors)
        report["hand_700_relative_errors"] = errors
        report["maximum_relative_error"] = max(errors)
        assert max(errors) <= .25, report
    return report


def compare_fake(enabled, disabled, loss_limit=.25):
    assess("fake", enabled)
    assess("fake-disabled", disabled)
    assert enabled["metadata"]["force_fake_gate"]
    assert disabled["metadata"]["timing_mode"] == "disabled"
    reference = {(r["opponent"], r["seed"]): r for r in disabled["matches"]}
    differences = [a - b for row in enabled["matches"]
                   for a, b in zip(row["raw"]["paired_bb"], reference[row["opponent"], row["seed"]]["raw"]["paired_bb"])]
    report = interval(differences)
    report["maximum_acceptable_loss_bb_per_deal"] = loss_limit
    assert report["ci"][0] >= -loss_limit, report
    assert not any(d["nudged_decisions"] for r in enabled["matches"] for d in r["timing_diagnostics"])
    return report


def run_control(kind, jobs=2, label=None):
    opponents, seeds = GROUPS[kind]
    label = label or f"phase2-final-{kind}"
    command = [sys.executable, "-B", str(ROOT / "tools/league.py"), "--opponents", *opponents,
               "--seeds", *map(str, seeds), "--deals", "1000", "--jobs", str(jobs),
               "--timing-reference", "--label", label]
    if kind == "fake":
        command += ["--force-fake-gate"]
    elif kind == "fake-disabled":
        command += ["--timing-mode", "disabled"]
    previous = set((ROOT / "league/results").glob(f"*_{label}.json"))
    env = dict(os.environ, BOT_SEED="7", JESTER_DIAG="1", PYTHONDONTWRITEBYTECODE="1")
    env.pop("JESTER_TIMING_PROBE", None)
    process = subprocess.Popen(command, cwd=ROOT, env=env, start_new_session=True)
    try:
        code = process.wait(timeout=7200)
        if code:
            raise RuntimeError(f"Control runner exited {code}: {kind}")
    finally:
        # Kill only this newly created process group; no unrelated server can
        # share its group. SIGTERM lets the league save and clean up normally.
        try:
            os.killpg(process.pid, signal.SIGTERM)
        except ProcessLookupError:
            pass
        if process.poll() is None:
            try:
                process.wait(timeout=20)
            except subprocess.TimeoutExpired:
                try:
                    os.killpg(process.pid, signal.SIGKILL)
                except ProcessLookupError:
                    pass
                process.wait()
        try:
            os.killpg(process.pid, signal.SIGKILL)
        except ProcessLookupError:
            pass
    created = set((ROOT / "league/results").glob(f"*_{label}.json")) - previous
    assert len(created) == 1
    path = created.pop()
    document = json.loads(path.read_text())
    report = assess(kind, document)
    return path, report


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--run", nargs="+", choices=GROUPS)
    parser.add_argument("--assess", nargs=2, metavar=("GROUP", "RESULT"))
    parser.add_argument("--jobs", type=int, default=2)
    args = parser.parse_args()
    def interrupted(*_):
        raise KeyboardInterrupt
    signal.signal(signal.SIGTERM, interrupted)
    if args.assess:
        kind, path = args.assess
        print(json.dumps(assess(kind, json.loads(Path(path).read_text())), indent=2))
    elif args.run:
        for kind in args.run:
            path, report = run_control(kind, args.jobs)
            print(json.dumps({"group": kind, "path": str(path), "report": report}), flush=True)
    else:
        parser.error("choose --run or --assess")


if __name__ == "__main__":
    main()
