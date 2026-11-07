"""Time 1,000 real random decision observations, excluding deal generation.

Run: BOT_SEED=7 .venv/bin/python tools/profile_equity.py
"""

import json
from pathlib import Path
from random import Random
from statistics import median
import sys
from time import perf_counter

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import agent
from game import Action, AgentConfig, Game, Street, make_deal


def profile_decisions(count=1000, budget_seconds=4.0):
    rng = Random(209)
    observations = []
    for i in range(count):
        game = Game(make_deal("equity-profile", i), i % 2, hand_index=i)
        target = Street(rng.randrange(4))
        while game.street < target:
            game.apply(Action.CHECK_CALL)
        observations.append(game.observation(game.to_act))

    memory = {}
    agent.new_half(AgentConfig(num_hands=count), memory)
    governor = memory["bot"].governor
    governor.budget_seconds = budget_seconds
    durations = []
    by_street = {street.name: [] for street in Street}
    for obs in observations:
        start = perf_counter()
        action = agent.choose_action(obs, memory)
        elapsed = perf_counter() - start
        assert action in obs.legal_actions
        durations.append(elapsed)
        by_street[obs.street.name].append(elapsed)
    ordered = sorted(durations)
    return dict(decisions=count, seconds=round(sum(durations), 6),
                p50_ms=round(median(durations) * 1000, 4),
                p99_ms=round(ordered[min(count - 1, int(count * .99))] * 1000, 4),
                max_ms=round(max(durations) * 1000, 4),
                street_p50_ms={street: round(median(times) * 1000, 4)
                               for street, times in by_street.items() if times},
                governor_seconds=round(governor.total_seconds, 6),
                reductions=governor.reductions, final_scale=governor.scale,
                safety_errors=memory["safety_errors"])


if __name__ == "__main__":
    print(json.dumps(profile_decisions(), indent=2))
