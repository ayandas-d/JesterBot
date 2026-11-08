"""Frozen evolved fair adversary. PORT selects its server; META.json records provenance."""
import importlib.util
from pathlib import Path
import sys

HERE = Path(__file__).resolve().parent
ROOT = next(p for p in HERE.parents if (p/"game.py").is_file())
sys.path.insert(0,str(ROOT))

def load(name):
    spec = importlib.util.spec_from_file_location("frozen_"+HERE.name+"_"+name,HERE/(name+".py"))
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module

family, server = load("family"), load("server")
PARAMETERS = {'preflop_floor': 0.47518, 'call_floor': 0.19056, 'call_margin': 0.10003, 'raise_threshold': 0.67484, 'raise_frequency': 0.75453, 'bluff': 0.1374, 'pot_fraction': 0.28566, 'reraise_threshold': 0.8501, 'range_bias': 0.76214, 'idea': 'reraise_bait', 'seed': 421894, 'samples': 80, 'preflop_samples': 24, 'bait_length': 32, 'switch_every': 102}

def new_half(config,memory):
    family.initialize(config,memory,PARAMETERS)

def choose_action(obs,memory):
    return family.choose(obs,memory,PARAMETERS)

def on_hand_end(result,memory):
    pass

app = server.create_app(HERE.name,new_half,choose_action,on_hand_end)

if __name__ == "__main__":
    server.serve(app)
