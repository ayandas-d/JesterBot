# Improvement league

This directory is development infrastructure. `.dockerignore` excludes it
from the submission image. The live `agent.py` and `bot/` strategy are unchanged
by the one-time setup.

## Snapshots

```sh
.venv/bin/python tools/snapshot.py --tag
.venv/bin/python tools/run_snapshot.py v1 --port 5020
.venv/bin/python tools/run_snapshot.py v1 --inspect
```

Snapshots use the next monotonically increasing version number. Each contains
`agent.py`, the complete `bot/` package without bytecode caches, and frozen
`game.py`/`evaluator.py` copies. `META.json` records source commit, UTC creation
date, dirty-runtime status and SHA-256 hashes. Launching verifies the manifest,
clears `PYTHONPATH`, changes to the snapshot directory and replaces the process
with a fresh interpreter. Every local runtime import resolves inside that
snapshot. Do not edit a champion in place; make a new snapshot.

`champion-v1` tags source commit `486507685c326ee891397c03adb2af8321fbc201`.
The infrastructure commit stores the v1 snapshot and launcher. Future snapshots
are discovered automatically as training opponents, including the current
champion for a self-play sanity check.

## Evaluation

```sh
# Exactly 300 deals, first three training seeds, training opponents + champions
BOT_SEED=7 .venv/bin/python tools/league.py --quick --label quick-check

# Exactly 1,000 deals, all 20 training seeds
BOT_SEED=7 .venv/bin/python tools/league.py --full --label acceptance

# Independent matches run in parallel; keep jobs=1 for conservative time audits
BOT_SEED=7 .venv/bin/python tools/league.py --quick --jobs 2 --label parallel-check

# Challenger versus a frozen champion; pooled paired-deal CI across seeds
BOT_SEED=7 .venv/bin/python tools/league.py --head-to-head v1 --seeds 1 2 3 4 5 --label h2h

# Milestone only: all holdout opponents and holdout seeds
BOT_SEED=7 .venv/bin/python tools/league.py --full --group holdout --milestone release-review --label holdout-review
```

Use `--challenger vN` to test frozen source instead of the live bot. Custom
subsets use `--opponents`, `--seeds`, and/or `--deals` without `--quick` or
`--full`. `--logs` includes every judge hand in the raw JSON. No snapshots or
test opponents share a bot interpreter or a memory dictionary.

`config.json` separates training seeds 1–20 from holdout seeds 101–110.
`gto_ish`, `adaptive_counter`, and `erratic` are holdouts. The CLI refuses to
use holdout names or seeds without an explicit `--milestone`, even through
custom options. Holdout scores are never used to tune this baseline.

Results include each matchup's verdict, bb/deal, 95% CI, errors, both half
thinking times with max/mean, forfeits and diagnostics. Summary tournament
points come directly from the judge: win 1, chop 0.5, loss 0, including its
forfeit override. The combined CI pools duplicate-pair returns, not unpaired
hands. Worst matchup means lowest mean bb/deal aggregated over its seeds.

`crashy` deliberately earns errors and forfeits partway through each half.
Its expected errors, forfeits and skipped calls are recorded separately.
Our errors/forfeits and unexpected opponent failures remain safety violations.
An ordinary strategic loss is a baseline result, not a runner failure: the
setup is measuring the champion, not tuning it to win the new league.

Raw results are saved to gitignored `results/<UTC timestamp>_<label>.json`,
including configuration and source hashes. Human-readable server/judge logs
remain under `/tmp/league-<label>-.../`. Each run appends a CSV summary to
`history.csv`. Cancellation retains partial results; all owned subprocesses
are terminated, with a kill fallback after a grace period. Concurrent appends
to history use a file lock. Full runs can take a while; progress is printed
after every match.

## Tests

```sh
.venv/bin/python -m pip install -r requirements-dev.txt
BOT_SEED=7 .venv/bin/python -m pytest -q          # fast tier, slow excluded
BOT_SEED=7 .venv/bin/python -m pytest -m slow    # explicit expensive milestone runs
```

Hypothesis is development-only. Property tests use reachable engine walks;
metamorphic tests cover suit relabelling, hole-card order and known made-hand
upgrades with sampling tolerances. A higher single card rank is not universally
a hand improvement in Omaha. The one short-call test is explicitly an
unequal-stack fixture authorized by the user: normal equal 80-chip starts
cannot produce `my_stack < to_call`, and this engine does not implement general
unequal-stack side-pot settlement. Engine source remains unchanged.

The fast suite also checks bounded half-local memory, stationary latency
probes, reset reproducibility, snapshot isolation, opponent contracts, holdout
guards, score aggregation, and failure containment in all active modules.
The slow tier runs full training and explicit milestone holdout evaluations.
Add a failing reproduction to `tests/test_regressions.py` before fixing each
strategy bug found during future improvement iterations.

Hypothesis settings and composite strategies follow its
[official settings documentation](https://hypothesis.readthedocs.io/en/latest/settings.html)
and [strategies reference](https://hypothesis.readthedocs.io/en/latest/reference/strategies.html).
