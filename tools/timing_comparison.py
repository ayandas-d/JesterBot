"""Compare immutable same-field timing experiments; this never promotes a bot.

python tools/timing_comparison.py BEFORE.json AFTER.json --json /tmp/compare.json
The listed gates cover only safety, training score and WIN-to-LOSS regression.
Head-to-head, p99 and fresh holdout are independent mandatory promotion gates.
"""

import argparse
import json
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from tools.league import interval, summarize, violations
from tools.result_io import read_result


def checked_rows(document):
    if not document["complete"]:
        raise ValueError("Both runs must be complete")
    result = {}
    for row in document["matches"]:
        key = row["opponent"], str(row["seed"])
        if key in result or "raw" not in row:
            raise ValueError("Duplicate or incomplete match")
        result[key] = row
    return result


def safety(document):
    issues = []
    for row in document["matches"]:
        current, _ = violations(row["raw"], row["diagnostics"], row["opponent"],
                                document["metadata"]["config"])
        # Preserve infrastructure/source-change faults that aren't judge stats.
        current += [v for v in row["safety_violations"]
                    if not v.startswith(("agent1/half", "agent2/half", "challenger/"))]
        if current:
            issues.append({"opponent": row["opponent"], "seed": row["seed"], "issues": current})
    return issues


def compare(before, after, tolerance=.02):
    old, new = checked_rows(before), checked_rows(after)
    if old.keys() != new.keys() or before["metadata"]["deals"] != after["metadata"]["deals"]:
        raise ValueError("Comparisons require matched opponent/seed/deal sets")
    differences = []
    regressions = []
    for key, row in old.items():
        challenger = new[key]
        a, b = row["raw"]["paired_bb"], challenger["raw"]["paired_bb"]
        if len(a) != len(b):
            raise ValueError("Comparisons require matched paired deals")
        differences.extend(y - x for x, y in zip(a, b))
        if row["verdict"] == "AGENT1_WIN" and challenger["verdict"] == "AGENT2_WIN":
            regressions.append(list(key))
    old_summary, new_summary = summarize(list(old.values())), summarize(list(new.values()))
    issues = safety(after)
    records = [d for row in new.values() for d in row.get("timing_diagnostics", [])]
    intervention = {key: sum(d.get(key, 0) for d in records)
                    for key in ("nudged_decisions", "lowered_k_decisions")}
    return {"before": old_summary, "after": new_summary,
            "paired_delta": interval(differences),
            "paired_ci_scope": "duplicate-deal differences; seeds share an opponent policy and are not iid policy draws",
            "win_to_loss": regressions, "safety_issues": issues,
            "max_jester_charged_seconds": max(h["time_seconds"] for r in new.values()
                                               for h in r["raw"]["agent_stats"]["agent1"]),
            "interventions": intervention,
            "gates": {"safety": not issues,
                      "league": (new_summary["tournament_points"] >= old_summary["tournament_points"]
                                 and new_summary["mean_bb_per_deal"] >= old_summary["mean_bb_per_deal"] - tolerance),
                      "no_regression": not regressions}}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("before", type=Path)
    parser.add_argument("after", type=Path)
    parser.add_argument("--json", type=Path)
    args = parser.parse_args()
    result = compare(read_result(args.before), read_result(args.after))
    result["inputs"] = {"before": str(args.before), "after": str(args.after)}
    output = json.dumps(result, indent=2) + "\n"
    if args.json:
        args.json.write_text(output)
    print(output)


if __name__ == "__main__":
    main()
