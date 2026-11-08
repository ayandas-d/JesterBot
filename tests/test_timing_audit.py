"""Runtime isolation and measured timing controls for Phase 2."""

import ast
import json
from pathlib import Path

import pytest


ROOT = Path(__file__).resolve().parents[1]


def test_runtime_never_imports_or_reads_development_or_opponent_sources():
    forbidden = {"league", "tools", "tests"}
    for path in [ROOT / "agent.py", *(ROOT / "bot").glob("*.py")]:
        tree = ast.parse(path.read_text())
        # Existing launcher instructions in module docstrings are documentation,
        # not runtime imports or file access. Do not edit protected plumbing.
        docstrings = {id(node.value) for node in ast.walk(tree)
                      if isinstance(node, ast.Expr) and isinstance(node.value, ast.Constant)
                      and isinstance(node.value.value, str)}
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                assert not any(n.name.split(".")[0] in forbidden for n in node.names), path
            if isinstance(node, ast.ImportFrom):
                assert (node.module or "").split(".")[0] not in forbidden, path
            if isinstance(node, ast.Constant) and isinstance(node.value, str) and id(node) not in docstrings:
                value = node.value.replace("\\", "/")
                assert not any(f"{name}/" in value or value == name for name in forbidden), (path, value)
            if isinstance(node, ast.Call):
                name = node.func
                assert not (isinstance(name, ast.Attribute) and name.attr == "sleep"), path
                assert not (isinstance(name, ast.Name) and name.id == "sleep"), path


def test_time_bank_estimates_the_judges_per_request_charged_clock():
    from bot.timing import PhasedTiming
    from tests.test_timing import Stream, baselines
    timing = PhasedTiming()
    baselines(timing, overhead=.0006)
    timing.baselines[True].extend([.0006] * 16)
    timing.overhead[True] = .0006
    stream = Stream(timing)
    for hand in range(700):
        if hand:
            stream.now += .0015  # opponent's next-hand small-blind action
        stream.sample(hand, "weak", .0015)
    # Two opponent actions per hand; first request isn't directly observed and
    # is estimated from the other 1,399. Each request gets its own 1 ms grace.
    assert timing.bank_estimate == pytest.approx(1400 * (.0015 - .001), abs=1e-8)
    assert timing.bank_coverage > .99


def test_diagnostics_are_opt_in_and_emit_only_to_stderr(monkeypatch, capsys):
    from bot.timing import PhasedTiming
    monkeypatch.delenv("JESTER_DIAG", raising=False)
    silent = PhasedTiming()
    silent.emit_diagnostics()
    assert not capsys.readouterr().err
    monkeypatch.setenv("JESTER_DIAG", "1")
    timing = PhasedTiming()
    timing.emit_diagnostics()
    captured = capsys.readouterr()
    assert captured.out == ""
    value = json.loads(captured.err.removeprefix("JESTER_TIMING "))
    assert value["gate"]["decision"] == "pending"
    assert value["showdown_labelled_clean_samples"] == 0
    assert value["nudges"] == []


def test_bank_does_not_extrapolate_fast_streets_to_slower_hand_boundaries():
    from bot.timing import PhasedTiming
    from tests.test_timing import Stream, baselines
    timing = PhasedTiming()
    baselines(timing, overhead=.0006)
    stream = Stream(timing)
    for hand in range(700):
        if hand:
            stream.now += .0015 if hand < 350 else .003
        stream.sample(hand, "weak", .0015)
    # Matching cross-hand baseline is absent, but this synthetic stream has
    # the same overhead on both sides. Count its observed gaps rather than
    # extrapolating only the cheaper within-hand requests.
    truth = 700 * .0005 + 350 * .0005 + 350 * .002
    assert timing.bank_estimate == pytest.approx(truth, abs=.001)


def test_false_open_fake_strength_tell_has_zero_default_policy_effect(monkeypatch, record_property):
    from random import Random
    from bot import fallback
    from bot.timing import TIMING_NUDGES
    from game import AgentConfig, Game, make_deal

    assert TIMING_NUDGES is False
    monkeypatch.setenv("BOT_SEED", "fake-tell-counterfactual")
    # Fixed deterministic reference strength isolates the timing policy from
    # real-clock deadline noise; full live pairs separately measure that noise.
    monkeypatch.setattr(fallback, "equity", lambda hole, *_a, **_k: .3 + sum(hole) % 41 / 100)
    outputs = []
    for enabled in (False, True):
        state = fallback.State(AgentConfig())
        state.timing.enabled = enabled
        opponent = Random(1047)
        actions, net = [], 0
        for index in range(700, 800):
            game = Game(make_deal("fake-tell-counterfactual", index), index % 2, hand_index=index)
            while not game.is_terminal:
                obs = game.observation(game.to_act)
                if game.to_act == 0:
                    state.opponent.observe(obs, state.gear)
                    context = (int(obs.street), 1, False)
                    state.timing.gate = "open"
                    state.timing.current = (context, .040)
                    state.timing.current_hand = index
                    # An adversarial model always claims the opponent is weak.
                    state.timing.models = {context: {"weak": (.040, .001)}}
                    action = fallback.policy(obs, state)
                    state.opponent.record_action(obs, action)
                    actions.append(action)
                else:
                    action = opponent.choice(obs.legal_actions)
                game.apply(action)
            outcome = game.hand_result(0)
            net += outcome.my_net / 2
            state.end(outcome)
        assert state.timing.nudged_decisions == 0
        outputs.append((actions, net))
    record_property("forced_fake_tell_difference_bb", outputs[1][1] - outputs[0][1])
    assert outputs[0] == outputs[1]


def test_control_failure_cleans_children_even_if_parent_already_exited(monkeypatch):
    import signal
    from tools import timing_controls
    killed = []
    class FailedParent:
        pid = 123456
        def wait(self, timeout=None):
            return 1
        def poll(self):
            return 1
    monkeypatch.setattr(timing_controls.subprocess, "Popen", lambda *_a, **_k: FailedParent())
    monkeypatch.setattr(timing_controls.os, "killpg", lambda pid, sig: killed.append((pid, sig)))
    with pytest.raises(RuntimeError, match="exited 1"):
        timing_controls.run_control("positive")
    assert (123456, signal.SIGTERM) in killed


def test_strength_band_uses_fixed_comparison_count_when_checking_free():
    from bot.policy import action_probabilities
    from game import Action, Game, make_deal
    class CountedStrength(float):
        def __ge__(self, other):
            self.comparisons += int(other not in (0, 1))
            return float.__ge__(self, other)
    game = Game(make_deal("fixed-band-work", 0), 0)
    game.apply(Action.CHECK_CALL)
    game.apply(Action.CHECK_CALL)
    for value in (.1, .5, .7, .95):
        strength = CountedStrength(value)
        strength.comparisons = 0
        action_probabilities(game.observation(game.to_act), strength, "MANIAC")
        assert strength.comparisons == 3


def test_fixed_work_policy_preserves_frozen_v2_distributions():
    import importlib.util
    from random import Random
    from bot.policy import CONFIG, action_probabilities, half_parameters
    from game import Game, make_deal
    spec = importlib.util.spec_from_file_location("v2_policy_reference", ROOT / "league/champions/v2/bot/policy.py")
    reference = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(reference)
    rng = Random(1048)
    for index in range(100):
        game = Game(make_deal("policy-work-equivalence", index), index % 2)
        parameters = half_parameters(rng)
        while not game.is_terminal:
            obs = game.observation(game.to_act)
            for gear in CONFIG["gears"]:
                for strength in (0.0, .30, .48, .50, .62, .84, 1.0):
                    assert action_probabilities(obs, strength, gear, parameters) == reference.action_probabilities(obs, strength, gear, parameters)
            game.apply(rng.choice(obs.legal_actions))


def test_bluff_adjustment_work_does_not_skip_strong_hands():
    from bot.policy import action_probabilities
    from game import Action, Game, make_deal
    class CountedMultiplier(float):
        def __rmul__(self, other):
            self.products += 1
            return float(other) * float(self)
    game = Game(make_deal("fixed-bluff-work", 0), 0)
    game.apply(Action.CHECK_CALL)
    game.apply(Action.CHECK_CALL)
    for strength in (.1, .5, .7, .95):
        multiplier = CountedMultiplier(1.0)
        multiplier.products = 0
        action_probabilities(game.observation(game.to_act), strength, "MANIAC", bluff_multiplier=multiplier)
        assert multiplier.products == 1


def test_strength_fitting_runs_only_at_predeclared_gate_checks(monkeypatch):
    from bot.timing import PhasedTiming
    timing = PhasedTiming()
    timing.baselines[False].extend([.0006] * 16)
    calls = []
    original = timing._fit
    def measured(groups):
        calls.append(1)
        return original(groups)
    monkeypatch.setattr(timing, "_fit", measured)
    for hand in range(90):
        timing._label(hand, (0, 1, False), .001 if hand % 2 else .010, 0 if hand % 2 else 8)
    assert not calls
    timing._gate(300)
    assert calls and timing.gate == "open"


def test_judge_prefix_reference_does_not_send_extra_requests(monkeypatch):
    from tools.judge_timing_audit import ObservedHandle
    from game import AgentConfig, Game, make_deal, Action
    handle = ObservedHandle("http://localhost:1", AgentConfig())
    handle.prefixes.append({})
    handle.stats.time_seconds = 1.25
    monkeypatch.setattr(handle, "_request", lambda *_a, **_k: pytest.fail("observer must not probe"))
    game = Game(make_deal("reference-prefix", 699), 0, hand_index=699)
    game.apply(Action.FOLD)
    handle.hand_end(game.hand_result(0))
    assert handle.prefixes[0]["700"]["time_seconds"] == 1.25
    handle.stats.time_seconds = 2.0
    assert handle.prefixes[0]["700"]["time_seconds"] == 1.25


def test_timing_nudge_diagnostics_count_changed_distributions_only():
    from bot.fallback import State
    from game import AgentConfig, Game, make_deal
    state = State(AgentConfig())
    obs = Game(make_deal("nudge-counter", 700), 0, hand_index=700).observation(0)
    # Far below the price floor, neither a returned hint nor a counterfactual
    # multiplier changes the fold distribution. It was never an applied nudge.
    state.timing.record_nudge(obs, 0, "MANIAC", state.gear_parameters, 1, 1.10)
    assert state.timing.nudged_decisions == 0
