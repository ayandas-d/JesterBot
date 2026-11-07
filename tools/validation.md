# Jester validation

Validated on macOS with the repository's Python 3.12 virtual environment on
2026-11-07. No dependencies were added. Only the permitted agent section and
new files under `bot/`, `tests/`, and `tools/` were changed. The team and bot
names are assigned inside that section as Brootal / Jester.

## Checks

- `.venv/bin/python -m pytest -q`: 31 passed. One existing server-stack
  deprecation warning about Starlette/httpx; dependency pins are unchanged.
- `.venv/bin/python tools/profile_bot.py`: 1,000 hands each against random,
  calling and pot-raising policies. Decision plus result-callback time was
  1.3602 s, 1.8536 s and 1.2279 s respectively. Corresponding p99 decision
  latency was 0.837 ms, 0.897 ms and 1.021 ms. Zero internal safety fallbacks.
  These timings exclude initial imports and evaluator warmup.
- `.venv/bin/python tools/run_local_match.py --deals 200 --seed 7`:
  `AGENT1_WIN`, +9.035 bb/deal, 95% CI [+5.950, +12.120]. Zero errors,
  forfeits or exhausted time banks in either half. Charged thinking time:
  0.04 s / 0.02 s.
- `git diff --check` passed. Byte comparisons confirmed all protected engine,
  test and requirements files, and everything outside the agent edit markers,
  match the starter commit.
- `bash tools/check_build.sh` could not run its build: Docker is unavailable
  in this environment. Container size, Linux startup and container smoke tests
  remain unverified. Run the build check on the committed code before submission.

## Additional duplicate matches

Each match used 1,000 deals per half (2,000 hands), seed 19, and completed with
zero errors, forfeits or time-bank exhaustion. These ran before the identity
assignment and the one-sample-per-hand/context timing training cap; the final
200-deal match above ran after those changes.

| Opponent | bb/deal | 95% confidence interval | Verdict |
| --- | ---: | --- | --- |
| RandomBot | +7.482 | [+6.105, +8.860] | Win |
| CallingStation | +4.960 | [+4.392, +5.528] | Win |
| AlwaysPot | +6.024 | [+4.422, +7.626] | Win |

Across these matches the maximum judge-charged thinking time was 1.44 s per
half. The bot deliberately seeds fresh private random streams each half, so
repeating a deal seed reproduces cards, not necessarily actions or results.
These baseline results do not establish performance against tournament bots.

## Strategy and limits

The preflop score is a heuristic. Postflop equity is against uniform random
opponent hands, using 24/32/48 samples on flop/turn/river; policy adjustments
for selective aggression are heuristic rather than a learned range model.
All samples respect blockers and exactly two hole plus three board cards,
using the engine's read-only five-card lookup table.

The opening gear mixes frequent raises. An 80-hand rolling opponent model
switches to value, counter-aggression, balanced or pressure gears with
hysteresis. Six consecutive observed folds to our raises enable cheap steals;
any observed defense revokes the detector. This identifies behavior, not the
underlying reason (a tight opponent, exhaustion and forfeiture look alike).

Timing uses local request gaps only, restricted to one opposing action within
the same hand and street. It excludes our decision computation and cross-hand
result processing. Preflop/river samples are labeled only after a revealed
opponent hand, with at most one sample per hand/context. Early training and a
separate temporal validation window must both pass conservative correlation
tests before a tell can change equity, by at most two percentage points.
Showdown selection and transport noise remain limitations. Late latency-drop
detection additionally requires behavioral fold evidence and is diagnostic;
timing alone never activates repeated steals. The timing edge was unit-tested
with synthetic signals and is not claimed to be demonstrated by baseline wins.

All learning and random streams live in the half's memory dictionary. Every
entry point catches internal failures; action failures or illegal returns
fall back to CHECK_CALL. `memory["safety_errors"]` counts these failures so
offline profiling also catches bugs that the judge cannot see.

The engine and evaluator agree with the pasted rule specifications. The PDF's
`python test_agent.py` instruction does not collect pytest tests; use the
`python -m pytest -q` command from the pasted request instead.
