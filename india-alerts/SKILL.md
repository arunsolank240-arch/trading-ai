---
name: india-alerts
description: >-
  Price Alerts and the NSE clock. Rings when a price, a stop or the opening
  bell hits. Turns the trade plan into three alerts in one go (the stop, the
  target and "flat by close" at your flat-by time), plus above / below / stop
  / target levels, percent moves from the previous close, any time of day, and
  the NSE opening bell, each ringing once so you are not spammed. Knows NSE
  hours (9:15 AM to 3:30 PM IST) and the 2026 weekday holidays and the Muhurat
  special session, fetches free delayed quotes (Yahoo chart JSON) one ticker
  at a time, and writes trader/prices.json for sizing and the risk check. Use
  when the user says "alert me when", "tell me if RELIANCE hits", "watch my
  stop", "watch my trade", "remind me to close by 3:15", "is the market open",
  "when does the market open", "get me a price", or right after /india-exit
  writes a plan.
argument-hint: "[symbol] [price]"
---

# india-alerts

`${CLAUDE_SKILL_DIR}` below is this skill's folder.

```bash
python3 "${CLAUDE_SKILL_DIR}/alerts.py" clock                          # is the NSE open? next open / close
python3 "${CLAUDE_SKILL_DIR}/alerts.py" quote RELIANCE --write         # quotes -> trader/prices.json
python3 "${CLAUDE_SKILL_DIR}/alerts.py" add --from-plan                # stop, target and flat-by from trader/plan.json
python3 "${CLAUDE_SKILL_DIR}/alerts.py" add --symbol RELIANCE --stop 1400.10
python3 "${CLAUDE_SKILL_DIR}/alerts.py" add --symbol INFY --pct 3
python3 "${CLAUDE_SKILL_DIR}/alerts.py" add --opening-bell
python3 "${CLAUDE_SKILL_DIR}/alerts.py" check                          # rings what hit, once; exit 1 if nothing rang
python3 "${CLAUDE_SKILL_DIR}/alerts.py" list
python3 "${CLAUDE_SKILL_DIR}/alerts.py" reset reliance-plan-stop
```

`--now "2026-10-19 10:00"` pins the clock (IST). Symbols are NSE symbols. Rules
live in `trader/alerts.json`; see `alerts.example.json`.

## Rule types

`above` / `target`, `below` / `stop`, `pct_move` (percent from yesterday's
close), `opening_bell`, `time` (an IST time on a trading day). An above/below
alert rings once and stays quiet until reset (unless `"rearm": true`). A rule
with a `date` is only watched that day: plan alerts are for the plan's day.

## Steps

1. `clock` first if you are unsure the market is open (weekends, NSE
   holidays and the Muhurat special session count as closed here).
2. After `/india-exit`: `add --from-plan`.
3. Run `check` every few minutes while a trade is open (a scheduled task or
   a loop in Claude Code). Read each ring to the user at once.
4. When the stop-loss or the target fills at the broker, record it with
   `/india-broker` (`ticket.py fill`) and cancel the other leg.

## Limits to say out loud

- Quotes are free, delayed and unofficial (Yahoo has no second source for
  NSE here). **An alert is not a stop.** The stop-loss ORDER you place at your
  broker is what stops you out; an alert is a reminder to look.
- This tool does not place or cancel orders, and nothing here runs while
  Claude is closed.
- The holiday list covers 2026. NSE publishes each year's list in its own
  circular: check nseindia.com.
