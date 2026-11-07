"""Compare passive timing enabled/disabled on the same 1,000-hand trajectory.

Usage: BOT_SEED=7 .venv/bin/python tools/profile_timing.py --json /tmp/timing.json
Timers instrument only bot work, excluding deal generation and game execution.
"""

import argparse
from collections import defaultdict
from hashlib import sha256
import json
from pathlib import Path
from random import Random
from statistics import median
import sys
from time import perf_counter

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import agent
from bot.timing import PhasedTiming
from game import AgentConfig, Game, make_deal


class MeasuredTiming(PhasedTiming):
    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        self.costs = defaultdict(list)
        self.total = 0.0


def measure(name):
    original = getattr(PhasedTiming, name)
    def wrapped(self, *args, **kwargs):
        start = perf_counter()
        try:
            return original(self, *args, **kwargs)
        finally:
            elapsed = perf_counter() - start
            self.costs[name].append(elapsed)
            self.total += elapsed
    return wrapped


for method in ("observe", "finish", "end", "bluff_multiplier", "detector_k"):
    setattr(MeasuredTiming, method, measure(method))


def percentile(values, fraction):
    return sorted(values)[min(len(values) - 1, int(len(values) * fraction))] if values else 0.0


def profile(enabled, hands=1000):
    memory = {}
    agent.new_half(AgentConfig(num_hands=hands), memory)
    timing = memory["bot"].timing = MeasuredTiming(enabled=enabled)
    rng = Random(0)
    durations, module_costs = [], []
    callbacks = 0.0
    actions = sha256()
    for index in range(hands):
        game = Game(make_deal("timing-profile-7", index), index % 2, hand_index=index)
        while not game.is_terminal:
            obs = game.observation(game.to_act)
            if game.to_act == 0:
                before = timing.total
                start = perf_counter()
                action = agent.choose_action(obs, memory)
                durations.append(perf_counter() - start)
                module_costs.append(timing.total - before)
                actions.update(bytes([action]))
            else:
                action = rng.choice(obs.legal_actions)
            game.apply(action)
        start = perf_counter()
        agent.on_hand_end(game.hand_result(0), memory)
        callbacks += perf_counter() - start
    report = {
        "enabled": enabled, "hands": hands, "decisions": len(durations),
        "thinking_seconds": sum(durations) + callbacks,
        "decision_p50_ms": median(durations) * 1000,
        "decision_p99_ms": percentile(durations, .99) * 1000,
        "module_mean_us": sum(module_costs) / len(module_costs) * 1e6,
        "module_p50_us": median(module_costs) * 1e6,
        "module_p99_us": percentile(module_costs, .99) * 1e6,
        "label_callback_p99_us": percentile(timing.costs["end"], .99) * 1e6,
        "gate": timing.gate, "gate_reason": timing.gate_reason, "gate_hand": timing.gate_hand,
        "labelled_hands": len(timing.labelled_hands), "gaps": timing.gap_counts,
        "baseline_same_hand_seconds": timing.overhead[False],
        "baseline_cross_hand_seconds": timing.overhead[True],
        "bank_estimate_seconds": timing.bank_estimate,
        "nudged_decisions": timing.nudged_decisions, "lowered_k_decisions": timing.lowered_k_decisions,
        "safety_errors": memory["safety_errors"], "action_hash": actions.hexdigest(),
        "governor_reductions": memory["bot"].governor.reductions,
    }
    assert report["safety_errors"] == 0
    assert report["thinking_seconds"] < 4 and report["decision_p99_ms"] < 20
    assert report["module_mean_us"] < 50 and report["module_p99_us"] < 50
    if enabled and hands >= 700:
        assert report["gate"] == "closed" and report["nudged_decisions"] == report["lowered_k_decisions"] == 0
    return report


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--json", type=Path)
    args = parser.parse_args()
    reports = [profile(False), profile(True)]
    assert reports[0]["action_hash"] == reports[1]["action_hash"], "No-signal timing changed actions"
    output = json.dumps(reports, indent=2)
    print(output)
    if args.json:
        args.json.write_text(output + "\n")


if __name__ == "__main__":
    main()
