"""
Exit strategy simulator — compares multiple exit rules against the same historical signals.

Each strategy is applied independently to the same entry. First condition to fire wins.

Strategies:
  A  Current live  — 2×ATR trailing stop + timeout per timeframe (no profit target)
  B  Wide trail    — 4×ATR trailing stop only, no timeout, no profit target
  C  Structural SL — hard SL at cloud bottom/kijun at entry + 4×ATR trailing
  D  Full proposed — structural SL + profit target (N×ATR) + 4×ATR trailing

Usage:
    cd ~/ichi-scorecard
    uv run python scripts/simulate_exits.py
    uv run python scripts/simulate_exits.py --min-bars 10 --signal-types 1,2,3
"""
from __future__ import annotations

import argparse
import json
import sys

# Force unbuffered output so progress shows in log files
sys.stdout.reconfigure(line_buffering=True)  # type: ignore[attr-defined]
from collections import defaultdict
from typing import Optional

import numpy as np
import pandas as pd
import psycopg2
import psycopg2.extras

# ── helpers copied from jobs.py so script is standalone ──────────────────────

def _compute_atr14(df: pd.DataFrame, bar_i: int) -> float:
    start = max(0, bar_i - 14)
    sub = df.iloc[start: bar_i + 1]
    if len(sub) < 2:
        return 0.0
    h = sub["high"].values
    l = sub["low"].values
    c = sub["close"].values
    prev_c = np.concatenate([[c[0]], c[:-1]])
    tr = np.maximum(h - l, np.maximum(np.abs(h - prev_c), np.abs(l - prev_c)))
    atr = tr[0]
    for t in tr[1:]:
        atr = (atr * 13 + t) / 14
    return float(atr)


def _pct_return(exit_p: float, entry_p: float) -> float:
    if entry_p <= 0:
        return 0.0
    return round((exit_p - entry_p) / entry_p * 100, 4)


# ── timeout per timeframe (strategy A) ───────────────────────────────────────

TIMEOUT_BARS = {"1h": 120, "4h": 90, "1d": 60, "1w": 26}

# ── profit target ATR multipliers (strategy D) ───────────────────────────────

PROFIT_TARGET_ATR = {1: 4.0, 2: 3.0, 3: 3.0, 4: 5.0, 5: 4.0, 6: 3.5, 7: 3.0, 9: 3.0}

SIGNAL_NAMES = {
    1: "Sanyaku", 2: "Balanced Breakout", 3: "KJ Break Retest",
    4: "E2E Entry", 5: "Twist Breakout", 6: "Cloud Curling",
    7: "Four-Level Retest", 9: "Chikou S/R Retest",
}

# ── structural SL calculator (strategies C, D) ───────────────────────────────

def _structural_sl(df: pd.DataFrame, entry_bar: int, signal_type: int,
                   metadata: dict, atr: float) -> Optional[float]:
    """Hard stop level calculated once at entry — based on what generated the signal."""
    try:
        cloud_bot = float(df["_cloud_bottom"].iat[entry_bar])
        kj        = float(df["kj"].iat[entry_bar])

        if signal_type in (1, 2, 5, 6):
            # Above-cloud entries — SL is cloud bottom at entry
            return cloud_bot

        if signal_type == 3:
            # KJ retest — SL is Kijun minus a small buffer
            return kj - 0.5 * atr

        if signal_type == 4:
            # E2E — entered from cloud bottom edge
            return cloud_bot

        if signal_type in (7, 9):
            # Level retest — use stored level_price if available, else kijun
            level_price = metadata.get("level_price") if isinstance(metadata, dict) else None
            if level_price:
                return float(level_price) - 0.5 * atr
            return kj - 0.5 * atr

    except Exception:
        pass
    return None


# ── per-bar simulation helpers ────────────────────────────────────────────────

def _simulate_strategy(
    df: pd.DataFrame,
    entry_bar: int,
    end_bar: int,
    entry_price: float,
    signal_type: int,
    metadata: dict,
    timeframe: str,
    strategy: str,
) -> dict:
    """
    Simulate one strategy bar-by-bar from entry_bar to end_bar.
    Returns dict with: exit_bar, exit_price, exit_return, condition, bars_held
    or None if no exit fired (still open at end_bar).
    """
    atr = _compute_atr14(df, entry_bar)
    if atr <= 0:
        return {"condition": "NO_ATR", "exit_return": None, "bars_held": None}

    # Strategy-specific setup
    if strategy == "A":
        trail_mult   = 2.0
        timeout      = TIMEOUT_BARS.get(timeframe, 60)
        profit_target = None
        struct_sl    = None

    elif strategy == "B":
        trail_mult   = 4.0
        timeout      = None
        profit_target = None
        struct_sl    = None

    elif strategy == "C":
        trail_mult   = 4.0
        timeout      = None
        profit_target = None
        struct_sl    = _structural_sl(df, entry_bar, signal_type, metadata, atr)

    elif strategy == "D":
        trail_mult   = 4.0
        timeout      = None
        pt_mult      = PROFIT_TARGET_ATR.get(signal_type, 3.0)
        profit_target = entry_price + pt_mult * atr
        struct_sl    = _structural_sl(df, entry_bar, signal_type, metadata, atr)

    else:
        raise ValueError(f"Unknown strategy {strategy!r}")

    initial_stop  = entry_price - trail_mult * atr
    trailing_stop = initial_stop
    highest_close = entry_price

    for j in range(entry_bar + 1, end_bar + 1):
        if j >= len(df):
            break

        bars = j - entry_bar
        close = float(df["close"].iat[j])

        # 1. Hard structural SL — checked first, fixed, never moves
        if struct_sl is not None and close < struct_sl:
            return {"condition": "STRUCTURAL_SL", "exit_return": _pct_return(close, entry_price),
                    "bars_held": bars, "exit_price": close}

        # 2. Profit target
        if profit_target is not None and close >= profit_target:
            return {"condition": "PROFIT_TARGET", "exit_return": _pct_return(close, entry_price),
                    "bars_held": bars, "exit_price": close}

        # 3. Trailing stop
        highest_close = max(highest_close, close)
        if bars <= 10:
            active_stop = initial_stop
        else:
            new_trail    = highest_close - trail_mult * atr
            trailing_stop = max(trailing_stop, new_trail)
            active_stop  = trailing_stop

        if close < active_stop:
            return {"condition": "TRAIL_STOP", "exit_return": _pct_return(close, entry_price),
                    "bars_held": bars, "exit_price": close}

        # 4. Timeout (strategy A only)
        if timeout is not None and bars >= timeout:
            return {"condition": "TIMEOUT", "exit_return": _pct_return(close, entry_price),
                    "bars_held": bars, "exit_price": close}

    # No exit fired — still open at end_bar
    last_close = float(df["close"].iat[min(end_bar, len(df) - 1)])
    return {"condition": "STILL_OPEN", "exit_return": _pct_return(last_close, entry_price),
            "bars_held": end_bar - entry_bar, "exit_price": last_close}


# ── statistics ────────────────────────────────────────────────────────────────

def _stats(results: list[dict]) -> dict:
    """Aggregate simulation results into summary stats."""
    closed = [r for r in results if r["condition"] != "STILL_OPEN"]
    open_  = [r for r in results if r["condition"] == "STILL_OPEN"]

    returns = [r["exit_return"] for r in results if r["exit_return"] is not None]
    closed_returns = [r["exit_return"] for r in closed if r["exit_return"] is not None]
    bars   = [r["bars_held"] for r in results if r["bars_held"] is not None]

    winners = [x for x in closed_returns if x > 0]
    losers  = [x for x in closed_returns if x <= 0]

    win_rate = len(winners) / len(closed_returns) if closed_returns else None

    mean_w  = float(np.mean(winners)) if winners else None
    mean_l  = float(np.mean(losers))  if losers  else None
    wl_ratio = abs(mean_w / mean_l) if (mean_w and mean_l) else None

    # Expected value: win_rate × avg_win + (1-win_rate) × avg_loss
    ev = None
    if win_rate is not None and mean_w and mean_l:
        ev = round(win_rate * mean_w + (1 - win_rate) * mean_l, 2)

    by_condition: dict[str, int] = defaultdict(int)
    for r in results:
        by_condition[r["condition"]] += 1

    return {
        "n": len(results),
        "n_closed": len(closed),
        "n_open": len(open_),
        "win_rate": round(win_rate, 3) if win_rate else None,
        "avg_return": round(float(np.mean(returns)), 2) if returns else None,
        "avg_win": round(mean_w, 2) if mean_w else None,
        "avg_loss": round(mean_l, 2) if mean_l else None,
        "wl_ratio": round(wl_ratio, 2) if wl_ratio else None,
        "expected_value": ev,
        "avg_bars": round(float(np.mean(bars)), 1) if bars else None,
        "by_condition": dict(by_condition),
    }


# ── printing ──────────────────────────────────────────────────────────────────

def _pct(val):
    if val is None:
        return "  —   "
    sign = "+" if val > 0 else ""
    return f"{sign}{val:.1f}%"

def _ratio(val):
    return f"{val:.2f}" if val is not None else "—"

def _rate(val):
    return f"{val*100:.1f}%" if val is not None else "—"

def _bars(val):
    return f"{val:.0f}" if val is not None else "—"


def print_comparison(all_results: dict[str, list[dict]], label: str = "ALL SIGNALS") -> None:
    strategies = ["A", "B", "C", "D"]
    names = {
        "A": "A  Current (2×ATR + timeout)",
        "B": "B  Wide trail (4×ATR only) ",
        "C": "C  Struct SL + 4×ATR       ",
        "D": "D  Full proposed (SL+PT+4×) ",
    }

    print(f"\n{'═'*90}")
    print(f"  {label}")
    print(f"{'═'*90}")
    print(f"  {'Strategy':<30} {'N':>5}  {'Win%':>6}  {'Avg Ret':>8}  {'Avg Win':>8}  {'Avg Loss':>9}  {'W/L':>5}  {'EV':>7}  {'Bars':>5}")
    print(f"  {'─'*30} {'─'*5}  {'─'*6}  {'─'*8}  {'─'*8}  {'─'*9}  {'─'*5}  {'─'*7}  {'─'*5}")

    for s in strategies:
        if s not in all_results or not all_results[s]:
            continue
        st = _stats(all_results[s])
        print(
            f"  {names[s]:<30} {st['n']:>5}  {_rate(st['win_rate']):>6}  "
            f"{_pct(st['avg_return']):>8}  {_pct(st['avg_win']):>8}  "
            f"{_pct(st['avg_loss']):>9}  {_ratio(st['wl_ratio']):>5}  "
            f"{_pct(st['expected_value']):>7}  {_bars(st['avg_bars']):>5}"
        )

    # Show how trades exited under each strategy
    print(f"\n  Exit breakdown:")
    for s in strategies:
        if s not in all_results:
            continue
        st = _stats(all_results[s])
        parts = ", ".join(f"{k}: {v}" for k, v in sorted(st["by_condition"].items(), key=lambda x: -x[1]))
        print(f"  {names[s][:2]}  {parts}")


# ── main ──────────────────────────────────────────────────────────────────────

def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--min-bars", type=int, default=15,
                        help="Minimum bars since entry to include a signal (default 15)")
    parser.add_argument("--signal-types", type=str, default="",
                        help="Comma-separated signal types to include, e.g. 1,2,3 (default: all)")
    parser.add_argument("--max-signals", type=int, default=0,
                        help="Cap total signals processed (0 = no cap, for quick tests)")
    args = parser.parse_args()

    filter_types = set()
    if args.signal_types:
        filter_types = {int(x) for x in args.signal_types.split(",")}

    import os
    db_url = os.environ.get("ICHI_DATABASE_URL", "postgresql://ichi:ichi@localhost/ichi_signals")
    conn = psycopg2.connect(db_url)
    conn.autocommit = True

    print("Loading signals from database...")
    with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
        where = ""
        if filter_types:
            placeholders = ",".join(str(t) for t in filter_types)
            where = f"WHERE signal_type IN ({placeholders})"
        cur.execute(f"""
            SELECT signal_id, signal_type, symbol, timeframe,
                   fired_at, entry_price, signal_metadata, bull_score
            FROM signal_log
            {where}
            ORDER BY fired_at ASC
        """)
        signals = [dict(r) for r in cur.fetchall()]
    conn.close()

    if args.max_signals:
        signals = signals[:args.max_signals]

    print(f"  {len(signals)} signals loaded. Grouping by (symbol, timeframe)...")

    # Group by (symbol, timeframe) so we fetch OHLCV once per pair
    from collections import defaultdict
    by_sym_tf: dict[tuple, list] = defaultdict(list)
    for sig in signals:
        by_sym_tf[(sig["symbol"], sig["timeframe"])].append(sig)

    print(f"  {len(by_sym_tf)} unique (symbol, timeframe) pairs — fetching OHLCV...")

    from ichi.data.fetcher import fetch_ohlcv
    from ichi.indicators.ichimoku import ichimoku
    from ichi.signal.jobs import _find_bar_by_timestamp

    # Precompute columns needed (cloud top/bottom, etc.)
    from ichi.indicators.precompute import precompute

    # Results: strategy → list of outcome dicts
    all_results: dict[str, list] = {s: [] for s in ["A", "B", "C", "D"]}
    by_type_results: dict[int, dict[str, list]] = {}

    processed = skipped = fetch_errors = 0
    total_pairs = len(by_sym_tf)

    for idx, ((symbol, timeframe), sigs) in enumerate(by_sym_tf.items()):
        pair = symbol.replace("USDT", "/USDT")
        try:
            df = fetch_ohlcv(pair, timeframe)
            df = ichimoku(df)
            df = precompute(df)
            current_bar = len(df) - 1
        except Exception as exc:
            fetch_errors += 1
            if fetch_errors <= 5:
                print(f"  [fetch error] {symbol} {timeframe}: {exc}")
            continue

        if idx % 20 == 0:
            print(f"  [{idx+1}/{total_pairs}] fetched {symbol} {timeframe}  "
                  f"({processed} signals processed so far)")

        for sig in sigs:
            entry_bar = _find_bar_by_timestamp(df, sig["fired_at"])
            if entry_bar is None:
                skipped += 1
                continue

            bars_available = current_bar - entry_bar
            if bars_available < args.min_bars:
                skipped += 1
                continue

            entry_price = float(sig["entry_price"])
            if entry_price <= 0:
                skipped += 1
                continue

            try:
                meta = json.loads(sig["signal_metadata"] or "{}")
            except Exception:
                meta = {}

            sig_type = int(sig["signal_type"])

            for strategy in ["A", "B", "C", "D"]:
                result = _simulate_strategy(
                    df, entry_bar, current_bar,
                    entry_price, sig_type, meta,
                    timeframe, strategy,
                )
                all_results[strategy].append(result)

                if sig_type not in by_type_results:
                    by_type_results[sig_type] = {s: [] for s in ["A", "B", "C", "D"]}
                by_type_results[sig_type][strategy].append(result)

            processed += 1

    print(f"\n  Done. Processed: {processed}  Skipped: {skipped}  Fetch errors: {fetch_errors}")

    # ── Print results ─────────────────────────────────────────────────────────
    print_comparison(all_results, f"ALL SIGNAL TYPES  (n={processed})")

    for sig_type in sorted(by_type_results.keys()):
        name = SIGNAL_NAMES.get(sig_type, f"Signal {sig_type}")
        n = len(by_type_results[sig_type].get("A", []))
        if n < 5:
            continue
        print_comparison(by_type_results[sig_type], f"Signal {sig_type}: {name}  (n={n})")

    print(f"\n{'═'*90}")
    print("  Strategy key:")
    print("    A  Current live  — 2×ATR trailing stop + timeout per timeframe")
    print("    B  Wide trail    — 4×ATR trailing only, no timeout")
    print("    C  Structural SL — hard stop at cloud bottom/kijun at entry + 4×ATR trail")
    print("    D  Full proposed — structural SL + profit target (N×ATR) + 4×ATR trail")
    print(f"{'═'*90}\n")


if __name__ == "__main__":
    main()
