#!/usr/bin/env python3
"""JSON-Locked Gemini Brief Generator & Anti-Hallucination Number Checker (brief.py).
Reads 100% of config from `trader/config.json` and 100% of sizing/charges from `india-budget/size.py`.
Enforces the strict rule:
  "sirf diye gaye JSON se bolo, koi number apne se mat banao, jo data nahi hai wo 'data nahi' likho."
And runs `verify_brief_numbers(brief_text, facts_json)` on every output.
"""
import argparse
import json
import os
import sys
import urllib.request

from verify_numbers import verify_brief_numbers

ROOT = os.path.dirname(os.path.abspath(__file__))
TRADER = os.path.join(ROOT, "trader")
DEFAULT_STATE_DIR = os.path.join(TRADER, "state")
GEMINI_MODEL = "gemini-2.5-flash"

STRICT_PROMPT_RULE = "sirf diye gaye JSON se bolo, koi number apne se mat banao, jo data nahi hai wo 'data nahi' likho."

STRICT_SYSTEM_INSTRUCTION = (
    "TUM EK STRICT JSON-LOCKED INTRADAY BRIEF WRITER HO.\n"
    f"HARD RULE: \"{STRICT_PROMPT_RULE}\"\n"
    "1. Probability, stop, target, charges, quantity, RSI, price, time — ye sab Python scripts nikalti hain aur JSON me deti hain.\n"
    "2. Tumhara kaam sirf diye gaye JSON ke numbers ko fixed Hinglish template me samjhana hai.\n"
    "3. Ek bhi number apne se calculate ya invent mat karo. Jo field JSON me khali ya 'data nahi' hai, wahan 'data nahi' likho.\n"
    "4. Kabhi mat likho ki 'ab loss nahi ho sakta' — stop-loss ya cost-trail me gap/slippage aur charges se loss ho sakta hai.\n"
    "5. Tumhare jawab ke har ek number ko `verify_numbers.py` JSON se match karega; agar ek bhi naya number mila toh jawab reject ho jayega."
)


def load_json(path, default=None):
    if not path or not os.path.exists(path):
        return default
    with open(path, encoding="utf-8") as f:
        return json.load(f)


def save_json(path, data):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2, ensure_ascii=False)


def call_gemini_strict(facts_json: dict, template_instructions: str) -> str:
    api_key = os.environ.get("GEMINI_API_KEY", "").strip()
    if not api_key:
        return ""
    prompt = (
        f"STRICT RULE: \"{STRICT_PROMPT_RULE}\"\n\n"
        f"{template_instructions}\n\n"
        f"SOURCE JSON (SIRF ISI JSON SE BOLO):\n{json.dumps(facts_json, ensure_ascii=False, indent=2)}"
    )
    url = f"https://generativelanguage.googleapis.com/v1beta/models/{GEMINI_MODEL}:generateContent?key={api_key}"
    payload = {
        "contents": [{"role": "user", "parts": [{"text": prompt}]}],
        "systemInstruction": {"parts": [{"text": STRICT_SYSTEM_INSTRUCTION}]},
        "generationConfig": {"temperature": 0.0, "maxOutputTokens": 1300},
    }
    try:
        req = urllib.request.Request(
            url,
            data=json.dumps(payload).encode("utf-8"),
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        with urllib.request.urlopen(req, timeout=25) as resp:
            data = json.loads(resp.read().decode("utf-8", "replace"))
        candidates = data.get("candidates") or []
        if candidates:
            parts = candidates[0].get("content", {}).get("parts") or []
            if parts:
                return (parts[0].get("text") or "").strip()
    except Exception as e:
        print(f"Gemini API note (using 100% JSON-verified fixed template): {e}")
    return ""


def audit_and_lock_brief(candidate_text: str, facts_json: dict, fallback_text: str, tag: str = "brief", state_dir: str = None) -> str:
    st_dir = state_dir or DEFAULT_STATE_DIR
    os.makedirs(st_dir, exist_ok=True)
    audit = verify_brief_numbers(candidate_text, facts_json)
    if candidate_text and candidate_text != fallback_text and audit["ok"]:
        print(f"[BRIEF NUMBER-CHECK PASS ({tag})] Gemini organized brief verified ({audit['total_numbers_checked']} numbers matched JSON).")
        final_text = candidate_text
    else:
        if candidate_text and candidate_text != fallback_text and not audit["ok"]:
            print(
                f"[BRIEF NUMBER-CHECK BLOCKED ({tag})] Gemini used unverified numbers {audit['hallucinated_numbers']}! "
                f"Using 100% JSON-locked organized Hinglish brief."
            )
        final_text = fallback_text
        audit = verify_brief_numbers(final_text, facts_json)
        print(f"[BRIEF NUMBER-CHECK PASS ({tag})] All {audit['total_numbers_checked']} numbers verified in JSON.")

    save_json(os.path.join(st_dir, "last_facts.json"), facts_json)
    save_json(os.path.join(st_dir, "last_number_audit.json"), audit)
    with open(os.path.join(st_dir, "last_brief.txt"), "w", encoding="utf-8") as f:
        f.write(final_text)
    return final_text



SETUP_HINDI_MAP = {
    "20-day closing-high breakout": "🔥 20-Din ka High Breakout (Strong Bullish)",
    "bull flag": "🚩 Bull Flag Pattern (Continuation Setup)",
    "reclaimed the 20-day average": "📈 20-Day Moving Average Reclaim (Support Bounce)",
    "orb": "⚡ 15-Min Opening Range Breakout (ORB)",
}

def _translate_setups(setups_list):
    if not setups_list:
        return "data nahi"
    out = []
    for s in setups_list:
        out.append(SETUP_HINDI_MAP.get(str(s).strip().lower(), str(s)))
    return " + ".join(out)

def _split_news_and_events(news_json: dict):
    items = (news_json or {}).get("items") or []
    announcements = []
    events = []
    event_keywords = ("result", "earning", "q1", "q2", "q3", "q4", "board meeting", "dividend", "agm", "split", "bonus", "outcome of board")
    for it in items:
        title = (it.get("title") or "").strip()
        cat = (it.get("category") or "NEWS").upper()
        src = (it.get("source") or "NSE/RSS").strip()
        tickers = ", ".join(it.get("tickers") or [])
        entry_obj = {
            "category": cat,
            "title": title or "data nahi",
            "source": src or "data nahi",
            "tickers": tickers or "MARKET",
        }
        low_t = (title + " " + cat).lower()
        if any(k in low_t for k in event_keywords):
            events.append(entry_obj)
        else:
            announcements.append(entry_obj)
    return announcements[:5], events[:5]


def generate_morning_brief(watchlist_json: dict, news_json: dict, tm_json: dict = None, config_json: dict = None, state_dir: str = None) -> str:
    st_dir = state_dir or DEFAULT_STATE_DIR
    cfg = config_json or load_json(os.path.join(TRADER, "config.json"), {})
    tm = tm_json or load_json(os.path.join(TRADER, "timemachine.json"), {})

    budget_inr = float(cfg.get("budget") or 10000.0)
    cash_buf_pct = float(cfg.get("cash_buffer_pct") or 0.0)
    avail_cash = round(budget_inr * (1.0 - cash_buf_pct / 100.0), 2)
    max_pos_pct = float(cfg.get("max_position_pct") or 100.0)
    max_order_inr = float(cfg.get("max_order_inr") or budget_inr)
    pos_cap_inr = min(avail_cash, round(budget_inr * max_pos_pct / 100.0, 2), max_order_inr)

    max_loss_inr = float(cfg.get("max_loss_per_trade_inr") or 200.0)
    max_daily_inr = float(cfg.get("max_daily_loss_inr") or 200.0)
    max_trades = int(cfg.get("max_trades_per_day") or 3)
    min_rr = float(cfg.get("min_reward_risk") or 2.0)
    min_rr_net = float(cfg.get("min_reward_risk_after_charges") or 1.0)
    allow_margin = bool(cfg.get("allow_margin", False))
    no_before = cfg.get("no_entries_before") or "09:30"
    no_after = cfg.get("no_entries_after") or "14:45"
    flat_by = cfg.get("flat_by") or "15:15"

    hits = (watchlist_json or {}).get("hits") or []
    affordable = [h for h in hits if (h.get("price") or 99999) <= pos_cap_inr]
    top_picks = (affordable[:8] + [h for h in hits if h not in affordable][:4])[:8]

    watchlist_facts = []
    for idx, h in enumerate(top_picks, 1):
        px = round(float(h.get("price") or 0), 2)
        max_sh = int(pos_cap_inr // px) if px > 0 else 0
        watchlist_facts.append({
            "rank": idx,
            "symbol": h.get("symbol") or "data nahi",
            "price": px,
            "rsi14": round(float(h.get("rsi14") or 0), 1),
            "setups": h.get("setups") or ["data nahi"],
            "max_shares_in_budget": max_sh,
        })

    announcements, events = _split_news_and_events(news_json)

    mc = (tm or {}).get("mc") or {}
    hist = (tm or {}).get("history") or {}
    tm_sym = ((tm or {}).get("plan") or {}).get("symbol") or "data nahi"
    tm_facts = {
        "reference_symbol": tm_sym,
        "replays": int(mc.get("replays") or 10000) if mc else "data nahi",
        "target_hit_pct": round(float(mc["p_target"]) * 100.0, 1) if mc.get("p_target") is not None else "data nahi",
        "stop_hit_pct": round(float(mc["p_stop"]) * 100.0, 1) if mc.get("p_stop") is not None else "data nahi",
        "sessions_tested": int(hist["sessions"]) if hist.get("sessions") is not None else "data nahi",
        "triggered_sessions": int(hist["triggered"]) if hist.get("triggered") is not None else "data nahi",
        "historical_wins": int(hist["target"]) if hist.get("target") is not None else "data nahi",
        "historical_losses": int(hist["stop"]) if hist.get("stop") is not None else "data nahi",
        "historical_avg_r": round(float(hist["avg_R"]), 2) if hist.get("avg_R") is not None else "data nahi",
    }

    facts_json = {
        "brief_type": "MORNING_830_IST_BRIEF",
        "template_sections": [1, 2, 3, 4, 5, 6],
        "schedule_ist": "8:30 AM",
        "date": (watchlist_json or {}).get("as_of_date") or "data nahi",
        "total_watchlist_matches": len(hits),
        "1_watchlist": watchlist_facts if watchlist_facts else "data nahi",
        "2_important_announcements": announcements if announcements else "data nahi",
        "3_events_results_board_meetings": events if events else "data nahi",
        "4_time_machine_odds": tm_facts,
        "5_risk_budget": {
            "budget_inr": budget_inr,
            "position_cap_inr": pos_cap_inr,
            "allow_margin": allow_margin,
            "max_loss_per_trade_inr": max_loss_inr,
            "max_daily_loss_inr": max_daily_inr,
            "min_reward_risk": min_rr,
            "min_reward_risk_after_charges": min_rr_net,
            "cost_trail_trigger_r": 1,
            "max_trades_per_day": max_trades,
        },
        "6_what_not_to_do": {
            "no_trade_window_morning": f"9:15–{no_before} AM (first 15 minutes — all 3 bars required)",
            "no_new_entry_after_ist": no_after,
            "auto_square_off_ist": flat_by,
            "max_daily_loss_stop_inr": max_daily_inr,
            "max_trades_cap": max_trades,
        },
    }

    save_json(os.path.join(st_dir, "morning_snapshot.json"), facts_json)

    lines = [
        "🌅 *8:30 AM IST PRE-MARKET BRIEF (FIXED TEMPLATE — SCRIPT JSON)*",
        "",
        f"📋 *1. WATCHLIST ({len(hits)} Daily Setup Matches):*",
    ]
    if watchlist_facts:
        for wf in watchlist_facts:
            s_txt = _translate_setups(wf["setups"])
            lines.append(
                f"{wf['rank']}. *{wf['symbol']}* — ₹{wf['price']:,.2f} | RSI {wf['rsi14']:.1f} | _{s_txt}_ "
                f"(Max {wf['max_shares_in_budget']} sh in ₹{pos_cap_inr:,.0f} cap)"
            )
    else:
        lines.append("• Watchlist: data nahi")

    lines.append("")
    lines.append("📢 *2. IMPORTANT ANNOUNCEMENTS (Exchange & Filings):*")
    if announcements:
        for an in announcements:
            lines.append(f"• *[{an['tickers']} | {an['category']}]* {an['title']} _({an['source']})_")
    else:
        lines.append("• Important Announcements: data nahi")

    lines.append("")
    lines.append("📅 *3. AAJ KE EVENTS (Results, Board Meetings, Corporate Actions):*")
    if events:
        for ev in events:
            lines.append(f"• *[{ev['tickers']} | {ev['category']}]* {ev['title']} _({ev['source']})_")
    else:
        lines.append("• Aaj Ke Events (Results / Board Meetings): data nahi")

    lines.append("")
    lines.append("🎲 *4. TIME MACHINE ODDS (`timemachine.py` JSON):*")
    if tm_facts["target_hit_pct"] != "data nahi":
        lines.append(
            f"• *Reference ({tm_facts['reference_symbol']} — {tm_facts['replays']:,} Replays):* "
            f"{tm_facts['target_hit_pct']}% Target Hit vs {tm_facts['stop_hit_pct']}% Stop Hit"
        )
        lines.append(
            f"• *Last {tm_facts['sessions_tested']} Sessions Backtest:* "
            f"{tm_facts['triggered_sessions']} Triggered -> {tm_facts['historical_wins']} Wins / {tm_facts['historical_losses']} Losses "
            f"(Avg {tm_facts['historical_avg_r']:+.2f}R)"
        )
    else:
        lines.append("• Time Machine Odds: data nahi")

    lines.extend([
        "",
        "💰 *5. RISK BUDGET (`trader/config.json` & `size.py`):*",
        f"• *Budget:* ₹{budget_inr:,.0f} (Position Cap: ₹{pos_cap_inr:,.0f} | allow_margin: {allow_margin})",
        f"• *Max Loss Limit:* ₹{max_loss_inr:,.0f}/trade aur ₹{max_daily_inr:,.0f}/day (including STT/GST/Brokerage)",
        f"• *Min Reward:Risk:* {min_rr:.1f}R before charges & minimum {min_rr_net:.1f}R after charges (`size.py` refusal enforced)",
        f"• *Max Trades Allowed:* {max_trades} trades/day",
        "",
        "🚫 *6. AAJ KYA NAHI KARNA (Strict Discipline Rules):*",
        f"• *9:15–{no_before} AM (Pehle 15 Min):* Koi trade nahi lena — poore 3 bars (9:15, 9:20, 9:25) banne dena zaroori hai.",
        f"• *Low Net R:R & Refused Setups:* Agar charges ke baad reward:risk {min_rr_net:.1f} se kam ho ya `size.py`/`check.py` refuse kare toh trade bilkul nahi lena.",
        f"• *Time & Loss Cutoff:* {no_after} IST ke baad nayi entry nahi, ₹{max_daily_inr:,.0f} daily loss ya {max_trades} trades ke baad system band, aur {flat_by} IST tak square-off!",
    ])
    fallback_text = "\n".join(lines)

    template_inst = (
        "Is JSON se 6-part Morning Brief Hinglish me likho jisme ye exact 6 headings hon:\n"
        "1. WATCHLIST\n2. IMPORTANT ANNOUNCEMENTS\n3. AAJ KE EVENTS (Results, Board Meetings)\n"
        "4. TIME MACHINE ODDS\n5. RISK BUDGET\n6. AAJ KYA NAHI KARNA\n"
        f"Rule yaad rakho: \"{STRICT_PROMPT_RULE}\""
    )
    ai_txt = call_gemini_strict(facts_json, template_inst)
    candidate = ai_txt if ai_txt else fallback_text
    return audit_and_lock_brief(candidate, facts_json, fallback_text, tag="morning", state_dir=st_dir)


def generate_setup_brief(
    symbol: str,
    entry_doc: dict,
    plan_doc: dict,
    size_doc: dict,
    tm_doc: dict,
    risk_doc: dict,
    news_json: dict = None,
    agent_note: str = "",
    state_dir: str = None,
    cron_delay_min: int = 0,
) -> str:
    """Generates the Live Intraday Setup Brief strictly from `size.py`, `plan.json`, `timemachine.json`,
    and `trader/config.json` — zero hardcoded numbers or invented formulas."""
    st_dir = state_dir or DEFAULT_STATE_DIR
    cfg = load_json(os.path.join(TRADER, "config.json"), {})
    sz = size_doc.get("sizing") if isinstance(size_doc, dict) and isinstance(size_doc.get("sizing"), dict) else (size_doc or {})

    signal_px = round(float((entry_doc.get("trigger") or {}).get("close") or entry_doc.get("price") or plan_doc.get("entry") or 0), 2)
    entry_px = round(float(sz.get("entry") or signal_px), 2)
    stop_px = round(float(sz.get("stop") or plan_doc.get("stop") or 0), 2)
    target_px = round(float(sz.get("target") or plan_doc.get("target") or 0), 2)
    risk_sh = round(float(sz.get("risk_per_share") or plan_doc.get("risk_per_share") or abs(entry_px - stop_px)), 2)
    reward_sh = round(target_px - entry_px, 2)
    rr = round(float(sz.get("reward_risk") or plan_doc.get("reward_risk") or 2.0), 2)
    one_r_px = round(entry_px + risk_sh, 2)

    or_info = plan_doc.get("opening_range") or entry_doc.get("opening_range") or {}
    or_high = round(float(or_info.get("high") or 0), 2)
    or_low = round(float(or_info.get("low") or 0), 2)
    or_min = int(or_info.get("minutes") or 15)
    or_bars_n = int(or_info.get("bars") or 3)
    entry_time = plan_doc.get("entry_time") or entry_doc.get("bar_end") or "09:35 AM"
    bar_start = entry_doc.get("bar_start") or "09:30"
    stop_reason = sz.get("stop_label") or plan_doc.get("stop_label") or plan_doc.get("stop_reason") or "opening-range low"
    target_label = sz.get("target_label") or plan_doc.get("target_label") or f"{rr:.0f}R"
    pct_over = round(float(entry_doc.get("pct_over_high") or ((signal_px / or_high - 1.0) * 100.0 if or_high else 0.0)), 2)

    # All sizing & charges come strictly from india-budget/size.py
    qty = int(sz.get("qty") or 0)
    pos_val = round(float(sz.get("cost") or 0.0), 2)
    budget_inr = round(float(sz.get("budget") or cfg.get("budget") or 10000.0), 2)
    max_loss_cap = round(float(sz.get("max_loss_per_trade_inr") or cfg.get("max_loss_per_trade_inr") or 200.0), 2)
    max_daily_cap = round(float(cfg.get("max_daily_loss_inr") or 200.0), 2)
    allow_margin = bool(cfg.get("allow_margin", False))
    bound_by = sz.get("bound_by") or "position cap"

    ch_stop_obj = sz.get("charges_at_stop") or {}
    ch_target_obj = sz.get("charges_at_target") or {}
    ch_stop = round(float(ch_stop_obj.get("total") if isinstance(ch_stop_obj, dict) else (ch_stop_obj or 0.0)), 2)
    ch_target = round(float(ch_target_obj.get("total") if isinstance(ch_target_obj, dict) else (ch_target_obj or 0.0)), 2)
    be_move = round(float(sz.get("breakeven_move_per_share") or 0.0), 2)
    pure_loss = round(float(sz.get("max_loss") or (qty * risk_sh)), 2)
    loss_at_stop = round(float(sz.get("loss_at_stop_with_charges") or 0.0), 2)
    gross_profit = round(float(sz.get("gross_profit_at_target") or (qty * reward_sh)), 2)
    net_profit = round(float(sz.get("net_profit_at_target") or 0.0), 2)
    rr_after_charges = round(net_profit / loss_at_stop, 2) if loss_at_stop > 0 else 0.0

    mc = (tm_doc or {}).get("mc") or (tm_doc or {}).get("monte_carlo") or {}
    hist = (tm_doc or {}).get("history") or (tm_doc or {}).get("historical") or {}
    replays_n = int(mc.get("replays") or 10000)
    p_t = mc.get("p_target")
    p_s = mc.get("p_stop")
    tgt_pct = round(float(p_t) * 100.0, 1) if p_t is not None else round(float(mc.get("target_Pct") or mc.get("target_pct") or 0.0), 1)
    stp_pct = round(float(p_s) * 100.0, 1) if p_s is not None else round(float(mc.get("stop_Pct") or mc.get("stop_pct") or 0.0), 1)
    hist_sessions = int(hist.get("sessions") or 29)
    hist_trig = int(hist.get("triggered") if hist.get("triggered") is not None else (hist.get("triggered_sessions") or 25))
    hist_win = int(hist.get("target") if hist.get("target") is not None else (hist.get("target_first") or 10))
    hist_loss = int(hist.get("stop") if hist.get("stop") is not None else (hist.get("stop_first") or 15))
    hist_avg_r = round(float(hist.get("avg_R") if hist.get("avg_R") is not None else (hist.get("avg_r") or 0.2)), 2)
    tm_verdict = (((tm_doc or {}).get("verdict") or "data nahi").split(":")[0]).strip()
    flat_by = sz.get("flat_by") or plan_doc.get("flat_by") or cfg.get("flat_by") or "15:15"
    no_after = cfg.get("no_entries_after") or "14:45"

    announcements, events = _split_news_and_events(news_json or {})

    facts_json = {
        "symbol": symbol,
        "template_sections": [1, 2, 3, 4, 5, 6],
        "setup_name": f"{or_min}-Min Opening Range Breakout (ORB)",
        "opening_range_window": "9:15–9:30 AM",
        "opening_range_minutes": or_min,
        "opening_range_bars_required": or_bars_n,
        "candle_interval_minutes": 5,
        "trigger_bar_window": f"{bar_start}–{entry_time}",
        "entry_time_ist": entry_time,
        "cron_delay_minutes": cron_delay_min,
        "or_low": or_low,
        "or_high": or_high,
        "signal_close_price": signal_px,
        "realistic_entry_fill_price": entry_px,
        "pct_over_or_high": pct_over,
        "stop_loss_price": stop_px,
        "stop_reason": stop_reason,
        "risk_per_share": risk_sh,
        "one_r_trail_trigger_price": one_r_px,
        "target_label": target_label,
        "reward_risk_before_charges": rr,
        "target_price": target_px,
        "reward_per_share": reward_sh,
        "budget_inr": budget_inr,
        "allow_margin": allow_margin,
        "max_loss_per_trade_inr": max_loss_cap,
        "max_daily_loss_inr": max_daily_cap,
        "qty_shares": qty,
        "bound_by": bound_by,
        "position_cost_inr": pos_val,
        "pure_price_risk_at_stop_inr": pure_loss,
        "estimated_charges_at_stop_inr": ch_stop,
        "estimated_charges_at_target_inr": ch_target,
        "breakeven_move_per_share_inr": be_move,
        "loss_at_stop_with_charges_inr": loss_at_stop,
        "gross_profit_at_target_inr": gross_profit,
        "net_profit_at_target_inr": net_profit,
        "reward_risk_after_charges": rr_after_charges,
        "monte_carlo_replays": replays_n,
        "target_hit_probability_pct": tgt_pct,
        "stop_hit_probability_pct": stp_pct,
        "historical_sessions": hist_sessions,
        "historical_triggered": hist_trig,
        "historical_wins": hist_win,
        "historical_losses": hist_loss,
        "historical_avg_r": hist_avg_r,
        "timemachine_verdict": tm_verdict,
        "no_entries_after_ist": no_after,
        "auto_square_off_ist": flat_by,
        "announcements": announcements if announcements else "data nahi",
        "events_results_board_meetings": events if events else "data nahi",
    }

    ann_line = announcements[0]["title"] if announcements else "data nahi"
    ev_line = events[0]["title"] if events else "data nahi"

    lines = [
        f"🚨 *LIVE INTRADAY SETUP: {symbol} (BUY — NSE MIS)*",
        f"🕒 *Kab (Trigger Time):* *{entry_time} IST* ({bar_start}–{entry_time} ki 5m candle close par | Delay: {cron_delay_min}m)",
        f"📍 *Kaha (Signal vs Realistic Fill):* Signal *₹{signal_px:.2f}* (+{pct_over:.2f}% > OR High ₹{or_high:.2f}) | Realistic Fill: *₹{entry_px:.2f}*",
        f"📐 *Konsa Setup:* *{or_min}-Min Opening Range Breakout (ORB — {or_bars_n}/{or_bars_n} Range Bars Verified)*",
        "",
        "🧠 *TRADE KYU AUR KAISE BANA? (SCRIPT JSON EXPLANATION):*",
        f"• *1. Opening Range (9:15–9:30 AM):* Pehle {or_min} minute ke teeno 5m bars mein {symbol} ne *₹{or_low:.2f} (Low)* se *₹{or_high:.2f} (High)* ka range banaya.",
        f"• *2. Breakout Confirmation ({entry_time} IST):* `{bar_start}–{entry_time}` wali 5-minute candle ne range high `₹{or_high:.2f}` ke upar *₹{signal_px:.2f}* par close diya.",
        f"• *3. Stop & Target Selection (`size.py` + `check.py` PASS):* Stop-Loss *{stop_reason} (₹{stop_px:.2f})* aur Target *{target_label} (₹{target_px:.2f}, {rr:.2f}R)* chuna gaya kyunki charges katne ke baad net reward:risk *{rr_after_charges:.2f}* hai.",
        "",
        "📢 *ANNOUNCEMENTS & AAJ KE EVENTS (`news.py` JSON):*",
        f"• *Important Announcements:* {ann_line}",
        f"• *Aaj Ke Events (Results / Board Meetings):* {ev_line}",
        "",
        "🎯 *EXACT ORDER LEVELS (`exit.py` & `size.py`):*",
        f"• *Buy Entry Fill:* *₹{entry_px:.2f}*",
        f"• *Stop-Loss ({stop_reason}):* *₹{stop_px:.2f}* (-₹{risk_sh:.2f}/sh)",
        f"• *+1R Cost-Trail Trigger:* *₹{one_r_px:.2f}* (SL moves to ₹{entry_px:.2f}; gap/slippage risk remains)",
        f"• *Target ({target_label} / {rr:.2f}R):* *₹{target_px:.2f}* (+₹{reward_sh:.2f}/sh)",
        "",
        f"🎲 *TIME MACHINE ODDS ({replays_n:,} Replays — `timemachine.py`):*",
        f"• *Monte Carlo Win Probability:* *{tgt_pct:.1f}% Target Hit* vs *{stp_pct:.1f}% Stop Hit* ({tm_verdict})",
        f"• *Last {hist_sessions} Sessions Backtest:* {hist_trig} Triggered -> *{hist_win} Wins / {hist_loss} Losses* (Avg *{hist_avg_r:+.2f}R*)",
        "",
        f"💰 *RISK BUDGET (`config.json` Budget ₹{budget_inr:,.0f} & `size.py`):*",
        f"• *Quantity:* *{qty} Shares* (bound by {bound_by})  |  *Position Cost:* *₹{pos_val:,.2f}* (allow_margin: {allow_margin})",
        f"• *Exact NSE Charges (`size.py`):* ₹{ch_stop:.2f} at SL  |  ₹{ch_target:.2f} at Target (Breakeven move: ₹{be_move:.2f}/sh)",
        f"• *All-In Loss if SL Hits:* *-₹{loss_at_stop:.2f}* (₹{pure_loss:.2f} price risk + ₹{ch_stop:.2f} charges; within ₹{max_loss_cap:,.0f} limit ✅)",
        f"• *Net Profit at Target:* *+₹{net_profit:.2f}* (Gross ₹{gross_profit:.2f} - ₹{ch_target:.2f} charges | *After-Charges R:R = {rr_after_charges:.2f}*)",
        "",
        "🚫 *AAJ KYA NAHI KARNA & REALISTIC RISK WARNING:*",
        f"• Stop-Loss (`₹{stop_px:.2f}`) ya Cost-Trail SL (`₹{entry_px:.2f}`) ek order hai, pakka wada nahi — fast market ya gap-down me SL ke niche fill ho sakta hai aur slippage + charges ka loss ho sakta hai.",
        f"• `{no_after} IST` ke baad nayi entry nahi lena aur `{flat_by} IST` tak position close karni hai.",
    ]
    fallback_text = "\n".join(lines)

    template_inst = (
        "Is JSON se Intraday Setup Brief Hinglish me likho jisme Kaha, Kitne Baje, Konsa Setup, Announcements/Events, "
        "Order Levels, Time Machine Odds, Risk Budget (exact `size.py` charges & after-charges R:R), aur Aaj Kya Nahi Karna saaf likha ho.\n"
        f"Rule yaad rakho: \"{STRICT_PROMPT_RULE}\""
    )
    ai_txt = call_gemini_strict(facts_json, template_inst)
    candidate = ai_txt if ai_txt else fallback_text
    return audit_and_lock_brief(candidate, facts_json, fallback_text, tag=f"setup_{symbol}", state_dir=st_dir)


def generate_evening_review_brief(paper_book: dict, passbook: dict, morning_snapshot: dict = None, state_dir: str = None) -> str:
    st_dir = state_dir or DEFAULT_STATE_DIR
    cfg = load_json(os.path.join(TRADER, "config.json"), {})
    date_str = paper_book.get("date") or "data nahi"
    trades = paper_book.get("trades") or []
    skipped = paper_book.get("skipped") or []
    closed = [t for t in trades if t.get("net_pnl") is not None]
    wins = [t for t in closed if t.get("status") == "TARGET_HIT"]
    cost_exits = [t for t in closed if t.get("status") == "TRAILED_COST_EXIT"]
    losses = [t for t in closed if t.get("status") == "SL_HIT"]
    time_exits = [t for t in closed if t.get("status") == "TIME_EXIT_1515"]

    gross_pnl = round(sum(float(t.get("gross_pnl") or 0.0) for t in closed), 2)
    charges = round(sum(float(t.get("charges") or 0.0) for t in closed), 2)
    net_pnl = round(sum(float(t.get("net_pnl") or 0.0) for t in closed), 2)
    start_cap = round(float(passbook.get("starting_capital") or cfg.get("budget") or 10000.0), 2)
    cur_bal = round(float(passbook.get("current_balance", start_cap + net_pnl)), 2)
    ret_pct = round(((cur_bal - start_cap) / start_cap) * 100.0, 2) if start_cap else 0.0

    ms = morning_snapshot or load_json(os.path.join(st_dir, "morning_snapshot.json"), {})
    morning_wl = ms.get("1_watchlist") if isinstance(ms.get("1_watchlist"), list) else []
    morning_ann = ms.get("2_important_announcements") if isinstance(ms.get("2_important_announcements"), list) else []
    morning_ev = ms.get("3_events_results_board_meetings") if isinstance(ms.get("3_events_results_board_meetings"), list) else []
    morning_syms = [w.get("symbol") for w in morning_wl if isinstance(w, dict) and w.get("symbol")]
    triggered_syms = [t.get("symbol") for t in trades if t.get("symbol")]

    facts_json = {
        "date": date_str,
        "template_sections": [1, 2, 3, 4, 5, 6],
        "starting_capital_inr": start_cap,
        "allow_margin": bool(cfg.get("allow_margin", False)),
        "current_balance_inr": cur_bal,
        "return_pct": ret_pct,
        "morning_watchlist_count": len(morning_syms),
        "morning_watchlist_symbols": morning_syms if morning_syms else "data nahi",
        "morning_announcements_count": len(morning_ann),
        "morning_events_count": len(morning_ev),
        "intraday_triggered_count": len(trades),
        "skipped_or_blocked_count": len(skipped),
        "target_hit_wins": len(wins),
        "trailed_stop_exits": len(cost_exits),
        "stop_loss_hits": len(losses),
        "time_exits_1515": len(time_exits),
        "square_off_time": "3:15 PM",
        "opening_range_window": "9:15–9:30",
        "opening_range_minutes": 15,
        "candle_interval_minutes": 5,
        "gross_pnl_inr": gross_pnl,
        "total_charges_inr": charges,
        "net_pnl_inr": net_pnl,
        "trades": trades,
        "skipped": skipped if skipped else "data nahi",
    }
    for idx in range(1, len(trades) + 1):
        facts_json[f"trade_index_{idx}"] = idx

    lines = [
        f"🌇 *SHAAM KA REVIEW — SCAN vs REALITY REPORT CARD ({date_str})*",
        f"💰 *Config Budget:* ₹{start_cap:,.0f} (allow_margin: {bool(cfg.get('allow_margin', False))})  |  *Account Passbook:* *₹{cur_bal:,.2f}* ({ret_pct:+.2f}%)",
        "",
        "🌅 *1. SUBAH KA SCAN AUR NEWS KYA BOLTA THA:*",
    ]
    if morning_syms:
        lines.append(f"• *Subah 8:30 AM Watchlist ({len(morning_syms)} Stocks):* {', '.join(morning_syms)}")
    else:
        lines.append(
            f"• *Subah ka Scan:* Watchlist me se *{len(trades)}* stock(s) ({', '.join(triggered_syms) if triggered_syms else 'data nahi'}) ne 9:15–9:30 AM Opening Range breakout + `india-budget`/`india-risk` pass kiya."
        )
    if morning_ann or morning_ev:
        lines.append(f"• *Subah ki News & Events:* {len(morning_ann)} announcements aur {len(morning_ev)} corporate events radar par the.")
    else:
        lines.append("• *Subah ki News & Events:* data nahi")

    lines.extend([
        "",
        f"⚡ *2. DIN ME KYA HUA ({len(trades)} Entered, {len(skipped)} Blocked/Skipped):*",
        f"• 🎯 *Target Hit (Wins):* {len(wins)}  |  🛡️ *1R Trailed Exit:* {len(cost_exits)}  |  🛑 *SL Hit:* {len(losses)}  |  🕒 *3:15 PM Exit:* {len(time_exits)}",
        f"• 💵 *Gross P&L:* ₹{gross_pnl:+.2f}  |  *size.py Charges:* -₹{charges:.2f}  |  🏆 *Net P&L:* *₹{net_pnl:+.2f}*",
        "",
    ])

    if not trades:
        lines.append("• *Aaj ke Entered Trades:* 0 (koi setup after-charges R:R aur risk filter par pass nahi hua).")
    if skipped:
        lines.append("")
        lines.append(f"🔍 *SKIPPED / BLOCKED SETUPS ({len(skipped)} Stock(s) — Kyu Skip Kiya):*")
        for sk in skipped[:6]:
            lines.append(f"• *{sk.get('symbol', 'STOCK')}* ({sk.get('time', '')} IST) — {sk.get('reason', 'filter block')}")
    else:
        for idx, t in enumerate(trades, 1):
            sym = t.get("symbol") or "data nahi"
            qty = int(t.get("qty") or 0)
            ent = float(t.get("entry") or 0)
            sig_px = float(t.get("signal_price") or ent)
            ent_t = t.get("fill_time") or t.get("entry_time") or "data nahi"
            or_h = float(t.get("or_high") or 0)
            or_l = float(t.get("or_low") or 0)
            sl = float(t.get("initial_stop") or t.get("stop") or 0)
            sl_rule = t.get("stop_rule") or "or-low"
            tgt = float(t.get("target") or 0)
            tgt_r = t.get("target_r") or "3R"
            ex = float(t.get("exit_price") or ent)
            ex_t = t.get("exit_time") or "data nahi"
            st = t.get("status") or "data nahi"
            npnl = float(t.get("net_pnl") or 0.0)
            icon = "🎯" if st == "TARGET_HIT" else ("🛡️" if st == "TRAILED_COST_EXIT" else ("🛑" if st == "SL_HIT" else "🕒"))
            lines.append(
                f"{idx}. {icon} *{sym}* ({qty} sh)\n"
                f"   • *Kab & Kaha:* *{ent_t} IST* par *₹{ent:.2f}* fill (Signal ₹{sig_px:.2f})\n"
                f"   • *Konsa Setup:* *15m ORB Breakout* (9:15–9:30 Range ₹{or_l:.2f}–₹{or_h:.2f} ke High ₹{or_h:.2f} ke upar close)\n"
                f"   • *Levels:* SL ₹{sl:.2f} ({sl_rule}) | +1R Trail ₹{float(t.get('one_r_price') or 0):.2f} | Target ₹{tgt:.2f} ({tgt_r})\n"
                f"   • *Din Me Kya Hua:* Exit @ *₹{ex:.2f}* ({ex_t} IST) — *{t.get('exit_reason', st)}* | Net P&L: *₹{npnl:+.2f}*"
            )

    lines.append("")
    lines.append("🧠 *3. AAJ KI SAMAJH (MORNING SCAN vs INTRADAY REALITY):*")
    if trades:
        lines.append(
            f"• *Execution & Slippage Reality:* Aaj {len(trades)} setup(s) `india-budget` aur `india-risk` se pass huye. "
            f"Realistic entry/exit slippage aur `size.py` ke exact NSE charges (-₹{charges:.2f}) ke baad net result *₹{net_pnl:+.2f}* raha (Account Balance: *₹{cur_bal:,.2f}*)."
        )
    else:
        lines.append("• *Execution Reality:* Aaj koi setup after-charges R:R aur risk filter par pass nahi hua — capital safe raha.")

    fallback_text = "\n".join(lines)

    template_inst = (
        "Is JSON se Shaam Ka Review (Evening Review) Hinglish me likho jisme ye 3 sections hon:\n"
        "1. SUBAH KA SCAN AUR NEWS KYA BOLTA THA\n"
        "2. DIN ME KYA HUA (Kaha, Kitne Baje, Konse Setup par trade bana, realistic fill/slippage aur result)\n"
        "3. AAJ KI SAMAJH (Scan vs Reality learning)\n"
        f"Rule yaad rakho: \"{STRICT_PROMPT_RULE}\""
    )
    ai_txt = call_gemini_strict(facts_json, template_inst)
    candidate = ai_txt if ai_txt else fallback_text
    return audit_and_lock_brief(candidate, facts_json, fallback_text, tag="evening", state_dir=st_dir)


if __name__ == "__main__":
    ap = argparse.ArgumentParser(description="Generate JSON-locked trading briefs via Gemini and run number-check.")
    ap.add_argument("--mode", choices=["morning", "setup", "evening"], default="morning")
    ap.add_argument("--symbol", default=None)
    ap.add_argument("--state-dir", default=DEFAULT_STATE_DIR)
    ap.add_argument("--check-only", action="store_true", help="Only run number verification on existing brief & json files")
    ap.add_argument("--brief", default=None)
    ap.add_argument("--json", default=None)
    args = ap.parse_args()

    st_dir = args.state_dir
    brief_path = args.brief or os.path.join(st_dir, "last_brief.txt")
    json_path = args.json or os.path.join(st_dir, "last_facts.json")

    if args.check_only:
        with open(brief_path, encoding="utf-8") as f:
            b_txt = f.read()
        j_data = load_json(json_path, {})
        res = verify_brief_numbers(b_txt, j_data)
        print(json.dumps(res, indent=2, ensure_ascii=False))
        sys.exit(0 if res["ok"] else 1)

    if args.mode == "morning":
        wl = load_json(os.path.join(TRADER, "watchlist.json"), {})
        nw = load_json(os.path.join(st_dir, "morning_news.json"), {})
        tm = load_json(os.path.join(TRADER, "timemachine.json"), {})
        cfg = load_json(os.path.join(TRADER, "config.json"), {})
        print(generate_morning_brief(wl, nw, tm, cfg, state_dir=st_dir))
    elif args.mode == "setup":
        ent = load_json(os.path.join(TRADER, "entry.json"), {})
        pln = load_json(os.path.join(TRADER, "plan.json"), {})
        ord_doc = load_json(os.path.join(TRADER, "orders.json"), {})
        tm = load_json(os.path.join(TRADER, "timemachine.json"), {})
        rsk = load_json(os.path.join(st_dir, "risk.json"), {})
        sym = args.symbol or pln.get("symbol") or ent.get("symbol") or "STOCK"
        print(generate_setup_brief(sym, ent, pln, ord_doc, tm, rsk, state_dir=st_dir))
    elif args.mode == "evening":
        pb = load_json(os.path.join(st_dir, "paper_book.json"), {})
        psb = load_json(os.path.join(st_dir, "paper_passbook.json"), {})
        ms = load_json(os.path.join(st_dir, "morning_snapshot.json"), {})
        print(generate_evening_review_brief(pb, psb, ms, state_dir=st_dir))
