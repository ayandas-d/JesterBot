"""Fair adversary contracts; these opponents receive only normal observations."""

from random import Random

import pytest

from game import Action, AgentConfig, Game, make_deal
from league.opponents.parametric import PARAMETERS, choose, initialize


@pytest.mark.parametrize("idea", ["balanced", "folder_lock", "reraise_bait", "detector_bait",
                                  "street_pressure", "range_reader", "gear_cycle", "value_trap"])
def test_parameter_family_uses_only_legal_actions_and_never_free_folds(idea):
    memory = {}
    parameters = dict(PARAMETERS, idea=idea)
    initialize(AgentConfig(num_hands=40), memory, parameters)
    rng = Random(idea)
    for i in range(40):
        game = Game(make_deal("fair-family", i), i % 2, hand_index=i)
        while not game.is_terminal:
            obs = game.observation(game.to_act)
            action = choose(obs, memory, parameters) if game.to_act == 0 else rng.choice(obs.legal_actions)
            assert action in obs.legal_actions
            if not obs.to_call:
                assert action != Action.FOLD
            game.apply(action)


def test_family_resets_all_memory_and_is_seed_reproducible():
    memories = [{"stale": [1]}, {}]
    obs = Game(make_deal("reset-family", 0), 0).observation(0)
    actions = []
    for memory in memories:
        initialize(AgentConfig(), memory, PARAMETERS)
        assert "stale" not in memory
        actions.append(choose(obs, memory, PARAMETERS))
    assert actions[0] == actions[1]
