---
name: india-news
description: >-
  News Monitor for NSE stocks. Tracks news on every stock you watch: Yahoo
  Finance and Google News India headlines per ticker, NSE corporate
  announcements (board-meeting outcomes, results, orders, rating changes,
  takeover and insider disclosures; best effort, NSE sometimes refuses
  scripts), and how far each stock is from yesterday's close. Shows only what
  is new since the last check, newest first, in IST, tags each item
  (earnings, analyst, deal, halt, regulatory, macro) and never repeats one.
  Use when the user says "any news on RELIANCE", "why is this moving", "what's
  the news on my watchlist", "morning briefing", "pre-market news", "did
  anything break", "check the announcements", or after /india-scanner finds
  setups.
argument-hint: "[tickers]"
---

# india-news

Watches the news for the tickers you care about and prints only what is new.

`${CLAUDE_SKILL_DIR}` below is this skill's folder.

```bash
python3 "${CLAUDE_SKILL_DIR}/news.py"                              # watchlist + plan + portfolio tickers
python3 "${CLAUDE_SKILL_DIR}/news.py" --tickers RELIANCE TCS INFY
python3 "${CLAUDE_SKILL_DIR}/news.py" --tickers RELIANCE --all --hours 72
python3 "${CLAUDE_SKILL_DIR}/news.py" --no-filings                 # headlines only
python3 "${CLAUDE_SKILL_DIR}/news.py" --no-moves --json
```

Exit code 0 when something new was shown, 1 when nothing was.

## Sources (one request each, per ticker)

| source | what | note |
| --- | --- | --- |
| Yahoo Finance RSS | headlines for `SYMBOL.NS` | free, can be thin for small stocks |
| Google News India RSS | a search for `SYMBOL NSE share` | a short symbol (ITC, LT) can bring noise |
| NSE corporate announcements | board outcomes, results, orders, ratings, disclosures | **best effort**: NSE's API wants the cookies its home page sets and sometimes refuses scripts. The tool says so and the headlines still run |
| Yahoo chart | last price vs yesterday's close; `MOVING` flag at 3 % (`--move-pct`) | |

An NSE announcement is marked `!` when its subject looks important (outcome of
board meeting, financial results, acquisition or merger, credit rating, fraud,
default, bonus, split, buyback, large orders, open offer, SEBI order...).
Trading-window notices and routine filings are not.

## State

`trader/state/news.json` remembers what you have seen (30 days), so an item
shows once. `--all` shows seen items too; `--dry-run` does not update it.

## Steps

1. Run it for the scanner's hits, or the tickers the user names.
2. Read the headlines to the user in plain words. Say which are NSE filings
   (primary) and which are press (leads). Never present a headline as fact.
3. A stock far from yesterday's close with no news is worth a pause: ask why
   before an entry. Results, bulk deals and sector news often explain it.
4. Next: `/india-entry TICKER`.

## Limits to say out loud

- Headlines are leads, not facts: open the story before acting.
- Free sources lag. A result or order win can be on the exchange minutes
  before it reaches any feed here.
- Not financial advice.
