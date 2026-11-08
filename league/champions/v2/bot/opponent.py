"""Public-information opponent accounting, with no clocks or hidden cards.

Rates facing our raises exclude blinds. A check is CHECK_CALL with zero
chips added; a paid call is never evidence for the check-fold detector.
Only completed hands enter aggregates; the detector also sees the live hand.
"""

from collections import Counter, deque
from dataclasses import dataclass, field, fields

from evaluator import TWO_PAIR, category_of, omaha_score
from game import Action, ObservedAction, RAISE_ACTIONS, Street

CONFIG = {"window_hands": 100, "checkfold_k": 15, "weak_showdown_category": TWO_PAIR}


@dataclass
class Stats:
    events: Counter = field(default_factory=Counter)
    net_bb_by_gear: Counter = field(default_factory=Counter)
    hands_by_gear: Counter = field(default_factory=Counter)
    actions_by_gear: Counter = field(default_factory=Counter)
    showdown_categories: Counter = field(default_factory=Counter)
    showdown_raises: Counter = field(default_factory=Counter)

    def add(self, other, sign=1):
        # Counter subtraction drops negative values, which would lose net losses.
        for item in fields(self):
            target = getattr(self, item.name)
            for key, value in getattr(other, item.name).items():
                target[key] += sign * value
                if target[key] == 0:
                    del target[key]

    def rate(self, numerator, denominator):
        return self.events[numerator] / max(1, self.events[denominator])

    @property
    def fold_to_raise_rate(self):
        return self.rate("folds_to_raise", "faced_raises")

    @property
    def raise_frequency(self):
        return self.rate("raises", "actions")

    @property
    def reraise_frequency(self):
        return self.rate("reraises", "faced_raises")

    @property
    def call_frequency(self):
        return self.rate("calls_to_raise", "faced_raises")

    @property
    def weak_aggressive_showdown_rate(self):
        """A bluffing proxy, not proof that a particular bet was a bluff."""
        return self.rate("weak_aggressive_showdowns", "aggressive_showdowns")


class CheckFoldDetector:
    def __init__(self, k):
        self.k = k
        self.streak = 0

    @property
    def active(self):
        return self.streak >= self.k

    def observe(self, action):
        if action.action == Action.FOLD or (action.action == Action.CHECK_CALL and action.amount == 0):
            self.streak += 1
        else:
            self.streak = 0


@dataclass
class Hand:
    index: int
    gear: str
    is_button: bool
    stats: Stats = field(default_factory=Stats)
    history: list = field(default_factory=list)
    street: Street = Street.PREFLOP
    pending_raise: bool = False
    last_observation: object = None
    showdown: dict | None = None


class OpponentModel:
    def __init__(self, config, settings=None):
        self.config = config
        self.settings = dict(CONFIG if settings is None else settings)
        self.whole = Stats()
        self.rolling = Stats()
        self.recent = deque()
        self.detector = CheckFoldDetector(self.settings["checkfold_k"])
        self.current = None
        self.last_finished = -1

    @property
    def exploit_checkfold(self):
        return self.detector.active

    def _consume(self, hand, action):
        if action.street != hand.street:
            hand.street = action.street
            hand.pending_raise = False
        hand.history.append(action)
        if action.is_me:
            hand.pending_raise = action.action in RAISE_ACTIONS
            return
        events = hand.stats.events
        events["actions"] += 1
        raised = action.action in RAISE_ACTIONS
        called = action.action == Action.CHECK_CALL and action.amount > 0
        folded = action.action == Action.FOLD
        events["raises"] += raised
        events["calls"] += called
        events["folds"] += folded
        events["checks"] += action.action == Action.CHECK_CALL and not called
        if hand.pending_raise:
            events["faced_raises"] += 1
            events["folds_to_raise"] += folded
            events["calls_to_raise"] += called
            events["reraises"] += raised
        hand.pending_raise = False
        self.detector.observe(action)

    def observe(self, obs, gear):
        hand = self.current
        if hand is None or hand.index != obs.hand_index:
            if hand is not None:
                # Missing results (e.g. standalone decision callers) leave a gap
                # in evidence, so do not carry a check-fold streak through it.
                self.detector.streak = 0
            hand = self.current = Hand(obs.hand_index, gear, obs.is_button)
        history = obs.action_history
        if tuple(hand.history) != history[:len(hand.history)]:
            # The authoritative engine history may differ from a proposed
            # action in simulation/retries. Rebuild, never double count it.
            self.detector.streak = 0
            hand = self.current = Hand(obs.hand_index, hand.gear, obs.is_button)
        for action in history[len(hand.history):]:
            self._consume(hand, action)
        hand.last_observation = obs

    def record_action(self, obs, action):
        hand = self.current
        if hand is None or hand.index != obs.hand_index:
            return
        amount = (obs.raise_to[action] - obs.my_bet if action in RAISE_ACTIONS else
                  min(obs.to_call, obs.my_stack) if action == Action.CHECK_CALL else 0)
        self._consume(hand, ObservedAction(obs.street, True, action, amount, obs.my_bet + amount))

    def _terminal_response(self, hand, result):
        if not hand.history or not hand.history[-1].is_me:
            return
        last = hand.history[-1]
        if last.action == Action.FOLD:
            return
        obs = hand.last_observation
        if not result.went_to_showdown and result.winner == "me":
            self._consume(hand, ObservedAction(last.street, False, Action.FOLD, 0, obs.opp_bet))
        elif result.went_to_showdown and last.action in RAISE_ACTIONS:
            amount = min(last.street_total - obs.opp_bet, obs.opp_stack)
            self._consume(hand, ObservedAction(last.street, False, Action.CHECK_CALL,
                                              amount, obs.opp_bet + amount))
        elif (result.went_to_showdown and last.street == Street.RIVER
              and last.amount == 0 and not hand.is_button):
            # Non-button's river check leaves the opponent's closing check
            # unseen. A closing call/check by us needs no inferred action.
            self._consume(hand, ObservedAction(last.street, False, Action.CHECK_CALL, 0, obs.opp_bet))

    def end(self, result, gear):
        """Commit an ordered HandResult once, including its unseen final action."""
        if result.hand_index <= self.last_finished:
            return False
        hand = self.current
        if hand is not None and hand.index == result.hand_index:
            self._terminal_response(hand, result)
            self.current = None
        else:
            hand = Hand(result.hand_index, gear, False)
            if not result.went_to_showdown and result.winner == "me":
                # Opponent folded their small blind before we had any decision.
                self._consume(hand, ObservedAction(Street.PREFLOP, False, Action.FOLD,
                                                  0, self.config.small_blind))
        stats = hand.stats
        stats.events["hands"] = 1
        stats.net_bb_by_gear[hand.gear] = result.my_net / self.config.big_blind
        stats.hands_by_gear[hand.gear] = 1
        stats.actions_by_gear[hand.gear] = stats.events["actions"]
        if result.went_to_showdown and result.opp_hole is not None:
            category = category_of(omaha_score(result.opp_hole, result.board))
            raises = stats.events["raises"]
            stats.events["showdowns"] = 1
            stats.events["aggressive_showdowns"] = int(raises > 0)
            stats.events["weak_aggressive_showdowns"] = int(
                raises > 0 and category <= self.settings["weak_showdown_category"])
            stats.showdown_categories[category] = 1
            stats.showdown_raises[category] = raises
            hand.showdown = {"category": category, "raises": raises, "actions": stats.events["actions"]}
        self.whole.add(stats)
        self.rolling.add(stats)
        self.recent.append(hand)
        if len(self.recent) > self.settings["window_hands"]:
            self.rolling.add(self.recent.popleft().stats, -1)
        self.last_finished = result.hand_index
        return True
