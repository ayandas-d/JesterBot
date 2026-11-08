"""Snapshot isolation, holdout guards, league scoring and adversary contracts."""

from argparse import Namespace
from copy import deepcopy
import importlib
import json
import os
from pathlib import Path
from random import Random
import subprocess
import sys
from threading import Event

from fastapi.testclient import TestClient
import pytest

from game import Action, AgentConfig, Game, make_deal
from league.opponents import styles
from tools import league
from tools.snapshot import snapshot, verify


def options(**kwargs):
    values = dict(group="training", quick=False, full=False, head_to_head=None,
                  opponents=None, seeds=None, deals=None, jobs=1, milestone=None, challenger="live")
    return Namespace(**(values | kwargs))


def test_holdout_names_and_seeds_are_disjoint_and_cannot_be_used_accidentally():
    config = league.load_config()
    assert len(config["holdout"]["opponents"]) >= 3
    assert set(config["holdout"]["opponents"]) <= set(config["opponents"])
    opponents, seeds, deals = league.plan(options(quick=True), config)
    assert len(seeds) == 3 and seeds == ["1", "2", "3"] and deals == 300
    assert "v1" in opponents and not set(opponents) & set(config["holdout"]["opponents"])
    for args in (options(group="holdout"), options(opponents=["gto_ish"]),
                 options(seeds=["101"]), options(quick=True, seeds=["1"]),
                 options(full=True, seeds=["1"]), options(seeds=["1", "1"]),
                 options(opponents=["check_fold", "check_fold"])):
        with pytest.raises(ValueError):
            league.plan(args, config)
    names, seeds, deals = league.plan(options(group="holdout", milestone="release-review", full=True), config)
    assert names == config["holdout"]["opponents"] and seeds == list(map(str, config["holdout"]["seeds"])) and deals == 1000


def test_champions_are_discovered_dynamically_and_head_to_head_pools_deals():
    config = league.load_config()
    assert "v1" in league.champions()
    names, seeds, deals = league.plan(options(head_to_head="v1", seeds=["1", "2"]), config)
    assert names == ["v1"] and seeds == ["1", "2"] and deals == 1000
    rows = [{"opponent": "v1", "seed": str(i), "points": p, "safety_violations": [],
             "raw": {"paired_bb": values}} for i, p, values in [(1, 1, [2, 4]), (2, .5, [-1, 3])]]
    summary = league.summarize(rows)
    assert summary["tournament_points"] == 1.5
    assert summary["mean_bb_per_deal"] == 2 and summary["deals"] == 4
    assert summary["ci"][0] < 2 < summary["ci"][1]
    assert summary["opponents"]["v1"]["ci"] == summary["ci"]


def test_retired_holdout_names_and_seeds_still_require_a_milestone(monkeypatch):
    config = league.load_config()
    config["holdout_history"] = [{"opponents": ["retired_control"], "seeds": [999]}]
    monkeypatch.setattr(league, "command", lambda *_: [])
    for args in (options(opponents=["retired_control"], seeds=["1"]),
                 options(opponents=["check_fold"], seeds=["999"])):
        with pytest.raises(ValueError, match="holdout"):
            league.plan(args, config)
    names, seeds, _ = league.plan(options(opponents=["retired_control"], seeds=["999"], milestone="historical-audit"), config)
    assert names == ["retired_control"] and seeds == ["999"]


def test_expected_crashy_forfeit_is_separate_from_our_safety_failures():
    half = dict(errors=0, forfeited=False, skipped_calls=0, timed_out=False, time_seconds=1)
    report = {"agent_stats": {p: [deepcopy(half), deepcopy(half)] for p in ("agent1", "agent2")}}
    report["agent_stats"]["agent2"][0].update(errors=5, forfeited=True, skipped_calls=100)
    diagnostics = [dict(final=True, safety_errors=0)] * 2
    issues, expected = league.violations(report, diagnostics, "crashy", league.load_config())
    assert not issues and len(expected) == 3
    report["agent_stats"]["agent1"][1]["errors"] = 1
    assert league.violations(report, diagnostics, "crashy", league.load_config())[0]
    assert league.violations(report, diagnostics, "anti_maniac", league.load_config())[0]


def test_our_four_second_ceiling_is_distinct_from_test_opponents_own_bank():
    half = dict(errors=0, forfeited=False, skipped_calls=0, timed_out=False, time_seconds=1)
    report = {"agent_stats": {p: [deepcopy(half), deepcopy(half)] for p in ("agent1", "agent2")}}
    diagnostics = [dict(final=True, safety_errors=0)] * 2
    # The deliberate-delay fixture is required to fit its own 8 s bank.
    # Jester must still meet our stricter 4 s ceiling in every comparison.
    report["agent_stats"]["agent2"][0]["time_seconds"] = 4.5
    assert not league.violations(report, diagnostics, "strong_tell", league.load_config())[0]
    report["agent_stats"]["agent1"][0]["time_seconds"] = 4.01
    assert "agent1/half1/think=4.010s" in league.violations(report, diagnostics, "strong_tell", league.load_config())[0]
    report["agent_stats"]["agent1"][0]["time_seconds"] = 1
    report["agent_stats"]["agent2"][0]["time_seconds"] = 8.01
    assert league.violations(report, diagnostics, "strong_tell", league.load_config())[0]


def test_snapshot_numbering_hashes_and_independence(tmp_path):
    root = tmp_path / "repo"
    (root / "bot").mkdir(parents=True)
    for name in ("agent.py", "game.py", "evaluator.py", "bot/__init__.py", "bot/policy.py"):
        (root / name).write_text(f"# initial {name}\n")
    subprocess.run(["git", "init", "-q", str(root)], check=True)
    subprocess.run(["git", "add", "."], cwd=root, check=True)
    subprocess.run(["git", "-c", "user.name=Snapshot Test", "-c", "user.email=snapshot@example.invalid",
                    "commit", "-qm", "fixture"], cwd=root, check=True)
    first = snapshot(root)
    assert first.name == "v1" and verify(first)["runtime_dirty"] is False
    original = (first / "bot/policy.py").read_text()
    (root / "bot/policy.py").write_text("# changed live source\n")
    second = snapshot(root)
    assert second.name == "v2" and verify(second)["runtime_dirty"] is True
    assert (first / "bot/policy.py").read_text() == original
    (first / "bot/policy.py").write_text("# tampered snapshot\n")
    with pytest.raises(ValueError, match="snapshot file changed"):
        verify(first)


def test_real_v1_runtime_imports_are_isolated_from_live_pythonpath():
    root = Path(__file__).resolve().parents[1]
    output = subprocess.check_output([sys.executable, "tools/run_snapshot.py", "v1", "--inspect"], cwd=root,
                                     env=dict(os.environ, PYTHONPATH=str(root)), text=True)
    paths = json.loads(output)
    snapshot_root = root / "league/champions/v1"
    assert {"agent", "game", "evaluator", "bot", "bot.policy"} <= set(paths)
    assert all(Path(p).is_relative_to(snapshot_root) for p in paths.values())
    assert verify(snapshot_root)["commit_sha"] == "486507685c326ee891397c03adb2af8321fbc201"


@pytest.mark.parametrize("name", ["anti_maniac", "adaptive_counter", "gto_ish", "tight_aggressive",
                                 "loose_passive", "bluff_heavy", "erratic", "slow_starter", "crashy"])
def test_new_opponent_http_contracts_and_legal_decisions(name, monkeypatch):
    module = importlib.import_module(f"league.opponents.{name}")
    monkeypatch.setattr(module, "TOKEN", None)
    with TestClient(module.app) as client:
        assert client.post("/new-half", json={"config": AgentConfig().to_dict()}).status_code == 200
        rng = Random(640)
        for index in range(5):
            game = Game(make_deal("league-contract", index), index % 2, hand_index=index)
            while not game.is_terminal:
                obs = game.observation(game.to_act)
                reply = client.post("/act", json={"observation": obs.to_dict(), "hand_results": []})
                assert reply.status_code == 200
                assert Action[reply.json()["action"]] in obs.legal_actions
                game.apply(rng.choice(obs.legal_actions))


def test_crashy_and_slow_starter_are_deliberate_and_deterministic(monkeypatch):
    obs = Game(make_deal("league-collapse", 0), 0, hand_index=900).observation(0)
    memory = {}
    styles.initialize_style("slow_starter", AgentConfig(), memory)
    assert 350 <= memory["collapse_hand"] < 750
    assert styles.choose_style("slow_starter", obs, memory) == Action.FOLD
    styles.initialize_style("crashy", AgentConfig(), memory)
    monkeypatch.setattr(styles, "estimate", lambda *_: .5)
    failures = 0
    for _ in range(100):
        try:
            styles.choose_style("crashy", obs, memory)
        except RuntimeError as exc:
            assert "intentional league fault" in str(exc)
            failures += 1
    assert failures >= 5


def test_cancellation_before_launch_creates_no_process(monkeypatch, tmp_path):
    stop = Event()
    stop.set()
    monkeypatch.setattr(league.subprocess, "Popen", lambda *_a, **_k: pytest.fail("must not launch after cancellation"))
    with pytest.raises(InterruptedError):
        league.run_one("live", "check_fold", "1", 10, tmp_path, league.load_config(), stop)


@pytest.mark.parametrize("failure", ["startup", "judge_timeout"])
def test_runner_failure_cleans_every_owned_process_and_socket(failure, monkeypatch, tmp_path):
    launched, sockets = [], []
    class FakeSocket:
        closed = False
        def __init__(self):
            sockets.append(self)
        def bind(self, address):
            pass
        def getsockname(self):
            return ("127.0.0.1", 5020 + sockets.index(self))
        def close(self):
            self.closed = True
    class FakeProcess:
        returncode = None
        terminated = False
        def __init__(self, *args, **kwargs):
            launched.append(self)
        def poll(self):
            return self.returncode
        def terminate(self):
            self.terminated, self.returncode = True, -15
        def wait(self, timeout=None):
            return self.returncode
    monkeypatch.setattr(league.socket, "socket", FakeSocket)
    monkeypatch.setattr(league.subprocess, "Popen", FakeProcess)
    def ready(*args):
        if failure == "startup" and len(launched) == 2:
            raise RuntimeError("injected startup failure")
    monkeypatch.setattr(league, "ready", ready)
    with pytest.raises(RuntimeError if failure == "startup" else TimeoutError):
        league.run_one("live", "check_fold", "1", 10, tmp_path, league.load_config(), Event(), timeout=-1)
    assert len(launched) == (2 if failure == "startup" else 3)
    assert all(process.terminated for process in launched)
    assert all(sock.closed for sock in sockets)
    assert all(handle.name in ("agent1.log", "agent2.log", "judge.log") for handle in tmp_path.iterdir())


def test_history_appends_one_header_and_one_record_per_run(tmp_path):
    import csv
    from concurrent.futures import ThreadPoolExecutor
    path = tmp_path / "history.csv"
    base = {"timestamp": "test", "label": "run", "challenger": "v1", "commit": "a" * 40,
            "group": "training", "deals": 300, "seeds": "1;2;3", "matches": 42,
            "points": 34.5, "mean_bb_per_deal": 2.4, "worst_matchup": "slow_tell",
            "safety_violations": 0, "complete": True, "result": "league/results/test.json"}
    with ThreadPoolExecutor(max_workers=4) as executor:
        list(executor.map(lambda i: league.append_history(path, base | {"label": f"run-{i}"}), range(8)))
    with path.open(newline="") as handle:
        rows = list(csv.DictReader(handle))
    assert len(rows) == 8 and {row["label"] for row in rows} == {f"run-{i}" for i in range(8)}
