# Final submission-prep validation

Validated 2026-11-07 on macOS with Python 3.12.16. Runtime strategy and requirements were unchanged from Task 6 commit 35f8e5a. No config tuning was necessary.

## Final checks

- Full pytest: **127 passed**, including all **12 test_agent.py tests**, with no failures or skipped tests. The existing Starlette/httpx deprecation warning remains.
- Final complete match suite: **21/21 passed**, 1,000 deals per half and seeds 7/19/41. Our bot and every opponent had zero errors, forfeits, timeouts and skipped calls; both stayed below 4 seconds of judge-charged thinking per half.
- All calling-station halves switched out of MANIAC. All check-fold halves activated the detector and earned the maximum +1.5 bb/deal. The timing gate stayed closed in all six slow-tell halves; no signal was forced through the gate.
- Doubled Monte Carlo samples (80/80/144), with governor reductions disabled: random **5.903 s**, always-call **6.612 s**, pot-maniac **6.281 s** per 1,000-hand half. All under 8 s, zero errors. Longest decision was 17.16 ms, below the sampling cap. This is a computation-cost proxy for a slower machine, not a guarantee for every VM.
- Peak process RSS during the audit: **99.1 MiB**, far below 4 GB. All 13 imported project source files were already tracked. Runtime source imports total 83,016 bytes.
- Audit hooks blocked outbound networking, subprocess execution, and writes/mutations outside /tmp throughout import and 3,000 engine hands. There were **zero attempted forbidden operations and zero runtime file writes**, even inside /tmp.
- Bytecode writes were disabled, matching PYTHONDONTWRITEBYTECODE=1 in the supplied base Dockerfile. The final match suite also inherited that setting.
- Root requirements remain exactly fastapi==0.156.1 and uvicorn==0.54.0. No dev packages, torch, or new dependencies were added.
- Added a Docker allowlist: 15 source/requirements files, **90,524 bytes**. The virtualenv, .git, tests, logs, reports and caches are excluded. This is source payload size, not a measured built-image layer size.
- Added .gitignore and removed one accidentally tracked generated .pyc; no source file was removed. Added STRATEGY.md and a repeatable hardening tool.
- Docker is not installed on this machine, so the actual Linux container build/smoke test and added image-layer size remain unverified. The supplied Dockerfiles were inspected but not changed.

## Final matrix

| Opponent | Seed | Result | bb/deal | 95% CI | Our seconds h1/h2 |
| --- | ---: | --- | ---: | --- | --- |
| baseline_random | 7 | AGENT1_WIN | +7.1580 | [+5.853, +8.463] | 1.545/0.846 |
| baseline_random | 19 | AGENT1_WIN | +6.2330 | [+4.938, +7.528] | 1.172/1.981 |
| baseline_random | 41 | AGENT1_WIN | +6.2255 | [+4.999, +7.452] | 1.967/1.499 |
| nit_folder | 7 | AGENT1_WIN | +1.1350 | [+0.854, +1.416] | 0.061/0.062 |
| nit_folder | 19 | AGENT1_WIN | +1.4560 | [+1.290, +1.622] | 0.038/0.035 |
| nit_folder | 41 | AGENT1_WIN | +1.5640 | [+1.385, +1.743] | 0.072/0.044 |
| check_fold | 7 | AGENT1_WIN | +1.5000 | [+1.500, +1.500] | 0.001/0.008 |
| check_fold | 19 | AGENT1_WIN | +1.5000 | [+1.500, +1.500] | 0.001/0.008 |
| check_fold | 41 | AGENT1_WIN | +1.5000 | [+1.500, +1.500] | 0.001/0.000 |
| calling_station | 7 | AGENT1_WIN | +8.0190 | [+6.992, +9.046] | 0.523/0.703 |
| calling_station | 19 | AGENT1_WIN | +8.1330 | [+7.040, +9.226] | 0.364/1.005 |
| calling_station | 41 | AGENT1_WIN | +8.4050 | [+7.356, +9.454] | 0.685/0.789 |
| pot_maniac | 7 | AGENT1_WIN | +6.1810 | [+4.608, +7.754] | 0.899/1.044 |
| pot_maniac | 19 | AGENT1_WIN | +5.7945 | [+4.216, +7.373] | 1.334/0.778 |
| pot_maniac | 41 | AGENT1_WIN | +6.4755 | [+4.917, +8.034] | 1.688/1.451 |
| pot_odds_bot | 7 | CHOP | -0.0775 | [-1.241, +1.086] | 1.688/1.872 |
| pot_odds_bot | 19 | CHOP | -0.5300 | [-1.558, +0.498] | 2.089/1.535 |
| pot_odds_bot | 41 | CHOP | -0.1990 | [-1.327, +0.929] | 1.847/2.258 |
| slow_tell | 7 | AGENT1_WIN | +1.1570 | [+0.217, +2.097] | 2.313/2.480 |
| slow_tell | 19 | CHOP | +0.3765 | [-0.791, +1.544] | 1.691/1.831 |
| slow_tell | 41 | CHOP | +0.4740 | [-0.583, +1.531] | 1.773/1.908 |

Clock-based governors can change sample counts under different machine load, so seeded results can differ between runs. These are the final measured results; the initial passing matrix is preserved in tools/task6_results.json.

Structured final results and hardening evidence are in tools/task7_results.json. Complete judge --logs histories and server diagnostics remain under /tmp/heads-up-task7-final-matches/.

## Reproduce

```sh
PYTHONDONTWRITEBYTECODE=1 BOT_SEED=7 .venv/bin/python -m pytest -q
BOT_SEED=7 .venv/bin/python -B tools/harden_submission.py
PYTHONDONTWRITEBYTECODE=1 BOT_SEED=7 .venv/bin/python tools/run_matches.py --deals 1000 --seeds 7 19 41 --logs --output /tmp/final-matches
```

## Publication

Local validation is complete. At preparation time origin still points to the organizer starter repository, https://github.com/tamu-datathon-org/heads-up-bundle. The team submission repository URL (or confirmation that this origin is intentional) was requested before pushing. A local commit SHA is not a submitted or remotely verified SHA until the push succeeds.

The final separate 200-deal RandomBot regression (seed 7) also passed: AGENT1_WIN, +6.4525 bb/deal, no errors/forfeits/timeouts. Protected-source checks and git diff --check passed.
