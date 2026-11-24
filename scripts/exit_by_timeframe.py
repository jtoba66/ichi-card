"""
Cloud Reentry Exit vs ATR — split by timeframe
===============================================
Tests whether cloud reentry exit is viable on 4h vs 1d vs 1w.
Key metric: MFE gap = avg(MFE - exit_return) = profit given back before exit.

Run on HP:
    cd ~/ichi-scorecard
    uv run python scripts/exit_by_timeframe.py
"""
from __future__ import annotations

import os
import sys
from collections import defaultdict

import psycopg2
import psycopg2.extras

sys.stdout.reconfigure(line_buffering=True)  # type: ignore[attr-defined]

DB_URL = os.environ.get("ICHI_DATABASE_URL", "postgresql://ichi:ichi@localhost/ichi_signals")

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

print("Loading closed signals...")
conn = psycopg2.connect(DB_URL)
with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
    cur.execute("""
        SELECT signal_id, symbol, timeframe, fired_at,
               entry_price, exit_return, mfe
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

by_sym_tf: dict[tuple, list] = defaultdict(list)
for sig in signals:
    by_sym_tf[(sig["symbol"], sig["timeframe"])].append(sig)

MULTIPLIERS = [4.0, 5.0, 6.0]
MAX_BARS = 500

# Per-signal results keyed by signal_id
results: dict[str, dict] = {
    sig["signal_id"]: {
        "actual_return": float(sig["exit_return"]),
        "mfe":           float(sig["mfe"]) if sig["mfe"] is not None else None,
        "timeframe":     sig["timeframe"],
        "mult":          {},   # {4.0: return, 5.0: return, 6.0: return}
        "cloud_return":  None,
        "cloud_bars":    None,
        "atr4_bars":     None,
    }
    for sig in signals
}

def simulate_trail(closes, entry_bar, entry_price, atr_entry, mult):
    stop = entry_price - mult * atr_entry
    highest = entry_price
    for j in range(entry_bar + 1, min(entry_bar + MAX_BARS, len(closes))):
        c = closes[j]
        highest = max(highest, c)
        bars = j - entry_bar
        active = stop if bars <= 10 else max(stop, highest - mult * atr_entry)
        stop = active
        if c < active:
            return (c - entry_price) / entry_price * 100, bars
    last = min(entry_bar + MAX_BARS - 1, len(closes) - 1)
    return (closes[last] - entry_price) / entry_price * 100, last - entry_bar

def simulate_cloud(closes, span_a, span_b, entry_bar, entry_price):
    for j in range(entry_bar + 2, min(entry_bar + MAX_BARS, len(closes))):
        cloud_top = max(span_a[j], span_b[j])
        if closes[j] < cloud_top:
            return (closes[j] - entry_price) / entry_price * 100, j - entry_bar
    last = min(entry_bar + MAX_BARS - 1, len(closes) - 1)
    return (closes[last] - entry_price) / entry_price * 100, last - entry_bar

total = len(by_sym_tf)
for idx, ((symbol, timeframe), sigs) in enumerate(by_sym_tf.items()):
    if idx % 50 == 0:
        print(f"  [{idx+1}/{total}] {symbol} {timeframe}")
    try:
        pair = symbol.replace("USDT", "/USDT")
        df = fetch_ohlcv(pair, timeframe)
        df = ichimoku(df)
    except Exception:
        continue

    closes = df["close"].values
    span_a = df["span_a"].values
    span_b = df["span_b"].values

    for sig in sigs:
        bar = _find_bar_by_timestamp(df, sig["fired_at"])
        if bar is None or bar < 14:
            continue
        entry_price = float(sig["entry_price"])
        if entry_price <= 0:
            continue
        atr = _compute_atr14(df, bar)
        if atr <= 0:
            continue

        r = results[sig["signal_id"]]

        for mult in MULTIPLIERS:
            ret, bars = simulate_trail(closes, bar, entry_price, atr, mult)
            r["mult"][mult] = ret
            if mult == 4.0:
                r["atr4_bars"] = bars

        cl_ret, cl_bars = simulate_cloud(closes, span_a, span_b, bar, entry_price)
        r["cloud_return"] = cl_ret
        r["cloud_bars"]   = cl_bars

print(f"\n  Done.\n")

all_r = [v for v in results.values() if v["mult"] and v["cloud_return"] is not None]

# ── Output ────────────────────────────────────────────────────────────────────
print("=" * 72)
print("CLOUD REENTRY vs ATR MULTIPLIERS — by timeframe")
print("=" * 72)

for tf in ["4h", "1d", "1w"]:
    sub = [r for r in all_r if r["timeframe"] == tf]
    if len(sub) < 20:
        continue

    print(f"\n{'─'*72}")
    print(f"  TIMEFRAME: {tf}  (n={len(sub)})")
    print(f"{'─'*72}")
    print(f"  {'Exit method':<30}  {'n':<6}  {'Avg Ret':<12}  {'Win%':<8}  {'W/L':<8}  {'Avg bars'}")
    print(f"  {'─'*68}")

    for mult in MULTIPLIERS:
        rets  = [r["mult"][mult] for r in sub if mult in r["mult"]]
        bars  = [r["atr4_bars"]  for r in sub if r["atr4_bars"] is not None] if mult == 4.0 else []
        label = f"{mult}× ATR {'(production)' if mult==4.0 else ''}"
        if not rets: continue
        avg, win_pct, wl = stats(rets)
        avg_b = round(sum(bars)/len(bars), 1) if bars else "—"
        print(f"  {label:<30}  n={len(rets):<5}  avg={_pct(avg):<12}  win={win_pct}%  W/L={wl:<8}  {avg_b}")

    # Cloud reentry
    cl_rets = [r["cloud_return"] for r in sub if r["cloud_return"] is not None]
    cl_bars = [r["cloud_bars"]   for r in sub if r["cloud_bars"]  is not None]
    if cl_rets:
        avg, win_pct, wl = stats(cl_rets)
        avg_b = round(sum(cl_bars)/len(cl_bars), 1) if cl_bars else "—"
        print(f"  {'Cloud reentry':<30}  n={len(cl_rets):<5}  avg={_pct(avg):<12}  win={win_pct}%  W/L={wl:<8}  {avg_b}")

    # MFE gap — profit given back before cloud reentry fires
    # Only for signals where cloud exit fires AND we have MFE
    gap_data = [
        (r["mfe"], r["cloud_return"])
        for r in sub
        if r["mfe"] is not None and r["cloud_return"] is not None
        and r["cloud_bars"] is not None
        # only where cloud fires before max bars (i.e. actually triggered)
        and r["cloud_bars"] < MAX_BARS - 1
    ]
    if gap_data:
        gaps = [mfe - cl for mfe, cl in gap_data if mfe is not None]
        avg_gap = round(sum(gaps)/len(gaps), 2) if gaps else None
        avg_mfe = round(sum(g[0] for g in gap_data)/len(gap_data), 2)
        print(f"\n  MFE analysis for cloud reentry exits on {tf}:")
        print(f"    Avg MFE (peak profit):     {_pct(avg_mfe)}")
        print(f"    Avg cloud exit return:     {_pct(round(sum(r['cloud_return'] for r in sub if r['cloud_return'] is not None)/len(cl_rets),2))}")
        print(f"    Avg profit given back:     {_pct(avg_gap)}  ← MFE minus exit return")

    # How often cloud fires before 4×ATR
    cloud_first = sum(1 for r in sub
                      if r["cloud_bars"] is not None and r["atr4_bars"] is not None
                      and r["cloud_bars"] < r["atr4_bars"])
    print(f"\n  Cloud fires before 4×ATR: {cloud_first}/{len(sub)} ({round(100*cloud_first/len(sub),1)}%)")

    # For those where cloud fires first — was it better or worse than 4×ATR?
    cloud_first_diff = [
        r["cloud_return"] - r["mult"].get(4.0, 0)
        for r in sub
        if r["cloud_bars"] is not None and r["atr4_bars"] is not None
        and r["cloud_bars"] < r["atr4_bars"]
        and 4.0 in r["mult"]
    ]
    if cloud_first_diff:
        better = sum(1 for d in cloud_first_diff if d > 0)
        avg_diff = round(sum(cloud_first_diff)/len(cloud_first_diff), 2)
        print(f"  When cloud fires first: avg diff vs 4×ATR = {_pct(avg_diff)}  "
              f"(better {better}/{len(cloud_first_diff)} times = {round(100*better/len(cloud_first_diff),1)}%)")

print("\n" + "=" * 72)
print("DONE")
print("=" * 72)
