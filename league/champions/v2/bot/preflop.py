"""Cheap PLO5 starting-hand structure score, normalized to [0, 1].

This is a heuristic quality score, not a calibrated probability of winning.
"""

STRAIGHTS = tuple(frozenset(range(i, i + 5)) for i in range(5)) + (frozenset((8, 0, 1, 2, 3)),)


def preflop_score(hole):
    ranks = [card >> 2 for card in hole]
    counts = [ranks.count(rank) for rank in range(9)]
    suits = [[card >> 2 for card in hole if card & 3 == suit] for suit in range(4)]
    high_cards = sum(ranks) / 40 * 0.24
    pairs = sum(0.10 + rank / 8 * 0.10 for rank, count in enumerate(counts) if count >= 2)
    suited = sum(0.055 + max(group) / 8 * 0.045 + (0.04 if 8 in group else 0)
                 for group in suits if len(group) >= 2)
    connected = max(len(set(ranks) & run) for run in STRAIGHTS)
    connectivity = max(0, connected - 2) * 0.055
    dead_cards = sum(max(0, count - 2) * 0.16 for count in counts)
    suit_crowding = sum(max(0, len(group) - 2) * 0.07 for group in suits)
    return max(0.0, min(1.0, 0.10 + high_cards + pairs + suited
                        + connectivity - dead_cards - suit_crowding))


def preflop_strength(hole):
    """Conservative policy proxy preserving the existing 0.30-0.70 scale."""
    return 0.30 + 0.40 * preflop_score(hole)
