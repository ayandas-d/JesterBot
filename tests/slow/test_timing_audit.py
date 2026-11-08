"""Opt-in live controls; fast-tier synthetic tests never sleep or use sockets."""

import json
import pytest

from tools.timing_controls import compare_fake, run_control


@pytest.mark.slow
def test_live_positive_timing_control():
    run_control("positive", label="pytest-timing-positive")


@pytest.mark.slow
def test_live_negative_timing_controls():
    run_control("negative", label="pytest-timing-negative")


@pytest.mark.slow
def test_live_hand_700_time_bank_accuracy():
    run_control("known", label="pytest-timing-bank")


@pytest.mark.slow
def test_live_forced_fake_tell_is_bounded_against_disabled_timing():
    active, _ = run_control("fake", label="pytest-timing-fake")
    disabled, _ = run_control("fake-disabled", label="pytest-timing-fake-disabled")
    compare_fake(json.loads(active.read_text()), json.loads(disabled.read_text()))
