"""Reserved Hard holdout: river nut-blocker bluffs, an idea absent from training."""

from collections import Counter
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from evaluator import ACE, card_rank, card_suit
from game import Action, Street
from league.opponents.parametric import initialize, choose
from league.opponents.server import create_app, serve

PARAMETERS = dict(seed=511, call_margin=.05, raise_threshold=.67, samples=80, bluff=.02)


def new_half(config, memory):
    initialize(config, memory, PARAMETERS)


def choose_action(obs, memory):
    action = choose(obs, memory, PARAMETERS)
    suits = Counter(map(card_suit, obs.board))
    blocker = any(n >= 3 and sum(card_suit(c) == suit for c in obs.hole_cards) == 1
                  and any(card_rank(c) == ACE and card_suit(c) == suit for c in obs.hole_cards)
                  for suit, n in suits.items())
    if (obs.street == Street.RIVER and not obs.to_call and blocker
            and action == Action.CHECK_CALL and Action.RAISE_POT in obs.legal_actions
            and memory["rng"].random() < .35):
        return Action.RAISE_POT
    return action


app = create_app("holdout3_blocker_counter", new_half, choose_action)

if __name__ == "__main__":
    serve(app)
