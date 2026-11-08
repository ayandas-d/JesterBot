"""Data-driven mixed policies with bounded opponent-model bluff adjustments."""

from copy import deepcopy
from math import isfinite

from game import Action, Street

# All strategic thresholds, frequencies and opening settings live here.
# Strength is equity postflop and the conservative preflop proxy before it.
CONFIG = {
    "default_gear": "MANIAC",
    "threshold_jitter": 0.012,
    "big_bet_pot_fraction": 0.40,
    "gears": {
        "MANIAC": {
            "thresholds": {
                "PREFLOP": {"medium": 0.48, "strong": 0.58, "top": 0.65},
                "POSTFLOP": {"medium": 0.48, "strong": 0.65, "top": 0.84},
            },
            "raise": {"weak": 0.98, "medium": 0.98, "strong": 0.99, "top": 0.99},
            "pot_fraction": 0.78,
            "call_margin": -0.035,
            "big_call_margin": -0.035,
            "continue_weak": 0.995,
            "reraise_multiplier": 1.0,
            "big_bet_raise_multiplier": 1.0,
        },
        "AGGRO": {
            "thresholds": {
                "PREFLOP": {"medium": 0.48, "strong": 0.57, "top": 0.65},
                "POSTFLOP": {"medium": 0.46, "strong": 0.62, "top": 0.82},
            },
            "raise": {"weak": 0.12, "medium": 0.68, "strong": 0.91, "top": 0.97},
            "pot_fraction": 0.58,
            "call_margin": 0.015,
            "big_call_margin": 0.04,
            "continue_weak": 0.75,
            "reraise_multiplier": 0.85,
            "big_bet_raise_multiplier": 0.85,
        },
        "VALUE": {
            "thresholds": {
                "PREFLOP": {"medium": 0.50, "strong": 0.58, "top": 0.65},
                "POSTFLOP": {"medium": 0.52, "strong": 0.64, "top": 0.81},
            },
            "raise": {"weak": 0.005, "medium": 0.76, "strong": 0.94, "top": 0.98},
            "pot_fraction": 0.84,
            "call_margin": 0.025,
            "big_call_margin": 0.04,
            "continue_weak": 0.65,
            "reraise_multiplier": 0.90,
            "big_bet_raise_multiplier": 0.90,
        },
        "TRAP": {
            "thresholds": {
                "PREFLOP": {"medium": 0.48, "strong": 0.56, "top": 0.65},
                "POSTFLOP": {"medium": 0.48, "strong": 0.62, "top": 0.85},
            },
            "raise": {"weak": 0.025, "medium": 0.10, "strong": 0.18, "top": 0.92},
            "pot_fraction": 0.70,
            "call_margin": 0.0,
            "big_call_margin": 0.025,
            "continue_weak": 0.90,
            "reraise_multiplier": 1.0,
            "big_bet_raise_multiplier": 1.0,
        },
    },
}


def half_parameters(rng):
    """Copy config and draw small, fixed-for-the-half threshold offsets.

    Price floors stay exact: jitter must not loosen the promised protection
    against continuing far below pot odds. The shared config is never mutated.
    """
    parameters = deepcopy(CONFIG["gears"])
    jitter = CONFIG["threshold_jitter"]
    for gear in parameters.values():
        for thresholds in gear["thresholds"].values():
            offset = rng.uniform(-jitter, jitter)
            for band in thresholds:
                thresholds[band] += offset
    return parameters


def action_probabilities(obs, strength, gear=None, parameters=None, bluff_multiplier=1.0):
    """Return a normalized distribution whose keys are exactly legal actions.

    Medium postflop equity includes live draws through their runout equity.
    No made-hand category shortcut is needed to recognize their value.
    """
    if not isfinite(strength) or not 0 <= strength <= 1:
        raise ValueError("strength must be finite and in [0, 1]")
    if not obs.legal_actions:
        raise ValueError("a policy decision requires legal actions")
    gear = CONFIG["default_gear"] if gear is None else gear
    params = (CONFIG["gears"] if parameters is None else parameters)[gear]
    probabilities = dict.fromkeys(obs.legal_actions, 0.0)
    call = min(obs.to_call, obs.my_stack)
    odds = call / max(1, obs.pot + call)
    big_bet = call > 0 and call / max(1, obs.pot) >= CONFIG["big_bet_pot_fraction"]
    margin = params["big_call_margin"] if big_bet else params["call_margin"]
    if call and strength < odds + margin:
        fallback = Action.FOLD if Action.FOLD in probabilities else Action.CHECK_CALL
        probabilities[fallback] = 1.0
        return probabilities

    thresholds = params["thresholds"]["PREFLOP" if obs.street == Street.PREFLOP else "POSTFLOP"]
    # Always compare all three thresholds. Preserve the old priority even if
    # a teammate temporarily configures thresholds out of order.
    top = strength >= thresholds["top"]
    strong = strength >= thresholds["strong"]
    medium = strength >= thresholds["medium"]
    band_index = 3 * top + (1 - top) * (2 * strong + (1 - strong) * medium)
    band = ("weak", "medium", "strong", "top")[band_index]
    raises = [action for action in (Action.RAISE_HALF, Action.RAISE_POT) if action in probabilities]
    raise_probability = params["raise"][band] if raises else 0.0
    adjusted = max(0.0, min(1.0, raise_probability * bluff_multiplier))
    raise_probability = adjusted if band == "weak" else raise_probability
    if call and obs.raises_this_street >= 2:
        raise_probability *= params["reraise_multiplier"]
    if big_bet:
        raise_probability *= params["big_bet_raise_multiplier"]
    if len(raises) == 2:
        probabilities[Action.RAISE_POT] = raise_probability * params["pot_fraction"]
        probabilities[Action.RAISE_HALF] = raise_probability * (1 - params["pot_fraction"])
    elif raises:
        probabilities[raises[0]] = raise_probability

    remaining = 1 - raise_probability
    weak_continuation = params["continue_weak"]
    continuation = weak_continuation if call and band == "weak" else 1.0
    probabilities[Action.CHECK_CALL] = remaining * continuation
    if Action.FOLD in probabilities:
        probabilities[Action.FOLD] = remaining * (1 - continuation)
    else:
        probabilities[Action.CHECK_CALL] = remaining
    total = sum(probabilities.values())
    if not total > 0 or any(not isfinite(p) or p < 0 for p in probabilities.values()):
        raise ValueError("invalid configured action probabilities")
    return {action: probability / total for action, probability in probabilities.items()}


def sample_action(obs, strength, gear, rng, parameters=None, bluff_multiplier=1.0):
    probabilities = action_probabilities(obs, strength, gear, parameters, bluff_multiplier)
    point = rng.random()
    cumulative = 0.0
    last_positive = Action.CHECK_CALL
    for action, probability in probabilities.items():
        if probability > 0:
            last_positive = action
            cumulative += probability
            if point < cumulative:
                return action
    return last_positive  # floating-point roundoff cannot select a zero weight
