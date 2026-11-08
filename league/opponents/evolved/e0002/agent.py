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
PARAMETERS = {'preflop_floor': 0.22474, 'call_floor': 0.41283, 'call_margin': 0.10003, 'raise_threshold': 0.69397, 'raise_frequency': 0.84838, 'bluff': 0.12614, 'pot_fraction': 0.28566, 'reraise_threshold': 0.59179, 'range_bias': 0.65681, 'idea': 'range_reader', 'seed': 626836, 'samples': 80, 'preflop_samples': 24, 'bait_length': 23, 'switch_every': 71}

def new_half(config,memory):
    family.initialize(config,memory,PARAMETERS)

def choose_action(obs,memory):
    return family.choose(obs,memory,PARAMETERS)

def on_hand_end(result,memory):
    pass

app = server.create_app(HERE.name,new_half,choose_action,on_hand_end)

if __name__ == "__main__":
    server.serve(app)
