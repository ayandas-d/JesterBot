# PART A: Project context

## What we are building

A Python bot for the TAMU Datathon Poker Bot Challenge: heads-up Short Deck 5-Card Pot-Limit Omaha. Our bot plays every other team's bot in a round-robin tournament. Each match is 2,000 hands (1,000 deals played twice with seats swapped, "duplicate" format, so both bots get identical cards).

A match is won only if the 95% confidence interval of our average bb/deal is entirely above 0. Otherwise it is a chop (0.5 points). A forfeit in either half is an automatic match loss.

## Ground rules for you (Codex)

- Only edit code between # ===== YOUR CODE HERE ===== and # ===== END OF YOUR CODE ===== in agent.py, plus new modules that agent.py imports (put them in a bot/ package) and new files under tests/ and tools/.
- Never edit the SERVER PLUMBING section of agent.py, game.py, evaluator.py, judge_engine.py, baseline-bots/, or test_agent.py. The tournament uses its own copies of the engine files anyway.
- game.py and evaluator.py are the source of truth. If anything in this document disagrees with them (field names, enum names, function names, constants), follow the code and tell me about the difference.
- Never interfere with the judge, the opponent's server, or the machine. No network sniffing, no contacting the opponent, no sleep() calls in our bot.
- Don't add dependencies unless truly needed. The base image already has FastAPI, uvicorn and PyTorch (CPU). Don't change the pins in requirements.txt for fastapi/uvicorn.
- After every task: run the full test suite, run a 200-deal match against baseline_random.py, report results, then git commit with a clear message.
- If a requirement is ambiguous, ask me before guessing.

Phase 2 work follows codex_phase2_adversarial.md. Its Part 5 rules apply on top of the existing loop rules.
