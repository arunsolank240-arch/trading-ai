---
name: india-entry
description: >-
  Entry Timer for NSE stocks. Watches a setup bar by bar and tells you the
  moment to get in. Reads free Yahoo 1-minute or 5-minute bars (NSE symbols
  take .NS), builds the opening range (9:15 to 9:30 AM IST by default) and
  calls the entry on the first completed bar that CLOSES above the range
  high, or above a level you give it (like a 20-day high from the scanner),
  with an optional volume check. Says waiting and how far, triggered with the
  time and the price, expired, or not open yet, and writes trader/entry.json
  for /india-exit. Long side only. It never places an order. Use when the
  user says "tell me when to get in", "watch RELIANCE", "has it broken out",
  "did it break the opening range", "entry signal", "time my entry", "check my
  watchlist", or after /india-scanner and /india-news, before /india-exit.
argument-hint: "[SYMBOL] [--setup orb|level] [--interval 5m|1m]"
---

# india-entry

`${CLAUDE_SKILL_DIR}` below is this skill's folder.

```bash
python3 "${CLAUDE_SKILL_DIR}/entry.py" check RELIANCE                       # status right now
python3 "${CLAUDE_SKILL_DIR}/entry.py" check RELIANCE --write               # also save trader/entry.json
python3 "${CLAUDE_SKILL_DIR}/entry.py" check RELIANCE --setup level --level 1405.00
python3 "${CLAUDE_SKILL_DIR}/entry.py" check RELIANCE --min-volume-x 1.5    # trigger bar volume vs the range's average
python3 "${CLAUDE_SKILL_DIR}/entry.py" watch RELIANCE --every 30 --until 15:15
python3 "${CLAUDE_SKILL_DIR}/entry.py" watchlist                            # every hit in trader/watchlist.json
```

Symbols are NSE symbols (RELIANCE, M&M); the `.NS` suffix is added for Yahoo.
`--now "2026-10-19 10:00"` pins the clock (IST). `--or-minutes 15`,
`--interval 5m|1m`, `--json`, `--offline PATH` as in the other skills.

## How the call is made

- The **opening range** is the first `--or-minutes` of the session: 9:15 to
  9:30 AM. Its high and low come from the bars in that window.
- **Triggered** = the first completed bar after the range whose CLOSE is above
  the range high (or the level). A wick above is not a trigger. A bar counts
  only once complete.
- **Waiting** shows how far the price is from the trigger. **Expired** = no
  trigger by `no_entries_after` (default 14:45 IST). **Not open yet** before
  9:15 AM, on weekends, NSE holidays and the Muhurat special session.
- The first 15 minutes of the NSE session are the most volatile of the day:
  wide spreads, gaps from the pre-open auction, fakeouts. The range exists to
  let that settle; it does not make a breakout safe.

## Steps

1. `check SYMBOL --write` (or `watchlist` for several).
2. Tell the user the status in plain words. Waiting: say how far and what it
   needs. Triggered: the time and the close. Never say "buy now".
3. If triggered, next: `/india-exit` (stop and target BEFORE any entry).

## Limits to say out loud

- A trigger is a rule met on delayed free data, not a prediction.
- Nothing here places an order. Not financial advice.
