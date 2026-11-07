"""Engine-generated legality coverage and failure containment for Task 1."""

from collections import Counter

from fastapi.testclient import TestClient
import pytest

import agent
from bot import fallback, safety
from game import Action, AgentConfig, Game, Street, make_deal
from tests.fuzz_states import fuzz_hands


def free_observation():
    game = Game(make_deal("free-check", 0), 0)
    game.apply(Action.CHECK_CALL)
    return game.observation(game.to_act)


def test_legality_fuzz_thousands_of_real_states():
    memories = [{}, {}]  # also exercise lazy initialization in both seats
    coverage = Counter()
    states = 0
    def observe(obs):
        nonlocal states
        # Button is hand_index % 2 in this shared walk.
        button = obs.hand_index % 2
        seat = button if obs.is_button else 1 - button
        action = agent.choose_action(obs, memories[seat])
        assert isinstance(action, Action) and action in obs.legal_actions
        coverage[obs.street] += 1
        coverage["facing_bet" if obs.to_call else "free_check"] += 1
        if obs.raises_this_street == AgentConfig().raise_cap:
            coverage["raise_cap"] += 1
        if obs.opp_stack == 0:
            coverage["opponent_all_in"] += 1
        states += 1
    def finish(results):
        for seat, result in enumerate(results):
            agent.on_hand_end(result, memories[seat])
    fuzz_hands(observe, finish)
    assert states > 10_000, states
    assert all(coverage[street] >= 100 for street in Street), coverage
    assert all(coverage[key] > 0 for key in ("facing_bet", "free_check", "raise_cap", "opponent_all_in")), coverage
    assert all(m["safety_errors"] == 0 for m in memories)
    assert all(m["bot"].hands_played == 2500 for m in memories)


def test_strategy_exception_returns_check_call_and_logs_stderr(monkeypatch, capsys):
    def broken(*_):
        raise RuntimeError("injected strategy fault")
    monkeypatch.setattr(agent, "policy", broken)
    memory = {}
    assert agent.choose_action(free_observation(), memory) == Action.CHECK_CALL
    assert memory["safety_errors"] == 1
    out = capsys.readouterr()
    assert out.out == "" and "injected strategy fault" in out.err and "Traceback" in out.err


@pytest.mark.parametrize("illegal", [Action.FOLD, "CHECK_CALL", 1, True, None, object()])
def test_illegal_return_uses_check_call(monkeypatch, capsys, illegal):
    obs = free_observation()
    assert Action.FOLD not in obs.legal_actions
    monkeypatch.setattr(agent, "policy", lambda *_: illegal)
    memory = {}
    assert agent.choose_action(obs, memory) == Action.CHECK_CALL
    assert memory["safety_errors"] == 1
    assert "illegal policy action" in capsys.readouterr().err


def test_new_half_exception_recovers_lazily(monkeypatch, capsys):
    def broken(*_):
        raise RuntimeError("injected initialization fault")
    monkeypatch.setattr(agent, "State", broken)
    memory = {"stale": "from old half"}
    assert agent.new_half(AgentConfig(), memory) is None
    assert "stale" not in memory and memory["safety_errors"] == 1
    assert agent.choose_action(free_observation(), memory) in free_observation().legal_actions
    assert isinstance(memory["bot"], fallback.State)
    assert "injected initialization fault" in capsys.readouterr().err


def test_result_callback_exception_is_contained(monkeypatch, capsys):
    game = Game(make_deal("callback", 0), 0)
    game.apply(Action.FOLD)
    def broken(*_):
        raise RuntimeError("injected result fault")
    monkeypatch.setattr(fallback.State, "end", broken)
    memory = {}
    assert agent.on_hand_end(game.hand_result(0), memory) is None
    assert memory["safety_errors"] == 1
    assert "injected result fault" in capsys.readouterr().err


def test_missing_new_half_supports_decisions_and_results():
    memory = {}
    obs = free_observation()
    assert agent.choose_action(obs, memory) in obs.legal_actions
    game = Game(make_deal("lazy-result", 0), 0)
    game.apply(Action.FOLD)
    other = {}
    agent.on_hand_end(game.hand_result(0), other)
    assert other["bot"].hands_played == 1 and other["safety_errors"] == 0


def test_diagnostic_failure_cannot_escape(monkeypatch, capsys):
    def broken(*_):
        raise OSError("stderr failed")
    monkeypatch.setattr(agent, "policy", broken)
    monkeypatch.setattr(safety.traceback, "print_exc", broken)
    assert agent.choose_action(free_observation(), {}) == Action.CHECK_CALL
    assert capsys.readouterr().out == ""


def test_http_faults_still_return_legal_actions_and_no_hand_end_errors(monkeypatch):
    monkeypatch.setattr(agent, "TOKEN", None)
    client = TestClient(agent.app)
    assert client.post("/new-half", json={"config": {}}).status_code == 200
    def broken(*_):
        raise RuntimeError("injected HTTP fault")
    monkeypatch.setattr(agent, "policy", broken)
    monkeypatch.setattr(fallback.State, "end", broken)
    game = Game(make_deal("http-fault", 0), 0)
    game.apply(Action.FOLD)
    response = client.post("/act", json={"observation": free_observation().to_dict(),
                                         "hand_results": [game.hand_result(0).to_dict()]})
    assert response.status_code == 200
    assert response.json() == {"action": "CHECK_CALL", "hand_end_errors": []}


def test_live_policy_is_not_the_adaptive_policy():
    assert agent.policy is fallback.policy


def test_fixed_postflop_simulation_count(monkeypatch):
    calls = []
    def estimate(hole, board, rng, samples, deadline):
        calls.append(samples)
        return 0.5
    monkeypatch.setattr(fallback, "equity", estimate)
    game = Game(make_deal("fixed-count", 0), 0)
    while not game.is_terminal:
        obs = game.observation(game.to_act)
        if obs.street != Street.PREFLOP:
            fallback.policy(obs, fallback.State(AgentConfig()))
        game.apply(Action.CHECK_CALL)
    assert calls == [40, 40, 40, 40, 72, 72]
