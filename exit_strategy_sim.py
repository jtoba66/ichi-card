"""
Exit strategy comparison: Signal 1 1d CLOSED instances
Three strategies: ATR_ONLY, CHANDELIER, COMBINED
"""
from __future__ import annotations

import json
import sqlite3
from pathlib import Path
from typing import Optional

import numpy as np
import pandas as pd

DATA_DIR = Path("data/ohlcv")
DB_PATH = Path("data/signals.db")
OUT_PATH = Path("data/exit_strategy_comparison.json")

# ── Helpers ────────────────────────────────────────────────────────────────────

def load_ohlcv(symbol: str, exchange_id: str, timeframe: str) -> Optional[pd.DataFrame]:
    safe = symbol.replace("/", "")
    p = DATA_DIR / f"{safe}_{exchange_id}_{timeframe}.parquet"
    if p.exists():
        return pd.read_parquet(p)
    old = DATA_DIR / f"{safe}_{timeframe}.parquet"
    if old.exists():
        return pd.read_parquet(old)
    # Try any exchange suffix
    for f in DATA_DIR.glob(f"{safe}_*_{timeframe}.parquet"):
        return pd.read_parquet(f)
    return None


def atr14(df: pd.DataFrame, bar_i: int) -> float:
    """Wilder ATR(14) at bar_i using bars [bar_i-14, bar_i]."""
    start = max(0, bar_i - 14)
    sub = df.iloc[start : bar_i + 1]
    if len(sub) < 2:
        return float("nan")
    high = sub["high"].values
    low = sub["low"].values
    close = sub["close"].values
    prev_close = np.concatenate([[close[0]], close[:-1]])
    tr = np.maximum(high - low, np.maximum(np.abs(high - prev_close), np.abs(low - prev_close)))
    # Wilder smoothing
    atr = tr[0]
    for t in tr[1:]:
        atr = (atr * 13 + t) / 14
    return atr


def simulate_exit(df: pd.DataFrame, entry_bar: int, entry_price: float,
                   atr_val: float, strategy: str, timeout: int = 60):
    """
    Simulate exit for one trade from entry_bar+1 forward.
    Returns dict with exit_bar, exit_price, exit_return, exit_condition,
    duration_bars, mae, mfe.
    """
    closes = df["close"].values
    n = len(closes)

    initial_stop = entry_price - 2.0 * atr_val
    trailing_stop = initial_stop  # for chandelier / combined

    lowest_close = entry_price
    highest_close = entry_price
    mae_price = entry_price
    mfe_price = entry_price

    for bar_offset in range(1, timeout + 1):
        bar_i = entry_bar + bar_offset
        if bar_i >= n:
            # ran out of data — treat as timeout exit at last bar
            exit_price = closes[min(bar_i - 1, n - 1)]
            exit_cond = "DATA_END"
            return _make_result(entry_price, exit_price, exit_cond, bar_offset,
                                mae_price, mfe_price)

        c = closes[bar_i]
        lowest_close = min(lowest_close, c)
        highest_close = max(highest_close, c)
        mae_price = min(mae_price, c)
        mfe_price = max(mfe_price, c)

        if strategy == "A":
            stop = initial_stop
        elif strategy == "B":
            new_stop = highest_close - 3.0 * atr_val
            trailing_stop = max(trailing_stop, new_stop)
            stop = trailing_stop
        else:  # COMBINED
            if bar_offset <= 10:
                stop = initial_stop
            else:
                new_stop = highest_close - 3.0 * atr_val
                trailing_stop = max(trailing_stop, new_stop)
                stop = trailing_stop

        if c < stop:
            return _make_result(entry_price, c, "STOP", bar_offset,
                                mae_price, mfe_price)

    # timeout
    bar_i = entry_bar + timeout
    exit_price = closes[min(bar_i, n - 1)]
    return _make_result(entry_price, exit_price, "TIMEOUT", timeout,
                        mae_price, mfe_price)


def _make_result(entry, exit_p, cond, dur, mae_p, mfe_p):
    exit_ret = (exit_p - entry) / entry * 100
    mae = (mae_p - entry) / entry * 100
    mfe = (mfe_p - entry) / entry * 100
    return {
        "exit_price": exit_p,
        "exit_return": exit_ret,
        "exit_condition": cond,
        "duration_bars": dur,
        "mae": mae,
        "mfe": mfe,
    }


# ── Equity simulation ──────────────────────────────────────────────────────────

def equity_stats(trades: list[dict]) -> dict:
    """Sequential $1000/trade compounding; max_dd, max_consec_losses."""
    sorted_trades = sorted(trades, key=lambda t: t["fired_at"])
    equity = 1000.0
    peak = equity
    max_dd = 0.0
    consec = 0
    max_consec = 0
    dd_start = 0
    max_dd_dur = 0

    for i, t in enumerate(sorted_trades):
        ret = t["exit_return"] / 100.0
        equity *= (1 + ret)
        if equity > peak:
            peak = equity
            dd_start = i
        dd = (peak - equity) / peak * 100
        max_dd = max(max_dd, dd)
        max_dd_dur = max(max_dd_dur, i - dd_start)

        if ret < 0:
            consec += 1
            max_consec = max(max_consec, consec)
        else:
            consec = 0

    final_ret = (equity - 1000.0) / 1000.0 * 100
    return {
        "final_return_pct": round(final_ret, 2),
        "max_drawdown_pct": round(-max_dd, 2),
        "max_consec_losses": max_consec,
        "max_dd_duration_trades": max_dd_dur,
    }


# ── Main ───────────────────────────────────────────────────────────────────────

def main():
    # Load universe map for exchange lookup
    universe_map = {}
    um_path = Path("data/universe_map.json")
    if um_path.exists():
        with open(um_path) as f:
            universe_map = json.load(f)

    def get_exchange(sym):
        return universe_map.get(sym, universe_map.get(sym.replace("USDT", "/USDT"), "binance"))

    # Load Signal 1 1d CLOSED instances
    conn = sqlite3.connect(DB_PATH)
    rows = conn.execute("""
        SELECT signal_id, symbol, fired_at, entry_price
        FROM signal_log
        WHERE signal_type=1 AND timeframe='1d' AND status='CLOSED'
        ORDER BY fired_at ASC
    """).fetchall()
    conn.close()

    print(f"Loaded {len(rows)} Signal 1 1d CLOSED instances")

    results = {"A": [], "B": [], "C": []}
    skipped = 0
    processed = 0

    # Track symbols we've already loaded to avoid re-reading parquet
    ohlcv_cache: dict[str, pd.DataFrame | None] = {}

    for signal_id, symbol, fired_at, entry_price in rows:
        # Find exchange
        exch = get_exchange(symbol)
        if isinstance(exch, str) and "/" in exch:
            exch = "binance"

        cache_key = f"{symbol}_{exch}"
        if cache_key not in ohlcv_cache:
            ohlcv_cache[cache_key] = load_ohlcv(symbol, exch, "1d")

        df = ohlcv_cache[cache_key]
        if df is None:
            skipped += 1
            continue

        # Find entry bar index by matching fired_at timestamp
        fired_ts = pd.Timestamp(fired_at)
        idx = df.index
        if idx.tzinfo is None:
            fired_ts = fired_ts.tz_localize(None)
        else:
            fired_ts = fired_ts.tz_convert(idx.tzinfo)

        matches = np.where(idx == fired_ts)[0]
        if len(matches) == 0:
            # Try nearest within 1 day
            diffs = np.abs((idx - fired_ts).total_seconds())
            best = np.argmin(diffs)
            if diffs[best] > 86400:
                skipped += 1
                continue
            entry_bar = int(best)
        else:
            entry_bar = int(matches[0])

        # Need at least 14 bars before entry for ATR
        if entry_bar < 14:
            skipped += 1
            continue

        atr_val = atr14(df, entry_bar)
        if np.isnan(atr_val) or atr_val <= 0:
            skipped += 1
            continue

        year = fired_ts.year

        for strat in ("A", "B", "C"):
            r = simulate_exit(df, entry_bar, entry_price, atr_val, strat)
            r["signal_id"] = signal_id
            r["symbol"] = symbol
            r["fired_at"] = fired_at
            r["year"] = year
            results[strat].append(r)

        processed += 1

    print(f"Processed: {processed}  Skipped: {skipped}")

    # ── Summary stats ──────────────────────────────────────────────────────────

    strat_labels = {"A": "A ATR_ONLY", "B": "B CHANDELIER", "C": "C COMBINED"}

    summary_rows = []
    for strat, label in strat_labels.items():
        trades = results[strat]
        if not trades:
            continue
        rets = [t["exit_return"] for t in trades]
        wins = [r for r in rets if r > 0]
        losses = [r for r in rets if r <= 0]
        wr = len(wins) / len(rets) * 100 if rets else 0
        avg_win = np.mean(wins) if wins else 0
        avg_loss = np.mean(losses) if losses else 0
        wl = avg_win / abs(avg_loss) if avg_loss != 0 else float("inf")
        mae_vals = [t["mae"] for t in trades]
        avg_bars = np.mean([t["duration_bars"] for t in trades])
        eq = equity_stats(trades)
        summary_rows.append({
            "label": label,
            "n": len(trades),
            "mean_exit_pct": round(np.mean(rets), 2),
            "wr": round(wr, 1),
            "wl": round(wl, 2),
            "mae": round(np.mean(mae_vals), 2),
            "avg_bars": round(avg_bars, 1),
            "max_dd": eq["max_drawdown_pct"],
            "max_streak": eq["max_consec_losses"],
        })

    print("\n" + "=" * 90)
    print(f"{'Strategy':<15} {'N':>5} {'MeanExit%':>10} {'WR':>7} {'W/L':>6} {'MAE':>7} {'AvgBars':>8} {'MaxDD':>8} {'MaxStreak':>10}")
    print("-" * 90)
    for r in summary_rows:
        print(f"{r['label']:<15} {r['n']:>5} {r['mean_exit_pct']:>+10.1f}% {r['wr']:>6.1f}% {r['wl']:>6.2f} {r['mae']:>+6.1f}% {r['avg_bars']:>8.1f} {r['max_dd']:>+7.1f}% {r['max_streak']:>10}")

    # ── Per-year breakdown ─────────────────────────────────────────────────────

    years = sorted({t["year"] for t in results["A"]})
    print("\n" + "=" * 70)
    print(f"{'Year':<6} {'Strat-A MeanExit%':>18} {'Strat-B MeanExit%':>18} {'Strat-C MeanExit%':>18}")
    print("-" * 70)
    year_data = {}
    for yr in years:
        row = {"year": yr}
        for strat in ("A", "B", "C"):
            yr_trades = [t for t in results[strat] if t["year"] == yr]
            if yr_trades:
                row[strat] = round(np.mean([t["exit_return"] for t in yr_trades]), 2)
                row[f"{strat}_n"] = len(yr_trades)
            else:
                row[strat] = None
        year_data[yr] = row
        a = f"{row['A']:+.1f}% (n={row.get('A_n',0)})" if row["A"] is not None else "N/A"
        b = f"{row['B']:+.1f}% (n={row.get('B_n',0)})" if row["B"] is not None else "N/A"
        c = f"{row['C']:+.1f}% (n={row.get('C_n',0)})" if row["C"] is not None else "N/A"
        print(f"{yr:<6} {a:>18} {b:>18} {c:>18}")

    # ── AKTUSDT 2023-07-27 specific ────────────────────────────────────────────

    print("\n" + "=" * 70)
    print("AKTUSDT 2023-07-27 trade detail (signal_id: SIG1_AKTUSDT_1d_1690416000)")
    print("-" * 70)
    akt_ts = "2023-07-27 00:00:00+00:00"
    for strat, label in strat_labels.items():
        matches = [t for t in results[strat]
                   if t["symbol"] == "AKTUSDT" and t["fired_at"] == akt_ts]
        if matches:
            t = matches[0]
            print(f"  {label}: exit={t['exit_return']:+.2f}%  cond={t['exit_condition']}  dur={t['duration_bars']}bars  MFE={t['mfe']:+.2f}%  MAE={t['mae']:+.2f}%")
        else:
            print(f"  {label}: not found")

    # ── Save full results ──────────────────────────────────────────────────────

    OUT_PATH.parent.mkdir(exist_ok=True)
    with open(OUT_PATH, "w") as f:
        json.dump({
            "summary": summary_rows,
            "per_year": {str(k): v for k, v in year_data.items()},
            "trades_A": results["A"],
            "trades_B": results["B"],
            "trades_C": results["C"],
        }, f, indent=2, default=str)
    print(f"\nFull results saved to {OUT_PATH}")


if __name__ == "__main__":
    main()
