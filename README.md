# india-trader-skills

Nine agent skills for **intraday trading on the Indian market (NSE)**: scan
stocks, check the news, time the entry, plan the exit, replay the odds, size the
position, check the risk, and turn the result into a ticket that **you** place at
your own broker.

It is an India port of [Jakeschincariol/day-trader-skill](https://github.com/Jakeschincariol/day-trader-skill)
(MIT; the original is US-only). Same workflow and the same safety rules, rebuilt for
NSE hours, holidays, rupees, the 0.05 tick, MIS orders and Indian trading charges.

> **Read this first.**
> - This is education and tooling, **not financial advice**. A scan is a list of charts that match a rule, not
>   a list of stocks to buy. Most retail day traders lose money, and the tools here do not change that.
> - **It was built and tested offline, on synthetic data.** It has not been run against live NSE, Yahoo or NSE
>   website data. Treat the first live runs as a test, and check every number against your broker's screen.
> - Nothing in this pack places an order. You place it, in your broker's app.
> - Intraday profits and losses are taxed as business income. Keep your contract notes and ask a chartered accountant.

## The workflow

```
scanner -> news -> entry -> exit -> timemachine -> budget -> risk -> broker (ticket + your yes)
                                   alerts (stop / target / flat-by) run during the trade
```

| skill | what it does |
| --- | --- |
| `india-scanner` | NSE EQ-series stock list, pre-market daily scan, opening-range breakout scan (9:15 to 9:30 AM range) |
| `india-news` | Yahoo + Google News India headlines, NSE corporate announcements (best effort), move vs yesterday's close |
| `india-entry` | calls the entry: first 5-minute bar that CLOSES above the opening-range high (or a level) |
| `india-exit` | stop (range midpoint by default) and target (2R by default) on the 0.05 tick, before you enter |
| `india-timemachine` | 10,000 replays of the rest of the session from the stock's own 75-bar sessions + the rule on every past session |
| `india-budget` | whole shares from your budget, max loss, position cap, cash; counts STT, GST, stamp duty, brokerage; refuses a trade that cannot pay its charges |
| `india-risk` | PASS / BLOCK against your rules: stop required, max loss, daily loss, trades a day, entry window, tick, whole shares, MIS only, no F&O |
| `india-broker` | the ticket as a checklist for your broker's app, your yes recorded word for word, fills, flatten ticket |
| `india-alerts` | the NSE clock and holidays, price / stop / target / flat-by alerts |

## What is different from the US version

- **Hours and calendar**: 9:15 AM to 3:30 PM IST, no daylight saving, no early closes. The 2026 NSE weekday holidays
  are built in; the Muhurat session (2026-11-08) counts as closed. **2027's list is not published yet**: the tools warn
  outside 2026 until you add it (`NSE_HOLIDAYS`, `CALENDAR_YEARS`).
- **Symbols**: NSE symbols (RELIANCE, M&M, BAJAJ-AUTO); Yahoo gets `.NS`.
- **Orders are by whole shares**, prices on the 0.05 tick, product MIS (intraday), day validity. Delivery (CNC), F&O,
  margin and shorts are off by default.
- **No bracket order, no paper account**: most Indian brokers no longer offer a linked bracket order, and there is no
  Alpaca-style free paper connector. So `india-broker` gives you a checklist (entry, then stop-loss, then target, cancel
  the other when one fills) and `"paper": true` means *practice, do not place it*.
- **Charges are part of the math**: a 1R trade on a small move often cannot pay brokerage + STT + GST + stamp duty, and
  `india-budget` says so and refuses it. Defaults are a typical discount broker's; put your own in `trader/config.json`.
- **Not ported**: the US-only `trader-analyst` (SEC filings) and `trader-pelosi` (congressional trades) skills. There is no
  equivalent free, stable source for them in India that I could verify.

## Install

Skills are folders with a `SKILL.md`. Copy the nine `india-*` folders into your agent's skills folder:

- Claude Code: `~/.claude/skills/` (all projects) or `.claude/skills/` (one project)
- Antigravity: `~/.gemini/antigravity/skills/` or `.agents/skills/` in the project
- claude.ai: zip each folder and add it in Settings > Capabilities > Skills

They run Python 3.8+ scripts (standard library only), so use an environment that can run code and reach the internet.
Optionally copy `GEMINI.md` into your project root: it tells an agent the order of the steps and the safety rules.

Everything is written to a `trader/` folder in your working directory. Start from `india-budget/config.example.json`:
copy it to `trader/config.json` and **set your own numbers**: budget, max loss per trade, daily loss.

## Try it without risking anything

```bash
python3 tests/make_fixtures.py                      # synthetic NSE-shaped data, no network
python3 -W ignore -m unittest tests/test_india.py -v
python3 india-scanner/scan.py orb --offline tests/fixtures/orb-bundle-2026-10-19.json --now "2026-10-19 10:00" --min-price 0 --no-write
```

Then, on a live trading day, in this order: `scan.py daily` before 9:15, `scan.py orb` after 9:35, `news.py`, `entry.py check
SYMBOL --write`, `exit.py plan --write`, `timemachine.py run --write`, `size.py --limit --write`, `check.py`, `ticket.py show`.

## Known limits

- Free Yahoo data is unofficial, delayed and can change or block. The NSE website API (announcements, the stock list)
  sometimes refuses scripts; the tools say so and carry on where they can.
- Circuit limits (price bands) and the ASM / GSM lists are not checked. A stock at its circuit cannot fill your stop.
- Brokers square off MIS positions around 3:15 to 3:25 PM and charge for it; the exact time is your broker's.
- Charges are estimates. Retail algo-order rules (for example a registered static IP for API orders) are your broker's and
  SEBI's; this pack does not place API orders.
- The Time Machine is a simulation from a stock's own recent bars. It is not a prediction.

MIT licence: see `LICENSE` (original copyright kept; the India changes are under the same licence).
