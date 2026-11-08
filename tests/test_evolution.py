"""Search randomness, immutable adversaries and training-only selection."""

from random import Random
import json

import pytest

from tools.evolve_adversary import random_parameters, child_parameters, write_frozen, qualified


def test_search_and_genetic_children_are_reproducible_and_bounded():
    a, b = Random(7), Random(7)
    parents = [random_parameters(a) for _ in range(4)]
    assert parents == [random_parameters(b) for _ in range(4)]
    for _ in range(50):
        child = child_parameters(parents[0], parents[1], a)
        assert 0 <= child["bluff"] <= .22 and 0 <= child["range_bias"] <= 1
        assert .45 <= child["raise_threshold"] <= .90
        assert 8 <= child["bait_length"] <= 120


def test_frozen_adversary_has_its_own_code_manifest_and_cannot_be_overwritten(tmp_path):
    target = tmp_path / "e0001"
    metadata = write_frozen(target, random_parameters(Random(7)), {"target_champion": "v2"})
    assert metadata["parameters"] and metadata["target_champion"] == "v2"
    assert set(metadata["source_sha256"]) == {"agent.py", "family.py", "server.py"}
    assert 'parametric' not in (target / "agent.py").read_text()
    assert (target / "family.py").is_file()
    assert json.loads((target / "META.json").read_text()) == metadata
    with pytest.raises(FileExistsError):
        write_frozen(target, {}, {})


def test_safety_failure_never_produces_an_adversary_winner():
    report = {"complete": True, "summary": {"mean_bb_per_deal": -.4, "safety_violations": []}}
    assert qualified(report)
    report["summary"]["safety_violations"] = ["error"]
    assert not qualified(report)
    report["summary"].update(safety_violations=[], mean_bb_per_deal=.6)
    assert not qualified(report)


def test_frozen_adversary_tampering_is_detected_before_launch(tmp_path):
    from tools import evolve_adversary
    target=tmp_path/"e0001"
    write_frozen(target,random_parameters(Random(8)),{})
    assert evolve_adversary.verify_frozen(target)["parameters"]
    (target/"family.py").write_text("# modified")
    with pytest.raises(ValueError,match="immutable"):
        evolve_adversary.verify_frozen(target)
