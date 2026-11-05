---
name: india-broker
description: >-
  Order Ticket and Your Yes, for NSE day trades. Turns an order that
  india-risk passed into a plain ticket and a checklist for YOUR broker's app
  (Zerodha Kite, Dhan, Upstox, Angel One, Groww...): the intraday (MIS) entry,
  then the stop-loss, then the target, and "cancel the other when one fills".
  Records your explicit yes word for word, one order at a time, then records
  what happened. Builds the sell ticket that closes a day trade by your
  flat-by time, records fills in trader/portfolio.json, and logs each trade's
  max loss so india-risk can hold the daily limit. It never sends an order:
  Claude does not place orders in this pack. Use when the user says "place
  the order", "buy it", "execute", "send it to my broker", "close my
  position", "flatten", "get me out", "record my fill", or after /india-risk
  passes.
argument-hint: "[order number]"
---

# india-broker

The most careful skill in the pack, because it is the last step before real
money. In India there is no free paper-trading broker connector like Alpaca's,
so the default is **manual**: Claude prepares the ticket and records your yes;
**you** place the order in your broker's app. Nothing is sent from here.

An order is ready for you to place only after two separate gates, every time,
for every order:

1. **india-risk passed this exact order today** (matched by fingerprint).
2. **The user typed an explicit yes for this one order** in the chat.

Then the user places it themselves. No yes, no ticket to act on.

`${CLAUDE_SKILL_DIR}` below is this skill's folder.

```bash
python3 "${CLAUDE_SKILL_DIR}/ticket.py" show                      # every ticket, READY or not
python3 "${CLAUDE_SKILL_DIR}/ticket.py" approve --index 1 --reply "yes"
python3 "${CLAUDE_SKILL_DIR}/ticket.py" result --index 1 --status placed --broker-id ID --filled-qty 53 --filled-price 1401.40
python3 "${CLAUDE_SKILL_DIR}/ticket.py" fill --symbol RELIANCE --side sell --qty 53 --price 1410.50
python3 "${CLAUDE_SKILL_DIR}/ticket.py" flatten --symbol RELIANCE --qty 53
python3 "${CLAUDE_SKILL_DIR}/ticket.py" log
```

`ticket.py` never talks to a broker. It renders tickets, checks that a reply
is a real yes for that order, builds the flatten ticket and keeps the log in
`trader/state/broker.json`. `--now "2026-10-19 10:00"` pins the clock (IST).

## What it reads and writes

| file | what |
| --- | --- |
| `trader/orders.json` | the proposed orders (india-budget writes it; `flatten` replaces it) |
| `trader/state/risk.json` | india-risk's verdicts; only a PASS from today is READY |
| `trader/state/broker.json` | every yes, no, placed, failed and filled, with each entry's max loss |
| `trader/portfolio.json` | cash and shares, updated by `fill` and by `result --filled-qty` |
| `trader/plan.json` | the flat-by time for `flatten` |

## Steps: the entry

1. `ticket.py show`. Only READY tickets go to the user. A ticket that is NOT
   READY or BLOCKED goes back to `/india-risk`.
2. Show ONE ticket and ask: "Will you place this order? Reply yes or no." One
   order per question. Never offer "yes to all".
3. Run `ticket.py approve --index N --reply "<the user's reply, word for word>"`.
   If it prints "Not recorded", the reply was not an explicit yes for this
   order ("sure", "ok", "yes to all", a yes that names a different stock or
   amount). Ask again. Never turn a reply into a yes yourself.
4. After "Recorded your yes", give the user the steps the tool printed. They
   place, in their own app: the MIS entry; **the stop-loss as soon as it
   fills**; the target; and they cancel the other leg when one fills (most
   brokers no longer link them). A bracket order is no longer offered by most
   Indian brokers, which is why this is a checklist.
5. Record what happened: `ticket.py result --index N --status placed
   --broker-id <id> --filled-qty Q --filled-price P`, or `--status denied`
   (the user decided not to), or `--status failed` with `--note` (the broker
   refused it). A failed order is not retried without a new check and a new yes.

## Steps: while it is open, and out by the close

- india-alerts watches the stop, the target and the flat-by time
  (`alerts.py add --from-plan`). An alert is a reminder: the stop-loss order
  at the broker is what stops the loss.
- When the stop-loss or the target fills, record it: `ticket.py fill
  --symbol RELIANCE --side sell --qty 53 --price 1400.10`, and remind the user
  to cancel the other leg.
- By `flat_by` (15:15 IST), anything still open gets closed:
  1. Ask the user how many shares they hold (their broker's positions page).
  2. `ticket.py flatten --symbol RELIANCE --qty 53` writes a market sell.
  3. `/india-risk` (a sell that only closes what they hold is never blocked by
     the day limits), then `ticket.py show` and their yes for that one order.
  4. The open stop-loss and target hold those shares at the broker: they
     cancel both first, then place the sell.
- Brokers auto-square-off MIS positions around 3:15 to 3:25 PM and charge for
  it. The user's broker's exact time is theirs to look up.

## Optional: a broker connector

Some Indian brokers publish MCP servers or APIs (Dhan has an official one;
Zerodha's hosted Kite MCP has been read-only apart from GTT, as of the pages
read on 2026-11-01; exchange rules for retail algo orders include things like
a registered static IP). **These talk to a real account: there is no paper
mode behind them.** This pack does not set one up and Claude does not place
orders through one unless the user has chosen to, has read their broker's
documentation, and keeps that connector's order tool on "Needs approval",
never "Always allow". Even then both gates above come first, for every order.
`show --json` always lists the entry, stop-loss and target with Kite Connect's
parameter names (`kite_orders`) as a reference; `"broker": "kite"` in
`trader/config.json` only adds a hint line to `show`. This tool sends none of it.

## What it never does

- Never sends an order, and never two orders on one yes.
- Never acts from a scheduled or background task: nobody is there to say yes.
- Never asks for, reads, stores or repeats API keys, passwords, TOTP codes or
  access tokens. If the user pastes one, tell them to delete the message and
  regenerate it at the broker.
- Never switches `"paper"` to false for the user. They do that themselves.
- Never promises a fill price: a market order and a stop fill at whatever the
  market gives, and a stock at its circuit may not fill at all.

## Safety

- Education and tooling, not financial advice. A PASS is a rules check, not a
  recommendation.
- `"paper": true` (the default) means PRACTICE: the ticket says so, and the
  user rehearses without placing anything. Going live is their decision.
- No F&O, margin, short selling, delivery (CNC) or leverage here unless the
  config allows it and the user confirms in their own words.
- Intraday trading profits and losses are taxed as business income in India:
  keep the contract notes and ask a chartered accountant. Nothing here is tax
  advice.
