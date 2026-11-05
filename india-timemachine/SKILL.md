---
name: india-timemachine
description: >-
  Time Machine for an NSE day trade. Replays the possible outcomes of a trade
  before you risk a rupee: 10,000 simulated sessions plus every past time the
  setup fired. Takes the plan from india-exit (entry, stop, target), rebuilds
  the rest of the day 10,000 times from the stock's own 5-minute bars over the
  last 60 days (full 75-bar NSE sessions, 9:15 AM to 3:30 PM), and re-runs the
  same rule on every past session. Prints the odds of target first, stop first
  or neither by your flat-by time, where the price sits then, and an honest
  verdict. A simulation, not a prediction. Charges are not counted (india-budget
  counts them). Use when the user says "what are the odds", "test this trade",
  "replay it", "simulate", "has this worked before", "backtest this setup", or
  after /india-exit, before /india-budget.
argument-hint: "[--replays N] [--seed N] [--until HH:MM]"
---

# india-timemachine

`${CLAUDE_SKILL_DIR}` below is this skill's folder.

```bash
python3 "${CLAUDE_SKILL_DIR}/timemachine.py" run                    # trader/plan.json, 10,000 replays, seed 19
python3 "${CLAUDE_SKILL_DIR}/timemachine.py" run --write            # also save trader/timemachine.json
python3 "${CLAUDE_SKILL_DIR}/timemachine.py" run --until 14:30      # end each replay earlier
python3 "${CLAUDE_SKILL_DIR}/timemachine.py" run --seed 7 --replays 20000 --json
python3 "${CLAUDE_SKILL_DIR}/timemachine.py" chart                  # ASCII fan chart of the replays
```

## How it works

1. One request for 60 days of 5-minute bars (Yahoo, `SYMBOL.NS`). Only FULL
   sessions before the plan's date count: 75 bars, 9:15 AM to 3:30 PM IST.
   Muhurat and Saturday special sessions, gaps and today are left out. It needs
   at least 20 full sessions and the entry bar in the data, or it refuses.
2. For each bar slot of the day it pools past bars as ratios to the previous
   close. A replay starts at the entry and walks the rest of the session, each
   bar drawn from a nearby slot of a past session. The stop is checked before
   the target in every bar (the conservative call).
3. Outcomes: target first, stop first, or neither by `--until` (default 15:15,
   the flat-by time). Then the same rule is re-run on every past full session.
4. The verdict compares the target's share of the decided replays with the
   share that breaks even at the plan's R (1/(1+R)).

Same plan, same data and same `--seed` give the same numbers.

## Steps

1. Run it after `/india-exit` has written `trader/plan.json`. Use `--write`.
2. Read the numbers to the user plainly: target first / stop first / neither,
   the median price at the end, the history line, and the verdict as written.
3. **Say what it leaves out**: charges (STT, brokerage, GST, stamp duty) can turn
   a small "win" into a loss, news, results, bulk deals and circuit limits can
   do what the last 60 days never did, and fills are never at the exact price.
4. Next: `/india-budget`.

## Limits to say out loud

- It is built from the stock's own recent bars. It is not a forecast, and a
  "leans toward the target" verdict is not a reason to trade.
- If the plan's entry is far outside the entry bar's range in the data, it
  says so: the plan and the data do not match.
- Education and tooling, not financial advice.
