"""F tier odds_wide: balanced with fixed declared thresholds. PORT selects this independent local server."""

import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from league.opponents.parametric import initialize, choose
from league.opponents.server import create_app, serve

PARAMETERS = {'seed': 116, 'call_margin': -0.045, 'raise_threshold': 0.6, 'bluff': 0.02}

def new_half(config, memory):
    initialize(config, memory, PARAMETERS)

def choose_action(obs, memory):
    return choose(obs, memory, PARAMETERS)

def on_hand_end(result, memory):
    pass

app = create_app('odds_wide', new_half, choose_action, on_hand_end)

if __name__ == "__main__":
    serve(app)
