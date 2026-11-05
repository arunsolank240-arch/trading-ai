---
name: india-scanner
description: >-
  Chart Scanner for the Indian market. Scans every NSE equity (EQ series)
  for setups: opening-range breakouts, 20-day breakouts, bull flags, reclaimed
  20-day average, oversold bounces. Builds the stock list from NSE's own
  EQUITY_L.csv, runs a pre-market scan of daily closes and an intraday
  opening-range breakout scan on 5-minute bars (9:15 to 9:30 AM IST range),
  then writes trader/watchlist.json for india-news and india-entry. Free Yahoo
  data (NSE symbols take a .NS suffix). Use when the user says "scan the NSE",
  "scan the market", "find me setups", "what is breaking out", "opening range
  breakouts", "oversold stocks", "pre-market scan", "build my watchlist",
  "what should I look at today", or at the start of a trading day before
  /india-news.
argument-hint: "[universe | daily | orb] [--at HH:MM]"
---

# india-scanner

The first step of a day trade. It reads many free charts and lists the ones
that match a rule. A scan is a list of charts that match a rule, not a list of
stocks to buy, and a setup on a chart is not a prediction. Most retail day
traders lose money; the scanner does not change that, it only saves you from
flipping through 2,000 charts by hand.

`${CLAUDE_SKILL_DIR}` below is this skill's folder (where this SKILL.md lives).

```bash
python3 "${CLAUDE_SKILL_DIR}/scan.py" universe                          # NSE EQUITY_L.csv -> trader/universe.txt
python3 "${CLAUDE_SKILL_DIR}/scan.py" daily                             # before 9:15 AM -> trader/watchlist.json
python3 "${CLAUDE_SKILL_DIR}/scan.py" daily --symbols RELIANCE,TCS,INFY # or --watchlist FILE, --limit 200
python3 "${CLAUDE_SKILL_DIR}/scan.py" orb                               # after 9:35 AM IST -> trader/watchlist.json
python3 "${CLAUDE_SKILL_DIR}/scan.py" orb --at 10:00                    # cut the clock at 10:00 AM IST
```

Flags: `--min-price 50` and `--min-volume` (daily 500,000 shares, orb 0),
`--or-minutes 15`, `--max-confirm 200` (orb stage 2), `--now "2026-10-19 10:00"`
(IST) to pin the clock, `--offline PATH`, `--no-write`, `--show N`, `--json`.
Exit code 0 when the scan found something, 1 when it found nothing or could
not run (the reason is one plain line).

## What it reads and writes

| file | what |
| --- | --- |
| `trader/universe.txt` | written by `universe`: one `SYMBOL\|Name` a line |
| `trader/watchlist.json` | written by `daily` and `orb`: `mode`, `as_of`, `hits[]`. india-news and india-entry read `hits[].symbol` |
| `trader/config.json` | read by `orb`: `no_entries_after` (default 14:45) |

## The universe

`universe` downloads NSE's `EQUITY_L.csv` and keeps the rows of the **EQ**
series with a plain symbol (letters, digits, `&`, `-`: RELIANCE, M&M,
BAJAJ-AUTO). BE (trade-for-trade), SM (SME) and other series are dropped:
they cannot be bought and sold the same day the usual way.

NSE sometimes refuses scripted downloads. If `universe` fails, save
EQUITY_L.csv from a browser into a folder and run `scan.py universe --offline
FOLDER`, or skip the list: `--symbols RELIANCE,TCS,...` or `--watchlist FILE`.

## Setups

- **daily** (closes only, 3 months): `breakout_20d`, `bull_flag`,
  `reclaim_ma20`, `oversold` (RSI 14 under 30), `oversold_bounce`. Today's
  daily bar is dropped until 3:30 PM IST.
- **orb**: the range is the first `--or-minutes` (15): 9:15 to 9:30 AM. A hit
  is the first completed 5-minute bar that CLOSES above the range high.
  Stage 1 uses closes for everyone; stage 2 re-checks candidates with real
  highs and lows (the most traded first, at most `--max-confirm`).

## Steps

1. If `trader/universe.txt` is missing or old, run `universe`.
2. Before the open: `daily`. After 9:35 AM IST: `orb`.
3. Show the user the hits plainly (symbol, setup, price). Say it is a list of
   matches, not advice.
4. Next: `/india-news TICKER` for what is happening in the stock, then
   `/india-entry TICKER`.

## Limits to say out loud

- Yahoo is free, unofficial and can lag or change. NSE prices there are for
  scanning, not for timing an order. The broker's price is the one that fills.
- NSE price bands (circuit limits) and the ASM / GSM lists are not checked: a
  stock stuck at its circuit cannot fill a stop. Look before trading it.
- Nothing here places an order. Education and tooling, not financial advice.
