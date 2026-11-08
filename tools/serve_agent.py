"""Local runner adapter: unchanged submission endpoints plus stderr telemetry.

Does not inspect the opponent, judge state or unrevealed cards. Run only for
tests; tournament agent.py does not import this observer.
"""

from collections import Counter, deque
import json
import os
from pathlib import Path
import sys
from time import perf_counter

sys.path.insert(0, os.environ.get("BOT_SOURCE_ROOT", str(Path(__file__).resolve().parents[1])))
import agent
from game import RAISE_ACTIONS

original_new_half = agent.new_half
original_choose = agent.choose_action
original_end = agent.on_hand_end
diagnostics = {}
decision_seconds = deque(maxlen=32768)


def new_half(config, memory):
    original_new_half(config, memory)
    if os.environ.get("JESTER_TIMING_PROBE") == "1":
        # Keep frozen runtime imports first; the observer itself is test-only.
        sys.path.append(str(Path(__file__).resolve().parents[1]))
        from tools.timing_probe import probe_type
        memory["bot"].timing = probe_type(type(memory["bot"].timing))()
    mode = os.environ.get("JESTER_TIMING_MODE", "configured")
    if mode == "disabled":
        memory["bot"].timing.enabled = False
    elif mode == "enabled":
        memory["bot"].timing.enabled = True
        memory["bot"].timing.settings["nudges"] = True
    elif mode == "observe":
        memory["bot"].timing.settings["nudges"] = False
    if os.environ.get("JESTER_FORCE_FAKE_GATE") == "1":
        timing = memory["bot"].timing
        def forced_gate(hand):
            if hand < timing.settings["cautious_start"]:
                return
            timing.gate = "open"
            timing.gate_hand = timing.gate_hand if timing.gate_hand is not None else hand
            timing.gate_reason = "test-only deliberately false gate; not validated evidence"
            timing.signal_kind = "forced_invalid"
            timing.models = {(street, action, cross): {"weak": (.040, .025), "strong": (.0006, .001)}
                             for street in range(4) for action in range(4) for cross in (False, True)}
        timing._gate = forced_gate
    diagnostics.clear()
    decision_seconds.clear()
    diagnostics.update(exploit_decisions=0, exploit_raises=0, gear_decisions=Counter())


def choose(obs, memory):
    started = perf_counter()
    action = original_choose(obs, memory)
    decision_seconds.append(perf_counter()-started)
    state = memory["bot"]
    diagnostics["gear_decisions"][state.gear] += 1
    if state.opponent.exploit_checkfold:
        diagnostics["exploit_decisions"] += 1
        diagnostics["exploit_raises"] += action in RAISE_ACTIONS
    return action


def end(result, memory):
    original_end(result, memory)
    state = memory["bot"]
    if state.hands_played % 25 == 0 or state.hands_played == state.config.num_hands:
        timing = state.timing
        report = {
            "hands": state.hands_played, "final": state.hands_played == state.config.num_hands,
            "gear": state.gear, "transitions": state.selector.transitions,
            "gear_net_bb": dict(state.opponent.whole.net_bb_by_gear),
            "gear_hands": dict(state.opponent.whole.hands_by_gear),
            "opponent_events": dict(state.opponent.whole.events),
            "safety_errors": memory["safety_errors"],
            "governor_seconds": state.governor.total_seconds,
            "governor_reductions": state.governor.reductions,
            "decision_p99_ms": (sorted(decision_seconds)[min(len(decision_seconds)-1, int(len(decision_seconds)*.99))]*1000
                                if state.hands_played == state.config.num_hands and decision_seconds else None),
            "gate": timing.gate, "gate_hand": timing.gate_hand, "gate_reason": timing.gate_reason,
            "timing_labels": len(timing.labelled_hands), "timing_gaps": timing.gap_counts,
            "nudges": timing.nudged_decisions, "lowered_k": timing.lowered_k_decisions,
            "bank_estimate": timing.bank_estimate, **diagnostics,
        }
        print("BOT_DIAGNOSTICS " + json.dumps(report), file=sys.stderr, flush=True)
        if report["final"] and os.environ.get("JESTER_TIMING_PROBE") == "1":
            print("TIMING_AUDIT " + json.dumps(timing.audit_report()), file=sys.stderr, flush=True)


agent.new_half, agent.choose_action, agent.on_hand_end = new_half, choose, end

if __name__ == "__main__":
    agent.uvicorn.run(agent.app, host="127.0.0.1", port=int(os.environ["PORT"]),
                      log_level="warning", access_log=False)
