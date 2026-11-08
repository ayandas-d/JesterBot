"""Mixed aggression with rolling opponent responses and reversible gears."""

from collections import deque
from dataclasses import dataclass, field
from random import Random

from game import Action, AgentConfig, Street
from bot.equity import equity, preflop_strength
from bot.timing import Timing

RAISES = (Action.RAISE_HALF, Action.RAISE_POT)


@dataclass
class Hand:
    index: int
    seen: int = 0
    decisions: int = 0
    raises: int = 0
    facing: int = 0
    folds: int = 0
    pending: bool = False
    timings: list = field(default_factory=list)


class State:
    def __init__(self, config):
        self.rng = Random()  # private entropy, never derived from the match/deal
        self.equity_rng = Random()
        self.learning_rng = Random()
        self.config = config
        self.timing = Timing(config.num_hands)
        self.hands = {}
        self.recent = deque(maxlen=80)
        self.hands_played = 0
        self.last_result = -1
        self.fold_streak = 0
        self.gear = "maniac"
        self.gear_since = 0
        self.last_equity = None

    def response(self, h, action):
        if action in RAISES or action == Action.CHECK_CALL:
            # Any voluntary defense contradicts the auto check/fold hypothesis.
            if h.pending or action in RAISES:
                self.fold_streak = 0
        if h.pending:
            h.facing += 1
            if action == Action.FOLD:
                h.folds += 1
                self.fold_streak += 1
            h.pending = False
        h.decisions += 1
        h.raises += action in RAISES

    def observe(self, obs, now):
        h = self.hands.setdefault(obs.hand_index, Hand(obs.hand_index))
        for event in obs.action_history[h.seen:]:
            if event.is_me:
                h.pending = event.action in RAISES
            else:
                self.response(h, event.action)
        h.seen = len(obs.action_history)
        self.timing.observe(obs, now)
        # Training only on preflop and river avoids assigning runout strength
        # to a flop draw. Flop/turn timing never changes the policy.
        if self.timing.current is not None and obs.street in (Street.PREFLOP, Street.RIVER):
            # Repeated raises in one hand are correlated. Count at most one
            # sample per hand/context toward the statistical gate.
            if not any(t[0] == self.timing.current[0] for t in h.timings):
                h.timings.append(self.timing.current)
        return h

    def record_action(self, obs, action):
        h = self.hands[obs.hand_index]
        h.pending = action in RAISES
        # Our own action will be in the next cumulative history; skip it there
        # so a pending raise is resolved exactly once, including terminal folds.
        h.seen = len(obs.action_history) + 1

    def end(self, result):
        if result.hand_index <= self.last_result:
            return  # result batches are ordered; duplicate delivery is harmless
        h = self.hands.pop(result.hand_index, Hand(result.hand_index))
        if h.pending:
            terminal = Action.FOLD if result.winner == "me" and not result.went_to_showdown else Action.CHECK_CALL
            self.response(h, terminal)
        if result.opp_hole:
            for context, gap, board in h.timings:
                strength = (preflop_strength(result.opp_hole) if not board else
                            equity(result.opp_hole, board, self.learning_rng, samples=16))
                self.timing.learn(context, gap, strength, result.hand_index)
        self.recent.append((h.decisions, h.raises, h.facing, h.folds,
                            result.my_net / self.config.big_blind, result.went_to_showdown))
        self.hands_played += 1
        self.last_result = result.hand_index
        self.update_gear()

    def stats(self):
        decisions = sum(r[0] for r in self.recent)
        facing = sum(r[2] for r in self.recent)
        return (decisions, facing,
                (sum(r[1] for r in self.recent) + 2) / (decisions + 6),
                (sum(r[3] for r in self.recent) + 1) / (facing + 4))

    def update_gear(self):
        if self.hands_played < 16 or self.hands_played - self.gear_since < 12:
            return
        decisions, facing, aggression, folding = self.stats()
        punished = sum(r[4] for r in self.recent) < -100 and sum(r[5] for r in self.recent) >= 12
        if decisions >= 25 and aggression > (0.36 if self.gear == "counter" else 0.47):
            target = "counter"
        elif (facing >= 12 and folding < (0.23 if self.gear == "value" else 0.16)) or punished:
            target = "value"
        elif facing >= 12 and folding > (0.43 if self.gear == "pressure" else 0.58):
            target = "pressure"
        else:
            target = "balanced"
        if target != self.gear:
            self.gear, self.gear_since = target, self.hands_played


def get_state(memory):
    state = memory.get("bot")
    if not isinstance(state, State):
        state = State(AgentConfig())
        memory["bot"] = state
    return state


def policy(obs, state):
    strength = (preflop_strength(obs.hole_cards) if obs.street == Street.PREFLOP else
                equity(obs.hole_cards, obs.board, state.equity_rng))
    state.last_equity = strength
    strength += state.timing.adjustment(obs.hand_index)
    raises = [a for a in RAISES if a in obs.legal_actions]
    state.timing.collapse_hint(obs.hand_index, state.fold_streak)
    if state.fold_streak >= 6 and raises and obs.to_call <= obs.big_blind:
        return raises[0]  # cheapest repeated steal; revoked immediately on defense

    _, facing, aggression, folding = state.stats()
    # Uniform-hand equity overstates our chances against a selective raiser.
    if obs.to_call > obs.big_blind and aggression < 0.30:
        strength -= 0.06 if obs.street != Street.PREFLOP else 0.035
    if obs.raises_this_street >= 2 and state.gear != "counter":
        strength -= 0.035
    call = min(obs.to_call, obs.my_stack)
    odds = call / max(1, obs.pot + call)
    if call and strength < odds + (0.025 if obs.street == Street.RIVER else 0.055):
        # Almost no hopeless calls; tiny randomization near the boundary only.
        if strength < odds - 0.04 or state.rng.random() < 0.92:
            return Action.FOLD
    if not raises:
        return Action.CHECK_CALL

    base = {"maniac": 0.72, "pressure": 0.78, "balanced": 0.42,
            "counter": 0.28, "value": 0.20}[state.gear]
    # Bluffs shrink when opponents defend; value raises grow with equity.
    raise_p = base + 1.1 * (strength - 0.50)
    if state.gear == "value":
        raise_p = 0.06 + max(0, strength - 0.48) * 3.2
    if obs.to_call > obs.big_blind:
        raise_p -= 0.23
    if obs.raises_this_street >= 2:
        raise_p -= 0.20
    if obs.is_button and obs.street != Street.PREFLOP:
        raise_p += 0.04
    if obs.street == Street.RIVER and strength < 0.35:
        raise_p = min(raise_p, 0.10 if facing >= 12 and folding > 0.50 else 0.025)
    if strength > 0.76:
        raise_p = max(raise_p, 0.88)
    if state.rng.random() >= max(0.015, min(0.95, raise_p)):
        return Action.CHECK_CALL
    # Size mixing is independent of hand strength, conditional on the gear.
    pot_p = 0.62 if state.gear in ("maniac", "pressure") else 0.40
    preferred = Action.RAISE_POT if state.rng.random() < pot_p else Action.RAISE_HALF
    return preferred if preferred in raises else raises[0]
