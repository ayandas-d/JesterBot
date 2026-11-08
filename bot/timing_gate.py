"""Passive action/latency association, not a private-hand-strength oracle.

One observation per completed hand, public-street normalization, and disjoint
confirmation splits avoid pretending every correlated action is independent.
This gate can confirm a timing pattern without licensing a strength nudge.
"""

from collections import deque
from itertools import combinations
from math import exp, lgamma, log, log10
from statistics import median


CONFIG = {"window": 64, "location_refresh": 8, "minimum_samples": 30, "minimum_split": 5,
          "minimum_tail": .001, "noise_multiple": 8.0,
          "split_p": .10, "alpha_spending": (.001, .003, .008), "minimum_tail_split": 3,
          "structure_effect_floor": .005, "structure_noise_multiple": 45.0,
          "structure_null_hand_rate": .01, "structure_minimum_tail_split": 6}


def upper_tail(a, n_left, c, n_right):
    """Exact conditional hypergeometric upper tail, without a dependency."""
    total, tails = n_left + n_right, a + c
    def log_choose(n, k):
        return lgamma(n + 1) - lgamma(k + 1) - lgamma(n - k + 1)
    probability = exp(log_choose(n_left, a) + log_choose(n_right, tails - a)
                      - log_choose(total, tails))
    result = probability
    for i in range(a, min(n_left, tails)):
        probability *= ((n_left - i) / (i + 1)) * ((tails - i) / (n_right - tails + i + 1))
        result += probability
    return min(1.0, result)


def binomial_tail(a, n, probability):
    value = exp(lgamma(n + 1) - lgamma(a + 1) - lgamma(n - a + 1)
                + a * log(probability) + (n - a) * log(1 - probability))
    result = value
    for i in range(a, n):
        value *= (n - i) / (i + 1) * probability / (1 - probability)
        result += value
    return min(1.0, result)


class ActionTimingGate:
    def __init__(self, settings=None):
        self.settings = {**CONFIG, **(settings or {})}
        self.locations = {}
        self.location_counts = {}
        self.location_cache = {}
        self.pending = {}
        self.groups = {}
        self.last_completed = -1
        self.samples = 0
        self.large_parts = [[0, 0], [0, 0]]
        self.last_test = {"statistic": None, "threshold": -log10(self.settings["alpha_spending"][-1]),
                          "reason": "not enough independent hand samples"}

    def add(self, hand, context, gap, baseline_sd):
        if hand <= self.last_completed:
            return
        street, action, cross = context
        key = (street, cross)
        values = self.locations.setdefault(key, deque(maxlen=self.settings["window"]))
        count = self.location_counts.get(key, 0)
        # Public sample cadence, independent of private strength and gap size.
        if key not in self.location_cache or count % self.settings["location_refresh"] == 0:
            center = median(values) if values else gap
            mad = median(abs(value - center) for value in values) if values else 0.0
            self.location_cache[key] = (center, mad)
        else:
            center, mad = self.location_cache[key]
        self.location_counts[key] = count + 1
        threshold = max(self.settings["minimum_tail"], self.settings["noise_multiple"] * baseline_sd,
                        self.settings["noise_multiple"] * 1.4826 * mad)
        severity = gap - center
        large_threshold = max(self.settings["structure_effect_floor"],
                              self.settings["structure_noise_multiple"] * baseline_sd,
                              self.settings["structure_noise_multiple"] * 1.4826 * mad)
        group = "fold" if action == 0 else "call" if action == 1 else "raise"
        previous = self.pending.get(hand)
        if previous is None or severity > previous[0]:
            # Retain the largest residual in this hand, not simply its last
            # decision (which can overwrite an earlier deliberately slow one).
            self.pending[hand] = (severity, group, severity > threshold, severity > large_threshold)
        values.append(gap)

    def complete(self, before_hand):
        for hand in sorted(tuple(self.pending)):
            if hand >= before_hand:
                continue
            _, group, tail, large = self.pending.pop(hand)
            if hand <= self.last_completed:
                continue
            pair = self.groups.setdefault(group, [[0, 0], [0, 0]])
            part = pair[(pair[0][0] + pair[1][0]) % 2]
            part[0] += 1
            part[1] += int(tail)
            large_part = self.large_parts[self.samples % 2]
            large_part[0] += 1
            large_part[1] += int(large)
            self.samples += 1
            self.last_completed = hand

    def evaluate(self, alpha=None):
        cfg = self.settings
        alpha = cfg["alpha_spending"][-1] if alpha is None else alpha
        best = None
        if self.samples < cfg["minimum_samples"]:
            return None
        for left, right in combinations(self.groups, 2):
            probabilities, directions = [], []
            usable = True
            for (n1, a), (n2, c) in zip(self.groups[left], self.groups[right]):
                if min(n1, n2) < cfg["minimum_split"]:
                    usable = False
                    break
                positive = a / n1 > c / n2
                directions.append(positive)
                p = upper_tail(a, n1, c, n2) if positive else upper_tail(c, n2, a, n1)
                probabilities.append(p)
                if max(a, c) < cfg["minimum_tail_split"]:
                    usable = False
            if not usable or len(probabilities) != 2 or directions[0] != directions[1]:
                continue
            product = probabilities[0] * probabilities[1]
            # Fisher's two-test survival probability. A product alone is not
            # a calibrated combined p-value. Splits contain disjoint hands.
            combined = product * (1 - log(max(product, 1e-300)))
            statistic = -log10(max(combined, 1e-300))
            report = {"statistic": statistic, "threshold": -log10(alpha), "combined_p": combined,
                      "kind": "action_latency", "strength_inference": False,
                      "groups": [left, right], "split_p": probabilities,
                      "maximum_split_p": cfg["split_p"], "samples": self.samples,
                      "group_counts": {g: [part.copy() for part in pair] for g, pair in self.groups.items()}, "alpha": alpha,
                      "reason": "action latency association passed; strength inference not established"}
            self.last_test = report
            if max(probabilities) <= cfg["split_p"] and combined <= alpha:
                if best is None or statistic > best["statistic"]:
                    best = report
        if min(v[1] for v in self.large_parts) >= cfg["structure_minimum_tail_split"]:
            probabilities = [binomial_tail(tails, n, cfg["structure_null_hand_rate"])
                             for n, tails in self.large_parts]
            product = probabilities[0] * probabilities[1]
            combined = product * (1 - log(max(product, 1e-300)))
            report = {"statistic": -log10(max(combined, 1e-300)), "threshold": -log10(alpha),
                      "combined_p": combined, "split_p": probabilities, "alpha": alpha,
                      "kind": "latency_structure", "strength_inference": False,
                      "independent_hand_parts": [v.copy() for v in self.large_parts],
                      "null_large_tail_hand_rate": cfg["structure_null_hand_rate"],
                      "effect_floor_seconds": cfg["structure_effect_floor"],
                      "noise_multiple": cfg["structure_noise_multiple"],
                      "reason": "repeatable large latency component; strength inference not established"}
            if self.last_test["statistic"] is None or report["statistic"] > self.last_test["statistic"]:
                self.last_test = report
            if max(probabilities) <= cfg["split_p"] and combined <= alpha:
                if best is None or report["statistic"] > best["statistic"]:
                    best = report
        if best is not None:
            self.last_test = best
        elif self.last_test["statistic"] is not None:
            self.last_test = {**self.last_test, "reason": "statistic below threshold"}
        else:
            self.last_test = {**self.last_test, "reason": "not enough contrasting tail samples"}
        return best
