from collections import Counter
from copy import deepcopy
from dataclasses import replace
from math import isclose, isfinite
from random import Random

import pytest

import agent
from bot.policy import CONFIG, action_probabilities, half_parameters, sample_action
from game import Action, AgentConfig, Game, Street, make_deal
from tests.fuzz_states import fuzz_hands
from tools.profile_policy import profile_policy

RAISES = (Action.RAISE_HALF, Action.RAISE_POT)


@pytest.fixture(scope="module")
def states():
    values = []
    fuzz_hands(values.append)
    assert len(values) > 10_000
    assert {obs.street for obs in values} == set(Street)
    return values


def flop_observation(reraised=False):
    game = Game(make_deal("policy-flop", 0), 0)
    game.apply(Action.CHECK_CALL)
    game.apply(Action.CHECK_CALL)
    if reraised:
        game.apply(Action.RAISE_HALF)
        game.apply(Action.RAISE_POT)
    return game.observation(game.to_act)


@pytest.mark.parametrize("gear", tuple(CONFIG["gears"]))
def test_every_gear_is_legal_and_normalized_across_shared_fuzz(states, gear):
    rng = Random(310)
    params = half_parameters(rng)
    for index, obs in enumerate(states):
        strength = (index % 101) / 100  # includes both endpoints and every band
        probabilities = action_probabilities(obs, strength, gear, params)
        assert set(probabilities) == set(obs.legal_actions)
        assert all(isfinite(p) and 0 <= p <= 1 for p in probabilities.values())
        assert isclose(sum(probabilities.values()), 1.0, abs_tol=1e-12)
        assert sample_action(obs, strength, gear, rng, params) in obs.legal_actions
        if obs.to_call == 0:
            assert probabilities.get(Action.FOLD, 0) == 0


def test_maniac_raises_at_least_eighty_percent_and_value_bluffs_less(states, record_property):
    result = profile_policy(states=states)
    for gear, metrics in result["gears"].items():
        record_property(f"{gear}_raise_rate", metrics["raise_rate"])
        record_property(f"{gear}_low_equity_raise_rate", metrics["low_equity_free_raise_rate"])
    assert result["raise_legal_sample"] >= 3000
    maniac, value = result["gears"]["MANIAC"], result["gears"]["VALUE"]
    assert maniac["raise_rate"] >= 0.80, result
    assert maniac["expected_raise_rate"] >= 0.80, result
    assert maniac["low_equity_free_raise_rate"] > 0.90
    assert value["low_equity_free_raise_rate"] < 0.02
    assert value["low_equity_free_raise_rate"] < maniac["low_equity_free_raise_rate"] * 0.05


@pytest.mark.parametrize("gear", tuple(CONFIG["gears"]))
def test_hopeless_hands_do_not_continue_to_big_bets(states, gear):
    big_bets = [obs for obs in states if obs.to_call > 0 and
                min(obs.to_call, obs.my_stack) / obs.pot >= 0.40]
    assert len(big_bets) >= 100
    rng = Random(311)
    params = half_parameters(rng)
    calls = 0
    for obs in big_bets:
        call = min(obs.to_call, obs.my_stack)
        odds = call / (obs.pot + call)
        strength = max(0, odds - 0.20)
        probabilities = action_probabilities(obs, strength, gear, params)
        assert probabilities[Action.CHECK_CALL] == 0
        assert sum(probabilities.get(a, 0) for a in RAISES) == 0
        calls += sample_action(obs, strength, gear, rng, params) == Action.CHECK_CALL
    assert calls / len(big_bets) <= 0.01


def test_maniac_reraise_floor_is_not_loosened_by_jitter():
    game = Game(make_deal("reraise", 0), 0)
    game.apply(Action.RAISE_POT)
    game.apply(Action.RAISE_POT)
    obs = game.observation(game.to_act)
    assert obs.raises_this_street == 2 and obs.to_call > 0
    odds = obs.to_call / (obs.pot + obs.to_call)
    for seed in range(20):
        params = half_parameters(Random(seed))
        margin = CONFIG["gears"]["MANIAC"]["call_margin"]
        bad = action_probabilities(obs, odds + margin - 0.00001, "MANIAC", params)
        assert bad[Action.FOLD] == 1.0
        good = action_probabilities(obs, odds + margin + 0.00001, "MANIAC", params)
        assert sum(good.get(a, 0) for a in RAISES) >= 0.90


def test_trap_slowplays_strong_hands_and_reraises_top_range():
    obs = flop_observation()
    trap = action_probabilities(obs, 0.72, "TRAP")
    aggro = action_probabilities(obs, 0.72, "AGGRO")
    assert trap[Action.CHECK_CALL] > 0.70
    assert aggro[Action.CHECK_CALL] < 0.20
    top = action_probabilities(flop_observation(reraised=True), 0.95, "TRAP")
    assert sum(top.get(a, 0) for a in RAISES) > 0.85


def test_aggro_raises_medium_equity_draws_and_value_sizes_bigger():
    obs = flop_observation()
    draw = action_probabilities(obs, 0.55, "AGGRO")
    trash = action_probabilities(obs, 0.10, "AGGRO")
    assert sum(draw.get(a, 0) for a in RAISES) > 0.60
    assert sum(trash.get(a, 0) for a in RAISES) < 0.20
    value = action_probabilities(obs, 0.60, "VALUE")
    assert sum(value.get(a, 0) for a in RAISES) > 0.70
    aggro = action_probabilities(obs, 0.60, "AGGRO")
    conditional_pot = lambda p: p[Action.RAISE_POT] / (p[Action.RAISE_POT] + p[Action.RAISE_HALF])
    assert conditional_pot(value) > conditional_pot(aggro)


def test_sampler_matches_distribution_and_mixes_sizes():
    obs = flop_observation()
    probabilities = action_probabilities(obs, 0.40, "MANIAC")
    rng = Random(312)
    counts = Counter(sample_action(obs, 0.40, "MANIAC", rng) for _ in range(20_000))
    for action, probability in probabilities.items():
        assert abs(counts[action] / 20_000 - probability) < 0.015
    assert counts[Action.RAISE_POT] > counts[Action.RAISE_HALF] > 0


def test_jitter_is_bounded_half_local_seeded_and_does_not_mutate_config(monkeypatch):
    original = deepcopy(CONFIG)
    params = half_parameters(Random(313))
    assert params == half_parameters(Random(313))
    assert params != half_parameters(Random(314))
    assert CONFIG == original
    for gear, values in params.items():
        for street, thresholds in values["thresholds"].items():
            base = CONFIG["gears"][gear]["thresholds"][street]
            assert thresholds["medium"] < thresholds["strong"] < thresholds["top"]
            assert all(abs(value - base[band]) <= CONFIG["threshold_jitter"] for band, value in thresholds.items())
    monkeypatch.setenv("BOT_SEED", "half-jitter")
    memory = {}
    agent.new_half(AgentConfig(), memory)
    first = deepcopy(memory["bot"].gear_parameters)
    memory["bot"].gear = "VALUE"
    agent.new_half(AgentConfig(), memory)
    assert memory["bot"].gear == "MANIAC"
    assert memory["bot"].gear_parameters == first


def test_live_adapter_uses_selected_gear_and_our_rng(monkeypatch):
    from bot import fallback
    state = fallback.State(AgentConfig())
    obs = flop_observation()
    monkeypatch.setattr(fallback, "equity", lambda *args, **kwargs: 0.10)
    state.gear = "VALUE"
    values = Counter(fallback.policy(obs, state) for _ in range(2000))
    assert sum(values[a] for a in RAISES) / 2000 < 0.02
    state.gear = "MANIAC"
    values = Counter(fallback.policy(obs, state) for _ in range(2000))
    assert sum(values[a] for a in RAISES) / 2000 >= 0.90


def test_restricting_available_raise_sizes_preserves_normalization():
    obs = replace(flop_observation(), legal_actions=(Action.CHECK_CALL, Action.RAISE_HALF))
    for gear in CONFIG["gears"]:
        probabilities = action_probabilities(obs, 0.95, gear)
        assert sum(probabilities.values()) == pytest.approx(1.0)
        assert probabilities[Action.RAISE_HALF] > 0


@pytest.mark.parametrize("strength", [float("nan"), float("inf"), -0.1, 1.1])
def test_invalid_strength_is_rejected(strength):
    with pytest.raises(ValueError):
        action_probabilities(flop_observation(), strength)
