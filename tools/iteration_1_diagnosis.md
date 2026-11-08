# Iteration 1 preparation — 2026-11-08

Status: ACCEPTED as v2 after every gate passed. Challenger changes only
`reraise_rate` from 0.30 to 0.35. See IMPROVEMENT_LOG.md and
tools/iteration_1_results.json for the complete acceptance evidence.

Champion: v1, source commit `486507685c326ee891397c03adb2af8321fbc201`.
Verified all live runtime files against the frozen manifest and verified the
logged full-result checksum before reusing the baseline: 242.5/280 points,
+2.7802875 bb/deal, zero unexpected safety violations, maximum our half
thinking time 2.046240 seconds. Intentional crashy opponent faults remain
separately classified as in the baseline infrastructure.

## Measurement

Weakest external matchup: slow_tell, +0.120900 bb/deal, 95% CI
[-0.116286, +0.358086], 10.5/20 points. Self-play is excluded when choosing
an external weakness. Close individual chops include tight_aggressive seeds
8 and 3 (CI lower bounds -0.009209 and -0.009215), anti_maniac seed 5
(-0.030537), and pot_odds_bot seed 16 (-0.032100). These single-seed results
are exploratory, not evidence that a proposed change will generalize.

## Logged diagnostic match

```sh
BOT_SEED=7 .venv/bin/python -B tools/league.py --challenger v1 --opponents slow_tell --seeds 1 --deals 1000 --jobs 1 --logs --label iteration-1-diagnosis
```

Raw result: `league/results/20261108T080523349878Z_iteration-1-diagnosis.json`.
Server/judge logs: `/tmp/league-iteration-1-diagnosis-3ep_kl2e/slow_tell-0/`.
Result: CHOP, -0.0405 bb/deal, CI [-1.014802, +0.933802]; zero errors,
forfeits or safety violations, maximum our half thinking time about 0.585 s.

Both halves switched MANIAC → VALUE at hand 50, then VALUE → TRAP at hand
150 because of frequent re-raises. Combined hand-log returns by active gear:

| Gear | Hands | Net bb | Showdown net bb | Non-showdown net bb |
| --- | ---: | ---: | ---: | ---: |
| MANIAC | 100 | -322.0 | -524.0 | +202.0 |
| VALUE | 200 | +445.0 | +507.0 | -62.0 |
| TRAP | 1,700 | -163.5 | +573.0 | -736.5 |

The timing gate closed at hand 300 in both halves with reason "no confirmed
signal" and zero nudges. The opponent injected delays in 321 and 320 hands,
using approximately 1.2 seconds of sleep per half. A closed gate therefore
does not establish the absence of an injected tell; it establishes that the
current detector did not confirm one.

## Candidate hypothesis

Investigate whether the re-raise-frequency threshold sends us into TRAP too
readily against selective value raisers. A focused experiment could raise
`bot/gears.py`'s `reraise_rate`, preserving VALUE longer. Expected benefit:
more value betting against this opponent. Risk: delayed trapping against
actual aggressive re-raisers. The gear totals above are observational and
confounded by cards and hand index; they do not prove VALUE caused the better
returns. Pin the intended switching behavior with a test before changing it,
then apply every requested gate on the same training opponents/seeds.

Exact replay of public observations through the opponent model found rolling
re-raise evidence at hands 125/150 of 47/147 and 36/111 in half 1, and 47/156
and 37/123 in half 2 (30.08–32.43%). Choose 0.35 as a modest increase above
these observations, leaving other thresholds untouched. Before editing the
default, six behavior tests passed: the logged windows cause a switch at
0.30 and preserve VALUE at 0.35; 65% re-raising still triggers TRAP at both
settings. These tests remain valid even if the experiment is rejected.

Other future investigations: pot_odds_bot's close chops, and whether clean
timing samples align with the street/hand strength producing slow_tell's
delay. Do not loosen the timing gate solely to force this test opponent to
trigger it.
