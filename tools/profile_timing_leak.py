"""Measure conditional own-equity/decision-latency association, without sleeps.

Each observation comes from Game. Public work is held fixed within a street;
all independent reference equities are computed first, then measurement order
is shuffled to avoid prewarming one particular hand immediately before timing.
Fresh half state and a nonbinding governor isolate private-card effects from
phase/age/budget effects. Whole-half drift is covered by separate benchmarks.
"""

import argparse
import json
from math import sqrt
from pathlib import Path
from random import Random
from statistics import mean, median
import sys
from time import perf_counter_ns

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import agent
from bot.equity import equity
from bot.preflop import preflop_strength
from game import Action, AgentConfig, Game, Street, make_deal


def ranks(values):
    order = sorted(range(len(values)), key=values.__getitem__)
    result = [0.0] * len(values)
    start = 0
    while start < len(order):
        end = start + 1
        while end < len(order) and values[order[end]] == values[order[start]]:
            end += 1
        for i in range(start, end):
            result[order[i]] = (start + end - 1) / 2
        start = end
    return result


def correlation(left, right):
    ml, mr = mean(left), mean(right)
    den = sqrt(sum((v - ml) ** 2 for v in left) * sum((v - mr) ** 2 for v in right))
    return sum((a - ml) * (b - mr) for a, b in zip(left, right)) / den if den else 0.0


def profile(per_street=250, deal_seed="timing-leak-2026"):
    reports = {}
    for street in Street:
        records, prepared = [], []
        for i in range(per_street):
            game = Game(make_deal(deal_seed, i), 0, hand_index=0)
            while game.street != street:
                game.apply(Action.CHECK_CALL)
            obs = game.observation(game.to_act)
            reference = (preflop_strength(obs.hole_cards) if street == Street.PREFLOP else
                         equity(obs.hole_cards, obs.board, Random(983 + i), samples=128))
            prepared.append((obs, reference))
        Random(985 + int(street)).shuffle(prepared)
        for obs, reference in prepared:
            memory = {}
            agent.new_half(AgentConfig(), memory)
            memory["bot"].governor.budget_seconds = 1_000_000
            started = perf_counter_ns()
            action = agent.choose_action(obs, memory)
            elapsed = (perf_counter_ns() - started) / 1e6
            assert action in obs.legal_actions and memory["safety_errors"] == 0
            records.append([reference, elapsed])
        strengths, times = zip(*records)
        sr, tr = ranks(strengths), ranks(times)
        rho = correlation(sr, tr)
        rng = Random(984)
        shuffled = list(tr)
        null = []
        for _ in range(199):
            rng.shuffle(shuffled)
            null.append(abs(correlation(sr, shuffled)))
        by_strength = sorted(records)
        tail = max(1, len(records) // 4)
        low = median(v[1] for v in by_strength[:tail])
        high = median(v[1] for v in by_strength[-tail:])
        reports[street.name] = {"n": len(records), "spearman_rho": rho,
                                "permutation_two_sided_p": (1 + sum(v >= abs(rho) for v in null)) / 200,
                                "median_ms": median(times), "p99_ms": sorted(times)[int(.99 * len(times))],
                                "high_minus_low_quartile_median_us": (high - low) * 1000,
                                "records_strength_ms": records}
    return {"design": __doc__, "per_street": per_street, "deal_seed": deal_seed, "streets": reports}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--per-street", type=int, default=250)
    parser.add_argument("--deal-seed", default="timing-leak-2026")
    parser.add_argument("--json", type=Path, default=Path("/tmp/jester-timing-leak.json"))
    args = parser.parse_args()
    if args.per_street < 20:
        parser.error("use at least 20 observations per street")
    result = profile(args.per_street, args.deal_seed)
    args.json.write_text(json.dumps(result, indent=2) + "\n")
    print(json.dumps({k: {n: v for n, v in r.items() if n != "records_strength_ms"}
                      for k, r in result["streets"].items()}, indent=2))


if __name__ == "__main__":
    main()
