# Task 2: hand strength engine

Validated on 2026-11-07 with Python 3.12.16 in the repository's `.venv` on
macOS. This builds on safety submission `1847c63`. All agent edits remain
inside the allowed markers. Engine files, server plumbing, baseline bots,
starter tests and dependency pins are unchanged. No dependencies were added.

## Engine and preflop score

`bot/equity.py` samples an opponent's five cards and the missing board cards
together without replacement from the unseen deck. It compares the engine's
actual `omaha_score` results; equal scores count as half a win. The estimate
is wins plus half-ties divided by completed trials, without prior shrinkage.
River hero evaluation is reused because its cards cannot change.

The Task 0 median was 15 microseconds per evaluator call. Two evaluations
per flop/turn sample plus dealing suggested 40 samples near 1-2 ms; one
opponent evaluation per river sample permits 72 samples. The default fixed
counts are **flop 40 / turn 40 / river 72**. There are no strength-based early
exits. Old mask helpers and the old `preflop_strength` import remain available
for compatibility with the archived strategy tests, but active simulations
call `omaha_score` directly.

The module-level `RNG` is a `random.Random` seeded from the literal string
in `BOT_SEED` when present, otherwise 32 bytes from `os.urandom`. Each new
half replaces this module RNG and stores its reference in half-local state.
Lazy initialization uses the same path. No previous-half random stream is
reused. Seeded replay is exact for the same sequence of requests, sample
counts and deadlines; wall-clock budget changes or deadline interruption
can change how many random draws are consumed.

`bot/preflop.py` exports `preflop_score`, normalized to [0, 1]. It rewards
high pairs, high cards, two-card suits, ace-suited combinations, connected
ranks and the A-6-7-8-9 wheel. It penalizes third/fourth rank copies and third
or later cards in a suit. The live policy uses the conservative proxy
`0.30 + 0.40 * preflop_score` to keep existing action thresholds on their
previous scale. Neither score is a calibrated preflop winning probability.

## Governor and deadline

`choose_action` uses `time.perf_counter` at entry and in `finally` so even
failed policy calls are charged to the half's `TimeGovernor`. State resets
on `new_half`. The governor targets 4 seconds, or 75% of a smaller configured
tournament bank. It projects cumulative decision time over the half using
public hand progress and keeps a 10% reserve.

When projected time exceeds the target it reduces one half-wide multiplier
for all street counts, with a 16-hand cooldown and an urgent-spending bypass.
It waits for 12 hands before ordinary adjustments to avoid overreacting to
the opening hand. Counts have a four-trial floor; scale never increases
within the half. No hand cards, equity, bet size or chosen action enter the
governor. Tight-budget tests confirm all street counts decrease together and
a new half restores their defaults.

Each decision passes a deadline of entry time plus 30 ms into the sampler.
Direct estimator calls also have a 30 ms default cap. The sampler checks the
clock before every trial and returns the completed-trial average, or neutral
0.5 if no trial completed. This is a cooperative cap: an individual engine
evaluation or operating-system scheduling pause cannot be preempted by
Python. Deadline interruption is the sole exception to fixed sample counts.

The governor measures decision computation, not HTTP overhead; the judge's
separate timing formula still applies. It is a pace controller, not a
real-time scheduling guarantee on arbitrary hardware.

## Tests and measurements

The full suite passes **58 tests**. The 12 Task 2 tests cover:

- The guide's straight rather than flush, river nuts above 0.99 and a dead
  river hand below 0.01, ties worth half, engine-evaluator calls and blockers.
- Seeded equity sequences and half replay, and OS entropy when unseeded.
- Preflop quality, ace-suited bonus, rank/suit dead-card penalties, score
  range and card-order/suit-renaming invariance.
- Equal work for strong/weak hands, global budget reductions and reset,
  deadline interruption, an already expired deadline, and failed-policy time.
- 1,000 real random observations with p50 below 2 ms, p99 below 20 ms and
  total below 4 seconds, plus another run with an artificially tight budget
  that demonstrably reduces sample counts.

Final standalone run, `BOT_SEED=7 python tools/profile_equity.py`:

| Decisions | p50 | p99 | Total | Internal errors |
| ---: | ---: | ---: | ---: | ---: |
| 1,000 | 0.8614 ms | 1.3790 ms | 0.696952 s | 0 |

Street medians: preflop 0.0068 ms, flop 1.0339 ms, turn 0.9358 ms,
river 0.7878 ms. A concurrent-load run also passed: p50 1.1135 ms,
p99 1.8959 ms, total 0.917735 s.

Final `BOT_SEED=7 python tools/profile_bot.py`, including callbacks but
excluding startup, warmed evaluator setup and game simulation:

| Opponent policy | Decisions in 1,000 hands | Thinking | p99 | Global reductions |
| --- | ---: | ---: | ---: | ---: |
| Random | 3,840 | 1.5970 s | 1.176 ms | 1 |
| Always call | 4,000 | 2.5947 s | 1.344 ms | 0 |
| Always pot | 3,887 | 1.6814 s | 1.268 ms | 0 |

All had zero safety fallbacks. Earlier concurrent-load full-half profiles
also passed; the slowest was 3.3098 s against always-call.

## Match results

Both RandomBot matches used `BOT_SEED=7` and the validation helper's
`--require-win --max-thinking 4` assertions. Each consists of both duplicate
halves. All halves had zero errors, forfeits or exhausted time banks.

| Deals per half | Deal seed | bb/deal | 95% confidence interval | Verdict |
| ---: | ---: | ---: | --- | --- |
| 200 | 7 | +7.492 | [+4.492, +10.493] | `AGENT1_WIN` |
| 1,000 | 19 | +8.902 | [+7.535, +10.268] | `AGENT1_WIN` |

Charged thinking time was 0.21 / 0.27 s for the required 200-deal match and
0.82 / 0.53 s for the full match. Different CPU load can alter the governor's
reductions and therefore actions even with fixed `BOT_SEED`.

Reproduce with:

```sh
BOT_SEED=7 .venv/bin/python -m pytest -q
BOT_SEED=7 .venv/bin/python tools/profile_equity.py
BOT_SEED=7 .venv/bin/python tools/profile_bot.py
BOT_SEED=7 .venv/bin/python tools/run_local_match.py --deals 200 --seed 7 --require-win --max-thinking 4
```

Structured profiles and judge score/fault summaries are in
`tools/task2_results.json`. `git diff --check` and byte comparisons of
protected files passed. Docker build validation remains unverified from
Task 1 because Docker is unavailable; no push or submission was performed.
