"""Regressions for judge-charged work outside choose_action's internal timer."""

import pytest

import agent
from bot.fallback import State
from game import Action, AgentConfig, Game, make_deal


def test_governor_reserves_headroom_for_measured_external_request_cost():
    state = State(AgentConfig())
    # Observed failing halves had 0.9–1.2 s of charges outside the internal
    # choose timer. A 3 s choose pace therefore cannot consume the full budget.
    for hand in range(500):
        state.governor.record(hand, .003)
    assert state.governor.scale < 1


def test_result_callback_work_is_accounted_without_counting_a_decision(monkeypatch):
    memory = {}
    agent.new_half(AgentConfig(), memory)
    game = Game(make_deal("callback-budget", 0), 0)
    game.apply(Action.FOLD)
    ticks = iter((10.0, 10.5))
    monkeypatch.setattr(agent, "monotonic", lambda: next(ticks))
    agent.on_hand_end(game.hand_result(0), memory)
    assert memory["bot"].governor.total_seconds == pytest.approx(.5)
    assert memory["bot"].governor.decisions == 0


def test_normal_fast_pace_keeps_full_samples():
    state = State(AgentConfig())
    for hand in range(500):
        state.governor.record(hand, .001)
    assert state.governor.scale == 1
