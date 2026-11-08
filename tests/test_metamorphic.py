"""Card symmetries and known hand upgrades, with controlled Monte Carlo noise."""

from dataclasses import replace
from random import Random

from hypothesis import given, settings, strategies as st

from bot.equity import equity
from bot.policy import CONFIG, action_probabilities
from bot.preflop import preflop_strength
from evaluator import cards_from_str, category_of, omaha_score
from game import Action, Game, make_deal


def permute(card, suits):
    return (card & ~3) | suits[card & 3]


@settings(max_examples=24, deadline=None, derandomize=True, database=None)
@given(st.integers(0, 100_000), st.permutations((0, 1, 2, 3)))
def test_suit_permutation_preserves_score_and_paired_equity(seed, suits):
    deal = make_deal("suit-metamorphic", seed)
    hole, board = deal.hole_cards[0], deal.board
    changed_hole = tuple(permute(c, suits) for c in hole)
    changed_board = tuple(permute(c, suits) for c in board)
    assert omaha_score(hole, board) == omaha_score(changed_hole, changed_board)
    assert category_of(omaha_score(hole, board)) == category_of(omaha_score(changed_hole, changed_board))
    inverse = tuple(suits.index(i) for i in range(4))
    class CoupledRandom(Random):
        def sample(self, population, k):
            original = sorted(permute(c, inverse) for c in population)
            return [permute(c, suits) for c in super().sample(original, k)]
    # Common random draws under the suit mapping are still uniform; this
    # removes sampling noise and checks every simulated showdown exactly.
    for count in (0, 3, 4, 5):
        a = equity(hole, board[:count], Random(seed), samples=64)
        b = equity(changed_hole, changed_board[:count], CoupledRandom(seed), samples=64)
        assert a == b


def test_uncoupled_suit_equities_agree_within_sampling_noise():
    suits = (2, 0, 3, 1)
    for seed in range(6):
        deal = make_deal("independent-suits", seed)
        hole, board = deal.hole_cards[0], deal.board[:3]
        changed_hole = tuple(permute(c, suits) for c in hole)
        changed_board = tuple(permute(c, suits) for c in board)
        a = sum(equity(hole, board, Random(seed * 10 + j), samples=128) for j in range(4)) / 4
        b = sum(equity(changed_hole, changed_board, Random(1000 + seed * 10 + j), samples=128) for j in range(4)) / 4
        # < 4 standard errors under the worst-case Bernoulli variance.
        assert abs(a - b) < .125


@settings(max_examples=30, deadline=None, derandomize=True, database=None)
@given(st.integers(0, 100_000), st.permutations((0, 1, 2, 3, 4)))
def test_hole_card_order_does_not_change_any_gear_distribution(seed, order):
    game = Game(make_deal("card-order", seed), 0)
    for street in range(4):
        obs = game.observation(game.to_act)
        changed = replace(obs, hole_cards=tuple(obs.hole_cards[i] for i in order))
        if street == 0:
            strength, other = preflop_strength(obs.hole_cards), preflop_strength(changed.hole_cards)
        else:
            strength = equity(obs.hole_cards, obs.board, Random(seed), samples=64)
            other = equity(changed.hole_cards, changed.board, Random(seed), samples=64)
        assert strength == other
        for gear in CONFIG["gears"]:
            assert action_probabilities(obs, strength, gear) == action_probabilities(changed, other, gear)
        if street < 3:
            game.apply(Action.CHECK_CALL)
            game.apply(Action.CHECK_CALL)


def test_known_river_hand_upgrades_do_not_lower_equity_beyond_noise():
    board = tuple(cards_from_str("Qh Jh Th 9c 6c"))
    hands = [tuple(cards_from_str(text)) for text in
             ("7c 7d 8c 8d 6s", "Ac Ad Kc 7d 8s", "Ah Kh 6d 7d 8s")]
    scores = [omaha_score(hand, board) for hand in hands]
    assert scores[0] < scores[1] < scores[2]
    strengths = [sum(equity(hand, board, Random(620 + j), samples=128) for j in range(4)) / 4 for hand in hands]
    assert all(a <= b + .125 for a, b in zip(strengths, strengths[1:]))
    assert strengths[-1] > .99
    # The fixture specifies actual made-hand upgrades. Merely replacing a
    # rank by a larger rank is NOT a valid monotonicity rule for Omaha draws.
