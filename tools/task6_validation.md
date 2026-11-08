# Task 6 validation

All 21 matches passed at 1,000 deals per half, using BOT_SEED=7 and deal seeds 7, 19 and 41. Full suite: **127 passed** (including the starter test_agent.py). No strategy configuration changes were needed.

| Opponent | Seed | Result | bb/deal | 95% CI | Our seconds h1/h2 |
| --- | ---: | --- | ---: | --- | --- |
| baseline_random | 7 | AGENT1_WIN | +7.1580 | [+5.853, +8.463] | 0.908/0.802 |
| baseline_random | 19 | AGENT1_WIN | +6.1585 | [+4.890, +7.427] | 0.796/0.863 |
| baseline_random | 41 | AGENT1_WIN | +5.6250 | [+4.345, +6.905] | 1.179/0.550 |
| nit_folder | 7 | AGENT1_WIN | +1.0740 | [+0.756, +1.392] | 0.075/0.032 |
| nit_folder | 19 | AGENT1_WIN | +1.4560 | [+1.290, +1.622] | 0.018/0.019 |
| nit_folder | 41 | AGENT1_WIN | +1.5640 | [+1.385, +1.743] | 0.029/0.018 |
| check_fold | 7 | AGENT1_WIN | +1.5000 | [+1.500, +1.500] | 0.000/0.000 |
| check_fold | 19 | AGENT1_WIN | +1.5000 | [+1.500, +1.500] | 0.000/0.000 |
| check_fold | 41 | AGENT1_WIN | +1.5000 | [+1.500, +1.500] | 0.003/0.000 |
| calling_station | 7 | AGENT1_WIN | +8.9520 | [+7.829, +10.075] | 0.529/1.005 |
| calling_station | 19 | AGENT1_WIN | +8.2300 | [+7.125, +9.335] | 1.084/1.061 |
| calling_station | 41 | AGENT1_WIN | +8.5570 | [+7.436, +9.678] | 0.271/1.078 |
| pot_maniac | 7 | AGENT1_WIN | +5.8665 | [+4.318, +7.415] | 1.041/1.095 |
| pot_maniac | 19 | AGENT1_WIN | +6.7840 | [+5.210, +8.358] | 0.710/1.119 |
| pot_maniac | 41 | AGENT1_WIN | +6.5655 | [+4.997, +8.134] | 1.133/0.959 |
| pot_odds_bot | 7 | CHOP | +0.9220 | [-0.156, +2.000] | 0.983/1.322 |
| pot_odds_bot | 19 | AGENT1_WIN | +2.1040 | [+1.047, +3.161] | 1.045/1.053 |
| pot_odds_bot | 41 | AGENT1_WIN | +2.1665 | [+1.070, +3.263] | 1.011/1.124 |
| slow_tell | 7 | CHOP | +0.5855 | [-0.507, +1.678] | 0.913/1.353 |
| slow_tell | 19 | CHOP | -0.2150 | [-1.363, +0.933] | 1.198/1.437 |
| slow_tell | 41 | CHOP | +0.4025 | [-0.640, +1.445] | 1.720/3.374 |

All opponents and our bot had zero judge errors, timeouts, skipped calls and forfeits. Both players stayed below 4 seconds of judge-charged thinking per half. Internal safety-fallback counts were also zero.

Every calling-station half switched out of MANIAC. Every check-fold half recorded active detector raises. The +1.5 bb/deal check-fold result is the maximum against its specified policy: we collect the small blind as the big blind and the big blind as the button, across the duplicate pair. The acceptance threshold is +1.4 bb/deal.

The slow_tell gate was closed in all six halves. The opponent adds up to 3 ms on medium Monte Carlo equity, once per hand, with a 1.2-second total sleep fund and a pace guard. This does not guarantee a reliable relationship to its final showdown category within the same action context; the gate correctly remains conservative. Its results were all CHOP, as required. Only this test opponent sleeps.

The six new bots copy the baseline HTTP plumbing and read PORT from the environment. Their equity helper is independent of our bot and uses no private engine state. They were not weakened or retuned after observing match results. Calling station checks/calls 99% and half-raises 1% when legal; nit continues facing a bet only with at least 70% estimated equity; pot maniac and check-fold implement their specified deterministic rules. The competent and slow opponents raise at 60% equity and otherwise respect pot odds.

tools/run_matches.py launches isolated servers, invokes the unchanged judge with optional --logs, retains logs on failure, prints results and faults, checks both players and collects our diagnostics. The tools/serve_agent.py observer is test-only and is never imported by the submission. All processes it owns are terminated on normal exit, failure, timeout, Ctrl-C or SIGTERM; stubborn processes are killed after a grace period. Tests cover legality, HTTP contracts, sleep budgeting, independent equity, acceptance predicates and cleanup.

Structured results and per-half diagnostics: tools/task6_results.json. Full judge histories, stderr diagnostics and judge stdout remain at /tmp/heads-up-task6-initial/.

Reproduce:

```sh
BOT_SEED=7 .venv/bin/python -m pytest -q
BOT_SEED=7 .venv/bin/python tools/run_matches.py --deals 1000 --seeds 7 19 41 --logs --output /tmp/task6-matches
```

The separate required 200-deal RandomBot regression (seed 7) also won: +6.4525 bb/deal, zero errors/forfeits/timeouts. Protected files are unchanged and git diff --check passed.
