# Phase 2 timing audit — 2026-11-08

This initial audit was written before any implementation or strategy change.
Champion: v2, `c81268ec9317ed64f2728e3f3070a004ab16a443`. Measurements below
come from its accepted 280-match training evaluation (14 opponents, seeds
1–20, 1,000 duplicate deals); new measurements will be appended with commands
and provenance. Unknown quantities are explicitly pending, not assumed zero.

## Observable information and attribution

Jester observes its own choose_action entry and reply-preparation completion
times, normal observations/action histories and delivered HandResults. It
never observes opponent requests, private cards before showdown, their clock,
or judge internals. A reply-to-request gap combines our response serialization,
HTTP, judge work, opponent work and result-batch delivery. Our measured callback
work is subtracted, but framework parsing/serialization remains. An end-of-half
callback does not supply a new choose_action request, so the final reply-to-end
gap is currently never sampled. Same-hand and cross-hand baselines are separate.
Only zero-opponent-action gaps estimate overhead; exactly-one-action gaps are
clean; multiple-action gaps cannot identify individual think times.

## Existing evidence: never fired is accurate, never can fire is not established

All **560 halves** in the accepted v2 training run ended with a closed gate,
zero timing nudges and zero K reductions. The synthetic suite does demonstrate
an open gate under an injected 3 ms tell with balanced labels and tiny noise;
that is not a realistic live positive control.

| Opponent | Clean gaps/half, median | Labelled hands/half, min / median / max |
| --- | ---: | ---: |
| baseline_random | 2,533.5 | 372 / 396 / 420 |
| calling_station | 2,430.5 | 642 / 764 / 790 |
| nit_folder | 19 | 0 / 0 / 3 |
| pot_maniac | 2,820 | 528 / 562 / 583 |
| check_fold | 0 | 0 / 0 / 0 |
| slow_tell | 1,952.5 | 363 / 399 / 526 |
| pot_odds_bot | 1,997 | 374 / 397.5 / 463 |
| anti_maniac | 1,985.5 | 352 / 408.5 / 438 |
| tight_aggressive | 323.5 | 50 / 64 / 84 |
| loose_passive | 2,359.5 | 592 / 650.5 / 674 |
| bluff_heavy | 2,197.5 | 116 / 238.5 / 336 |
| slow_starter | 1,137 | 204 / 230 / 271 |
| crashy (intentional faults) | 716 | 136 / 150.5 / 182 |
| v1 | 2,632.5 | 645 / 683.5 / 726 |

Labels are plentiful against slow_tell in total, but this is not the gate's
effective sample size: it needs 30 labels within the same street/action/boundary
context, at least 10 per strength group (five in each confirmation split), and
eight matching baselines. Existing diagnostics omit these effective counts.
Nit/check-fold opponents have genuine showdown starvation. Their lack of
strength labels should not be misreported as evidence against a timing tell.

The gate freezes permanently when the first eligible context fails after hand
300, even if another context has too few labels or evidence would accumulate
later. Its labels are **final made-hand categories**. slow_tell instead delays
on **current Monte Carlo equity 0.42–0.62**, often on an earlier street, once
per hand with a finite delay fund. Final category is not that label. Both
fragmentation and label mismatch need quantified controls before a fix.

## Noise, detectability and transfer

The current implementation retains at most 128 overhead samples per boundary
class and uses their median. Prior telemetry recorded neither full-stream mean,
standard deviation nor p99. Fresh real-judge measurements of those statistics,
including effective labelled counts at the gate decision, are pending. They
must precede threshold tuning. For two groups with standard deviation sigma
and n samples per group, a rough mean-difference threshold is
`z * sigma * sqrt(2/n)`; 90% power adds about 1.282 standard errors to z.
The existing z=4.5 applies separately to two splits, so n is the per-split
count, not the total clean-gap count. A sub-noise tell is not automatically
undetectable: repeated independent samples can detect a smaller mean shift;
heavy tails, dependence and the available sample count determine power.

Container/network load changes both overhead and noise. Any retained detector
must calibrate from that half's own overhead and avoid fixed laptop-specific
latency cutoffs as proof of strength. Compare 0/1/3/10/30 ms synthetic doses
using measured residual noise; use live positive and negative controls.

## Time-bank ground truth: important metric mismatch

The judge reports **charged request time**, not direct CPU/think time:
`sum(max(0, HTTP_elapsed - 0.001))`, including callbacks/new_half. It also
reports full HTTP wall time and call count. Jester's current estimate sums
baseline-subtracted gaps and extrapolates clean gaps to all observed actions.
These metrics cannot be equated without calibration: subtracting 1 ms after
summing is not equivalent to clipping each request before summing.

| Opponent | Current estimated bank/half, median s | Judge charged bank/half, median s |
| --- | ---: | ---: |
| baseline_random | 0.88474 | 0.00022 |
| slow_tell | 3.34722 | 1.19467 |
| pot_odds_bot | 3.04551 | 0.13066 |
| nit_folder | 0 | 0.58940 |
| v1 | 5.12713 | 1.45072 |

The discrepancies are large. Clean gaps need not represent multi-action gaps,
zero baselines may be absent, and per-request grace matters. The immutable
judge JSON only gives per-half totals, so an accuracy test at hand 700 needs
an independently recorded test-only prefix reference or a matched prefix run;
comparing hand-700 estimates with final totals would be invalid. Jester must
never read these external references. Report absolute error near zero because
relative error is undefined for a zero reference. Do not promise universal
±25% identification of an unobservable network/compute decomposition.

## Realistic value and attack surface

Most rule/constant-work opponents provide no usable strength tell. Timing may
be more useful for warning about a time-bank collapse, but the current design
requires the strength gate to open before lowering detector K. The user earlier
required all effects off after gate failure; retain that constraint unless a
separately tested redesign is explicitly authorized. Faster behavioral collapse
detection must be measured, not inferred from the existence of an estimate.

An opponent can fake slow/fast strength signals. Existing bluff frequency is
multiplied by at most 0.90–1.10, and equity/pot-odds floors remain intact. That
bound alone is not a chip-loss bound: tiny changes in large pots can be costly.
Measure a fixed fake-tell control against timing-disabled Jester and retain a
default-off nudge switch if no gain/lag benefit survives fair-league evaluation.
Never tune on holdout results.

## Jester's own leak and rules

Street-fixed sample counts and a strength-blind global governor reduce timing
leakage, but do not prove absence of correlation. Existing latency evidence:
1,000-hand random/call/pot profiles had worst p99 1.664 ms and zero safety
errors; no per-decision equity/latency pairs were retained. A new per-street
correlation audit with strength measured outside the timed region is pending.
Control for street, public history and pacing rather than pooling unlike work.

All new runtime measurement must remain passive, half-local and bounded.
Diagnostics stay in memory and print to stderr only under `JESTER_DIAG=1`.
No bot sleeps, probes, opponent requests, judge-output reads or engine edits.
Only test opponents may deliberately sleep. The latest champion remains
untouched and submittable while the audit is developed. No module deletion
or runtime dependency growth is authorized.

## Completion status

The initial measurements, failure hypotheses and rejected experiments are
recorded here. No experimental timing implementation passed all promotion
gates. The live bot remains v2; the complete experiment and its tests are
preserved on `experiment/phase2-timing-audit`. Full enabled/disabled training
value, head-to-head and holdout were not completed after the loss guardrail
failed. They must not be reported as passes or as evidence of a timing benefit.

## Fresh measurement and confirmed regressions

Command (unchanged frozen v2, an external observer only):

```sh
JESTER_DIAG=1 JESTER_TIMING_PROBE=1 BOT_SEED=7 .venv/bin/python -B tools/league.py --challenger v2 --opponents baseline_random slow_tell pot_odds_bot calling_station --seeds 1 2 3 --deals 1000 --jobs 2 --label phase2-timing-original-audit
```

All 12 matches / 24 halves completed without safety violations. Raw evidence:
`league/results/20261108T091448113891Z_phase2-timing-original-audit.json`;
compact statistics and reproducible residual-noise data:
`tools/timing_original_evidence.json`.

| Context, against RandomBot | n | Mean ms | SD ms | p99 ms |
| --- | ---: | ---: | ---: | ---: |
| Same hand | 3,363 | 0.256594 | 0.029450 | 0.334875 |
| Cross hand | 1,326 | 0.316969 | 0.045241 | 0.429167 |

For comparison, same-hand mean/SD/p99 were 0.262736/0.037710/0.356500 ms
against slow_tell and 0.265571/0.033971/0.331792 ms against pot_odds_bot.
The nominal 90%-power minimum contrast with sigma=0.045241 ms, n=5 per
group/split and z=4.5 is about **0.165 ms**, before the old explicit **1 ms**
floor. These are Gaussian independent-sample approximations; a sparse mixture
or a mislabeled category can require far more samples. A true 3 ms contrast
would dominate this overhead noise if the available labels identified it.

At the original gate decision, **2/6 RandomBot halves and 2/6 pot_odds_bot
halves had zero contexts with two strength groups having five samples in both
splits**. They nevertheless closed as "no confirmed signal". All six slow_tell
halves did have a usable contrast somewhere, so starvation alone does not
explain that opponent: final-category/current-equity label mismatch remains
important. Nit/check-fold starvation from the full league is separately real.

Regressions demonstrated before fixes:

1. A terminal sample from hand 699 could produce a 1.10 bluff multiplier on
   unrelated hand 700. `test_previous_hand_timing_cannot_nudge_a_new_hand`
   failed with 1.1 instead of 1.0; samples now retain their source hand.
2. The raw-gap bank metric ignored per-request grace. A synthetic 1,400 ×
   1.5 ms stream returned **2.1 s**, rather than the judge's **0.7 s** charge.
3. Extrapolating fast same-hand samples into slower boundary requests gave
   **0.700 s** against a known **1.225 s** stream. Boundary gaps now contribute
   their own observed work. Borrowed same-half calibration is marked lower
   confidence, and insufficient direct calibration cannot lower detector K.
4. When the first overhead baseline arrived at hand 600, early work was
   discarded. A synthetic stream returned **0.700 s** instead of **1.750 s**.
   A bounded 4,096-gap buffer now retrospectively prices early observations;
   truncation is reported and blocks K reduction. No unbounded runtime list
   was introduced.

The final /hand-end flush is also sampled without inventing a decision, and
its different route is excluded from zero-opponent /act overhead baselines.
Each bug has an injected-clock test. The original permanent-failure test is
retained: the redesigned qualification window may gather evidence until hand
699, but a failed final gate stays closed and all timing effects stay off.

## Statistical prototype results and next qualification

The first action/latency prototype used a single independent hand summary,
public-street normalization, tail enrichment and disjoint confirmation splits.
It passed synthetic doses (0 ms: 0%; 1 ms: 91%; 3/10/30 ms: 100%, 100 halves
per dose), but **failed** the wider live positive control: **21/40 opens
(52.5%)**. Its negative control had **0/60 opens**. Those results are retained
under `phase2-positive-control` / `phase2-negative-control`; they are not
claimed as a successful audit or promotion. A four-half pilot had misleadingly
shown 4/4 opens, illustrating why the larger control is required.

The final qualification uses three predeclared checks (hands 300, 500 and
699), with alpha spending 0.001 / 0.003 / 0.008 across four tests
(nominal total 0.048). Each check uses a proper Fisher combined p-value, not
an uncalibrated product, and requires the same direction in disjoint hand
splits. The nominal bound assumes valid independent split tests; live negative
controls and measured-noise simulations remain mandatory under real dependence.
An action-latency association establishes a repeatable timing pattern, **not
private hand strength**. It supplies no bluff model; only separately confirmed,
unambiguous strength contexts may supply bounded bluff hints. Unknown evidence
remains neutral. No runtime strategy RNG draws are consumed by the detector.

The known-clock pilot also found a fixture problem: its own work cap of 7 s
kept it inside the tournament's 8 s bank, but produced ~4.3 s judge charges,
above our runner's 4 s safety threshold. The test-only cap is now 5 s. These
pilot violations are retained in raw results; Jester itself had zero faults.
They are not waived in final controls. Exact hand-prefix ground truth now
comes from `tools/judge_timing_audit.py`, which delegates every action, deal,
request and score to unchanged judge APIs, copying normal AgentStats only at
hand-end boundaries. No oracle information is delivered to Jester.

## Safety rejection and the next budget experiment

Iteration 2 was rejected: Jester used **4.251613 s** in a charged half while
its internal choose timer counted **3.338083 s**. A timing-disabled fake-tell
half also used **4.225189 s** against **3.072345 s** internally. This is a
real safety failure, regardless of the absence of a tournament forfeit. The
partial full run was stopped at 214/300 matches; it cannot pass a league gate.
The rejected source is archived independently under
`tools/phase2_candidates/rejected_iteration2/`. v2 was restored and verified
before the audited measurement implementation was used as the next experiment's
base. No new champion was tagged.

Iteration 3 changes only budget accounting/headroom relative to that base:
record HandResult callback work without counting extra decisions, and reserve
1.5 s of the 4 s ceiling for framework/request work that our choose timer
cannot observe. The normal internal budget is 2.5 s. It remains global and
strength-blind, with a 30 ms per-decision cap. Regression tests failed before
this correction. The six 1,000-deal slow_tell/fake_tell regression matches
(seeds 3, 4, 20) all won with zero safety violations. The full fast suite passed
203 tests in 18.116 s; wider performance and safety gates are still running.

The runner also had an evaluation-scope bug: it applied Jester's **4 s**
headroom ceiling to deliberate-delay fixtures required to stay inside their
own **8 s** bank. A regression first demonstrated this with a healthy 4.5 s
control. The corrected evaluation keeps Jester's 4 s rule and every error,
timeout and forfeit check, and checks controls against their own 8 s bank.
Historical raw summaries and times are retained, including two 4.48 s
strong_tell halves; they are explicitly reassessed under that stated scope.
This does not change either rejected Jester safety result above.

On the current budget implementation, the live +40 ms control opened **38/40
halves (95%)**. The two closed halves are retained; detection of a work pattern
does not authorize a strength nudge. Production `TIMING_NUDGES=False` remains
the default. Negative controls, clock validation, fake-tell impact and full
same-field value/promotion comparisons remain pending.

## Final measurements and rejection of iteration 3

Current-source controls (20 seeds / 40 halves for positive and fake controls;
10 seeds × three negative opponents / 60 halves; five seeds × two known-clock
opponents / 20 halves), all 1,000 duplicate deals:

| Check | Observed result | Criterion |
| --- | --- | --- |
| +40 ms live positive | 38/40 opens (95%) | ≥80% |
| Random / constant-work negatives | 0/60 opens | ≤5% |
| Hand-700 bank accuracy | worst relative error 18.86% | ≤25% |
| False gate, default nudges off | 0 actual distribution nudges | neutral intended |
| Fake-tell end-to-end delta vs disabled | −0.33125 bb/deal, 95% CI [−0.60198, −0.06052] | lower CI ≥−0.25: **FAIL** |

Every current-source control had zero Jester errors/timeouts/forfeits and a
charged half below 4 s. Controls stayed within their own 8 s banks. Zero
negative opens gives a one-sided nominal 95% upper bound of 4.87% if halves
are independent; duplicate halves are clustered, so the empirical rate is the
primary reported result. The synthetic measured-noise suite used 100 halves
at each 0/1/3/10/30 ms dose: 0%, 100%, 100%, 100%, 100% opens. These results
qualify repeatable latency-pattern detection, not hand-strength inference.

The fake-tell comparison is a genuine rejection despite default-off nudges:
measuring timing can change global pacing/sample counts and therefore the
strategy RNG trajectory. A unit test with identical fixed computation proves
zero direct nudge effect, but that does not erase the end-to-end loss. No
statistical threshold or loss bound was changed after seeing the result.

The configured full run was stopped with 246/300 matches completed. On that
same 246-match subset, v2 scored 228.0 points / +3.436600 bb/deal; the candidate
scored 221.5 / +2.952561. Jester had zero safety issues, maximum charged half
1.703904 s. These are **partial matched-subset measurements**, not a completed
league gate. Head-to-head and fresh holdout were not run after rejection; no
holdout scores informed a change. No new champion was tagged.

Exact input paths, hashes, assessments and per-control maximum clocks are in
`tools/phase2_iteration3_results.json`. Raw match JSON remains under
`league/results/` (gitignored). Commands and seed/deal/source metadata are
embedded in every record. The candidate fast suite, including preliminary
isolated expansion-tool tests, passed **222 tests in 19.43 s**; its 200-deal
random regression won at +6.4525 bb/deal, with zero errors or safety issues.

## Conditional own-latency audit

Initial exploratory preflop measurements found a tiny correlation. Policy
band selection now performs all three comparisons and computes bluff scaling
in every band in the experimental implementation; probability distributions
were checked against frozen v2 on reachable states and remained identical.
This is a work-hygiene change, not proof of hardware constant-time execution.

An independent fresh-card validation used 500 observations per street,
precomputed independent reference equities, randomized measurement order,
fixed public work and a nonbinding governor:

| Street | Spearman rho | permutation p | p99 ms | high-minus-low equity quartile median µs |
| --- | ---: | ---: | ---: | ---: |
| Preflop | −0.07565 | 0.110 | 0.03225 | −0.167 |
| Flop | −0.04391 | 0.340 | 1.55138 | −8.083 |
| Turn | −0.03107 | 0.520 | 1.92692 | −27.791 |
| River | −0.04967 | 0.295 | 1.68392 | −23.625 |

No street was significant in this independent validation. The raw 2,000
strength/latency pairs and exact design are retained in
`tools/timing_own_leak_evidence.json`. The budget change is not exercised in
this nonbinding test; full-half pacing is measured separately. Sub-microsecond
preflop effects are far below the measured packet-noise detection scale for
one half, but we do not assert absence of all possible side channels.

## Operational conclusion

Keep v2 runnable and do not promote either rejected timing candidate. Retain
the timing module. Default-off nudges are implemented in the experimental
branch; they have not been promoted to the live champion. Before resuming
this feature, isolate and reduce its measured computation/pacing cost, then
repeat the full value and promotion gates. The requested expanded fair/Hard/
oracle league can be built independently around frozen v2.
