# Project rules: NSE intraday trading skills (india-trader-skills)

Copy this file to the root of your trading project. It applies to every conversation here.

## The workflow (always in this order)

`india-scanner` -> `india-news` -> `india-entry` -> `india-exit` -> `india-timemachine` -> `india-budget` -> `india-risk` -> `india-broker`.
`india-alerts` runs while a trade is open. Each step reads the previous step's file in `trader/`.
Do not skip a step, and never size or ticket a trade that has no stop.

## Safety rules (never relax these)

1. Nothing places an order. The agent prepares a ticket; **the user places it in their own broker app**.
2. A ticket is READY only if `india-risk` passed that exact order today. A BLOCK is final: do not edit the order,
   the config or the clock to get a PASS.
3. One explicit "yes" per order, recorded with `ticket.py approve`. Never accept "sure", "ok" or "yes to all".
4. `trader/config.json` is the user's. Never invent their budget, max loss or daily loss, and never loosen a limit.
5. Never ask for, read, store or repeat API keys, passwords, TOTP codes or access tokens.
6. Intraday MIS, long, cash equity on NSE only. No F&O, margin, delivery or short selling unless the user turns it on in
   their own config and says so.
7. If a broker connector is ever connected, its order tools stay on "needs approval" and both gates above still come first.

## Facts to keep straight

- NSE session 9:15 AM to 3:30 PM IST, no daylight saving, no early closes. Flat by 15:15 (brokers square off MIS around
  3:15 to 3:25 PM). The holiday list in the scripts covers 2026 only: say so when asked about another year.
- Symbols are NSE symbols (RELIANCE, M&M), never `.NS`. Prices are on the 0.05 tick. Orders are whole shares, in rupees.
- Charges (STT, GST, stamp duty, brokerage) are counted by `india-budget`. The Time Machine does not count them.
- Data is free and unofficial (Yahoo, Google News, NSE website). It can be late or blocked: say what failed, do not guess.
- Python on Windows may be `python` or `py` instead of `python3`.
- Say plainly that this is education and tooling, not financial advice, and that most retail day traders lose money.
