How to use this file
1. Add this line to AGENTS.md: "Phase 2 work follows codex_phase2_adversarial.md. Its Part 5 rules apply on top of the existing loop rules."
2. Paste Part 1 first (timing audit). Then Part 2 (league expansion), then Part 3 (continuous testing runner). Each part is one Codex session or more; commit at the end of each.
3. After Parts 1–3 are done, use Part 4 as the new loop prompt instead of the old Part 2 loop. Paste it whenever you want another improvement session; it resumes from IMPROVEMENT_LOG.md.
4. Between Codex sessions, leave tools/continuous.py running on your laptop. It keeps generating data without using any Codex budget.
Definitions used throughout
- Jester = our bot. Champion = the latest champion-vN tag (currently v2).
- "4× stronger" = the new Hard tier, as a group, holds the champion to one quarter or less of its current average edge. v2's training mean is about +3.0 bb/deal, so Hard-tier bots must hold it to ≤ +0.75 bb/deal, or beat it.
- "4× larger" = about 60 training opponents (up from 15) and about 12 holdout opponents (up from 3).
- "Perfect" isn't reachable in poker, so it's defined as measurable targets: zero safety violations across millions of hands, zero losses against the fair league, chops steadily converting to wins, and losses to cheating bots that shrink over time.
Backtesting shows the timing module was never used once. The iteration-0 log also says its gate stayed closed in all 40 slow_tell halves. Find out whether that is correct behavior (no usable signal exists) or a bug (the gate can never open), fix any bugs, and decide with data whether the module earns its place.
Before changing anything, write tools/timing_audit.md covering these points, with numbers from our own data where possible:
- What we can observe. Only gaps between our reply and the judge's next request. Each gap mixes judge processing, HTTP round trips, opponent think time, and batched on_hand_end delivery. We never see the opponent's requests.
- Noise vs signal. Measure the overhead baseline's mean, standard deviation and p99 on this machine. A tell smaller than the overhead noise can't be detected with the samples available in one half. Estimate the minimum detectable tell size for our sample counts.
- Sample starvation. The gate needs clean samples (exactly one opponent action in the gap) that are also linked to showdowns. Count how many such labelled samples we actually get per half, per opponent. If the count is usually below the gate's minimum (30), the gate cannot open, and that's a design bug, not a lack of signal.
- Tournament conditions differ. Bots may run in separate containers or machines with different load and network latency. Thresholds tuned on a laptop may not transfer. The module must self-calibrate from each half's own baseline.
- Most real bots have no timing tell. Constant-work bots and simple rule bots produce noise only, so the realistic upside is small. The time-bank collapse use case is the more valuable one.
- Ground truth exists locally. The judge's JSON report contains each bot's real thinking time per half. Use it to validate our estimates. It's for testing only; the bot itself never reads judge output.
- Attack surface. An opponent could fake tells (think long with strong hands to bait our bluffs). Any timing-driven nudge must be small and bounded so a fake tell can't cost much.
- Our own leak. Confirm that our decision time doesn't correlate with our hand strength.
- Rules. Passive measurement of our own request timing only. No sleeps, no probing, no contact with the opponent or judge beyond normal replies.
Add per-half diagnostics to the timing module, stored in memory and emitted to stderr only when env var JESTER_DIAG=1 (never in the tournament):
- overhead samples, clean samples, showdown-labelled clean samples
- gate test statistic, threshold, decision, and reason (e.g. "not enough labelled samples", "statistic below threshold", "passed")
- number of decisions where a timing nudge was actually applied, and the size of each nudge
- opponent time-bank estimate at hands 300, 500, 700, 900 and at half end, plus when (if ever) detector K was lowered
Extend tools/league.py to collect these diagnostics into results JSON and to add the judge's ground-truth opponent thinking time next to our estimate.
Create tests/test_timing_audit.py and slow-tier integration tests:
- Dose-response test: synthetic gap streams with an injected tell of 0, 1, 3, 10 and 30 ms (on medium-strength showdown hands) over realistic noise from 1.2. Record the detection rate across many simulated halves. Requirements: ≥ 90% detection at 10 ms and 30 ms, and ≤ 5% false positives at 0 ms.
- Live positive control: make league/opponents/strong_tell.py, a copy of slow_tell with a large tell (e.g. +40 ms on medium hands, still well inside its time bank). The gate must open in ≥ 80% of halves against it in real judge matches.
- Live negative control: against baseline_random and constant-time bots, the gate must open in ≤ 5% of halves.
- Time-bank estimate accuracy: against bots with known think-time patterns, our estimate at hand 700 must be within ±25% of the judge's ground truth.
- Nudge is bounded: even with a gate falsely open, a fake-tell bot can't make us lose more than a small, measured amount versus timing-disabled Jester.
- If the gate can't open because of sample starvation, redesign the gate rather than just lowering thresholds. Options include using all opponent decisions (not only showdowns) for a time-vs-action-type test, pooling across streets, or a sequential test that can open as soon as evidence is strong. Keep the false-positive requirement.
- If attribution is wrong (batching, hand boundaries, first-action gaps), fix it and add a regression test for each bug.
- Measure the value: run the full training league with timing enabled vs disabled (same seeds). Report points and bb/deal differences, plus how many hands earlier check-fold exploitation fires when the time-bank estimate is used.
- Decision rule: if the module produces no measurable gain and no detection lag improvement, keep it with nudges disabled (TIMING_NUDGES = False) but keep the diagnostics, and ask me before deleting it. If it helps, keep it on.
Done when: tools/timing_audit.md explains why it never fired, every control passes, any bugs have regression tests, the value measurement is logged in IMPROVEMENT_LOG.md as a normal iteration (accepted or rejected through all gates), and it's committed.

PART 5: Phase 2 rules (on top of the existing loop rules)
Safety still beats everything. A single forfeit costs more than many tuning gains combined.
Cheating is test-only. Cheater bots and the oracle judge live only in league/ and tools/. Add a test that agent.py and bot/ never import from, read, or reference league/, tools/ or tests/. Jester itself never cheats, never sleeps, never probes, and never interferes with the judge or opponents.
Never modify judge_engine.py, game.py, evaluator.py, test_agent.py or the server plumbing. The oracle judge is a separate copy.
No tuning on holdout, and rotate holdout after any holdout-influenced decision.
Fair-league results decide promotions. Cheater results are a guardrail only; never trade fair-league points for a smaller loss to an oracle.
Hall of fame is permanent. Never remove an evolved adversary or past champion from the league without asking me.
One change per iteration, tests before code, and log everything, including rejected experiments.
Keep the champion submittable at all times. It must always pass pytest test_agent.py, the fast suite, and a full safety run.
Runtime stays lean. Dev and evolution tools go in requirements-dev.txt only. The submitted bot's dependencies don't grow without asking me.
Ask me first before deleting the timing module, changing Jester's overall strategy direction, or anything that would grow the repo past about 200 MB.


## Parts 2–4 — received after Part 1 began

Grow the league from 15 to about 60 training opponents and from 3 to about 12 holdout opponents. Organize them in tiers in league/config.json. Every bot is a runnable server with its port from PORT, has a short docstring describing its idea, and has its source hash recorded.
Existing training bots, plus parameter variants of them (tighter, looser, more and less aggressive versions of station, nit, TAG, LAG, maniac, pot-odds and equity bots) so the league reflects the range of styles other teams will actually submit.
These play by the real rules but are designed specifically to beat Jester. Read Jester's code, gear logic, thresholds and detectors, and attack each one:
These bots get unfair advantages that are impossible in the real tournament. They exist only to measure how exploitable Jester is and to keep it robust under extreme pressure.
- Build tools/oracle_judge/, a copy of the judge (never modify judge_engine.py), that can give one seat extra information or resources. Add a test that the real judge_engine.py is byte-identical to the original.
- Cheater variants: 
  - oracle_full: sees Jester's hole cards and plays a near-best response.
  - oracle_partial: sees 2 of Jester's 5 hole cards.
  - board_oracle: knows the next board card.
  - unlimited_compute: very large Monte Carlo sample counts with an unlimited time bank.
  - oracle_counter: sees Jester's current gear and opponent-model state through the test harness.
- Cheater matches are run only through the oracle judge, are reported separately, and are never counted in league points or used in acceptance gates other than the exploitability gate (Part 4).
- Metric: Jester's bb/deal loss to each cheater over time. We aren't expected to beat an oracle. The goal is that the loss shrinks or at least never grows, which means Jester is getting harder to exploit. Jester must never crash, time out or forfeit against them.
Create tools/evolve_adversary.py:
- A parameterized opponent family (thresholds, bluff rates, bet-size mix, call-down width, switching rules, bait lengths).
- Search (random search, then CMA-ES or a genetic algorithm; dev-only dependency) for parameters that maximize bb/deal against the current champion, using quick matches for screening and full matches for confirmation.
- The best adversaries found are saved as frozen bots in league/opponents/evolved/ with their parameters, the champion version they were evolved against, and the date.
- They join Tier H permanently as a hall of fame, so Jester can't cycle back into old weaknesses.
About 12 holdout opponents drawn across tiers F and H (at least 4 Hard-tier, including at least one evolved adversary and one counter bot whose idea isn't used anywhere in training), plus a fresh holdout seed range (e.g. 201–220). Rotate in new holdout bots and seeds whenever a decision was influenced by holdout results.
The full league is now about 4× larger, so:
- Tiered evaluation: a screening run (subset of opponents, fewer seeds) rejects clearly worse challengers early. Only promising challengers get the full league.
- Sequential testing: stop a head-to-head early when the CI is already clearly decisive, either way.
- Cache champion results so they're only recomputed when the champion or league changes.
- Report wall-clock time for every run.
Run the full expanded league (training, Hard tier, holdout, and cheaters via the oracle judge) for the current champion. Log it as a new BASELINE in IMPROVEMENT_LOG.md. Don't compare raw point totals with the old 15-opponent league. Report:
- points and bb/deal by tier
- whether Tier H meets the "4× stronger" definition. If not, strengthen or evolve more adversaries until it does, and log what was needed
- the top 10 hardest matchups
- loss to each cheater bot
Done when: the league has about 60 training and about 12 holdout opponents, Tier H holds the champion to ≤ +0.75 bb/deal on average, every bot passes a smoke test, the new baseline is logged, and everything is committed.
Create tools/continuous.py, a long-running local process that keeps producing data while no Codex session is active.
- Cycle, repeated forever: 
  1. Run a rotating slice of the training league against the champion with fresh seeds (e.g. from 1,000 upward, never reusing seeds). Append results to league/history.csv.
  2. Run one round of adversary evolution (2.4). Save any adversary that beats the champion or holds it under +0.5 bb/deal.
  3. Run a safety sweep: a large legality fuzz and an edge-case run on the champion.
  4. Every N cycles, rerun cheaters through the oracle judge.
- Alerts: write a line to league/ALERTS.md immediately if any of these happen: a champion error, forfeit or timeout; think time above 4 s per half; a fair-league loss; a new evolved adversary that beats the champion.
- Summary: maintain league/DASHBOARD.md with trends per tier, the hardest current matchups, cheater-loss trend, safety record (total hands played without a safety violation), and alerts. Codex reads this at the start of every Part 4 session.
- Operations: resumable after restart, stops cleanly when a league/STOP file exists, caps CPU usage (--jobs), rotates raw logs so disk use stays bounded, and never modifies agent.py, bot/ or any champion snapshot.
- Command to start it: BOT_SEED=7 .venv/bin/python -B tools/continuous.py --jobs 2. Include instructions in its docstring for running it in the background on macOS.
Done when: it runs at least two full cycles cleanly, the dashboard and alerts files populate correctly, the STOP file works, and it's committed.
You're running the adversarial improvement loop for Jester. First read AGENTS.md, this file's Part 5 rules, league/DASHBOARD.md, league/ALERTS.md, and IMPROVEMENT_LOG.md. Resume from where the log left off.
Run up to 5 iterations this session, then stop and summarize. Each iteration:
1. Triage. Any open alert in league/ALERTS.md is priority 1: reproduce it, add a regression test, fix it. Otherwise pick the weakest area from the dashboard, in this order: Hard-tier losses, then Hard-tier chops, then fair-tier chops, then growth in loss to cheaters.
2. Diagnose with --logs and the diagnostics. Write down numbers.
3. Hypothesize one change and state the expected gain and the risk.
4. Test first. Add tests pinning the intended behavior.
5. Implement the change as the challenger. Run the fast test tier.
6. Evaluate through all gates: 
   1. Safety gate: zero errors, timeouts and forfeits everywhere, including against cheater bots; think time ≤ 4 s per half; p99 decision < 20 ms.
   2. Head-to-head gate: challenger vs champion, at least 20 fresh seeds × 1,000 deals; CI not entirely below 0.
   3. League gate: training points ≥ champion; mean bb/deal ≥ champion minus 0.02.
   4. Hard-tier gate: Tier H points and bb/deal ≥ champion's.
   5. No-regression gate: no champion WIN becomes a LOSS on any matchup.
   6. Exploitability gate: loss to cheater bots doesn't grow significantly.
   7. Holdout gate (at promotion only): holdout points ≥ champion's.
7. Accept or reject. On accept: commit, snapshot, tag champion-vN, and add the new snapshot to the league. Run one round of adversary evolution against the new champion right away and add the winners to Tier H. On reject: revert, keep valid tests, and log the result.
8. Log in the team format in IMPROVEMENT_LOG.md, adding these fields: Tier results (F / H / C) and Adversaries added.
Session end: summarize changes accepted and rejected, the current champion and its full SHA, standings by tier, the hardest matchups, the safety record, and the top 3 ideas for next session. If a new champion was tagged, remind me to consider submitting its full 40-character SHA.
