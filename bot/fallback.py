"""Half-local runtime state and strength estimation for the mixed policy."""

from bot.equity import equity, reset_rng
from bot.preflop import preflop_strength
from bot.governor import TimeGovernor
from bot.policy import CONFIG, half_parameters, sample_action
from game import AgentConfig, Street

class State:
    def __init__(self, config):
        self.config = config
        self.rng = reset_rng()
        self.gear = CONFIG["default_gear"]
        self.gear_parameters = half_parameters(self.rng)
        self.governor = TimeGovernor(config.num_hands, min(4.0, config.time_bank_seconds * 0.75))
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
                equity(obs.hole_cards, obs.board, state.rng,
                       samples=state.governor.samples_for(len(obs.board)),
                       deadline=state.governor.deadline))
    return sample_action(obs, strength, state.gear, state.rng, state.gear_parameters)
