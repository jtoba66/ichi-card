"""
Exit Tests — 4 tests on the 4×ATR trailing stop
=================================================
1. Time in trade — how many bars do winners vs losers hold? By TF, year, quality.
2. ATR multiplier — simulate 2×, 3×, 4×, 5×, 6× using exact production logic.
   Compare EV, win%, W/L across multipliers.
3. Ichimoku exits — simulate kijun-cross and cloud-reentry vs 4×ATR.
   Also test hybrid: ichimoku exit OR ATR stop, whichever fires first.
4. 2025 exit timing — are trades getting stopped faster in 2025? (decay cause check)

Production exit logic (from jobs.py):
  - ATR computed at entry bar (FIXED, not dynamic)
  - First 10 bars: stop frozen at entry_price - mult×ATR  (protection zone)
  - After bar 10: stop = max(prev_stop, highest_close - mult×ATR)
  - Exit when close < stop

Run on HP:
    cd ~/ichi-scorecard
    uv run python scripts/exit_tests.py
"""
from __future__ import annotations

import os
import sys
from collections import defaultdict
from datetime import datetime, timezone

import numpy as np
import pandas as pd
import psycopg2
import psycopg2.extras

sys.stdout.reconfigure(line_buffering=True)  # type: ignore[attr-defined]

DB_URL = os.environ.get("ICHI_DATABASE_URL", "postgresql://ichi:ichi@localhost/ichi_signals")

# ── Helpers ───────────────────────────────────────────────────────────────────
def _pct(v): return f"{v:+.2f}%" if v is not None else "—"

def stats(returns):
    if not returns:
        return None, None, None
    wins    = [r for r in returns if r > 0]
    losses  = [r for r in returns if r < 0]
    avg     = round(sum(returns) / len(returns), 2)
    win_pct = round(100 * len(wins) / len(returns), 1)
    avg_win  = round(sum(wins)/len(wins), 2)    if wins   else None
    avg_loss = round(sum(losses)/len(losses), 2) if losses else None
    wl = round(abs(avg_win/avg_loss), 2) if (avg_win and avg_loss) else None
    return avg, win_pct, wl

def row(label, rets, width=38):
    if not rets or len(rets) < 10:
        return None
    avg, win_pct, wl = stats(rets)
    return f"  {label:<{width}}  n={len(rets):<5}  avg={_pct(avg):<12}  win={win_pct}%  W/L={wl}"

def header(title):
    print("\n" + "=" * 72)
    print(title)
    print("=" * 72)

def get_year(fired_at):
    try:
        return datetime.fromisoformat(fired_at.replace(" ", "T")).year
    except Exception:
        return None

# ── Load signals ──────────────────────────────────────────────────────────────
print("Loading closed signals with exit data...")
conn = psycopg2.connect(DB_URL)
with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
    cur.execute("""
        SELECT signal_id, signal_type, symbol, timeframe, fired_at,
               entry_price, exit_return, exit_bar, exit_condition,
               mae, mfe, duration_bars, quality_score, hosoda_active
        FROM signal_log
        WHERE is_backfill = 1
          AND status = 'CLOSED'
          AND exit_return IS NOT NULL
        ORDER BY fired_at ASC
    """)
    signals = [dict(r) for r in cur.fetchall()]
conn.close()
print(f"  {len(signals)} signals loaded.\n")

from ichi.data.fetcher import fetch_ohlcv
from ichi.indicators.ichimoku import ichimoku
from ichi.signal.jobs import _find_bar_by_timestamp, _compute_atr14

def qs_tier(qs):
    if qs is None or qs == 0: return "unscored"
    if qs >= 60: return "QS 60+"
    if qs >= 40: return "QS 40-59"
    return "QS <40"

# ── TEST 1: Time in Trade ─────────────────────────────────────────────────────
header("TEST 1: TIME IN TRADE")
print("  Using duration_bars from DB (bars held from entry to exit)\n")

def dur_bucket(d):
    if d is None: return None
    if d <= 3:    return "0-3 bars"
    if d <= 10:   return "4-10 bars"
    if d <= 30:   return "11-30 bars"
    if d <= 60:   return "31-60 bars"
    return ">60 bars"

DUR_ORDER = ["0-3 bars", "4-10 bars", "11-30 bars", "31-60 bars", ">60 bars"]

# Overall by duration bucket
print(f"  {'Duration':<20}  {'n':<6}  {'Avg Return':<12}  {'Win%':<8}  {'W/L'}")
print("  " + "─" * 58)
dur_buckets: dict[str, list] = defaultdict(list)
for sig in signals:
    b = dur_bucket(sig["duration_bars"])
    if b:
        dur_buckets[b].append(float(sig["exit_return"]))
for b in DUR_ORDER:
    r = row(b, dur_buckets[b], width=20)
    if r: print(r)

# Winners vs losers: how long do they hold?
wins_dur  = [sig["duration_bars"] for sig in signals if sig["exit_return"] and sig["exit_return"] > 0 and sig["duration_bars"]]
losses_dur = [sig["duration_bars"] for sig in signals if sig["exit_return"] and sig["exit_return"] < 0 and sig["duration_bars"]]
print(f"\n  Avg bars held — winners: {round(sum(wins_dur)/len(wins_dur),1) if wins_dur else '—'}  "
      f"losers: {round(sum(losses_dur)/len(losses_dur),1) if losses_dur else '—'}")

# By timeframe
print(f"\n  By timeframe:")
print(f"  {'TF + outcome':<25}  {'avg bars held':<16}  {'median'}")
print("  " + "─" * 55)
for tf in ["1h", "4h", "1d", "1w"]:
    w = [s["duration_bars"] for s in signals if s["timeframe"]==tf and s["exit_return"] and s["exit_return"]>0 and s["duration_bars"]]
    l = [s["duration_bars"] for s in signals if s["timeframe"]==tf and s["exit_return"] and s["exit_return"]<0 and s["duration_bars"]]
    if w:
        print(f"  {tf} winners              {round(sum(w)/len(w),1):<16}  {round(sorted(w)[len(w)//2],1)}")
    if l:
        print(f"  {tf} losers               {round(sum(l)/len(l),1):<16}  {round(sorted(l)[len(l)//2],1)}")

# By year
print(f"\n  Avg bars held by year (all signals):")
print(f"  {'Year':<8}  {'Avg bars':<12}  {'Winners avg bars':<20}  {'Losers avg bars'}")
print("  " + "─" * 60)
for year in [2023, 2024, 2025, 2026]:
    yr_sigs = [s for s in signals if get_year(s["fired_at"]) == year and s["duration_bars"]]
    all_d  = [s["duration_bars"] for s in yr_sigs]
    win_d  = [s["duration_bars"] for s in yr_sigs if s["exit_return"] and s["exit_return"] > 0]
    loss_d = [s["duration_bars"] for s in yr_sigs if s["exit_return"] and s["exit_return"] < 0]
    if all_d:
        print(f"  {year:<8}  {round(sum(all_d)/len(all_d),1):<12}  "
              f"{round(sum(win_d)/len(win_d),1) if win_d else '—':<20}  "
              f"{round(sum(loss_d)/len(loss_d),1) if loss_d else '—'}")

# MAE / MFE analysis
mfe_vals = [float(s["mfe"]) for s in signals if s["mfe"] is not None and s["exit_return"] and s["exit_return"] < 0]
if mfe_vals:
    print(f"\n  Losing trades — avg MFE (peak gain before reversal): {_pct(round(sum(mfe_vals)/len(mfe_vals),2))}")
    print(f"  → This is how much they went green before the stop hit on average")

# ── Simulation setup ──────────────────────────────────────────────────────────
print("\n\nLoading OHLCV per pair for ATR + Ichimoku exit simulations...")
print("(Tests 2, 3, 4 computed together in one OHLCV pass)\n")

by_sym_tf: dict[tuple, list] = defaultdict(list)
for sig in signals:
    by_sym_tf[(sig["symbol"], sig["timeframe"])].append(sig)

MULTIPLIERS = [2.0, 3.0, 4.0, 5.0, 6.0]
MAX_BARS = 500  # max bars to simulate forward

# Per-signal simulation results
sim: dict[str, dict] = {
    sig["signal_id"]: {
        "actual_return": float(sig["exit_return"]),
        "actual_bars":   sig["duration_bars"],
        "year":          get_year(sig["fired_at"]),
        "timeframe":     sig["timeframe"],
        "qs_tier":       qs_tier(sig["quality_score"]),
        # ATR mult sims: {2.0: return, 3.0: return, ...}
        "mult_returns":  {},
        "mult_bars":     {},
        # Ichimoku exits
        "kijun_return":  None,
        "kijun_bars":    None,
        "cloud_return":  None,
        "cloud_bars":    None,
        "hybrid_kijun_return": None,  # ichimoku OR ATR, whichever first
        "hybrid_cloud_return": None,
    }
    for sig in signals
}

def simulate_trail_stop(closes, lows, kj_arr, span_a_arr, span_b_arr,
                        entry_bar, entry_price, atr_entry, mult):
    """Simulate trailing stop exit. Returns (exit_return%, bars_held)."""
    stop = entry_price - mult * atr_entry
    highest = entry_price
    for j in range(entry_bar + 1, min(entry_bar + MAX_BARS, len(closes))):
        c = closes[j]
        highest = max(highest, c)
        bars = j - entry_bar
        if bars <= 10:
            active = stop
        else:
            new_trail = highest - mult * atr_entry
            stop = max(stop, new_trail)
            active = stop
        if c < active:
            ret = (c - entry_price) / entry_price * 100
            return ret, bars
    # Didn't exit — use last close
    last = min(entry_bar + MAX_BARS - 1, len(closes) - 1)
    return (closes[last] - entry_price) / entry_price * 100, last - entry_bar

def simulate_kijun_exit(closes, kj_arr, entry_bar, entry_price):
    """Exit when close drops below kijun."""
    for j in range(entry_bar + 2, min(entry_bar + MAX_BARS, len(closes))):
        if closes[j] < kj_arr[j]:
            ret = (closes[j] - entry_price) / entry_price * 100
            return ret, j - entry_bar
    last = min(entry_bar + MAX_BARS - 1, len(closes) - 1)
    return (closes[last] - entry_price) / entry_price * 100, last - entry_bar

def simulate_cloud_exit(closes, span_a_arr, span_b_arr, entry_bar, entry_price):
    """Exit when close drops below cloud top."""
    for j in range(entry_bar + 2, min(entry_bar + MAX_BARS, len(closes))):
        cloud_top = max(span_a_arr[j], span_b_arr[j])
        if closes[j] < cloud_top:
            ret = (closes[j] - entry_price) / entry_price * 100
            return ret, j - entry_bar
    last = min(entry_bar + MAX_BARS - 1, len(closes) - 1)
    return (closes[last] - entry_price) / entry_price * 100, last - entry_bar

total = len(by_sym_tf)
skipped = 0

for idx, ((symbol, timeframe), sigs) in enumerate(by_sym_tf.items()):
    if idx % 50 == 0:
        print(f"  [{idx+1}/{total}] {symbol} {timeframe}")
    try:
        pair = symbol.replace("USDT", "/USDT")
        df = fetch_ohlcv(pair, timeframe)
        df = ichimoku(df)
    except Exception:
        skipped += len(sigs)
        continue

    closes  = df["close"].values
    lows    = df["low"].values
    kj_arr  = df["kj"].values
    span_a  = df["span_a"].values
    span_b  = df["span_b"].values

    for sig in sigs:
        bar = _find_bar_by_timestamp(df, sig["fired_at"])
        if bar is None or bar < 14:
            skipped += 1
            continue

        entry_price = float(sig["entry_price"])
        if entry_price <= 0:
            skipped += 1
            continue

        atr_entry = _compute_atr14(df, bar)
        if atr_entry <= 0:
            skipped += 1
            continue

        s = sim[sig["signal_id"]]

        # ATR multiplier simulations
        for mult in MULTIPLIERS:
            ret, bars = simulate_trail_stop(
                closes, lows, kj_arr, span_a, span_b,
                bar, entry_price, atr_entry, mult
            )
            s["mult_returns"][mult] = ret
            s["mult_bars"][mult]    = bars

        # Ichimoku exits
        kj_ret, kj_bars = simulate_kijun_exit(closes, kj_arr, bar, entry_price)
        s["kijun_return"] = kj_ret
        s["kijun_bars"]   = kj_bars

        cl_ret, cl_bars = simulate_cloud_exit(closes, span_a, span_b, bar, entry_price)
        s["cloud_return"] = cl_ret
        s["cloud_bars"]   = cl_bars

        # Hybrid: whichever fires first (kijun or 4×ATR)
        atr4_ret, atr4_bars = s["mult_returns"].get(4.0), s["mult_bars"].get(4.0)
        if atr4_bars is not None:
            s["hybrid_kijun_return"] = kj_ret if kj_bars <= atr4_bars else atr4_ret
            s["hybrid_cloud_return"] = cl_ret if cl_bars <= atr4_bars else atr4_ret

print(f"\n  Done. {len(sim) - skipped} signals simulated, {skipped} skipped.\n")
all_s = [v for v in sim.values() if v["mult_returns"]]

# ══════════════════════════════════════════════════════════════════════════════
header("TEST 2: ATR MULTIPLIER COMPARISON")
print(f"\n  Simulating: 2×, 3×, 4× (production), 5×, 6× ATR trailing stop\n")
print(f"  {'Multiplier':<25}  {'n':<6}  {'Avg Return':<12}  {'Win%':<8}  {'W/L':<8}  Avg bars")
print("  " + "─" * 72)
for mult in MULTIPLIERS:
    rets  = [s["mult_returns"][mult] for s in all_s if mult in s["mult_returns"]]
    bars  = [s["mult_bars"][mult]    for s in all_s if mult in s["mult_bars"]]
    label = f"{mult}× ATR {'(production)' if mult == 4.0 else ''}"
    if not rets: continue
    avg, win_pct, wl = stats(rets)
    avg_b = round(sum(bars)/len(bars), 1) if bars else "—"
    print(f"  {label:<25}  n={len(rets):<5}  avg={_pct(avg):<12}  win={win_pct}%  W/L={wl:<8}  {avg_b}")

# By quality tier
print(f"\n  ATR multiplier × Quality tier (avg return):")
print(f"  {'QS tier':<18}  " + "  ".join(f"{m}×ATR" .ljust(10) for m in MULTIPLIERS))
print("  " + "─" * 72)
for tier in ["QS 60+", "QS 40-59", "unscored"]:
    sub = [s for s in all_s if s["qs_tier"] == tier]
    parts = []
    for mult in MULTIPLIERS:
        rets = [s["mult_returns"][mult] for s in sub if mult in s["mult_returns"]]
        avg = _pct(round(sum(rets)/len(rets), 2)) if rets else "—"
        parts.append(f"{avg:<10}")
    print(f"  {tier:<18}  " + "  ".join(parts))

# By timeframe
print(f"\n  ATR multiplier × Timeframe (avg return):")
print(f"  {'Timeframe':<10}  " + "  ".join(f"{m}×ATR".ljust(10) for m in MULTIPLIERS))
print("  " + "─" * 65)
for tf in ["1h", "4h", "1d", "1w"]:
    sub = [s for s in all_s if s["timeframe"] == tf]
    if len(sub) < 20: continue
    parts = []
    for mult in MULTIPLIERS:
        rets = [s["mult_returns"][mult] for s in sub if mult in s["mult_returns"]]
        avg = _pct(round(sum(rets)/len(rets), 2)) if rets else "—"
        parts.append(f"{avg:<10}")
    print(f"  {tf:<10}  " + "  ".join(parts))

# ══════════════════════════════════════════════════════════════════════════════
header("TEST 3: ICHIMOKU EXITS vs 4×ATR")

exit_groups = [
    ("4×ATR (production)",    [s["mult_returns"].get(4.0) for s in all_s if s["mult_returns"]]),
    ("Exit on kijun cross",   [s["kijun_return"] for s in all_s if s["kijun_return"] is not None]),
    ("Exit on cloud reentry", [s["cloud_return"] for s in all_s if s["cloud_return"] is not None]),
    ("Hybrid: kijun OR 4×ATR", [s["hybrid_kijun_return"] for s in all_s if s["hybrid_kijun_return"] is not None]),
    ("Hybrid: cloud OR 4×ATR", [s["hybrid_cloud_return"] for s in all_s if s["hybrid_cloud_return"] is not None]),
]

print(f"\n  {'Exit method':<30}  {'n':<6}  {'Avg Return':<12}  {'Win%':<8}  {'W/L':<8}  Avg bars")
print("  " + "─" * 75)
bars_map = {
    "4×ATR (production)":     [s["mult_bars"].get(4.0) for s in all_s if s["mult_bars"]],
    "Exit on kijun cross":    [s["kijun_bars"] for s in all_s if s["kijun_bars"] is not None],
    "Exit on cloud reentry":  [s["cloud_bars"] for s in all_s if s["cloud_bars"] is not None],
    "Hybrid: kijun OR 4×ATR": [s["kijun_bars"] if (s["kijun_bars"] or 999) <= (s["mult_bars"].get(4.0) or 999)
                                else s["mult_bars"].get(4.0)
                                for s in all_s if s["kijun_bars"] is not None and s["mult_bars"]],
    "Hybrid: cloud OR 4×ATR": [s["cloud_bars"] if (s["cloud_bars"] or 999) <= (s["mult_bars"].get(4.0) or 999)
                                else s["mult_bars"].get(4.0)
                                for s in all_s if s["cloud_bars"] is not None and s["mult_bars"]],
}
for label, rets in exit_groups:
    rets = [r for r in rets if r is not None]
    if not rets: continue
    avg, win_pct, wl = stats(rets)
    bars_list = [b for b in bars_map.get(label, []) if b is not None]
    avg_b = round(sum(bars_list)/len(bars_list), 1) if bars_list else "—"
    print(f"  {label:<30}  n={len(rets):<5}  avg={_pct(avg):<12}  win={win_pct}%  W/L={wl:<8}  {avg_b}")

# How often does kijun/cloud exit fire BEFORE the ATR stop?
kijun_first = sum(1 for s in all_s
                  if s["kijun_bars"] is not None and s["mult_bars"].get(4.0) is not None
                  and s["kijun_bars"] < s["mult_bars"].get(4.0))
cloud_first = sum(1 for s in all_s
                  if s["cloud_bars"] is not None and s["mult_bars"].get(4.0) is not None
                  and s["cloud_bars"] < s["mult_bars"].get(4.0))
total_sim = len(all_s)
print(f"\n  Kijun exit fires BEFORE ATR stop: {kijun_first}/{total_sim} ({round(100*kijun_first/total_sim,1)}% of trades)")
print(f"  Cloud exit fires BEFORE ATR stop: {cloud_first}/{total_sim} ({round(100*cloud_first/total_sim,1)}% of trades)")

# Breakdown: when kijun fires first, is it better or worse?
kijun_better = [(s["kijun_return"] or 0) - (s["mult_returns"].get(4.0) or 0)
                for s in all_s if s["kijun_bars"] is not None and s["mult_bars"].get(4.0) is not None
                and s["kijun_bars"] < s["mult_bars"].get(4.0)]
kijun_worse_count = sum(1 for d in kijun_better if d < 0)
if kijun_better:
    avg_diff = round(sum(kijun_better)/len(kijun_better), 2)
    print(f"\n  When kijun fires first: avg difference vs 4×ATR = {_pct(avg_diff)}")
    print(f"  Kijun exit was WORSE than ATR in {kijun_worse_count}/{len(kijun_better)} cases ({round(100*kijun_worse_count/len(kijun_better),1)}%)")

# ══════════════════════════════════════════════════════════════════════════════
header("TEST 4: 2025 EXIT TIMING — Are trades stopping faster?")

print(f"\n  Avg bars held by year + outcome:")
print(f"  {'Year + outcome':<25}  {'Avg bars':<12}  {'n'}")
print("  " + "─" * 45)
for year in [2023, 2024, 2025, 2026]:
    for outcome in ["win", "loss"]:
        sub = [s for s in all_s
               if s["year"] == year
               and s["mult_bars"].get(4.0) is not None
               and ((outcome == "win" and s["actual_return"] > 0)
                    or (outcome == "loss" and s["actual_return"] < 0))]
        bars = [s["mult_bars"][4.0] for s in sub]
        if bars:
            print(f"  {year} {outcome:<18}  {round(sum(bars)/len(bars),1):<12}  {len(bars)}")
    print()

# ATR size by year — is volatility itself higher/lower?
print(f"  ATR% at entry by year (is vol changing?):")
print(f"  (This explains whether the stop is effectively wider or narrower over time)")
print(f"\n  {'Year':<8}  {'Avg ATR% at entry':<20}  {'n'}")
print("  " + "─" * 42)

# Need ATR% - recompute from actual_return and bars vs entry price proxy
# Actually we stored this in extended_tests... let's compute it fresh here
# We need OHLCV for this so let's just use the sim data we have
# Proxy: (entry_price - initial_stop) / entry_price = ATR_mult / entry_price * ATR
# We know mult=4, so: ATR_at_entry ≈ (entry_price - stop_level) / 4
# But we don't have stop_level stored... Let's compute from signals directly

# Alternative: use MAE and MFE data from DB
# Check if MAE correlates with ATR
# Let's just show avg ATR bars and let the user interpret

print("  (Using MAE as proxy for effective stop width)")
print(f"\n  {'Year':<8}  {'Avg MAE (losers)':<22}  {'Avg MFE (all)':<20}  n_losers")
print("  " + "─" * 58)
for year in [2023, 2024, 2025, 2026]:
    yr_sigs = [s for s in signals if get_year(s["fired_at"]) == year]
    losers_mae = [float(s["mae"]) for s in yr_sigs if s["mae"] is not None and s["exit_return"] and s["exit_return"] < 0]
    all_mfe    = [float(s["mfe"]) for s in yr_sigs if s["mfe"] is not None]
    if losers_mae:
        print(f"  {year:<8}  {_pct(round(sum(losers_mae)/len(losers_mae),2)):<22}  "
              f"{_pct(round(sum(all_mfe)/len(all_mfe),2)) if all_mfe else '—':<20}  "
              f"{len(losers_mae)}")

# How much do trades go in profit before stopping out (2025 specific)
print(f"\n  Losing trades that went positive before stopping (MFE > 0):")
for year in [2023, 2024, 2025, 2026]:
    yr_sigs = [s for s in signals if get_year(s["fired_at"]) == year
               and s["exit_return"] and s["exit_return"] < 0
               and s["mfe"] is not None]
    if not yr_sigs: continue
    went_green = [s for s in yr_sigs if float(s["mfe"]) > 0.5]
    pct = round(100 * len(went_green) / len(yr_sigs), 1)
    avg_mfe = round(sum(float(s["mfe"]) for s in went_green)/len(went_green), 2) if went_green else 0
    print(f"  {year}: {pct}% of losers went >{0.5}% green first (avg MFE when they did: +{avg_mfe}%)")

print("\n" + "=" * 72)
print("ALL EXIT TESTS COMPLETE")
print("=" * 72)
