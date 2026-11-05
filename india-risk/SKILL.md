---
name: india-risk
description: >-
  Risk Manager for NSE day trades. Checks every proposed order against your
  limits and stops anything over them, before you place it. A stop is
  required, the loss at the stop must fit your max loss per trade (measured
  from the higher of the plan's entry and a fresh price), reward:risk must
  meet your minimum, the day's total risk must fit your daily loss limit, no
  more than your trades per day, and no new entries outside your entry window
  or when the NSE is closed (weekend, holiday, Muhurat special session). It
  also checks the format the exchange needs (whole shares, prices on the 0.05
  tick, day orders), intraday MIS only, plain NSE equity symbols only (no
  F&O), blocked tickers, order size, position cap, cash buffer, margin, short
  sales, duplicates and a daily order limit. Getting out is never blocked by a
  day limit. Prints PASS or BLOCK with the reason and records the verdicts so
  india-broker only shows an order that passed. Use when the user says "check
  my order", "is this safe", "risk check", "does this break my rules", "can I
  take this trade", "how much have I risked today", or before /india-broker,
  always.
argument-hint: "[path to orders.json]"
---

# india-risk

A rules check, not a recommendation. `${CLAUDE_SKILL_DIR}` is this skill's folder.

```bash
python3 "${CLAUDE_SKILL_DIR}/check.py"                          # trader/orders.json -> trader/state/risk.json
python3 "${CLAUDE_SKILL_DIR}/check.py" --now "2026-10-19 10:00" # pin the clock (IST)
python3 "${CLAUDE_SKILL_DIR}/check.py" --json
python3 "${CLAUDE_SKILL_DIR}/check.py" --no-write               # check without recording the verdicts
```

Exit code 0 when every order passes, 1 when any is blocked. No network.

## What it reads

`trader/orders.json` (india-budget or `ticket.py flatten`), `trader/config.json`
(your rules), `trader/portfolio.json` (cash and shares; without it, a fresh
account funded with `budget`), `trader/prices.json` (india-alerts), and
`trader/state/broker.json` (what was decided today).

## What blocks an order

Every order: **format** (symbol, side, a whole-share qty, prices on the tick,
time in force day or ioc, no extended hours, a bracket plan with both legs),
**asset** (F&O contracts unless `allow_options`; anything that is not a plain
NSE symbol, so `RELIANCE`, not `RELIANCE.NS`), **short** (selling more than
you hold unless `allow_short`).

An entry on top: **product** (MIS only: CNC delivery holds overnight), the
**blocked** list, **size** (min and max order in rupees), **position** cap,
**cash** (the buffer; margin is off, and MIS brokers will lend several times
your cash: this pack does not), **duplicate**, **daily limit** on orders,
**stop** required and on the right side, **loss** at the stop over
`max_loss_per_trade_inr`, **reward:risk** under `min_reward_risk`, **daily
loss** over `max_daily_loss_inr`, **trades** over `max_trades_per_day`, and the
**window**: before `no_entries_before` (09:30), after `no_entries_after` (14:45),
or the market closed.

An exit (a sell that only reduces what you hold) is checked for format,
asset and short sales only. Everything else becomes a warning: getting out
must always be possible.

## Steps

1. Run `check.py`. Read each verdict to the user in plain words: PASS or
   BLOCK, and every reason.
2. A BLOCK is final for this order. Do not edit the order, the config or the
   clock to make it pass. If a rule is wrong for the user, they change
   `trader/config.json` themselves and you run the check again.
3. A PASS means "inside your rules", nothing more. Next: `/india-broker`.

## Not checked (say it)

NSE price bands (circuit limits), the ASM / GSM surveillance lists, the
broker's own margin and risk rules, and the day's news. A stock at its circuit
cannot fill a stop. The holiday list covers 2026 only: it warns outside that.

Education and tooling, not financial advice.
