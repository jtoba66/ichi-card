"""
Rule IC (Information Coefficient) Analysis
==========================================
For each signal type × timeframe combination, re-runs all 18 scoring rules
at the entry bar of every historical signal and correlates each rule's
firing (1/0) with the actual exit_return outcome.

This tells you which rules actually PREDICT good outcomes vs which are noise.

Output per (signal_type, timeframe):
  - Rule name
  - % of signals where it fired
  - Avg return when fired vs NOT fired
  - IC (Pearson correlation with exit_return)
  - Verdict: PREDICTIVE / NOISE / HARMFUL

Usage:
    cd ~/ichi-scorecard
    uv run python scripts/rule_ic_analysis.py
    uv run python scripts/rule_ic_analysis.py --min-signals 30 --signal-types 1,5
"""
from __future__ import annotations

import argparse
import sys
from collections import defaultdict

import numpy as np
import pandas as pd
import psycopg2
import psycopg2.extras

sys.stdout.reconfigure(line_buffering=True)  # type: ignore[attr-defined]

SIGNAL_NAMES = {
    1: "Sanyaku", 2: "Balanced Breakout", 3: "KJ Break Retest",
    4: "E2E Entry", 5: "Twist Breakout", 6: "Cloud Curling",
    7: "Four-Level Retest", 9: "Chikou S/R Retest",
}


def _pearson_ic(x: list[float], y: list[float]) -> float:
    """Pearson correlation between binary rule vector and return vector."""
    if len(x) < 5:
        return 0.0
    try:
        xa, ya = np.array(x, dtype=float), np.array(y, dtype=float)
        if xa.std() == 0 or ya.std() == 0:
            return 0.0
        return float(np.corrcoef(xa, ya)[0, 1])
    except Exception:
        return 0.0


def _verdict(ic: float, fired_pct: float) -> str:
    """Human verdict on a rule's usefulness."""
    if abs(ic) < 0.03:
        return "NOISE"
    if ic >= 0.10:
        return "★★ STRONG"
    if ic >= 0.05:
        return "★ USEFUL"
    if ic > 0.02:
        return "weak+"
    if ic <= -0.05:
        return "✗ HARMFUL"
    return "weak-"


def print_ic_table(
    rule_ids: list[str],
    results: dict[str, dict],   # rule_id → {fired: [], returns_fired: [], returns_not: []}
    exit_returns: list[float],
    label: str,
    n: int,
) -> None:
    print(f"\n{'═'*80}")
    print(f"  {label}  (n={n})")
    print(f"{'═'*80}")
    print(f"  {'Rule':<22} {'Fired%':>7}  {'AvgRet↑':>8}  {'AvgRet↓':>8}  {'Lift':>7}  {'IC':>7}  Verdict")
    print(f"  {'─'*22} {'─'*7}  {'─'*8}  {'─'*8}  {'─'*7}  {'─'*7}  {'─'*10}")

    rows = []
    for rid in rule_ids:
        d = results.get(rid)
        if d is None:
            continue
        fired_vec   = d["fired"]
        ret_fired   = d["ret_fired"]
        ret_not     = d["ret_not"]

        ic          = _pearson_ic(fired_vec, exit_returns)
        fired_pct   = 100 * sum(fired_vec) / len(fired_vec) if fired_vec else 0
        avg_fired   = float(np.mean(ret_fired)) if ret_fired else None
        avg_not     = float(np.mean(ret_not))   if ret_not   else None
        lift        = (avg_fired - avg_not) if (avg_fired is not None and avg_not is not None) else None
        rows.append((rid, fired_pct, avg_fired, avg_not, lift, ic))

    # Sort by IC descending
    rows.sort(key=lambda r: -r[5])

    for rid, fired_pct, avg_fired, avg_not, lift, ic in rows:
        verdict = _verdict(ic, fired_pct)

        def fmt(v):
            if v is None: return "   —   "
            sign = "+" if v > 0 else ""
            return f"{sign}{v:.2f}%"

        ic_str = f"{ic:+.3f}"
        print(
            f"  {rid:<22} {fired_pct:>6.1f}%  {fmt(avg_fired):>8}  {fmt(avg_not):>8}  "
            f"{fmt(lift):>7}  {ic_str:>7}  {verdict}"
        )

    # Summary: which rules to keep/drop
    strong  = [r[0] for r in rows if r[5] >= 0.05]
    harmful = [r[0] for r in rows if r[5] <= -0.05]
    noise   = [r[0] for r in rows if abs(r[5]) < 0.03]

    print(f"\n  KEEP  ({len(strong)}): {', '.join(strong) or 'none'}")
    print(f"  DROP  ({len(harmful)+len(noise)}): harmful=[{', '.join(harmful)}]  noise=[{', '.join(noise[:5])}{'...' if len(noise)>5 else ''}]")


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--min-signals", type=int, default=30,
                        help="Min signals per (type, timeframe) to include (default 30)")
    parser.add_argument("--signal-types", type=str, default="",
                        help="Comma-separated signal types, e.g. 1,5 (default: all)")
    args = parser.parse_args()

    filter_types: set[int] = set()
    if args.signal_types:
        filter_types = {int(x) for x in args.signal_types.split(",")}

    import os
    db_url = os.environ.get("ICHI_DATABASE_URL", "postgresql://ichi:ichi@localhost/ichi_signals")
    conn = psycopg2.connect(db_url)

    print("Loading closed signals from database...")
    with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
        where = "WHERE status='CLOSED' AND exit_return IS NOT NULL"
        if filter_types:
            placeholders = ",".join(str(t) for t in filter_types)
            where += f" AND signal_type IN ({placeholders})"
        cur.execute(f"""
            SELECT signal_id, signal_type, symbol, timeframe,
                   fired_at, entry_price, exit_return
            FROM signal_log
            {where}
            ORDER BY fired_at ASC
        """)
        signals = [dict(r) for r in cur.fetchall()]
    conn.close()

    print(f"  {len(signals)} closed signals loaded.")

    # Group by (signal_type, timeframe)
    groups: dict[tuple, list] = defaultdict(list)
    for sig in signals:
        groups[(sig["signal_type"], sig["timeframe"])].append(sig)

    # Build per-pair fetch map
    by_sym_tf: dict[tuple, list] = defaultdict(list)
    for sig in signals:
        by_sym_tf[(sig["symbol"], sig["timeframe"])].append(sig)

    print(f"  {len(by_sym_tf)} unique (symbol, timeframe) pairs to process.")

    from ichi.data.fetcher import fetch_ohlcv
    from ichi.indicators.ichimoku import ichimoku
    from ichi.indicators.precompute import precompute
    from ichi.rules.registry import RuleRegistry
    from ichi.scoring.engine import evaluate
    from ichi.signal.jobs import _find_bar_by_timestamp

    registry = RuleRegistry.canonical()
    rule_ids = [r.rule_id for r in registry.all_rules]

    # Data store: (signal_type, timeframe) → rule_id → {fired, ret_fired, ret_not}
    # Also store exit_returns per group for IC calculation
    group_data: dict[tuple, dict] = {}       # key → {rule_id: {fired:[], ret_fired:[], ret_not:[]}}
    group_returns: dict[tuple, list] = {}    # key → [exit_returns]

    processed = skipped = fetch_errors = 0
    total = len(by_sym_tf)

    for idx, ((symbol, timeframe), sigs) in enumerate(by_sym_tf.items()):
        if idx % 20 == 0:
            print(f"  [{idx+1}/{total}] {symbol} {timeframe}  ({processed} processed so far)")

        try:
            pair = symbol.replace("USDT", "/USDT")
            df = fetch_ohlcv(pair, timeframe)
            df = ichimoku(df)
            df = precompute(df)
        except Exception as exc:
            fetch_errors += 1
            if fetch_errors <= 3:
                print(f"  [fetch error] {symbol} {timeframe}: {exc}")
            skipped += len(sigs)
            continue

        for sig in sigs:
            entry_bar = _find_bar_by_timestamp(df, sig["fired_at"])
            if entry_bar is None or entry_bar < 1:
                skipped += 1
                continue

            exit_return = sig["exit_return"]
            if exit_return is None:
                skipped += 1
                continue

            # Run all 18 rules at entry bar
            try:
                scorecard = evaluate(df, entry_bar, registry)
            except Exception:
                skipped += 1
                continue

            fired_map = {r.rule_id: (1 if r.qualifies_bull else 0) for r in scorecard.rules}

            key = (int(sig["signal_type"]), timeframe)
            if key not in group_data:
                group_data[key] = {rid: {"fired": [], "ret_fired": [], "ret_not": []} for rid in rule_ids}
                group_returns[key] = []

            group_returns[key].append(float(exit_return))

            for rid in rule_ids:
                fired = fired_map.get(rid, 0)
                group_data[key][rid]["fired"].append(fired)
                if fired:
                    group_data[key][rid]["ret_fired"].append(float(exit_return))
                else:
                    group_data[key][rid]["ret_not"].append(float(exit_return))

            processed += 1

    print(f"\n  Done. Processed: {processed}  Skipped: {skipped}  Fetch errors: {fetch_errors}")

    # ── Print results per (signal_type, timeframe) ────────────────────────────
    timeframe_order = ["1w", "1d", "4h", "1h"]

    for sig_type in sorted(SIGNAL_NAMES.keys()):
        if filter_types and sig_type not in filter_types:
            continue
        name = SIGNAL_NAMES[sig_type]

        for tf in timeframe_order:
            key = (sig_type, tf)
            if key not in group_data:
                continue
            n = len(group_returns[key])
            if n < args.min_signals:
                continue

            print_ic_table(
                rule_ids,
                group_data[key],
                group_returns[key],
                f"Signal {sig_type}: {name} · {tf}",
                n,
            )

    print(f"\n{'═'*80}")
    print("  IC guide:  ≥0.10 = strong predictor  |  0.05-0.10 = useful  |")
    print("             <0.03 = noise (both +/-)   |  ≤-0.05 = harmful")
    print(f"{'═'*80}\n")


if __name__ == "__main__":
    main()
