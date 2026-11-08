"""Test-only Jester observer for oracle_counter, writing only an explicit /tmp channel.

It sends no requests and exposes no new HTTP endpoint. The copied oracle judge
reads the channel. The submission has no reference to this adapter.
"""

import json
import os
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from tools import serve_agent

agent = serve_agent.agent
original_choose = agent.choose_action
original_end = agent.on_hand_end
original_new_half = agent.new_half
destination = Path(os.environ["ORACLE_STATE_PATH"]).resolve()
if not destination.is_relative_to(Path("/tmp").resolve()):
    raise ValueError("The oracle observer channel must be under /tmp")


def write_state(hand, memory):
    state = memory["bot"]
    model=state.opponent
    def stats(value):
        return {key:dict(getattr(value,key)) for key in ("events","net_bb_by_gear","hands_by_gear",
                 "actions_by_gear","showdown_categories","showdown_raises")}
    data = dict(hand_index=hand, gear=state.gear,
                events=dict(model.rolling.events),whole_events=dict(model.whole.events),
                whole=stats(model.whole),rolling=stats(model.rolling),
                detector=dict(k=model.detector.k,streak=model.detector.streak),
                current_hand=(dict(index=model.current.index,events=dict(model.current.stats.events),
                                   pending_raise=model.current.pending_raise,street=int(model.current.street),
                                   observed_actions=len(model.current.history)) if model.current else None),
                selector=dict(folder=state.selector.folder,candidate=state.selector.candidate,
                              confirmations=state.selector.confirmations,last_switch=state.selector.last_switch),
                exploit_checkfold=model.exploit_checkfold,transitions=state.selector.transitions)
    temporary = destination.with_suffix(".new")
    temporary.write_text(json.dumps(data))
    temporary.replace(destination)


def choose(obs, memory):
    result = original_choose(obs, memory)
    write_state(obs.hand_index, memory)
    return result


def end(result, memory):
    original_end(result, memory)
    write_state(result.hand_index, memory)


def new_half(config,memory):
    original_new_half(config,memory)
    write_state(-1,memory)


agent.choose_action, agent.on_hand_end, agent.new_half = choose, end, new_half

if __name__ == "__main__":
    agent.uvicorn.run(agent.app, host="127.0.0.1", port=int(os.environ["PORT"]),
                      log_level="warning", access_log=False)
