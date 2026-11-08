"""Independent statistical controls; no real clocks or bot policy RNG draws."""

import json
from pathlib import Path
from random import Random
from math import comb

import pytest

from bot.timing_gate import ActionTimingGate, CONFIG, upper_tail


def detection_rate(dose, halves=100):
    evidence = json.loads((Path(__file__).resolve().parents[1] / "tools/timing_original_evidence.json").read_text())
    noise = evidence["noise_residual_seconds"]
    detected = 0
    for seed in range(halves):
        rng = Random(seed + 971)
        gate = ActionTimingGate()
        for hand in range(350):
            group = rng.randrange(3)
            action = (0, 1, 3)[group]
            gap = .001 + rng.choice(noise) + (dose if group == 1 else 0)
            gate.add(hand, (hand % 4, action, False), gap, baseline_sd=.00005)
            gate.complete(hand + 1)
        detected += gate.evaluate() is not None
    return detected / halves


@pytest.mark.parametrize("dose", [0, .001, .003, .010, .030])
def test_measured_noise_dose_response(dose, record_property):
    rate = detection_rate(dose)
    record_property(f"detection_rate_{dose * 1000:g}_ms", rate)
    if dose == 0:
        assert rate <= .05
    elif dose >= .010:
        assert rate >= .90


def test_action_gate_needs_two_groups_and_counts_each_hand_once():
    gate = ActionTimingGate()
    for hand in range(350):
        for _ in range(5):
            gate.add(hand, (0, 1, False), .010, baseline_sd=.00005)
        gate.complete(hand + 1)
        gate.complete(hand + 1)
    assert gate.samples == 350
    assert gate.evaluate() is None


def test_fixed_look_alpha_budget_and_independent_confirmation():
    assert 4 * sum(CONFIG["alpha_spending"]) <= .05
    gate = ActionTimingGate()
    gate.groups = {"call": [[150, 12], [150, 12]], "raise": [[100, 2], [100, 2]]}
    gate.samples = 500
    assert gate.evaluate(alpha=.002) is None
    result = gate.evaluate(alpha=.01)
    assert result is not None and result["combined_p"] < .01
    gate.groups["raise"][1][1] = 15  # opposite direction in confirmation
    assert gate.evaluate(alpha=.01) is None


@pytest.mark.parametrize("a,n1,c,n2", [(2, 5, 0, 5), (3, 8, 2, 7), (0, 5, 0, 5)])
def test_hypergeometric_tail_matches_exact_small_tables(a, n1, c, n2):
    k = a + c
    expected = sum(comb(n1, i) * comb(n2, k - i) / comb(n1 + n2, k)
                   for i in range(a, min(n1, k) + 1) if 0 <= k - i <= n2)
    assert upper_tail(a, n1, c, n2) == pytest.approx(expected)


def test_large_repeatable_work_pattern_is_detected_without_claiming_strength():
    gate = ActionTimingGate()
    for hand in range(600):
        # A real latency component need not be strongly associated with an
        # action class. It cannot license a private-strength bluff inference.
        gate.add(hand, (hand % 4, (0, 1, 3)[hand % 3], False),
                 .001 + (.040 if hand % 5 == 0 else 0), baseline_sd=.00005)
        gate.complete(hand + 1)
    result = gate.evaluate()
    assert result is not None and result["kind"] == "latency_structure"
    assert result["strength_inference"] is False


def test_location_updates_use_a_public_fixed_cadence(monkeypatch):
    from bot import timing_gate
    original = timing_gate.median
    calls = []
    def measured(values):
        calls.append(1)
        return original(values)
    monkeypatch.setattr(timing_gate, "median", measured)
    gate = ActionTimingGate()
    for hand in range(100):
        gate.add(hand, (0, 1, False), .001, baseline_sd=.00005)
        gate.complete(hand + 1)
    assert len(calls) < 50
