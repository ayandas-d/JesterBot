"""Behavioral evidence for configurable re-raise thresholds, including rejected settings."""

import pytest

from bot.gears import CONFIG, GearSelector
from bot.opponent import Stats


@pytest.mark.parametrize("threshold,expected", [(0.30, "TRAP"), (0.35, "VALUE")])
@pytest.mark.parametrize("windows", [((47, 147, 314), (36, 111, 228)),
                                     ((47, 156, 117.5), (37, 123, 217))])
def test_logged_moderate_reraises_preserve_value_with_higher_threshold(threshold, expected, windows):
    # Actual rolling evidence at hands 125/150 in the v1 slow_tell seed-1 logs.
    selector = GearSelector({**CONFIG, "reraise_rate": threshold})
    gear = "VALUE"
    for hands, (reraises, opportunities, net) in zip((125, 150), windows):
        stats = Stats()
        stats.events.update(faced_raises=opportunities, reraises=reraises)
        stats.actions_by_gear["VALUE"] = opportunities
        stats.net_bb_by_gear["VALUE"] = net
        gear = selector.evaluate(hands, stats, gear)
        if hands == 125:
            assert gear == "VALUE"  # one window cannot bypass confirmation
    assert gear == expected


@pytest.mark.parametrize("threshold", [0.30, 0.35])
def test_high_reraises_still_trigger_trap_with_both_thresholds(threshold):
    selector = GearSelector({**CONFIG, "reraise_rate": threshold})
    stats = Stats()
    stats.events.update(faced_raises=100, reraises=65)
    stats.net_bb_by_gear["VALUE"] = 100
    assert selector.evaluate(125, stats, "VALUE") == "VALUE"
    assert selector.evaluate(150, stats, "VALUE") == "TRAP"
