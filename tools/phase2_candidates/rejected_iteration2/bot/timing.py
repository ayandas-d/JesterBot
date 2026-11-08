"""Passive timing only. Request gaps are noisy proxies, never clock access
to the opponent. Separate contexts and held-out confirmation are mandatory.
"""

from collections import defaultdict, deque
from math import sqrt
from statistics import median
import json
import os
import sys

from bot.timing_gate import ActionTimingGate

TIMING_NUDGES = False  # Strength nudges need measured value; diagnostic gates do not imply it.

# Active Task 5 implementation. The older Timing class below remains solely
# for the archived strategy's tests; the live adapter imports PhasedTiming.
CONFIG = {
    "cautious_start": 300,
    "endgame_start": 700,
    "baseline_window": 128,
    "minimum_baselines": 8,
    "minimum_labels": 30,
    "minimum_group_split": 5,
    "minimum_mean_difference": 0.001,
    "minimum_signal_se": 4.5,
    "prediction_radius_floor": 0.0005,
    "prediction_sd_radius": 3.0,
    "maximum_gap": 1.0,
    "bluff_nudge": 0.10,
    "bank_threshold": 6.5,
    "minimum_bank_samples": 30,
    "endgame_detector_k": 8,
    "weak_category_max": 2,
    "medium_category_max": 4,
    "bank_request_grace": .001,
    "minimum_bank_coverage": .70,
}


class Moments:
    """Constant-space moments; timing uses no draws from the strategy RNG."""
    def __init__(self):
        self.n = 0
        self.mean = 0.0
        self.m2 = 0.0

    def add(self, value):
        self.n += 1
        delta = value - self.mean
        self.mean += delta / self.n
        self.m2 += delta * (value - self.mean)

    @property
    def variance(self):
        return self.m2 / max(1, self.n - 1)


class PhasedTiming:
    """Passive request-gap measurement with injected monotonic timestamps.

The opponent model supplies counts, including inferred terminal responses.
One showdown label per hand avoids treating repeated decisions as independent
evidence. Gate failure is permanent and disables *all* timing effects.
"""
    def __init__(self, settings=None, enabled=True):
        self.settings = {**CONFIG, **(settings or {})}
        self.enabled = enabled
        self.last = None
        self.current = None
        self.current_hand = None
        self.callback_seconds = 0.0
        self.baselines = {cross: deque(maxlen=self.settings["baseline_window"]) for cross in (False, True)}
        self.overhead = {False: 0.0, True: 0.0}
        self.clean_counts = {False: 0, True: 0}
        self.clean_sums = {False: 0.0, True: 0.0}
        self.opponent_actions = 0
        self.gap_counts = {"baseline": 0, "clean": 0, "multiple": 0, "discarded": 0}
        self.pending = None
        self.labelled_hands = set()
        self.groups = {}
        self.context_counts = {}
        self.candidates = {}
        self.models = {}
        self.action_gate = ActionTimingGate()
        self.signal_kind = None
        self.fit_statistics = {}
        self.last_gate_review = -1
        self.gate_looks_used = set()
        self.baseline_moments = {cross: Moments() for cross in (False, True)}
        self.free_allowance = {cross: Moments() for cross in (False, True)}
        self.bank_charged_sum = 0.0
        self.bank_covered_actions = 0
        self.bank_direct_actions = 0
        self.bank_borrowed_actions = 0
        self.unpriced_gaps = deque(maxlen=4096)
        self.bank_dropped_actions = 0
        self.checkpoints = {}
        self.nudge_records = deque(maxlen=16384)
        self.k_changes = deque(maxlen=128)
        self.last_detector_k = None
        self.diagnostics_enabled = os.environ.get("JESTER_DIAG") == "1"
        self._finalizing = False
        self.gate = "pending"
        self.gate_reason = "learning"
        self.gate_hand = None
        self.nudged_decisions = 0
        self.lowered_k_decisions = 0

    def phase(self, hand):
        if hand < self.settings["cautious_start"]:
            return "learn"
        return "cautious" if hand < self.settings["endgame_start"] else "endgame"

    @staticmethod
    def _actions(model):
        return model.whole.events["actions"] + (model.current.stats.events["actions"] if model.current else 0)

    def finish(self, obs, model, now):
        if not self.enabled:
            return
        hand = model.current
        history = tuple(hand.history) if hand and hand.index == obs.hand_index else obs.action_history
        self.last = (obs.hand_index, history, self._actions(model), now)
        self.callback_seconds = 0.0

    def observe(self, obs, model, now):
        self.current = None
        self.current_hand = None
        if not self.enabled:
            return
        self.opponent_actions = self._actions(model)
        if self.last is not None:
            old_index, prefix, old_count, replied = self.last
            cross = obs.hand_index != old_index
            gap = now - replied - self.callback_seconds
            count = self.opponent_actions - old_count
            completed = []
            valid = obs.hand_index >= old_index and 0 <= gap <= self.settings["maximum_gap"] and count >= 0
            if cross:
                # Every intervening result is needed to distinguish a clean
                # terminal response from several hands' opponent actions.
                for hand in reversed(model.recent):
                    if hand.index < old_index:
                        break
                    completed.append(hand)
                completed.reverse()
                valid = valid and [h.index for h in completed] == list(range(old_index, obs.hand_index))
                valid = valid and bool(completed) and tuple(completed[0].history[:len(prefix)]) == prefix
            else:
                valid = valid and obs.action_history[:len(prefix)] == prefix
            if not valid:
                self.gap_counts["discarded"] += 1
            elif count == 0 and self._finalizing:
                # /hand-end has a different payload/route from /act; never
                # contaminate request-overhead baselines with the final flush.
                self.gap_counts["discarded"] += 1
            elif count == 0:
                self.baselines[cross].append(gap)
                self.overhead[cross] = median(self.baselines[cross])
                self.baseline_moments[cross].add(gap)
                self.gap_counts["baseline"] += 1
            elif count == 1:
                self.clean_counts[cross] += 1
                self.clean_sums[cross] += gap
                self.gap_counts["clean"] += 1
                # Locate the unique new action, possibly in a just-ended hand.
                source = model.current
                action = next((a for a in reversed(source.history) if not a.is_me), None) if source else None
                if action is None:
                    for hand in reversed(completed):
                        action = next((a for a in reversed(hand.history) if not a.is_me), None)
                        if action is not None:
                            source = hand
                            break
                if action is not None:
                    context = (int(action.street), int(action.action), cross)
                    self.current = (context, gap)
                    self.current_hand = source.index
                    self.action_gate.add(source.index, context, gap,
                                         sqrt(self.baseline_moments[cross].variance))
                    if source.showdown is not None:
                        self._label(source.index, context, gap, source.showdown["category"])
                    elif source is model.current:
                        self.pending = (source.index, context, gap)
            else:
                self.gap_counts["multiple"] += 1
            self._price_pending()
            if valid and count > 0 and not self._price_gap(cross, gap, count):
                if len(self.unpriced_gaps) == self.unpriced_gaps.maxlen:
                    self.bank_dropped_actions += self.unpriced_gaps[0][2]
                self.unpriced_gaps.append((cross, gap, count))
        # Standalone callers may omit results; never label a stale sample as
        # belonging to a newer hand, and do not grow an unbounded pending map.
        if self.pending is not None and self.pending[0] < obs.hand_index:
            self.pending = None
        self.action_gate.complete(obs.hand_index)
        self._gate(obs.hand_index)

    def _price_gap(self, cross, gap, count):
        direct = len(self.baselines[cross]) >= self.settings["minimum_baselines"]
        borrowed = not direct and len(self.baselines[not cross]) >= self.settings["minimum_baselines"]
        if not (direct or borrowed):
            return False
        # The clock is charged per request, with explicit same-half borrowed
        # calibration when a boundary class has no zero-action opportunities.
        baseline = self.overhead[cross] if self.baselines[cross] else self.overhead[not cross]
        wall = max(0.0, gap - baseline)
        grace = self.settings["bank_request_grace"]
        if count == 1:
            charge = max(0.0, wall - grace)
            self.free_allowance[cross].add(max(0.0, grace - wall))
        else:
            allowance = self.free_allowance[cross] if self.free_allowance[cross].n else self.free_allowance[not cross]
            charge = max(0.0, wall - count * grace + count * allowance.mean)
        self.bank_charged_sum += charge
        self.bank_covered_actions += count
        self.bank_direct_actions += count if direct else 0
        self.bank_borrowed_actions += count if borrowed else 0
        return True

    def _price_pending(self):
        if self.unpriced_gaps and any(len(v) >= self.settings["minimum_baselines"] for v in self.baselines.values()):
            for _ in range(len(self.unpriced_gaps)):
                cross, gap, count = self.unpriced_gaps.popleft()
                if not self._price_gap(cross, gap, count):
                    self.unpriced_gaps.append((cross, gap, count))

    def end(self, hand):
        if not self.enabled or self.pending is None or self.pending[0] != hand.index:
            return
        index, context, gap = self.pending
        self.pending = None
        if hand.showdown is not None:
            self._label(index, context, gap, hand.showdown["category"])

    def _label(self, hand, context, gap, category):
        if hand in self.labelled_hands:
            return
        self.labelled_hands.add(hand)
        group = ("weak" if category <= self.settings["weak_category_max"] else
                 "medium" if category <= self.settings["medium_category_max"] else "strong")
        groups = self.groups.setdefault(context, {})
        pair = groups.setdefault(group, (Moments(), Moments()))
        # Alternating unique samples in this context form disjoint groups.
        # Each strength group gets its own balanced split, without RNG use.
        pair[(pair[0].n + pair[1].n) % 2].add(gap)
        self.context_counts[context] = self.context_counts.get(context, 0) + 1

    def _fit(self, groups):
        cfg = self.settings
        usable = {name: pair for name, pair in groups.items()
                  if min(part.n for part in pair) >= cfg["minimum_group_split"]}
        names = tuple(usable)
        passed = False
        self._last_fit_statistic = 0.0
        for i, left in enumerate(names):
            for right in names[i + 1:]:
                differences, statistics = [], []
                for a, b in zip(usable[left], usable[right]):
                    difference = a.mean - b.mean
                    se = sqrt(a.variance / a.n + b.variance / b.n)
                    differences.append(difference)
                    statistics.append(abs(difference) / max(se, 1e-12))
                self._last_fit_statistic = max(self._last_fit_statistic, min(statistics))
                if (min(abs(v) for v in differences) >= cfg["minimum_mean_difference"]
                        and min(statistics) >= cfg["minimum_signal_se"]
                        and differences[0] * differences[1] > 0):
                    passed = True
        if not passed:
            return None
        return {name: ((a.mean + b.mean) / 2,
                       max(cfg["prediction_radius_floor"], cfg["prediction_sd_radius"] * sqrt(max(a.variance, b.variance))))
                for name, (a, b) in usable.items()}

    def _gate(self, hand):
        if self.gate != "pending" or self.phase(hand) == "learn":
            return
        start, stop = self.settings["cautious_start"], self.settings["endgame_start"]
        looks = (start, (start + stop) // 2, stop - 1)
        available = [i for i, boundary in enumerate(looks) if hand >= boundary and i not in self.gate_looks_used]
        if not available:
            if self.phase(hand) == "endgame":
                self.gate, self.gate_reason, self.gate_hand = "closed", "statistic below threshold or insufficient samples", hand
            return
        look = max(available)
        self.gate_looks_used.update(range(look + 1))
        self.last_gate_review = hand
        eligible = [context for context, n in self.context_counts.items()
                    if n >= self.settings["minimum_labels"]
                    and len(self.baselines[context[2]]) >= self.settings["minimum_baselines"]]
        for context in eligible:
            fitted = self._fit(self.groups[context])
            self.fit_statistics[context] = self._last_fit_statistic
            if fitted:
                self.candidates[context] = fitted
            else:
                self.candidates.pop(context, None)
        self.models = {c: self.candidates[c] for c in eligible if c in self.candidates}
        action_fit = self.action_gate.evaluate(self.action_gate.settings["alpha_spending"][look]) if any(
            len(v) >= self.settings["minimum_baselines"] for v in self.baselines.values()) else None
        if self.models or action_fit:
            self.gate = "open"
            self.signal_kind = "showdown_strength" if self.models else action_fit["kind"]
            self.gate_reason = "confirmed group difference" if self.models else action_fit["reason"]
            self.gate_hand = hand
        elif self.phase(hand) == "endgame":
            reason = "statistic below threshold" if eligible else "not enough labelled samples or baselines"
            self.gate, self.gate_reason, self.gate_hand = "closed", reason, hand
        else:
            self.gate_reason = "collecting independent evidence; no timing effect"

    def bluff_multiplier(self, hand):
        if (not self.settings.get("nudges", TIMING_NUDGES) or not self.enabled
                or self.phase(hand) == "learn" or self.gate != "open"
                or self.current is None or self.current_hand != hand):
            return 1.0
        context, gap = self.current
        fitted = self.models.get(context, {})
        matches = [name for name, (mean, radius) in fitted.items() if abs(gap - mean) <= radius]
        # Overlapping weak/strong timing clusters (e.g. only medium hands are
        # slow) do not identify weakness and must not increase bluffing.
        if len(matches) != 1 or matches[0] == "medium":
            return 1.0
        return 1 + self.settings["bluff_nudge"] * (1 if matches[0] == "weak" else -1)

    def record_nudge(self, obs, strength, gear, parameters, baseline_boost, multiplier):
        """Count changed distributions, not merely queries of a timing hint."""
        if multiplier == 1:
            return
        from bot.policy import action_probabilities
        plain = action_probabilities(obs, strength, gear, parameters, baseline_boost)
        nudged = action_probabilities(obs, strength, gear, parameters, baseline_boost * multiplier)
        if any(abs(plain[a] - nudged[a]) > 1e-12 for a in plain):
            self.nudged_decisions += 1
            self.nudge_records.append({"hand": obs.hand_index, "multiplier": multiplier})

    @property
    def bank_samples(self):
        return sum(n for cross, n in self.clean_counts.items()
                   if len(self.baselines[cross]) >= self.settings["minimum_baselines"])

    @property
    def bank_estimate(self):
        return (self.bank_charged_sum * self.opponent_actions / self.bank_covered_actions
                if self.bank_covered_actions else 0.0)

    @property
    def bank_coverage(self):
        return self.bank_covered_actions / max(1, self.opponent_actions)

    @property
    def bank_direct_coverage(self):
        return self.bank_direct_actions / max(1, self.opponent_actions)

    def detector_k(self, hand, normal_k):
        if (self.enabled and self.phase(hand) == "endgame" and self.gate == "open"
                and self.bank_samples >= self.settings["minimum_bank_samples"]
                and self.bank_direct_coverage >= self.settings["minimum_bank_coverage"]
                and not self.bank_dropped_actions
                and self.bank_estimate >= self.settings["bank_threshold"]):
            self.lowered_k_decisions += 1
            result = min(normal_k, self.settings["endgame_detector_k"])
            if self.last_detector_k != result:
                self.k_changes.append({"hand": hand, "k": result, "bank_estimate": self.bank_estimate})
            self.last_detector_k = result
            return result
        self.last_detector_k = normal_k
        return normal_k

    def checkpoint(self, hands, model):
        self.opponent_actions = self._actions(model)
        if hands in (300, 500, 700, 900, model.config.num_hands):
            self.checkpoints[hands] = {"hands": hands, "estimate": self.bank_estimate,
                                       "coverage": self.bank_coverage,
                                       "direct_context_coverage": self.bank_direct_coverage,
                                       "samples": self.bank_samples}

    def finalize(self, model, requested):
        """Close the final normal result-delivery gap without inventing a turn."""
        if self.last is None or not self.enabled:
            return
        from types import SimpleNamespace
        self._finalizing = True
        try:
            self.observe(SimpleNamespace(hand_index=model.last_finished + 1, action_history=()), model, requested)
        finally:
            self._finalizing = False
            self.last = None

    def diagnostics(self):
        overhead = {}
        for cross, moments in self.baseline_moments.items():
            window = sorted(self.baselines[cross])
            overhead[str(cross)] = {"samples": moments.n, "mean": moments.mean,
                                     "sd": sqrt(moments.variance),
                                     "p99_window": window[min(len(window) - 1, int(.99 * len(window)))] if window else None,
                                     "window_samples": len(window)}
        action = self.action_gate.last_test
        statistic = (max((self.fit_statistics.get(c, 0) for c in self.models), default=0)
                     if self.signal_kind == "showdown_strength" else action["statistic"])
        return {"overhead": overhead, "clean_samples": self.gap_counts["clean"],
                "showdown_labelled_clean_samples": len(self.labelled_hands),
                "action_labelled_hands": self.action_gate.samples,
                "large_latency_hand_parts": [v.copy() for v in self.action_gate.large_parts],
                "contexts": [{"context": c, "labels": n,
                               "groups": {g: [p.n for p in pair] for g, pair in self.groups[c].items()}}
                              for c, n in self.context_counts.items()],
                "gate": {"statistic": statistic,
                         "threshold": self.settings["minimum_signal_se"] if self.signal_kind == "showdown_strength" else action["threshold"],
                         "decision": self.gate, "reason": self.gate_reason,
                         "hand": self.gate_hand, "signal_kind": self.signal_kind,
                         "action_test": action},
                "nudged_decisions": self.nudged_decisions, "nudges": list(self.nudge_records),
                "bank_checkpoints": list(self.checkpoints.values()),
                "final_bank_estimate": self.bank_estimate, "bank_coverage": self.bank_coverage,
                "bank_direct_context_coverage": self.bank_direct_coverage,
                "bank_borrowed_actions": self.bank_borrowed_actions,
                "bank_unpriced_gaps": len(self.unpriced_gaps), "bank_dropped_actions": self.bank_dropped_actions,
                "k_changes": list(self.k_changes), "lowered_k_decisions": self.lowered_k_decisions}

    def emit_diagnostics(self):
        if self.diagnostics_enabled:
            try:
                print("JESTER_TIMING " + json.dumps(self.diagnostics()), file=sys.stderr, flush=True)
            except (OSError, ValueError):
                pass


def correlation(samples):
    n = len(samples)
    if n < 3:
        return 0.0
    mx = sum(x for x, _ in samples) / n
    my = sum(y for _, y in samples) / n
    xx = sum((x - mx) ** 2 for x, _ in samples)
    yy = sum((y - my) ** 2 for _, y in samples)
    return sum((x - mx) * (y - my) for x, y in samples) / sqrt(xx * yy) if xx * yy else 0.0


class Timing:
    def __init__(self, num_hands):
        self.num_hands = num_hands
        self.train = defaultdict(lambda: deque(maxlen=160))
        self.validation = defaultdict(lambda: deque(maxlen=100))
        self.last = None
        self.current = None
        self.observations = 0
        self.collapsed = False
        self.early_gaps = deque(maxlen=100)
        self.late_gaps = deque(maxlen=12)

    def observe(self, obs, now):
        self.current = None
        if self.last is None:
            return
        hand, street, history_len, own_action, finished = self.last
        # Cross-hand/street gaps include dealing, result callbacks and variable
        # numbers of opponent turns. Reject them rather than invent precision.
        if (hand != obs.hand_index or street != obs.street
                or len(obs.action_history) != history_len + 2):
            return
        reply = obs.action_history[-1]
        gap = now - finished
        if reply.is_me or not 0.00005 <= gap <= 0.1:
            return
        context = (int(street), int(own_action), int(reply.action))
        self.current = (context, gap, tuple(obs.board))
        self.observations += 1
        phase = obs.hand_index / max(1, self.num_hands)
        if phase < 0.35:
            self.early_gaps.append(gap)
        elif phase >= 0.7:
            self.late_gaps.append(gap)

    def finish(self, obs, action, now):
        self.last = (obs.hand_index, obs.street, len(obs.action_history), action, now)

    def learn(self, context, gap, strength, hand):
        phase = hand / max(1, self.num_hands)
        if phase < 0.35:
            self.train[context].append((gap, strength))
        elif phase < 0.65:
            self.validation[context].append((gap, strength))

    def adjustment(self, hand):
        if self.current is None or hand < 0.65 * self.num_hands:
            return 0.0
        context, gap, _ = self.current
        train, validation = self.train[context], self.validation[context]
        # Conservative correlation tests in BOTH independent temporal sets.
        # This is only a heuristic gate, not proof of a causal timing tell.
        if len(train) < 50 or len(validation) < 30:
            return 0.0
        r, rv = correlation(train), correlation(validation)
        if r * rv <= 0 or min(abs(r), abs(rv)) < 0.6:
            return 0.0
        if any(abs(c) * sqrt((len(s) - 2) / max(1e-9, 1 - c * c)) < 4.5
               for c, s in ((r, train), (rv, validation))):
            return 0.0
        mean = sum(x for x, _ in train) / len(train)
        sd = sqrt(sum((x - mean) ** 2 for x, _ in train) / len(train))
        if sd < 0.0003:
            return 0.0
        # Stronger predicted opponent -> lower our equity, at most two points.
        return max(-0.02, min(0.02, -0.01 * r * (gap - mean) / sd))

    def collapse_hint(self, hand, fold_streak):
        # Fast gaps cannot establish time-bank exhaustion. Behavior must first
        # confirm it; late timing only annotates the existing fold detector.
        self.collapsed = bool(
            hand >= 0.7 * self.num_hands and fold_streak >= 6
            and len(self.early_gaps) >= 30 and len(self.late_gaps) >= 8
            and median(self.early_gaps) > 0.002
            and median(self.late_gaps) < 0.4 * median(self.early_gaps))
        return self.collapsed
