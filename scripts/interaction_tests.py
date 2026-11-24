"""
Interaction Tests — All filters combined + Kumo Twist Age Analysis
==================================================================
Builds a signal-level feature table combining everything we know:
  - BTC 1d regime (above/inside/below cloud)
  - Quality score bucket
  - Hosoda active
  - Signal type
  - Timeframe
  - KJ distance at entry
  - Nearest kumo twist: direction (bullish/bearish) + bars ago

Then tests:
  A) Twist age — how many bars since the twist, split by direction
     Windows: 1-2, 3-5, 6-10, 11-20, 21-40, >40, none
  B) BTC regime × Quality bucket
  C) BTC regime × Hosoda
  D) BTC regime × Quality × Hosoda  (triple combo — "gold standard")
  E) Quality × KJ distance
  F) Twist direction × Quality
  G) Signal type × BTC regime
  H) KJ distance × BTC regime
  I) Bad coins × BTC regime  (do losers improve when BTC is above cloud?)

Run on HP:
    cd ~/ichi-scorecard
    uv run python scripts/interaction_tests.py
"""
from __future__ import annotations

import os
import sys
from collections import defaultdict

import psycopg2
import psycopg2.extras

sys.stdout.reconfigure(line_buffering=True)  # type: ignore[attr-defined]

DB_URL = os.environ.get("ICHI_DATABASE_URL", "postgresql://ichi:ichi@localhost/ichi_signals")

# ── Helpers ───────────────────────────────────────────────────────────────────
def _pct(v): return f"{v:+.2f}%" if v is not None else "—"

def stats(returns):
    if not returns:
        return None, None, None
    wins   = [r for r in returns if r > 0]
    losses = [r for r in returns if r < 0]
    avg    = round(sum(returns) / len(returns), 2)
    win_pct = round(100 * len(wins) / len(returns), 1)
    avg_win  = round(sum(wins)/len(wins), 2)   if wins   else None
    avg_loss = round(sum(losses)/len(losses), 2) if losses else None
    wl = round(abs(avg_win/avg_loss), 2) if (avg_win and avg_loss) else None
    return avg, win_pct, wl

def print_table(headers, rows):
    print(f"\n  {headers}")
    print("  " + "─" * 72)
    for row in rows:
        print(f"  {row}")

def row(label, rets, width=38):
    if not rets:
        return None
    avg, win_pct, wl = stats(rets)
    return f"{label:<{width}}  n={len(rets):<5}  avg={_pct(avg):<12}  win={win_pct}%  W/L={wl}"

# ── Load signals ──────────────────────────────────────────────────────────────
print("Loading closed signals...")
conn = psycopg2.connect(DB_URL)
with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
    cur.execute("""
        SELECT signal_id, signal_type, symbol, timeframe, fired_at,
               entry_price, exit_return, quality_score,
               hosoda_active, is_backfill
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
from ichi.signal.jobs import _find_bar_by_timestamp

# ── BTC 1d regime ─────────────────────────────────────────────────────────────
print("Loading BTC 1d for regime...")
btc_1d = fetch_ohlcv("BTC/USDT", "1d")
btc_1d = ichimoku(btc_1d)

def btc_regime(fired_at, df):
    bar = _find_bar_by_timestamp(df, fired_at)
    if bar is None or bar < 52:
        return "unknown"
    close = float(df["close"].iat[bar])
    top = float(max(df["span_a"].iat[bar], df["span_b"].iat[bar]))
    bot = float(min(df["span_a"].iat[bar], df["span_b"].iat[bar]))
    if close > top:   return "above"
    if close < bot:   return "below"
    return "inside"

# ── Quality bucket ────────────────────────────────────────────────────────────
def qs_bucket(qs):
    if qs is None or qs == 0: return "unscored (0)"
    if qs >= 80: return "80-100 (Elite)"
    if qs >= 60: return "60-79 (Strong)"
    if qs >= 40: return "40-59 (Solid)"
    if qs >= 20: return "20-39 (Weak)"
    return "<20 (Low)"

# ── KJ distance bucket ────────────────────────────────────────────────────────
def kj_bucket(d):
    if d is None:    return None
    if d < 0:        return "below KJ"
    if d < 3:        return "0-3% above KJ"
    if d < 7:        return "3-7% above KJ"
    if d < 15:       return "7-15% above KJ"
    if d < 30:       return "15-30% above KJ"
    return ">30% above KJ"

# ── Bad coins from Test 2 ─────────────────────────────────────────────────────
BAD_COINS = {"BATUSDT", "EIGENUSDT", "SFPUSDT", "FFUSDT", "APEUSDT", "XMRUSDT"}

# ── Build signal feature table ────────────────────────────────────────────────
print("Building per-signal feature table (fetching OHLCV per pair)...")

# Index signals by (symbol, timeframe)
by_sym_tf: dict[tuple, list] = defaultdict(list)
for sig in signals:
    by_sym_tf[(sig["symbol"], sig["timeframe"])].append(sig)

# Store features per signal_id
features: dict[str, dict] = {}

# Pre-assign BTC regime + quality bucket (don't need OHLCV for these)
for sig in signals:
    features[sig["signal_id"]] = {
        "exit_return":  float(sig["exit_return"]),
        "signal_type":  sig["signal_type"],
        "timeframe":    sig["timeframe"],
        "symbol":       sig["symbol"],
        "btc_regime":   btc_regime(sig["fired_at"], btc_1d),
        "qs_bucket":    qs_bucket(sig["quality_score"]),
        "hosoda":       bool(sig["hosoda_active"]),
        "bad_coin":     sig["symbol"] in BAD_COINS,
        "kj_dist":      None,   # filled below
        "kj_bucket":    None,
        "twist_dir":    "none", # filled below: bullish / bearish / none
        "twist_age":    None,   # bars since nearest twist
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

    span_a = df["span_a"].values
    span_b = df["span_b"].values

    # Detect all twist bars + direction
    bullish_twists: list[int] = []  # span_a crosses above span_b
    bearish_twists: list[int] = []  # span_a crosses below span_b
    for i in range(1, len(df)):
        if span_a[i-1] <= span_b[i-1] and span_a[i] > span_b[i]:
            bullish_twists.append(i)
        elif span_a[i-1] >= span_b[i-1] and span_a[i] < span_b[i]:
            bearish_twists.append(i)

    for sig in sigs:
        bar = _find_bar_by_timestamp(df, sig["fired_at"])
        if bar is None or bar < 52:
            continue

        feat = features[sig["signal_id"]]

        # KJ distance
        kj = float(df["kj"].iat[bar])
        if kj > 0:
            entry = float(sig["entry_price"])
            d = (entry - kj) / kj * 100
            feat["kj_dist"]   = d
            feat["kj_bucket"] = kj_bucket(d)

        # Nearest twist + direction (look back up to 60 bars)
        best_age  = None
        best_dir  = "none"
        for t in bullish_twists:
            age = bar - t
            if 0 <= age <= 60:
                if best_age is None or age < best_age:
                    best_age = age
                    best_dir = "bullish"
        for t in bearish_twists:
            age = bar - t
            if 0 <= age <= 60:
                if best_age is None or age < best_age:
                    best_age = age
                    best_dir = "bearish"

        feat["twist_dir"] = best_dir
        feat["twist_age"] = best_age

print(f"\n  Feature table built for {len(features)} signals.\n")

all_f = list(features.values())

# ── Twist age bucket ──────────────────────────────────────────────────────────
def age_bucket(age):
    if age is None:   return "no twist (>60 bars)"
    if age <= 2:      return "0-2 bars ago"
    if age <= 5:      return "3-5 bars ago"
    if age <= 10:     return "6-10 bars ago"
    if age <= 20:     return "11-20 bars ago"
    if age <= 40:     return "21-40 bars ago"
    return "41-60 bars ago"

AGE_ORDER = ["0-2 bars ago", "3-5 bars ago", "6-10 bars ago",
             "11-20 bars ago", "21-40 bars ago", "41-60 bars ago",
             "no twist (>60 bars)"]

# ══════════════════════════════════════════════════════════════════════════════
print("=" * 72)
print("TEST A: KUMO TWIST AGE — How many bars since the twist?")
print("         (split by bullish vs bearish twist direction)")
print("=" * 72)

for direction in ["bullish", "bearish"]:
    print(f"\n  Direction: {direction.upper()} twist")
    print(f"  {'Age bucket':<22}  {'n':<6}  {'Avg Return':<12}  {'Win%':<8}  {'W/L'}")
    print("  " + "─" * 62)
    for bucket in AGE_ORDER:
        if bucket == "no twist (>60 bars)":
            rets = [f["exit_return"] for f in all_f if f["twist_dir"] == "none"]
            label = "no twist nearby"
        else:
            rets = [f["exit_return"] for f in all_f
                    if f["twist_dir"] == direction and age_bucket(f["twist_age"]) == bucket]
        if not rets:
            continue
        r = row(bucket if bucket != "no twist (>60 bars)" else "no twist nearby", rets, width=22)
        if r: print(f"  {r}")

# ══════════════════════════════════════════════════════════════════════════════
print("\n" + "=" * 72)
print("TEST B: BTC REGIME × QUALITY BUCKET")
print("=" * 72)
print(f"\n  {'Regime + Quality':<40}  {'n':<6}  {'Avg Return':<12}  {'Win%':<8}  {'W/L'}")
print("  " + "─" * 72)

QS_ORDER = ["80-100 (Elite)", "60-79 (Strong)", "40-59 (Solid)",
            "20-39 (Weak)", "<20 (Low)", "unscored (0)"]

for regime in ["above", "inside", "below"]:
    for qb in QS_ORDER:
        rets = [f["exit_return"] for f in all_f
                if f["btc_regime"] == regime and f["qs_bucket"] == qb]
        if len(rets) < 20:
            continue
        r = row(f"BTC {regime} + QS {qb}", rets, width=40)
        if r: print(f"  {r}")
    print()

# ══════════════════════════════════════════════════════════════════════════════
print("=" * 72)
print("TEST C: BTC REGIME × HOSODA")
print("=" * 72)
print(f"\n  {'Group':<35}  {'n':<6}  {'Avg Return':<12}  {'Win%':<8}  {'W/L'}")
print("  " + "─" * 68)
for regime in ["above", "inside", "below"]:
    for hosoda in [True, False]:
        label = f"BTC {regime} + {'Hosoda' if hosoda else 'no Hosoda'}"
        rets = [f["exit_return"] for f in all_f
                if f["btc_regime"] == regime and f["hosoda"] == hosoda]
        r = row(label, rets, width=35)
        if r: print(f"  {r}")
    print()

# ══════════════════════════════════════════════════════════════════════════════
print("=" * 72)
print("TEST D: BTC ABOVE × QUALITY × HOSODA  (triple combo)")
print("=" * 72)
print(f"\n  {'Combo':<45}  {'n':<6}  {'Avg Return':<12}  {'Win%':<8}  {'W/L'}")
print("  " + "─" * 75)

combos = [
    ("BTC above + QS 60+ + Hosoda",      lambda f: f["btc_regime"]=="above" and f["qs_bucket"] in ["60-79 (Strong)","80-100 (Elite)"] and f["hosoda"]),
    ("BTC above + QS 60+ no Hosoda",     lambda f: f["btc_regime"]=="above" and f["qs_bucket"] in ["60-79 (Strong)","80-100 (Elite)"] and not f["hosoda"]),
    ("BTC above + QS 40-59 + Hosoda",    lambda f: f["btc_regime"]=="above" and f["qs_bucket"]=="40-59 (Solid)" and f["hosoda"]),
    ("BTC above + QS 40-59 no Hosoda",   lambda f: f["btc_regime"]=="above" and f["qs_bucket"]=="40-59 (Solid)" and not f["hosoda"]),
    ("BTC above + unscored + Hosoda",    lambda f: f["btc_regime"]=="above" and f["qs_bucket"]=="unscored (0)" and f["hosoda"]),
    ("BTC above + unscored no Hosoda",   lambda f: f["btc_regime"]=="above" and f["qs_bucket"]=="unscored (0)" and not f["hosoda"]),
    ("── baseline: BTC above (all)",     lambda f: f["btc_regime"]=="above"),
    ("── baseline: all signals",         lambda f: True),
]
for label, fn in combos:
    rets = [f["exit_return"] for f in all_f if fn(f)]
    r = row(label, rets, width=45)
    if r: print(f"  {r}")

# ══════════════════════════════════════════════════════════════════════════════
print("\n" + "=" * 72)
print("TEST E: QUALITY × KJ DISTANCE")
print("=" * 72)
print(f"\n  {'QS bucket + KJ distance':<42}  {'n':<6}  {'Avg Return':<12}  {'Win%':<8}  {'W/L'}")
print("  " + "─" * 74)

KJ_ORDER = ["below KJ", "0-3% above KJ", "3-7% above KJ",
            "7-15% above KJ", "15-30% above KJ", ">30% above KJ"]

for qb in ["60-79 (Strong)", "80-100 (Elite)", "40-59 (Solid)", "unscored (0)"]:
    for kb in KJ_ORDER:
        rets = [f["exit_return"] for f in all_f
                if f["qs_bucket"] == qb and f["kj_bucket"] == kb]
        if len(rets) < 15:
            continue
        r = row(f"QS {qb} + {kb}", rets, width=42)
        if r: print(f"  {r}")
    print()

# ══════════════════════════════════════════════════════════════════════════════
print("=" * 72)
print("TEST F: TWIST DIRECTION × QUALITY")
print("=" * 72)
print(f"\n  {'Twist + Quality':<40}  {'n':<6}  {'Avg Return':<12}  {'Win%':<8}  {'W/L'}")
print("  " + "─" * 72)

for twist in ["bearish", "bullish", "none"]:
    for qb in ["80-100 (Elite)", "60-79 (Strong)", "40-59 (Solid)", "unscored (0)"]:
        rets = [f["exit_return"] for f in all_f
                if f["twist_dir"] == twist and f["qs_bucket"] == qb]
        if len(rets) < 15:
            continue
        r = row(f"{twist} twist + QS {qb}", rets, width=40)
        if r: print(f"  {r}")
    print()

# ══════════════════════════════════════════════════════════════════════════════
print("=" * 72)
print("TEST G: SIGNAL TYPE × BTC REGIME")
print("=" * 72)
print(f"\n  {'Signal type + BTC regime':<35}  {'n':<6}  {'Avg Return':<12}  {'Win%':<8}  {'W/L'}")
print("  " + "─" * 68)

sig_types = sorted({f["signal_type"] for f in all_f})
for st in sig_types:
    for regime in ["above", "inside", "below"]:
        rets = [f["exit_return"] for f in all_f
                if f["signal_type"] == st and f["btc_regime"] == regime]
        if len(rets) < 20:
            continue
        r = row(f"Signal {st} + BTC {regime}", rets, width=35)
        if r: print(f"  {r}")
    print()

# ══════════════════════════════════════════════════════════════════════════════
print("=" * 72)
print("TEST H: KJ DISTANCE × BTC REGIME")
print("=" * 72)
print(f"\n  {'KJ distance + BTC regime':<35}  {'n':<6}  {'Avg Return':<12}  {'Win%':<8}  {'W/L'}")
print("  " + "─" * 68)

for kb in KJ_ORDER:
    for regime in ["above", "inside", "below"]:
        rets = [f["exit_return"] for f in all_f
                if f["kj_bucket"] == kb and f["btc_regime"] == regime]
        if len(rets) < 20:
            continue
        r = row(f"{kb} + BTC {regime}", rets, width=35)
        if r: print(f"  {r}")
    print()

# ══════════════════════════════════════════════════════════════════════════════
print("=" * 72)
print("TEST I: BAD COINS × BTC REGIME")
print("  (Do the consistently losing coins recover when BTC is above cloud?)")
print("=" * 72)
print(f"\n  {'Group':<35}  {'n':<6}  {'Avg Return':<12}  {'Win%':<8}  {'W/L'}")
print("  " + "─" * 68)

for regime in ["above", "inside", "below"]:
    for bad in [True, False]:
        label = f"{'Bad coins' if bad else 'Good coins'} + BTC {regime}"
        rets = [f["exit_return"] for f in all_f
                if f["bad_coin"] == bad and f["btc_regime"] == regime]
        r = row(label, rets, width=35)
        if r: print(f"  {r}")
print()

# Bad coin breakdown by name × BTC above
print(f"\n  Bad coins when BTC ABOVE cloud:")
print(f"  {'Symbol':<15}  {'n':<6}  {'Avg Return':<12}  {'Win%':<8}  {'W/L'}")
print("  " + "─" * 50)
for coin in sorted(BAD_COINS):
    rets = [f["exit_return"] for f in all_f
            if f["symbol"] == coin and f["btc_regime"] == "above"]
    r = row(coin, rets, width=15)
    if r: print(f"  {r}")

print("\n" + "=" * 72)
print("ALL INTERACTION TESTS COMPLETE")
print("=" * 72)
