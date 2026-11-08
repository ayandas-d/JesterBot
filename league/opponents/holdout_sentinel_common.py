"""Fixed validation-only policies, declared before any Phase 2 holdout scores.

Two versions are reserved in advance for deterministic holdout rotation. They
do not import Jester or consume training/holdout results.
"""

from time import perf_counter

from game import Action
from league.opponents.common import estimate

CONFIG = {
    "a": {"margin": .030, "strong": .70, "medium": .54,
          "strong_raise": .88, "medium_raise": .50, "bluff": .04, "half": .65},
    "b": {"margin": .025, "strong": .68, "medium": .56,
          "strong_raise": .85, "medium_raise": .60, "bluff": .04, "half": .55},
}


def choose(obs, memory, version):
    start = perf_counter()
    try:
        cfg = CONFIG[version]
        strength = estimate(obs, memory, 32)
        call = min(obs.to_call, obs.my_stack)
        odds = call / max(1, obs.pot + call)
        if call and strength < odds + cfg["margin"] and Action.FOLD in obs.legal_actions:
            return Action.FOLD
        frequency = (cfg["strong_raise"] if strength >= cfg["strong"] else
                     cfg["medium_raise"] if strength >= cfg["medium"] else cfg["bluff"])
        draw = memory["rng"].random()
        preferred = Action.RAISE_HALF if memory["rng"].random() < cfg["half"] else Action.RAISE_POT
        if draw < frequency:
            for action in (preferred, Action.RAISE_HALF, Action.RAISE_POT):
                if action in obs.legal_actions:
                    return action
        return Action.CHECK_CALL
    finally:
        memory["elapsed"] += perf_counter() - start
