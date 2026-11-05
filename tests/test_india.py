#!/usr/bin/env python3
"""Offline tests for the India port. No network: every run uses the SYNTHETIC fixtures in tests/fixtures
(made by tests/make_fixtures.py). Run:  python3 tests/make_fixtures.py && python3 -W ignore -m unittest tests/test_india.py -v
"""
import datetime
import importlib.util
import json
import os
import subprocess
import sys
import tempfile
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
FIX = os.path.join(HERE, "fixtures")
S = {
    "scan": "india-scanner/scan.py", "news": "india-news/news.py", "entry": "india-entry/entry.py",
    "exit": "india-exit/exit.py", "tm": "india-timemachine/timemachine.py", "size": "india-budget/size.py",
    "check": "india-risk/check.py", "ticket": "india-broker/ticket.py", "alerts": "india-alerts/alerts.py",
}


def load(key):
    path = os.path.join(ROOT, S[key])
    spec = importlib.util.spec_from_file_location("m_" + key, path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def run(key, *args, cwd=None):
    p = subprocess.run([sys.executable, os.path.join(ROOT, S[key])] + list(args), cwd=cwd,
                       capture_output=True, text=True)
    return p.returncode, p.stdout + p.stderr


GOOD = {"symbol": "RELIANCE", "exchange": "NSE", "product": "MIS", "side": "buy", "qty": "53", "type": "limit",
        "time_in_force": "day", "limit_price": "1401.40", "order_class": "bracket",
        "take_profit_limit_price": "1410.50", "stop_loss_stop_price": "1400.10",
        "plan": {"entry": 1401.4, "stop": 1400.1, "target": 1410.5}}
CFG = {"budget": 100000, "max_loss_per_trade_inr": 500}
T_0940 = datetime.datetime(2026, 10, 19, 4, 10)   # 09:40 IST in naive UTC


def verdict(order=None, now=T_0940, cfg=None, **kw):
    o = dict(GOOD)
    o.update(order or {})
    c = dict(CFG)
    c.update(cfg or {})
    res = load("check").check([o], c, None, {}, {}, None, now, None)
    return res["results"][0]


class Calendar(unittest.TestCase):
    def test_ist_is_utc_plus_530_all_year(self):
        for k in ("scan", "entry", "check", "alerts"):
            m = load(k)
            self.assertEqual(m.to_ist(datetime.datetime(2026, 10, 19, 4, 30)), datetime.datetime(2026, 10, 19, 10, 0))
            self.assertEqual(m.to_ist(datetime.datetime(2026, 1, 5, 4, 30)), datetime.datetime(2026, 1, 5, 10, 0))
            self.assertEqual(m.ist_to_utc(datetime.datetime(2026, 10, 19, 9, 15)), datetime.datetime(2026, 10, 19, 3, 45))

    def test_session_and_holidays(self):
        m = load("entry")
        self.assertEqual((m.OPEN, m.CLOSE), (datetime.time(9, 15), datetime.time(15, 30)))
        ok, _ = m.trading_day(datetime.date(2026, 10, 19))
        self.assertTrue(ok)
        for d, word in ((datetime.date(2026, 10, 20), "Dussehra"), (datetime.date(2026, 10, 24), "weekend"),
                        (datetime.date(2026, 11, 8), "Muhurat"), (datetime.date(2026, 12, 25), "Christmas")):
            ok, why = m.trading_day(d)
            self.assertFalse(ok, d)
            self.assertIn(word, why)
        # US holidays are NOT NSE holidays
        self.assertTrue(m.trading_day(datetime.date(2026, 11, 26))[0])   # US Thanksgiving, an NSE trading day
        self.assertTrue(m.trading_day(datetime.date(2026, 7, 3))[0])


class Scanner(unittest.TestCase):
    def test_universe_keeps_only_eq_series(self):
        m = load("scan")
        kept, counts, _ = m.build_universe({m.NSE_FILE: open(os.path.join(FIX, "EQUITY_L.csv")).read()})
        self.assertEqual([k for k, _ in kept], ["BAJAJ-AUTO", "M&M", "RELIANCE", "TCS"])

    def test_yahoo_symbols(self):
        m = load("scan")
        self.assertEqual(m.to_yahoo("RELIANCE"), "RELIANCE.NS")
        self.assertEqual(m.to_yahoo("M&M"), "M%26M.NS")
        self.assertEqual(m.from_yahoo("M&M.NS"), "M&M")
        self.assertEqual(m.to_yahoo("^NSEI"), "^NSEI")

    def test_orb_finds_the_breakout_at_935(self):
        with tempfile.TemporaryDirectory() as d:
            rc, out = run("scan", "orb", "--offline", os.path.join(FIX, "orb-bundle-2026-10-19.json"),
                          "--now", "2026-10-19 10:00", "--min-price", "0", "--no-write", "--symbols", "RELIANCE,TCS,M&M", cwd=d)
            self.assertEqual(rc, 0, out)
            self.assertIn("RELIANCE", out)
            self.assertIn("9:35 AM", out)
            self.assertNotIn("TCS  ", out)


def chain(d, until="09:40", target="7R", extra_cfg=None):
    """entry -> exit -> budget on the fixture, in directory d."""
    os.makedirs(os.path.join(d, "trader"), exist_ok=True)
    cfg = {"budget": 100000, "max_loss_per_trade_inr": 500}
    cfg.update(extra_cfg or {})
    json.dump(cfg, open(os.path.join(d, "trader", "config.json"), "w"))
    f = os.path.join(FIX, "RELIANCE-2026-10-19-5m.json")
    now = "2026-10-19 " + until
    r1 = run("entry", "check", "RELIANCE", "--now", now, "--offline", f, "--write", cwd=d)
    r2 = run("exit", "plan", "--stop", "or-mid", "--target", target, "--write", cwd=d)
    r3 = run("size", "--now", now, "--limit", "--write", cwd=d)
    return r1, r2, r3


class Chain(unittest.TestCase):
    def test_entry_states(self):
        f = os.path.join(FIX, "RELIANCE-2026-10-19-5m.json")
        with tempfile.TemporaryDirectory() as d:
            _, early = run("entry", "check", "RELIANCE", "--now", "2026-10-19 09:25", "--offline", f, cwd=d)
            self.assertNotIn("triggered", early.lower().split("\n")[0] + "")
            rc, out = run("entry", "check", "RELIANCE", "--now", "2026-10-19 09:40", "--offline", f, cwd=d)
            self.assertIn("9:35", out)

    def test_exit_levels_are_on_the_tick_and_symbol_is_plain(self):
        with tempfile.TemporaryDirectory() as d:
            chain(d)
            plan = json.load(open(os.path.join(d, "trader", "plan.json")))
            self.assertEqual(plan["symbol"], "RELIANCE")
            for k in ("stop", "target"):
                self.assertAlmostEqual(plan[k] / 0.05, round(plan[k] / 0.05), places=6, msg=k)
            self.assertLess(plan["stop"], plan["entry"])

    def test_budget_sizes_whole_shares_in_rupees(self):
        with tempfile.TemporaryDirectory() as d:
            _, _, (rc, out) = chain(d)
            self.assertEqual(rc, 0, out)
            o = json.load(open(os.path.join(d, "trader", "orders.json")))["orders"][0]
            self.assertEqual((o["exchange"], o["product"], o["time_in_force"]), ("NSE", "MIS", "day"))
            self.assertEqual(o["qty"], str(int(o["qty"])))
            self.assertIn("\u20b9", out)

    def test_budget_refuses_when_charges_eat_the_target(self):
        with tempfile.TemporaryDirectory() as d:
            _, _, (rc, out) = chain(d, target="1R")
            self.assertEqual(rc, 1, out)
            self.assertIn("charges", out)
            self.assertFalse(os.path.exists(os.path.join(d, "trader", "orders.json")))

    def test_charges_formula(self):
        m = load("size")
        c = m.charges_for(100, 1400.0, 1402.7)
        self.assertAlmostEqual(c["stt"], 100 * 1402.7 * 0.00025, places=2)
        self.assertAlmostEqual(c["stamp"], 100 * 1400 * 0.00003, places=2)
        self.assertAlmostEqual(c["brokerage"], 40.0, places=2)
        self.assertAlmostEqual(c["gst"], round((c["brokerage"] + c["exchange"] + c["sebi"]) * 0.18, 2), places=1)
        self.assertEqual(m.charges_for(100, 1400, 1402, {"charges": False})["total"], 0.0)

    def test_money_uses_indian_grouping(self):
        m = load("size")
        self.assertEqual(m.money(123456.5), "\u20b91,23,456.50")
        self.assertEqual(m.money(100000), "\u20b91,00,000")
        self.assertEqual(m.money(999), "\u20b9999")

    def test_timemachine_is_deterministic(self):
        with tempfile.TemporaryDirectory() as d:
            chain(d, target="2R")
            f = os.path.join(FIX, "RELIANCE-60d-5m.json")
            a = run("tm", "run", "--offline", f, "--now", "2026-10-19 16:00", "--replays", "300", cwd=d)
            b = run("tm", "run", "--offline", f, "--now", "2026-10-19 16:00", "--replays", "300", cwd=d)
            self.assertEqual(a[0], 0, a[1])
            self.assertEqual(a[1], b[1])
            self.assertIn("29 full sessions", a[1])
            self.assertIn("3:15 PM", a[1])


class Risk(unittest.TestCase):
    def test_good_order_passes(self):
        v = verdict()
        self.assertEqual(v["verdict"], "PASS", v["reasons"])

    def test_blocks(self):
        cases = [
            ({"qty": "53.5"}, "whole"),
            ({"limit_price": "1401.43"}, "tick"),
            ({"symbol": "RELIANCE.NS"}, "NSE equity symbol"),
            ({"symbol": "RELIANCE26NOV1400CE"}, "futures or options"),
            ({"product": "CNC"}, "intraday"),
            ({"notional": "5000", "qty": None}, "quantity"),
            ({"time_in_force": "gtc"}, "time_in_force"),
            ({"exchange": "NYSE"}, "exchange"),
            ({"stop_loss_stop_price": "1401.40"}, "stop"),
        ]
        for patch, word in cases:
            v = verdict(patch)
            self.assertEqual(v["verdict"], "BLOCK", patch)
            self.assertTrue(any(word in r for r in v["reasons"]), (patch, v["reasons"]))

    def test_window_and_calendar(self):
        for now, word in ((datetime.datetime(2026, 10, 19, 3, 50), "before 09:30"),      # 09:20 IST
                          (datetime.datetime(2026, 10, 19, 9, 30), "after 14:45"),       # 15:00 IST
                          (datetime.datetime(2026, 10, 20, 4, 30), "Dussehra"),
                          (datetime.datetime(2026, 11, 8, 13, 0), "Muhurat")):
            v = verdict(now=now)
            self.assertEqual(v["verdict"], "BLOCK", now)
            self.assertTrue(any(word in r for r in v["reasons"]), (now, v["reasons"]))

    def test_loss_cap_and_exit_never_blocked(self):
        v = verdict({"qty": "400"}, cfg={"max_position_pct": 100, "max_order_inr": 10 ** 7, "budget": 10 ** 6})
        self.assertEqual(v["verdict"], "BLOCK")
        self.assertTrue(any("loss" in r for r in v["reasons"]))
        sell = {"symbol": "RELIANCE", "exchange": "NSE", "product": "MIS", "side": "sell", "qty": "10",
                "type": "market", "time_in_force": "day"}
        pf = {"cash": 1000, "positions": [{"ticker": "RELIANCE", "shares": 10}]}
        late = datetime.datetime(2026, 10, 19, 9, 40)   # 15:10 IST
        res = load("check").check([sell], CFG, pf, {"RELIANCE": 1400.0}, {}, None, late, None)
        self.assertEqual(res["results"][0]["kind"], "exit")
        self.assertEqual(res["results"][0]["verdict"], "PASS", res["results"][0]["reasons"])


class Broker(unittest.TestCase):
    def setUp(self):
        self.d = tempfile.TemporaryDirectory()
        chain(self.d.name)
        run("check", "--now", "2026-10-19 09:40", cwd=self.d.name)

    def tearDown(self):
        self.d.cleanup()

    def test_ready_ticket_is_a_manual_checklist(self):
        rc, out = run("ticket", "show", "--now", "2026-10-19 09:41", cwd=self.d.name)
        self.assertIn("READY", out)
        self.assertIn("MIS", out)
        self.assertIn("cancel the other", out)
        self.assertIn("Nothing is sent from here", out)
        self.assertNotIn("place_stock_order", out)

    def test_only_an_explicit_yes_counts(self):
        for bad in ("sure", "ok", "yes to all", "maybe"):
            rc, out = run("ticket", "approve", "--index", "1", "--reply", bad, "--now", "2026-10-19 09:41", cwd=self.d.name)
            self.assertEqual(rc, 1, bad)
            self.assertIn("Not recorded", out)
        rc, out = run("ticket", "approve", "--index", "1", "--reply", "yes", "--now", "2026-10-19 09:41", cwd=self.d.name)
        self.assertEqual(rc, 0, out)
        self.assertIn("place it yourself", out)

    def test_changed_order_is_not_ready(self):
        p = os.path.join(self.d.name, "trader", "orders.json")
        doc = json.load(open(p))
        doc["orders"][0]["qty"] = "54"
        json.dump(doc, open(p, "w"))
        rc, out = run("ticket", "approve", "--index", "1", "--reply", "yes", "--now", "2026-10-19 09:41", cwd=self.d.name)
        self.assertEqual(rc, 1)
        self.assertIn("not ready", out)

    def test_flatten_builds_a_market_sell(self):
        run("ticket", "approve", "--index", "1", "--reply", "yes", "--now", "2026-10-19 09:41", cwd=self.d.name)
        run("ticket", "result", "--index", "1", "--status", "placed", "--filled-qty", "53", "--filled-price", "1401.40",
            "--now", "2026-10-19 09:42", cwd=self.d.name)
        rc, out = run("ticket", "flatten", "--symbol", "RELIANCE", "--now", "2026-10-19 15:10", cwd=self.d.name)
        self.assertEqual(rc, 0, out)
        o = json.load(open(os.path.join(self.d.name, "trader", "orders.json")))["orders"][0]
        self.assertEqual((o["side"], o["type"], o["qty"], o["product"]), ("sell", "market", "53", "MIS"))


class Alerts(unittest.TestCase):
    def test_clock_and_stop_rings_once(self):
        with tempfile.TemporaryDirectory() as d:
            chain(d, target="2R")
            rc, out = run("alerts", "clock", "--now", "2026-10-20 10:00", cwd=d)
            self.assertIn("Dussehra", out)
            run("alerts", "add", "--from-plan", cwd=d)
            fx = os.path.join(FIX, "alerts")
            rc, out = run("alerts", "check", "--now", "2026-10-19 15:16", "--offline", fx, cwd=d)
            self.assertEqual(rc, 0, out)
            self.assertIn("stop", out.lower())
            rc, out = run("alerts", "check", "--now", "2026-10-19 15:17", "--offline", fx, cwd=d)
            self.assertEqual(rc, 1, out)


class News(unittest.TestCase):
    def test_nse_announcements_and_sources(self):
        with tempfile.TemporaryDirectory() as d:
            rc, out = run("news", "--tickers", "RELIANCE", "--offline", os.path.join(FIX, "news"),
                          "--now", "2026-10-19T10:00:00+00:00", "--dry-run", cwd=d)
            self.assertEqual(rc, 0, out)
            self.assertIn("NSE announcement", out)
            self.assertIn("Outcome of Board Meeting", out)
            self.assertIn("Google News", out + "Google News" if "Example Times" in out else out)
            self.assertIn("IST", out)
            self.assertNotIn("SEC", out.replace("SECTOR", ""))


if __name__ == "__main__":
    unittest.main()
