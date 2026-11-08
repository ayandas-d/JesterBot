"""Resumable seed allocation, immediate deduplicated alerts and bounded history."""

from concurrent.futures import ThreadPoolExecutor
import json
import pytest

from tools.league_state import reserve_seeds
from tools.league_alerts import alert, open_alerts


def test_restart_and_concurrent_allocations_never_reuse_seeds(tmp_path):
    path=tmp_path/"state.json"
    first=reserve_seeds(3,"cycle",path=path,minimum=1000,reserved={1001})
    assert first==[1000,1002,1003]
    with ThreadPoolExecutor(max_workers=4) as executor:
        blocks=list(executor.map(lambda _:reserve_seeds(10,"evolution",path=path),range(4)))
    all_seeds=first+[v for block in blocks for v in block]
    assert len(all_seeds)==len(set(all_seeds))
    assert min(reserve_seeds(1,"restart",path=path))>max(all_seeds)


def test_seed_allocator_tracks_high_water_mark_with_bounded_recent_records(tmp_path):
    path=tmp_path/"state.json"
    for _ in range(150):reserve_seeds(1,"cycle",path=path)
    state=json.loads(path.read_text())
    assert len(state["recent"])<=128 and state["next_seed"]>=1150


def test_alerts_are_immediate_deduplicated_and_survive_restart(tmp_path):
    path=tmp_path/"ALERTS.md"
    with ThreadPoolExecutor(max_workers=4) as executor:
        list(executor.map(lambda _:alert("same-event","SAFETY","test failure",path),range(8)))
    assert path.read_text().count("test failure")==1
    assert len(open_alerts(path))==1
    alert("other-event","FAIR LOSS","opponent won",path)
    assert len(open_alerts(path))==2


def test_judge_observer_alerts_at_the_failing_request_without_extra_http(tmp_path,monkeypatch):
    from tools.judge_timing_audit import ObservedHandle,judge
    from game import AgentConfig
    path=tmp_path/"ALERTS.md"
    monkeypatch.setenv("LEAGUE_ALERT_PATH",str(path))
    monkeypatch.setenv("LEAGUE_ALERT_CONTEXT","test-request")
    calls=[]
    def fail(self,*args):
        calls.append(args)
        self.stats.errors+=1
        self.stats.time_seconds=4.01
        return None
    monkeypatch.setattr(judge.HttpAgentHandle,"_post",fail)
    handle=ObservedHandle("http://localhost:1",AgentConfig(),role="agent1")
    handle._post("choose_action","/act",{})
    assert len(calls)==1
    assert "errors=1" in path.read_text() and "4.010000" in path.read_text()


def test_crash_recovery_replaces_serialized_inflight_seed_in_all_plan_copies(monkeypatch):
    from tools import continuous
    active=json.loads(json.dumps(dict(plan=[dict(opponent="x",seed=1000)],
        running=[dict(opponent="x",seed=1000)],training_plan=[dict(opponent="x",seed=1000)],
        metadata=dict(seeds=["1000"]))))
    monkeypatch.setattr(continuous,"reserve_seeds",lambda *args,**kwargs:[9000])
    continuous.recover_inflight(active)
    assert active["plan"][0]["seed"]==active["training_plan"][0]["seed"]==9000
    assert active["metadata"]["seeds"]==["9000"]
    assert active["abandoned_seeds"]==[1000] and not active["running"]


def test_crash_after_raw_result_saved_does_not_replay_that_seed(monkeypatch):
    from tools import continuous
    active=dict(plan=[dict(opponent="x",seed=1000)],running=[dict(opponent="x",seed=1000)],metadata={})
    monkeypatch.setattr(continuous,"reserve_seeds",lambda *_: (_ for _ in ()).throw(AssertionError("already finished")))
    continuous.recover_inflight(active,completed={("x","1000")})
    assert active["plan"][0]["seed"]==1000 and not active["running"]


def test_stop_file_prevents_all_work_and_writes_a_clean_dashboard(tmp_path,monkeypatch,capsys):
    from tools import continuous
    for name,filename in (("STATE","state.json"),("STOP","STOP"),("DASHBOARD","DASHBOARD.md"),("ALERTS","ALERTS.md")):
        monkeypatch.setattr(continuous,name,tmp_path/filename)
    continuous.STOP.touch()
    monkeypatch.setattr(continuous.signal,"signal",lambda *_:None)
    monkeypatch.setattr(continuous,"reserve_seeds",lambda *_: (_ for _ in ()).throw(AssertionError("STOP means no work")))
    continuous.main(["--cycles","2"])
    assert '"stopped_by_file": true' in capsys.readouterr().out
    assert "stopped cleanly" in continuous.DASHBOARD.read_text()


def test_raw_rotation_only_removes_explicit_old_owned_results(tmp_path,monkeypatch):
    from tools import continuous
    monkeypatch.setattr(continuous,"ROOT",tmp_path)
    results=tmp_path/"league/results";results.mkdir(parents=True)
    paths=[results/f"stamp_continuous-cycle-{i}.json" for i in range(4)]
    for p in paths:p.write_text("x"*128)
    unrelated=results/"user-audit.json";unrelated.write_text("keep")
    state=dict(raw_artifacts=list(map(str,paths)))
    continuous.rotate_raw(state,maximum_bytes=256,keep_cycles=2)
    assert not paths[0].exists() and paths[-1].exists() and unrelated.exists()
    assert len(state["raw_artifacts"])==2


def test_raw_rotation_refuses_to_touch_a_hall_of_fame_bot(tmp_path,monkeypatch):
    from tools import continuous
    monkeypatch.setattr(continuous,"ROOT",tmp_path)
    protected=tmp_path/"league/opponents/evolved/e0001/agent.py"
    protected.parent.mkdir(parents=True);protected.write_text("permanent")
    state=dict(raw_artifacts=[str(protected)]*3)
    with pytest.raises(ValueError,match="unowned"):
        continuous.rotate_raw(state,maximum_bytes=1)
    assert protected.read_text()=="permanent"
