from random import Random

import pytest

import agent
from bot import equity as engine
from bot.governor import TimeGovernor
from bot.preflop import preflop_score
from evaluator import cards_from_str, omaha_score
from game import Action, AgentConfig, Game, make_deal
from tools.profile_equity import profile_decisions


def cards(text):
    return tuple(cards_from_str(text))


def test_guide_straight_is_not_a_flush():
    hole = cards("Th 7s 7d 8c 9c")
    board = cards("Ah Kh Qh Jh 6c")
    assert omaha_score(hole, board) >> 20 == 3


def test_river_nuts_and_dead_hand():
    assert engine.equity(cards("Ah Kh 6d 7d 8s"), cards("Qh Jh Th 9c 6c"),
                         Random(1), samples=512) > 0.99
    assert engine.equity(cards("6d 6h 7d 7h 8s"), cards("Ac Kc Qc Jd Td"),
                         Random(2), samples=512) < 0.01


def test_ties_count_half_and_engine_evaluator_is_used(monkeypatch):
    calls = []
    def tied(hole, board):
        assert len(hole) == len(board) == 5
        assert len(set(hole) | set(board)) == 10
        calls.append((tuple(hole), tuple(board)))
        return 100
    monkeypatch.setattr(engine, "omaha_score", tied)
    hole, board = cards("6c 7d 8h 9s Tc"), cards("Jc Qd Kh")
    assert engine.equity(hole, board, Random(3), samples=10) == 0.5
    assert len(calls) == 20
    for ours, theirs in zip(calls[::2], calls[1::2]):
        assert ours[1] == theirs[1]
        assert set(ours[0]).isdisjoint(theirs[0])


def test_fixed_seed_reproduces_multiple_equities_and_half_reset(monkeypatch):
    monkeypatch.setenv("BOT_SEED", "task-2-repeatable")
    hole, flop = cards("Ac Ad Kc Qd Jh"), cards("6c 8h Ts")
    engine.reset_rng()
    first = [engine.equity(hole, flop) for _ in range(10)]
    assert all(0 <= value <= 1 for value in first)
    engine.reset_rng()
    assert first == [engine.equity(hole, flop) for _ in range(10)]
    memory = {}
    actions = []
    for _ in range(2):
        agent.new_half(AgentConfig(), memory)
        game = Game(make_deal("reset", 0), 0)
        while not game.is_terminal:
            obs = game.observation(game.to_act)
            actions.append(agent.choose_action(obs, memory))
            game.apply(Action.CHECK_CALL)
    assert actions[:8] == actions[8:]
    assert memory["bot"].governor.decisions == 8


def test_unseeded_rng_uses_os_entropy(monkeypatch):
    monkeypatch.delenv("BOT_SEED", raising=False)
    calls = []
    def entropy(size):
        calls.append(size)
        return b"x" * size
    monkeypatch.setattr(engine.os, "urandom", entropy)
    rng = engine.reset_rng()
    assert rng is engine.RNG
    assert rng.random() == Random(b"x" * 32).random()
    assert calls == [32]


def test_preflop_quality_and_structural_penalties():
    score = lambda text: preflop_score(cards(text))
    assert score("Ac Ad Kc Jd Th") > score("6c 7d 9h Js Ks")
    assert score("Ac Kc Qd Jh Ts") > score("Ad Kc Qc Jh Ts")  # ace-suited bonus
    assert score("Ac Ad Jh Ks Qc") > score("Ac Ad Ah Ks Qc")  # dead third ace
    assert score("Ac Ad Qh Js Kc") > score("Ac Ad Ah As Kc")  # dead fourth ace
    assert score("As Ks Qh Jh Tc") > score("As Ks Qs Jh Tc")  # suit crowding
    assert score("6c 7d 8h 9s Tc") > score("6c 7d 9h Js Ks")  # connected ranks
    rng = Random(7)
    for _ in range(100):
        hole = rng.sample(range(36), 5)
        value = preflop_score(hole)
        assert 0 <= value <= 1
        assert preflop_score(tuple(reversed(hole))) == value
        assert preflop_score([(c & ~3) | ((c + 1) & 3) for c in hole]) == pytest.approx(value)


def test_sample_counts_do_not_depend_on_strength(monkeypatch):
    monkeypatch.setattr(engine, "omaha_score", lambda hole, board: 0)
    for board in (cards("6c 7d 8h"), cards("6c 7d 8h 9s"), cards("6c 7d 8h 9s Tc")):
        for hole in (cards("Ac Ad Kh Qd Jh"), cards("6d 6h 7c 7h 8s")):
            class Spy(Random):
                calls = 0
                def sample(self, population, k):
                    self.calls += 1
                    assert set(population).isdisjoint((*hole, *board))
                    return super().sample(population, k)
            rng = Spy(9)
            assert engine.equity(hole, board, rng) == 0.5
            assert rng.calls == engine.SAMPLES[len(board)]


def test_governor_reduces_every_street_together_and_resets():
    governor = TimeGovernor(1000, budget_seconds=0.01)
    original = {street: governor.samples_for(street) for street in engine.SAMPLES}
    governor.record(hand_index=11, elapsed=0.005)
    assert governor.total_seconds == 0.005 and governor.reductions == 1
    assert all(4 <= governor.samples_for(street) < count for street, count in original.items())
    before = governor.scale
    governor.record(hand_index=12, elapsed=0.00001)
    assert governor.scale == before  # hysteresis; no per-hand recalibration
    memory = {}
    agent.new_half(AgentConfig(), memory)
    memory["bot"].governor.record(11, 0.1)
    agent.new_half(AgentConfig(), memory)
    fresh = memory["bot"].governor
    assert fresh.total_seconds == 0 and fresh.scale == 1 and fresh.reductions == 0


def test_deadline_caps_sampling_even_for_large_requested_batches(monkeypatch):
    ticks = iter((0.0, 0.0, 0.01, 0.02, 0.031))
    monkeypatch.setattr(engine, "perf_counter", lambda: next(ticks))
    calls = []
    def score(hole, board):
        calls.append(1)
        return 100
    monkeypatch.setattr(engine, "omaha_score", score)
    assert engine.equity(cards("Ac Ad Kc Qd Jh"), cards("6c 8h Ts"), Random(2), samples=10000) == 0.5
    assert len(calls) == 6  # three completed trials, not 10,000


def test_expired_decision_deadline_returns_neutral_without_sampling(monkeypatch):
    monkeypatch.setattr(engine, "perf_counter", lambda: 10.0)
    monkeypatch.setattr(engine, "omaha_score", lambda *_: pytest.fail("sampled after deadline"))
    assert engine.equity(cards("Ac Ad Kc Qd Jh"), cards("6c 8h Ts"), deadline=9.9) == 0.5


def test_failed_policy_is_still_charged_to_half_governor(monkeypatch, capsys):
    def fail(*_):
        raise RuntimeError("timed failure")
    monkeypatch.setattr(agent, "policy", fail)
    memory = {}
    obs = Game(make_deal(1, 0), 0).observation(0)
    assert agent.choose_action(obs, memory) == Action.CHECK_CALL
    assert memory["bot"].governor.decisions == 1
    assert memory["bot"].governor.total_seconds > 0
    assert "timed failure" in capsys.readouterr().err


def test_thousand_random_decisions_meet_latency_budget(monkeypatch, record_property):
    monkeypatch.setenv("BOT_SEED", "equity-timing")
    result = profile_decisions()
    for key in ("seconds", "p50_ms", "p99_ms", "max_ms"):
        record_property(key, result[key])
    assert result["safety_errors"] == 0
    assert result["p50_ms"] < 2.0, result
    assert result["p99_ms"] < 20, result
    assert result["seconds"] <= 4, result
    assert 0 < result["governor_seconds"] <= result["seconds"]
    tightened = profile_decisions(100, budget_seconds=0.01)
    assert tightened["reductions"] > 0 and tightened["final_scale"] < 1, tightened
