"""Unscored holdout policy fixed before validation. PORT selects this independent local server."""

import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from league.opponents.parametric import initialize, choose
from league.opponents.server import create_app, serve

PARAMETERS = {'seed': 408, 'idea': 'value_trap', 'preflop_floor': 0.49, 'call_margin': 0.065, 'samples': 80}

def new_half(config, memory):
    initialize(config, memory, PARAMETERS)

def choose_action(obs, memory):
    return choose(obs, memory, PARAMETERS)

def on_hand_end(result, memory):
    pass

app = create_app('holdout3_trap', new_half, choose_action, on_hand_end)

if __name__ == "__main__":
    serve(app)
