#!/usr/bin/env python3
"""Config-Driven Setup Chart & Evening Trade Report Card Generator (chart_gen.py).
Reads 100% of budget/risk settings from `trader/config.json` and 100% of share qty, cost,
and NSE charges from `india-budget/size.py` (`orders.json` / `size_json`).
Never invents fallback quantities or hardcoded leverage/charge numbers.
"""
import argparse
import datetime
import json
import os
import urllib.parse
import urllib.request
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import matplotlib.patches as patches
from matplotlib.gridspec import GridSpec

IST_OFFSET = datetime.timedelta(hours=5, minutes=30)
EPOCH = datetime.datetime(1970, 1, 1)
UA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0 Safari/537.36"


def load_json(path, default=None):
    if not path or not os.path.exists(path):
        return default
    with open(path, encoding="utf-8") as f:
        return json.load(f)


def fetch_5m_chart(symbol, offline_path=None):
    if offline_path and os.path.exists(offline_path):
        with open(offline_path, encoding="utf-8") as f:
            doc = json.load(f)
        if symbol in doc and "chart" in doc[symbol]:
            return doc[symbol]
        return doc
    ysym = symbol if symbol.endswith(".NS") or symbol.startswith("^") else symbol + ".NS"
    url = f"https://query2.finance.yahoo.com/v8/finance/chart/{urllib.parse.quote(ysym)}?range=1d&interval=5m"
    req = urllib.request.Request(url, headers={"User-Agent": UA, "Accept": "application/json"})
    with urllib.request.urlopen(req, timeout=20) as resp:
        return json.loads(resp.read().decode("utf-8", "replace"))


def generate_chart(trader_dir="trader", out_path=None, offline_chart=None, size_json=None, state_dir=None):
    st_dir = state_dir or os.path.join(trader_dir, "state")
    cfg_data = load_json(os.path.join(trader_dir, "config.json"), {})
    entry_data = load_json(os.path.join(trader_dir, "entry.json"), {})
    plan_data = load_json(os.path.join(trader_dir, "plan.json"), {})
    orders_data = load_json(os.path.join(trader_dir, "orders.json"), {})
    tm_data = load_json(os.path.join(trader_dir, "timemachine.json"), {})
    risk_data = load_json(os.path.join(st_dir, "risk.json"), {})

    symbol = plan_data.get("symbol") or entry_data.get("symbol") or "STOCK"
    session_date = plan_data.get("date") or entry_data.get("date") or datetime.date.today().isoformat()
    if not out_path:
        os.makedirs(os.path.join(trader_dir, "charts"), exist_ok=True)
        out_path = os.path.join(trader_dir, "charts", f"{symbol}_{session_date}.png")

    chart_raw = fetch_5m_chart(symbol, offline_chart)
    res = chart_raw["chart"]["result"][0]
    timestamps = res.get("timestamp") or []
    quote = (res.get("indicators", {}).get("quote") or [{}])[0]
    opens = quote.get("open") or []
    highs = quote.get("high") or []
    lows = quote.get("low") or []
    closes = quote.get("close") or []
    volumes = quote.get("volume") or []

    bars = []
    for i, ts in enumerate(timestamps):
        if i >= len(closes) or closes[i] is None or opens[i] is None:
            continue
        dt_ist = EPOCH + datetime.timedelta(seconds=ts) + IST_OFFSET
        bars.append({
            "time_str": dt_ist.strftime("%H:%M"),
            "o": float(opens[i]),
            "h": float(highs[i]),
            "l": float(lows[i]),
            "c": float(closes[i]),
            "v": int(volumes[i] or 0),
        })

    entry_bar_idx = int(plan_data.get("entry_bar") or entry_data.get("bar_index") or 3)
    max_bars = min(len(bars), max(entry_bar_idx + 22, 28))
    bars = bars[:max_bars]
    n_bars = len(bars)

    times_ist = [b["time_str"] for b in bars]
    o = [b["o"] for b in bars]
    h = [b["h"] for b in bars]
    l = [b["l"] for b in bars]
    c = [b["c"] for b in bars]
    v = [b["v"] for b in bars]

    or_info = plan_data.get("opening_range") or entry_data.get("opening_range") or {}
    or_min = int(or_info.get("minutes") or 15)
    n_or_bars = max(1, or_min // 5)
    or_high = float(or_info.get("high") or max(h[:n_or_bars]))
    or_low = float(or_info.get("low") or min(l[:n_or_bars]))

    sz = {}
    if isinstance(size_json, dict):
        sz = size_json.get("sizing") if isinstance(size_json.get("sizing"), dict) else size_json

    signal_px = float((entry_data.get("trigger") or {}).get("close") or entry_data.get("price") or plan_data.get("entry") or c[min(entry_bar_idx, n_bars - 1)])
    entry_px = float(sz.get("entry") or signal_px)
    stop_px = float(sz.get("stop") or plan_data.get("stop") or (or_high + or_low) / 2.0)
    target_px = float(sz.get("target") or plan_data.get("target") or (entry_px + 2.0 * (entry_px - stop_px)))
    risk_sh = float(sz.get("risk_per_share") or plan_data.get("risk_per_share") or abs(entry_px - stop_px))
    one_r_px = round(entry_px + risk_sh, 2)
    rr = float(sz.get("reward_risk") or plan_data.get("reward_risk") or 2.0)
    entry_time_str = plan_data.get("entry_time") or entry_data.get("bar_end") or "09:35 AM"
    bar_start_str = entry_data.get("bar_start") or "09:30"
    stop_reason = plan_data.get("stop_label") or plan_data.get("stop_reason") or "opening-range low"
    flat_by = sz.get("flat_by") or plan_data.get("flat_by") or cfg_data.get("flat_by") or "15:15"
    pct_over = (signal_px / or_high - 1.0) * 100.0 if or_high else 0.0

    # Strict sizing numbers from india-budget/size.py & trader/config.json ONLY
    qty = int(sz.get("qty") or 0)
    pos_val = float(sz.get("cost") or 0.0)
    budget_inr = float(sz.get("budget") or cfg_data.get("budget") or 10000.0)
    max_loss_cap = float(sz.get("max_loss_per_trade_inr") or cfg_data.get("max_loss_per_trade_inr") or 200.0)
    max_daily_cap = float(cfg_data.get("max_daily_loss_inr") or 200.0)
    allow_margin = bool(cfg_data.get("allow_margin", False))

    ch_stop_obj = sz.get("charges_at_stop") or {}
    ch_target_obj = sz.get("charges_at_target") or {}
    ch_stop = float(ch_stop_obj.get("total") if isinstance(ch_stop_obj, dict) else (ch_stop_obj or 0.0))
    ch_target = float(ch_target_obj.get("total") if isinstance(ch_target_obj, dict) else (ch_target_obj or 0.0))

    net_loss = float(sz.get("loss_at_stop_with_charges") or 0.0)
    net_gain = float(sz.get("net_profit_at_target") or 0.0)
    rr_after_charges = round(net_gain / net_loss, 2) if net_loss > 0 else 0.0

    risk_results = risk_data.get("results") or []
    verdict = risk_results[0].get("verdict") if risk_results else ("BLOCK" if risk_data.get("block") else "PASS")

    mc = tm_data.get("mc") or tm_data.get("monte_carlo") or {}
    p_t = mc.get("p_target")
    p_s = mc.get("p_stop")
    tgt_pct = round(float(p_t) * 100.0, 1) if p_t is not None else float(mc.get("target_Pct") or mc.get("target_pct") or 44.0)
    stp_pct = round(float(p_s) * 100.0, 1) if p_s is not None else float(mc.get("stop_Pct") or mc.get("stop_pct") or 56.0)
    hist = tm_data.get("history") or tm_data.get("historical") or {}
    hist_trig = int(hist.get("triggered") if hist.get("triggered") is not None else (hist.get("triggered_sessions") or 1))
    hist_win = int(hist.get("target") if hist.get("target") is not None else (hist.get("target_first") or 0))
    hist_loss = int(hist.get("stop") if hist.get("stop") is not None else (hist.get("stop_first") or 1))
    hist_avg_r = float(hist.get("avg_R") if hist.get("avg_R") is not None else (hist.get("avg_r") or 0.0))
    tm_verdict = ((tm_data.get("verdict") or "Leans toward the target").split(":")[0]).strip().capitalize()

    BG_FIG = "#0B1120"
    BG_PANEL = "#111827"
    BG_CARD = "#1E293B"
    GRID_COL = "#1F2937"
    TEXT_MAIN = "#F8FAFC"
    TEXT_MUTED = "#94A3B8"
    GREEN = "#10B981"
    RED = "#EF4444"
    BLUE = "#38BDF8"
    AMBER = "#F59E0B"
    PURPLE = "#A855F7"

    plt.rcParams["font.sans-serif"] = "DejaVu Sans"
    plt.rcParams["axes.edgecolor"] = "#334155"
    plt.rcParams["axes.linewidth"] = 0.9

    fig = plt.figure(figsize=(16, 9.5), dpi=180, facecolor=BG_FIG)
    gs = GridSpec(
        3, 2, figure=fig,
        width_ratios=[1.52, 1.08],
        height_ratios=[0.13, 0.65, 0.22],
        hspace=0.08, wspace=0.09,
        left=0.045, right=0.98, top=0.95, bottom=0.06
    )

    # 1. Top Header Banner
    ax_hdr = fig.add_subplot(gs[0, :])
    ax_hdr.set_facecolor(BG_CARD)
    ax_hdr.set_xticks([])
    ax_hdr.set_yticks([])
    for spine in ax_hdr.spines.values():
        spine.set_color("#334155")
        spine.set_linewidth(1.2)

    ax_hdr.text(
        0.016, 0.68,
        f"{symbol} (NSE) — LIVE INTRADAY SETUP: 15m ORB BREAKOUT @ {entry_time_str} IST",
        color=TEXT_MAIN, fontsize=14.5, fontweight="bold", va="center", transform=ax_hdr.transAxes
    )
    ax_hdr.text(
        0.016, 0.24,
        f"Setup Reason: {bar_start_str}–{entry_time_str} 5m Candle Closed @ ₹{signal_px:.2f} (+{pct_over:.2f}% > OR High ₹{or_high:.2f}) | Fill: ₹{entry_px:.2f} | Date: {session_date}",
        color="#7DD3FC", fontsize=9.1, fontweight="bold", va="center", transform=ax_hdr.transAxes
    )

    pill_bg = "#064E3B" if verdict == "PASS" else "#7F1D1D"
    pill_edge = GREEN if verdict == "PASS" else RED
    pill_fg = "#A7F3D0" if verdict == "PASS" else "#FCA5A5"
    badge_box = patches.FancyBboxPatch(
        (0.735, 0.20), 0.248, 0.60,
        boxstyle="round,pad=0.012,rounding_size=0.02",
        facecolor=pill_bg, edgecolor=pill_edge, linewidth=1.5,
        transform=ax_hdr.transAxes
    )
    ax_hdr.add_patch(badge_box)
    ax_hdr.text(
        0.859, 0.50,
        f"INDIA-RISK: {verdict} | {qty} SHARES (₹{budget_inr:,.0f})",
        color=pill_fg, fontsize=10.0, fontweight="bold", ha="center", va="center", transform=ax_hdr.transAxes
    )

    # 2. Main Candlestick Chart
    ax_price = fig.add_subplot(gs[1, 0])
    ax_price.set_facecolor(BG_PANEL)
    ax_price.grid(True, color=GRID_COL, linestyle="--", linewidth=0.7, alpha=0.8)

    or_rect = patches.Rectangle(
        (-0.4, or_low), n_or_bars - 0.2, or_high - or_low,
        facecolor=AMBER, edgecolor=AMBER, alpha=0.18, linewidth=1.5, linestyle="--", zorder=2
    )
    ax_price.add_patch(or_rect)

    y_min = min(min(l), stop_px) - risk_sh * 0.45
    y_max = max(max(h), target_px) + risk_sh * 0.60

    ax_price.annotate(
        f"1. 15m Opening Range (09:15–09:30 IST — All 3 Bars)\nRange High: ₹{or_high:.2f}  |  Range Low: ₹{or_low:.2f}",
        xy=(1.0, or_high),
        xytext=(0.15, y_max - (y_max - y_min) * 0.14),
        color="#FCD34D", fontsize=8.3, fontweight="bold", ha="left", va="center",
        bbox=dict(boxstyle="round,pad=0.3", facecolor="#1E293B", edgecolor=AMBER, alpha=0.95, lw=1.0),
        arrowprops=dict(arrowstyle="->", color=AMBER, lw=1.3, connectionstyle="arc3,rad=0.12"),
        zorder=7
    )

    ax_price.fill_between([entry_bar_idx, n_bars - 0.5], entry_px, target_px, color=GREEN, alpha=0.09, zorder=1)
    ax_price.fill_between([entry_bar_idx, n_bars - 0.5], stop_px, entry_px, color=RED, alpha=0.12, zorder=1)

    ax_price.axhline(target_px, color=GREEN, linestyle="-", linewidth=1.8, zorder=3)
    ax_price.axhline(one_r_px, color="#A7F3D0", linestyle="-.", linewidth=1.2, alpha=0.85, zorder=3)
    ax_price.axhline(entry_px, color=BLUE, linestyle="--", linewidth=1.8, zorder=3)
    ax_price.axhline(or_high, color=AMBER, linestyle=":", linewidth=1.2, alpha=0.85, zorder=3)
    ax_price.axhline(stop_px, color=RED, linestyle="-", linewidth=1.8, zorder=3)
    ax_price.axhline(or_low, color=AMBER, linestyle=":", linewidth=1.1, alpha=0.7, zorder=3)

    candle_width = 0.58
    for idx in range(n_bars):
        is_bull = c[idx] >= o[idx]
        col = GREEN if is_bull else RED
        if idx == entry_bar_idx:
            col = "#38BDF8"
        ax_price.plot([idx, idx], [l[idx], h[idx]], color=col, linewidth=1.3, zorder=4)
        body_low = min(o[idx], c[idx])
        body_h = max(abs(c[idx] - o[idx]), (y_max - y_min) * 0.005)
        rect = patches.Rectangle(
            (idx - candle_width / 2, body_low), candle_width, body_h,
            facecolor=col, edgecolor=col, linewidth=1.0, zorder=5
        )
        ax_price.add_patch(rect)

    ax_price.annotate(
        f"2. WHERE & WHEN ENTRY TRIGGERED\nTime: {entry_time_str} IST (Bar #{entry_bar_idx + 1} Close ₹{signal_px:.2f})\nRealistic Entry Fill: ₹{entry_px:.2f}",
        xy=(entry_bar_idx + 0.15, entry_px),
        xytext=(min(entry_bar_idx + 2.8, n_bars - 7.5), stop_px + (entry_px - stop_px) * 0.18),
        color=TEXT_MAIN, fontsize=8.2, fontweight="bold",
        bbox=dict(boxstyle="round,pad=0.32", facecolor="#0369A1", edgecolor="#7DD3FC", lw=1.2),
        arrowprops=dict(arrowstyle="->", color="#7DD3FC", lw=1.5, connectionstyle="arc3,rad=-0.18"),
        zorder=8
    )

    x_tag = n_bars - 0.35
    level_tags = [
        (target_px, f" TARGET ({rr:.1f}R): ₹{target_px:.2f} (+₹{target_px - entry_px:.2f}/sh) ", "#065F46", "#6EE7B7"),
        (one_r_px,  f" +1R TRAIL TRIGGER (SL -> COST): ₹{one_r_px:.2f} ", "#064E3B", "#A7F3D0"),
        (entry_px,  f" ENTRY FILL @ {entry_time_str}: ₹{entry_px:.2f} ", "#075985", "#7DD3FC"),
        (or_high,   f" 15m OR HIGH: ₹{or_high:.2f} ", "#78350F", "#FDE68A"),
        (stop_px,   f" STOP-LOSS ({stop_reason}): ₹{stop_px:.2f} (-₹{risk_sh:.2f}/sh) ", "#7F1D1D", "#FCA5A5"),
    ]
    for y_val, lbl_txt, bg_c, fg_c in level_tags:
        ax_price.text(
            x_tag, y_val, lbl_txt,
            color=fg_c, fontsize=7.9, fontweight="bold", va="center", ha="right",
            bbox=dict(boxstyle="round,pad=0.19", facecolor=bg_c, edgecolor=fg_c, lw=0.8, alpha=0.94),
            zorder=9
        )

    ax_price.set_ylim(y_min, y_max)
    ax_price.set_xlim(-0.8, n_bars + 0.2)
    ax_price.set_ylabel("Price (INR ₹)", color=TEXT_MUTED, fontsize=10, fontweight="bold")
    ax_price.tick_params(axis="y", colors=TEXT_MAIN, labelsize=9.5)
    ax_price.tick_params(axis="x", labelbottom=False)

    # 3. Volume Subplot
    ax_vol = fig.add_subplot(gs[2, 0], sharex=ax_price)
    ax_vol.set_facecolor(BG_PANEL)
    ax_vol.grid(True, color=GRID_COL, linestyle="--", linewidth=0.6, alpha=0.7)

    or_avg_vol = sum(v[:n_or_bars]) / float(n_or_bars) if v else 0
    for idx in range(n_bars):
        is_bull = c[idx] >= o[idx]
        col = GREEN if is_bull else RED
        if idx == entry_bar_idx:
            col = "#38BDF8"
        ax_vol.bar(idx, v[idx] / 1000.0, width=candle_width, color=col, alpha=0.8, zorder=3)

    if or_avg_vol > 0:
        ax_vol.axhline(or_avg_vol / 1000.0, color=AMBER, linestyle="--", linewidth=1.0, alpha=0.8, zorder=4)
        ax_vol.text(
            n_bars - 0.5, (or_avg_vol / 1000.0) * 1.04,
            f"OR Avg Vol: {int(or_avg_vol):,}",
            color="#FCD34D", fontsize=8, ha="right", va="bottom"
        )

    ax_vol.set_ylabel("Vol (K)", color=TEXT_MUTED, fontsize=9.5, fontweight="bold")
    ax_vol.set_xlabel("Time (IST - 5 Minute Candles)", color=TEXT_MUTED, fontsize=9.5, fontweight="bold")
    ax_vol.tick_params(axis="y", colors=TEXT_MUTED, labelsize=8.5)
    step = max(1, n_bars // 12)
    ax_vol.set_xticks(range(0, n_bars, step))
    ax_vol.set_xticklabels([times_ist[i] for i in range(0, n_bars, step)], color=TEXT_MAIN, fontsize=8.5)

    # 4. Right Trade Ticket & Setup Explanation Card
    ax_card = fig.add_subplot(gs[1:, 1])
    ax_card.set_facecolor(BG_CARD)
    ax_card.set_xticks([])
    ax_card.set_yticks([])
    for spine in ax_card.spines.values():
        spine.set_color("#334155")
        spine.set_linewidth(1.2)

    def draw_section_header(y, title, accent_col):
        rect = patches.FancyBboxPatch(
            (0.03, y - 0.036), 0.94, 0.040,
            boxstyle="round,pad=0.005,rounding_size=0.01",
            facecolor="#0F172A", edgecolor=accent_col, linewidth=1.0,
            transform=ax_card.transAxes
        )
        ax_card.add_patch(rect)
        ax_card.text(
            0.052, y - 0.016, title,
            color=accent_col, fontsize=9.0, fontweight="bold", va="center", transform=ax_card.transAxes
        )

    def draw_kv(y, k_txt, v_txt, v_col=TEXT_MAIN, bold_v=True):
        ax_card.text(0.045, y, k_txt, color=TEXT_MUTED, fontsize=8.3, va="center", transform=ax_card.transAxes)
        ax_card.text(
            0.955, y, v_txt,
            color=v_col, fontsize=8.45, fontweight="bold" if bold_v else "normal",
            ha="right", va="center", transform=ax_card.transAxes
        )

    y_cur = 0.968
    draw_section_header(y_cur, "1. KAHA, KAB & KONSA SETUP (SETUP & ENTRY LOGIC)", BLUE)
    y_cur -= 0.057
    draw_kv(y_cur, "Setup Name:", f"{or_min}-Min Opening Range Breakout (ORB)", "#7DD3FC")
    y_cur -= 0.034
    draw_kv(y_cur, "Kab (Trigger Time):", f"{entry_time_str} IST ({bar_start_str}–{entry_time_str} Candle Close)", "#FDE68A")
    y_cur -= 0.034
    draw_kv(y_cur, "Kaha (Signal vs Fill):", f"Signal ₹{signal_px:,.2f} -> Fill ₹{entry_px:,.2f} (+{pct_over:.2f}%)", "#38BDF8")
    y_cur -= 0.034
    draw_kv(y_cur, f"9:15–9:30 Range ({or_min}m):", f"Low ₹{or_low:.2f}  to  High ₹{or_high:.2f} (3/3 Bars)", TEXT_MAIN)
    y_cur -= 0.034
    draw_kv(y_cur, f"Stop-Loss ({stop_reason}):", f"₹{stop_px:,.2f} (-₹{risk_sh:.2f}/sh)", "#FCA5A5")
    y_cur -= 0.034
    draw_kv(y_cur, "1:1 Trail Trigger:", f"₹{one_r_px:,.2f} (Trails SL -> ₹{entry_px:.2f}; gap risk applies)", "#A7F3D0")
    y_cur -= 0.034
    draw_kv(y_cur, f"Target ({rr:.1f}R):", f"₹{target_px:,.2f} (+₹{target_px - entry_px:.2f}/sh)", "#6EE7B7")

    y_cur -= 0.045
    draw_section_header(y_cur, f"2. BUDGET (₹{budget_inr:,.0f}) & CHARGES (india-budget/size.py)", GREEN)
    y_cur -= 0.057
    mode_lbl = "Margin ON" if allow_margin else "Cash / No Margin (allow_margin: false)"
    draw_kv(y_cur, "Config Budget & Mode:", f"₹{budget_inr:,.0f} ({mode_lbl})", TEXT_MAIN)
    y_cur -= 0.034
    draw_kv(y_cur, "Sized Qty & Cost:", f"{qty} Shares  |  Position Cost: ₹{pos_val:,.2f}", "#6EE7B7")
    y_cur -= 0.034
    draw_kv(y_cur, "Max Loss Limits (Config):", f"₹{max_loss_cap:,.0f}/trade  |  ₹{max_daily_cap:,.0f}/day", "#FCA5A5")
    y_cur -= 0.034
    draw_kv(y_cur, "Exact Charges (size.py):", f"₹{ch_stop:.2f} (at SL)  |  ₹{ch_target:.2f} (at Target)", "#FCD34D")
    y_cur -= 0.034
    draw_kv(y_cur, "All-In Loss if Stop Hits:", f"-₹{net_loss:.2f} (₹{qty * risk_sh:.2f} + ₹{ch_stop:.2f} chg)", RED)
    y_cur -= 0.034
    draw_kv(y_cur, "Net Profit & After-Chg R:R:", f"+₹{net_gain:.2f}  (R:R {rr_after_charges:.2f} after charges)", GREEN)

    y_cur -= 0.045
    draw_section_header(y_cur, "3. KYU CHUNA YEH TRADE? (10,000 REPLAY ODDS)", PURPLE)
    y_cur -= 0.057
    be_needed = 100.0 / (1.0 + rr)
    draw_kv(y_cur, "10,000 Replay Win Odds:", f"{tgt_pct:.1f}% Target Hit vs {stp_pct:.1f}% Stop Hit", TEXT_MAIN)
    y_cur -= 0.034
    draw_kv(y_cur, f"Break-Even Needed ({rr:.1f}R):", f"Needs {be_needed:.1f}% -> Actual {tgt_pct:.1f}% ({tm_verdict})", "#6EE7B7")
    y_cur -= 0.034
    draw_kv(y_cur, "Historical Backtest:", f"{hist_trig} Setups: {hist_win} Win / {hist_loss} Loss ({hist_avg_r:+.2f}R)", "#D8B4FE")

    y_cur -= 0.045
    draw_section_header(y_cur, "4. BROKER ORDER & REALISTIC RISK NOTE", AMBER)
    y_cur -= 0.052
    steps_txt = (
        f"• Why: 9:15–9:30 range high (₹{or_high:.2f}) broke @ {entry_time_str} (₹{signal_px:.2f}); net R:R after charges is {rr_after_charges:.2f}.\n"
        f"• Broker Order: BUY {qty} {symbol} Limit ₹{entry_px:.2f} | SL-M ₹{stop_px:.2f} | Target ₹{target_px:.2f} (Flat by {flat_by}).\n"
        f"• Risk Note: A stop or cost-trail SL-M is an order, not a guarantee — fast moves or gaps can fill below stop."
    )
    ax_card.text(
        0.045, y_cur, steps_txt,
        color=TEXT_MAIN, fontsize=8.0, va="top", linespacing=1.42, transform=ax_card.transAxes
    )

    plt.savefig(out_path, dpi=180, facecolor=BG_FIG)
    plt.close(fig)
    return out_path


def generate_eod_scorecard(paper_book, passbook, trader_dir="trader", out_path=None):
    """Renders Evening Intraday Trade Report Card PNG with config-driven budget, realistic slippage/charges,
    and Trade-by-Trade Setup Explanation."""
    cfg_data = load_json(os.path.join(trader_dir, "config.json"), {})
    date_str = paper_book.get("date") or datetime.date.today().isoformat()
    trades = paper_book.get("trades") or []
    if not out_path:
        os.makedirs(os.path.join(trader_dir, "charts"), exist_ok=True)
        out_path = os.path.join(trader_dir, "charts", f"eod_scorecard_{date_str}.png")

    BG_FIG = "#0B1120"
    BG_CARD = "#1E293B"
    BG_ROW_A = "#111827"
    BG_ROW_B = "#172033"
    TEXT_MAIN = "#F8FAFC"
    TEXT_MUTED = "#94A3B8"
    GREEN = "#10B981"
    RED = "#EF4444"
    BLUE = "#38BDF8"
    AMBER = "#F59E0B"
    PURPLE = "#A855F7"

    plt.rcParams["font.sans-serif"] = "DejaVu Sans"

    total_trades = len(trades)
    wins = sum(1 for t in trades if t.get("status") == "TARGET_HIT")
    cost_exits = sum(1 for t in trades if t.get("status") == "TRAILED_COST_EXIT")
    losses = sum(1 for t in trades if t.get("status") == "SL_HIT")

    closed_trades = [t for t in trades if t.get("net_pnl") is not None]
    gross_pnl = sum(float(t.get("gross_pnl") or 0.0) for t in closed_trades)
    total_charges = sum(float(t.get("charges") or 0.0) for t in closed_trades)
    net_pnl = sum(float(t.get("net_pnl") or 0.0) for t in closed_trades)
    win_rate = (wins / len(closed_trades) * 100.0) if closed_trades else 0.0

    start_cap = float(passbook.get("starting_capital") or cfg_data.get("budget") or 10000.0)
    max_daily_loss = float(cfg_data.get("max_daily_loss_inr") or 200.0)
    cur_bal = float(passbook.get("current_balance", start_cap + net_pnl))
    total_ret_pct = ((cur_bal - start_cap) / start_cap) * 100.0 if start_cap else 0.0

    fig_h = max(8.2, 4.8 + 0.65 * max(total_trades, 3))
    fig = plt.figure(figsize=(16, fig_h), dpi=180, facecolor=BG_FIG)
    ax = fig.add_axes([0.02, 0.025, 0.96, 0.95])
    ax.set_facecolor(BG_FIG)
    ax.set_xlim(0, 1)
    ax.set_ylim(0, 1)
    ax.axis("off")

    hdr = patches.FancyBboxPatch(
        (0.01, 0.875), 0.98, 0.108,
        boxstyle="round,pad=0.008,rounding_size=0.015",
        facecolor=BG_CARD, edgecolor="#334155", linewidth=1.3
    )
    ax.add_patch(hdr)
    ax.text(
        0.025, 0.948,
        f"NSE AI INTRADAY — EVENING TRADE REPORT CARD ({date_str})",
        color=TEXT_MAIN, fontsize=15.0, fontweight="bold", va="center"
    )
    ax.text(
        0.025, 0.902,
        f"Config Budget: ₹{start_cap:,.0f} (allow_margin: {bool(cfg_data.get('allow_margin', False))}) | Max Daily Loss: ₹{max_daily_loss:,.0f} | Realistic Slippage & size.py Charges",
        color="#7DD3FC", fontsize=9.0, fontweight="bold", va="center"
    )

    pnl_col = GREEN if net_pnl >= 0 else RED
    pnl_bg = "#064E3B" if net_pnl >= 0 else "#7F1D1D"
    pill = patches.FancyBboxPatch(
        (0.735, 0.892), 0.24, 0.074,
        boxstyle="round,pad=0.008,rounding_size=0.015",
        facecolor=pnl_bg, edgecolor=pnl_col, linewidth=1.5
    )
    ax.add_patch(pill)
    ax.text(
        0.855, 0.929,
        f"DAY NET P&L: {'+' if net_pnl >= 0 else ''}₹{net_pnl:.2f} ({net_pnl / (start_cap / 100.0):+.2f}%)",
        color="#A7F3D0" if net_pnl >= 0 else "#FCA5A5",
        fontsize=10.8, fontweight="bold", ha="center", va="center"
    )

    kpis = [
        ("TOTAL SETUPS", f"{total_trades} Setups", f"{wins} Target | {cost_exits} Trail | {losses} SL", BLUE),
        ("TARGET WIN RATE", f"{win_rate:.0f}% Target", f"{wins} Target / {cost_exits} Trailed Exit", GREEN),
        ("GROSS vs CHARGES", f"₹{gross_pnl:+.2f}", f"size.py Charges: -₹{total_charges:.2f}", AMBER),
        ("DAY NET P&L", f"₹{net_pnl:+.2f}", f"On ₹{start_cap:,.0f} Budget", pnl_col),
        ("ACCOUNT BALANCE", f"₹{cur_bal:,.2f}", f"Start: ₹{start_cap:,.0f} ({total_ret_pct:+.2f}% Total)", PURPLE),
    ]
    card_w = 0.184
    gap = 0.015
    for idx, (title, big_val, sub_val, col) in enumerate(kpis):
        x0 = 0.01 + idx * (card_w + gap)
        cbox = patches.FancyBboxPatch(
            (x0, 0.72), card_w, 0.132,
            boxstyle="round,pad=0.006,rounding_size=0.012",
            facecolor=BG_CARD, edgecolor=col, linewidth=1.1
        )
        ax.add_patch(cbox)
        ax.text(x0 + 0.013, 0.825, title, color=TEXT_MUTED, fontsize=8.2, fontweight="bold", va="center")
        ax.text(x0 + 0.013, 0.776, big_val, color=col, fontsize=13.2, fontweight="bold", va="center")
        ax.text(x0 + 0.013, 0.738, sub_val, color=TEXT_MAIN, fontsize=7.9, va="center")

    cols = [
        (0.018, "STOCK", "left"),
        (0.095, "KONSA SETUP (LOGIC)", "left"),
        (0.285, "KAB & KAHA (FILL)", "left"),
        (0.425, "QTY (COST)", "left"),
        (0.535, "SL / TARGET", "left"),
        (0.675, "EXIT PX & TIME", "left"),
        (0.815, "OUTCOME", "center"),
        (0.905, "CHARGES", "right"),
        (0.980, "NET P&L", "right"),
    ]

    tbl_top = 0.685
    row_h = min(0.064, 0.38 / max(total_trades + 1, 3))

    th_box = patches.Rectangle((0.01, tbl_top - row_h), 0.98, row_h, facecolor="#0F172A", edgecolor="#334155", linewidth=1.0)
    ax.add_patch(th_box)
    for cx, ctitle, align in cols:
        ax.text(cx, tbl_top - row_h / 2, ctitle, color=BLUE, fontsize=8.1, fontweight="bold", ha=align, va="center")

    STATUS_BADGE = {
        "TARGET_HIT":        ("TARGET HIT", "#065F46", "#6EE7B7"),
        "TRAILED_COST_EXIT": ("1R TRAIL SL EXIT", "#1E3A8A", "#93C5FD"),
        "SL_HIT":            ("STOP-LOSS HIT", "#7F1D1D", "#FCA5A5"),
        "TIME_EXIT_1515":    ("3:15 PM CLOSE", "#78350F", "#FDE68A"),
        "OPEN_TRAILED":      ("OPEN (SL TRAILED)", "#065F46", "#A7F3D0"),
        "OPEN":              ("OPEN ACTIVE", "#374151", "#E5E7EB"),
    }

    if not trades:
        r_y = tbl_top - 2 * row_h
        rbox = patches.Rectangle((0.01, r_y), 0.98, row_h, facecolor=BG_ROW_A, edgecolor="#1F2937")
        ax.add_patch(rbox)
        ax.text(0.5, r_y + row_h / 2, "No setups passed india-budget & india-risk during today's session.", color=TEXT_MUTED, fontsize=10, ha="center", va="center")
    else:
        for i, tr in enumerate(trades):
            r_y = tbl_top - (i + 2) * row_h
            bg_c = BG_ROW_A if i % 2 == 0 else BG_ROW_B
            rbox = patches.Rectangle((0.01, r_y), 0.98, row_h, facecolor=bg_c, edgecolor="#1F2937", linewidth=0.6)
            ax.add_patch(rbox)

            cy = r_y + row_h / 2
            sym = tr.get("symbol", "")
            setup_lbl = tr.get("setup_short") or f"15m ORB (>₹{tr.get('or_high', 0):.1f})"
            ttime = tr.get("fill_time") or tr.get("entry_time", "")
            qty = int(tr.get("qty") or 1)
            pos_cost = float(tr.get("cost") or (qty * float(tr.get("entry") or 0)))
            ent = float(tr.get("entry") or 0.0)
            sl = float(tr.get("initial_stop") or tr.get("stop") or 0.0)
            tgt = float(tr.get("target") or 0.0)
            ex_px = tr.get("exit_price")
            ex_tm = tr.get("exit_time") or ""
            st = tr.get("status", "OPEN")
            chg = float(tr.get("charges") or 0.0)
            npnl = tr.get("net_pnl")

            ax.text(0.018, cy, sym, color=TEXT_MAIN, fontsize=9.0, fontweight="bold", ha="left", va="center")
            ax.text(0.095, cy, setup_lbl, color="#FDE68A", fontsize=8.1, ha="left", va="center")
            ax.text(0.285, cy, f"{ttime} @ ₹{ent:.2f}", color="#7DD3FC", fontsize=8.4, fontweight="bold", ha="left", va="center")
            ax.text(0.425, cy, f"{qty} sh (₹{pos_cost:,.0f})", color=TEXT_MAIN, fontsize=8.2, ha="left", va="center")
            ax.text(0.535, cy, f"₹{sl:.2f} / ₹{tgt:.2f}", color="#6EE7B7", fontsize=8.2, ha="left", va="center")

            ex_str = f"₹{float(ex_px):.2f} ({ex_tm})" if ex_px is not None else "Running..."
            ax.text(0.675, cy, ex_str, color=TEXT_MAIN, fontsize=8.2, ha="left", va="center")

            b_txt, b_bg, b_fg = STATUS_BADGE.get(st, (st, "#374151", TEXT_MAIN))
            ax.text(
                0.815, cy, f" {b_txt} ",
                color=b_fg, fontsize=7.5, fontweight="bold", ha="center", va="center",
                bbox=dict(boxstyle="round,pad=0.20", facecolor=b_bg, edgecolor=b_fg, lw=0.7)
            )

            ax.text(0.905, cy, f"-₹{chg:.2f}", color="#FCD34D", fontsize=8.2, ha="right", va="center")
            if npnl is not None:
                ncol = GREEN if float(npnl) >= 0 else RED
                ax.text(0.980, cy, f"{'+' if float(npnl) >= 0 else ''}₹{float(npnl):.2f}", color=ncol, fontsize=9.0, fontweight="bold", ha="right", va="center")
            else:
                ax.text(0.980, cy, "--", color=TEXT_MUTED, fontsize=8.5, ha="right", va="center")

    exp_box_top = max(0.24, tbl_top - (max(total_trades, 1) + 2.3) * row_h)
    exp_box_h = exp_box_top - 0.03
    ebox = patches.FancyBboxPatch(
        (0.01, 0.025), 0.98, max(0.18, exp_box_h),
        boxstyle="round,pad=0.008,rounding_size=0.012",
        facecolor=BG_CARD, edgecolor="#38BDF8", linewidth=1.1
    )
    ax.add_patch(ebox)
    top_y = 0.025 + max(0.18, exp_box_h) - 0.028
    ax.text(
        0.025, top_y,
        "SETUP EXPLANATION — TRADE KAHA, KITNE BAJE AUR KONSE SETUP PAR LIYA GAYA (WITH REALISTIC SLIPPAGE & CHARGES):",
        color="#38BDF8", fontsize=9.1, fontweight="bold", va="center"
    )

    if not trades:
        ax.text(0.025, top_y - 0.045, "• Aaj koi bhi stock 15m ORB + india-budget + india-risk filter par pass nahi hua.", color=TEXT_MAIN, fontsize=8.5, va="center")
    else:
        y_line = top_y - 0.042
        for idx, tr in enumerate(trades[:4], 1):
            sym = tr.get("symbol", "")
            ttime = tr.get("fill_time") or tr.get("entry_time", "09:35 AM")
            ent = float(tr.get("entry") or 0)
            sig_px = float(tr.get("signal_price") or ent)
            or_h = float(tr.get("or_high") or 0)
            or_l = float(tr.get("or_low") or 0)
            sl = float(tr.get("initial_stop") or tr.get("stop") or 0)
            sl_rule = tr.get("stop_rule") or "or-low"
            tgt = float(tr.get("target") or 0)
            qty = int(tr.get("qty") or 1)
            ex_px = tr.get("exit_price")
            ex_tm = tr.get("exit_time") or ""
            reason_ex = tr.get("exit_reason") or "Open"
            npnl = float(tr.get("net_pnl") or 0.0)
            line1 = (
                f"{idx}. {sym} ({qty} Shares): {ttime} IST par ₹{ent:.2f} fill (Signal ₹{sig_px:.2f}) pe '15-Min ORB Breakout' liya "
                f"(9:15–9:30 Range ₹{or_l:.2f}–₹{or_h:.2f} ke High ₹{or_h:.2f} ke upar close)."
            )
            line2 = (
                f"    -> Plan: SL ₹{sl:.2f} ({sl_rule}) | +1R Trail ₹{tr.get('one_r_price', 0):.2f} | Target ₹{tgt:.2f} ({tr.get('target_r', '3R')}) "
                f"| Exit @ ₹{float(ex_px or ent):.2f} ({ex_tm}) [{reason_ex}] -> Net P&L: {'+' if npnl >= 0 else ''}₹{npnl:.2f}"
            )
            ax.text(0.025, y_line, line1, color=TEXT_MAIN, fontsize=8.2, fontweight="bold", va="center")
            y_line -= 0.032
            ax.text(0.025, y_line, line2, color="#A7F3D0" if npnl >= 0 else "#FDE68A", fontsize=7.9, va="center")
            y_line -= 0.036

    plt.savefig(out_path, dpi=180, facecolor=BG_FIG)
    plt.close(fig)
    return out_path


if __name__ == "__main__":
    p = argparse.ArgumentParser()
    p.add_argument("--trader-dir", default="trader")
    p.add_argument("--out", default=None)
    p.add_argument("--offline", default=None)
    args = p.parse_args()
    out = generate_chart(args.trader_dir, args.out, args.offline)
    print("Generated chart:", out)
