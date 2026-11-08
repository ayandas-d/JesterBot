"""Tier separation, cache identity and sequential evidence contracts."""

from copy import deepcopy
from pathlib import Path

from tools.league_features import tier_of, tier_summary, cache_key, decisive


def test_cheater_points_never_enter_fair_score():
    rows = [dict(tier=t, points=p, opponent=t, raw={"paired_bb": [v, v]})
            for t, p, v in (("F", 1, 2), ("H", .5, 0), ("C", 1, -8))]
    summary = tier_summary(rows)
    assert summary["fair_points"] == 1.5
    assert summary["fair_mean_bb_per_deal"] == 1
    assert summary["tiers"]["C"]["points"] is None
    assert summary["tiers"]["C"]["mean_bb_per_deal"] == -8


def test_past_champions_are_hard_and_explicit_tiers_override_default():
    config = {"opponents": {"x": {"tier": "C"}, "y": {"tier": "H"}}}
    assert [tier_of(name, config) for name in ("v1", "x", "y", "unlisted")] == ["H", "C", "H", "F"]


def test_cache_identity_covers_sources_rules_seeds_and_computation(tmp_path):
    base = dict(challenger={"a": "hash"}, opponent={"b": "hash"}, rules="judgehash",
                seed="1", deals=1000, bot_seed="7", mode="configured", jobs=2)
    original = cache_key(base)
    for key, replacement in (("seed", "2"), ("deals", 300), ("rules", "different"),
                             ("challenger", {"a": "changed"}), ("jobs", 1), ("mode", "disabled")):
        altered = dict(base, **{key: replacement})
        assert cache_key(altered) != original
    assert cache_key(dict(reversed(list(base.items())))) == original


def test_sequential_stopping_requires_minimum_seeds_and_decisive_ci():
    assert decisive([1.] * 100, seeds=19, minimum_seeds=20) is None
    assert decisive([1.] * 100, seeds=20, minimum_seeds=20) == "positive"
    assert decisive([-1.] * 100, seeds=20, minimum_seeds=20) == "negative"
    assert decisive([-1., 1.] * 100, seeds=20, minimum_seeds=20) is None


def test_full_cheater_mode_uses_its_separate_declared_seed_set():
    from tools import league
    from tests.test_league_infrastructure import options
    config=league.load_config()
    names,seeds,deals=league.plan(options(tier="C",full=True),config)
    assert names and all(tier_of(n,config)=="C" for n in names)
    assert seeds==list(map(str,config["cheaters"]["seeds"])) and deals==1000
