"""Test-only board_oracle: explicit unfair privileges from the separate oracle judge. PORT selects the server."""

import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from league.opponents.oracle_common import initialize, choose
from league.opponents.server import create_app, serve

KIND = 'board_oracle'

def choose_action(obs, memory):
    raise ValueError("Use tools/oracle_judge/engine.py for cheater matches")

def choose_extra(obs, memory, extra):
    return choose(KIND, obs, memory, extra)

new_half = initialize
app = create_app(KIND, new_half, choose_action, extra_action=choose_extra)

if __name__ == "__main__":
    serve(app)
