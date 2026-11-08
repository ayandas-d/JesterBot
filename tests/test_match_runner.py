"""Independent opponent contracts and runner failure/acceptance handling."""

from copy import deepcopy
from dataclasses import replace
import importlib
from pathlib import Path
import subprocess
import sys

from fastapi.testclient import TestClient
import pytest

from game import Action, AgentConfig, Game, make_deal
from tests.bots import common, slow_tell
from tests.fuzz_states import fuzz_hands
from tools import run_matches

NAMES = tuple(name for name in run_matches.OPPONENTS if name != "baseline_random")


@pytest.mark.parametrize("name", NAMES)
def test_opponent_server_contract_and_port_environment(name, monkeypatch):
    module = importlib.import_module(f"tests.bots.{name}")
    monkeypatch.setattr(module, "TOKEN", "test-secret")
    if name == "slow_tell":
        monkeypatch.setattr(module, "sleep", lambda _: None)
    module.STATUS["started"] = False
    with TestClient(module.app) as client:
        assert client.get("/").json()["agent_name"] == name
        assert client.post("/new-half", json={}).status_code == 401
        headers = {"x-agent-token": "test-secret"}
        assert client.post("/act", json={}, headers=headers).status_code == 409
        assert client.post("/new-half", json={"config": AgentConfig().to_dict()}, headers=headers).status_code == 200
        game = Game(make_deal("contract", 0), 0)
        obs = game.observation(0)
        reply = client.post("/act", json={"observation": obs.to_dict(), "hand_results": []}, headers=headers)
        assert Action[reply.json()["action"]] in obs.legal_actions
        game.apply(Action.FOLD)
        assert client.post("/hand-end", json={"results": [game.hand_result(0).to_dict()]}, headers=headers).status_code == 200
    assert 'os.environ.get("PORT", "5009")' in Path(module.__file__).read_text()


def test_all_opponents_return_legal_actions_across_engine_states(monkeypatch):
    modules = [importlib.import_module(f"tests.bots.{name}") for name in NAMES]
    monkeypatch.setattr(slow_tell, "sleep", lambda _: None)
    memories = [{} for _ in modules]
    for module, memory in zip(modules, memories):
        module.new_half(AgentConfig(), memory)
    def inspect(obs):
        for module, memory in zip(modules, memories):
            assert module.choose_action(obs, memory) in obs.legal_actions
    fuzz_hands(inspect, hands=80)


def test_slow_tell_delays_only_medium_hands_and_respects_fund_and_pace(monkeypatch):
    clock = [0.0]
    sleeps = []
    monkeypatch.setattr(slow_tell, "perf_counter", lambda: clock[0])
    def sleep(seconds):
        sleeps.append(seconds)
        clock[0] += seconds
    monkeypatch.setattr(slow_tell, "sleep", sleep)
    memory = {}
    slow_tell.new_half(AgentConfig(), memory)
    obs = Game(make_deal("tell-delay", 0), 0).observation(0)
    for i, strength in enumerate((.2, .8, .5)):
        monkeypatch.setattr(slow_tell, "estimate", lambda *args, value=strength: value)
        slow_tell.choose_action(replace(obs, hand_index=i), memory)
    assert sleeps == [.003]
    slow_tell.choose_action(replace(obs, hand_index=2), memory)
    assert sleeps == [.003]  # only once in a hand
    memory["sleep_total"] = 1.2
    slow_tell.choose_action(replace(obs, hand_index=3), memory)
    memory["sleep_total"] = 0
    memory["elapsed"] = 3.4
    slow_tell.choose_action(replace(obs, hand_index=500), memory)
    assert sleeps == [.003]


def test_independent_equity_counts_ties_and_respects_pot_odds(monkeypatch):
    monkeypatch.setattr(common, "omaha_score", lambda *_: 1)
    memory = {}
    common.initialize(AgentConfig(), memory)
    obs = Game(make_deal("equity-contract", 0), 0).observation(0)
    assert common.estimate(obs, memory, 20) == .5
    assert common.equity_action(obs, 0) == Action.FOLD
    assert common.equity_action(obs, .5) == Action.CHECK_CALL
    assert common.equity_action(obs, .9) == Action.RAISE_POT


@pytest.mark.parametrize("exception", [RuntimeError, KeyboardInterrupt, SystemExit])
def test_owned_processes_are_terminated_on_every_exit(exception):
    with pytest.raises(exception):
        with run_matches.processes() as owned:
            process = subprocess.Popen([sys.executable, "-c", "import threading; threading.Event().wait(30)"])
            owned.append(process)
            raise exception()
    assert process.poll() is not None


def test_stubborn_owned_process_is_killed_after_timeout():
    class Stubborn:
        terminated = killed = False
        def poll(self):
            return None
        def terminate(self):
            self.terminated = True
        def wait(self, timeout=None):
            if not self.killed:
                raise subprocess.TimeoutExpired("owned", timeout)
        def kill(self):
            self.killed = True
    process = Stubborn()
    with run_matches.processes() as owned:
        owned.append(process)
    assert process.terminated and process.killed


def test_acceptance_rejects_failures_in_either_bot_and_checks_behavior():
    half = dict(errors=0, forfeited=False, timed_out=False, skipped_calls=0, time_seconds=1.0)
    report = dict(verdict="AGENT1_WIN", mean_bb_per_deal=1.5,
                  agent_stats={"agent1": [deepcopy(half), deepcopy(half)], "agent2": [deepcopy(half), deepcopy(half)]})
    diagnostic = dict(final=True, safety_errors=0, exploit_raises=10, transitions=[(75, "MANIAC", "VALUE")])
    diagnostics = [deepcopy(diagnostic), deepcopy(diagnostic)]
    for name in run_matches.OPPONENTS:
        assert not run_matches.acceptance(name, report, diagnostics)
    for player in report["agent_stats"]:
        for key, value in (("errors", 1), ("forfeited", True), ("timed_out", True),
                           ("skipped_calls", 1), ("time_seconds", 4.1)):
            broken = deepcopy(report)
            broken["agent_stats"][player][1][key] = value
            assert run_matches.acceptance("baseline_random", broken, diagnostics)
    diagnostics[1]["transitions"] = []
    assert run_matches.acceptance("calling_station", report, diagnostics)
    diagnostics[1]["exploit_raises"] = 0
    assert run_matches.acceptance("check_fold", report, diagnostics)
    report["verdict"] = "AGENT2_WIN"
    assert run_matches.acceptance("pot_odds_bot", report, diagnostics)
    report["verdict"] = "CHOP"
    assert not run_matches.acceptance("pot_odds_bot", report, diagnostics)
    assert run_matches.acceptance("baseline_random", report, diagnostics)
