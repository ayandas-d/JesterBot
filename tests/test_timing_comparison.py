"""Promotion comparisons must use matched fields and preserve safety failures."""

from copy import deepcopy

import pytest

from tools.timing_comparison import compare


def document(values=(1, 2), verdict="AGENT1_WIN", points=1):
    half = dict(errors=0, forfeited=False, skipped_calls=0, timed_out=False, time_seconds=1)
    row = dict(opponent="example", seed="1", verdict=verdict, points=points,
               safety_violations=[], diagnostics=[dict(final=True, safety_errors=0)] * 2,
               timing_diagnostics=[], runtime_source_sha256={"agent.py": "fixture"},
               raw=dict(paired_bb=list(values), agent_stats={p: [deepcopy(half), deepcopy(half)]
                                                            for p in ("agent1", "agent2")}))
    return dict(complete=True, metadata=dict(config={"safety": {"max_thinking_seconds": 4,
                "expected_fault_opponents": []}}, deals=len(values)), matches=[row])


def test_win_to_loss_regression_is_not_hidden_by_positive_other_deals():
    before, after = document(), document((10, 11), "AGENT2_WIN", 0)
    result = compare(before, after)
    assert not result["gates"]["league"]
    assert not result["gates"]["no_regression"]
    assert result["win_to_loss"] == [["example", "1"]]


def test_paired_comparison_and_neutral_intervention_counts():
    result = compare(document(), document((2, 3)))
    assert result["paired_delta"]["mean_bb_per_deal"] == 1
    assert result["paired_delta"]["ci"] == [1, 1]
    assert result["interventions"] == {"nudged_decisions": 0, "lowered_k_decisions": 0}
    assert all(result["gates"].values())


def test_changed_field_or_missing_matches_cannot_pass():
    after = document()
    after["matches"][0]["seed"] = "2"
    with pytest.raises(ValueError, match="matched"):
        compare(document(), after)
    after = document()
    after["complete"] = False
    with pytest.raises(ValueError, match="complete"):
        compare(document(), after)


def test_jester_charged_time_above_ceiling_fails_even_if_internal_timer_is_low():
    after = document()
    after["matches"][0]["raw"]["agent_stats"]["agent1"][0]["time_seconds"] = 4.01
    assert not compare(document(), after)["gates"]["safety"]
