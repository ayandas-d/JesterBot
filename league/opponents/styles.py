"""Independent adversaries for the improvement league, not submission policy."""

from random import Random
from time import perf_counter

from game import Action, Street
from league.opponents.common import initialize, estimate, equity_action

CONFIG = {
    "samples": 32,
    "anti_maniac": {"call_margin": -.05, "minimum_call": .30, "raise": .65},
    "adaptive_counter": {"minimum_events": 40, "high_raise_rate": .50, "low_raise_rate": .25},
    "gto_ish": {"buckets": ((.35, .10), (.55, .20), (.70, .65), (1.01, .85)), "pot_fraction": .60},
    "tight_aggressive": {"preflop_floor": .58, "call_margin": .05, "raise": .60},
    "loose_passive": {"call_margin": -.12, "minimum_call": .15, "raise_frequency": .02},
    "bluff_heavy": {"weak_raise": .80, "strong_raise": .90, "reraise_floor": .70},
    "erratic": {"minimum_hands": 50, "maximum_hands": 200},
    "slow_starter": {"earliest": .35, "latest": .75},
    "crashy": {"start_fraction": .35, "error_probability": .25},
}


def initialize_style(style, config, memory):
    initialize(config, memory)
    rng = memory["style_rng"] = Random(style)
    memory.update(seen_hand=-1, seen_actions=0, opponent_actions=0, opponent_raises=0,
                  next_style_hand=rng.randint(50, 200), current_style="loose_passive")
    lo = max(1, int(config.num_hands * CONFIG["slow_starter"]["earliest"]))
    hi = max(lo + 1, int(config.num_hands * CONFIG["slow_starter"]["latest"]))
    memory["collapse_hand"] = rng.randrange(lo, hi)


def observe(obs, memory):
    if memory["seen_hand"] != obs.hand_index:
        memory["seen_hand"], memory["seen_actions"] = obs.hand_index, 0
    for event in obs.action_history[memory["seen_actions"]:]:
        if not event.is_me:
            memory["opponent_actions"] += 1
            memory["opponent_raises"] += event.action in (Action.RAISE_HALF, Action.RAISE_POT)
    memory["seen_actions"] = len(obs.action_history)


def choose_style(style, obs, memory):
    started = perf_counter()
    try:
        observe(obs, memory)
        rng = memory["style_rng"]
        if style == "crashy":
            cfg = CONFIG[style]
            if obs.hand_index >= int(memory["config"].num_hands * cfg["start_fraction"]) and rng.random() < cfg["error_probability"]:
                raise RuntimeError("intentional league fault: crashy")
        if style == "slow_starter" and obs.hand_index >= memory["collapse_hand"]:
            return Action.FOLD if obs.to_call else Action.CHECK_CALL
        if style == "erratic":
            while obs.hand_index >= memory["next_style_hand"]:
                memory["current_style"] = rng.choice([name for name in
                    ("anti_maniac", "tight_aggressive", "loose_passive", "bluff_heavy")
                    if name != memory["current_style"]])
                cfg = CONFIG[style]
                memory["next_style_hand"] += rng.randint(cfg["minimum_hands"], cfg["maximum_hands"])
            style = memory["current_style"]
        strength = estimate(obs, memory, CONFIG["samples"])
        call = min(obs.to_call, obs.my_stack)
        odds = call / max(1, obs.pot + call)
        can_raise = Action.RAISE_POT in obs.legal_actions
        if style in ("slow_starter", "crashy"):
            return equity_action(obs, strength)
        if style == "adaptive_counter":
            cfg = CONFIG[style]
            rate = memory["opponent_raises"] / max(1, memory["opponent_actions"])
            margin, threshold = .02, .62
            if memory["opponent_actions"] >= cfg["minimum_events"]:
                if rate > cfg["high_raise_rate"]:
                    margin, threshold = -.04, .66
                elif rate < cfg["low_raise_rate"]:
                    margin, threshold = .07, .60
            if call and strength < max(.25, odds + margin):
                return Action.FOLD
            return Action.RAISE_POT if can_raise and strength >= threshold else Action.CHECK_CALL
        if style == "anti_maniac":
            cfg = CONFIG[style]
            if call and strength < max(cfg["minimum_call"], odds + cfg["call_margin"]):
                return Action.FOLD
            return Action.RAISE_POT if can_raise and strength >= cfg["raise"] else Action.CHECK_CALL
        if style == "tight_aggressive":
            cfg = CONFIG[style]
            floor = cfg["preflop_floor"] if obs.street == Street.PREFLOP else odds + cfg["call_margin"]
            if call and strength < floor:
                return Action.FOLD
            return Action.RAISE_POT if can_raise and strength >= cfg["raise"] else Action.CHECK_CALL
        if style == "loose_passive":
            cfg = CONFIG[style]
            if call and strength < max(cfg["minimum_call"], odds + cfg["call_margin"]):
                return Action.FOLD
            return Action.RAISE_HALF if can_raise and rng.random() < cfg["raise_frequency"] else Action.CHECK_CALL
        if style == "bluff_heavy":
            cfg = CONFIG[style]
            if call and obs.raises_this_street >= 2 and strength < cfg["reraise_floor"]:
                return Action.FOLD
            frequency = cfg["weak_raise"] if strength < .5 else cfg["strong_raise"]
            if can_raise and rng.random() < frequency:
                return Action.RAISE_POT
            return Action.FOLD if call and strength < odds else Action.CHECK_CALL
        if style == "gto_ish":
            cfg = CONFIG[style]
            if call and strength < odds:
                return Action.FOLD
            frequency = next(p for ceiling, p in cfg["buckets"] if strength < ceiling)
            if can_raise and rng.random() < frequency:
                return Action.RAISE_POT if rng.random() < cfg["pot_fraction"] else Action.RAISE_HALF
            return Action.CHECK_CALL
        raise ValueError(f"unknown opponent style: {style}")
    finally:
        memory["elapsed"] += perf_counter() - started
