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

## Iteration 2 (2026-11-08) — REJECTED

- Champion / commit: v2, `c81268ec9317ed64f2728e3f3070a004ab16a443`.
- Weakness targeted: the timing gate never opened in the accepted 560-half
  training evaluation, and its time-bank estimate used a different clock from
  the judge. slow_tell's median estimate was 3.347 s versus 1.195 s charged.
- Diagnosis: final-category/current-equity label mismatch, fragmented and
  underpowered early gate decisions, previous-hand hint attribution, omitted
  final gaps, per-request-grace mismatch and discarded pre-calibration work.
  The audit and individual failing regressions are in `tools/timing_audit.md`.
- Change: audited passive timing measurement and diagnostics; planned-look
  work-pattern/action association tests; conservative default-off strength
  nudges; semantics-preserving fixed-work band/bluff calculations. All poker
  thresholds and gear parameters stayed unchanged. Strong-pattern detection
  does not itself establish a private-strength model.
- Tests added: timing audit/isolation/clock/false-gate tests, dose-response
  and statistical-control tests, unchanged-v2 probability equivalence, and
  source-hand/late-baseline regression cases. Fast suite: **198 passed in
  31.01 s**. The final gate prototype detected **40/40** live positive halves
  and **0/60** negatives. Hand-700 clock errors were at most **13.87%** over
  20 known-clock halves. Failed prototypes and their raw records are retained.
- Results: fresh expanded v2 reference **262/300 points**, **+2.852877 bb/deal**.
  Challenger evaluation was intentionally stopped after **214/300** completed
  matches when the safety gate failed; no full-league acceptance comparison,
  head-to-head gate or holdout gate was claimed. No new champion was tagged.
- Safety: **REJECTED**, maximum Jester charged half **4.251613 s > 4 s**
  (slow_tell, seed 3, half 1), despite **3.338083 s** in its choose governor.
  The timing-disabled fake-tell comparison also reached **4.225189 s** while
  its governor recorded **3.072345 s**. There were no Jester HTTP errors,
  timeouts or forfeits in those cases. The discrepancy exposes missing
  callback accounting and insufficient headroom for charged work outside
  choose_action; it is not excused by the absence of a tournament forfeit.
- Holdout (if run): not run. Fresh generation-2 opponents/seeds were reserved
  without looking at their scores; validation remains pending.
- Decision: reject on the priority-one safety gate. Experimental runtime
  files were reverted to verified v2 bytes, with the rejected implementation
  archived in `tools/phase2_candidates/rejected_iteration2/` and the revert
  recorded in `tools/phase2_rejection_2.json`. The audited measurement code
  remains the experimental base for the next narrowly focused safety fix;
  it is not a promoted champion. v2 snapshots/tags remain unchanged.
- Commands and raw evidence: `phase2-configured-full` raw JSON under
  `league/results/20261108T112013486950Z_phase2-configured-full.json` and
  `phase2-final-fake-disabled` under
  `league/results/20261108T111820886547Z_phase2-final-fake-disabled.json`.
  Exact options, source hashes and completed match records are embedded in
  each file. The configured run used:

  ```sh
  JESTER_DIAG=1 BOT_SEED=7 .venv/bin/python -B tools/league.py --full --jobs 2 --timing-mode configured --label phase2-configured-full
  ```

- Tier results (F / H / C): legacy fair field only; expanded Hard/cheater
  tiers have not been built or evaluated yet. Adversaries added: none.
- Next idea: count all result-callback work and reserve 1.5 s of the 4 s
  ceiling for unobserved request costs. A regression-first experiment must
  then repeat safety and performance gates. This changes only the time-budget
  accounting/headroom relative to the failed timing candidate. The newly
  supplied expansion, oracle/evolution and continuous-runner tasks follow
  the timing-audit commit; they do not alter the current comparison field.

## Iteration 3 (2026-11-08) — REJECTED

- Champion / commit: v2, `c81268ec9317ed64f2728e3f3070a004ab16a443`.
- Weakness targeted: iteration 2 exceeded the 4 s charged half ceiling while
  its choose-only governor understated work by 0.9–1.2 s.
- Diagnosis: callbacks were unaccounted, and the internal budget left too
  little room for framework/request work. Passive instrumentation can also
  alter sample-governor decisions, even with zero policy nudges.
- Change: relative to the unchanged audited timing base, account callback
  work and reserve 1.5 s external headroom (2.5 s internal budget). No poker
  threshold or gear change. Correct the test runner's clock scope: Jester
  ≤4 s; deliberately delayed controls inside their own 8 s bank. Raw older
  summaries are retained, and neither prior Jester safety failure is waived.
- Tests added: `tests/test_safety_budget.py`, clock-scope regression in
  `tests/test_league_infrastructure.py`, matched-field/safety comparison tests.
  Before/after regressions were demonstrated. The candidate's final fast
  suite passed 222 tests in 19.43 s, including preliminary independent league
  tooling tests. Profile p99 ≤1.383 ms; maximum offline half 1.8442 s.
- Results: the six-case 1,000-deal budget regression won 6/6 with zero safety
  issues. Positive timing controls opened 38/40 (95%); negative controls 0/60;
  known-clock hand-700 error ≤18.86%. **Fake-tell guardrail failed:** default-off
  instrumented play versus disabled play −0.33125 bb/deal, 95% CI
  [−0.60198, −0.06052], below the predefined −0.25 lower-CI bound. Actual
  distribution nudges were zero. The difference can arise through timing
  cost, global sample reduction and subsequent RNG trajectory changes.
- Tournament points / bb/deal: on the **partial matched 246-match subset**, v2
  228.0 → challenger 221.5 points; +3.436600 → +2.952561 bb/deal. The run was
  stopped after rejection, so this is not a completed full-league result.
- Safety: zero Jester errors/timeouts/forfeits in completed candidate matches;
  partial-training maximum charged half 1.703904 s. No safety failure is hidden
  by the performance rejection. The 200-deal random regression won at
  +6.4525 bb/deal with zero safety issues.
- Holdout (if run): not run; no reserved generation-2 scores were observed.
  Head-to-head and full enabled/disabled training were not completed after
  the guardrail failure. They are not claimed as passes.
- Decision: reject. Preserve the complete experimental source and tests on
  `experiment/phase2-timing-audit`, restore live source to champion v2, and
  retain audit/results on main. No new champion/tag. The audit feature remains
  unpromoted; default-off nudges exist only in that experiment.
- Commands: `JESTER_DIAG=1 BOT_SEED=7 .venv/bin/python -B tools/league.py --full --jobs 2 --timing-mode configured --label phase2-budget-configured-full`;
  `BOT_SEED=7 .venv/bin/python -B tools/timing_controls.py --run positive negative known fake fake-disabled --jobs 2`
  (the negative/known/fake/fake-disabled sequence resumed after the clock-scope
  bug, preserving the original positive raw record). Controls use 1,000 deals:
  positive/fake seeds 1–20; negative seeds 1–10 against three opponents; known
  seeds 1–5 against two opponents. Final tests:
  `BOT_SEED=7 .venv/bin/python -B -m pytest -q --junitxml=/tmp/phase2-rejected-final-fast.xml`.
  Profile: `BOT_SEED=7 .venv/bin/python -B tools/profile_bot.py`.
  Random regression: `BOT_SEED=7 .venv/bin/python -B tools/league.py --opponents baseline_random --seeds 7 --deals 200 --label phase2-rejected-regression`.
  Exact paths/hashes/assessments: `tools/phase2_iteration3_results.json`;
  detailed limitations and failed prototypes: `tools/timing_audit.md`.
- Tier results (F / H / C): old fair field only; expanded tiers pending.
- Adversaries added: independent test-only family/oracle scaffolds prepared,
  none registered in this comparison field and no hall-of-fame entry removed.
- Next idea: reduce timing instrumentation cost before another feature
  promotion attempt. First complete the user's independently requested
  expanded league and continuous runner around frozen v2.

## Infrastructure checkpoint (2026-11-08) — STOPPED AT USER REQUEST

- Champion / commit: v2, `c81268ec9317ed64f2728e3f3070a004ab16a443`.
  Live agent.py and bot/ remain byte-identical to this verified snapshot.
- Added: 62 training opponents including champions, 12 reserved holdouts,
  five separate test-only oracle opponents; tier scoring, source hashes,
  immutable evolved adversaries, caching, sequential screening, timing
  telemetry, and continuous-runner infrastructure. No runtime dependency added.
- Tests: 296 fast tests passed in 36.75 s, including test_agent.py. Three slow
  integration tests remain excluded by default. All declared opponents passed
  HTTP/source-manifest smoke tests; copied-judge scoring and real-judge byte
  integrity are tested.
- Search: six random candidates, one six-child genetic generation, then
  1,000-deal confirmation on three fresh training seeds. Published permanent
  entries evolved_e0001/e0002 (training), evolved_e0003 (reserved holdout).
- Expanded baseline: deliberately stopped at the user's wrap-up request,
  464/1,240 completed matches, zero safety violations, maximum Jester charged
  half 3.629846 s. This is a PARTIAL run, not an accepted expanded baseline.
  Raw evidence: league/results/20261108T165209985078Z_expanded-training-baseline.json.
- Hard design pilot: eight 300-deal matches across four counters, aggregate
  Jester -0.790833 bb/deal; no safety issues. This does not establish the full
  Tier H strength criterion. Five oracle variants passed 20-deal smoke tests;
  their full 1,000-deal guardrail remains pending. Holdout remains unscored.
- Continuous runner: source, restart/seed/alert/STOP/rotation unit tests are
  implemented. Two live cycles and a live STOP verification have NOT run.
- Raw historical JSON was compressed losslessly, with byte verification and
  transparent archive readers; no hall-of-fame source or champion was removed.
- Decision: commit the tested infrastructure checkpoint without changing or
  promoting the bot. No new champion tagged. The latest user instruction is
  to stop Devpost work and commit bot-related changes on main.
- Resume: BOT_SEED=7 .venv/bin/python -B tools/league.py --challenger v2 --full --cache --jobs 4 --label expanded-training-resume
  Then complete full Hard/holdout/oracle validation before claiming Part 2
  done; complete live continuous validation before claiming Part 3 done.
