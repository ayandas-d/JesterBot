# Task 5: passive phased timing

Validated on 2026-11-07 with Python 3.12.16 in `.venv` on macOS, building on
Task 4 commit `8d67548`. The active implementation is `PhasedTiming` in
`bot/timing.py`; the older `Timing` class is retained only for the archived
strategy and its tests. No dependencies, engine files, baseline bots,
server plumbing or agent code outside the permitted markers changed.

## Measurements and labels

`choose_action` captures `time.monotonic()` on entry and at the end of its
reply preparation. The next request gap excludes our own processing since
the previous reply; separately timed result callbacks are also subtracted.
Serialization and judge/network overhead remain part of the measured gap.
This is a passive proxy, not direct access to the opponent's clock. There
are no sleeps, opponent connections, probes or network inspection.

The Task 4 opponent model supplies cumulative opponent action counts from
histories and completed results, including otherwise unseen terminal
responses. The timing layer checks the prior history prefix and intervening
hand indices before accepting a gap. Zero-action gaps update median overhead
baselines; exactly-one-action gaps supply clean samples. Multiple-action
gaps contribute to the known action total but not clean latency samples.
Incomplete histories, missing results, clock reversals and gaps over one
second are discarded. Same-hand and cross-hand baselines are separate,
each retaining the last 128 samples.

Clean samples use context `(opponent street, action, hand-boundary flag)`.
The most recent within-hand sample is linked to the revealed final Omaha
category at showdown. A terminal clean sample first measured on the next
hand can also link to the completed hand's stored category. Each hand
contributes at most one label, preventing repeated decisions from inflating
the evidence count. No-showdown hands supply no strength labels. Categories
describe the revealed final hand, not exact equity on an earlier street.

## Phases, gate and policy effects

All phase boundaries, sample requirements, gate thresholds, nudge size and
time-bank/detector settings are in `bot/timing.py:CONFIG`.

- **0–299:** measure and accumulate evidence only. Neither policy parameters
  nor detector K can change, even if a candidate model already fits.
- **300–699:** evaluate the gate once sufficient evidence exists. Require
  at least 30 distinct labelled hands in a context and eight matching
  baseline samples. Strength groups are weak (high card through two pair),
  medium (straight/trips), and strong (full house or better).
- Each strength group is split into two disjoint, alternating sample sets.
  A contrast needs at least five examples per group in each set, the same
  direction in both sets, at least a 1 ms mean difference, and a difference
  exceeding 4.5 standard errors in both sets. This catches non-monotonic
  tells such as medium hands being slower than both weak and strong hands.
- A failed gate stays closed for the rest of the half. Insufficient evidence
  remains pending until hand 700, then closes. Accepted models are frozen;
  later evidence cannot reopen a failed gate.
- An accepted context can multiply weak-hand bluff frequency by 1.10 for
  predicted weakness or 0.90 for predicted strength. Medium, out-of-range,
  unsupported or ambiguous timing predictions are neutral. In particular,
  overlapping weak/strong clusters do not identify weakness just because
  medium hands have different timing. Equity and pot-odds floors are intact.
- **700–999:** estimate cumulative opponent thinking from clean gap sums
  minus baseline overhead, then extrapolate the clean mean to the total
  known opponent actions. With an **open gate**, at least 30 baseline-backed
  clean samples and an estimate of at least 6.5 s, lower K from 15 to 8.
  The behavioral detector must still accumulate those check/fold actions;
  one paid call or raise resets it immediately.

The user explicitly selected **all timing effects off after gate failure**.
The time-bank estimate can still be recorded, but cannot lower K while the
gate is pending or closed. Bank estimates depend on clean samples being
representative and can include residual judge noise; they are not a claim
that the opponent has actually exhausted its clock.

The timing layer uses no strategy RNG draws and does not change Monte Carlo
sample counts, equity, price floors or the existing global time governor.
All timing state and detector K reset on `new_half`.

## Tests and runtime

Full suite: **113 passed**, including **16 new timing tests**. One existing
Starlette/httpx deprecation warning remains. Tests use injected timestamps,
not sleeps or real-clock delay streams. They cover phase boundaries,
300-hand action/RNG equivalence with timing disabled, pure noise and
permanent gate failure, an injected medium-hand tell, opposite-direction
confirmation rejection, insufficient evidence, overhead accuracy, callback
subtraction, cross-hand terminal actions and labels, multiple-action gaps,
missing/inconsistent histories, bank extrapolation, live K reduction,
bounded policy nudges, price floors, deduplication and full half reset.

Synthetic timing work measured 1.54 us p50 / 2.17 us p99 for baseline
maintenance. A conservative measurement charging two clean-stream requests,
their label callback and gate/policy checks to one decision measured
14.37 us p99. Both are below the 50 us per-decision target.

`tools/profile_timing.py` compares 1,000 hands against the same random
opponent trajectory with timing disabled and enabled, measuring bot work
only. Both runs made 3,585 decisions with the **same action-sequence SHA-256**,
zero errors and no governor reductions. Enabled timing closed its gate at
hand 336 with no confirmed signal; there were **zero bluff nudges and zero
K reductions** across the entire half.

| Measurement | Disabled | Enabled |
| --- | ---: | ---: |
| Whole-half bot work, including callbacks | 2.291 s | 2.352 s |
| Decision p99 | 1.681 ms | 1.711 ms |
| Timing-module mean per decision | 0.66 us | 4.85 us |
| Timing-module p99 per decision | 1.67 us | 13.75 us |

Passive measurement adds a small nonzero cost; the observed whole-half
difference was 61 ms (2.7%), with substantial headroom under the 4 s target.
These are single-run measurements, not a claim of precisely zero slowdown.

## Required RandomBot matches

Both duplicate matches used `BOT_SEED=7` and
`--require-win --max-thinking 4`. The 1,000-deal match exercises all phases.

| Deals per half | Deal seed | bb/deal | 95% confidence interval | Verdict |
| ---: | ---: | ---: | --- | --- |
| 200 | 7 | +6.4525 | [+3.446, +9.459] | AGENT1_WIN |
| 1,000 | 19 | +6.1585 | [+4.890, +7.427] | AGENT1_WIN |

All four halves had **zero errors, forfeits, timeouts and skipped calls**.
Judge-charged thinking was 0.13/0.12 s for the short match and 0.95/0.84 s
for the full match, all below the 4 s target. Every paired deal's return
matches Task 4 exactly. Full match wall time was 8.90 s versus Task 4's
8.73 s; neither run experienced timeout or time-bank pressure.

Structured reports, timing profiles and synthetic overhead measurements are
in `tools/task5_results.json`. Protected-file comparisons and
`git diff --check` passed. Docker build validation remains unverified from
earlier tasks; no tournament submission or deployment was performed.

```sh
BOT_SEED=7 .venv/bin/python -m pytest -q
BOT_SEED=7 .venv/bin/python tools/profile_timing.py --json /tmp/timing-profile.json
BOT_SEED=7 .venv/bin/python tools/run_local_match.py --deals 200 --seed 7 --require-win --max-thinking 4
BOT_SEED=7 .venv/bin/python tools/run_local_match.py --deals 1000 --seed 19 --require-win --max-thinking 4
```
