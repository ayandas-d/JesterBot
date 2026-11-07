# Task 4: opponent model, gear switching and check-fold detection

Validated on 2026-11-07 using Python 3.12.16 in `.venv` on macOS, building
on Task 3 commit `affdb09`. All changes are inside the permitted agent
section, imported bot modules, tests and tools. Protected files and agent
code outside the markers were compared byte-for-byte with HEAD and are
unchanged. No dependencies were added.

## Accounting and integration

`bot/opponent.py` maintains whole-half aggregates and a rolling window of
100 completed hands. It counts opponent actions, raises, checks, calls,
folds, responses to our voluntary raises, calls/folds/re-raises among those
responses, and net big blinds and opponent action counts by our gear.
Blind responses count as actions but are excluded from the voluntary-raise
response denominator. Raise frequency uses all opponent actions as its
denominator; fold, call and re-raise response rates use responses to our
voluntary raises. A zero denominator reports zero; switching requires
actual sample counts before using a rate.

The model consumes cumulative histories incrementally and records our
chosen action. It deduplicates ordered results and avoids counting a
history prefix twice. The engine history takes precedence if a simulation
applies a different action from the one proposed by the bot. Missing
results or divergent histories break the detector's evidence streak
conservatively. Storage is bounded to the current hand, 100 completed hands
and aggregate counters.

Terminal opponent folds and calls do not appear in a subsequent decision
history. The model reconstructs those from our last action and the result.
It also accounts for the opponent's closing river check and a small-blind
fold before our first decision. Street boundaries clear pending raises;
blinds and free checks cannot masquerade as calls to our raises.

At showdown, the engine's `omaha_score` and `category_of` label the opponent's
revealed hand. Records link that category to the hand's opponent raises and
action count. Whole-half and rolling summaries retain category counts,
raise totals by category, and the fraction of aggressive showdowns with
two pair or weaker. This last measure is a bluffing proxy: a final category
alone cannot prove that an earlier bet was a bluff.

`agent.choose_action` updates the model before selecting an action, and
`on_hand_end` finalizes statistics and evaluates gears. Missing `new_half`
still initializes safely. A fresh half resets every aggregate, rolling
record, pending hand, detector streak, gear candidate, transition history,
RNG, threshold jitter and governor.

## Switching and exploitation

All adaptation settings are in `bot/gears.py:CONFIG`; model window, detector
K and weak-showdown category settings are in `bot/opponent.py:CONFIG`.

- Start in MANIAC; evaluate every 25 completed hands.
- Require 40 relevant events: responses to our raises for opponent-type
  rules, or opponent actions while we played the current gear for loss rules.
- Require the same proposed gear at two consecutive evaluations and at
  least 75 hands between actual switches.
- Re-raise rate above 30% selects TRAP; fold rate above 55% selects MANIAC.
  These opponent-type rules take precedence over generic loss reduction.
- Fold rate below 30%, call rate above 55%, and negative MANIAC net selects
  VALUE. Otherwise negative rolling net in the current gear steps MANIAC
  down to AGGRO, then AGGRO to VALUE; sufficient re-raise evidence selects
  TRAP instead. VALUE and TRAP hold unless an opponent-type rule changes them.
- Confirmed folders receive a 1.10 multiplier on MANIAC's weak-hand raise
  frequency, capped at 1.0. The mixed policy still applies its price floor.

The check-fold detector activates after 15 consecutive opponent actions
that are either free checks or folds. Paid calls (including blind calls)
and raises clear it immediately, before the next decision. While active,
the bot raises whenever legal, preferring HALF, then POT. When raising is
unavailable, the ordinary legal mixed policy applies. The bot still does
the same street-budgeted strength estimation while exploiting; it does
not skip Monte Carlo work based on the exploit or estimated strength.

## Validation

Full suite: **97 passed**, including **19 new opponent tests**. The existing
Starlette/httpx deprecation warning remains. Coverage includes exact
hand-crafted counts, blind/street distinctions, rolling eviction with
negative net values, showdown labels and aggression, duplicated histories
and results, model-generated folder/station/re-raiser streams, minimum
samples, alternating noisy signals, cooldowns, loss-based step-down,
check-fold activation and immediate reset, live HALF preference, legal
fallbacks, fixed sample counts, price floors and complete half reset.

A separate 300-hand engine walk independently counts each player's full
terminal history and compares it against the partial-information model
for both seats, including terminal-action inference and detector streaks.
The existing 2,500-hand safety fuzz and all four gears' legality/distribution
tests also pass.

Both RandomBot duplicate matches used `BOT_SEED=7` and
`--require-win --max-thinking 4`:

| Deals per half | Deal seed | bb/deal | 95% confidence interval | Verdict |
| ---: | ---: | ---: | --- | --- |
| 200 | 7 | +6.4525 | [+3.446, +9.459] | AGENT1_WIN |
| 1,000 | 19 | +6.1585 | [+4.890, +7.427] | AGENT1_WIN |

All four halves had **zero errors, forfeits, skipped calls and timeouts**.
Judge-charged thinking was 0.15/0.13 seconds for the 200-deal match and
0.88/0.80 seconds for the full match. Raw reports are retained in
`tools/task4_results.json`.

Full-half offline profiles include callbacks and exclude engine simulation
and startup. These check runtime, not profitability against each policy:

| Opponent policy | 1,000-hand thinking | p50 decision | p99 decision | Final gear |
| --- | ---: | ---: | ---: | --- |
| Random | 2.1632 s | 0.712 ms | 1.636 ms | TRAP |
| Always call | 2.4705 s | 0.775 ms | 1.709 ms | VALUE |
| Always pot | 1.7712 s | 0.016 ms | 1.697 ms | TRAP |

All profiles had zero internal errors and required no governor reductions.
The RandomBot win margins on these seeds are smaller than Task 3's; these
results validate correctness, time budget and continued wins, not an
overall tournament-strength improvement. Gear and detector thresholds are
configurable for later tuning. Task 5 timing behavior is not activated.

Reproduce with:

```sh
BOT_SEED=7 .venv/bin/python -m pytest -q
BOT_SEED=7 .venv/bin/python tools/profile_bot.py
BOT_SEED=7 .venv/bin/python tools/run_local_match.py --deals 200 --seed 7 --require-win --max-thinking 4
BOT_SEED=7 .venv/bin/python tools/run_local_match.py --deals 1000 --seed 19 --require-win --max-thinking 4
```

`git diff --check` passed. Docker build validation remains unverified from
earlier tasks; no deployment or tournament submission was performed.
