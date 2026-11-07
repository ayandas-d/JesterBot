"""Benchmark 10,000 individual warm omaha_score calls on varied legal cards.

Run with the repository interpreter: .venv/bin/python tools/benchmark_evaluator.py
Dealing and lookup warmup are outside the timed region. Individual timings
include the normal overhead of the two perf_counter_ns clock reads.
"""

import json
from pathlib import Path
from random import Random
from statistics import median
import sys
from time import perf_counter_ns

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from evaluator import omaha_score, warmup


def benchmark():
    rng = Random(240)
    deals = [rng.sample(range(36), 10) for _ in range(10_000)]
    cases = [(tuple(cards[:5]), tuple(cards[5:])) for cards in deals]
    warmup()
    for hole, board in cases[:200]:
        omaha_score(hole, board)
    timings = []
    for hole, board in cases:
        start = perf_counter_ns()
        omaha_score(hole, board)
        timings.append(perf_counter_ns() - start)
    return {"calls": len(timings), "median_ns": median(timings),
            "median_us": median(timings) / 1000, "python": sys.version.split()[0]}


if __name__ == "__main__":
    print(json.dumps(benchmark()))
