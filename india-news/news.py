#!/usr/bin/env python3
"""News monitor for india-news. Standard library only.

Watches headlines and NSE corporate announcements for the stocks you watch or
hold and prints only what is new since the last check, newest first, with how
far each stock has moved today and a flag on anything that touches your tickers.

    python3 news.py                                  # watchlist + plan + portfolio tickers
    python3 news.py --tickers RELIANCE TCS INFY
    python3 news.py --tickers RELIANCE --all --hours 72  # everything in the last 3 days, seen or not
    python3 news.py --no-filings                     # headlines only
    python3 news.py --no-moves                       # skip the price line per ticker

Your tickers, when --tickers is not given: every hit in trader/watchlist.json
(india-scanner), the symbol in trader/plan.json (india-exit) and the
positions in trader/portfolio.json. Tickers are NSE symbols (RELIANCE, M&M).

Sources, one request each per ticker:
  - Yahoo Finance headline RSS (NSE symbols take a .NS suffix):
    https://feeds.finance.yahoo.com/rss/2.0/headline?s=<SYMBOL>.NS&region=IN&lang=en-IN
  - Google News India RSS, a search for the symbol plus "NSE share":
    https://news.google.com/rss/search?q=<SYMBOL>+NSE+share&hl=en-IN&gl=IN&ceid=IN:en
    (a search, so a short symbol like ITC or LT can bring some noise)
  - NSE corporate announcements (board-meeting outcomes, results, orders,
    insider-trading and takeover disclosures, rating changes). BEST EFFORT:
    NSE's website API wants the cookies its home page hands out and sometimes
    refuses scripts. When it does, the tool says so and the headlines still run.
    https://www.nseindia.com/api/corporate-announcements?index=equities&symbol=<SYMBOL>
  - The move: Yahoo Finance's chart endpoint (unofficial, can lag), the last
    price against yesterday's close:
    https://query2.finance.yahoo.com/v8/finance/chart/<SYMBOL>.NS?range=1d&interval=5m

Times print in IST. State: trader/state/news.json remembers what you have seen
(30 days), so an item shows once. Offline: --offline DIR reads
yahoo-<SYMBOL>.xml, gnews-<SYMBOL>.xml, nse-<SYMBOL>.json and
chart-<SYMBOL>.json from DIR. The tests use it.

Headlines are leads, not facts: open the story before acting, and treat
nothing here as advice.
"""

import argparse
import datetime as _dt
import email.utils
import gzip
import hashlib
import http.cookiejar
import json
import os
import re
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
import xml.etree.ElementTree as ET

YAHOO = "https://feeds.finance.yahoo.com/rss/2.0/headline?s=%s&region=IN&lang=en-IN"
GNEWS = "https://news.google.com/rss/search?q=%s&hl=en-IN&gl=IN&ceid=IN:en"
NSE_HOME = "https://www.nseindia.com/"
NSE_ANN = "https://www.nseindia.com/api/corporate-announcements?index=equities&symbol=%s"
CHART = "https://%s.finance.yahoo.com/v8/finance/chart/%s?range=1d&interval=5m"
BROWSER_UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
              "(KHTML, like Gecko) Chrome/124.0 Safari/537.36")
KEEP_DAYS = 30
MOVE_PCT = 3.0  # a stock this far from yesterday's close is flagged as moving
# An NSE announcement whose subject matches this is marked important (!).
NSE_IMPORTANT = re.compile(
    r"outcome of board meeting|financial results|acquisition|amalgamation|merger|demerger|scheme of arrangement"
    r"|credit rating|fraud|default|insolvency|resignation|cessation|bonus|stock split|sub-division|dividend"
    r"|buy-?back|rights issue|preferential|qip|fund ?raising|bagging|receiving of orders|order received"
    r"|takeover|open offer|SEBI order|penalty|suspension|delisting|pledge|earnings call",
    re.I)
KEYWORDS = [
    ("earnings", r"\bearnings\b|\bresults\b|\bEPS\b|\bPAT\b|\bnet profit\b|\bQ[1-4]\b|\bquarterly\b|\bguidance\b"),
    ("analyst", r"\bupgrade[sd]?\b|\bdowngrade[sd]?\b|target price|price target|\bbrokerage\b|\boutperform\b|\bunderperform\b"),
    ("legal", r"\blawsuit\b|\bprobe\b|\binvestigation\b|\bSEBI\b|\bNCLT\b|\bCBI\b|\bED\b|\bcourt\b|\btribunal\b|\bpenalty\b"),
    ("deal", r"\bacqui(?:re|res|red|sition)\b|\bmerger\b|\btakeover\b|\bstake\b|\bdeal\b|\bblock deal\b|\bbulk deal\b|\bwins? order|\bbags? order"),
    ("capital", r"\bdividend\b|\bbuyback\b|\bbonus\b|\bstock split\b|\brights issue\b|\bQIP\b|\bIPO\b|\bOFS\b|\boffering\b"),
    ("people", r"\bCEO\b|\bCFO\b|\bMD\b|\bpromoter\b|\bresign|\bsteps down\b|\bappoint"),
    ("risk", r"\brecall\b|\bbankrupt|\bdefault\b|\bdelist|\bpledge|\bfraud\b|\bhack|\bbreach\b|\bASM\b|\bGSM\b"),
    ("halt", r"\bhalt(?:s|ed)?\b|\btrading (?:pause|suspen)|\bupper circuit\b|\blower circuit\b"),
    ("regulatory", r"\bRBI\b|\bSEBI\b|\bCCI\b|\bapproval\b|\bapproves\b|\bclearance\b|\bDGCA\b|\bUSFDA\b"),
    ("macro", r"\bRBI\b|\brepo rate\b|\bMPC\b|\bSensex\b|\bNifty\b|\bFII\b|\bFPI\b|\binflation\b|\bGDP\b|\bBudget\b|\btariffs?\b|\bcrude\b|\brupee\b"),
]


class NewsError(Exception):
    pass


# ---------------------------------------------------------------- time

IST_OFFSET = _dt.timedelta(hours=5, minutes=30)   # India has no daylight saving


def ist_offset(utc):
    """India Standard Time is always UTC+5:30 (no daylight saving)."""
    return IST_OFFSET


def to_ist(utc):
    """Aware or naive UTC -> naive India wall-clock time."""
    if getattr(utc, "tzinfo", None) is not None:
        utc = utc.astimezone(_dt.timezone.utc)
    return utc.replace(tzinfo=None) + IST_OFFSET


def ist_to_utc(local):
    """Naive India wall-clock time -> naive UTC."""
    return local - IST_OFFSET



# ---------------------------------------------------------------- inputs

def load_json(path):
    if path and os.path.isfile(path):
        with open(path, encoding="utf-8") as fh:
            return json.load(fh)
    return None


def watch_from_files(portfolio="trader/portfolio.json", watchlist="trader/watchlist.json",
                     plan="trader/plan.json"):
    """{ticker: name or None}: the scanner's hits, the planned trade and your holdings."""
    out = {}
    wl = load_json(watchlist) or {}
    for h in wl.get("hits", []):
        sym = h.get("symbol") or h.get("ticker")
        if sym:
            out[sym.upper()] = h.get("name")
    pl = load_json(plan) or {}
    if pl.get("symbol"):
        out.setdefault(pl["symbol"].upper(), pl.get("name"))
    pf = load_json(portfolio) or {}
    for p in pf.get("positions", []):
        sym = p.get("ticker") or p.get("symbol")
        if sym:
            out[sym.upper()] = p.get("name") or out.get(sym.upper())
    return out


# ---------------------------------------------------------------- fetching

class Fetcher(object):
    def __init__(self, offline=None, pause=0.3):
        self.offline = offline
        self.pause = pause
        self._last = 0.0
        self._nse = None   # an opener that keeps the cookies NSE hands out on its home page

    def _open(self, opener, url, extra, timeout=30):
        headers = {"User-Agent": BROWSER_UA, "Accept-Encoding": "gzip", "Accept-Language": "en-IN,en;q=0.9"}
        headers.update(extra)
        req = urllib.request.Request(url, headers=headers)
        try:
            with opener.open(req, timeout=timeout) as resp:
                data = resp.read()
                if resp.headers.get("Content-Encoding") == "gzip":
                    data = gzip.decompress(data)
                return data
        except urllib.error.HTTPError as exc:
            raise NewsError("HTTP %s for %s" % (exc.code, url.split("?")[0]))
        except urllib.error.URLError as exc:
            raise NewsError("could not reach %s: %s" % (url.split("?")[0], exc.reason))
        except OSError as exc:
            raise NewsError("could not read %s: %s" % (url.split("?")[0], exc))

    def get(self, url, name, nse=False):
        if self.offline:
            path = os.path.join(self.offline, name)
            if not os.path.isfile(path):
                raise NewsError("offline: no file %s" % path)
            with open(path, "rb") as fh:
                return fh.read()
        gap = time.time() - self._last
        if gap < self.pause:
            time.sleep(self.pause - gap)
        self._last = time.time()
        if not nse:
            return self._open(urllib.request.build_opener(), url, {})
        if self._nse is None:
            jar = http.cookiejar.CookieJar()
            self._nse = urllib.request.build_opener(urllib.request.HTTPCookieProcessor(jar))
            self._open(self._nse, NSE_HOME, {})   # the visit that makes NSE set its cookies
        return self._open(self._nse, url, {"Referer": NSE_HOME, "Accept": "application/json, text/plain, */*"})


def yahoo_symbol(sym):
    """NSE symbol -> Yahoo's symbol: RELIANCE -> RELIANCE.NS (M&M -> M&M.NS).
    A symbol that already ends in .NS / .BO, or an index like ^NSEI, is kept."""
    s = sym.strip().upper()
    if s.startswith("^") or s.endswith(".NS") or s.endswith(".BO"):
        return s
    return s + ".NS"


def nse_symbol(ysym):
    """Yahoo's symbol -> the NSE symbol your broker uses: RELIANCE.NS -> RELIANCE."""
    s = str(ysym).strip().upper()
    for suf in (".NS", ".BO"):
        if s.endswith(suf):
            return s[:-len(suf)]
    return s


# ---------------------------------------------------------------- parsing

def _local(tag):
    return tag.rsplit("}", 1)[-1]


def _text(el, name):
    for c in el.iter():
        if _local(c.tag) == name:
            return (c.text or "").strip()
    return ""


def parse_time(value):
    """RFC 822 (RSS) or ISO 8601 (Atom) -> aware UTC datetime, or None."""
    value = (value or "").strip()
    if not value:
        return None
    try:
        d = email.utils.parsedate_to_datetime(value)
    except (TypeError, ValueError, IndexError):
        d = None
    if d is None:
        try:
            d = _dt.datetime.fromisoformat(value.replace("Z", "+00:00"))
        except ValueError:
            return None
    if d.tzinfo is None:
        d = d.replace(tzinfo=_dt.timezone.utc)
    return d.astimezone(_dt.timezone.utc)


def parse_rss(data, ticker, source="Yahoo Finance", prefix="rss"):
    """A headline RSS (Yahoo or Google News) -> items."""
    try:
        root = ET.fromstring(data)
    except ET.ParseError as exc:
        raise NewsError("RSS for %s is not valid XML: %s" % (ticker, exc))
    out = []
    for it in root.iter("item"):
        title = _text(it, "title")
        link = _text(it, "link")
        guid = _text(it, "guid") or link
        src = _text(it, "source") or source
        out.append({"id": prefix + ":" + guid, "source": src if prefix == "gnews" else source, "kind": "headline",
                    "ticker": ticker, "title": title, "summary": re.sub(r"<[^>]+>", " ", _text(it, "description")).strip(),
                    "link": link, "time": parse_time(_text(it, "pubDate"))})
    return out


def parse_nse_time(value):
    """NSE's '01-Nov-2026 10:15:30' (IST) or ISO -> aware UTC datetime, or None."""
    value = (value or "").strip()
    if not value:
        return None
    for fmt in ("%d-%b-%Y %H:%M:%S", "%Y-%m-%d %H:%M:%S", "%d-%b-%Y %H:%M", "%d-%b-%Y", "%Y-%m-%dT%H:%M:%S"):
        try:
            naive = _dt.datetime.strptime(value, fmt)
        except ValueError:
            continue
        return ist_to_utc(naive).replace(tzinfo=_dt.timezone.utc)
    return parse_time(value)


def parse_nse_announcements(data, ticker):
    """NSE corporate-announcements JSON -> items. The JSON is a list, or {"data": [...]}."""
    try:
        doc = json.loads(data.decode("utf-8") if isinstance(data, bytes) else data)
    except ValueError:
        raise NewsError("NSE announcements for %s are not JSON (NSE may have refused the script)" % ticker)
    rows = doc.get("data") if isinstance(doc, dict) else doc
    if not isinstance(rows, list):
        raise NewsError("NSE announcements for %s are not the shape this tool knows" % ticker)
    out = []
    for r in rows:
        if not isinstance(r, dict):
            continue
        desc = str(r.get("desc") or r.get("subject") or "").strip()
        text = str(r.get("attchmntText") or r.get("text") or "").strip()
        when = parse_nse_time(str(r.get("an_dt") or r.get("sort_date") or r.get("dt") or ""))
        link = str(r.get("attchmntFile") or "").strip()
        rid = str(r.get("seq_id") or r.get("an_dt") or "") + "|" + desc
        if not desc and not text:
            continue
        out.append({"id": "nse:%s:%s" % (ticker, rid), "source": "NSE announcement", "kind": "filing",
                    "ticker": ticker, "title": "%s: %s" % (ticker, desc or text[:90]), "summary": text,
                    "important": bool(NSE_IMPORTANT.search(desc + " " + text[:200])),
                    "link": link, "time": when})
    return out


def parse_chart(data, ticker):
    """Yahoo chart JSON -> {"ticker", "price", "prev_close", "pct", "time"} or raise."""
    try:
        doc = json.loads(data.decode("utf-8") if isinstance(data, bytes) else data)
        meta = doc["chart"]["result"][0]["meta"]
    except (ValueError, KeyError, IndexError, TypeError):
        raise NewsError("chart for %s is not usable" % ticker)
    price = meta.get("regularMarketPrice")
    prev = meta.get("chartPreviousClose") or meta.get("previousClose")
    if not price or not prev:
        raise NewsError("chart for %s has no price" % ticker)
    when = meta.get("regularMarketTime")
    return {"ticker": ticker, "price": round(float(price), 2), "prev_close": round(float(prev), 2),
            "pct": round((float(price) / float(prev) - 1) * 100, 2),
            "time": _dt.datetime.fromtimestamp(when, _dt.timezone.utc) if when else None}


def collect_moves(fetcher, watch, errors=None):
    errors = [] if errors is None else errors
    out = []
    for t in sorted(watch):
        name = "chart-%s.json" % t
        try:
            try:
                data = fetcher.get(CHART % ("query2", yahoo_symbol(t)), name)
            except NewsError as exc:
                if fetcher.offline or not re.search(r"HTTP (429|5\d\d)", str(exc)):
                    raise
                data = fetcher.get(CHART % ("query1", yahoo_symbol(t)), name)
            out.append(parse_chart(data, t))
        except NewsError as exc:
            if not (fetcher.offline and "no file" in str(exc)):
                errors.append("price for %s: %s" % (t, exc))
    return out


def mention_patterns(watch):
    pats = {}
    for t, name in watch.items():
        alts = [r"\(%s\)" % re.escape(t), r"\b(?:NSE|BSE)\s*:\s*%s\b" % re.escape(t)]
        if name and len(name) >= 4:
            alts.append(r"\b%s\b" % re.escape(name).replace(r"\ ", r"[\s-]"))
        pats[t] = re.compile("|".join(alts))
    return pats


def tag(items, watch):
    """Which of your tickers each item touches, and why it matters."""
    pats = mention_patterns(watch)
    for it in items:
        hay = "%s %s" % (it["title"], it.get("summary") or "")
        touches = {it["ticker"]} if it["ticker"] in watch else set()
        for t, rx in pats.items():
            if rx.search(hay):
                touches.add(t)
        it["touches"] = sorted(touches)
        it["tags"] = [label for label, rx in KEYWORDS if re.search(rx, hay, re.I)]
    return items


def dedupe(items):
    """One item per story: same id, or same link, or same title the same day."""
    seen, out = {}, []
    for it in items:
        keys = [it["id"], it["link"],
                "%s|%s" % (re.sub(r"\W+", " ", it["title"].lower()).strip(),
                           it["time"].date() if it["time"] else "")]
        hit = next((seen[k] for k in keys if k and k in seen), None)
        if hit is not None:
            for t in it.get("touches", []):
                if t not in hit["touches"]:
                    hit["touches"].append(t)
            hit["touches"].sort()
            continue
        for k in keys:
            if k:
                seen[k] = it
        out.append(it)
    return out


def fingerprint(it):
    return hashlib.sha1(it["id"].encode("utf-8")).hexdigest()[:16]


# ---------------------------------------------------------------- the check

def collect(fetcher, watch, state, filings=True, errors=None):
    errors = [] if errors is None else errors
    items = []
    for t in sorted(watch):
        try:
            items += parse_rss(fetcher.get(YAHOO % urllib.parse.quote(yahoo_symbol(t), safe="^.-"), "yahoo-%s.xml" % t), t)
        except NewsError as exc:
            errors.append("Yahoo headlines for %s: %s" % (t, exc))
        try:
            q = urllib.parse.quote_plus("%s NSE share" % t)
            items += parse_rss(fetcher.get(GNEWS % q, "gnews-%s.xml" % t), t, "Google News", "gnews")
        except NewsError as exc:
            errors.append("Google News for %s: %s" % (t, exc))
        if filings:
            try:
                data = fetcher.get(NSE_ANN % urllib.parse.quote(t, safe=""), "nse-%s.json" % t, nse=True)
                items += parse_nse_announcements(data, t)
            except NewsError as exc:
                errors.append("NSE announcements for %s: %s" % (t, exc))
    return items


def select(items, state, now, hours=48, show_all=False):
    """Items within the window; only unseen ones unless show_all."""
    seen = state.setdefault("seen", {})
    cutoff = now - _dt.timedelta(hours=hours)
    ahead = now + _dt.timedelta(minutes=10)  # a pinned --now: nothing from after it
    out = []
    for it in items:
        if it["time"] is not None and (it["time"] < cutoff or it["time"] > ahead):
            continue
        fp = fingerprint(it)
        it["new"] = fp not in seen
        if it["new"] or show_all:
            out.append(it)
    out.sort(key=lambda i: (i["time"] or now), reverse=True)
    return out


def remember(items, state, now):
    seen = state.setdefault("seen", {})
    stamp = now.isoformat()
    for it in items:
        seen.setdefault(fingerprint(it), stamp)
    cutoff = (now - _dt.timedelta(days=KEEP_DAYS)).isoformat()
    state["seen"] = {k: v for k, v in seen.items() if v >= cutoff}
    state["last_check"] = stamp


def render_moves(moves, move_pct=MOVE_PCT):
    out = []
    for m in moves:
        flag = "MOVING" if abs(m["pct"]) >= move_pct else ""
        when = (" at %s IST" % to_ist(m["time"]).strftime("%H:%M")) if m.get("time") else ""
        out.append("%-6s %s %+.2f%% vs yesterday's close %s%s  %s" % (
            m["ticker"], "{:,.2f}".format(m["price"]), m["pct"], "{:,.2f}".format(m["prev_close"]),
            when, flag))
    return out


def render(items, errors, now, moves=None, move_pct=MOVE_PCT):
    out = render_moves(moves or [], move_pct)
    if out:
        out.append("")
    if not items:
        out.append("Nothing new.")
    for it in items:
        when = to_ist(it["time"]).strftime("%Y-%m-%d %H:%M IST") if it["time"] else "time unknown"
        mark = "!" if it.get("important") else " "
        who = ",".join(it["touches"]) or it["ticker"]
        out.append("%s %s  %-11s %-13s %s" % (mark, when, who, it["source"], it["title"]))
        extra = []
        if it["tags"]:
            extra.append("tags: " + ", ".join(it["tags"]))
        extra.append(it["link"])
        out.append("      " + "  ".join(extra))
    for e in errors:
        out.append("note: %s" % e)
    out.append("Checked %s. Headlines are leads, not facts; open the story before acting. "
               "Not financial advice." % to_ist(now).strftime("%Y-%m-%d %H:%M IST"))
    return "\n".join(out) + "\n"


def _json_ready(items):
    out = []
    for it in items:
        d = dict(it)
        d["time"] = it["time"].isoformat() if it["time"] else None
        out.append(d)
    return out


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--tickers", nargs="*", help="default: watchlist + plan + portfolio")
    ap.add_argument("--portfolio", default="trader/portfolio.json")
    ap.add_argument("--watchlist", default="trader/watchlist.json")
    ap.add_argument("--plan", default="trader/plan.json")
    ap.add_argument("--state", default="trader/state/news.json")
    ap.add_argument("--hours", type=float, default=48, help="ignore items older than this")
    ap.add_argument("--all", action="store_true", help="show seen items too")
    ap.add_argument("--no-filings", "--no-sec", dest="no_filings", action="store_true",
                    help="headlines only: skip NSE corporate announcements")
    ap.add_argument("--no-moves", action="store_true", help="skip the price line per ticker")
    ap.add_argument("--move-pct", type=float, default=MOVE_PCT, help="flag a move this big (percent)")
    ap.add_argument("--config", default="trader/config.json")
    ap.add_argument("--offline", metavar="DIR")
    ap.add_argument("--now", help="ISO time, for reproducible runs")
    ap.add_argument("--dry-run", action="store_true", help="do not update the state file")
    ap.add_argument("--json", action="store_true")
    args = ap.parse_args(argv)

    if args.tickers:
        watch = {t.upper(): None for t in args.tickers}
        known = watch_from_files(args.portfolio, args.watchlist, args.plan)
        watch.update({t: known[t] for t in watch if known.get(t)})
    else:
        watch = watch_from_files(args.portfolio, args.watchlist, args.plan)
    if not watch:
        print("news: no tickers. Pass --tickers, or run /india-scanner first (it writes "
              "trader/watchlist.json).", file=sys.stderr)
        return 2
    now = parse_time(args.now) if args.now else _dt.datetime.now(_dt.timezone.utc)
    state = load_json(args.state) or {}
    errors = []
    fetcher = Fetcher(offline=args.offline)
    items = collect(fetcher, watch, state, filings=not args.no_filings, errors=errors)
    items = dedupe(tag(items, watch))
    shown = select(items, state, now, hours=args.hours, show_all=args.all)
    moves = [] if args.no_moves else collect_moves(fetcher, watch, errors)
    if args.json:
        mv = [dict(m, time=m["time"].isoformat() if m.get("time") else None,
                   moving=abs(m["pct"]) >= args.move_pct) for m in moves]
        print(json.dumps({"checked": now.isoformat(), "moves": mv, "items": _json_ready(shown),
                          "notes": errors}, indent=2))
    else:
        sys.stdout.write(render(shown, errors, now, moves, args.move_pct))
    if not args.dry_run:
        remember(items, state, now)
        folder = os.path.dirname(args.state)
        if folder:
            os.makedirs(folder, exist_ok=True)
        with open(args.state, "w", encoding="utf-8") as fh:
            json.dump(state, fh, indent=2)
            fh.write("\n")
    return 0 if any(i["new"] for i in shown) else 1


if __name__ == "__main__":
    sys.exit(main())
