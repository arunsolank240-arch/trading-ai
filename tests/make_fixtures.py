#!/usr/bin/env python3
"""Builds SYNTHETIC NSE-shaped fixtures (not real prices) so the tests run offline.
Monday 2026-10-19 is a normal NSE session. Bars are 5-minute, 9:15 to 15:25 IST."""
import datetime, json, os, random

HERE = os.path.dirname(os.path.abspath(__file__))
FIX = os.path.join(HERE, "fixtures")
os.makedirs(FIX, exist_ok=True)
EPOCH = datetime.datetime(1970, 1, 1)
IST = datetime.timedelta(hours=5, minutes=30)


def ts(day, hh, mm):
    return int((datetime.datetime.combine(day, datetime.time(hh, mm)) - IST - EPOCH).total_seconds())


def day_chart(sym, day, _unused, base, seed, prev_close=None, upto=(15, 25), path=None):
    """path: list of per-bar close offsets in rupees from `base` (cycled/extended with noise)."""
    rnd = random.Random(seed)
    t, o, h, l, c, v = [], [], [], [], [], []
    cur = base
    k = 0
    hh, mm = 9, 15
    while (hh, mm) <= upto:
        step = path[k] if k < len(path) else rnd.choice([-0.3, -0.1, 0.0, 0.1, 0.3])
        op = cur
        cl = round(base + step if k < len(path) else cur + step, 2)
        hi = round(max(op, cl) + rnd.choice([0.2, 0.4, 0.6]), 2)
        lo = round(min(op, cl) - rnd.choice([0.2, 0.4, 0.6]), 2)
        t.append(ts(day, hh, mm)); o.append(round(op, 2)); h.append(hi); l.append(lo); c.append(cl)
        v.append(rnd.randint(20000, 90000))
        cur = cl
        k += 1
        mm += 5
        if mm == 60:
            hh, mm = hh + 1, 0
    return {"chart": {"result": [{
        "meta": {"symbol": sym + ".NS", "currency": "INR", "exchangeName": "NSI", "timezone": "IST",
                 "gmtoffset": 19800, "regularMarketPrice": c[-1], "regularMarketVolume": sum(v),
                 "chartPreviousClose": prev_close or base, "previousClose": prev_close or base},
        "timestamp": t,
        "indicators": {"quote": [{"open": o, "high": h, "low": l, "close": c, "volume": v}]}}],
        "error": None}}


day = datetime.date(2026, 10, 19)
# first 3 bars (9:15, 9:20, 9:25) are the 15-minute opening range
breakout = [0.0, 0.4, 0.2, 1.4, 2.2, 2.4, 2.6, 2.9, 3.1, 3.0]   # closes above the range high at 9:30 bar
flat = [0.0, 0.3, 0.1, 0.2, 0.0, -0.1, 0.1, 0.0, 0.1, 0.0]
weak = [0.0, -0.4, -0.2, -1.0, -1.6, -2.0, -2.2, -2.1, -2.4, -2.6]
bundle = {
    "RELIANCE": day_chart("RELIANCE", day, None, 1400.0, 1, upto=(10, 0), path=breakout),
    "TCS": day_chart("TCS", day, None, 3300.0, 2, upto=(10, 0), path=flat),
    "M&M": day_chart("M&M", day, None, 3100.0, 3, upto=(10, 0), path=weak),
}
with open(os.path.join(FIX, "orb-bundle-2026-10-19.json"), "w") as fh:
    json.dump(bundle, fh)

# a full session for the Time Machine / entry tests
with open(os.path.join(FIX, "RELIANCE-2026-10-19-5m.json"), "w") as fh:
    json.dump(day_chart("RELIANCE", day, None, 1400.0, 11, upto=(15, 25), path=breakout), fh)

with open(os.path.join(FIX, "EQUITY_L.csv"), "w") as fh:
    fh.write("SYMBOL,NAME OF COMPANY, SERIES, DATE OF LISTING, PAID UP VALUE, MARKET LOT, ISIN NUMBER, FACE VALUE\n")
    for row in ["RELIANCE,Reliance Industries Limited,EQ,29-NOV-1995,10,1,INE002A01018,10",
                "TCS,Tata Consultancy Services Limited,EQ,25-AUG-2004,1,1,INE467B01029,1",
                "M&M,Mahindra & Mahindra Limited,EQ,01-JAN-1996,5,1,INE101A01026,5",
                "BAJAJ-AUTO,Bajaj Auto Limited,EQ,01-JAN-1996,10,1,INE917I01010,10",
                "SOMEBE,Some Trade-for-Trade Limited,BE,01-JAN-2010,10,1,INE000000001,10",
                "TINYSME,Tiny SME Limited,SM,01-JAN-2020,10,1,INE000000002,10"]:
        fh.write(row + "\n")
print("fixtures written to", FIX)


# ---- 60 days of SYNTHETIC 5-minute bars for the Time Machine: 30 full sessions ending on `day`
def sixty_day_chart(sym, end_day, base, seed, sessions=30):
    rnd = random.Random(seed)
    holidays = {"2026-10-02"}
    days, d = [], end_day
    while len(days) < sessions:
        if d.weekday() < 5 and d.isoformat() not in holidays:
            days.append(d)
        d -= datetime.timedelta(days=1)
    days.reverse()
    t, o, h, l, c, v = [], [], [], [], [], []
    px = base
    for dd in days:
        hh, mm = 9, 15
        while (hh, mm) <= (15, 25):
            op = px
            cl = round(op * (1 + rnd.gauss(0.0001, 0.0012)), 2)
            hi = round(max(op, cl) * (1 + abs(rnd.gauss(0, 0.0006))), 2)
            lo = round(min(op, cl) * (1 - abs(rnd.gauss(0, 0.0006))), 2)
            t.append(ts(dd, hh, mm)); o.append(round(op, 2)); h.append(hi); l.append(lo); c.append(cl)
            v.append(rnd.randint(20000, 90000))
            px = cl
            mm += 5
            if mm == 60:
                hh, mm = hh + 1, 0
    return {"chart": {"result": [{
        "meta": {"symbol": sym + ".NS", "currency": "INR", "timezone": "IST", "gmtoffset": 19800,
                 "dataGranularity": "5m", "range": "60d", "regularMarketPrice": c[-1],
                 "chartPreviousClose": o[0], "previousClose": o[0]},
        "timestamp": t, "indicators": {"quote": [{"open": o, "high": h, "low": l, "close": c, "volume": v}]}}],
        "error": None}}


with open(os.path.join(FIX, "RELIANCE-60d-5m.json"), "w") as fh:
    json.dump(sixty_day_chart("RELIANCE", day, 1400.0, 7), fh)
print("60-day fixture written")
