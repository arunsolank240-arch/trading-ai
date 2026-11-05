---
name: india-budget
description: >-
  Budget Manager for NSE day trades. Sizes every position to your budget and
  your max loss per trade in rupees. Reads the trade plan from india-exit
  (entry, stop, target), finds the whole shares that fit inside four limits
  (max loss per trade including estimated charges, position cap, max order,
  cash after your buffer), says which limit decided it, and writes ONE
  proposed intraday (MIS) trade with its stop-loss and target to
  trader/orders.json. Estimates the round-trip charges (brokerage, STT, stamp
  duty, exchange fee, SEBI fee, GST) and refuses a trade whose target does not
  even cover them. A stop too far away for your max loss is a plain refusal,
  not a smaller order. Nothing is placed. Use when the user says "how many
  shares", "size this trade", "how much should I buy", "I have 1 lakh", "I
  only want to risk 500 rupees a trade", "set my rules", "keep 10% in cash",
  or after /india-exit writes a plan.
argument-hint: "[budget in rupees]"
---

# india-budget

`${CLAUDE_SKILL_DIR}` below is this skill's folder.

```bash
python3 "${CLAUDE_SKILL_DIR}/size.py"                          # trader/plan.json + trader/config.json
python3 "${CLAUDE_SKILL_DIR}/size.py" --write                  # write trader/orders.json
python3 "${CLAUDE_SKILL_DIR}/size.py" --limit --write          # a limit order at the plan's entry (recommended)
python3 "${CLAUDE_SKILL_DIR}/size.py" --limit 1401.40 --write
python3 "${CLAUDE_SKILL_DIR}/size.py" --budget 100000 --json
```

Exit code 0 when an order was sized, 1 on a refusal (the reason is plain).

## The rules, in `trader/config.json`

`config.example.json` has every key with a small-account default. The ones that
matter: `budget` (rupees), `max_loss_per_trade_inr`, `max_daily_loss_inr`,
`max_position_pct`, `max_order_inr`, `min_order_inr`, `cash_buffer_pct`,
`min_reward_risk`, `max_trades_per_day`, `no_entries_before` (09:30),
`no_entries_after` (14:45), `flat_by` (15:15), `tick_size` (0.05).
**The user sets these. Do not invent a budget or a loss limit for them.**

## How many shares

Whole shares (NSE has no fractions): the smallest of
max loss / (risk per share, with estimated charges at the stop), position cap,
max order and cash after the buffer. The report names the limit that decided.
A market order is sized at the higher of the plan's entry and a fresh price
(under 15 minutes old) because a price that ran up means a bigger loss at the
same stop. Prefer `--limit`: plain market orders can fill a few ticks away
from the plan, and some brokers reject them on thin stocks.

## Charges (estimates)

Intraday equity on the NSE: brokerage on both legs, STT 0.025 % of the sell
value, stamp duty 0.003 % of the buy value, NSE transaction charge about
0.00297 %, SEBI fee Rs 10 a crore, 18 % GST on brokerage + exchange + SEBI.
Defaults assume a discount broker (Rs 20 or 0.03 % a leg, whichever is
lower). Your broker's contract note is the truth: set `"charges": {...}` in
the config to match it, or `"charges": false` to turn the estimate off. The
report shows the break-even move per share, the loss at the stop and the
profit at the target, all after charges. On a small R they are a large part
of the profit, and a trade whose target does not cover them is refused.

## Steps

1. Run `size.py --limit` (add `--write` once the user is happy).
2. Read the report plainly: shares, cost, max loss at the stop, charges, the
   all-in loss and gain, which limit bound the size.
3. A refusal is a result. Do not shrink the stop or the rules to get an order.
4. Next: `/india-risk`.

## Never

- Never invent the budget or the max loss. Never size a short, an F&O
  contract, a delivery (CNC) trade or a leveraged position here.
- Never place anything. This writes a proposal.
- Not financial advice. Education and tooling.
