from dataclasses import replace
from random import Random

import pytest

import agent
from bot.equity import board_masks, equity, pair_masks, preflop_strength, score_masks
from bot.strategy import Hand, State, policy
from bot.timing import Timing
from evaluator import cards_from_str, get_table, omaha_score, score_five
from game import Action, AgentConfig, Game, HandResult, Street, make_deal


def observation(seed=4):
    return Game(make_deal(seed, 0), 0).observation(0)


def test_identity():
    assert agent.PARTICIPANT == "Brootal" and agent.AGENT_NAME == "Jester"


def result(hand, winner="me", showdown=False):
    return HandResult(hand, 2 if winner == "me" else -2, 8, showdown,
                      (), None, winner)


def test_fast_scorer_matches_engine_for_random_hands():
    rng = Random(7)
    for _ in range(200):
        cards = rng.sample(range(36), 10)
        assert score_masks(pair_masks(cards[:5]), board_masks(cards[5:]), get_table()) == omaha_score(cards[:5], cards[5:])


def test_short_deck_rankings_and_wheel():
    score = lambda text: score_five(cards_from_str(text))
    assert score("6c 8c Tc Qc Ac") > score("Kh Kd Ks 9c 9h")
    assert score("6c 6d 6h Ac Kd") > score("Tc Jd Qh Ks Ac")
    assert score("6c 7d 8h 9s Tc") > score("Ac 6d 7h 8s 9c")


def test_exact_two_hole_rule_and_nut_equity():
    hole = cards_from_str("Th 7s 7d 8c 9c")
    board = cards_from_str("Ah Kh Qh Jh 6c")
    assert omaha_score(hole, board) >> 20 == 3  # straight, not flush
    nuts = cards_from_str("Ah Kh 6d 7d 8s")
    board = cards_from_str("Qh Jh Th 9c 6c")
    assert equity(nuts, board, Random(1)) > 0.97


def test_simulation_never_reuses_known_cards_and_has_fixed_work():
    hole = (0, 5, 10, 15, 20)
    for board, expected in (((25, 30, 35), 24), ((25, 30, 35, 1), 32), ((25, 30, 35, 1, 2), 48)):
        class Spy(Random):
            calls = 0

            def sample(self, population, k):
                self.calls += 1
                assert not (set(population) & (set(hole) | set(board)))
                draw = super().sample(population, k)
                assert len(set(draw)) == k == 10 - len(board)
                return draw
        rng = Spy(2)
        assert 0 < equity(hole, board, rng) < 1
        assert rng.calls == expected


def test_preflop_rewards_useful_pairs_and_double_suits():
    assert preflop_strength(cards_from_str("Ac Ad Kc Kd Qh")) > preflop_strength(cards_from_str("6c 6d 6h 6s 8c"))


@pytest.mark.parametrize("failure", [RuntimeError("fault"), None, Action.FOLD, "CHECK_CALL"])
def test_safety_wrapper_checks_return_and_exceptions(monkeypatch, failure):
    obs = replace(observation(), to_call=0, legal_actions=(Action.CHECK_CALL, Action.RAISE_POT))
    def broken(*args):
        if isinstance(failure, Exception):
            raise failure
        return failure
    monkeypatch.setattr(agent, "policy", broken)
    memory = {}
    assert agent.choose_action(obs, memory) == Action.CHECK_CALL
    assert memory["safety_errors"] == 1


def test_new_half_and_result_failures_are_contained(monkeypatch):
    monkeypatch.setattr(agent, "State", lambda *_: (_ for _ in ()).throw(ValueError("fault")))
    memory = {}
    agent.new_half(AgentConfig(), memory)
    assert memory["safety_errors"] == 1
    monkeypatch.setattr(State, "end", lambda *_: (_ for _ in ()).throw(ValueError("fault")))
    agent.on_hand_end(result(0), memory)
    assert memory["safety_errors"] == 2


def test_half_reset_removes_all_learning_and_clock_state():
    memory = {}
    agent.new_half(AgentConfig(), memory)
    old = memory["bot"]
    old.fold_streak, old.gear = 8, "value"
    old.timing.last = (1, 2, 3, 4, 5)
    old.recent.append((1, 1, 1, 1, 80, False))
    agent.new_half(AgentConfig(), memory)
    fresh = memory["bot"]
    assert fresh is not old and fresh.gear == "maniac"
    assert fresh.fold_streak == 0 and not fresh.recent and fresh.timing.last is None


def test_terminal_folds_are_learned_once_and_defense_revokes_exploit():
    state = State(AgentConfig())
    for i in range(6):
        state.hands[i] = Hand(i, pending=True)
        state.end(result(i))
        state.end(result(i))
    assert state.fold_streak == 6 and state.hands_played == 6
    assert sum(x[2] for x in state.recent) == sum(x[3] for x in state.recent) == 6
    obs = replace(observation(), hand_index=6)
    assert policy(obs, state) == Action.RAISE_HALF
    state.response(Hand(6, pending=True), Action.CHECK_CALL)
    assert state.fold_streak == 0
    state.fold_streak = 6
    state.response(Hand(7), Action.RAISE_POT)
    assert state.fold_streak == 0


def test_history_not_counted_twice_across_streets():
    state = State(AgentConfig())
    game = Game(make_deal(3, 0), 0)
    obs = game.observation(0)
    state.observe(obs, 1.0)
    state.record_action(obs, Action.RAISE_HALF)
    game.apply(Action.RAISE_HALF)
    game.apply(Action.CHECK_CALL)
    # Seat 1 checks the flop before we see its final preflop call.
    game.apply(Action.CHECK_CALL)
    obs = game.observation(0)
    state.observe(obs, 2.0)
    state.observe(obs, 2.1)
    h = state.hands[0]
    assert h.facing == 1 and h.decisions == 2 and not h.pending


def test_gear_switching_and_hysteresis():
    state = State(AgentConfig())
    state.recent.extend([(2, 0, 1, 0, 0, True)] * 20)
    state.hands_played = 20
    state.update_gear()
    assert state.gear == "value"
    state.recent.clear()
    state.recent.extend([(2, 0, 1, 1, 0, False)] * 20)
    state.hands_played = 25
    state.update_gear()
    assert state.gear == "value"
    state.hands_played = 32
    state.update_gear()
    assert state.gear == "pressure"
    state.recent.clear()
    state.recent.extend([(3, 2, 1, 0, 0, True)] * 20)
    state.hands_played = 44
    state.update_gear()
    assert state.gear == "counter"


def test_late_timing_collapse_requires_behavior_and_latency_shift():
    timing = Timing(1000)
    timing.early_gaps.extend([0.008] * 40)
    timing.late_gaps.extend([0.001] * 10)
    assert not timing.collapse_hint(800, 5)
    assert not timing.collapse_hint(500, 6)
    assert timing.collapse_hint(800, 6)
    assert not timing.collapse_hint(801, 0)
    timing.late_gaps.clear()
    timing.late_gaps.extend([0.008] * 10)
    assert not timing.collapse_hint(800, 6)


def test_timing_rejects_cross_hand_and_street_and_subtracts_own_work():
    timing = Timing(1000)
    obs = observation()
    timing.finish(obs, Action.RAISE_HALF, 10.0)
    timing.observe(replace(obs, hand_index=1), 10.01)
    assert timing.current is None
    timing.observe(replace(obs, street=Street.FLOP), 10.01)
    assert timing.current is None
    game = Game(make_deal(4, 0), 0)
    game.apply(Action.RAISE_HALF)
    game.apply(Action.RAISE_POT)
    timing.observe(game.observation(0), 10.012)
    assert timing.current[1] == pytest.approx(0.012)


def test_timing_gate_requires_held_out_signal_and_matching_context():
    timing = Timing(1000)
    key = (0, 2, 3)
    for i in range(80):
        timing.learn(key, 0.001 + i * 0.0001, 0.3 + i * 0.004, 100)
    timing.current = (key, 0.009, ())
    assert timing.adjustment(800) == 0
    for i in range(40):
        timing.learn(key, 0.001 + i * 0.0002, 0.3 + i * 0.008, 500)
    assert -0.02 <= timing.adjustment(800) < 0
    assert timing.adjustment(500) == 0
    timing.current = ((1, 2, 3), 0.009, ())
    assert timing.adjustment(800) == 0
    timing.validation[key].clear()
    for i in range(40):
        timing.learn(key, 0.001 + i * 0.0002, 0.7 - i * 0.008, 500)
    timing.current = (key, 0.009, ())
    assert timing.adjustment(800) == 0


def test_many_engine_hands_have_zero_safety_fallbacks():
    memory = {}
    agent.new_half(AgentConfig(), memory)
    rng = Random(10)
    for i in range(120):
        game = Game(make_deal("strategy-test", i), i % 2, hand_index=i)
        seat = i % 2
        while not game.is_terminal:
            obs = game.observation(game.to_act)
            action = agent.choose_action(obs, memory) if game.to_act == seat else rng.choice(obs.legal_actions)
            assert action in obs.legal_actions
            game.apply(action)
        agent.on_hand_end(game.hand_result(seat), memory)
    assert memory["safety_errors"] == 0
    assert memory["bot"].hands_played == 120
