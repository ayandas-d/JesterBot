"""Small, fixed-work equity estimates using the engine's read-only table."""

from itertools import combinations

from evaluator import get_table

SAMPLES = {3: 24, 4: 32, 5: 48}
STRAIGHTS = tuple(set(range(i, i + 5)) for i in range(5)) + ({8, 0, 1, 2, 3},)


def preflop_strength(hole):
    """A bounded heuristic, not a calibrated preflop equity table.

    Reward useful pairs, two-card suit coverage and connected high ranks.
    Third/fourth copies and excessive cards of one suit waste PLO hole cards.
    """
    ranks = [c >> 2 for c in hole]
    counts = [ranks.count(r) for r in range(9)]
    suits = [[c >> 2 for c in hole if c & 3 == s] for s in range(4)]
    pairs = sum(0.032 + r * 0.006 for r, n in enumerate(counts) if n >= 2)
    waste = sum(max(0, n - 2) * 0.045 for n in counts)
    suited = sum(0.022 + max(rs) * 0.002 for rs in suits if len(rs) >= 2)
    waste += sum(max(0, len(rs) - 2) * 0.016 for rs in suits)
    connected = max(len(set(ranks) & run) for run in STRAIGHTS)
    return max(0.30, min(0.70, 0.32 + sum(ranks) * 0.004 + pairs
                         + suited + max(0, connected - 2) * 0.025 - waste))


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


def equity(hole, board, rng, samples=None):
    """Equity against uniformly random legal five-card hands, ties worth 1/2.

    Sample opponent and runout together without replacement. No early exit
    based on strength. Counts depend only on the public street.
    """
    n = SAMPLES[len(board)] if samples is None else samples
    known = set(hole) | set(board)
    unseen = tuple(c for c in range(36) if c not in known)
    missing = 5 - len(board)
    pairs = pair_masks(hole)
    table = get_table()
    fixed_triples = board_masks(board) if not missing else None
    fixed_score = score_masks(pairs, fixed_triples, table) if not missing else None
    wins = 0.0
    for _ in range(n):
        draw = rng.sample(unseen, 5 + missing)
        triples = fixed_triples if not missing else board_masks((*board, *draw[5:]))
        ours = fixed_score if not missing else score_masks(pairs, triples, table)
        theirs = score_masks(pair_masks(draw[:5]), triples, table)
        wins += (ours > theirs) + 0.5 * (ours == theirs)
    # Mild shrinkage reduces false certainty from these intentionally small batches.
    return (wins + 1.0) / (n + 2.0)
