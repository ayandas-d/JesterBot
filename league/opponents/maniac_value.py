"""F tier maniac_value: balanced with fixed declared thresholds. PORT selects this independent local server."""

import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from league.opponents.parametric import initialize, choose
from league.opponents.server import create_app, serve

PARAMETERS = {'seed': 114, 'call_margin': -0.025, 'raise_threshold': 0.5, 'bluff': 0.45, 'reraise_threshold': 0.52}

def new_half(config, memory):
    initialize(config, memory, PARAMETERS)

def choose_action(obs, memory):
    return choose(obs, memory, PARAMETERS)

def on_hand_end(result, memory):
    pass

app = create_app('maniac_value', new_half, choose_action, on_hand_end)

if __name__ == "__main__":
    serve(app)
