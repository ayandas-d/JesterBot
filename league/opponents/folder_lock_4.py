"""H tier folder_lock_4: folder_lock with fixed declared thresholds. PORT selects this independent local server."""

import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from league.opponents.parametric import initialize, choose
from league.opponents.server import create_app, serve

PARAMETERS = {'seed': 203, 'idea': 'folder_lock', 'preflop_floor': 0.61, 'call_floor': 0.61, 'call_margin': 0.08, 'raise_threshold': 0.8, 'reraise_threshold': 0.86, 'samples': 80, 'bluff': 0.0, 'pot_fraction': 0.95}

def new_half(config, memory):
    initialize(config, memory, PARAMETERS)

def choose_action(obs, memory):
    return choose(obs, memory, PARAMETERS)

def on_hand_end(result, memory):
    pass

app = create_app('folder_lock_4', new_half, choose_action, on_hand_end)

if __name__ == "__main__":
    serve(app)
