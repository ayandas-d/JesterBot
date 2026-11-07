"""Opponent accounting, automatic adaptation and live check-fold exploitation."""

from collections import Counter
from copy import deepcopy
from dataclasses import replace
from random import Random

import pytest

import agent
from bot import fallback
from bot.gears import CONFIG as GEAR_CONFIG, GearSelector
from bot.opponent import CONFIG as MODEL_CONFIG, OpponentModel, Stats
from bot.policy import action_probabilities
from evaluator import cards_from_str, category_of, omaha_score
from game import Action, AgentConfig, Game, HandResult, ObservedAction, RAISE_ACTIONS, Street, make_deal


def event(me, action, amount=0, total=0, street=Street.PREFLOP):
    return ObservedAction(street, me, action, amount, total)


def observation(index=0, history=()):
    obs = Game(make_deal("opponent", index), 0, hand_index=index).observation(0)
    return replace(obs, action_history=tuple(history))


def result(index, net=2, showdown=False, board=(), hole=None):
    return HandResult(index, net, 12, showdown, board, hole, "me" if net > 0 else "opp")


def test_exact_stats_street_resets_deduplication_and_rolling_eviction():
    model = OpponentModel(AgentConfig(), {**MODEL_CONFIG, "window_hands": 1})
    history = [event(True, Action.RAISE_POT, 5, 6), event(False, Action.CHECK_CALL, 4, 6),
               event(False, Action.CHECK_CALL, street=Street.FLOP),
               event(True, Action.RAISE_HALF, 6, 6, Street.FLOP),
               event(False, Action.RAISE_POT, 12, 12, Street.FLOP),
               event(True, Action.CHECK_CALL, 6, 12, Street.FLOP),
               event(False, Action.CHECK_CALL, street=Street.TURN),
               event(True, Action.CHECK_CALL, street=Street.TURN),
               event(False, Action.RAISE_HALF, 8, 8, Street.RIVER),
               event(True, Action.FOLD, street=Street.RIVER)]
    model.observe(observation(history=history[:2]), "MANIAC")
    model.observe(observation(history=history[:2]), "MANIAC")
    model.observe(observation(history=history), "MANIAC")
    assert model.end(result(0, -18), "MANIAC")
    assert not model.end(result(0, -18), "MANIAC")
    assert model.whole.events["hands"] == 1
    assert model.whole.events["actions"] == 5
    assert model.whole.events["checks"] == 2
    assert model.whole.events["raises"] == 2
    assert model.whole.events["faced_raises"] == 2
    assert model.whole.call_frequency == 0.5
    assert model.whole.reraise_frequency == 0.5
    assert model.whole.net_bb_by_gear == {"MANIAC": -9}

    model.observe(observation(1, [event(True, Action.RAISE_POT, 5, 6),
                                  event(False, Action.FOLD, 0, 2)]), "VALUE")
    model.end(result(1), "VALUE")
    assert model.whole.fold_to_raise_rate == pytest.approx(1 / 3)
    assert model.whole.call_frequency == pytest.approx(1 / 3)
    assert model.whole.reraise_frequency == pytest.approx(1 / 3)
    assert model.whole.raise_frequency == pytest.approx(2 / 6)
    assert model.whole.net_bb_by_gear == {"MANIAC": -9, "VALUE": 1}
    assert model.rolling.fold_to_raise_rate == 1
    assert model.rolling.events["actions"] == 1
    assert model.rolling.net_bb_by_gear == {"VALUE": 1}
    assert model.rolling.hands_by_gear == {"VALUE": 1}
    assert len(model.recent) == 1


def test_blind_calls_and_new_street_checks_are_not_responses_to_our_raise():
    model = OpponentModel(AgentConfig())
    history = [event(False, Action.CHECK_CALL, 1, 2), event(True, Action.RAISE_HALF, 4, 6),
               event(False, Action.CHECK_CALL, 4, 6),
               event(True, Action.CHECK_CALL, street=Street.FLOP),
               event(False, Action.CHECK_CALL, street=Street.FLOP)]
    model.observe(observation(history=history), "MANIAC")
    stats = model.current.stats
    assert stats.events["calls"] == 2
    assert stats.events["faced_raises"] == stats.events["calls_to_raise"] == 1
    assert stats.events["checks"] == 1


def test_showdown_strength_is_linked_to_aggression_and_evicted():
    model = OpponentModel(AgentConfig(), {**MODEL_CONFIG, "window_hands": 1})
    hole = tuple(cards_from_str("6d 6h 7d 7h 8s"))
    board = tuple(cards_from_str("Ac Kc Qc Jd Td"))
    history = [event(True, Action.RAISE_POT, 5, 6),
               event(False, Action.RAISE_POT, 12, 14), event(True, Action.CHECK_CALL, 8, 14)]
    model.observe(observation(history=history), "TRAP")
    model.end(result(0, -14, True, board, hole), "TRAP")
    category = category_of(omaha_score(hole, board))
    assert model.recent[-1].showdown == {"category": category, "raises": 1, "actions": 1}
    assert model.whole.showdown_categories[category] == 1
    assert model.whole.showdown_raises[category] == 1
    assert model.whole.weak_aggressive_showdown_rate == 1
    model.end(result(1), "VALUE")
    assert model.whole.events["showdowns"] == 1
    assert not model.rolling.events["showdowns"]
    assert not model.rolling.showdown_categories
    assert not model.rolling.showdown_raises


def play_model_hands(hands=300):
    """Verify partial-information tracking against independently counted full history."""
    models = [OpponentModel(AgentConfig()) for _ in range(2)]
    rng = Random(401)
    totals = [Counter(), Counter()]
    nets = [Counter(), Counter()]
    streaks = [0, 0]
    for index in range(hands):
        game = Game(make_deal("model-engine", index), index % 2, hand_index=index)
        gear = "MANIAC" if index % 2 else "VALUE"
        while not game.is_terminal:
            seat = game.to_act
            obs = game.observation(seat)
            models[seat].observe(obs, gear)
            choices = [a for a in obs.legal_actions if a != Action.FOLD] if index % 3 == 0 else obs.legal_actions
            action = Action.CHECK_CALL if index % 7 == 0 else rng.choice(choices)
            models[seat].record_action(obs, action)
            game.apply(action)
        for seat, model in enumerate(models):
            expected = Counter()
            previous = None
            for action in game.observation(seat).action_history:
                if not action.is_me:
                    expected["actions"] += 1
                    raised = action.action in RAISE_ACTIONS
                    called = action.action == Action.CHECK_CALL and action.amount > 0
                    folded = action.action == Action.FOLD
                    checked = action.action == Action.CHECK_CALL and not called
                    expected["raises"] += raised
                    expected["calls"] += called
                    expected["checks"] += checked
                    expected["folds"] += folded
                    if previous and previous.is_me and previous.street == action.street and previous.action in RAISE_ACTIONS:
                        expected["faced_raises"] += 1
                        expected["folds_to_raise"] += folded
                        expected["calls_to_raise"] += called
                        expected["reraises"] += raised
                    streaks[seat] = streaks[seat] + 1 if folded or checked else 0
                previous = action
            hand_result = game.hand_result(seat)
            model.end(hand_result, gear)
            actual = model.recent[-1].stats.events
            for key in ("actions", "raises", "calls", "checks", "folds", "faced_raises",
                        "folds_to_raise", "calls_to_raise", "reraises"):
                assert actual[key] == expected[key], (index, seat, key, game.observation(seat).action_history)
            assert model.detector.streak == streaks[seat], (index, seat)
            totals[seat].update(expected)
            nets[seat][gear] += hand_result.my_net / 2
    for seat, model in enumerate(models):
        assert all(model.whole.events[key] == count for key, count in totals[seat].items())
        assert model.whole.net_bb_by_gear == nets[seat]
        assert model.rolling.events["hands"] == len(model.recent) == 100
        assert model.whole.events["hands"] == hands
    return models


def test_real_engine_terminal_folds_calls_checks_both_seats_and_all_streets():
    play_model_hands()


@pytest.mark.parametrize("kind,start,expected", [("folder", "MANIAC", "MANIAC"),
                                                  ("folder", "VALUE", "MANIAC"),
                                                  ("station", "MANIAC", "VALUE"),
                                                  ("reraiser", "MANIAC", "TRAP")])
def test_synthetic_opponents_select_expected_gears(kind, start, expected):
    state = fallback.State(AgentConfig())
    state.gear = start
    for index in range(100):
        history = [event(True, Action.RAISE_POT, 5, 6)]
        if kind == "folder":
            history.append(event(False, Action.FOLD, 0, 2))
        elif kind == "station":
            history.extend([event(False, Action.CHECK_CALL, 4, 6),
                            event(False, Action.RAISE_HALF, 6, 6, Street.FLOP),
                            event(True, Action.FOLD, street=Street.FLOP)])
        else:
            history.extend([event(False, Action.RAISE_POT, 12, 14), event(True, Action.FOLD, 0, 6)])
        state.opponent.observe(observation(index, history), state.gear)
        state.end(result(index, 2 if kind == "folder" else -6))
        if index < 74:
            assert state.gear == start
    assert state.gear == expected
    if kind == "folder":
        assert state.selector.bluff_multiplier(state.gear) > 1
    if start != expected:
        assert state.selector.transitions[0][:3] == (75, start, expected)


def evidence(fold=0.20, reraise=0.10, calls=0.70, count=100, net=-20, gear="MANIAC"):
    stats = Stats()
    stats.events.update(faced_raises=count, folds_to_raise=round(fold * count),
                        reraises=round(reraise * count), calls_to_raise=round(calls * count), actions=count)
    stats.actions_by_gear[gear] = count
    stats.net_bb_by_gear[gear] = net
    return stats


@pytest.mark.parametrize("stats", [evidence(count=39), evidence(count=39, reraise=.9),
                                   evidence(count=39, fold=.9, net=20)])
def test_no_switch_without_minimum_relevant_events(stats):
    selector = GearSelector()
    for hands in range(25, 201, 25):
        assert selector.evaluate(hands, stats, "AGGRO") == "AGGRO"
    assert not selector.transitions


def test_noisy_alternating_evidence_cannot_switch_every_window_and_cooldown_holds():
    selector = GearSelector()
    station, reraiser = evidence(), evidence(reraise=.7, calls=.1)
    gear = "MANIAC"
    for hands in range(25, 301, 25):
        gear = selector.evaluate(hands, station if hands % 50 else reraiser, gear)
        assert gear == "MANIAC"
    assert not selector.transitions
    for hands in (325, 350):
        gear = selector.evaluate(hands, station, gear)
    assert gear == "VALUE"
    for hands in (375, 400):
        gear = selector.evaluate(hands, reraiser, gear)
        assert gear == "VALUE"
    gear = selector.evaluate(425, reraiser, gear)
    assert gear == "TRAP"
    assert selector.transitions[-1][0] - selector.transitions[-2][0] >= GEAR_CONFIG["cooldown_hands"]


def test_rolling_losses_step_down_and_repeated_evaluation_does_not_accelerate():
    selector = GearSelector()
    stats = evidence(fold=.4, reraise=.2, calls=.4)
    assert selector.evaluate(25, stats, "MANIAC") == "MANIAC"
    for _ in range(10):
        assert selector.evaluate(25, stats, "MANIAC") == "MANIAC"
    assert selector.evaluate(50, stats, "MANIAC") == "AGGRO"
    stats.actions_by_gear["AGGRO"] = 40
    stats.net_bb_by_gear["AGGRO"] = -1
    for hands in (75, 100):
        assert selector.evaluate(hands, stats, "AGGRO") == "AGGRO"
    assert selector.evaluate(125, stats, "AGGRO") == "VALUE"


def test_detector_triggers_at_k_checks_folds_and_immediately_resets_on_call_or_raise():
    model = OpponentModel(AgentConfig())
    k = MODEL_CONFIG["checkfold_k"]
    for index in range(k):
        model.observe(observation(index, [event(True, Action.RAISE_HALF, 3, 4),
                                          event(False, Action.FOLD, 0, 2)]), "MANIAC")
        model.end(result(index), "MANIAC")
        assert model.exploit_checkfold == (index + 1 == k)
    for action in (event(False, Action.CHECK_CALL, 2, 4), event(False, Action.RAISE_POT, 8, 10)):
        model.detector.streak = k
        model.observe(observation(k, [event(True, Action.RAISE_HALF, 3, 4), action]), "MANIAC")
        assert not model.exploit_checkfold
    model.detector.streak = k - 1
    model.observe(observation(k + 1), "MANIAC")
    # Missing results break the evidence streak conservatively.
    assert model.detector.streak == 0


def test_free_checks_qualify_but_paid_blind_calls_reset_detector():
    model = OpponentModel(AgentConfig())
    model.detector.streak = MODEL_CONFIG["checkfold_k"] - 1
    model.observe(observation(history=[event(True, Action.CHECK_CALL, 1, 2),
                                      event(False, Action.CHECK_CALL, 0, 2)]), "MANIAC")
    assert model.exploit_checkfold
    model = OpponentModel(AgentConfig())
    model.detector.streak = MODEL_CONFIG["checkfold_k"]
    model.observe(observation(history=[event(False, Action.CHECK_CALL, 1, 2)]), "MANIAC")
    assert not model.exploit_checkfold


def test_live_exploit_prefers_half_and_a_call_turns_it_off_before_next_decision(monkeypatch):
    memory = {}
    agent.new_half(AgentConfig(), memory)
    state = memory["bot"]
    game = Game(make_deal("checkfold", 0), 0)
    state.opponent.detector.streak = MODEL_CONFIG["checkfold_k"]
    assert agent.choose_action(game.observation(0), memory) == Action.RAISE_HALF
    game.apply(Action.RAISE_HALF)
    game.apply(Action.CHECK_CALL)
    game.apply(Action.CHECK_CALL)  # opponent checks first on the flop
    monkeypatch.setattr(fallback, "equity", lambda *args, **kwargs: .1)
    state.gear = "VALUE"
    state.gear_parameters["VALUE"]["raise"]["weak"] = 0
    assert agent.choose_action(game.observation(0), memory) == Action.CHECK_CALL
    assert not state.opponent.exploit_checkfold
    assert memory["safety_errors"] == 0


def test_exploit_keeps_fixed_equity_work_and_legal_fallback_when_raise_unavailable(monkeypatch):
    game = Game(make_deal("sample-budget", 0), 0)
    game.apply(Action.CHECK_CALL)
    game.apply(Action.CHECK_CALL)
    obs = game.observation(game.to_act)
    state = fallback.State(AgentConfig())
    calls = []
    def equity(*args, **kwargs):
        calls.append(kwargs["samples"])
        return .1
    monkeypatch.setattr(fallback, "equity", equity)
    fallback.policy(obs, state)
    state.opponent.detector.streak = MODEL_CONFIG["checkfold_k"]
    assert fallback.policy(obs, state) == Action.RAISE_HALF
    assert calls[0] == calls[1] > 0
    assert fallback.policy(replace(obs, legal_actions=(Action.CHECK_CALL,)), state) == Action.CHECK_CALL
    assert fallback.policy(replace(obs, legal_actions=(Action.CHECK_CALL, Action.RAISE_POT)), state) == Action.RAISE_POT


def test_folder_bluff_boost_keeps_normalization_and_price_floors():
    game = Game(make_deal("folder-boost", 0), 0)
    game.apply(Action.CHECK_CALL)
    obs = game.observation(game.to_act)
    base = action_probabilities(obs, .1, "MANIAC")
    boosted = action_probabilities(obs, .1, "MANIAC", bluff_multiplier=1.1)
    assert sum(boosted[a] for a in RAISE_ACTIONS) > sum(base[a] for a in RAISE_ACTIONS)
    assert sum(boosted.values()) == pytest.approx(1)
    game.apply(Action.RAISE_POT)
    assert action_probabilities(game.observation(game.to_act), 0, "MANIAC", bluff_multiplier=1.1)[Action.FOLD] == 1


def test_new_half_resets_all_opponent_gear_detector_and_rng_state(monkeypatch):
    monkeypatch.setenv("BOT_SEED", "task4-reset")
    memory = {}
    agent.new_half(AgentConfig(), memory)
    old = memory["bot"]
    parameters = deepcopy(old.gear_parameters)
    first_random = old.rng.random()
    old.opponent.end(result(0), old.gear)
    old.opponent.detector.streak = 100
    old.opponent.observe(observation(1), old.gear)
    old.gear = "TRAP"
    old.selector.candidate = "VALUE"
    old.selector.confirmations = 1
    old.selector.folder = True
    old.selector.transitions.append((50, "MANIAC", "TRAP", "test"))
    old.hands_played = 50
    old.governor.total_seconds = 2
    memory["safety_errors"] = 5
    agent.new_half(AgentConfig(), memory)
    state = memory["bot"]
    assert state is not old
    assert state.gear == "MANIAC" and state.hands_played == 0
    assert not state.opponent.whole.events and not state.opponent.rolling.events
    assert not state.opponent.recent and state.opponent.current is None
    assert state.opponent.last_finished == -1 and state.opponent.detector.streak == 0
    assert not state.opponent.exploit_checkfold
    assert state.selector.candidate is None and state.selector.confirmations == 0
    assert not state.selector.folder and not state.selector.transitions
    assert state.selector.last_evaluation == 0
    assert state.governor.total_seconds == memory["safety_errors"] == 0
    assert state.gear_parameters == parameters and state.rng.random() == first_random
