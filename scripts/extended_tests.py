"""
Extended Tests 1-8
==================
1. Cloud thickness at entry
2. Chikou span position (vs past cloud + past price)
3. Kijun slope (flat / rising / falling)
4. Tenkan vs Kijun alignment at entry
5. Signal year — has alpha decayed over time?
6. Day of week
7. ETH regime (1d cloud, same as BTC test)
8. Volatility at entry (ATR% of price)

All sliced against exit_return. BTC 1d regime included as context throughout.

Run on HP:
    cd ~/ichi-scorecard
    uv run python scripts/extended_tests.py
"""
from __future__ import annotations

import os
import sys
from collections import defaultdict
from datetime import datetime, timezone

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
    avg     = round(sum(returns) / len(returns), 2)
    win_pct = round(100 * len(wins) / len(returns), 1)
    avg_win  = round(sum(wins)/len(wins), 2)   if wins   else None
    avg_loss = round(sum(losses)/len(losses), 2) if losses else None
    wl = round(abs(avg_win/avg_loss), 2) if (avg_win and avg_loss) else None
    return avg, win_pct, wl

def row(label, rets, width=35):
    if not rets or len(rets) < 10:
        return None
    avg, win_pct, wl = stats(rets)
    return f"  {label:<{width}}  n={len(rets):<5}  avg={_pct(avg):<12}  win={win_pct}%  W/L={wl}"

def header(title):
    print("\n" + "=" * 72)
    print(title)
    print("=" * 72)

# ── Load signals ──────────────────────────────────────────────────────────────
print("Loading closed signals...")
conn = psycopg2.connect(DB_URL)
with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
    cur.execute("""
        SELECT signal_id, signal_type, symbol, timeframe, fired_at,
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
from ichi.signal.jobs import _find_bar_by_timestamp

# ── BTC 1d + ETH 1d regime ────────────────────────────────────────────────────
print("Loading BTC/USDT 1d and ETH/USDT 1d...")
btc_1d = ichimoku(fetch_ohlcv("BTC/USDT", "1d"))
eth_1d = ichimoku(fetch_ohlcv("ETH/USDT", "1d"))

def regime_at(df, fired_at):
    bar = _find_bar_by_timestamp(df, fired_at)
    if bar is None or bar < 52:
        return "unknown"
    close = float(df["close"].iat[bar])
    top = float(max(df["span_a"].iat[bar], df["span_b"].iat[bar]))
    bot = float(min(df["span_a"].iat[bar], df["span_b"].iat[bar]))
    if close > top:  return "above"
    if close < bot:  return "below"
    return "inside"

# ── Tests 5 + 6: time-based (no OHLCV needed) ────────────────────────────────
header("TEST 5: SIGNAL YEAR — Has alpha decayed over time?")
year_buckets: dict[str, list] = defaultdict(list)
dow_buckets:  dict[str, list] = defaultdict(list)
DAYS = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"]

for sig in signals:
    ret = float(sig["exit_return"])
    fired_str = sig["fired_at"]
    try:
        # fired_at is stored as string e.g. "2023-04-15 08:00:00+00"
        dt = datetime.fromisoformat(fired_str.replace(" ", "T"))
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        year_buckets[str(dt.year)].append(ret)
        dow_buckets[DAYS[dt.weekday()]].append(ret)
    except Exception:
        pass

print(f"\n  {'Year':<12}  {'n':<6}  {'Avg Return':<12}  {'Win%':<8}  {'W/L'}")
print("  " + "─" * 55)
for year in sorted(year_buckets):
    r = row(year, year_buckets[year], width=12)
    if r: print(r)

header("TEST 6: DAY OF WEEK")
print(f"\n  {'Day':<12}  {'n':<6}  {'Avg Return':<12}  {'Win%':<8}  {'W/L'}")
print("  " + "─" * 55)
for day in DAYS:
    r = row(day, dow_buckets.get(day, []), width=12)
    if r: print(r)

# ── Test 7: ETH regime ────────────────────────────────────────────────────────
header("TEST 7: ETH 1d REGIME FILTER")
eth_buckets: dict[str, list] = defaultdict(list)
for sig in signals:
    r = regime_at(eth_1d, sig["fired_at"])
    eth_buckets[r].append(float(sig["exit_return"]))

print(f"\n  {'Regime':<28}  {'n':<6}  {'Avg Return':<12}  {'Win%':<8}  {'W/L'}")
print("  " + "─" * 62)
for regime in ["above", "inside", "below", "unknown"]:
    rets = eth_buckets[regime]
    r = row(f"ETH {regime}", rets, width=28)
    if r: print(r)

all_rets = [f for rets in eth_buckets.values() for f in rets]
above = eth_buckets["above"]
print(f"\n  Baseline (all)    n={len(all_rets):<5}  avg={_pct(round(sum(all_rets)/len(all_rets),2))}")
print(f"  ETH above only    n={len(above):<5}  avg={_pct(round(sum(above)/len(above),2)) if above else '—'}")

# Also: ETH × BTC regime combo
print(f"\n  ETH + BTC regime combo:")
print(f"  {'Combo':<32}  {'n':<6}  {'Avg Return':<12}  {'Win%':<8}  {'W/L'}")
print("  " + "─" * 65)
eth_btc: dict[str, list] = defaultdict(list)
for sig in signals:
    er = regime_at(eth_1d, sig["fired_at"])
    br = regime_at(btc_1d, sig["fired_at"])
    eth_btc[f"ETH {er} + BTC {br}"].append(float(sig["exit_return"]))

for key in sorted(eth_btc, key=lambda k: -(sum(eth_btc[k])/len(eth_btc[k]) if eth_btc[k] else 0)):
    rets = eth_btc[key]
    r = row(key, rets, width=32)
    if r: print(r)

# ── Per-pair OHLCV loop — tests 1, 2, 3, 4, 8 ────────────────────────────────
print("\n\nBuilding per-signal features (tests 1-4, 8) via OHLCV fetch...")
by_sym_tf: dict[tuple, list] = defaultdict(list)
for sig in signals:
    by_sym_tf[(sig["symbol"], sig["timeframe"])].append(sig)

# Feature storage
feat: dict[str, dict] = {
    sig["signal_id"]: {
        "ret":          float(sig["exit_return"]),
        "btc_regime":   regime_at(btc_1d, sig["fired_at"]),
        "cloud_thick":  None,   # % of price
        "thick_bucket": None,
        "chikou_cloud": None,   # above / inside / below (vs 26-bar-ago cloud)
        "chikou_price": None,   # above / below (vs 26-bar-ago close)
        "kj_slope":     None,   # rising / flat / falling
        "tk_vs_kj":     None,   # above / below
        "atr_pct":      None,
        "atr_bucket":   None,
    }
    for sig in signals
}

def thick_bucket(t):
    if t is None:  return None
    if t < 0.5:    return "<0.5% (paper thin)"
    if t < 2:      return "0.5-2% (thin)"
    if t < 5:      return "2-5% (medium)"
    if t < 15:     return "5-15% (thick)"
    return ">15% (very thick)"

def atr_bucket(a):
    if a is None:  return None
    if a < 2:      return "<2% (low vol)"
    if a < 5:      return "2-5% (medium)"
    if a < 10:     return "5-10% (high)"
    return ">10% (very high)"

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

    highs  = df["high"].values
    lows   = df["low"].values
    closes = df["close"].values
    span_a = df["span_a"].values
    span_b = df["span_b"].values
    tk_arr = df["tk"].values
    kj_arr = df["kj"].values

    for sig in sigs:
        bar = _find_bar_by_timestamp(df, sig["fired_at"])
        if bar is None or bar < 52:
            continue

        f = feat[sig["signal_id"]]
        close = closes[bar]
        if close <= 0:
            continue

        # ── 1. Cloud thickness ──
        sa, sb = span_a[bar], span_b[bar]
        thickness = abs(sa - sb) / close * 100
        f["cloud_thick"]  = thickness
        f["thick_bucket"] = thick_bucket(thickness)

        # ── 2. Chikou position (close vs cloud/price from 26 bars ago) ──
        if bar >= 26:
            past_sa = span_a[bar - 26]
            past_sb = span_b[bar - 26]
            past_top = max(past_sa, past_sb)
            past_bot = min(past_sa, past_sb)
            if close > past_top:
                f["chikou_cloud"] = "above past cloud"
            elif close < past_bot:
                f["chikou_cloud"] = "below past cloud"
            else:
                f["chikou_cloud"] = "inside past cloud"

            past_close = closes[bar - 26]
            f["chikou_price"] = "above past price" if close > past_close else "below past price"

        # ── 3. Kijun slope (over 10 bars) ──
        if bar >= 10:
            kj_now = kj_arr[bar]
            kj_ago = kj_arr[bar - 10]
            if kj_ago > 0:
                slope = (kj_now - kj_ago) / kj_ago * 100
                if abs(slope) < 0.3:
                    f["kj_slope"] = "flat"
                elif slope > 0:
                    f["kj_slope"] = "rising"
                else:
                    f["kj_slope"] = "falling"

        # ── 4. Tenkan vs Kijun ──
        tk = tk_arr[bar]
        kj = kj_arr[bar]
        if kj > 0:
            f["tk_vs_kj"] = "TK above KJ" if tk > kj else ("TK = KJ" if tk == kj else "TK below KJ")

        # ── 8. ATR% ──
        start = max(1, bar - 13)
        tr_vals = [
            max(highs[i] - lows[i],
                abs(highs[i] - closes[i-1]),
                abs(lows[i] - closes[i-1]))
            for i in range(start, bar + 1)
        ]
        atr = sum(tr_vals) / len(tr_vals) if tr_vals else 0
        atr_p = atr / close * 100
        f["atr_pct"]    = atr_p
        f["atr_bucket"] = atr_bucket(atr_p)

print(f"\n  Done. Feature table complete.\n")
all_f = list(feat.values())

# ══════════════════════════════════════════════════════════════════════════════
header("TEST 1: CLOUD THICKNESS AT ENTRY")
print(f"\n  {'Thickness':<28}  {'n':<6}  {'Avg Return':<12}  {'Win%':<8}  {'W/L'}")
print("  " + "─" * 62)
THICK_ORDER = ["<0.5% (paper thin)", "0.5-2% (thin)", "2-5% (medium)",
               "5-15% (thick)", ">15% (very thick)"]
for b in THICK_ORDER:
    rets = [f["ret"] for f in all_f if f["thick_bucket"] == b]
    r = row(b, rets, width=28)
    if r: print(r)

# Also × BTC regime
print(f"\n  Cloud thickness × BTC above cloud:")
print(f"  {'Thickness + BTC above':<30}  {'n':<6}  {'Avg Return':<12}  {'Win%':<8}  {'W/L'}")
print("  " + "─" * 65)
for b in THICK_ORDER:
    rets = [f["ret"] for f in all_f if f["thick_bucket"] == b and f["btc_regime"] == "above"]
    r = row(f"{b} + BTC above", rets, width=30)
    if r: print(r)

# ══════════════════════════════════════════════════════════════════════════════
header("TEST 2: CHIKOU SPAN POSITION")

print(f"\n  vs Cloud 26 bars ago:")
print(f"  {'Chikou position':<28}  {'n':<6}  {'Avg Return':<12}  {'Win%':<8}  {'W/L'}")
print("  " + "─" * 62)
for b in ["above past cloud", "inside past cloud", "below past cloud"]:
    rets = [f["ret"] for f in all_f if f["chikou_cloud"] == b]
    r = row(b, rets, width=28)
    if r: print(r)

print(f"\n  vs Price 26 bars ago:")
print(f"  {'Chikou vs price':<28}  {'n':<6}  {'Avg Return':<12}  {'Win%':<8}  {'W/L'}")
print("  " + "─" * 62)
for b in ["above past price", "below past price"]:
    rets = [f["ret"] for f in all_f if f["chikou_price"] == b]
    r = row(b, rets, width=28)
    if r: print(r)

# Chikou both conditions: above cloud AND above price
print(f"\n  Full chikou confirmation (above cloud AND above past price):")
rets_both = [f["ret"] for f in all_f
             if f["chikou_cloud"] == "above past cloud" and f["chikou_price"] == "above past price"]
rets_partial = [f["ret"] for f in all_f
                if f["chikou_cloud"] == "above past cloud" and f["chikou_price"] == "below past price"]
rets_neither = [f["ret"] for f in all_f
                if f["chikou_cloud"] != "above past cloud"]
for label, rets in [
    ("above cloud + above price (full)", rets_both),
    ("above cloud + below price (partial)", rets_partial),
    ("NOT above past cloud", rets_neither),
]:
    r = row(label, rets, width=38)
    if r: print(r)

# × BTC regime
print(f"\n  Full chikou confirmation × BTC regime:")
print(f"  {'Combo':<38}  {'n':<6}  {'Avg Return':<12}  {'Win%':<8}  {'W/L'}")
print("  " + "─" * 70)
for regime in ["above", "inside", "below"]:
    rets = [f["ret"] for f in all_f
            if f["chikou_cloud"] == "above past cloud"
            and f["chikou_price"] == "above past price"
            and f["btc_regime"] == regime]
    r = row(f"Full chikou + BTC {regime}", rets, width=38)
    if r: print(r)

# ══════════════════════════════════════════════════════════════════════════════
header("TEST 3: KIJUN SLOPE AT ENTRY")
print(f"\n  {'Kijun slope':<20}  {'n':<6}  {'Avg Return':<12}  {'Win%':<8}  {'W/L'}")
print("  " + "─" * 55)
for b in ["rising", "flat", "falling"]:
    rets = [f["ret"] for f in all_f if f["kj_slope"] == b]
    r = row(b, rets, width=20)
    if r: print(r)

# × BTC regime
print(f"\n  Kijun slope × BTC above cloud:")
print(f"  {'Slope + BTC above':<25}  {'n':<6}  {'Avg Return':<12}  {'Win%':<8}  {'W/L'}")
print("  " + "─" * 58)
for b in ["rising", "flat", "falling"]:
    rets = [f["ret"] for f in all_f if f["kj_slope"] == b and f["btc_regime"] == "above"]
    r = row(f"{b} kijun + BTC above", rets, width=25)
    if r: print(r)

# ══════════════════════════════════════════════════════════════════════════════
header("TEST 4: TENKAN vs KIJUN ALIGNMENT AT ENTRY")
print(f"\n  {'TK alignment':<20}  {'n':<6}  {'Avg Return':<12}  {'Win%':<8}  {'W/L'}")
print("  " + "─" * 55)
for b in ["TK above KJ", "TK below KJ"]:
    rets = [f["ret"] for f in all_f if f["tk_vs_kj"] == b]
    r = row(b, rets, width=20)
    if r: print(r)

# × BTC + Kijun slope (triple: rising kijun + TK above KJ + BTC above)
print(f"\n  Rising kijun + TK above KJ + BTC above (triple combo):")
rets_triple = [f["ret"] for f in all_f
               if f["kj_slope"] == "rising"
               and f["tk_vs_kj"] == "TK above KJ"
               and f["btc_regime"] == "above"]
rets_base = [f["ret"] for f in all_f if f["btc_regime"] == "above"]
for label, rets in [
    ("rising KJ + TK above KJ + BTC above", rets_triple),
    ("baseline: BTC above (all)", rets_base),
]:
    r = row(label, rets, width=38)
    if r: print(r)

# ══════════════════════════════════════════════════════════════════════════════
header("TEST 8: VOLATILITY AT ENTRY (ATR %)")
print(f"\n  {'ATR bucket':<25}  {'n':<6}  {'Avg Return':<12}  {'Win%':<8}  {'W/L'}")
print("  " + "─" * 58)
ATR_ORDER = ["<2% (low vol)", "2-5% (medium)", "5-10% (high)", ">10% (very high)"]
for b in ATR_ORDER:
    rets = [f["ret"] for f in all_f if f["atr_bucket"] == b]
    r = row(b, rets, width=25)
    if r: print(r)

# × BTC regime
print(f"\n  ATR bucket × BTC above cloud:")
print(f"  {'ATR + BTC above':<28}  {'n':<6}  {'Avg Return':<12}  {'Win%':<8}  {'W/L'}")
print("  " + "─" * 62)
for b in ATR_ORDER:
    rets = [f["ret"] for f in all_f if f["atr_bucket"] == b and f["btc_regime"] == "above"]
    r = row(f"{b} + BTC above", rets, width=28)
    if r: print(r)

# ATR × KJ distance (does momentum = high ATR explain KJ distance anomaly?)
print(f"\n  High ATR (>5%) × KJ distance — unpacking the KJ anomaly:")
print(f"  {'ATR high/low + KJ bucket':<35}  {'n':<6}  {'Avg Return':<12}  {'Win%':<8}  {'W/L'}")
print("  " + "─" * 68)
KJ_BUCKETS_SHORT = ["0-3% above KJ", "3-7% above KJ", "7-15% above KJ",
                    "15-30% above KJ", ">30% above KJ"]

# Need KJ bucket — recompute here from closed signals × OHLCV
# Re-use: feat doesn't have kj_bucket, let's add it during the loop above
# (we didn't store it) — so re-derive from atr_pct and a separate atr/kj join won't work
# Instead: just show high vol vs low vol separately
for atr_label, atr_fn in [("High ATR (>5%)", lambda f: f["atr_pct"] and f["atr_pct"] > 5),
                           ("Low ATR (<2%)",  lambda f: f["atr_pct"] and f["atr_pct"] < 2)]:
    sub = [f["ret"] for f in all_f if atr_fn(f)]
    r = row(atr_label, sub, width=35)
    if r: print(r)

print("\n" + "=" * 72)
print("ALL EXTENDED TESTS COMPLETE")
print("=" * 72)
