"""Shared independent engine walks used by safety and policy tests."""

from random import Random

from game import Action, Game, make_deal


def fuzz_hands(observe, finish=None, hands=2500):
    rng = Random(20261107)
    for hand in range(hands):
        game = Game(make_deal("safety-fuzz", hand), hand % 2, hand_index=hand)
        while not game.is_terminal:
            obs = game.observation(game.to_act)
            observe(obs)
            mode = hand % 4
            if mode == 0:
                applied = Action.CHECK_CALL
            elif mode == 1:
                applied = Action.RAISE_POT if Action.RAISE_POT in obs.legal_actions else Action.CHECK_CALL
            elif mode == 2:
                applied = rng.choice(obs.legal_actions)
            else:
                applied = rng.choice([a for a in obs.legal_actions if a != Action.FOLD])
            game.apply(applied)
        if finish is not None:
            finish(tuple(game.hand_result(seat) for seat in (0, 1)))
