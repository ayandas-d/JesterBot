"""Test-only observer of the unmodified timing algorithm; never imported by Jester.

The observer uses only information already present in Jester's memory. It
records overhead distributions and gate-effective sample sizes without changing
any action, fitted model, random draw or timestamp supplied to the base class.
"""

from itertools import combinations
from math import sqrt
from statistics import mean, median, stdev


def distribution(values):
    ordered = sorted(values)
    return {"n": len(values), "mean": mean(values) if values else None,
            "sd": stdev(values) if len(values) > 1 else None,
            "median": median(values) if values else None,
            "p99": ordered[min(len(ordered) - 1, int(len(ordered) * .99))] if ordered else None}


def contexts(timing):
    rows = []
    for context, groups in timing.groups.items():
        row = {"context": list(context), "labels": timing.context_counts[context],
               "matching_baselines": len(timing.baselines[context[2]]), "groups": {}, "contrasts": []}
        for name, parts in groups.items():
            row["groups"][name] = [{"n": v.n, "mean": v.mean, "sd": sqrt(v.variance)} for v in parts]
        for left, right in combinations(groups, 2):
            splits = []
            for a, b in zip(groups[left], groups[right]):
                difference = a.mean - b.mean
                se = sqrt(a.variance / max(1, a.n) + b.variance / max(1, b.n))
                splits.append({"difference": difference, "se": se,
                               "statistic": abs(difference) / max(se, 1e-12)})
            row["contrasts"].append({"groups": [left, right], "splits": splits})
        rows.append(row)
    return rows


def probe_type(base):
    class TimingProbe(base):
        def __init__(self):
            super().__init__()
            self.audit_baselines = {False: [], True: []}
            self.audit_clean = []
            self.audit_labels = []
            self.audit_gate = None
            self.audit_checkpoints = []
            self.audit_dropped = 0

        def _append(self, destination, value):
            if len(destination) < 16384:
                destination.append(value)
            else:
                self.audit_dropped += 1

        def observe(self, obs, model, now):
            before = self.gap_counts.copy()
            gap = now - self.last[3] - self.callback_seconds if self.last is not None else None
            cross = bool(self.last is not None and self.last[0] != obs.hand_index)
            super().observe(obs, model, now)
            if self.gap_counts["baseline"] > before["baseline"]:
                self._append(self.audit_baselines[cross], gap)
            elif self.gap_counts["clean"] > before["clean"]:
                self._append(self.audit_clean, [obs.hand_index, cross, gap,
                                               list(self.current[0]) if self.current else None])
            for checkpoint in (300, 500, 700, 900):
                if obs.hand_index >= checkpoint and not any(v["checkpoint"] == checkpoint for v in self.audit_checkpoints):
                    self.audit_checkpoints.append({"checkpoint": checkpoint, "observed_hand": obs.hand_index,
                                                   "bank_estimate": self.bank_estimate,
                                                   "opponent_actions": self.opponent_actions})

        def _label(self, hand, context, gap, category):
            before = len(self.labelled_hands)
            super()._label(hand, context, gap, category)
            if len(self.labelled_hands) > before:
                self._append(self.audit_labels, [hand, list(context), gap, category])

        def _gate(self, hand):
            previous = self.gate
            super()._gate(hand)
            if previous != self.gate:
                self.audit_gate = {"hand": hand, "decision": self.gate, "reason": self.gate_reason,
                                   "contexts": contexts(self)}

        def audit_report(self):
            return {"overhead": {str(k): distribution(v) for k, v in self.audit_baselines.items()},
                    "overhead_samples": {str(k): v for k, v in self.audit_baselines.items()},
                    "clean_samples": self.audit_clean, "labelled_samples": self.audit_labels,
                    "gate_test": self.audit_gate, "contexts_at_end": contexts(self),
                    "checkpoints": self.audit_checkpoints, "final_bank_estimate": self.bank_estimate,
                    "nudges": self.nudged_decisions, "lowered_k": self.lowered_k_decisions,
                    "dropped": self.audit_dropped}
    return TimingProbe
