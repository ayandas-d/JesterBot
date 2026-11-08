"""Every declared opponent has provenance and answers the HTTP contract."""

import hashlib
import importlib.util
from pathlib import Path

from fastapi.testclient import TestClient
import pytest

from game import Action, AgentConfig, Game, make_deal
from tools.league import load_config, champions, tier_of
from tools.oracle_judge.privileges import information

ROOT=Path(__file__).resolve().parents[1]
CONFIG=load_config()
NAMES=list(dict.fromkeys(CONFIG["training"]["opponents"]+CONFIG["holdout"]["opponents"]+
                        [n for n in CONFIG["opponents"] if tier_of(n,CONFIG)=="C"]))


def test_expanded_registry_has_required_tiers_and_disjoint_fresh_holdout():
    training=CONFIG["training"]["opponents"]+champions()
    holdout=CONFIG["holdout"]["opponents"]
    assert 58<=len(training)<=70
    assert 11<=len(holdout)<=14  # twelve after evolved reserve is published
    assert not set(training)&set(holdout)
    assert sum(tier_of(n,CONFIG)=="H" for n in holdout)>=4
    assert any(CONFIG["opponents"][n].get("unique_idea") for n in holdout)
    assert not set(CONFIG["training"]["seeds"])&set(CONFIG["holdout"]["seeds"])
    assert not any(tier_of(n,CONFIG)=="C" for n in training+holdout)


@pytest.mark.parametrize("name",NAMES)
def test_registered_server_smoke_and_source_manifest(name,monkeypatch):
    entry=CONFIG["opponents"][name]
    path=ROOT/entry["script"]
    assert hashlib.sha256(path.read_bytes()).hexdigest()==entry["source_sha256"]
    for relative,digest in entry["source_files"].items():
        assert hashlib.sha256((ROOT/relative).read_bytes()).hexdigest()==digest
    spec=importlib.util.spec_from_file_location("registry_"+name,path)
    module=importlib.util.module_from_spec(spec);spec.loader.exec_module(module)
    assert module.__doc__ and ("PORT" in path.read_text() or "serve(" in path.read_text())
    if hasattr(module,"sleep"):monkeypatch.setattr(module,"sleep",lambda _:None)
    game=Game(make_deal("registry-contract",0),0)
    obs=game.observation(game.to_act)
    with TestClient(module.app) as client:
        assert client.get("/").status_code==200
        assert client.post("/new-half",json={"config":AgentConfig().to_dict()}).status_code==200
        payload=dict(observation=obs.to_dict(),hand_results=[])
        if entry["tier"]=="C":payload["oracle"]=information(game,game.to_act,name,None)
        reply=client.post("/act",json=payload)
        assert reply.status_code==200,reply.text
        assert Action[reply.json()["action"]] in obs.legal_actions
        game.apply(Action.FOLD)
        assert client.post("/hand-end",json={"results":[game.hand_result(0).to_dict()]}).status_code==200
