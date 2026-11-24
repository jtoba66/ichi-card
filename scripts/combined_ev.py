"""
Combined EV: Entry filters × ATR multipliers
=============================================
Applies all validated entry filters and simulates each ATR multiplier
to get the precise expected value per trade for each tier.

Filters tested:
  - Tier 1: BTC above + QS 60+ + Hosoda + no bad coin
  - Tier 2: BTC above + QS 60+ + no bad coin
  - Tier 3: BTC above (all, unfiltered quality)
  - Baseline: all signals

ATR multipliers: 4× (current), 5×, 6×
Split by timeframe (4h, 1d, 1w) since optimal multiplier differs.

Run on HP:
    cd ~/ichi-scorecard
    uv run python scripts/combined_ev.py
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

BAD_COINS = {"BATUSDT", "EIGENUSDT", "SFPUSDT", "FFUSDT", "APEUSDT", "XMRUSDT"}

print("Loading closed signals...")
conn = psycopg2.connect(DB_URL)
with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
    cur.execute("""
        SELECT signal_id, symbol, timeframe, fired_at,
               entry_price, exit_return, quality_score, hosoda_active
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

# BTC 1d regime
print("Loading BTC 1d regime...")
btc_1d = ichimoku(fetch_ohlcv("BTC/USDT", "1d"))

def btc_regime(fired_at):
    bar = _find_bar_by_timestamp(btc_1d, fired_at)
    if bar is None or bar < 52: return "unknown"
    close = float(btc_1d["close"].iat[bar])
    top = float(max(btc_1d["span_a"].iat[bar], btc_1d["span_b"].iat[bar]))
    bot = float(min(btc_1d["span_a"].iat[bar], btc_1d["span_b"].iat[bar]))
    if close > top: return "above"
    if close < bot: return "below"
    return "inside"

def qs_ok(qs): return qs is not None and qs >= 60

# Pre-tag each signal
print("Tagging signals with regime + filters...")
for sig in signals:
    sig["_regime"]  = btc_regime(sig["fired_at"])
    sig["_qs_ok"]   = qs_ok(sig["quality_score"])
    sig["_hosoda"]  = bool(sig["hosoda_active"])
    sig["_bad"]     = sig["symbol"] in BAD_COINS

TIERS = {
    "Tier 1 (BTC above+QS60++Hosoda+clean)": lambda s: s["_regime"]=="above" and s["_qs_ok"] and s["_hosoda"] and not s["_bad"],
    "Tier 2 (BTC above+QS60++clean)":        lambda s: s["_regime"]=="above" and s["_qs_ok"] and not s["_bad"],
    "Tier 3 (BTC above, all quality)":        lambda s: s["_regime"]=="above",
    "Baseline (all signals)":                 lambda s: True,
}

# Group by (symbol, timeframe)
by_sym_tf: dict[tuple, list] = defaultdict(list)
for sig in signals:
    by_sym_tf[(sig["symbol"], sig["timeframe"])].append(sig)

MULTIPLIERS = [4.0, 5.0, 6.0]
MAX_BARS = 500

# Store sim results per signal
sim: dict[str, dict] = {
    sig["signal_id"]: {
        "timeframe": sig["timeframe"],
        "tier_flags": {
            name: fn(sig) for name, fn in TIERS.items()
        },
        "mult": {},
    }
    for sig in signals
}

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

    for sig in sigs:
        bar = _find_bar_by_timestamp(df, sig["fired_at"])
        if bar is None or bar < 14:
            continue
        entry = float(sig["entry_price"])
        if entry <= 0:
            continue
        atr = _compute_atr14(df, bar)
        if atr <= 0:
            continue

        for mult in MULTIPLIERS:
            stop = entry - mult * atr
            highest = entry
            ret = None
            for j in range(bar + 1, min(bar + MAX_BARS, len(closes))):
                c = closes[j]
                highest = max(highest, c)
                bars = j - bar
                active = stop if bars <= 10 else max(stop, highest - mult * atr)
                stop = active
                if c < active:
                    ret = (c - entry) / entry * 100
                    break
            if ret is None:
                last = min(bar + MAX_BARS - 1, len(closes) - 1)
                ret = (closes[last] - entry) / entry * 100
            sim[sig["signal_id"]]["mult"][mult] = ret

print(f"\n  Simulation complete.\n")

# ── Output ────────────────────────────────────────────────────────────────────
print("=" * 72)
print("COMBINED EV: Entry filters × ATR multiplier")
print("=" * 72)

# Best multiplier per timeframe based on exit tests:
BEST_MULT = {"4h": 6.0, "1d": 6.0, "1w": 4.0}

all_sim = [v for v in sim.values() if v["mult"]]

for tier_name in TIERS:
    print(f"\n{'─'*72}")
    print(f"  {tier_name}")
    print(f"{'─'*72}")
    print(f"  {'Scope':<30}  {'n':<6}  {'Avg Ret':<12}  {'Win%':<8}  {'W/L':<8}  Avg win / Avg loss")
    print(f"  {'─'*70}")

    for tf_label, tf_filter in [
        ("All timeframes combined", lambda s: True),
        ("4h only",                 lambda s: s["timeframe"] == "4h"),
        ("1d only",                 lambda s: s["timeframe"] == "1d"),
        ("1w only",                 lambda s: s["timeframe"] == "1w"),
    ]:
        # Use optimal multiplier per timeframe
        rets = []
        for s in all_sim:
            if not s["tier_flags"][tier_name]: continue
            if not tf_filter(s): continue
            tf = s["timeframe"]
            mult = BEST_MULT.get(tf, 4.0)
            if mult in s["mult"]:
                rets.append(s["mult"][mult])

        if len(rets) < 10:
            continue
        avg, win_pct, wl = stats(rets)
        avg_win  = round(sum(r for r in rets if r > 0) / max(1, sum(1 for r in rets if r > 0)), 2)
        avg_loss = round(sum(r for r in rets if r < 0) / max(1, sum(1 for r in rets if r < 0)), 2)
        print(f"  {tf_label:<30}  n={len(rets):<5}  avg={_pct(avg):<12}  win={win_pct}%  W/L={wl:<8}  {_pct(avg_win)} / {_pct(avg_loss)}")

    # Also show all multipliers for all-timeframe combined (to see progression)
    print(f"\n  Multiplier breakdown (all TFs, optimal per TF):")
    print(f"  {'Multiplier':<15}  {'n':<6}  {'Avg Ret':<12}  {'Win%':<8}  {'W/L'}")
    print(f"  {'─'*55}")
    for mult in MULTIPLIERS:
        rets = [
            s["mult"][mult]
            for s in all_sim
            if s["tier_flags"][tier_name] and mult in s["mult"]
        ]
        if not rets: continue
        avg, win_pct, wl = stats(rets)
        label = f"{mult}× ATR {'← current' if mult==4.0 else ''}"
        print(f"  {label:<15}  n={len(rets):<5}  avg={_pct(avg):<12}  win={win_pct}%  W/L={wl}")

print("\n" + "=" * 72)
print("DONE")
print("=" * 72)
