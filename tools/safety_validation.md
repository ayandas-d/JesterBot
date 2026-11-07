# Task 1: safety submission

Validated on 2026-11-07 using Python 3.12.16 in `.venv` on macOS. This is the
active simple safety policy; the earlier adaptive Jester code remains
available in commit `827529a` and is not imported by the live agent.
Task 0 recon is separately committed as `1726016`; its exact API inventory
and 10,000-call benchmark are in `tools/recon.md`.

## Implementation

- Identity inside the permitted section of `agent.py` is `TEAM_NAME_HERE` /
  `ManiacAdaptive`, as requested. The earlier starter assignments outside
  the edit markers are unchanged and overridden by these values.
- `bot/safety.py` wraps all three entry points. Exceptions are contained,
  action results must be an `Action` present in `obs.legal_actions`, and
  action failures return `CHECK_CALL`. Callback failures return normally.
  Error counts are retained in `memory["safety_errors"]`; diagnostics and
  tracebacks go to stderr only, even if the diagnostic stream itself fails.
- `bot/fallback.py` lazily initializes minimal per-half state, so decisions
  and hand results also work when `new_half` was never called. Calling
  `new_half` clears previous state and creates a fresh random generator.
- The active policy uses the existing cheap preflop heuristic and exactly
  24 postflop Monte Carlo samples on every decision, independent of strength.
  It raises strong hands, compares estimated strength with pot odds for
  calls, and otherwise checks for free or folds. It has no timing tells,
  adaptive gears or opponent model. Preflop strength is a heuristic rather
  than calibrated equity; random-opponent postflop equity is an estimate.
- No dependencies were added. Engine files, baseline bots, starter tests,
  server plumbing, and requirement pins match the preceding commit byte
  for byte. All agent edits are inside the permitted markers.

## Tests

`python -m pytest -q`: **46 passed**, with one existing Starlette/httpx
deprecation warning. `python -m pytest --collect-only -q tests`: **34
tests collected** from `tests/`; the other 12 are starter tests.

`tests/test_safety.py` includes:

- Legality checks at every decision along 2,500 real engine-generated hands,
  testing both seats and more than 10,000 real decision states. Independent
  legal action sequences cover every street, free checks, bets, raise caps,
  and an all-in opponent. No exceptions, illegal returns or internal safety
  fallbacks occurred.
- Injected policy exceptions and illegal enum/string/int/bool/None/object
  returns. Every case safely returns `CHECK_CALL` and logs to stderr.
- Initialization and result-callback failures, lazy memory initialization
  without `new_half`, diagnostic failures, and HTTP-level delivery of a
  failing callback together with a failing decision.
- Fixed postflop sample count and an explicit assertion that the live
  policy is the simple fallback, not the adaptive implementation.

The existing strategy tests still exercise the archived adaptive components
directly. Their live-agent safety/reset/identity assertions now target the
new safety submission.

## Required matches

Every full match below used 1,000 duplicate deals per half, for 2,000 hands.
All six halves had zero judge errors, zero forfeits, zero skipped calls and
no exhausted time banks. The highest charged thinking time was under 0.57 s,
comfortably within the 4 s target. Each run used the validation helper's
`--require-win --max-thinking 4` assertions.

| Seed | bb/deal | 95% confidence interval | Result |
| --- | ---: | --- | --- |
| 7 | +8.058 | [+6.773, +9.343] | `AGENT1_WIN` |
| 19 | +7.915 | [+6.565, +9.264] | `AGENT1_WIN` |
| 41 | +9.141 | [+7.813, +10.469] | `AGENT1_WIN` |

The additional required 200-deal match against RandomBot, seed 7, also
returned `AGENT1_WIN`: +7.645 bb/deal, 95% CI [+4.458, +10.832], zero errors,
forfeits or exhaustion, charged thinking time 0.05 s / 0.04 s.

Reproduce a full match with:

```sh
.venv/bin/python tools/run_local_match.py --deals 1000 --seed 7 --require-win --max-thinking 4
```

Structured score/fault/timing summaries are committed in
`tools/safety_match_results.json`. Actions are randomized, so repeated deal
seeds reproduce the cards but may produce different results. These baseline
wins are validation of the safety policy, not proof of a tournament edge.

## Performance and build status

`python tools/profile_bot.py` timed complete 1,000-hand offline runs,
including decision and callback computation, excluding startup/warmup:

| Opponent policy | Total thinking | p99 decision | Internal errors |
| --- | ---: | ---: | ---: |
| Random | 1.1295 s | 0.763 ms | 0 |
| Always call | 1.3855 s | 0.769 ms | 0 |
| Always pot | 0.9480 s | 0.708 ms | 0 |

`git diff --check` passed. `bash tools/check_build.sh` was attempted and
stopped with `Docker isn't running`. Container build, size and Linux smoke
validation remain unverified and must be completed before tournament
submission. No repository push or form submission was performed.
