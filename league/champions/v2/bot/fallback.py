"""Half-local runtime state and strength estimation for the mixed policy."""

from bot.equity import equity, reset_rng
from bot.preflop import preflop_strength
from bot.governor import TimeGovernor
from bot.opponent import OpponentModel
from bot.gears import GearSelector
from bot.timing import PhasedTiming
from bot.policy import CONFIG, half_parameters, sample_action
from game import Action, AgentConfig, Street

class State:
    def __init__(self, config):
        self.config = config
        self.rng = reset_rng()
        self.gear = CONFIG["default_gear"]
        self.gear_parameters = half_parameters(self.rng)
        self.governor = TimeGovernor(config.num_hands, min(4.0, config.time_bank_seconds * 0.75))
        self.hands_played = 0
        self.opponent = OpponentModel(config)
        self.selector = GearSelector()
        self.timing = PhasedTiming()

    def end(self, result):
        if self.opponent.end(result, self.gear):
            self.timing.end(self.opponent.recent[-1])
            self.hands_played += 1
            self.gear = self.selector.evaluate(self.hands_played, self.opponent.rolling, self.gear)


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
    # Still estimate strength with the same sample budget during exploitation.
    if state.opponent.exploit_checkfold:
        for action in (Action.RAISE_HALF, Action.RAISE_POT):
            if action in obs.legal_actions:
                return action
    return sample_action(obs, strength, state.gear, state.rng, state.gear_parameters,
                         bluff_multiplier=(state.selector.bluff_multiplier(state.gear)
                                           * state.timing.bluff_multiplier(obs.hand_index)))
