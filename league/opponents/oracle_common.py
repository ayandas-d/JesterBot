"""Unfair test-only strategies; refuse to run without the oracle judge payload."""

from time import perf_counter

from evaluator import NUM_CARDS, omaha_score
from game import Action
from league.opponents.parametric import initialize as init_family, PARAMETERS


def initialize(config, memory):
    init_family(config, memory, PARAMETERS)


def estimate(obs, memory, extra):
    kind = extra["kind"]
    known = tuple(extra.get("opponent_hole", ()))
    next_card = extra.get("next_board_card")
    future = (next_card,) if next_card is not None and len(obs.board) < 5 else ()
    used = set((*obs.hole_cards, *obs.board, *known, *future))
    unseen = [c for c in range(NUM_CARDS) if c not in used]
    missing_opponent, missing_board = 5-len(known), 5-len(obs.board)-len(future)
    count = (256 if not obs.board else 1024) if kind == "unlimited_compute" else 64
    if kind != "unlimited_compute":
        config = memory["config"]
        projection = memory["elapsed"] * config.num_hands / max(1, obs.hand_index+1)
        if obs.hand_index >= 12 and projection > 4.8:
            memory["scale"] = min(memory["scale"], max(.125, 4.8/projection))
        count = max(8, int(count*memory["scale"]))
    if not missing_opponent and not missing_board:
        count = 1
    fixed = omaha_score(obs.hole_cards, obs.board) if len(obs.board) == 5 else None
    wins = 0.
    for _ in range(count):
        draw = memory["rng"].sample(unseen, missing_opponent+missing_board)
        opponent = (*known, *draw[:missing_opponent])
        board = (*obs.board, *future, *draw[missing_opponent:])
        ours = fixed if fixed is not None else omaha_score(obs.hole_cards, board)
        theirs = omaha_score(opponent, board)
        wins += (ours > theirs) + .5*(ours == theirs)
    return wins/count


def choose(kind, obs, memory, extra):
    if not isinstance(extra, dict) or extra.get("kind") != kind:
        raise ValueError("Cheater opponents require the separate oracle judge")
    start = perf_counter()
    try:
        strength = estimate(obs, memory, extra)
        call = min(obs.to_call, obs.my_stack)
        odds = call/max(1, obs.pot+call)
        floor, threshold, bluff = odds, .59, 0.
        if kind == "oracle_full":
            threshold = .54
        elif kind == "oracle_counter":
            state = extra.get("target_state") or {}
            gear = state.get("gear", "MANIAC")
            if gear == "MANIAC":
                floor, threshold = max(.25, odds-.04), .61
            elif gear == "TRAP":
                threshold, bluff = .62, .14 if not call else .02
            else:
                floor, threshold = odds+.045, .69
            if state.get("exploit_checkfold"):
                floor = max(.20, odds-.06)
        if call and strength < floor and Action.FOLD in obs.legal_actions:
            return Action.FOLD
        if strength >= threshold or memory["rng"].random() < bluff:
            for action in (Action.RAISE_POT, Action.RAISE_HALF):
                if action in obs.legal_actions:
                    return action
        return Action.CHECK_CALL
    finally:
        memory["elapsed"] += perf_counter()-start
