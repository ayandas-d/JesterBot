"""Experiment-only adapter; production strategy remains untouched."""
import os
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from tools import serve_agent as telemetry

variant = os.environ.get('BACKTEST_VARIANT', 'original')
base_new = telemetry.agent.new_half

def new_half(config, memory):
    base_new(config, memory)
    state = memory['bot']
    if variant == 'no_timing':
        state.timing.enabled = False
    elif variant == 'aggro_start':
        state.gear = 'AGGRO'
    elif variant != 'original':
        raise ValueError(variant)

telemetry.agent.new_half = new_half
if __name__ == '__main__':
    telemetry.agent.uvicorn.run(telemetry.agent.app, host='127.0.0.1',
        port=int(os.environ['PORT']), log_level='warning', access_log=False)
