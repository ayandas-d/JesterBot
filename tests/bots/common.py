"""Independent test-opponent equity estimator; no imports from our bot."""

from random import Random
from time import perf_counter

from evaluator import NUM_CARDS, omaha_score, warmup
from game import Action

warmup()


def initialize(config, memory):
    memory.clear()
    memory.update(config=config, rng=Random(0), elapsed=0.0, sample_scale=1.0)


def estimate(obs, memory, samples):
    config = memory["config"]
    # Same sample count for every strength at a given public pacing state.
    target = min(2.2, config.time_bank_seconds * .35)
    projected = memory["elapsed"] * config.num_hands / max(1, obs.hand_index + 1)
    if obs.hand_index >= 20 and projected > target:
        memory["sample_scale"] = min(memory["sample_scale"], max(.20, target / projected))
    count = max(8, int(samples * memory["sample_scale"]))
    unseen = [c for c in range(NUM_CARDS) if c not in obs.hole_cards and c not in obs.board]
    missing = 5 - len(obs.board)
    fixed = omaha_score(obs.hole_cards, obs.board) if not missing else None
    wins = done = 0
    deadline = perf_counter() + .020
    for _ in range(count):
        if perf_counter() >= deadline:
            break
        draw = memory["rng"].sample(unseen, 5 + missing)
        board = (*obs.board, *draw[5:]) if missing else obs.board
        ours = omaha_score(obs.hole_cards, board) if fixed is None else fixed
        theirs = omaha_score(draw[:5], board)
        wins += (ours > theirs) + .5 * (ours == theirs)
        done += 1
    return wins / done if done else .5


def equity_action(obs, strength):
    call = min(obs.to_call, obs.my_stack)
    odds = call / max(1, obs.pot + call)
    if call and strength < odds and Action.FOLD in obs.legal_actions:
        return Action.FOLD
    if strength >= .60 and Action.RAISE_POT in obs.legal_actions:
        return Action.RAISE_POT
    return Action.CHECK_CALL
