# Improvement log

Each entry uses the team’s format below. Record exact commands, measured
results and the gate that decided acceptance. For a baseline, omit weakness,
change and tests-added fields; use N/A for the previous score. Never substitute
training results for holdout results. CI means a 95% confidence interval over
duplicate-pair bb returns. Benchmark p99 is distinguished from judge thinking
time per half. Intentional opponent faults are reported separately.

```text
## Iteration <n> — <date> — ACCEPTED as vN | REJECTED | BASELINE
- Champion / commit: <vN, full SHA>
- Commands: <exact league/test commands, incl. seeds and deal counts>
- Weakness targeted: <matchup + numbers>          (skip for baseline)
- Change: <files / config keys changed, and why>  (skip for baseline)
- Tests added: <names>                             (skip for baseline)
- Tournament points: <before → after>
- bb/deal: <before → after>; head-to-head vs champion: <bb/deal ± CI>
- Safety: <errors, forfeits, max think time per half, p99 decision time>
- Holdout (if run): <points, notes>
- Decision: <accept / reject, and which gate decided it>
- Next idea: <what to try next>
```

## Iteration 0 — 2026-11-08 — BASELINE

- Champion / commit: v1, `486507685c326ee891397c03adb2af8321fbc201`;
  annotated tag `champion-v1` points to this source commit. The subsequent
  infrastructure commit contains the frozen snapshot and this log. Live
  `agent.py`, `bot/`, engine files and runtime requirements are unchanged.
- Commands: executed from the repository root:

  ```sh
  .venv/bin/python -B tools/snapshot.py --tag
  BOT_SEED=7 .venv/bin/python -m pytest -q --junitxml=/tmp/league-fast-tests-final.xml -o junit_family=xunit1
  BOT_SEED=7 .venv/bin/python -B tools/league.py --quick --challenger v1 --jobs 2 --label baseline-v1-quick
  BOT_SEED=7 .venv/bin/python -B tools/league.py --full --challenger v1 --jobs 2 --label baseline-v1-full
  BOT_SEED=7 .venv/bin/python -B tools/league.py --challenger v1 --head-to-head v1 --seeds 1 2 3 --deals 300 --jobs 2 --label baseline-v1-h2h
  BOT_SEED=7 .venv/bin/python -B tools/profile_timing.py --json /tmp/league-v1-profile.json
  BOT_SEED=7 .venv/bin/python -B tools/run_local_match.py --deals 200 --seed 7 --require-win --max-thinking 4 --json /tmp/league-setup-random-200.json
  ```

  Quick: 300 deals per match, seeds 1, 2, 3, 14 training opponents including v1,
  42 matches. Full: 1,000 deals per match, seeds 1, 2, 3, 4, 5, 6, 7, 8, 9,
  10, 11, 12, 13, 14, 15, 16, 17, 18, 19, 20, the same 14 opponents,
  280 matches / 560,000 hands. All matches use the real duplicate judge.
  Fast tests: 167 passed in 16.39 s, including `test_agent.py`; two slow
  tests deselected. Full training was run directly; holdouts remain reserved.
- Tournament points: N/A → **242.5 / 280** full (205 wins, 75 chops,
  zero losses); quick **34.5 / 42**. Intentional crashy forfeits contribute
  their actual judge-awarded points.
- bb/deal: N/A → **+2.780288**, CI **[+2.719112, +2.841463]** full;
  quick **+2.461905**, CI **[+2.159929, +2.763881]**.
  Head-to-head vs champion: v1 versus v1, **0.000 ± 0.000** over the
  dedicated three-seed / 900-deal check. Full self-play across 20 seeds:
  **−0.008400**, CI **[−0.055691, +0.038891]**; wall-clock budget adaptation
  can cause two independently running copies to diverge. The weakest
  external matchup is slow_tell: **+0.120900**, CI **[−0.116286, +0.358086]**,
  **10.5 / 20** points. The runner’s overall worst matchup includes v1 itself.
- Safety: **0 our errors, 0 our forfeits, 0 unexpected safety violations**
  in full and quick runs. Full maximum thinking time per half: **2.046240 s**
  for both our bot and either player (limit 4 s). The deliberate crashy
  opponent forfeited all 40 halves in its 20 matches; no other opponent
  forfeited. Separate 1,000-hand timing-enabled benchmark: **0.951209 ms p99**
  decision time, **1.757556 s** cumulative bot work; timing-module mean
  **4.068 µs**, p99 **9.375 µs**. No-signal enabled/disabled runs produced
  identical actions. State after 1,000 simulated hands serialized to
  **81,762 bytes**; fixed-probe median moved from **0.679 ms** to **0.714 ms**.
  Required 200-deal random regression: **AGENT1_WIN**, **+6.4525 bb/deal**,
  CI **[+3.446, +9.459]**, no errors or forfeits. Check-fold exploitation
  activated in every check_fold and slow_starter half in the full league.
- Holdout (if run): not run. gto_ish, adaptive_counter, erratic and seeds
  101–110 remain reserved for explicitly named milestones. Their basic HTTP
  contracts were unit-tested without scoring holdout matches.
- Decision: **BASELINE recorded; infrastructure acceptance gates passed**:
  isolated v1 snapshot/tag, fast suite under 60 s, complete quick/full league
  runs without unexpected safety violations, head-to-head CLI, regression
  and timing checks. No strategy candidate was accepted or rejected.
  Compact results, source hashes and diagnostics summaries are preserved in
  [league/BASELINE.json](league/BASELINE.json); raw JSON stays gitignored
  under `league/results/`, with paths and checksums in the compact artifact.
- Next idea: investigate slow_tell first: +0.121 bb/deal with a CI spanning
  zero, and its timing gate stayed closed in all 40 halves. Diagnose signal
  availability and policy performance before proposing a targeted change;
  keep holdout scores untouched during tuning.
