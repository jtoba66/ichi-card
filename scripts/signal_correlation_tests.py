"""
Signal Correlation Tests: BTC Regime, KJ Distance, Kumo Twist Proximity
========================================================================
Test 1: BTC regime filter — signals when BTC is above/below/inside cloud
Test 5: KJ distance at entry — how far price is above Kijun at signal entry
Test 6: Kumo twist proximity — does firing near a kumo twist affect outcome?

Run on HP:
    cd ~/ichi-scorecard
    uv run python scripts/signal_correlation_tests.py
"""
from __future__ import annotations

import os
import sys
from collections import defaultdict

import numpy as np
import pandas as pd
import psycopg2
import psycopg2.extras

sys.stdout.reconfigure(line_buffering=True)  # type: ignore[attr-defined]

DB_URL = os.environ.get("ICHI_DATABASE_URL", "postgresql://ichi:ichi@localhost/ichi_signals")

def _pct(v): return f"{v:+.2f}%" if v is not None else "—"
def _bar(label, n, avg, win, wl):
    return f"  {label:<28}  n={n:<5}  avg={_pct(avg)}  win={win or '—'}%  W/L={wl or '—'}"

# ── Load signals ──────────────────────────────────────────────────────────────
print("Loading closed signals...")
conn = psycopg2.connect(DB_URL)
with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
    cur.execute("""
        SELECT signal_id, signal_type, symbol, timeframe, fired_at,
               entry_price, exit_return, status, quality_score, hosoda_active
        FROM signal_log
        WHERE is_backfill = 1
          AND status = 'CLOSED'
          AND exit_return IS NOT NULL
        ORDER BY fired_at ASC
    """)
    signals = [dict(r) for r in cur.fetchall()]
conn.close()
print(f"  {len(signals)} closed signals loaded.\n")

from ichi.data.fetcher import fetch_ohlcv
from ichi.indicators.ichimoku import ichimoku
from ichi.signal.jobs import _find_bar_by_timestamp

# ── TEST 1: BTC Regime ────────────────────────────────────────────────────────
print("=" * 70)
print("TEST 1: BTC REGIME FILTER")
print("=" * 70)

print("Loading BTC 1d OHLCV + ichimoku...")
btc_df = fetch_ohlcv("BTC/USDT", "1d")
btc_df = ichimoku(btc_df)

# Build date → regime lookup
def btc_regime_at(fired_at: str) -> str:
    bar = _find_bar_by_timestamp(btc_df, fired_at)
    if bar is None or bar < 52:
        return "unknown"
    close = float(btc_df["close"].iat[bar])
    cloud_top = float(max(btc_df["span_a"].iat[bar], btc_df["span_b"].iat[bar]))
    cloud_bot = float(min(btc_df["span_a"].iat[bar], btc_df["span_b"].iat[bar]))
    if close > cloud_top:
        return "above"
    elif close < cloud_bot:
        return "below"
    else:
        return "inside"

regime_buckets: dict[str, list] = defaultdict(list)
for sig in signals:
    r = btc_regime_at(sig["fired_at"])
    regime_buckets[r].append(float(sig["exit_return"]))

def stats(returns):
    if not returns:
        return None, None, None
    wins = [r for r in returns if r > 0]
    losses = [r for r in returns if r < 0]
    avg = round(sum(returns) / len(returns), 2)
    win_pct = round(100 * len(wins) / len(returns), 1)
    avg_win = round(sum(wins)/len(wins), 2) if wins else None
    avg_loss = round(sum(losses)/len(losses), 2) if losses else None
    wl = round(abs(avg_win/avg_loss), 2) if (avg_win and avg_loss) else None
    return avg, win_pct, wl

print(f"\n  {'Regime':<28}  {'n':<6}  {'Avg Return':<12}  {'Win%':<8}  {'W/L'}")
print("  " + "─" * 65)
for regime in ["above", "inside", "below", "unknown"]:
    rets = regime_buckets[regime]
    if not rets:
        continue
    avg, win_pct, wl = stats(rets)
    print(f"  BTC {regime:<24}  n={len(rets):<5}  avg={_pct(avg):<12}  win={win_pct}%  W/L={wl}")

# Also: with vs without BTC above cloud — what's the EV improvement if we skip below/inside?
above_rets = regime_buckets["above"]
skip_rets = regime_buckets["below"] + regime_buckets["inside"]
all_rets = above_rets + skip_rets + regime_buckets["unknown"]

print(f"\n  {'Baseline (all signals)':<28}  n={len(all_rets):<5}  avg={_pct(round(sum(all_rets)/len(all_rets),2))}")
print(f"  {'BTC above cloud only':<28}  n={len(above_rets):<5}  avg={_pct(round(sum(above_rets)/len(above_rets),2))}")
print(f"  {'Signals skipped (below/inside)':<28}  n={len(skip_rets)}")

# ── TEST 5: KJ Distance at Entry ──────────────────────────────────────────────
print("\n" + "=" * 70)
print("TEST 5: KJ DISTANCE AT ENTRY")
print("  (How far above Kijun was price when signal fired?)")
print("=" * 70)

by_sym_tf: dict[tuple, list] = defaultdict(list)
for sig in signals:
    by_sym_tf[(sig["symbol"], sig["timeframe"])].append(sig)

kj_dist_data: list[dict] = []
processed = skipped = 0
total = len(by_sym_tf)

print(f"\nProcessing {total} (symbol, timeframe) pairs...")
for idx, ((symbol, timeframe), sigs) in enumerate(by_sym_tf.items()):
    if idx % 50 == 0:
        print(f"  [{idx+1}/{total}]  ({processed} signals processed)")
    try:
        pair = symbol.replace("USDT", "/USDT")
        df = fetch_ohlcv(pair, timeframe)
        df = ichimoku(df)
    except Exception:
        skipped += len(sigs)
        continue

    for sig in sigs:
        bar = _find_bar_by_timestamp(df, sig["fired_at"])
        if bar is None or bar < 52:
            skipped += 1
            continue
        kj = float(df["kj"].iat[bar])
        if kj <= 0:
            skipped += 1
            continue
        entry = float(sig["entry_price"])
        kj_dist_pct = (entry - kj) / kj * 100
        kj_dist_data.append({
            "signal_id": sig["signal_id"],
            "exit_return": float(sig["exit_return"]),
            "kj_dist_pct": kj_dist_pct,
        })
        processed += 1

print(f"\n  Done. {processed} signals with KJ distance computed, {skipped} skipped.")

# Bucket by KJ distance
def kj_bucket(d):
    if d < 0: return "below KJ (<0%)"
    if d < 3: return "0-3% above KJ"
    if d < 7: return "3-7% above KJ"
    if d < 15: return "7-15% above KJ"
    if d < 30: return "15-30% above KJ"
    return ">30% above KJ (overextended)"

from collections import defaultdict
kj_buckets: dict[str, list] = defaultdict(list)
for d in kj_dist_data:
    kj_buckets[kj_bucket(d["kj_dist_pct"])].append(d["exit_return"])

order = ["below KJ (<0%)", "0-3% above KJ", "3-7% above KJ",
         "7-15% above KJ", "15-30% above KJ", ">30% above KJ (overextended)"]

print(f"\n  {'KJ Distance':<30}  {'n':<6}  {'Avg Return':<12}  {'Win%':<8}  {'W/L'}")
print("  " + "─" * 65)
for bucket in order:
    rets = kj_buckets[bucket]
    if not rets:
        continue
    avg, win_pct, wl = stats(rets)
    print(f"  {bucket:<30}  n={len(rets):<5}  avg={_pct(avg):<12}  win={win_pct}%  W/L={wl}")

# ── TEST 6: Kumo Twist Proximity ──────────────────────────────────────────────
print("\n" + "=" * 70)
print("TEST 6: KUMO TWIST PROXIMITY")
print("  (Does firing within ±5 bars of a kumo twist affect outcomes?)")
print("=" * 70)

TWIST_WINDOW = 5  # bars either side

twist_data: list[dict] = []

for idx, ((symbol, timeframe), sigs) in enumerate(by_sym_tf.items()):
    try:
        pair = symbol.replace("USDT", "/USDT")
        df = fetch_ohlcv(pair, timeframe)
        df = ichimoku(df)
    except Exception:
        continue

    # Find all kumo twist bars
    if "span_a" not in df.columns or "span_b" not in df.columns:
        continue
    ssa = df["span_a"].values
    ssb = df["span_b"].values
    twist_bars = set()
    for i in range(1, len(df)):
        if (ssa[i-1] - ssb[i-1]) * (ssa[i] - ssb[i]) < 0:
            twist_bars.add(i)

    for sig in sigs:
        bar = _find_bar_by_timestamp(df, sig["fired_at"])
        if bar is None or bar < 52:
            continue
        near_twist = any(abs(bar - t) <= TWIST_WINDOW for t in twist_bars)
        twist_data.append({
            "exit_return": float(sig["exit_return"]),
            "near_twist": near_twist,
        })

near_rets  = [d["exit_return"] for d in twist_data if d["near_twist"]]
far_rets   = [d["exit_return"] for d in twist_data if not d["near_twist"]]

print(f"\n  Window: ±{TWIST_WINDOW} bars from a kumo twist")
print(f"\n  {'Group':<35}  {'n':<6}  {'Avg Return':<12}  {'Win%':<8}  {'W/L'}")
print("  " + "─" * 65)
for label, rets in [("Near kumo twist (±5 bars)", near_rets),
                    ("Far from kumo twist (>5 bars)", far_rets)]:
    avg, win_pct, wl = stats(rets)
    print(f"  {label:<35}  n={len(rets):<5}  avg={_pct(avg):<12}  win={win_pct}%  W/L={wl}")

# Sub-analysis: near twist by direction (green→red vs red→green)
green_twist: list[float] = []
red_twist: list[float] = []

for idx, ((symbol, timeframe), sigs) in enumerate(by_sym_tf.items()):
    try:
        pair = symbol.replace("USDT", "/USDT")
        df = fetch_ohlcv(pair, timeframe)
        df = ichimoku(df)
    except Exception:
        continue
    if "span_a" not in df.columns or "span_b" not in df.columns:
        continue
    ssa = df["span_a"].values
    ssb = df["span_b"].values
    green_twists = set()  # ssa crosses above ssb (bullish)
    red_twists = set()    # ssa crosses below ssb (bearish)
    for i in range(1, len(df)):
        if ssa[i-1] < ssb[i-1] and ssa[i] > ssb[i]:
            green_twists.add(i)
        elif ssa[i-1] > ssb[i-1] and ssa[i] < ssb[i]:
            red_twists.add(i)
    for sig in sigs:
        bar = _find_bar_by_timestamp(df, sig["fired_at"])
        if bar is None or bar < 52:
            continue
        er = float(sig["exit_return"])
        if any(abs(bar - t) <= TWIST_WINDOW for t in green_twists):
            green_twist.append(er)
        elif any(abs(bar - t) <= TWIST_WINDOW for t in red_twists):
            red_twist.append(er)

print(f"\n  Near a BULLISH kumo twist (→green):")
if green_twist:
    avg, win_pct, wl = stats(green_twist)
    print(f"    n={len(green_twist)}  avg={_pct(avg)}  win={win_pct}%  W/L={wl}")

print(f"\n  Near a BEARISH kumo twist (→red):")
if red_twist:
    avg, win_pct, wl = stats(red_twist)
    print(f"    n={len(red_twist)}  avg={_pct(avg)}  win={win_pct}%  W/L={wl}")

print("\n" + "=" * 70)
print("ALL TESTS COMPLETE")
print("=" * 70)
