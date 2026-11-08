"""Fair parameterized opponents attacking public gear/detector behavior only.

No Jester imports, private-information reads, sleeps or cross-server requests.
Frozen evolved bots keep their own copy of this implementation.
"""

from collections import Counter
from random import Random
from time import perf_counter

from evaluator import NUM_CARDS, card_rank, card_suit, omaha_score, warmup
from game import Action, Street

warmup()
PARAMETERS = dict(idea="balanced", seed=17, samples=48, preflop_samples=20,
                  preflop_floor=.0, call_floor=.0, call_margin=.025,
                  raise_threshold=.66, raise_frequency=.9, bluff=.035,
                  pot_fraction=.8, reraise_threshold=.70, bait_length=15,
                  switch_every=100, range_bias=.0, free_raise=.0)


def initialize(config, memory, parameters):
    memory.clear()
    memory.update(config=config, rng=Random(parameters.get("seed", 17)), elapsed=0.,
                  scale=1., hand=-1, seen=0, opponent_actions=0, opponent_raises=0,
                  facing=0, folded=0)


def quality(cards):
    """Cheap range feature, not a private-information or engine shortcut."""
    ranks = Counter(map(card_rank, cards))
    suits = Counter(map(card_suit, cards))
    high = sum(r / 8 for r in ranks) / 5
    pairs = sum((.12 + .15 * r / 8) for r, n in ranks.items() if n == 2)
    dead = sum(.13 * (n - 2) for n in ranks.values() if n >= 3)
    links = sum(1 for r in ranks for s in ranks if r < s <= r + 2) * .025
    suited = sum(.06 for n in suits.values() if n >= 2)
    return max(0., min(1., .15 + .55 * high + pairs + links + suited - dead))


def observe(obs, memory):
    if obs.hand_index != memory["hand"]:
        memory["hand"], memory["seen"] = obs.hand_index, 0
    for event in obs.action_history[memory["seen"]:]:
        if not event.is_me:
            memory["opponent_actions"] += 1
            memory["opponent_raises"] += event.action in (Action.RAISE_HALF, Action.RAISE_POT)
    memory["seen"] = len(obs.action_history)


def estimate(obs, memory, parameters):
    """Uniform or public-action-weighted MC with a half-wide public governor."""
    config = memory["config"]
    projected = memory["elapsed"] * config.num_hands / max(1, obs.hand_index + 1)
    target = min(4.8, config.time_bank_seconds * .60)
    if obs.hand_index >= 12 and projected > target:
        memory["scale"] = min(memory["scale"], max(.125, target / projected))
    count = max(6, int(parameters.get("preflop_samples", 20) if not obs.board
                       else parameters.get("samples", 48)))
    count = max(6, int(count * memory["scale"]))
    rng = memory["rng"]
    unseen = [c for c in range(NUM_CARDS) if c not in obs.hole_cards and c not in obs.board]
    missing = 5 - len(obs.board)
    fixed = omaha_score(obs.hole_cards, obs.board) if not missing else None
    rate = memory["opponent_raises"] / max(1, memory["opponent_actions"])
    bias = parameters.get("range_bias", 0) if obs.to_call and rate < .45 else 0
    wins = total = 0.
    deadline = perf_counter() + .025
    for _ in range(count):
        draw = rng.sample(unseen, 5 + missing)
        board = (*obs.board, *draw[5:])
        ours = fixed if fixed is not None else omaha_score(obs.hole_cards, board)
        theirs = omaha_score(draw[:5], board)
        # Importance weights, not rejection loops; all samples use normal
        # unseen cards and a bounded fixed count independent of our strength.
        weight = (1 - bias) + bias * (1 + 4 * max(0, quality(draw[:5]) - .45))
        wins += weight * ((ours > theirs) + .5 * (ours == theirs))
        total += weight
        if perf_counter() >= deadline:
            break
    return wins / total if total else .5


def choose(obs, memory, parameters):
    start = perf_counter()
    try:
        if "config" not in memory:
            from game import AgentConfig
            initialize(AgentConfig(), memory, parameters)
        observe(obs, memory)
        p = dict(PARAMETERS, **parameters)
        rng = memory["rng"]
        strength = estimate(obs, memory, p)
        call = min(obs.to_call, obs.my_stack)
        odds = call / max(1, obs.pot + call)
        raise_actions = [a for a in (Action.RAISE_HALF, Action.RAISE_POT) if a in obs.legal_actions]
        floor, threshold, bluff = max(p["call_floor"], odds + p["call_margin"]), p["raise_threshold"], p["bluff"]
        if obs.street == Street.PREFLOP:
            floor = max(floor, p["preflop_floor"])
        idea = p["idea"]
        # The source of these attacks is Jester's published gear priority:
        # >55% folds pins MANIAC even when losing, >35% re-raises invites TRAP,
        # and K uninterrupted check/folds enables forced half-pot raises.
        if idea in ("folder_lock", "value_trap"):
            floor = max(floor, .56 if idea == "folder_lock" else .51)
            threshold = max(threshold, .79)
            bluff = 0
        elif idea == "reraise_bait":
            if obs.hand_index < p["bait_length"]:
                threshold, bluff = .40, .70
            else:
                threshold, floor, bluff = .67, max(floor, .40), .01
        elif idea == "detector_bait":
            if obs.hand_index % max(2 * p["bait_length"], 40) < p["bait_length"]:
                return Action.FOLD if call and Action.FOLD in obs.legal_actions else Action.CHECK_CALL
            floor, threshold, bluff = max(floor, .47), .66, 0
        elif idea == "street_pressure":
            bluff = min(.85, bluff + (.22 if obs.street == Street.FLOP and obs.is_button else 0))
            floor += .04 if obs.street == Street.RIVER and call else 0
        elif idea == "gear_cycle":
            cycle = (obs.hand_index // max(25, p["switch_every"])) % 3
            floor += (.10, -.06, .03)[cycle]
            threshold += (.08, -.12, 0)[cycle]
            bluff = (.01, .45, .04)[cycle]
        if call and strength < floor:
            return Action.FOLD if Action.FOLD in obs.legal_actions else Action.CHECK_CALL
        reraising = call and obs.raises_this_street > 0
        value = strength >= (max(threshold, p["reraise_threshold"]) if reraising else threshold)
        # Slow-play selected value versus MANIAC's nearly forced opening bets.
        if idea == "value_trap" and obs.street != Street.RIVER and strength < .82:
            value = False
        frequency = p["raise_frequency"] if value else bluff
        if not call:
            frequency = max(frequency, p["free_raise"])
        if raise_actions and rng.random() < frequency:
            desired = Action.RAISE_POT if rng.random() < p["pot_fraction"] else Action.RAISE_HALF
            return desired if desired in raise_actions else raise_actions[0]
        return Action.CHECK_CALL
    finally:
        memory["elapsed"] = memory.get("elapsed", 0) + perf_counter() - start
