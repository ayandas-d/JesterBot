"""Regression cases go here BEFORE fixing bugs found by the improvement loop.

No strategy bug fixes are part of the one-time infrastructure setup.
"""


def test_previous_hand_timing_cannot_nudge_a_new_hand():
    """A correctly labelled terminal gap is still not a tell about the next deal."""
    from bot.opponent import OpponentModel
    from bot.timing import PhasedTiming
    from game import Action, AgentConfig, Game, Street, make_deal

    timing, model = PhasedTiming(settings={"nudges": True}), OpponentModel(AgentConfig())
    game = Game(make_deal("timing-leak-regression", 699), 0, hand_index=699)
    while not (game.street == Street.RIVER and game.to_act == 0):
        game.apply(Action.CHECK_CALL)
    obs = game.observation(0)
    model.observe(obs, "MANIAC")
    model.record_action(obs, Action.RAISE_HALF)
    timing.finish(obs, model, 1.002)
    game.apply(Action.RAISE_HALF)
    game.apply(Action.CHECK_CALL)
    model.end(game.hand_result(0), "MANIAC")
    timing.end(model.recent[-1])
    next_game = Game(make_deal("timing-leak-regression", 700), 0, hand_index=700)
    next_obs = next_game.observation(0)
    model.observe(next_obs, "MANIAC")
    timing.observe(next_obs, model, 1.008)
    context, gap = timing.current
    timing.gate = "open"
    timing.models = {context: {"weak": (gap, .0001), "strong": (gap + .01, .0001)}}
    assert timing.bluff_multiplier(700) == 1.0


def test_late_baseline_does_not_erase_earlier_think_time():
    import pytest
    from bot.timing import PhasedTiming
    from tests.test_timing import Stream

    timing = PhasedTiming()
    stream = Stream(timing)
    for hand in range(700):
        if hand == 600:
            # Zero-opponent calibration opportunities may arrive much later
            # than the expensive requests. Their information must also price
            # the retained earlier gaps, not only future cheap requests.
            for cross in (False, True):
                timing.baselines[cross].extend([.0006] * 16)
                timing.overhead[cross] = .0006
        think = .003 if hand < 350 else .0015
        if hand:
            stream.now += think
        stream.sample(hand, "weak", think)
    assert timing.bank_estimate == pytest.approx(350 * 2 * .002 + 350 * 2 * .0005, abs=.002)
