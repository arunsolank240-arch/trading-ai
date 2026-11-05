---
name: india-exit
description: >-
  Exit Planner for NSE stocks. Sets your stop and your target before you
  enter, so you know when to get out. Reads the entry from india-entry (or a
  price you give), puts the stop at the opening-range midpoint by default (or
  the range low, your price, a percent, or a multiple of the ATR), rounds it
  to the NSE tick of 0.05 (down, away from the entry), and sets the target at
  2R (or 1R, or your price), also on the tick. Refuses a stop at or above the
  entry, a target at or below it, or a stop too tight to survive the spread,
  and says why. Writes trader/plan.json for the Time Machine, the Budget
  Manager and Price Alerts. Long side only. Use when the user says "where's my
  stop", "set my stop and target", "plan the exit", "when do I get out", "stop
  loss", "what's my R", "risk reward", or right after /india-entry triggers,
  before /india-timemachine.
argument-hint: "[--stop or-mid|or-low|price:X|pct:X|atr:K] [--target 2R|1R|price:X]"
---

# india-exit

Decide the exit before the entry. `${CLAUDE_SKILL_DIR}` is this skill's folder.

```bash
python3 "${CLAUDE_SKILL_DIR}/exit.py" plan                              # from trader/entry.json: or-mid stop, 2R target
python3 "${CLAUDE_SKILL_DIR}/exit.py" plan --write                      # save trader/plan.json
python3 "${CLAUDE_SKILL_DIR}/exit.py" plan --stop or-low --target 1R
python3 "${CLAUDE_SKILL_DIR}/exit.py" plan --stop pct:0.8 --target price:1420
python3 "${CLAUDE_SKILL_DIR}/exit.py" plan --symbol TCS --entry 3305.00 --setup level --stop pct:1
python3 "${CLAUDE_SKILL_DIR}/exit.py" show
```

## The rules

- **Stop**: `or-mid` (default, the midpoint of the opening range), `or-low`,
  `price:X`, `pct:X`, or `atr:K` (K times the ATR; needs data). A long's stop
  rounds DOWN to the tick (0.05), away from the entry.
- **Target**: `2R` (default), `1R`, `1.5R`, or `price:X`; rounded to the tick.
  R is the risk per share: entry minus stop.
- **Flat by**: `flat_by` in `trader/config.json` (default 15:15 IST). Most
  brokers auto-square-off intraday (MIS) positions around 3:15 to 3:25 PM and
  charge for it: check your broker's time.
- `tick_size` in `trader/config.json` changes the tick (a few stocks trade in
  0.01 steps).
- Refused, with the reason: a stop at or above the entry, a target at or below
  it, a stop less than 0.05 % of the price away (inside the spread's noise).

## Steps

1. Run `plan --write` after `/india-entry` triggers (or with the user's
   levels).
2. State the stop, the target, the risk per share and the reward:risk in
   plain words. A stop is an order to place at the broker, not a promise:
   a gap or a fast market (or a stock stuck at its circuit) can fill past it.
3. Next: `/india-timemachine` replays the plan, then `/india-budget` sizes it.

## Limits to say out loud

- A 1R target on a small move may not even pay the charges: india-budget
  checks that and refuses a trade that cannot make money after STT, GST,
  stamp duty and brokerage.
- Not financial advice.
