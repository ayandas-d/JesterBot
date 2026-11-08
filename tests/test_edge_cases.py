"""Engine-built boundary states; one explicitly synthetic unequal-stack case."""

from fastapi.testclient import TestClient

import agent
from bot.policy import CONFIG, action_probabilities
from game import Action, AgentConfig, Game, Street, make_deal


def raised_game(action):
    game = Game(make_deal("edge-raises", 0), 0)
    for _ in range(4):
        game.apply(action)
    return game


def assert_no_raise(obs):
    assert Action.RAISE_HALF not in obs.legal_actions and Action.RAISE_POT not in obs.legal_actions
    for gear in CONFIG["gears"]:
        probabilities = action_probabilities(obs, .99, gear)
        assert set(probabilities) <= {Action.FOLD, Action.CHECK_CALL}
    memory = {}
    assert agent.choose_action(obs, memory) in (Action.FOLD, Action.CHECK_CALL)
    assert memory["safety_errors"] == 0


def test_four_raise_cap_without_all_in():
    game = raised_game(Action.RAISE_HALF)
    obs = game.observation(game.to_act)
    assert obs.raises_this_street == 4 and obs.my_stack > obs.to_call and obs.opp_stack > 0
    assert_no_raise(obs)


def test_opponent_all_in_and_exact_stack_to_call():
    game = raised_game(Action.RAISE_POT)
    obs = game.observation(game.to_act)
    assert obs.my_stack == obs.to_call == 26
    assert obs.opp_stack == 0
    assert_no_raise(obs)


def test_synthetic_unequal_stack_short_call_uses_engine_observation_and_apply():
    # Authorized fixture: this cannot arise from the tournament's equal 80-
    # chip starting stacks. Only the test Game instance is changed, not engine
    # source. The engine has no general unequal-stack side-pot settlement.
    game = raised_game(Action.RAISE_POT)
    seat = game.to_act
    game.stacks[seat] = 10
    obs = game.observation(seat)
    assert obs.my_stack == 10 < obs.to_call == 26
    assert_no_raise(obs)
    game.apply(Action.CHECK_CALL)
    assert game.stacks[seat] == 0 and game.history[-1].amount == 10


def test_all_in_preflop_runs_out_board_without_more_decisions():
    game = raised_game(Action.RAISE_POT)
    assert game.street == Street.PREFLOP and not game.is_terminal
    game.apply(Action.CHECK_CALL)
    assert game.is_terminal and game.street == Street.RIVER
    assert game.legal_actions() == ()
    assert game.hand_result(0).went_to_showdown and len(game.hand_result(0).board) == 5


def test_first_decision_empty_history_and_missing_new_half():
    game = Game(make_deal("first-edge", 0), 0)
    obs = game.observation(0)
    assert obs.action_history == () and obs.hand_index == 0
    memory = {}
    assert agent.choose_action(obs, memory) in obs.legal_actions
    assert memory["safety_errors"] == 0


def test_hand_999_and_final_batched_results(monkeypatch):
    monkeypatch.setattr(agent, "TOKEN", None)
    results = []
    for index in (997, 998, 999):
        game = Game(make_deal("last-batch", index), 0, hand_index=index)
        game.apply(Action.FOLD)
        results.append(game.hand_result(0).to_dict())
    with TestClient(agent.app) as client:
        assert client.post("/new-half", json={"config": AgentConfig().to_dict()}).status_code == 200
        game = Game(make_deal("last-batch", 999), 0, hand_index=999)
        obs = game.observation(0)
        response = client.post("/act", json={"observation": obs.to_dict(), "hand_results": results[:2]})
        assert response.status_code == 200 and Action[response.json()["action"]] in obs.legal_actions
        assert not response.json()["hand_end_errors"]
        response = client.post("/hand-end", json={"results": results[2:]})
        assert response.status_code == 200 and response.json()["hand_end_errors"] == []
        assert agent.MEMORY["bot"].opponent.last_finished == 999
        assert agent.MEMORY["bot"].hands_played == 3 and agent.MEMORY["safety_errors"] == 0
