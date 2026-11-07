# Task 0: engine reconnaissance

Date: 2026-11-07. Interpreter: repository `.venv`, Python 3.12.16 on macOS.
Read `agent.py`, `game.py`, `evaluator.py`, `judge_engine.py`, `test_agent.py`
and all four baseline bots. Task 0 changes no strategy. Existing Jester
implementation is preserved in commit `827529a` and remains active throughout
this recon commit. The supplied PART A context is saved verbatim in substance
as the root `AGENTS.md` at the user's explicit request.

## Exact enums

Both are `enum.IntEnum`, defined in `game.py`:

| Enum | Member | Value |
| --- | --- | ---: |
| `Action` | `FOLD` | 0 |
| `Action` | `CHECK_CALL` | 1 |
| `Action` | `RAISE_HALF` | 2 |
| `Action` | `RAISE_POT` | 3 |
| `Street` | `PREFLOP` | 0 |
| `Street` | `FLOP` | 1 |
| `Street` | `TURN` | 2 |
| `Street` | `RIVER` | 3 |

Wire JSON encodes these by member name. `CHECK_CALL` is always legal on a
real decision; `FOLD` requires `to_call > 0`. Both raises require fewer than
four street raises, our stack greater than the call, and an opponent with
chips behind. Engine observations for a seat that is not acting have an
empty `legal_actions`; these are not valid decision requests.

## Exact observation and result fields

`Observation` is a frozen dataclass, with these fields in definition order:

| Field | Type |
| --- | --- |
| `hand_index` | `int` |
| `street` | `Street` |
| `hole_cards` | `tuple[int, ...]` |
| `board` | `tuple[int, ...]` |
| `pot` | `int` |
| `to_call` | `int` |
| `my_bet` | `int` |
| `opp_bet` | `int` |
| `my_stack` | `int` |
| `opp_stack` | `int` |
| `is_button` | `bool` |
| `legal_actions` | `tuple[Action, ...]` |
| `raise_to` | `dict[Action, int]` |
| `min_raise_to` | `int` |
| `raises_this_street` | `int` |
| `action_history` | `tuple[ObservedAction, ...]` |
| `big_blind` | `int` |

`ObservedAction` fields are `street: Street`, `is_me: bool`, `action: Action`,
`amount: int`, `street_total: int`. Blinds are not history entries. `amount`
is added chips; `street_total` is the acting player's resulting street bet.

`HandResult` is a frozen dataclass, with these fields in definition order:

| Field | Type |
| --- | --- |
| `hand_index` | `int` |
| `my_net` | `int` |
| `pot` | `int` |
| `went_to_showdown` | `bool` |
| `board` | `tuple[int, ...]` |
| `opp_hole` | `Optional[tuple[int, ...]]` |
| `winner` | `str` |

`winner` is `"me"`, `"opp"` or `"split"`; `opp_hole` is `None` unless there
was a showdown. Results arrive in batches before the next decision, with
leftovers delivered to `/hand-end` at half end.

## new_half config

The signature is `new_half(config: AgentConfig, memory: dict) -> None`.
`AgentConfig` is a frozen dataclass, rebuilt from the request's `config`
object. Its exact fields/defaults are:

| Field | Type | Default |
| --- | --- | ---: |
| `starting_stack` | `int` | 80 |
| `big_blind` | `int` | 2 |
| `small_blind` | `int` | 1 |
| `num_hands` | `int` | 1000 |
| `time_bank_seconds` | `float` | 8.0 |
| `raise_cap` | `int` | 4 |

`AgentConfig.to_dict()` and `AgentConfig.from_dict()` serialize it; unknown
input keys are ignored. The judge sets `num_hands` from `--deals`. It does not
send the half number, seat or secret match seed to `new_half`. The server
clears `memory` before calling it. Each tournament half has a fresh process.

## Game constants

| Name | Value |
| --- | --- |
| `STARTING_STACK` | 80 |
| `SMALL_BLIND` | 1 |
| `BIG_BLIND` | 2 |
| `RAISE_CAP_PER_STREET` | 4 |
| `NUM_DEALS` | 1000 |
| `TIME_BANK_SECONDS` | 8.0 |
| `NETWORK_GRACE_SECONDS` | 0.001 |
| `ACTION_TIMEOUT_SECONDS` | 1.0 |
| `STARTUP_TIMEOUT_SECONDS` | 15.0 |
| `ERROR_LIMIT` | 5 |
| `CHOP_Z` | 1.96 |
| `AGENT1_DEFAULT_PORT` | 5008 |
| `AGENT2_DEFAULT_PORT` | 5009 |
| `NUM_HOLE_CARDS` | 5 |
| `NUM_BOARD_CARDS` | 5 |
| `RAISE_ACTIONS` | `(Action.RAISE_HALF, Action.RAISE_POT)` |
| `BOARD_CARDS_VISIBLE` | `{Street.PREFLOP: 0, Street.FLOP: 3, Street.TURN: 4, Street.RIVER: 5}` |

Stacks reset each hand. Button posts small blind and acts first preflop,
last postflop. Use `obs.raise_to` for exact engine-selected raise totals;
both sizes can collapse to the same all-in total. The remaining config
fields describe the fixed engine rules; `Game` reads its module constants
directly rather than accepting a custom `AgentConfig`.

## Evaluator helpers and constants

Public functions in `evaluator.py`:

- `card_rank(card: int) -> int`
- `card_suit(card: int) -> int`
- `card_to_str(card: int) -> str`
- `str_to_card(text: str) -> int`
- `cards_to_str(cards: Iterable[int]) -> str`
- `cards_from_str(text: str) -> list[int]`
- `category_of(score: int) -> int`
- `category_name(score: int) -> str`
- `score_five(cards: Sequence[int]) -> int`
- `get_table() -> dict[int, int]`
- `warmup() -> None`
- `omaha_score(hole: Sequence[int], board: Sequence[int]) -> int`

Private helpers: `_pack(category, ranks)`, `_straight_top(ranks_desc)`,
`_score_ranks(ranks_desc, is_flush)`, `_build_table()`.

| Constant | Value |
| --- | --- |
| `NUM_RANKS` | 9 |
| `NUM_SUITS` | 4 |
| `NUM_CARDS` | 36 |
| `RANK_CHARS` | `"6789TJQKA"` |
| `SUIT_CHARS` | `"cdhs"` |
| `ACE` | 8 |
| `NINE` | 3 |
| `HIGH_CARD` | 0 |
| `ONE_PAIR` | 1 |
| `TWO_PAIR` | 2 |
| `STRAIGHT` | 3 |
| `THREE_OF_A_KIND` | 4 |
| `FULL_HOUSE` | 5 |
| `FLUSH` | 6 |
| `FOUR_OF_A_KIND` | 7 |
| `STRAIGHT_FLUSH` | 8 |
| `_CATEGORY_SHIFT` | 20 |

`CATEGORY_NAMES` is `("high card", "one pair", "two pair", "straight",
"three of a kind", "full house", "flush", "four of a kind", "straight flush")`.
`_PAIRS` is all 10 combinations of 2 indices from `range(5)`; `_TRIPLES` is
all 10 combinations of 3 indices from `range(5)`. `_TABLE` is the mutable
module cache, initially `None`, then a dictionary of all 376,992 distinct
five-card masks to scores. The bot must treat this engine table as read-only.

Card ranks use `c >> 2` and suits `c & 3`. `omaha_score` requires exactly five
hole cards and a full five-card board, and takes the best exactly 2+3 hand
over 100 combinations. Higher scores win; equality ties; category is
`score >> 20`. A-6-7-8-9 is the lowest straight. Flush outranks full house;
trips outrank straight.

## Baselines and judge details

- `baseline_random.py`: uniform random choice from legal actions, private
  `random.Random(0)` reset each half.
- `baseline_calling_station.py`: always `CHECK_CALL`.
- `baseline_always_half.py`: `RAISE_HALF` if legal, else `CHECK_CALL`.
- `baseline_always_pot.py`: `RAISE_POT` if legal, else `CHECK_CALL`.
- All default to port 5009 and honor `PORT` and `AGENT_TOKEN`.
- The judge's fallback is check when free, fold when facing a bet. Our
  requested safety fallback is instead always `CHECK_CALL`.
- Charged time is `max(0, HTTP_request_elapsed - 0.001)` per POST, including
  result callbacks. The engine does not independently subtract measured
  network latency beyond this fixed grace.
- `paired_bb[d] = (net_half1[d] + net_half2[d]) / BIG_BLIND`; the reported
  bb/deal averages these paired totals, not individual hands. The CI uses
  sample standard deviation, standard error and `CHOP_Z = 1.96`.
- Match JSON stores per-half faults in `agent_stats["agent1"]` and
  `agent_stats["agent2"]`, each a two-element list. The exhaustion flag is
  `timed_out`, not `time_bank_empty`.

## Differences from AGENTS.md

One factual difference: AGENTS.md says that every result other than an
entirely positive interval is a chop. `judge_engine.decide_verdict` instead
returns a loss (0 points) when the entire interval is below zero. Only an
interval including or touching zero is a chop (0.5 points). An entirely
positive interval is a win (1 point). Forfeiture overrides those outcomes;
if both bots forfeit, both get zero points.

The supplied AGENTS.md gives no enum, observation, result, evaluator-helper
or config-field inventory to contradict. The more detailed earlier pasted
specification's names, category ordering, stack/blind values and raise cap
agree with the source. Its first-millisecond grace is literal; any phrase
implying all network time is free is less precise than the actual formula.

The PDF's `python test_agent.py` command does not invoke pytest collection;
use `python -m pytest -q`, as the pasted project instructions specify.

## Benchmark and collection

`tools/benchmark_evaluator.py` makes 10,000 individually timed calls with
varied, pre-generated legal hole/board tuples after warming the table and
200 untimed calls. Warmup and dealing are excluded. Clock-call overhead is
included. Median on this machine: **15,000 ns = 15.0 microseconds per call**.

`python -m pytest --collect-only -q tests` collected 19 existing tests.
The `bot/`, `tests/`, and `tools/` directories all contain empty
`__init__.py` files. Full suite: **31 passed**, with one existing
Starlette/httpx deprecation warning.

Required unchanged-strategy match: 200 deals per half, seed 7, RandomBot.
`AGENT1_WIN`, +6.237 bb/deal, 95% CI [+3.218, +9.257]. Zero errors, forfeits
or exhaustion; charged thinking time 0.08 s / 0.02 s. `git diff --check`
passed. Strategy files and the agent entry points are unchanged in Task 0.
