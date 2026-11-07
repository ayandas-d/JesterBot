"""Offline whole-half CPU/latency check: .venv/bin/python tools/profile_bot.py."""

import json
from pathlib import Path
from random import Random
import sys
from time import perf_counter

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import agent
from game import Action, AgentConfig, Game, make_deal


def profile(opponent, seed, hands=1000):
    memory = {}
    agent.new_half(AgentConfig(num_hands=hands), memory)
    rng = Random(0)
    durations, callbacks = [], 0.0
    for i in range(hands):
        game = Game(make_deal(seed, i), i % 2, hand_index=i)
        seat = i % 2
        while not game.is_terminal:
            obs = game.observation(game.to_act)
            if game.to_act == seat:
                start = perf_counter()
                action = agent.choose_action(obs, memory)
                durations.append(perf_counter() - start)
            elif opponent == "random":
                action = rng.choice(obs.legal_actions)
            elif opponent == "call":
                action = Action.CHECK_CALL
            else:
                action = Action.RAISE_POT if Action.RAISE_POT in obs.legal_actions else Action.CHECK_CALL
            assert action in obs.legal_actions
            game.apply(action)
        start = perf_counter()
        agent.on_hand_end(game.hand_result(seat), memory)
        callbacks += perf_counter() - start
    ordered = sorted(durations)
    report = dict(opponent=opponent, hands=hands, decisions=len(durations),
                  seconds=round(sum(durations) + callbacks, 4),
                  p99_ms=round(ordered[int(len(ordered) * .99)] * 1000, 3),
                  max_ms=round(max(durations) * 1000, 3),
                  safety_errors=memory["safety_errors"], gear=memory["bot"].gear)
    print(json.dumps(report), flush=True)
    assert report["safety_errors"] == 0
    assert report["seconds"] <= 4 and report["p99_ms"] < 20, report


if __name__ == "__main__":
    for opponent in ("random", "call", "pot"):
        profile(opponent, "profile-7")
