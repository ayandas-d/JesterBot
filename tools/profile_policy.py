"""Measure mixed-policy frequencies on the same engine walks as Task 1.

The MANIAC raise rate includes EVERY sampled raise-legal observation, even
ones failing the equity floor. Strengths are estimated from actual cards,
not chosen to make the aggression target pass.
"""

import json
from pathlib import Path
from random import Random
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from bot.equity import equity
from bot.policy import CONFIG, action_probabilities, half_parameters, sample_action
from bot.preflop import preflop_strength
from evaluator import warmup
from game import Action, Street
from tests.fuzz_states import fuzz_hands

RAISES = (Action.RAISE_HALF, Action.RAISE_POT)


def profile_policy(count=4000, states=None):
    warmup()
    if states is None:
        states = []
        fuzz_hands(states.append)
    selection = Random(301)
    raise_states = [obs for obs in states if any(a in obs.legal_actions for a in RAISES)]
    observations = selection.sample(raise_states, min(count, len(raise_states)))
    equity_rng = Random(302)
    cache = {}
    strengths = []
    for obs in observations:
        key = (obs.hole_cards, obs.board)
        if key not in cache:
            cache[key] = (preflop_strength(obs.hole_cards) if obs.street == Street.PREFLOP else
                          equity(obs.hole_cards, obs.board, equity_rng, samples=24))
        strengths.append(cache[key])
    params = half_parameters(Random(303))
    report = {"fuzz_states": len(states), "raise_legal_sample": len(observations), "gears": {}}
    free_states = [obs for obs in states if obs.to_call == 0 and any(a in obs.legal_actions for a in RAISES)]
    low_observations = selection.sample(free_states, min(count, len(free_states)))
    for gear in CONFIG["gears"]:
        rng = Random(f"policy-{gear}")
        raises, expected = 0, 0.0
        for obs, strength in zip(observations, strengths):
            distribution = action_probabilities(obs, strength, gear, params)
            expected += sum(distribution.get(a, 0) for a in RAISES)
            raises += sample_action(obs, strength, gear, rng, params) in RAISES
        low_raises = sum(sample_action(obs, 0.10, gear, rng, params) in RAISES for obs in low_observations)
        report["gears"][gear] = {
            "raise_rate": raises / len(observations),
            "expected_raise_rate": expected / len(observations),
            "low_equity_free_raise_rate": low_raises / len(low_observations),
            "low_equity_free_spots": len(low_observations),
        }
    return report


if __name__ == "__main__":
    print(json.dumps(profile_policy(), indent=2))
