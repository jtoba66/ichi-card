"""
Pre-Implementation Checks
==========================
1. Alpha decay check — does 2025 decline persist within BTC above + QS 60+?
2. Signal frequency — how many signals survive per week after stacking filters?
3. Weekly (1w) timeframe signals — do same filters apply?

Run on HP:
    cd ~/ichi-scorecard
    uv run python scripts/pre_implementation_checks.py
"""
from __future__ import annotations

import os
import sys
from collections import defaultdict
from datetime import datetime, timezone, timedelta

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

def row(label, rets, width=42):
    if not rets or len(rets) < 5:
        return None
    avg, win_pct, wl = stats(rets)
    return f"  {label:<{width}}  n={len(rets):<5}  avg={_pct(avg):<12}  win={win_pct}%  W/L={wl}"

def header(title):
    print("\n" + "=" * 72)
    print(title)
    print("=" * 72)

BAD_COINS = {"BATUSDT", "EIGENUSDT", "SFPUSDT", "FFUSDT", "APEUSDT", "XMRUSDT"}

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
    closed = [dict(r) for r in cur.fetchall()]

    # Also load ALL signals (open + closed) for frequency test
    cur.execute("""
        SELECT signal_id, signal_type, symbol, timeframe, fired_at,
               quality_score, hosoda_active
        FROM signal_log
        WHERE is_backfill = 1
        ORDER BY fired_at ASC
    """)
    all_signals = [dict(r) for r in cur.fetchall()]
conn.close()
print(f"  {len(closed)} closed signals, {len(all_signals)} total signals loaded.\n")

from ichi.data.fetcher import fetch_ohlcv
from ichi.indicators.ichimoku import ichimoku
from ichi.signal.jobs import _find_bar_by_timestamp

print("Loading BTC/USDT 1d...")
btc_1d = ichimoku(fetch_ohlcv("BTC/USDT", "1d"))

def btc_regime(fired_at):
    bar = _find_bar_by_timestamp(btc_1d, fired_at)
    if bar is None or bar < 52:
        return "unknown"
    close = float(btc_1d["close"].iat[bar])
    top = float(max(btc_1d["span_a"].iat[bar], btc_1d["span_b"].iat[bar]))
    bot = float(min(btc_1d["span_a"].iat[bar], btc_1d["span_b"].iat[bar]))
    if close > top:  return "above"
    if close < bot:  return "below"
    return "inside"

def qs_tier(qs):
    if qs is None or qs == 0: return "unscored"
    if qs >= 60: return "QS 60+"
    if qs >= 40: return "QS 40-59"
    return "QS <40"

def get_year(fired_at):
    try:
        dt = datetime.fromisoformat(fired_at.replace(" ", "T"))
        return str(dt.year)
    except Exception:
        return "unknown"

def get_week(fired_at):
    try:
        dt = datetime.fromisoformat(fired_at.replace(" ", "T"))
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        # ISO week key: "2024-W03"
        return dt.strftime("%Y-W%W")
    except Exception:
        return None

# ── Build feature per closed signal ──────────────────────────────────────────
print("Computing BTC regime per signal...")
for sig in closed:
    sig["_regime"]  = btc_regime(sig["fired_at"])
    sig["_year"]    = get_year(sig["fired_at"])
    sig["_qs_tier"] = qs_tier(sig["quality_score"])
    sig["_bad"]     = sig["symbol"] in BAD_COINS
    sig["_hosoda"]  = bool(sig["hosoda_active"])

# Also for all signals (for frequency)
for sig in all_signals:
    sig["_regime"]  = btc_regime(sig["fired_at"])
    sig["_qs_tier"] = qs_tier(sig["quality_score"])
    sig["_bad"]     = sig["symbol"] in BAD_COINS
    sig["_hosoda"]  = bool(sig["hosoda_active"])
    sig["_week"]    = get_week(sig["fired_at"])
    sig["_year"]    = get_year(sig["fired_at"])

print("  Done.\n")

# ══════════════════════════════════════════════════════════════════════════════
header("CHECK 1: ALPHA DECAY — Does 2025 drop persist within top filters?")

print(f"\n  Year × BTC regime × Quality tier:")
print(f"  {'Year + Regime + QS':<42}  {'n':<6}  {'Avg Return':<12}  {'Win%':<8}  {'W/L'}")
print("  " + "─" * 75)

for year in ["2023", "2024", "2025", "2026"]:
    printed = False
    for regime in ["above", "inside", "below"]:
        for tier in ["QS 60+", "QS 40-59", "unscored"]:
            rets = [float(s["exit_return"]) for s in closed
                    if s["_year"] == year and s["_regime"] == regime and s["_qs_tier"] == tier]
            if len(rets) < 20:
                continue
            r = row(f"{year} + BTC {regime} + {tier}", rets, width=42)
            if r:
                print(r)
                printed = True
    if printed:
        print()

# Summary: just top filter by year
print(f"\n  Summary — BTC above + QS 60+ by year:")
print(f"  {'Year':<10}  {'n':<6}  {'Avg Return':<12}  {'Win%':<8}  {'W/L'}")
print("  " + "─" * 55)
for year in ["2023", "2024", "2025", "2026"]:
    rets = [float(s["exit_return"]) for s in closed
            if s["_year"] == year and s["_regime"] == "above" and s["_qs_tier"] == "QS 60+"]
    r = row(year, rets, width=10)
    if r: print(r)

print(f"\n  Summary — ALL signals by year (baseline):")
print(f"  {'Year':<10}  {'n':<6}  {'Avg Return':<12}  {'Win%':<8}  {'W/L'}")
print("  " + "─" * 55)
for year in ["2023", "2024", "2025", "2026"]:
    rets = [float(s["exit_return"]) for s in closed if s["_year"] == year]
    r = row(year, rets, width=10)
    if r: print(r)

# ══════════════════════════════════════════════════════════════════════════════
header("CHECK 2: SIGNAL FREQUENCY — How many signals survive per week?")

# Define filter tiers
filter_tiers = [
    ("No filter (all signals)",
     lambda s: True),
    ("BTC above cloud",
     lambda s: s["_regime"] == "above"),
    ("BTC above + no bad coin",
     lambda s: s["_regime"] == "above" and not s["_bad"]),
    ("BTC above + QS 60+",
     lambda s: s["_regime"] == "above" and s["_qs_tier"] == "QS 60+"),
    ("BTC above + QS 60+ + no bad coin",
     lambda s: s["_regime"] == "above" and s["_qs_tier"] == "QS 60+" and not s["_bad"]),
    ("BTC above + QS 60+ + Hosoda",
     lambda s: s["_regime"] == "above" and s["_qs_tier"] == "QS 60+" and s["_hosoda"]),
    ("BTC above + QS 60+ + Hosoda + no bad coin",
     lambda s: s["_regime"] == "above" and s["_qs_tier"] == "QS 60+" and s["_hosoda"] and not s["_bad"]),
]

# Use all signals (not just closed) for frequency to get full picture
# Count unique weeks in the dataset
all_weeks = sorted({s["_week"] for s in all_signals if s["_week"]})
n_weeks = len(all_weeks)

print(f"\n  Dataset spans {n_weeks} weeks ({all_weeks[0]} → {all_weeks[-1]})")
print(f"\n  {'Filter':<45}  {'Total':<8}  {'Per week':<10}  {'Weeks active'}")
print("  " + "─" * 75)

for label, fn in filter_tiers:
    matching = [s for s in all_signals if fn(s)]
    weeks_with_signals = len({s["_week"] for s in matching if s["_week"]})
    per_week = round(len(matching) / n_weeks, 1) if n_weeks else 0
    active_pct = round(100 * weeks_with_signals / n_weeks, 0) if n_weeks else 0
    print(f"  {label:<45}  {len(matching):<8}  {per_week:<10}  {active_pct}% of weeks")

# Frequency by year for top filter
print(f"\n  BTC above + QS 60+ + no bad coin — signals per week by year:")
print(f"  {'Year':<8}  {'Total signals':<16}  {'Weeks':<8}  {'Per week'}")
print("  " + "─" * 50)
for year in ["2023", "2024", "2025", "2026"]:
    matching = [s for s in all_signals
                if s["_year"] == year
                and s["_regime"] == "above"
                and s["_qs_tier"] == "QS 60+"
                and not s["_bad"]]
    year_weeks = len({s["_week"] for s in all_signals if s["_year"] == year and s["_week"]})
    per_week = round(len(matching) / year_weeks, 1) if year_weeks else 0
    print(f"  {year:<8}  {len(matching):<16}  {year_weeks:<8}  {per_week}/week")

# ══════════════════════════════════════════════════════════════════════════════
header("CHECK 3: WEEKLY (1w) TIMEFRAME SIGNALS")

weekly = [s for s in closed if s["timeframe"] == "1w"]
print(f"\n  {len(weekly)} closed 1w signals found.\n")

if not weekly:
    print("  No 1w signals — skipping.")
else:
    # Basic stats
    rets_all = [float(s["exit_return"]) for s in weekly]
    avg, win_pct, wl = stats(rets_all)
    print(f"  Overall 1w: n={len(weekly)}  avg={_pct(avg)}  win={win_pct}%  W/L={wl}\n")

    # Signal type breakdown
    print(f"  By signal type:")
    print(f"  {'Type':<12}  {'n':<6}  {'Avg Return':<12}  {'Win%':<8}  {'W/L'}")
    print("  " + "─" * 52)
    for st in sorted({s["signal_type"] for s in weekly}):
        rets = [float(s["exit_return"]) for s in weekly if s["signal_type"] == st]
        r = row(f"Signal {st}", rets, width=12)
        if r: print(r)

    # BTC regime
    print(f"\n  By BTC 1d regime:")
    print(f"  {'Regime':<20}  {'n':<6}  {'Avg Return':<12}  {'Win%':<8}  {'W/L'}")
    print("  " + "─" * 55)
    for regime in ["above", "inside", "below"]:
        rets = [float(s["exit_return"]) for s in weekly if s["_regime"] == regime]
        r = row(f"BTC {regime}", rets, width=20)
        if r: print(r)

    # Quality
    print(f"\n  By quality tier:")
    print(f"  {'QS tier':<20}  {'n':<6}  {'Avg Return':<12}  {'Win%':<8}  {'W/L'}")
    print("  " + "─" * 55)
    for tier in ["QS 60+", "QS 40-59", "unscored"]:
        rets = [float(s["exit_return"]) for s in weekly if s["_qs_tier"] == tier]
        r = row(tier, rets, width=20)
        if r: print(r)

    # BTC × Quality
    print(f"\n  BTC above + QS 60+ (1w only):")
    rets = [float(s["exit_return"]) for s in weekly
            if s["_regime"] == "above" and s["_qs_tier"] == "QS 60+"]
    if rets:
        avg, win_pct, wl = stats(rets)
        print(f"  n={len(rets)}  avg={_pct(avg)}  win={win_pct}%  W/L={wl}")
    else:
        print("  Too few signals.")

    # Year breakdown for 1w
    print(f"\n  By year:")
    print(f"  {'Year':<8}  {'n':<6}  {'Avg Return':<12}  {'Win%':<8}  {'W/L'}")
    print("  " + "─" * 50)
    for year in ["2023", "2024", "2025", "2026"]:
        rets = [float(s["exit_return"]) for s in weekly if s["_year"] == year]
        r = row(year, rets, width=8)
        if r: print(r)

    # Hosoda on 1w
    print(f"\n  Hosoda on 1w signals:")
    for hosoda in [True, False]:
        rets = [float(s["exit_return"]) for s in weekly if s["_hosoda"] == hosoda]
        label = "Hosoda" if hosoda else "No Hosoda"
        r = row(label, rets, width=15)
        if r: print(r)

print("\n" + "=" * 72)
print("ALL PRE-IMPLEMENTATION CHECKS COMPLETE")
print("=" * 72)
