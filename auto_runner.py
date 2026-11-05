#!/usr/bin/env python3
"""Config-Driven NSE Intraday Trading & Realistic Paper Tracking Engine (auto_runner.py).

Fixes enforced:
1. Strict Obedience to `india-budget/size.py` and `india-risk/check.py`:
   - Never invents a fallback qty or formula if `size.py` refuses (`rc != 0` or `refusal`).
   - Enforces `min_reward_risk_after_charges` (default 1.0 in `trader/config.json`) so setups where
     brokerage/taxes eat the reward:risk (e.g. 0.72 after charges) are rejected!
   - Logs placed trades in `broker.json` and enforces `max_trades_per_day` & `max_daily_loss_inr`.
2. Zero Hardcoded Config / Charge Numbers:
   - Reads `budget`, `allow_margin`, `max_loss_per_trade_inr`, `max_daily_loss_inr`, `tick_size` from `trader/config.json`.
   - Uses `charges_for()` directly from `india-budget/size.py` for all exit P&L calculations.
3. Realistic Entry & Stop Fills (Cron Delay + Gap/Slippage):
   - Checks completed bars up to `cutoff_hhmm`. If GitHub cron ran 5–30m late and the trade already hit SL/Target
     or ran away (> 0.5R above trigger), skips the trade instead of backdating the fill!
   - Applies 1-tick entry slippage and gap-aware stop-loss slippage (`min(stop, bar_open) - tick_size`).
4. Safe Simulation Isolation:
   - `test` and `replay_today` use `trader/state_sim/` and NEVER delete live `trader/state/paper_book.json`
     or `trader/state/sent_today.json`!
"""
import argparse
import datetime
import importlib.util
import json
import os
import subprocess
import sys

from chart_gen import generate_chart, generate_eod_scorecard, fetch_5m_chart
from telegram_notify import notify_all
from brief import (
    generate_morning_brief,
    generate_setup_brief,
    generate_evening_review_brief,
)

ROOT = os.path.dirname(os.path.abspath(__file__))
TRADER = os.path.join(ROOT, "trader")
CONFIG_FILE = os.path.join(TRADER, "config.json")
IST_OFFSET = datetime.timedelta(hours=5, minutes=30)
EPOCH = datetime.datetime(1970, 1, 1)

# Dynamically import `charges_for` from `india-budget/size.py` so charges match 100% down to the paisa
_size_spec = importlib.util.spec_from_file_location("india_budget_size", os.path.join(ROOT, "india-budget", "size.py"))
_size_mod = importlib.util.module_from_spec(_size_spec)
_size_spec.loader.exec_module(_size_mod)
charges_for = _size_mod.charges_for


def now_ist():
    return datetime.datetime.now(datetime.timezone.utc).replace(tzinfo=None) + IST_OFFSET


def run_cmd(args):
    p = subprocess.run([sys.executable] + args, cwd=ROOT, capture_output=True, text=True)
    return p.returncode, (p.stdout + p.stderr).strip()


def load_json(path, default=None):
    if not path or not os.path.exists(path):
        return default
    with open(path, encoding="utf-8") as f:
        return json.load(f)


def save_json(path, data):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2, ensure_ascii=False)


def load_config():
    return load_json(CONFIG_FILE, {"budget": 10000, "max_loss_per_trade_inr": 200, "max_daily_loss_inr": 200, "max_trades_per_day": 3, "tick_size": 0.05})


def get_state_paths(state_dir):
    return {
        "dir": state_dir,
        "sent": os.path.join(state_dir, "sent_today.json"),
        "book": os.path.join(state_dir, "paper_book.json"),
        "passbook": os.path.join(state_dir, "paper_passbook.json"),
        "broker": os.path.join(state_dir, "broker.json"),
        "risk": os.path.join(state_dir, "risk.json"),
        "news": os.path.join(state_dir, "morning_news.json"),
    }


def load_paper_book(book_path, today_iso):
    book = load_json(book_path, {"date": today_iso, "trades": [], "skipped": [], "eod_sent": False})
    if book.get("date") != today_iso:
        book = {"date": today_iso, "trades": [], "skipped": [], "eod_sent": False}
    book.setdefault("trades", [])
    book.setdefault("skipped", [])
    return book


def load_passbook(passbook_path, cfg):
    budget = float(cfg.get("budget") or 10000.0)
    return load_json(passbook_path, {
        "starting_capital": budget,
        "current_balance": budget,
        "days_traded": 0,
        "history": [],
    })


def parse_session_bars_from_chart(chart_raw, day_iso, cutoff_hhmm="15:30"):
    try:
        res = chart_raw["chart"]["result"][0]
        timestamps = res.get("timestamp") or []
        quote = (res.get("indicators", {}).get("quote") or [{}])[0]
        opens = quote.get("open") or []
        highs = quote.get("high") or []
        lows = quote.get("low") or []
        closes = quote.get("close") or []
    except Exception:
        return []

    bars = []
    for i, ts in enumerate(timestamps):
        if i >= len(closes) or closes[i] is None or highs[i] is None or lows[i] is None or opens[i] is None:
            continue
        dt_ist = EPOCH + datetime.timedelta(seconds=ts) + IST_OFFSET
        if dt_ist.date().isoformat() != day_iso:
            continue
        end_dt = dt_ist + datetime.timedelta(minutes=5)
        end_hhmm = end_dt.strftime("%H:%M")
        if end_hhmm > cutoff_hhmm:
            continue
        bars.append({
            "start_hhmm": dt_ist.strftime("%H:%M"),
            "end_hhmm": end_hhmm,
            "end_ampm": end_dt.strftime("%I:%M %p").lstrip("0"),
            "o": float(opens[i]),
            "h": float(highs[i]),
            "l": float(lows[i]),
            "c": float(closes[i]),
        })
    return bars


def round_tick(price: float, tick: float = 0.05) -> float:
    return round(round(float(price) / tick) * tick, 2)


def detect_realistic_entry_fill(sym, entry_doc, today_iso, cutoff_hhmm, offline_5m, cfg):
    """Handles 5–30 minute GitHub Actions cron delays and realistic entry slippage:
    - Finds all completed bars after the trigger bar up to `cutoff_hhmm`.
    - If cron ran late and price already touched OR-low stop or ran > 0.5R away or fell back below OR high,
      returns `(None, None, delay_min, reason)` so we never backdate an optimistic fill!
    - Otherwise returns `(fill_price, fill_time_ampm, delay_min, None)` with 1-tick entry slippage.
    """
    tick = float(cfg.get("tick_size") or 0.05)
    trig_info = entry_doc.get("trigger") or {}
    or_info = entry_doc.get("opening_range") or {}
    signal_px = float(trig_info.get("close") or entry_doc.get("price") or 0.0)
    or_high = float(or_info.get("high") or signal_px)
    or_low = float(or_info.get("low") or signal_px)
    bar_start = trig_info.get("bar_start") or entry_doc.get("bar_start") or "09:30"
    signal_time = trig_info.get("bar_end") or entry_doc.get("bar_end") or "9:35 AM"

    try:
        chart_raw = fetch_5m_chart(sym, offline_5m)
        bars = parse_session_bars_from_chart(chart_raw, today_iso, cutoff_hhmm=cutoff_hhmm)
    except Exception:
        bars = []

    later_bars = [b for b in bars if b["start_hhmm"] > bar_start]
    delay_min = len(later_bars) * 5

    if not later_bars:
        # Detected right after trigger bar closed: apply 1 tick realistic slippage
        fill_px = round_tick(signal_px + tick, tick)
        return fill_px, signal_time, 0, None

    # Cron ran late (1 or more bars after trigger bar): verify trade hasn't already broken down or run away
    est_risk = max(tick, signal_px - or_low)
    for b in later_bars:
        if b["l"] <= or_low:
            return None, None, delay_min, f"Cron {delay_min}m late: price already touched OR-Low ₹{or_low:.2f} at {b['end_ampm']}"
        if b["h"] >= signal_px + 2.0 * est_risk:
            return None, None, delay_min, f"Cron {delay_min}m late: target move already happened at {b['end_ampm']} (₹{b['h']:.2f})"

    latest_bar = later_bars[-1]
    fill_px = round_tick(latest_bar["c"] + tick, tick)
    if fill_px <= or_high:
        return None, None, delay_min, f"Cron {delay_min}m late: breakout failed back below OR High ₹{or_high:.2f} (now ₹{latest_bar['c']:.2f})"
    if fill_px > signal_px + 0.5 * est_risk:
        return None, None, delay_min, f"Cron {delay_min}m late: price ran away to ₹{fill_px:.2f} vs signal ₹{signal_px:.2f} (no chasing)"

    return fill_px, latest_bar["end_ampm"], delay_min, None


def update_paper_trades(paper_book, paths, today_iso, cfg, cutoff_hhmm="15:30", offline_5m=None, send_live_alerts=True):
    """Walks every open trade bar-by-bar with realistic gap & SL-M slippage and exact `size.py` charges."""
    tick = float(cfg.get("tick_size") or 0.05)
    changed = False

    for tr in paper_book.get("trades", []):
        if tr.get("status") not in ("OPEN", "OPEN_TRAILED"):
            continue

        sym = tr["symbol"]
        try:
            chart_raw = fetch_5m_chart(sym, offline_5m)
        except Exception as e:
            print(f"Warning: could not fetch 5m bars for {sym}: {e}")
            continue

        bars = parse_session_bars_from_chart(chart_raw, today_iso, cutoff_hhmm=cutoff_hhmm)
        if not bars:
            continue

        entry_bar_start = tr.get("entry_bar_start", "09:30")
        last_checked = tr.get("last_checked_hhmm", entry_bar_start)

        qty = int(tr.get("qty") or 1)
        entry_px = float(tr.get("entry") or 0.0)
        target_px = float(tr.get("target") or 0.0)
        one_r_px = float(tr.get("one_r_price") or (entry_px + float(tr.get("risk_per_share") or 1.0)))

        for b in bars:
            if b["start_hhmm"] <= entry_bar_start or b["end_hhmm"] <= last_checked:
                continue

            cur_stop = float(tr.get("stop") or tr.get("initial_stop") or 0.0)

            # 1. Check Stop-Loss / Trailed Stop hit first (with realistic gap-down + 1 tick SL-M slippage!)
            if b["l"] <= cur_stop:
                # If bar opened below cur_stop (gap down), SL-M fills at open - 1 tick; else cur_stop - 1 tick
                raw_exit = min(cur_stop, b["o"])
                exit_px = round_tick(raw_exit - tick, tick)
                exact_ch = charges_for(qty, entry_px, exit_px, cfg)["total"]
                gross = round((exit_px - entry_px) * qty, 2)
                net = round(gross - exact_ch, 2)

                tr["exit_price"] = exit_px
                tr["exit_time"] = b["end_ampm"]
                tr["charges"] = exact_ch
                tr["gross_pnl"] = gross
                tr["net_pnl"] = net
                tr["last_checked_hhmm"] = b["end_hhmm"]
                changed = True

                if tr.get("trailed_to_cost"):
                    tr["status"] = "TRAILED_COST_EXIT"
                    tr["exit_reason"] = f"1R Trail SL Exit (SL ₹{cur_stop:.2f}, Fill ₹{exit_px:.2f})"
                    if send_live_alerts:
                        notify_all(
                            f"🛡️ *TRAILED STOP EXIT: {sym} ({qty} Shares)*\n"
                            f"• *Exit Time:* {b['end_ampm']} IST  |  *SL Trigger:* ₹{cur_stop:.2f}  |  *Realistic SL-M Fill:* ₹{exit_px:.2f}\n"
                            f"• *Setup:* {tr.get('setup_short', '15m ORB')} (Entry Fill ₹{entry_px:.2f})\n"
                            f"• *Price Slippage P&L:* ₹{gross:+.2f}  |  *Exact NSE Charges (`size.py`):* -₹{exact_ch:.2f}\n"
                            f"• *Net P&L:* *₹{net:+.2f}* (Trailing SL reduced loss from full stop to ₹{ abs(net):.2f})"
                        )
                else:
                    tr["status"] = "SL_HIT"
                    tr["exit_reason"] = f"Stop-Loss Hit (SL ₹{cur_stop:.2f}, Fill ₹{exit_px:.2f})"
                    if send_live_alerts:
                        notify_all(
                            f"🛑 *STOP-LOSS HIT: {sym} ({qty} Shares)*\n"
                            f"• *Exit Time:* {b['end_ampm']} IST  |  *SL Trigger:* ₹{cur_stop:.2f}  |  *Realistic SL-M Fill:* ₹{exit_px:.2f}\n"
                            f"• *Setup:* {tr.get('setup_short', '15m ORB')} (Entry Fill ₹{entry_px:.2f})\n"
                            f"• *Gross Loss:* ₹{gross:+.2f}  |  *Exact NSE Charges (`size.py`):* -₹{exact_ch:.2f}\n"
                            f"• *Net P&L:* *₹{net:+.2f}*"
                        )
                break

            # 2. Check Target Hit (Limit sell order fills at target_px, or bar open if gapped above target)
            if b["h"] >= target_px:
                exit_px = round_tick(max(target_px, b["o"]), tick)
                exact_ch = charges_for(qty, entry_px, exit_px, cfg)["total"]
                gross = round((exit_px - entry_px) * qty, 2)
                net = round(gross - exact_ch, 2)

                tr["status"] = "TARGET_HIT"
                tr["exit_price"] = exit_px
                tr["exit_time"] = b["end_ampm"]
                tr["exit_reason"] = f"{tr.get('target_r', 'Target')} Hit"
                tr["charges"] = exact_ch
                tr["gross_pnl"] = gross
                tr["net_pnl"] = net
                tr["last_checked_hhmm"] = b["end_hhmm"]
                changed = True
                if send_live_alerts:
                    notify_all(
                        f"🎯 *TARGET HIT: {sym} ({qty} Shares)*\n"
                        f"• *Exit Time:* {b['end_ampm']} IST  |  *Target Fill:* ₹{exit_px:.2f}\n"
                        f"• *Setup:* {tr.get('setup_short', '15m ORB')} (Entry Fill ₹{entry_px:.2f})\n"
                        f"• *Gross Profit:* *+₹{gross:.2f}*  |  *Exact NSE Charges (`size.py`):* -₹{exact_ch:.2f}\n"
                        f"• *Clean Net Profit:* *+₹{net:.2f}*"
                    )
                break

            # 3. Check +1R (1:1) reached -> Trail Stop-Loss to Entry Fill Price
            if not tr.get("trailed_to_cost") and b["h"] >= one_r_px:
                tr["trailed_to_cost"] = True
                tr["stop"] = entry_px
                tr["status"] = "OPEN_TRAILED"
                tr["trailed_at_time"] = b["end_ampm"]
                changed = True
                if send_live_alerts:
                    notify_all(
                        f"🛡️ *+1R REACHED — TRAIL STOP-LOSS TO ENTRY COST: {sym}*\n"
                        f"• *Time:* {b['end_ampm']} IST  |  *High:* ₹{b['h']:.2f} (+1R Trigger: ₹{one_r_px:.2f})\n"
                        f"• *{sym}* ({qty} sh) ka Stop-Loss `₹{tr.get('initial_stop'):.2f}` se utha kar **Entry Price (`₹{entry_px:.2f}`)** par trail kiya gaya hai.\n"
                        f"• *Note:* SL-M order fast move ya gap-down me `₹{entry_px:.2f}` ke niche bhi fill ho sakta hai (slippage + NSE charges lagenge)."
                    )

            # 4. Check 15:15 IST Auto Square-Off
            if b["end_hhmm"] >= "15:15":
                exit_px = round_tick(b["c"] - tick, tick)
                exact_ch = charges_for(qty, entry_px, exit_px, cfg)["total"]
                gross = round((exit_px - entry_px) * qty, 2)
                net = round(gross - exact_ch, 2)

                tr["status"] = "TIME_EXIT_1515"
                tr["exit_price"] = exit_px
                tr["exit_time"] = b["end_ampm"]
                tr["exit_reason"] = "3:15 PM Intraday Square-Off"
                tr["charges"] = exact_ch
                tr["gross_pnl"] = gross
                tr["net_pnl"] = net
                tr["last_checked_hhmm"] = b["end_hhmm"]
                changed = True
                if send_live_alerts:
                    notify_all(
                        f"🕒 *3:15 PM INTRADAY AUTO SQUARE-OFF: {sym}*\n"
                        f"• *Time:* {b['end_ampm']} IST  |  *Exit Fill:* ₹{exit_px:.2f}\n"
                        f"• *Gross P&L:* ₹{gross:+.2f}  |  *Charges:* -₹{exact_ch:.2f}  |  *Net P&L:* *₹{net:+.2f}*"
                    )
                break

            tr["last_checked_hhmm"] = b["end_hhmm"]
            changed = True

    if changed:
        save_json(paths["book"], paper_book)
    return changed


def sync_broker_state_for_risk(paper_book, broker_path, today_iso):
    """Writes `broker.json` so `india-risk/check.py` natively enforces `max_trades_per_day`
    and `max_daily_loss_inr` (using actual realized loss for closed losing trades and all-in stop risk for open trades)."""
    orders = []
    for tr in paper_book.get("trades", []):
        st = tr.get("status", "OPEN")
        if st in ("OPEN", "OPEN_TRAILED"):
            risk_used = float(tr.get("all_in_stop_loss") or 0.0)
        else:
            npnl = float(tr.get("net_pnl") or 0.0)
            risk_used = abs(npnl) if npnl < 0 else 0.0
        orders.append({
            "status": "placed",
            "date": today_iso,
            "kind": "entry",
            "symbol": tr.get("symbol"),
            "side": "buy",
            "qty": int(tr.get("qty") or 1),
            "max_loss": round(risk_used, 2),
        })
    save_json(broker_path, {"orders": orders})


def evaluate_and_optimize_symbol(
    sym,
    now_flags,
    today_iso,
    cutoff_hhmm,
    paths,
    cfg,
    offline_5m=None,
    offline_60d=None,
    try_stops=("or-mid", "or-low"),
    try_targets=("2R", "3R"),
):
    """Evaluates candidate plans and strictly enforces:
    1. `india-entry/entry.py` triggered with complete 3-bar opening range.
    2. Realistic detection-time fill price (`detect_realistic_entry_fill`).
    3. `india-budget/size.py --limit <fill_px>` succeeds with `rc == 0`, `refusal is None`, and `qty > 0`.
    4. `reward_risk_after_charges >= cfg["min_reward_risk_after_charges"]` (default 1.0).
    5. `india-risk/check.py` succeeds with `rc == 0` and `verdict == "PASS"`.
    """
    ent_args = ["india-entry/entry.py", "check", sym, "--write"] + now_flags
    if offline_5m:
        ent_args += ["--offline", offline_5m]
    rc_e, out_e = run_cmd(ent_args)
    print(out_e)
    if rc_e != 0:
        return None, f"{sym}: entry not triggered"

    entry_doc = load_json(os.path.join(TRADER, "entry.json"), {})
    fill_px, fill_time_ampm, delay_min, skip_reason = detect_realistic_entry_fill(
        sym, entry_doc, today_iso, cutoff_hhmm, offline_5m, cfg
    )
    if skip_reason or fill_px is None:
        print(f"Skipping {sym}: {skip_reason}")
        return None, f"{sym}: {skip_reason}"

    min_rr_net = float(cfg.get("min_reward_risk_after_charges") or 1.0)
    valid_candidates = []
    rejection_reasons = []

    for stp in try_stops:
        for tgt in try_targets:
            ext_args = ["india-exit/exit.py", "plan", "--entry", f"{fill_px:.2f}", "--stop", stp, "--target", tgt, "--write"] + now_flags
            rc_x, _ = run_cmd(ext_args)
            if rc_x != 0:
                continue
            plan_c = load_json(os.path.join(TRADER, "plan.json"), {})

            # Size at the realistic fill price using india-budget/size.py --limit <fill_px>
            sz_args = ["india-budget/size.py", "--limit", f"{fill_px:.2f}", "--write", "--json"] + now_flags
            rc_sz, sz_out = run_cmd(sz_args)
            sz_doc = json.loads(sz_out) if sz_out.strip().startswith("{") else {}
            sz_inner = sz_doc.get("sizing") if isinstance(sz_doc.get("sizing"), dict) else sz_doc

            if rc_sz != 0 or not sz_inner or sz_inner.get("refusal") or int(sz_inner.get("qty") or 0) <= 0:
                ref_msg = (sz_inner or {}).get("refusal") or sz_out.splitlines()[0] if sz_out else "budget refused"
                rejection_reasons.append(f"{stp}/{tgt}: india-budget refused ({ref_msg})")
                continue

            loss_all_in = float(sz_inner.get("loss_at_stop_with_charges") or 0.0)
            net_win = float(sz_inner.get("net_profit_at_target") or 0.0)
            rr_after_chg = round(net_win / loss_all_in, 2) if loss_all_in > 0 else 0.0
            if rr_after_chg < min_rr_net:
                rejection_reasons.append(
                    f"{stp}/{tgt}: reward:risk after charges is {rr_after_chg:.2f} (< min {min_rr_net:.2f}; "
                    f"net win ₹{net_win:.2f} vs all-in stop loss ₹{loss_all_in:.2f})"
                )
                continue

            # Run india-risk/check.py against current broker state
            rk_args = [
                "india-risk/check.py",
                "--state", paths["broker"],
                "--out", paths["risk"],
                "--json",
            ] + now_flags
            rc_rk, rk_out = run_cmd(rk_args)
            rk_doc = json.loads(rk_out) if rk_out.strip().startswith("{") else {}
            if rc_rk != 0 or int(rk_doc.get("block") or 0) > 0:
                blk_reasons = []
                for r_item in rk_doc.get("results") or []:
                    blk_reasons.extend(r_item.get("reasons") or [])
                rejection_reasons.append(f"{stp}/{tgt}: india-risk BLOCK ({'; '.join(blk_reasons) or rk_out})")
                continue

            tm_args = ["india-timemachine/timemachine.py", "run", "--write"] + now_flags
            if offline_60d:
                tm_args += ["--offline", offline_60d]
            run_cmd(tm_args)
            tm_c = load_json(os.path.join(TRADER, "timemachine.json"), {})

            mc = tm_c.get("mc") or {}
            p_win = float(mc.get("p_target") or 0.40)
            p_loss = float(mc.get("p_stop") or 0.60)
            ev_inr = round(p_win * net_win - p_loss * loss_all_in, 2)

            valid_candidates.append({
                "stop_rule": stp,
                "target_r": tgt,
                "plan": plan_c,
                "sz_doc": sz_doc,
                "sz_inner": sz_inner,
                "rk_doc": rk_doc,
                "tm": tm_c,
                "entry_doc": entry_doc,
                "entry_bar_start": entry_doc.get("bar_start") or (entry_doc.get("trigger") or {}).get("bar_start") or "09:30",
                "signal_price": float((entry_doc.get("trigger") or {}).get("close") or entry_doc.get("price") or fill_px),
                "fill_price": fill_px,
                "fill_time": fill_time_ampm,
                "cron_delay_min": delay_min,
                "rr_after_charges": rr_after_chg,
                "ev_inr": ev_inr,
            })

    if not valid_candidates:
        why_str = " | ".join(rejection_reasons) if rejection_reasons else "no valid plan passed budget & risk"
        print(f"BLOCKED/SKIPPED {sym}: {why_str}")
        return None, f"{sym}: {why_str}"

    # Pick candidate with highest expected value after charges
    valid_candidates.sort(key=lambda c: (c["ev_inr"], c["rr_after_charges"]), reverse=True)
    best = valid_candidates[0]

    # Re-write the winning plan, orders, risk, and timemachine files so disk state matches `best`
    save_json(os.path.join(TRADER, "plan.json"), best["plan"])
    run_cmd(["india-budget/size.py", "--limit", f"{best['fill_price']:.2f}", "--write"] + now_flags)
    run_cmd(["india-risk/check.py", "--state", paths["broker"], "--out", paths["risk"]] + now_flags)
    save_json(os.path.join(TRADER, "timemachine.json"), best["tm"])
    return best, None


def run_eod_report(today_iso=None, offline_5m=None, state_dir=None):
    cfg = load_config()
    st_dir = state_dir or os.path.join(TRADER, "state")
    paths = get_state_paths(st_dir)
    cur_ist = now_ist()
    today_iso = today_iso or cur_ist.date().isoformat()
    paper_book = load_paper_book(paths["book"], today_iso)

    update_paper_trades(paper_book, paths, today_iso, cfg, cutoff_hhmm="15:25", offline_5m=offline_5m, send_live_alerts=False)

    passbook = load_passbook(paths["passbook"], cfg)
    closed = [t for t in paper_book.get("trades", []) if t.get("net_pnl") is not None]
    day_net = round(sum(float(t.get("net_pnl") or 0.0) for t in closed), 2)

    existing_dates = [h.get("date") for h in passbook.get("history", [])]
    if today_iso not in existing_dates and paper_book.get("trades"):
        passbook["current_balance"] = round(float(passbook.get("current_balance", cfg.get("budget", 10000.0))) + day_net, 2)
        passbook["days_traded"] = int(passbook.get("days_traded", 0)) + 1
        passbook.setdefault("history", []).append({
            "date": today_iso,
            "trades": len(paper_book.get("trades", [])),
            "net_pnl": day_net,
            "balance": passbook["current_balance"],
        })
        save_json(paths["passbook"], passbook)

    scorecard_png = generate_eod_scorecard(paper_book, passbook, trader_dir=TRADER)
    print("Generated EOD Scorecard PNG at:", scorecard_png)

    caption = generate_evening_review_brief(paper_book, passbook, state_dir=st_dir)
    notify_all(caption, scorecard_png)

    paper_book["eod_sent"] = True
    save_json(paths["book"], paper_book)
    return 0


def run_premarket(state_dir=None):
    st_dir = state_dir or os.path.join(TRADER, "state")
    paths = get_state_paths(st_dir)
    cur_ist = now_ist()
    today_iso = cur_ist.date().isoformat()
    sent_state = load_json(paths["sent"], {"date": today_iso, "symbols": [], "morning_ping": False, "premarket_done": False})
    if sent_state.get("date") != today_iso:
        sent_state = {"date": today_iso, "symbols": [], "morning_ping": False, "premarket_done": False}

    rc_sc, sc_out = run_cmd(["india-scanner/scan.py", "daily", "--top", "15"])
    print(sc_out)
    watchlist_doc = load_json(os.path.join(TRADER, "watchlist.json"), {})

    top_syms = [h.get("symbol") for h in (watchlist_doc.get("hits") or [])[:5] if h.get("symbol")]
    news_args = ["india-news/news.py", "--hours", "18", "--no-moves"]
    if top_syms:
        news_args += ["--tickers", ",".join(top_syms)]
    rc_nw, news_out = run_cmd(news_args)
    print(news_out)

    news_doc = {}
    rc_nj, nw_json_str = run_cmd(news_args + ["--json"])
    if rc_nj == 0 and nw_json_str.startswith("{"):
        try:
            news_doc = json.loads(nw_json_str)
        except Exception:
            news_doc = {}

    save_json(paths["news"], news_doc)
    tm_doc = load_json(os.path.join(TRADER, "timemachine.json"), {})
    cfg = load_config()
    report_msg = generate_morning_brief(watchlist_doc, news_doc, tm_json=tm_doc, config_json=cfg, state_dir=st_dir)
    notify_all(report_msg)
    sent_state["premarket_done"] = True
    save_json(paths["sent"], sent_state)
    return 0


def run_intraday(
    now_arg=None,
    offline_orb=None,
    offline_5m=None,
    offline_60d=None,
    target_r="2R",
    max_alerts_per_run=3,
    send_eod_after=False,
    state_dir=None,
):
    cfg = load_config()
    st_dir = state_dir or os.path.join(TRADER, "state")
    paths = get_state_paths(st_dir)
    now_flags = ["--now", now_arg] if now_arg else []
    cur_ist = now_ist()
    now_str = now_arg or cur_ist.strftime("%Y-%m-%d %H:%M")
    today_iso = now_str.split()[0]
    cutoff_hhmm = now_str.split()[1][:5] if " " in now_str else cur_ist.strftime("%H:%M")

    clock_st = {"open": True, "reason": "simulated"}
    rc, clock_out = run_cmd(["india-alerts/alerts.py", "clock", "--json"] + now_flags)
    if rc == 0 and clock_out.startswith("{"):
        clock_st = json.loads(clock_out)

    sent_state = load_json(paths["sent"], {"date": today_iso, "symbols": [], "morning_ping": False, "premarket_done": False})
    if sent_state.get("date") != today_iso:
        sent_state = {"date": today_iso, "symbols": [], "morning_ping": False, "premarket_done": False}

    paper_book = load_paper_book(paths["book"], today_iso)

    # 1. Update open trades first
    if paper_book.get("trades"):
        update_paper_trades(paper_book, paths, today_iso, cfg, cutoff_hhmm=cutoff_hhmm, offline_5m=offline_5m, send_live_alerts=not send_eod_after)

    if not offline_orb and not now_arg and cutoff_hhmm >= "15:20" and not paper_book.get("eod_sent") and (paper_book.get("trades") or paper_book.get("skipped")):
        return run_eod_report(today_iso, state_dir=st_dir)

    if not offline_orb and not now_arg and not clock_st.get("open"):
        print(f"NSE is closed ({clock_st.get('reason')}).")
        return 0

    # Sync broker.json and check hard daily limits BEFORE scanning
    sync_broker_state_for_risk(paper_book, paths["broker"], today_iso)
    max_trades_day = int(cfg.get("max_trades_per_day") or 3)
    max_daily_loss = float(cfg.get("max_daily_loss_inr") or 200.0)
    broker_orders = (load_json(paths["broker"], {}) or {}).get("orders") or []
    used_daily_risk = sum(float(o.get("max_loss") or 0.0) for o in broker_orders)

    if len(paper_book["trades"]) >= max_trades_day:
        print(f"HALT: max_trades_per_day ({len(paper_book['trades'])}/{max_trades_day}) reached.")
        return 0
    if used_daily_risk >= max_daily_loss:
        print(f"HALT: max_daily_loss_inr (₹{used_daily_risk:.2f}/₹{max_daily_loss:.2f}) reached.")
        return 0

    try_stops = ("or-mid", "or-low")
    try_targets = ("2R", "3R")

    # 2. Run ORB Scanner (before no_entries_after cutoff)
    no_after = cfg.get("no_entries_after") or "14:45"
    if cutoff_hhmm <= no_after or offline_orb or now_arg:
        scan_args = ["india-scanner/scan.py", "orb"] + now_flags
        if offline_orb:
            scan_args += ["--offline", offline_orb, "--min-price", "0", "--symbols", "RELIANCE,TCS,M&M"]
        rc_sc, sc_out = run_cmd(scan_args)
        print(sc_out)

        watchlist = load_json(os.path.join(TRADER, "watchlist.json"), {})
        hits = watchlist.get("hits") or []
        budget_inr = float(cfg.get("budget") or 10000.0)
        hits.sort(key=lambda h: (0 if (h.get("price") or 99999) <= budget_inr else 1, h.get("symbol", "")))

        if not sent_state.get("morning_ping") and not offline_orb and not now_arg:
            sent_state["morning_ping"] = True
            save_json(paths["sent"], sent_state)
            hit_lines = []
            for h in hits[:8]:
                hit_lines.append(
                    f"• *{h.get('symbol')}*: Breakout @ ₹{float(h.get('price') or 0):.2f} ({h.get('at')}) | "
                    f"9:15–9:30 Range: ₹{float(h.get('or_low') or 0):.2f} – ₹{float(h.get('or_high') or 0):.2f}"
                )
            hits_block = "\n".join(hit_lines) if hit_lines else "• Abhi 9:15–9:30 AM ki range me koi stock breakout nahi hua hai; har 5 min me scan chalu hai."
            notify_all(
                f"🤖 *9:30 AM IST — OPENING RANGE LOCKED & LIVE SCANNER ACTIVE ({today_iso})*\n"
                f"💰 *Budget:* ₹{budget_inr:,.0f} (`allow_margin: {bool(cfg.get('allow_margin', False))}`) | "
                f"*Max Loss:* ₹{float(cfg.get('max_loss_per_trade_inr', 200)):,.0f}/trade, ₹{max_daily_loss:,.0f}/day | *Max Trades:* {max_trades_day}/day\n\n"
                f"📊 *INITIAL 15m ORB BREAKOUT CANDIDATES ({len(hits)} Matches):*\n"
                f"{hits_block}\n\n"
                f"⚡ Ab bot har candidate par `india-exit`, `india-budget` (after-charges R:R >= {float(cfg.get('min_reward_risk_after_charges', 1.0)):.1f}), aur `india-risk` chala kar valid setup ka Chart + Poora Brief bhejega!"
            )

        sent_count_this_run = 0
        for hit in hits:
            sym = hit["symbol"]
            if sym in sent_state["symbols"]:
                continue
            if len(paper_book["trades"]) >= max_trades_day or sent_count_this_run >= max_alerts_per_run:
                break

            sync_broker_state_for_risk(paper_book, paths["broker"], today_iso)
            best, reject_reason = evaluate_and_optimize_symbol(
                sym, now_flags, today_iso, cutoff_hhmm, paths, cfg, offline_5m, offline_60d, try_stops, try_targets
            )
            if not best:
                paper_book["skipped"].append({"symbol": sym, "time": cutoff_hhmm, "reason": reject_reason})
                save_json(paths["book"], paper_book)
                sent_state["symbols"].append(sym)
                save_json(paths["sent"], sent_state)
                continue

            sz_inner = best["sz_inner"]
            loss_all_in = float(sz_inner.get("loss_at_stop_with_charges") or 0.0)
            broker_orders = (load_json(paths["broker"], {}) or {}).get("orders") or []
            used_daily_risk = sum(float(o.get("max_loss") or 0.0) for o in broker_orders)
            if used_daily_risk + loss_all_in > max_daily_loss + 0.01:
                reason = f"{sym}: daily loss cap would exceed ₹{max_daily_loss:.2f} (used ₹{used_daily_risk:.2f} + new ₹{loss_all_in:.2f})"
                print("BLOCKED:", reason)
                paper_book["skipped"].append({"symbol": sym, "time": cutoff_hhmm, "reason": reason})
                save_json(paths["book"], paper_book)
                continue

            sym_news_doc = {}
            if not offline_orb:
                rc_nj, nw_str = run_cmd(["india-news/news.py", "--tickers", sym, "--all", "--hours", "24", "--no-moves", "--json"])
                if rc_nj == 0 and nw_str.strip().startswith("{"):
                    try:
                        sym_news_doc = json.loads(nw_str)
                    except Exception:
                        sym_news_doc = {}

            plan_doc = best["plan"]
            tm_doc = best["tm"]
            entry_doc = best["entry_doc"]
            risk_doc = load_json(paths["risk"], {})
            sz_doc = best["sz_doc"]

            entry_px = float(best["fill_price"])
            signal_px = float(best["signal_price"])
            stop_px = float(sz_inner.get("stop") or plan_doc.get("stop") or 0.0)
            target_px = float(sz_inner.get("target") or plan_doc.get("target") or 0.0)
            risk_sh = float(sz_inner.get("risk_per_share") or abs(entry_px - stop_px))
            qty = int(sz_inner.get("qty") or 0)
            pos_cost = float(sz_inner.get("cost") or 0.0)
            ch_stop = float((sz_inner.get("charges_at_stop") or {}).get("total") or 0.0)
            or_info = plan_doc.get("opening_range") or entry_doc.get("opening_range") or {}
            or_high = float(or_info.get("high") or 0.0)
            or_low = float(or_info.get("low") or 0.0)

            chart_path = generate_chart(
                trader_dir=TRADER,
                offline_chart=offline_5m or offline_orb,
                size_json=sz_doc,
                state_dir=st_dir,
            )
            print("Generated setup chart PNG at:", chart_path)

            caption = generate_setup_brief(
                sym,
                entry_doc,
                plan_doc,
                sz_doc,
                tm_doc,
                risk_doc,
                news_json=sym_news_doc,
                state_dir=st_dir,
                cron_delay_min=best["cron_delay_min"],
            )
            notify_all(caption, chart_path)

            trade_record = {
                "symbol": sym,
                "setup_name": "15m Opening Range Breakout (ORB)",
                "setup_short": f"15m ORB (>₹{or_high:.1f}) | {best['stop_rule']}/{best['target_r']}",
                "or_high": or_high,
                "or_low": or_low,
                "stop_rule": best["stop_rule"],
                "target_r": best["target_r"],
                "entry_time": plan_doc.get("entry_time", "09:35 AM"),
                "fill_time": best["fill_time"],
                "cron_delay_min": best["cron_delay_min"],
                "entry_bar_start": best["entry_bar_start"],
                "last_checked_hhmm": best["entry_bar_start"],
                "qty": qty,
                "cost": pos_cost,
                "signal_price": signal_px,
                "entry": entry_px,
                "initial_stop": stop_px,
                "stop": stop_px,
                "one_r_price": round(entry_px + risk_sh, 2),
                "target": target_px,
                "risk_per_share": risk_sh,
                "charges": ch_stop,
                "all_in_stop_loss": loss_all_in,
                "rr_after_charges": best["rr_after_charges"],
                "status": "OPEN",
                "exit_price": None,
                "exit_time": None,
                "exit_reason": None,
                "trailed_to_cost": False,
                "gross_pnl": None,
                "net_pnl": None,
            }
            paper_book["trades"].append(trade_record)
            save_json(paths["book"], paper_book)
            sync_broker_state_for_risk(paper_book, paths["broker"], today_iso)

            sent_state["symbols"].append(sym)
            save_json(paths["sent"], sent_state)
            sent_count_this_run += 1

    if send_eod_after and (paper_book.get("trades") or paper_book.get("skipped")):
        update_paper_trades(paper_book, paths, today_iso, cfg, cutoff_hhmm="15:25", offline_5m=offline_5m, send_live_alerts=True)
        run_eod_report(today_iso=today_iso, offline_5m=offline_5m, state_dir=st_dir)

    return 0


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--mode", choices=["auto_schedule", "intraday", "premarket", "eod_report", "test", "replay_today"], default="intraday")
    ap.add_argument("--now", default=None)
    ap.add_argument("--offline-orb", default=None)
    ap.add_argument("--offline-5m", default=None)
    ap.add_argument("--offline-60d", default=None)
    ap.add_argument("--target", default="2R")
    a = ap.parse_args()

    if a.mode == "auto_schedule":
        cur = now_ist()
        if cur.weekday() >= 5:
            print(f"Weekend ({cur.strftime('%A')}) — market closed. Exiting.")
            sys.exit(0)
        hhmm = cur.strftime("%H:%M")
        today_iso = cur.date().isoformat()
        st_dir = os.path.join(TRADER, "state")
        paths = get_state_paths(st_dir)
        sent_st = load_json(paths["sent"], {"date": today_iso})
        if sent_st.get("date") != today_iso:
            sent_st = {"date": today_iso}
        book_st = load_paper_book(paths["book"], today_iso)

        print(f"Auto-Schedule triggered at actual IST time: {today_iso} {hhmm} IST")
        if hhmm < "08:15" or hhmm > "16:00":
            print(f"Outside active IST window (08:15–16:00 IST). Current IST is {hhmm}. Ignoring delayed GitHub cron!")
            sys.exit(0)
        elif "08:15" <= hhmm <= "09:14":
            if sent_st.get("premarket_done"):
                print("Pre-market brief already sent today. Exiting.")
                sys.exit(0)
            sys.exit(run_premarket())
        elif "09:15" <= hhmm < "09:30":
            print("9:15–9:30 AM Opening Range is currently forming. Waiting for 9:30 AM close.")
            sys.exit(0)
        elif "09:30" <= hhmm <= "15:20":
            sys.exit(run_intraday())
        else:
            # 15:21 to 16:00 IST -> Evening Report Card (once per day)
            if book_st.get("eod_sent"):
                print("Evening report card already sent today. Exiting.")
                sys.exit(0)
            sys.exit(run_eod_report(today_iso))
    elif a.mode == "premarket":
        sys.exit(run_premarket())
    elif a.mode == "eod_report":
        sys.exit(run_eod_report())
    elif a.mode == "replay_today":
        # Uses isolated trader/state_sim/ so live trader/state/ is NEVER deleted!
        sim_dir = os.path.join(TRADER, "state_sim")
        os.makedirs(sim_dir, exist_ok=True)
        for fn in ("sent_today.json", "paper_book.json", "broker.json"):
            p = os.path.join(sim_dir, fn)
            if os.path.exists(p):
                os.remove(p)
        cur = now_ist()
        d = cur.date()
        while d.weekday() >= 5:
            d -= datetime.timedelta(days=1)
        sim_now = f"{d.isoformat()} 09:40"
        print(f"Replaying session {sim_now} IST in isolated sandbox (trader/state_sim/)...")
        sys.exit(run_intraday(now_arg=sim_now, target_r=a.target, max_alerts_per_run=3, send_eod_after=True, state_dir=sim_dir))
    elif a.mode == "test":
        # Uses isolated trader/state_sim/ so live trader/state/ is NEVER deleted!
        sim_dir = os.path.join(TRADER, "state_sim")
        os.makedirs(sim_dir, exist_ok=True)
        for fn in ("sent_today.json", "paper_book.json", "paper_passbook.json", "broker.json"):
            p = os.path.join(sim_dir, fn)
            if os.path.exists(p):
                os.remove(p)
        print("Running TEST mode in isolated sandbox (trader/state_sim/)...")
        sys.exit(run_intraday(
            now_arg="2026-10-19 09:36",
            offline_orb=os.path.join(ROOT, "tests/fixtures/orb-bundle-2026-10-19.json"),
            offline_5m=os.path.join(ROOT, "tests/fixtures/RELIANCE-2026-10-19-5m.json"),
            offline_60d=os.path.join(ROOT, "tests/fixtures/RELIANCE-60d-5m.json"),
            target_r=a.target,
            send_eod_after=True,
            state_dir=sim_dir,
        ))
    else:
        sys.exit(run_intraday(a.now, a.offline_orb, a.offline_5m, a.offline_60d, a.target))
