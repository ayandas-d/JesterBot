"""Periodic opponent-driven gear selection with evidence and hysteresis."""

CONFIG = {
    "evaluate_every": 25,
    "minimum_events": 40,
    "confirmations": 2,
    "cooldown_hands": 75,
    "folder_fold_rate": 0.55,
    "station_fold_rate": 0.30,
    "station_call_rate": 0.55,
    "reraise_rate": 0.30,
    "losing_net_bb": 0.0,
    "folder_bluff_multiplier": 1.10,
}


class GearSelector:
    def __init__(self, settings=None):
        self.settings = dict(CONFIG if settings is None else settings)
        self.last_evaluation = 0
        self.last_switch = -self.settings["cooldown_hands"]
        self.candidate = None
        self.confirmations = 0
        self.folder = False
        self.transitions = []

    def _target(self, stats, gear):
        cfg = self.settings
        responses = stats.events["faced_raises"] >= cfg["minimum_events"]
        reraiser = responses and stats.reraise_frequency > cfg["reraise_rate"]
        self.folder = responses and stats.fold_to_raise_rate > cfg["folder_fold_rate"]
        if reraiser:
            return "TRAP", "frequent re-raises"
        if self.folder:
            return "MANIAC", "frequent folds"
        station = (responses and stats.fold_to_raise_rate < cfg["station_fold_rate"]
                   and stats.call_frequency > cfg["station_call_rate"])
        if station and stats.net_bb_by_gear["MANIAC"] < cfg["losing_net_bb"]:
            return "VALUE", "calling station punishes MANIAC"
        if (stats.actions_by_gear[gear] >= cfg["minimum_events"]
                and stats.net_bb_by_gear[gear] < cfg["losing_net_bb"]):
            target = {"MANIAC": "AGGRO", "AGGRO": "VALUE"}.get(gear, gear)
            return target, "rolling losses in current gear"
        return gear, "hold"

    def evaluate(self, hands, stats, gear):
        cfg = self.settings
        if hands - self.last_evaluation < cfg["evaluate_every"]:
            return gear
        self.last_evaluation = hands
        target, reason = self._target(stats, gear)
        if target == gear:
            self.candidate, self.confirmations = None, 0
            return gear
        if target == self.candidate:
            self.confirmations += 1
        else:
            self.candidate, self.confirmations = target, 1
        if (self.confirmations >= cfg["confirmations"]
                and hands - self.last_switch >= cfg["cooldown_hands"]):
            self.transitions.append((hands, gear, target, reason))
            self.last_switch = hands
            self.candidate, self.confirmations = None, 0
            return target
        return gear

    def bluff_multiplier(self, gear):
        return self.settings["folder_bluff_multiplier"] if self.folder and gear == "MANIAC" else 1.0
