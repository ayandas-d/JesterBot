"""Safety submission: no opponent model, timing tells or adaptive gears."""

from random import Random

from bot.equity import equity, preflop_strength
from game import Action, AgentConfig, Street

POSTFLOP_SAMPLES = 24


class State:
    def __init__(self, config):
        self.config = config
        self.rng = Random()
        self.hands_played = 0

    def end(self, result):
        self.hands_played += 1


def get_state(memory):
    if not isinstance(memory.get("bot"), State):
        memory["bot"] = State(AgentConfig())
    memory.setdefault("safety_errors", 0)
    return memory["bot"]


def policy(obs, state):
    preflop = obs.street == Street.PREFLOP
    strength = (preflop_strength(obs.hole_cards) if preflop else
                equity(obs.hole_cards, obs.board, state.rng, samples=POSTFLOP_SAMPLES))
    call = min(obs.to_call, obs.my_stack)
    pot_odds = call / max(1, obs.pot + call)
    if call and strength < pot_odds + 0.035:
        return Action.FOLD if Action.FOLD in obs.legal_actions else Action.CHECK_CALL

    # The preflop score is only a cheap heuristic; separate thresholds avoid
    # pretending it is calibrated equity. All sizing uses engine legal actions.
    half_threshold = 0.57 if preflop else 0.60
    pot_threshold = 0.65 if preflop else 0.76
    if strength >= pot_threshold and Action.RAISE_POT in obs.legal_actions:
        return Action.RAISE_POT
    if strength >= half_threshold and Action.RAISE_HALF in obs.legal_actions:
        return Action.RAISE_HALF
    return Action.CHECK_CALL
