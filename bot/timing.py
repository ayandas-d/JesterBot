"""Passive timing only. Request gaps are noisy proxies, never clock access
to the opponent. Separate contexts and held-out confirmation are mandatory.
"""

from collections import defaultdict, deque
from math import sqrt
from statistics import median

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
            elif count == 0:
                self.baselines[cross].append(gap)
                self.overhead[cross] = median(self.baselines[cross])
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
                    if source.showdown is not None:
                        self._label(source.index, context, gap, source.showdown["category"])
                    elif source is model.current:
                        self.pending = (source.index, context, gap)
            else:
                self.gap_counts["multiple"] += 1
        # Standalone callers may omit results; never label a stale sample as
        # belonging to a newer hand, and do not grow an unbounded pending map.
        if self.pending is not None and self.pending[0] < obs.hand_index:
            self.pending = None
        self._gate(obs.hand_index)

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
        if self.gate == "pending" and self.context_counts[context] >= self.settings["minimum_labels"]:
            fitted = self._fit(groups)
            if fitted:
                self.candidates[context] = fitted
            else:
                self.candidates.pop(context, None)

    def _fit(self, groups):
        cfg = self.settings
        usable = {name: pair for name, pair in groups.items()
                  if min(part.n for part in pair) >= cfg["minimum_group_split"]}
        names = tuple(usable)
        passed = False
        for i, left in enumerate(names):
            for right in names[i + 1:]:
                differences = []
                for a, b in zip(usable[left], usable[right]):
                    difference = a.mean - b.mean
                    se = sqrt(a.variance / a.n + b.variance / b.n)
                    if (abs(difference) < cfg["minimum_mean_difference"]
                            or abs(difference) < cfg["minimum_signal_se"] * max(se, 1e-12)):
                        break
                    differences.append(difference)
                if len(differences) == 2 and differences[0] * differences[1] > 0:
                    passed = True
        if not passed:
            return None
        return {name: ((a.mean + b.mean) / 2,
                       max(cfg["prediction_radius_floor"], cfg["prediction_sd_radius"] * sqrt(max(a.variance, b.variance))))
                for name, (a, b) in usable.items()}

    def _gate(self, hand):
        if self.gate != "pending" or self.phase(hand) == "learn":
            return
        eligible = [context for context, n in self.context_counts.items()
                    if n >= self.settings["minimum_labels"]
                    and len(self.baselines[context[2]]) >= self.settings["minimum_baselines"]]
        if eligible:
            self.models = {c: self.candidates[c] for c in eligible if c in self.candidates}
            self.gate = "open" if self.models else "closed"
            self.gate_reason = "confirmed group difference" if self.models else "no confirmed signal"
            self.gate_hand = hand
        elif self.phase(hand) == "endgame":
            self.gate, self.gate_reason, self.gate_hand = "closed", "insufficient labelled or baseline samples", hand

    def bluff_multiplier(self, hand):
        if not self.enabled or self.phase(hand) == "learn" or self.gate != "open" or self.current is None:
            return 1.0
        context, gap = self.current
        fitted = self.models.get(context, {})
        matches = [name for name, (mean, radius) in fitted.items() if abs(gap - mean) <= radius]
        # Overlapping weak/strong timing clusters (e.g. only medium hands are
        # slow) do not identify weakness and must not increase bluffing.
        if len(matches) != 1 or matches[0] == "medium":
            return 1.0
        self.nudged_decisions += 1
        return 1 + self.settings["bluff_nudge"] * (1 if matches[0] == "weak" else -1)

    @property
    def bank_samples(self):
        return sum(n for cross, n in self.clean_counts.items()
                   if len(self.baselines[cross]) >= self.settings["minimum_baselines"])

    @property
    def bank_estimate(self):
        # Subtract overhead before extrapolating the clean mean to all known
        # opponent actions. This is an estimate, not access to their clock.
        usable = [cross for cross in (False, True)
                  if len(self.baselines[cross]) >= self.settings["minimum_baselines"]]
        count = sum(self.clean_counts[cross] for cross in usable)
        net = sum(max(0.0, self.clean_sums[cross] - self.clean_counts[cross] * self.overhead[cross]) for cross in usable)
        return net * self.opponent_actions / count if count else 0.0

    def detector_k(self, hand, normal_k):
        if (self.enabled and self.phase(hand) == "endgame" and self.gate == "open"
                and self.bank_samples >= self.settings["minimum_bank_samples"]
                and self.bank_estimate >= self.settings["bank_threshold"]):
            self.lowered_k_decisions += 1
            return min(normal_k, self.settings["endgame_detector_k"])
        return normal_k


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
