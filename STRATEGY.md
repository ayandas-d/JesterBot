# Strategy and tuning

The active path is `agent.py` → `bot/fallback.py`; `bot/strategy.py` is an
archived implementation. Runtime identity is editable inside agent.py's
permitted section. All three callbacks have exception containment; invalid
or failed decisions fall back to CHECK_CALL and log only to stderr.

Preflop uses a cheap five-card heuristic: high pairs, suited aces, connectivity
and high cards help; redundant trips/quads and crowded suits hurt. Postflop
uses Monte Carlo against uniformly sampled legal opponent hands and runouts,
with the engine's exact two-hole/three-board Omaha evaluator. Ties count half.
Samples depend on street and the global half budget, never hand strength.
The governor targets 4 seconds and imposes a 30 ms per-decision sampling cap.

## Gears and behavioral adaptation

- **MANIAC:** opening gear; frequent mixed pot/half-pot raises, with a
  pot-odds floor when facing bets.
- **AGGRO:** strong-hand/draw aggression plus occasional weak-hand bluffs.
- **VALUE:** almost no bluffs; medium/strong value bets, usually larger.
- **TRAP:** more strong-hand checks/calls against re-raisers; re-raise the top.

The model tracks whole-half and last-100-hand response rates, showdown
categories versus aggression, and net bb by gear. Re-evaluate every 25 hands,
require 40 relevant events and two agreeing evaluations, and wait 75 hands
between switches. Frequent folders favor MANIAC; calling stations that punish
MANIAC favor VALUE; frequent re-raisers favor TRAP. Otherwise losses step
MANIAC down to AGGRO, then VALUE. Each half adds small seeded threshold jitter.

After 15 consecutive opponent free checks/folds, the check-fold detector
raises whenever legal, preferring HALF. One paid call or raise resets it.
Terminal opponent responses are reconstructed from public hand results.

## Passive timing

Hands 0–299 only gather evidence. Zero-opponent-action request gaps estimate
judge overhead; exactly-one-action gaps are clean samples. Our callback time
is subtracted, and hand boundaries are checked. At most one sample per hand
is linked to the opponent's revealed final category.

From hand 300, a gate requires 30 labelled hands in a matching context, enough
baseline samples, and a strong mean-time difference confirmed in two disjoint
sample groups. Accepted signals only multiply bluff frequency by 0.9 or 1.1;
they never change equity or price floors. Ambiguous predictions are neutral.
A failed gate disables **all** timing effects for the rest of the half.

From hand 700, an open gate and an estimated opponent bank usage above 6.5 s
can lower check-fold K to 8. This is an estimate, not access to the opponent's
clock. Behavioral confirmation is still required. The submission never sleeps
or contacts the opponent. Only `tests/bots/slow_tell.py` intentionally sleeps.

## Knobs and validation

| File | Knobs |
| --- | --- |
| `bot/policy.py:CONFIG` | Gear strength thresholds, frequencies, bet sizes, price margins, jitter |
| `bot/gears.py:CONFIG` | Switching evidence, cadence, cooldown and opponent-type thresholds |
| `bot/opponent.py:CONFIG` | Rolling window, check-fold K, weak-showdown category |
| `bot/timing.py:CONFIG` | Phase boundaries, gate evidence, nudge, bank threshold, endgame K |
| `bot/equity.py:SAMPLES` | Fixed flop/turn/river samples: 40/40/72 |
| `bot/governor.py` | Global budget and reduction logic |

Set `BOT_SEED` for reproducible strategy draws. A new half resets all state.
Keep runtime requirements to FastAPI/uvicorn; do not add torch (the base image
already supplies it). `.dockerignore` includes only runtime sources.

After tuning, run `BOT_SEED=7 .venv/bin/python -m pytest -q`, then
`BOT_SEED=7 .venv/bin/python tools/run_matches.py --logs --output /tmp/matches`.
Defaults are 1,000 duplicate deals and seeds 7/19/41. Inspect judge hand logs
and `BOT_DIAGNOSTICS` in the retained server logs. Tests and practice opponents
are excluded from the submission image. See `tools/task6_validation.md` for
the acceptance matrix and `tools/task7_validation.md` for final hardening.
