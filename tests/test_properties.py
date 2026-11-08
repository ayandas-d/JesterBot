"""Reachable engine states generated and shrunk by Hypothesis."""

from math import isfinite
from random import Random

from hypothesis import given, settings, strategies as st

import agent
from bot.equity import equity
from bot.fallback import State, policy
from bot.policy import CONFIG, action_probabilities, half_parameters, sample_action
from bot.preflop import preflop_score
from game import Action, AgentConfig, Deal, Game


@st.composite
def reachable_observations(draw):
    cards = draw(st.lists(st.integers(0, 35), min_size=15, max_size=15, unique=True))
    game = Game(Deal((tuple(cards[:5]), tuple(cards[5:10])), tuple(cards[10:])),
                draw(st.integers(0, 1)), draw(st.integers(0, 999)))
    choices = draw(st.lists(st.integers(0, 7), max_size=30))
    obs = game.observation(game.to_act)
    for choice in choices:
        obs = game.observation(game.to_act)
        # Include check/call-heavy walks to reach every later street.
        action = Action.CHECK_CALL if choice >= 4 else obs.legal_actions[choice % len(obs.legal_actions)]
        game.apply(action)
        if game.is_terminal:
            return obs
    return game.observation(game.to_act)


@settings(max_examples=160, deadline=None, derandomize=True, database=None)
@given(reachable_observations(), st.floats(min_value=0, max_value=1, allow_nan=False, allow_infinity=False))
def test_all_gears_modules_and_entrypoint_preserve_legality(obs, strength):
    rng = Random(610)
    params = half_parameters(rng)
    assert 0 <= preflop_score(obs.hole_cards) <= 1
    measured = equity(obs.hole_cards, obs.board, Random(611), samples=8)
    assert 0 <= measured <= 1
    state = State(AgentConfig())
    state.opponent.observe(obs, state.gear)
    state.timing.observe(obs, state.opponent, 1.0)
    for gear in CONFIG["gears"]:
        probabilities = action_probabilities(obs, strength, gear, params)
        assert set(probabilities) == set(obs.legal_actions)
        assert all(isfinite(p) and 0 <= p <= 1 for p in probabilities.values())
        assert abs(sum(probabilities.values()) - 1) < 1e-12
        assert sample_action(obs, strength, gear, rng, params) in obs.legal_actions
        state.gear = gear
        assert policy(obs, state) in obs.legal_actions
        if not obs.to_call:
            assert probabilities.get(Action.FOLD, 0) == 0
    memory = {}
    action = agent.choose_action(obs, memory)
    assert action in obs.legal_actions and memory["safety_errors"] == 0
    if not obs.to_call:
        assert action != Action.FOLD


def test_reset_replays_same_half_inputs_and_decisions(monkeypatch):
    from game import make_deal
    monkeypatch.setenv("BOT_SEED", "property-half-reset")
    memory = {}
    outputs = []
    for repeat in range(2):
        agent.new_half(AgentConfig(), memory)
        # Remove wall-clock budget adaptation from a seeded reset property.
        memory["bot"].governor.budget_seconds = 1_000_000
        rng = Random(612)
        actions = []
        for index in range(40):
            game = Game(make_deal("reset-property", index), index % 2, hand_index=index)
            while not game.is_terminal:
                obs = game.observation(game.to_act)
                action = agent.choose_action(obs, memory) if game.to_act == 0 else rng.choice(obs.legal_actions)
                actions.append(action)
                game.apply(action)
            agent.on_hand_end(game.hand_result(0), memory)
        state = memory["bot"]
        assert memory["safety_errors"] == 0
        outputs.append((actions, state.rng.getstate(), state.opponent.whole.events.copy()))
        memory["stale"] = True
    assert "stale" in memory  # sentinel was added only after the second replay
    assert outputs[0] == outputs[1]
    agent.new_half(AgentConfig(), memory)
    assert "stale" not in memory and memory["bot"].hands_played == 0
    assert not memory["bot"].opponent.recent and memory["bot"].timing.last is None
