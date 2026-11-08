# Improvement loop rules

User-provided Part 4, received 2026-11-08. Read alongside root AGENTS.md and
IMPROVEMENT_LOG.md before resuming.

1. Safety beats everything. Reject any change adding an error or forfeit or
   exceeding 4 seconds thinking time per half, regardless of bb/deal.
2. One change per iteration, so results are attributable.
3. Tests before code; every bug gets a regression test first.
4. Never tune on holdout. Use holdout opponents/seeds only for validation.
   If holdout results drive a change, rotate in new holdout seeds and a new bot.
5. Prefer broad improvements over overfitting to one test bot.
6. Respect AGENTS.md: never edit server plumbing, game.py, evaluator.py,
   judge_engine.py or test_agent.py. No bot sleeps, network tricks or
   interference with judge/opponent.
7. Keep runtime dependencies minimal; development tools belong only in
   requirements-dev.txt.
8. Keep the champion runnable and submittable at all times. Its tag must pass
   pytest test_agent.py and a full safety run.
9. Log all experiments, including rejections.
10. Ask before changing overall strategy direction, adding a large dependency
    or model file, deleting tests, or making the repository exceed about 200 MB.

## Session and acceptance protocol (Part 2)

Run up to five iterations, stopping earlier if budget is low. Reuse the latest
full champion baseline only when runtime/config/opponents are unchanged.
Diagnose one weakness from --logs, record numbers, state one hypothesis and
its risks, test first, then implement and run all fast tests.

Acceptance requires zero challenger errors/forfeits, <=4 s per half and
p99 decision latency <20 ms; >=20 training seeds x 1,000-deal head-to-head
with CI not entirely below zero; training points >= champion and mean bb/deal
>= champion minus 0.02; no champion WIN becoming a LOSS; holdout points not
below champion whenever tagging a new champion (also every third accepted
change). Compare the same opponents and seeds. The intentionally faulting
crashy fixture retains its separately recorded expected-opponent-fault
classification; never exempt challenger faults.

Accept only after every gate passes: commit source, snapshot next vN, tag
champion-vN, and include the new snapshot in subsequent league runs. On any
failed gate, revert only the experimental strategy change, retain valid tests,
and log the rejection. Do not tune on a failed holdout. Append the user's
iteration format (weakness, diagnosis, change, tests, results, holdout, next
idea), plus source SHA and exact commands. At session end report accepted and
rejected changes, champion and full source SHA, standing, and three next ideas;
remind the user about submitting a newly tagged champion's full SHA.
