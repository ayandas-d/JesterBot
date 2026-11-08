"""A half-wide computation budget. It never inspects private cards/equity."""

from bot.equity import SAMPLES

CONFIG = {"half_ceiling_seconds": 4.0, "external_reserve_seconds": 1.5,
          "time_bank_fraction": .75}


def computation_budget(config):
    total = min(CONFIG["half_ceiling_seconds"], config.time_bank_seconds * CONFIG["time_bank_fraction"])
    fraction = 1 - CONFIG["external_reserve_seconds"] / CONFIG["half_ceiling_seconds"]
    return max(.000001, total * fraction)


class TimeGovernor:
    def __init__(self, num_hands, budget_seconds=4.0, decision_cap=0.030):
        self.num_hands = max(1, num_hands)
        self.budget_seconds = max(0.000001, budget_seconds)
        self.decision_cap = decision_cap
        self.total_seconds = 0.0
        self.callback_seconds = 0.0
        self.decisions = 0
        self.scale = 1.0
        self.reductions = 0
        self.last_reduction_hand = -16
        self.deadline = None

    def samples_for(self, board_length):
        return max(4, int(SAMPLES[board_length] * self.scale))

    def begin(self, start):
        self.deadline = start + self.decision_cap

    def record(self, hand_index, elapsed):
        self.decisions += 1
        self._account(hand_index, elapsed)

    def record_callback(self, hand_index, elapsed):
        self.callback_seconds += max(0.0, elapsed)
        self._account(hand_index, elapsed)

    def _account(self, hand_index, elapsed):
        self.total_seconds += max(0.0, elapsed)
        projected = self.total_seconds * self.num_hands / max(1, hand_index + 1)
        target = self.budget_seconds * 0.90
        # Avoid overreacting to one unusually long opening hand. Tiny budgets
        # and genuinely spent budgets still trigger an immediate reduction.
        urgent = self.total_seconds >= target
        enough_data = hand_index >= 11 or self.total_seconds >= self.budget_seconds * 0.25
        cooled_down = hand_index - self.last_reduction_hand >= 16
        if projected > target and enough_data and (cooled_down or urgent):
            new_scale = max(0.0625, min(self.scale * 0.75, self.scale * target / projected))
            if new_scale < self.scale:
                self.scale = new_scale
                self.reductions += 1
                self.last_reduction_hand = hand_index
