"""Large reachable-state legality sweep plus edge/property tests of a frozen champion."""

import argparse
import json
from pathlib import Path
from random import Random
import sys

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
from tools.run_snapshot import resolve_snapshot


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--champion",default="v2")
    parser.add_argument("--hands",type=int,default=2000)
    parser.add_argument("--seed",default="safety-sweep")
    parser.add_argument("--json",type=Path,required=True)
    args=parser.parse_args()
    if args.hands<1000:parser.error("Large sweep requires at least 1,000 hands")
    source=resolve_snapshot(args.champion)
    sys.path.insert(0,str(source))
    import agent
    from game import Action,AgentConfig,Game,make_deal
    assert Path(agent.__file__).parent==source
    rng=Random(args.seed);memory={};decisions=0
    for index in range(args.hands):
        hand=index%1000
        if hand==0:agent.new_half(AgentConfig(),memory)
        seat=index%2
        game=Game(make_deal(args.seed,index),index%2,hand_index=hand)
        while not game.is_terminal:
            obs=game.observation(game.to_act)
            if game.to_act==seat:
                action=agent.choose_action(obs,memory);decisions+=1
                assert action in obs.legal_actions
                assert obs.to_call or action!=Action.FOLD
                assert memory["safety_errors"]==0
            else:action=rng.choice(obs.legal_actions)
            game.apply(action)
        agent.on_hand_end(game.hand_result(seat),memory)
        assert memory["safety_errors"]==0
    import pytest
    code=pytest.main([str(ROOT/"tests/test_edge_cases.py"),str(ROOT/"tests/test_properties.py"),
                      "-q","-o",f"pythonpath={source}"])
    report=dict(champion=args.champion,hands=args.hands,decisions=decisions,
                safety_errors=0,edge_property_exit_code=code,
                source=str(source),passed=code==0)
    args.json.write_text(json.dumps(report,indent=2)+"\n")
    print(json.dumps(report))
    return code


if __name__=="__main__":raise SystemExit(main())
