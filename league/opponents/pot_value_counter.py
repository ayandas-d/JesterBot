"""H tier pot_value_counter: balanced with fixed declared thresholds. PORT selects this independent local server."""

import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from league.opponents.parametric import initialize, choose
from league.opponents.server import create_app, serve

PARAMETERS = {'seed': 221, 'idea': 'balanced', 'call_margin': 0.1, 'raise_threshold': 0.64, 'reraise_threshold': 0.67, 'samples': 96, 'bluff': 0.0, 'pot_fraction': 1.0}

def new_half(config, memory):
    initialize(config, memory, PARAMETERS)

def choose_action(obs, memory):
    return choose(obs, memory, PARAMETERS)

def on_hand_end(result, memory):
    pass

app = create_app('pot_value_counter', new_half, choose_action, on_hand_end)

if __name__ == "__main__":
    serve(app)
