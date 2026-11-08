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

## Iteration 1 (2026-11-08) — ACCEPTED as v2

- Champion / commit: v1, `486507685c326ee891397c03adb2af8321fbc201`, before
  the experiment. Accepted v2 source commit:
  `c81268ec9317ed64f2728e3f3070a004ab16a443`, tagged `champion-v2`. The
  following packaging commit stores `league/champions/v2/META.json` and the
  independent frozen runtime. [Loop rules](tools/LOOP_RULES.md) preserve the user's
  Part 4 and acceptance protocol for future sessions.
- Weakness targeted: slow_tell, **10.5/20 points**, **+0.120900 bb/deal**,
  CI **[-0.116286, +0.358086]** in the unchanged v1 training baseline.
- Diagnosis: a logged 1,000-deal seed-1 match switched VALUE → TRAP at hand
  150 in both halves. Replaying the public histories through the opponent
  model gave rolling re-raise rates **30.08–32.43%** at hands 125/150, barely
  above the old 30% cutoff. VALUE earned **+445 bb over 200 hands**; TRAP
  lost **163.5 bb over 1,700 hands**, including **-736.5 bb** in hands ending
  without showdown. These observational totals suggested a hypothesis; they
  were not treated as a causal comparison. Details and replay counts are in
  [the diagnosis](tools/iteration_1_diagnosis.md).
- Change: only `bot/gears.py`, `CONFIG["reraise_rate"]`: **0.30 → 0.35**.
  Hypothesis: preserve VALUE longer against moderate re-raisers. Risk:
  switching later to TRAP against genuinely aggressive opponents. No policy
  frequencies, equity work, timing gate, opponents, seeds or dependencies
  changed. Opponent source hashes and league config match the baseline.
- Tests added: `test_logged_moderate_reraises_preserve_value_with_higher_threshold`
  and `test_high_reraises_still_trigger_trap_with_both_thresholds` in
  `tests/test_gear_thresholds.py` (six parametrized cases). Before changing
  the default, all six passed with explicit settings: actual logged windows
  trigger TRAP at 0.30 and retain VALUE at 0.35, while 65% re-raising triggers
  TRAP for both. They pin the relevant behavioral distinction without merely
  asserting a config literal. This was a tuning experiment, not a bug fix;
  `tests/test_regressions.py` remains empty. Final fast suite: **173 passed,
  two slow tests deselected, in 16.53 seconds** (under the 60-second limit).
  Frozen v2 separately passed all **12** unchanged `test_agent.py` tests in
  an isolated directory, and its own HTTP snapshot server won the 200-deal
  random smoke match with no faults. All local imports resolve inside v2.
- Results: training points **242.5/280 → 248/280**, mean bb/deal
  **+2.780288 → +3.018275** (challenger CI **[+2.956622, +3.079928]**).
  **216 wins, 64 chops, zero losses**; no v1 WIN became a LOSS on any
  opponent/seed. Dedicated head-to-head: **-0.018300 ± 0.056355 bb/deal**,
  CI **[-0.074655, +0.038055]**, over **20 seeds × 1,000 deals**. The CI is
  not entirely negative, so the specified head-to-head gate passed.
  Target slow_tell improved **10.5 → 12.5 points**, **+0.121 → +0.958 bb/deal**;
  pot_odds_bot **11.5 → 15 points**, tight_aggressive **19 → 20 points**,
  bluff_heavy **+4.954 → +6.825 bb/deal**. Tradeoffs: anti_maniac points
  **15 → 14.5** and slow_starter **16.5 → 15.5**, with no strategic losses.
  Safety: **0 challenger errors/forfeits**, no unexpected safety violations
  across **330 candidate matches** (280 training, 20 head-to-head, 30 holdout);
  maximum thinking time **1.900951 s per half**; worst benchmark p99
  **1.664 ms** across random/call/pot 1,000-hand profiles. Intentional crashy
  opponent faults remain separately reported; all 40 of its halves forfeit
  by design. Required 200-deal random regression: **AGENT1_WIN**, **+6.4525
  bb/deal**, no errors/forfeits. Frozen v1 independently passed all 12
  `test_agent.py` tests, and its full safety baseline remains valid.
- Holdout (if run): promotion-only milestone `iteration-1-promotion`, same
  three opponents and seeds **101–110**, **1,000 deals per match**, 30 matches
  per version. Points **26/30 → 26.5/30**, bb/deal **+1.363000 → +1.506750**;
  no safety violations or win-to-loss regressions. Aggregate points passed
  the specified holdout gate. Individual points: gto_ish **9 → 8**,
  adaptive_counter **8 → 8.5**, erratic **9 → 10**. No parameter changed
  after seeing holdout results; use these scores only for validation.
- Decision: **accept**, all five gates passed: safety, head-to-head,
  training points/mean, no WIN → LOSS, and holdout points. Compact evidence,
  exact source hashes, summaries and raw-result checksums are preserved in
  [iteration_1_results.json](tools/iteration_1_results.json). Raw match logs
  remain gitignored. This session stops after one fully evaluated iteration
  to reserve the remaining budget for champion packaging and the requested
  push. No experiments were rejected.
- Commands: run from the repository root with fixed `BOT_SEED=7`:

  ```sh
  BOT_SEED=7 .venv/bin/python -B tools/league.py --challenger v1 --opponents slow_tell --seeds 1 --deals 1000 --jobs 1 --logs --label iteration-1-diagnosis
  BOT_SEED=7 .venv/bin/python -m pytest -q tests/test_gear_thresholds.py
  BOT_SEED=7 .venv/bin/python -m pytest -q --junitxml=/tmp/iteration-1-fast.xml -o junit_family=xunit1
  BOT_SEED=7 .venv/bin/python -B tools/profile_bot.py > /tmp/iteration-1-profile.jsonl
  BOT_SEED=7 .venv/bin/python -B tools/league.py --head-to-head v1 --seeds 1 2 3 4 5 6 7 8 9 10 11 12 13 14 15 16 17 18 19 20 --deals 1000 --jobs 2 --label iteration-1-h2h
  BOT_SEED=7 .venv/bin/python -B tools/league.py --full --jobs 2 --label iteration-1-full
  BOT_SEED=7 .venv/bin/python -B tools/league.py --full --group holdout --milestone iteration-1-promotion --challenger v1 --jobs 2 --label iteration-1-holdout-v1
  BOT_SEED=7 .venv/bin/python -B tools/run_local_match.py --deals 200 --seed 7 --require-win --max-thinking 4 --json /tmp/iteration-1-random-200.json
  BOT_SEED=7 .venv/bin/python -B tools/league.py --full --group holdout --milestone iteration-1-promotion --jobs 2 --label iteration-1-holdout-challenger
  BOT_SEED=7 .venv/bin/python -m pytest -q --junitxml=/tmp/iteration-1-final-fast.xml -o junit_family=xunit1
  .venv/bin/python -B tools/snapshot.py --tag
  .venv/bin/python -B tools/run_snapshot.py v2 --inspect
  BOT_SEED=7 .venv/bin/python -B tools/league.py --challenger v2 --opponents baseline_random --seeds 7 --deals 200 --jobs 1 --label v2-snapshot-smoke
  ```

  Full training uses seeds 1–20, 14 opponents, 1,000 duplicate deals each.
  Full holdout uses seeds 101–110, three opponents, 1,000 deals each.
  Seed lists, config and source hashes are also embedded in the evidence.
- Next idea: first remeasure v2 against the expanded training field (v2 is
  now an automatically discovered opponent; 15 opponents × 20 seeds = 300
  matches, so do not compare its raw point total to 248/280). Then diagnose
  slow_starter's training-point tradeoff; investigate remaining close
  pot-odds-bot chops; and examine whether a confidence requirement on gear
  changes improves consistency. These ideas come from training evidence.
  If future tuning targets an observed holdout weakness, rotate holdout
  seeds and a bot before validation, as required by Part 4.
