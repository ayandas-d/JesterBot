"""Half-long state bounds, stationary timing probes and module failure recovery."""

import pickle
from random import Random
from statistics import median
from time import perf_counter

import pytest

import agent
from bot import fallback
from game import Action, AgentConfig, Game, make_deal


def flop():
    game = Game(make_deal("robust-flop", 0), 0)
    game.apply(Action.CHECK_CALL)
    game.apply(Action.CHECK_CALL)
    return game.observation(game.to_act)


def test_state_is_bounded_and_stationary_probe_time_does_not_drift(monkeypatch, record_property):
    monkeypatch.setenv("BOT_SEED", "robustness-half")
    memory = {}
    agent.new_half(AgentConfig(), memory)
    state = memory["bot"]
    rng = Random(630)
    probe = flop()
    probes, sizes = [], {}
    for index in range(1000):
        game = Game(make_deal("bounded-half", index), index % 2, hand_index=index)
        while not game.is_terminal:
            obs = game.observation(game.to_act)
            action = agent.choose_action(obs, memory) if game.to_act == 0 else rng.choice(obs.legal_actions)
            assert action in obs.legal_actions
            game.apply(action)
        agent.on_hand_end(game.hand_result(0), memory)
        start = perf_counter()
        fallback.policy(probe, state)  # constant cards/street isolate state-age cost
        probes.append(perf_counter() - start)
        assert len(state.opponent.recent) <= 100
        assert all(len(hand.history) <= 40 for hand in state.opponent.recent)
        assert all(len(window) <= 128 for window in state.timing.baselines.values())
        assert len(state.timing.groups) <= 32
        assert len(state.timing.labelled_hands) <= index + 1 <= state.config.num_hands
        assert len(state.selector.transitions) <= 1 + index // state.selector.settings["cooldown_hands"]
        if index in (249, 999):
            sizes[index] = len(pickle.dumps(state))
    early, late = median(probes[:200]), median(probes[-200:])
    record_property("early_probe_ms", early * 1000)
    record_property("late_probe_ms", late * 1000)
    record_property("final_state_bytes", sizes[999])
    assert late <= max(early * 2, early + .001)
    assert sizes[999] < 1_000_000 and sizes[999] <= sizes[249] * 2 + 50_000
    assert memory["safety_errors"] == 0


@pytest.mark.parametrize("component,method", [("equity", None), ("opponent", "observe"),
                                               ("timing", "observe"), ("timing", "finish"),
                                               ("selector", "bluff_multiplier")])
def test_fault_in_each_decision_module_returns_safe_legal_fallback(component, method, monkeypatch, capsys):
    memory = {}
    agent.new_half(AgentConfig(), memory)
    def fail(*args, **kwargs):
        raise RuntimeError(f"injected {component}/{method}")
    if component == "equity":
        monkeypatch.setattr(fallback, "equity", fail)
    else:
        monkeypatch.setattr(getattr(memory["bot"], component), method, fail)
    assert agent.choose_action(flop(), memory) == Action.CHECK_CALL
    assert memory["safety_errors"] >= 1
    assert "injected" in capsys.readouterr().err


@pytest.mark.parametrize("component,method", [("opponent", "end"), ("timing", "end"), ("selector", "evaluate")])
def test_result_module_fault_never_escapes_callback(component, method, monkeypatch, capsys):
    memory = {}
    agent.new_half(AgentConfig(), memory)
    game = Game(make_deal("callback-fault", 0), 0)
    game.apply(Action.FOLD)
    def fail(*args, **kwargs):
        raise RuntimeError(f"injected {component}/{method}")
    monkeypatch.setattr(getattr(memory["bot"], component), method, fail)
    assert agent.on_hand_end(game.hand_result(0), memory) is None
    assert memory["safety_errors"] == 1
    assert "injected" in capsys.readouterr().err
    assert agent.choose_action(flop(), memory) in flop().legal_actions
