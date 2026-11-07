# Task 3: randomized mixed policy

Validated on 2026-11-07 with Python 3.12.16 in `.venv` on macOS. This builds
on Task 2 commit `2955b63`. No dependencies were added. Byte comparisons
confirmed protected engine files, baseline bots, starter tests, dependency
pins and all agent code outside the allowed markers are unchanged.

## Policy configuration and state

`bot/policy.py` defines a single `CONFIG` dictionary containing the default
gear, all strength thresholds, price margins, raise/bluff probabilities,
size mixing, continuation frequencies, and the threshold jitter amplitude.
Every gear uses the same distribution-building algorithm:

- `MANIAC`: 98-99% raises when the price floor permits continuing; 78% of
  raises are pot-sized and 22% half-pot when both actions are available.
- `AGGRO`: 12% weak-hand bluffs, 68% raises in the medium-equity band
  (including live draws), and 91-97% strong/top raises. Calls require
  stronger equity margins when facing big bets or re-raises.
- `VALUE`: 0.5% weak-hand bluffs, 76% medium-strength value bets and 94-98%
  strong/top raises. Conditional pot-size frequency is 84%.
- `TRAP`: 18% raises and 82% check/calls with strong non-top hands in free
  spots, but 92% raises with the very top range, including facing re-raises.

The stated base frequencies can be reduced by the gear's configured public
big-bet/re-raise multipliers. Each gear has separate preflop and postflop
strength thresholds because the preflop proxy uses a conservative scale.

Before assigning raise/call weights, the policy checks the call price.
MANIAC may continue only at equity >= pot odds minus 0.035. Other gears
use their configured nonnegative margins. Hands far below this floor fold
with probability one, including the very largest raises. The guard is
not jittered. No gear folds when checking is free.

`action_probabilities` returns a nonnegative normalized dictionary with
exactly the observation's legal actions as keys. Unavailable raises get no
mass; if only one size is legal, it receives the entire raise probability.
`sample_action` draws from that distribution using the existing half RNG.
It skips zero-weight actions even at cumulative floating-point boundaries.

State begins in `MANIAC`. Each half draws one offset per gear/street group,
bounded by +/-0.012, and applies it to that group's three band thresholds.
Offsets stay fixed during the half and preserve threshold ordering. Config
is copied, never mutated. `BOT_SEED` reproduces jitter and mixing; an
unseeded half uses the existing OS-entropy seeding. A fresh half resets the
gear, jitter, random stream and time governor. `state.gear` is available for
the subsequent opponent-model layer; this task introduces no automatic
gear switching.

The active runtime adapter in `bot/fallback.py` still computes strength
with the Task 2 estimator and time governor, then delegates action selection
to the mixed policy. Existing exception safety and stderr diagnostics remain
in place.

## Tests and frequency measurements

Full suite: **78 passed**, including all 20 new policy tests. One existing
Starlette/httpx deprecation warning remains.

Task 1's independent legal trajectories now live in `tests/fuzz_states.py`
and are shared by the safety and policy tests. They generate **15,781 real
decision states from 2,500 hands**, covering both seats, every street, free
checks, facing bets, raise caps and all-in opponents. All four gears were
checked for legal sampled actions, finite nonnegative weights summing to
one, and zero free-check fold probability across these states.

`tools/profile_policy.py` samples 4,000 raise-legal observations from that
pool. Strength is estimated from their actual cards, with the preflop proxy
or a fixed 24-sample postflop Monte Carlo estimate. The denominator includes
all sampled raise-legal observations, including ones rejected by the price
floor. Separately, every gear sees the same 4,000 weak-equity free-check
observations with strength set to 0.10.

| Gear | Sampled overall raises | Weak-equity free-check raises |
| --- | ---: | ---: |
| MANIAC | 96.600% | 98.200% |
| AGGRO | 47.175% | 13.125% |
| VALUE | 35.825% | 0.675% |
| TRAP | 13.900% | 2.300% |

MANIAC's expected raise rate from its probabilities was 96.6035%, also above
the 80% target. The equity-floor tests found zero calls or raises for hands
far below pot odds while facing big bets, for every gear. The suite also
checks the re-raise floor across jitter seeds, TRAP slowplay/top raises,
AGGRO medium-equity aggression, VALUE size selection, empirical sampling
against its advertised distribution, half reset, bounded seeded jitter,
single-size restrictions and invalid-strength rejection.

## Required matches and runtime

Both matches used `BOT_SEED=7`, `--require-win --max-thinking 4`, and both
duplicate halves. All four halves had zero errors, forfeits, skipped calls
or exhausted time banks.

| Deals per half | Deal seed | bb/deal | 95% confidence interval | Verdict |
| ---: | ---: | ---: | --- | --- |
| 1,000 | 19 | +11.785 | [+9.990, +13.580] | `AGENT1_WIN` |
| 200 | 7 | +11.200 | [+7.390, +15.010] | `AGENT1_WIN` |

Judge-charged thinking was 0.52 / 0.48 s for the full match and 0.10 / 0.09 s
for the 200-deal regression. Full-half offline profiles (including callbacks,
excluding game simulation and startup) also passed:

| Opponent policy | Thinking for 1,000 hands | p99 decision | Internal errors |
| --- | ---: | ---: | ---: |
| Random | 0.9971 s | 1.734 ms | 0 |
| Always call | 3.1407 s | 1.842 ms | 0 |
| Always pot | 0.1218 s | 1.258 ms | 0 |

These profiles measure runtime, not profitability against each policy.
The win requirement was validated against RandomBot. Action mix and runtime
can vary with random seed, opponent behavior and time-governor reductions.

Reproduce with:

```sh
BOT_SEED=7 .venv/bin/python -m pytest -q
.venv/bin/python tools/profile_policy.py
BOT_SEED=7 .venv/bin/python tools/profile_bot.py
BOT_SEED=7 .venv/bin/python tools/run_local_match.py --deals 1000 --seed 19 --require-win --max-thinking 4
BOT_SEED=7 .venv/bin/python tools/run_local_match.py --deals 200 --seed 7 --require-win --max-thinking 4
```

Structured scores, faults, runtime profiles and mixing measurements are in
`tools/task3_results.json`. `git diff --check` passed. Docker build validation
remains unverified from earlier tasks; no push or form submission was made.
