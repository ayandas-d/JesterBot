"""Street-fixed Monte Carlo using the engine's exact Omaha evaluator."""

from itertools import combinations
import os
from random import Random
from time import perf_counter

from evaluator import omaha_score
from bot.preflop import preflop_strength  # compatibility for the earlier policy

SAMPLES = {3: 40, 4: 40, 5: 72}
DECISION_CAP_SECONDS = 0.030


def reset_rng():
    """Fresh module RNG per half; BOT_SEED reproduces the complete stream."""
    global RNG
    seed = os.environ.get("BOT_SEED")
    RNG = Random(seed if seed is not None else os.urandom(32))
    return RNG


RNG = reset_rng()


def pair_masks(cards):
    return tuple((1 << a) | (1 << b) for a, b in combinations(cards, 2))


def board_masks(board):
    return tuple((1 << a) | (1 << b) | (1 << c)
                 for a, b, c in combinations(board, 3))


def score_masks(pairs, triples, table):
    best = 0
    for pair in pairs:
        for triple in triples:
            score = table[pair | triple]
            if score > best:
                best = score
    return best


def equity(hole, board, rng=None, samples=None, deadline=None):
    """Equity against uniformly random legal five-card hands, ties worth 1/2.

    Sample opponent and runout together without replacement, respecting all
    known cards. Counts depend on street and the half's global governor.
    A cooperative wall-clock deadline is the only early exit; strength
    never affects work. A cap interrupted before any trial returns 0.5.
    """
    n = SAMPLES[len(board)] if samples is None else samples
    if n < 1:
        raise ValueError("samples must be positive")
    rng = RNG if rng is None else rng
    cap = perf_counter() + DECISION_CAP_SECONDS
    deadline = cap if deadline is None else min(deadline, cap)
    known = set(hole) | set(board)
    unseen = tuple(c for c in range(36) if c not in known)
    missing = 5 - len(board)
    fixed_score = omaha_score(hole, board) if not missing else None
    wins = 0.0
    completed = 0
    for _ in range(n):
        if perf_counter() >= deadline:
            break
        draw = rng.sample(unseen, 5 + missing)
        full_board = board if not missing else (*board, *draw[5:])
        ours = fixed_score if not missing else omaha_score(hole, full_board)
        theirs = omaha_score(draw[:5], full_board)
        wins += (ours > theirs) + 0.5 * (ours == theirs)
        completed += 1
    return wins / completed if completed else 0.5
