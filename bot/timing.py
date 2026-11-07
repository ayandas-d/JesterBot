"""Passive timing only. Request gaps are noisy proxies, never clock access
to the opponent. Separate contexts and held-out confirmation are mandatory.
"""

from collections import defaultdict, deque
from math import sqrt
from statistics import median


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
