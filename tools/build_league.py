"""Declare the expanded league before validation; never overwrite evolved bots.

Run once for initial setup, then use refresh_hashes() after deliberate edits.
Rebuilding an already expanded config is refused to preserve the hall of fame.
"""

from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))


def wrapper(name, parameters, idea, path=None):
    path = path or ROOT / "league/opponents" / (name + ".py")
    path.parent.mkdir(parents=True, exist_ok=True)
    source = f'''"""{idea} PORT selects this independent local server."""

import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from league.opponents.parametric import initialize, choose
from league.opponents.server import create_app, serve

PARAMETERS = {parameters!r}

def new_half(config, memory):
    initialize(config, memory, PARAMETERS)

def choose_action(obs, memory):
    return choose(obs, memory, PARAMETERS)

def on_hand_end(result, memory):
    pass

app = create_app({name!r}, new_half, choose_action, on_hand_end)

if __name__ == "__main__":
    serve(app)
'''
    path.write_text(source)
    return path


def refresh_hashes(config):
    shared = ("parametric.py", "server.py", "common.py", "styles.py", "oracle_common.py")
    for entry in config["opponents"].values():
        script = ROOT / entry["script"]
        sources = [script, *(ROOT / "league/opponents" / name for name in shared)]
        if script.parent != ROOT / "league/opponents":
            sources += list(script.parent.glob("*.py")) + list(script.parent.glob("*.json"))
        entry["source_sha256"] = hashlib.sha256(script.read_bytes()).hexdigest()
        entry["source_files"] = {str(p.relative_to(ROOT)): hashlib.sha256(p.read_bytes()).hexdigest()
                                 for p in sources if p.is_file()}
    return config


def build():
    path = ROOT / "league/config.json"
    config = json.loads(path.read_text())
    if config.get("schema_version", 1) >= 2:
        raise ValueError("Expanded league exists; refusing to replace its hall of fame")
    training = config["training"]["opponents"]
    for name in training:
        config["opponents"][name]["tier"] = "F"
    fair = {
        "station_wide": dict(call_margin=-.20, raise_threshold=.90, bluff=0., raise_frequency=.1),
        "station_selective": dict(call_floor=.30, call_margin=-.06, raise_threshold=.80, bluff=0.),
        "station_value": dict(call_margin=-.08, raise_threshold=.58, bluff=.01, pot_fraction=.9),
        "nit_52": dict(preflop_floor=.52, call_margin=.08, raise_threshold=.66, bluff=0.),
        "nit_58": dict(preflop_floor=.58, call_margin=.10, raise_threshold=.72, bluff=0.),
        "nit_64": dict(preflop_floor=.64, call_margin=.12, raise_threshold=.78, bluff=0.),
        "tag_halfpot": dict(preflop_floor=.52, call_margin=.035, raise_threshold=.58, pot_fraction=.15),
        "tag_value": dict(preflop_floor=.50, call_margin=.06, raise_threshold=.64, pot_fraction=.95),
        "tag_pressure": dict(preflop_floor=.48, call_margin=.01, raise_threshold=.55, bluff=.08),
        "lag_halfpot": dict(call_margin=-.04, raise_threshold=.52, bluff=.22, pot_fraction=.2),
        "lag_pot": dict(call_margin=-.03, raise_threshold=.55, bluff=.32, pot_fraction=.95),
        "lag_position": dict(idea="street_pressure", call_margin=-.02, raise_threshold=.58, bluff=.12),
        "maniac_selective": dict(call_floor=.25, call_margin=-.08, raise_threshold=.46, bluff=.75),
        "maniac_halfpot": dict(call_margin=-.06, raise_threshold=.44, bluff=.9, pot_fraction=.05),
        "maniac_value": dict(call_margin=-.025, raise_threshold=.50, bluff=.45, reraise_threshold=.52),
        "odds_tight": dict(call_margin=.08, raise_threshold=.68, bluff=0.),
        "odds_wide": dict(call_margin=-.045, raise_threshold=.60, bluff=.02),
        "odds_balanced": dict(call_margin=.005, raise_threshold=.62, bluff=.08, pot_fraction=.5),
        "equity_conservative": dict(call_margin=.055, raise_threshold=.72, samples=64),
        "equity_semibluff": dict(call_margin=.015, raise_threshold=.57, bluff=.10, samples=64),
        "equity_rangewise": dict(idea="range_reader", call_margin=.025, raise_threshold=.65, range_bias=.85),
        "mixed_street": dict(idea="street_pressure", call_margin=.03, raise_threshold=.65, bluff=.06),
        "mixed_cycle": dict(idea="gear_cycle", switch_every=80, call_margin=.025, bluff=.06),
    }
    hard = {}
    for index, floor in enumerate((.52, .55, .58, .61, .64, .67)):
        hard[f"folder_lock_{index+1}"] = dict(idea="folder_lock", preflop_floor=floor,
            call_floor=floor, call_margin=.08, raise_threshold=.80, reraise_threshold=.86,
            samples=80, bluff=0., pot_fraction=.95)
    for index, floor in enumerate((.43, .47, .51, .55)):
        hard[f"value_trap_{index+1}"] = dict(idea="value_trap", preflop_floor=floor,
            call_margin=.06, raise_threshold=.72, reraise_threshold=.80, samples=80, bluff=0.)
    for index, bait in enumerate((40, 75, 100)):
        hard[f"reraise_bait_{index+1}"] = dict(idea="reraise_bait", bait_length=bait,
            call_floor=.32, call_margin=.02, reraise_threshold=.58, samples=64, pot_fraction=.9)
    for index, bait in enumerate((15, 20, 28)):
        hard[f"detector_bait_{index+1}"] = dict(idea="detector_bait", bait_length=bait,
            call_margin=.06, raise_threshold=.63, samples=64, bluff=0.)
    for index, window in enumerate((50, 75, 125)):
        hard[f"gear_cycle_{index+1}"] = dict(idea="gear_cycle", switch_every=window,
            call_margin=.05, raise_threshold=.64, samples=64, range_bias=.8)
    hard.update(range_counter=dict(idea="range_reader", preflop_floor=.46, call_margin=.09,
                                   raise_threshold=.69, range_bias=1., samples=96),
                river_pressure=dict(idea="street_pressure", call_margin=.06, raise_threshold=.65,
                                    bluff=.02, samples=80),
                pot_value_counter=dict(idea="balanced", call_margin=.10, raise_threshold=.64,
                                       reraise_threshold=.67, samples=96, bluff=0., pot_fraction=1.))
    for tier, variants in (("F", fair), ("H", hard)):
        for index, (name, params) in enumerate(variants.items()):
            params = dict(seed=100+index if tier == "F" else 200+index, **params)
            idea = f"{tier} tier {name}: {params.get('idea', 'balanced')} with fixed declared thresholds."
            script = wrapper(name, params, idea)
            config["opponents"][name] = dict(script=str(script.relative_to(ROOT)), tier=tier, idea=idea)
            training.append(name)
    old = dict(config["holdout"], consumed_by="Reserved but not scored during rejected timing audit")
    config.setdefault("holdout_history", []).append(old)
    holdouts = {}
    for i, (name, params) in enumerate((
        ("holdout3_station", dict(call_floor=.24, call_margin=-.11, raise_threshold=.74)),
        ("holdout3_nit", dict(preflop_floor=.56, call_margin=.09, raise_threshold=.70)),
        ("holdout3_tag", dict(preflop_floor=.51, call_margin=.04, raise_threshold=.61, bluff=.04)),
        ("holdout3_lag", dict(call_margin=-.02, raise_threshold=.54, bluff=.19, pot_fraction=.35)),
        ("holdout3_odds", dict(call_margin=.045, raise_threshold=.66, bluff=.025)),
        ("holdout3_equity", dict(call_margin=.02, raise_threshold=.63, samples=80, range_bias=.7)),
        ("holdout3_cycle", dict(idea="gear_cycle", switch_every=135, call_margin=.04, samples=64)),
        ("holdout3_folder", dict(idea="folder_lock", preflop_floor=.57, call_floor=.54, call_margin=.075, samples=80)),
        ("holdout3_trap", dict(idea="value_trap", preflop_floor=.49, call_margin=.065, samples=80)),
        ("holdout3_reraiser", dict(idea="reraise_bait", bait_length=90, call_margin=.035, samples=80)),
    )):
        params = dict(seed=400+i, **params)
        script = wrapper(name, params, "Unscored holdout policy fixed before validation.")
        holdouts[name] = dict(script=str(script.relative_to(ROOT)), tier="H" if i >= 7 else "F")
    # The eleventh is a unique counter idea, written separately; the twelfth
    # is a frozen evolved reserve registered by evolve_adversary.py.
    unique = "holdout3_blocker_counter"
    holdouts[unique] = dict(script=f"league/opponents/{unique}.py", tier="H", unique_idea=True)
    config["opponents"].update(holdouts)
    config["holdout"] = dict(generation=3, opponents=list(holdouts), seeds=list(range(401,421)),
                              requires_milestone=True, evolved_reserve_pending=True)
    config["schema_version"] = 2
    config["tiers"] = {"F": dict(description="Fair population style variants"),
                       "H": dict(description="Jester-specific fair counters and permanent hall of fame", maximum_champion_edge=.75),
                       "C": dict(description="Unfair test-only guardrail, excluded from points")}
    config["screening"] = dict(opponents=["baseline_random", "calling_station", "pot_maniac", "pot_odds_bot",
        "anti_maniac", "tag_value", "lag_pot", "odds_tight", "folder_lock_2", "folder_lock_4",
        "value_trap_2", "reraise_bait_2", "gear_cycle_2", "range_counter"])
    config["champions"]["tier"] = "H"
    config["cheaters"] = dict(seeds=[41,42,43], excluded_from_points=True)
    for name in ("oracle_full", "oracle_partial", "board_oracle", "unlimited_compute", "oracle_counter"):
        config["opponents"][name] = dict(script=f"league/opponents/{name}.py", tier="C",
            time_bank_seconds=1e9 if name == "unlimited_compute" else 8.)
    config["declared_at"] = datetime.now(timezone.utc).isoformat()
    refresh_hashes(config)
    path.write_text(json.dumps(config,indent=2)+"\n")
    return config


if __name__ == "__main__":
    print(len(build()["training"]["opponents"]), "registered training servers plus past champions")
