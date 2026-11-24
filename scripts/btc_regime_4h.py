"""
BTC 4h Regime Filter — applied to 1d and 4h signals
=====================================================
Uses BTC/USDT 4h cloud to determine regime at each signal's fired_at.
Reports results split by signal timeframe (1d vs 4h).

Run on HP:
    cd ~/ichi-scorecard
    uv run python scripts/btc_regime_4h.py
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
    wins = [r for r in returns if r > 0]
    losses = [r for r in returns if r < 0]
    avg = round(sum(returns) / len(returns), 2)
    win_pct = round(100 * len(wins) / len(returns), 1)
    avg_win = round(sum(wins)/len(wins), 2) if wins else None
    avg_loss = round(sum(losses)/len(losses), 2) if losses else None
    wl = round(abs(avg_win/avg_loss), 2) if (avg_win and avg_loss) else None
    return avg, win_pct, wl

# Load 4h and 1d signals only
print("Loading closed 4h and 1d signals...")
conn = psycopg2.connect(DB_URL)
with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
    cur.execute("""
        SELECT signal_id, signal_type, symbol, timeframe, fired_at,
               entry_price, exit_return, status
        FROM signal_log
        WHERE is_backfill = 1
          AND status = 'CLOSED'
          AND exit_return IS NOT NULL
          AND timeframe IN ('4h', '1d')
        ORDER BY fired_at ASC
    """)
    signals = [dict(r) for r in cur.fetchall()]
conn.close()

tf_counts = defaultdict(int)
for s in signals:
    tf_counts[s["timeframe"]] += 1
print(f"  {len(signals)} signals loaded  (4h: {tf_counts['4h']}, 1d: {tf_counts['1d']})\n")

from ichi.data.fetcher import fetch_ohlcv
from ichi.indicators.ichimoku import ichimoku
from ichi.signal.jobs import _find_bar_by_timestamp

# Load BTC 4h
print("Loading BTC/USDT 4h OHLCV + ichimoku...")
btc_4h = fetch_ohlcv("BTC/USDT", "4h")
btc_4h = ichimoku(btc_4h)
print(f"  {len(btc_4h)} bars loaded.\n")

def btc_regime_4h(fired_at: str) -> str:
    bar = _find_bar_by_timestamp(btc_4h, fired_at)
    if bar is None or bar < 52:
        return "unknown"
    close = float(btc_4h["close"].iat[bar])
    cloud_top = float(max(btc_4h["span_a"].iat[bar], btc_4h["span_b"].iat[bar]))
    cloud_bot = float(min(btc_4h["span_a"].iat[bar], btc_4h["span_b"].iat[bar]))
    if close > cloud_top:
        return "above"
    elif close < cloud_bot:
        return "below"
    else:
        return "inside"

# Bucket by (timeframe, regime)
buckets: dict[tuple, list] = defaultdict(list)
for sig in signals:
    r = btc_regime_4h(sig["fired_at"])
    buckets[(sig["timeframe"], r)].append(float(sig["exit_return"]))

print("=" * 70)
print("BTC 4h REGIME FILTER — applied to 4h signals")
print("=" * 70)
print(f"\n  {'Regime':<28}  {'n':<6}  {'Avg Return':<12}  {'Win%':<8}  {'W/L'}")
print("  " + "─" * 62)
for regime in ["above", "inside", "below", "unknown"]:
    rets = buckets[("4h", regime)]
    if not rets:
        continue
    avg, win_pct, wl = stats(rets)
    print(f"  BTC 4h {regime:<21}  n={len(rets):<5}  avg={_pct(avg):<12}  win={win_pct}%  W/L={wl}")

all_4h = [r for regime in ["above","inside","below","unknown"] for r in buckets[("4h", regime)]]
above_4h = buckets[("4h", "above")]
skip_4h = buckets[("4h", "below")] + buckets[("4h", "inside")]
if all_4h:
    print(f"\n  Baseline (all 4h signals)     n={len(all_4h):<5}  avg={_pct(round(sum(all_4h)/len(all_4h),2))}")
    print(f"  BTC 4h above cloud only       n={len(above_4h):<5}  avg={_pct(round(sum(above_4h)/len(above_4h),2))}")
    print(f"  Signals skipped               n={len(skip_4h)}")

print("\n" + "=" * 70)
print("BTC 4h REGIME FILTER — applied to 1d signals")
print("=" * 70)
print(f"\n  {'Regime':<28}  {'n':<6}  {'Avg Return':<12}  {'Win%':<8}  {'W/L'}")
print("  " + "─" * 62)
for regime in ["above", "inside", "below", "unknown"]:
    rets = buckets[("1d", regime)]
    if not rets:
        continue
    avg, win_pct, wl = stats(rets)
    print(f"  BTC 4h {regime:<21}  n={len(rets):<5}  avg={_pct(avg):<12}  win={win_pct}%  W/L={wl}")

all_1d = [r for regime in ["above","inside","below","unknown"] for r in buckets[("1d", regime)]]
above_1d = buckets[("1d", "above")]
skip_1d = buckets[("1d", "below")] + buckets[("1d", "inside")]
if all_1d:
    print(f"\n  Baseline (all 1d signals)     n={len(all_1d):<5}  avg={_pct(round(sum(all_1d)/len(all_1d),2))}")
    print(f"  BTC 4h above cloud only       n={len(above_1d):<5}  avg={_pct(round(sum(above_1d)/len(above_1d),2))}")
    print(f"  Signals skipped               n={len(skip_1d)}")

print("\n" + "=" * 70)
print("DONE")
print("=" * 70)
