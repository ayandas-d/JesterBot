"""Synthetic monotonic gap streams: no sleeps or opponent clock access."""

from dataclasses import replace
from random import Random
from statistics import median
from time import perf_counter_ns

import pytest

import agent
from bot import fallback
from bot.opponent import OpponentModel
from bot.policy import action_probabilities
from bot.timing import CONFIG, PhasedTiming
from evaluator import cards_from_str
from game import Action, AgentConfig, Game, HandResult, Street, make_deal


def cards(value):
    return tuple(cards_from_str(value))


SHOWDOWNS = {
    "weak": (cards("6d 6h 7d 7h 8s"), cards("Ac Kc Qc Jd Td")),
    "medium": (cards("Th 7s 7d 8c 9c"), cards("Ah Kh Qh Jh 6c")),
    "strong": (cards("Ah Kh 6d 7d 8s"), cards("Qh Jh Th 9c 6c")),
}


def observe(timing, model, obs, now):
    model.observe(obs, "MANIAC")
    timing.observe(obs, model, now)


def finish(timing, model, obs, action, now):
    model.record_action(obs, action)
    timing.finish(obs, model, now)


def baselines(timing, overhead=.0006, count=16):
    """Independent real request pairs: our closing call -> our first flop turn."""
    for i in range(count):
        model = OpponentModel(AgentConfig())
        game = Game(make_deal("zero-gap", i), 0, hand_index=i)
        game.apply(Action.RAISE_HALF)
        obs = game.observation(1)
        timing.last = None
        observe(timing, model, obs, float(i))
        finish(timing, model, obs, Action.CHECK_CALL, i + .002)
        game.apply(Action.CHECK_CALL)
        observe(timing, model, game.observation(1), i + .002 + overhead)
    timing.last = None


class Stream:
    """Legal request prefixes, followed by synthetic revealed HandResults.

    The showdown fixtures deliberately control category; we aren't attempting
    to simulate card-dependent opponent delay using the real clock.
    """
    def __init__(self, timing=None):
        self.timing = timing or PhasedTiming()
        self.model = OpponentModel(AgentConfig())
        self.now = 10.0

    def sample(self, index, strength, think, overhead=.0006, showdown=True):
        game = Game(make_deal("clean-gap", index), 0, hand_index=index)
        game.apply(Action.CHECK_CALL)  # opponent's small-blind limp
        obs = game.observation(1)
        observe(self.timing, self.model, obs, self.now)
        finish(self.timing, self.model, obs, Action.RAISE_HALF, self.now + .002)
        game.apply(Action.RAISE_HALF)
        game.apply(Action.CHECK_CALL)
        self.now += .002 + overhead + think
        obs = game.observation(1)  # one opponent call, then our first flop turn
        observe(self.timing, self.model, obs, self.now)
        current = self.timing.current
        finish(self.timing, self.model, obs, Action.CHECK_CALL, self.now + .002)
        hole, board = SHOWDOWNS[strength]
        result = HandResult(index, -2, 160, showdown, board, hole if showdown else None, "opp")
        self.model.end(result, "MANIAC")
        self.timing.end(self.model.recent[-1])
        self.now += .002 + overhead
        return current


def trained(kind="tell", samples=90):
    timing = PhasedTiming()
    baselines(timing)
    stream = Stream(timing)
    rng = Random(510)
    for i in range(samples):
        strength = ("weak", "medium", "strong")[i % 3]
        think = .001 + (0.003 if kind == "tell" and strength == "medium" else 0)
        think += rng.uniform(-.0001, .0001) if kind == "tell" else rng.uniform(0, .004)
        stream.sample(i, strength, think)
    return stream


def test_phase_boundaries_and_no_effect_before_300_even_with_an_open_model():
    timing = trained().timing
    assert [timing.phase(i) for i in (0, 299, 300, 699, 700, 999)] == [
        "learn", "learn", "cautious", "cautious", "endgame", "endgame"]
    timing._gate(299)
    assert timing.gate == "pending"
    timing._gate(300)
    assert timing.gate == "open"
    assert timing.bluff_multiplier(299) == 1
    assert timing.detector_k(299, 15) == 15


def test_learn_phase_actions_match_disabled_timing_on_same_seed(monkeypatch):
    monkeypatch.setenv("BOT_SEED", "task5-identical")
    # This tests action/RNG equivalence, with fixed sample counts and injected
    # request timestamps; runtime benchmarking is separate.
    monkeypatch.setattr(fallback, "equity", lambda *args, **kwargs: .5)
    outputs = []
    for enabled in (False, True):
        ticks = iter(i * .00001 for i in range(100_000))
        monkeypatch.setattr(agent, "monotonic", lambda: next(ticks))
        memory = {}
        agent.new_half(AgentConfig(), memory)
        state = memory["bot"]
        state.timing.enabled = enabled
        rng = Random(511)
        actions = []
        for index in range(300):
            game = Game(make_deal("learn-equivalence", index), index % 2, hand_index=index)
            while not game.is_terminal:
                obs = game.observation(game.to_act)
                if game.to_act == 0:
                    action = agent.choose_action(obs, memory)
                    actions.append(action)
                else:
                    action = rng.choice(obs.legal_actions)
                game.apply(action)
            agent.on_hand_end(game.hand_result(0), memory)
        assert memory["safety_errors"] == 0
        assert state.timing.nudged_decisions == state.timing.lowered_k_decisions == 0
        assert state.opponent.detector.k == 15
        outputs.append((actions, state.rng.getstate(), state.gear, state.opponent.whole.events))
    assert outputs[0] == outputs[1]


def test_noise_closes_gate_permanently_and_disables_all_effects():
    stream = trained("noise")
    timing = stream.timing
    stream.sample(300, "weak", .008)
    assert timing.gate == "pending" and timing.bluff_multiplier(300) == 1
    # Sequential qualification gathers more independent evidence; only the
    # final failed gate is permanent. Pure noise must remain non-actionable.
    rng = Random(516)
    for i in range(301, 701):
        stream.sample(i, ("weak", "medium", "strong")[i % 3], .001 + rng.uniform(0, .004))
    assert timing.gate == "closed" and timing.gate_hand == 700
    # Later perfect signals and an enormous estimated bank cannot reopen it.
    for i in range(701, 1000):
        stream.sample(i, "weak" if i % 2 else "strong", .008 if i % 2 else .012)
    assert timing.gate == "closed"
    assert timing.bluff_multiplier(999) == 1
    assert timing.detector_k(999, 15) == 15


def test_medium_hand_tell_opens_gate_in_phase_two_but_ambiguous_weakness_is_neutral():
    stream = trained()
    stream.sample(300, "medium", .004)
    timing = stream.timing
    assert timing.gate == "open" and timing.gate_hand == 300
    assert len(timing.labelled_hands) >= 30
    assert timing.bluff_multiplier(300) == 1  # medium isn't weakness
    stream.sample(301, "weak", .001)
    assert timing.bluff_multiplier(301) == 1  # strong and weak overlap here


def test_insufficient_showdowns_baselines_or_context_samples_cannot_enable_timing():
    for condition in ("few_labels", "no_showdowns", "no_baseline"):
        timing = PhasedTiming()
        if condition != "no_baseline":
            baselines(timing)
        stream = Stream(timing)
        count = 29 if condition == "few_labels" else 60
        for i in range(count):
            stream.sample(i, "weak" if i % 2 else "strong", .001 if i % 2 else .004,
                          showdown=condition != "no_showdowns")
        timing._gate(300)
        assert timing.gate == "pending"
        timing._gate(700)
        assert timing.gate == "closed"
        assert timing.detector_k(700, 15) == 15


def test_independent_confirmation_rejects_signal_with_reversed_validation():
    timing = PhasedTiming()
    baselines(timing)
    stream = Stream(timing)
    for i in range(80):
        strength = "weak" if i % 2 else "strong"
        # Each strength alternates between the two confirmation sets.
        fast = (i // 2) % 2 == 0
        think = .001 if (fast == (strength == "weak")) else .004
        stream.sample(i, strength, think)
    stream.sample(300, "weak", .001)
    timing._gate(700)
    assert timing.gate == "closed"


def test_overhead_baseline_and_own_processing_are_separate_from_opponent_gap():
    timing = PhasedTiming()
    baselines(timing, overhead=.0007)
    assert timing.overhead[False] == pytest.approx(.0007, abs=1e-10)
    assert timing.gap_counts["baseline"] == 16
    stream = Stream(timing)
    _, gap = stream.sample(20, "weak", .003, overhead=.0007)
    assert gap == pytest.approx(.0037)
    assert gap - timing.overhead[False] == pytest.approx(.003)
    # In the next gap, callback work is explicitly subtracted.
    timing.callback_seconds = .005
    stream.now += .005
    before = timing.clean_sums[True]
    stream.sample(21, "weak", .003, overhead=.0007)
    assert timing.clean_sums[True] - before == pytest.approx(.0007)


def test_cross_hand_terminal_fold_counts_as_one_action_and_not_baseline():
    timing, model = PhasedTiming(), OpponentModel(AgentConfig())
    game = Game(make_deal("terminal-gap", 0), 0, hand_index=0)
    obs = game.observation(0)
    observe(timing, model, obs, 1.0)
    finish(timing, model, obs, Action.RAISE_HALF, 1.002)
    game.apply(Action.RAISE_HALF)
    game.apply(Action.FOLD)
    model.end(game.hand_result(0), "MANIAC")
    timing.end(model.recent[-1])
    next_game = Game(make_deal("terminal-gap", 1), 0, hand_index=1)
    observe(timing, model, next_game.observation(0), 1.008)
    assert timing.gap_counts["clean"] == 1 and timing.gap_counts["baseline"] == 0
    assert timing.current == ((int(Street.PREFLOP), int(Action.FOLD), True), pytest.approx(.006))


def test_cross_hand_no_opponent_action_is_baseline_and_multiple_actions_are_not_clean():
    for extra in (False, True):
        timing, model = PhasedTiming(), OpponentModel(AgentConfig())
        game = Game(make_deal("boundary", 0), 0, hand_index=0)
        obs = game.observation(0)
        observe(timing, model, obs, 0)
        action = Action.RAISE_HALF if extra else Action.FOLD
        finish(timing, model, obs, action, .002)
        game.apply(action)
        if extra:
            game.apply(Action.FOLD)
        model.end(game.hand_result(0), "MANIAC")
        next_game = Game(make_deal("boundary", 1), 1 if extra else 0, hand_index=1)
        if extra:
            next_game.apply(Action.RAISE_HALF)
        observe(timing, model, next_game.observation(0), .008)
        assert timing.gap_counts["multiple" if extra else "baseline"] == 1
        assert timing.gap_counts["clean"] == 0
        if not extra:
            assert timing.overhead[True] == pytest.approx(.006)


def test_cross_hand_clean_showdown_labels_the_completed_hand_not_the_new_one():
    timing, model = PhasedTiming(), OpponentModel(AgentConfig())
    game = Game(make_deal("river-terminal", 0), 0, hand_index=0)
    while not (game.street == Street.RIVER and game.to_act == 0):
        game.apply(Action.CHECK_CALL)
    obs = game.observation(0)
    observe(timing, model, obs, 1.0)
    finish(timing, model, obs, Action.RAISE_HALF, 1.002)
    game.apply(Action.RAISE_HALF)
    game.apply(Action.CHECK_CALL)
    assert game.is_terminal
    model.end(game.hand_result(0), "MANIAC")
    timing.end(model.recent[-1])
    assert not timing.labelled_hands  # gap hasn't been measured yet
    next_game = Game(make_deal("river-terminal", 1), 0, hand_index=1)
    observe(timing, model, next_game.observation(0), 1.008)
    assert timing.labelled_hands == {0}
    assert timing.context_counts[(int(Street.RIVER), int(Action.CHECK_CALL), True)] == 1
    assert timing.pending is None


def test_invalid_clock_history_and_missing_results_discard_gaps():
    for bad in ("clock", "history", "missing_result"):
        timing, model = PhasedTiming(), OpponentModel(AgentConfig())
        game = Game(make_deal("invalid", 0), 0)
        obs = game.observation(0)
        observe(timing, model, obs, 0)
        finish(timing, model, obs, Action.RAISE_HALF, .002)
        game.apply(Action.RAISE_POT if bad == "history" else Action.RAISE_HALF)
        game.apply(Action.RAISE_POT)
        next_obs = game.observation(0)
        if bad == "missing_result":
            next_obs = replace(next_obs, hand_index=2)
        observe(timing, model, next_obs, .001 if bad == "clock" else .008)
        assert timing.gap_counts["discarded"] == 1
        assert timing.gap_counts["clean"] == timing.gap_counts["baseline"] == 0


def test_heavy_thinker_extrapolation_crosses_threshold_and_only_endgame_lowers_k(monkeypatch):
    timing = PhasedTiming()
    baselines(timing)
    timing.baselines[True].extend([.0006] * 16)
    timing.overhead[True] = .0006
    stream = Stream(timing)
    for i in range(701):
        if i:
            stream.now += .008 if i % 2 else .011
        stream.sample(i, "weak" if i % 2 else "strong", .008 if i % 2 else .011)
    assert timing.gate == "open"
    assert timing.bank_samples == 1401
    # The judge charges each request after its first free millisecond. The
    # first opponent action is unobserved; allow that small sampling error.
    assert timing.bank_estimate == pytest.approx((.007 * 350 + .010 * 351) * 2, abs=.002)
    assert timing.bank_coverage > .99
    assert timing.bank_estimate > 6.5
    assert timing.detector_k(699, 15) == 15
    assert timing.detector_k(700, 15) == 8
    detector = stream.model.detector
    detector.streak = 8
    assert not detector.active
    detector.k = timing.detector_k(700, 15)
    assert detector.active
    detector.observe(game_call())
    assert not detector.active
    memory = {}
    agent.new_half(AgentConfig(), memory)
    memory["bot"].timing = timing
    memory["bot"].opponent = stream.model
    detector.k, detector.streak = 15, 8
    monkeypatch.setattr(agent, "monotonic", lambda: stream.now)
    next_game = Game(make_deal("live-bank", 701), 0, hand_index=701)
    assert agent.choose_action(next_game.observation(0), memory) == Action.RAISE_HALF
    assert detector.k == 8 and memory["safety_errors"] == 0


def game_call():
    game = Game(make_deal("paid-call", 0), 0)
    game.apply(Action.CHECK_CALL)
    return game.observation(1).action_history[-1]


def test_nudges_are_bounded_and_cannot_override_price_floors(monkeypatch):
    timing = PhasedTiming(settings={"nudges": True})
    baselines(timing)
    stream = Stream(timing)
    for i in range(80):
        stream.sample(i, "weak" if i % 2 else "strong", .001 if i % 2 else .004)
    stream.sample(300, "weak", .001)
    assert timing.bluff_multiplier(300) == pytest.approx(1.1)
    stream.sample(301, "strong", .004)
    assert timing.bluff_multiplier(301) == pytest.approx(.9)
    state = fallback.State(AgentConfig())
    state.timing = timing
    captured = []
    def sample(obs, strength, gear, rng, params, bluff_multiplier):
        captured.append(bluff_multiplier)
        return Action.CHECK_CALL
    monkeypatch.setattr(fallback, "sample_action", sample)
    obs = replace(Game(make_deal("nudge", 0), 0).observation(0), hand_index=301)
    fallback.policy(obs, state)
    assert captured == [pytest.approx(.9)]
    for gear in ("MANIAC", "AGGRO", "VALUE", "TRAP"):
        assert action_probabilities(obs, 0, gear, bluff_multiplier=1.1)[Action.FOLD] == 1


def test_one_label_per_hand_and_half_reset_clear_all_timing_state():
    stream = trained()
    timing = stream.timing
    n = len(timing.labelled_hands)
    timing.end(stream.model.recent[-1])
    timing._label(stream.model.recent[-1].index, (0, 1, False), .1, 8)
    assert len(timing.labelled_hands) == n
    memory = {}
    agent.new_half(AgentConfig(), memory)
    memory["bot"].timing = timing
    memory["bot"].opponent.detector.k = 8
    agent.new_half(AgentConfig(), memory)
    fresh = memory["bot"].timing
    assert fresh is not timing and fresh.gate == "pending"
    assert fresh.last is fresh.pending is fresh.current is None
    assert not fresh.labelled_hands and not fresh.groups and not fresh.models
    assert fresh.bank_estimate == fresh.bank_samples == 0
    assert fresh.nudged_decisions == fresh.lowered_k_decisions == 0
    assert memory["bot"].opponent.detector.k == 15


def test_module_overhead_below_50_microseconds_per_decision(record_property):
    timing, model = PhasedTiming(), OpponentModel(AgentConfig())
    game = Game(make_deal("overhead", 0), 0)
    game.apply(Action.RAISE_HALF)
    obs = game.observation(1)
    model.observe(obs, "MANIAC")
    model.record_action(obs, Action.CHECK_CALL)
    game.apply(Action.CHECK_CALL)
    next_obs = game.observation(1)
    model.observe(next_obs, "MANIAC")
    durations = []
    for i in range(10_000):
        # Same-hand zero-opponent pairs exercise median baseline maintenance.
        start = perf_counter_ns()
        timing.finish(next_obs, model, i * .01)
        timing.observe(next_obs, model, i * .01 + .0006)
        timing.bluff_multiplier(299)
        timing.detector_k(299, 15)
        durations.append((perf_counter_ns() - start) / 1000)
    p99 = sorted(durations)[int(len(durations) * .99)]
    record_property("timing_p50_us", median(durations))
    record_property("timing_p99_us", p99)
    assert median(durations) < 50 and p99 < 50


def test_clean_label_and_gate_paths_also_fit_module_overhead_target(record_property):
    from tools.profile_timing import MeasuredTiming
    timing = MeasuredTiming()
    baselines(timing)
    timing.baselines[True].extend([.0006] * 16)
    timing.overhead[True] = .0006
    stream = Stream(timing)
    costs = []
    for i in range(800):
        before = timing.total
        if i:
            stream.now += .008 if i % 2 else .011
        stream.sample(i, "weak" if i % 2 else "strong", .008 if i % 2 else .011)
        timing.bluff_multiplier(i)
        timing.detector_k(i, 15)
        # Includes two decisions and the label callback: conservatively charge
        # the entire pair's timing work to one decision.
        costs.append((timing.total - before) * 1e6)
    p99 = sorted(costs)[int(len(costs) * .99)]
    record_property("timing_clean_and_label_p99_us", p99)
    assert median(costs) < 50 and p99 < 50
    assert timing.gate == "open" and timing.lowered_k_decisions > 0
