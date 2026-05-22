"""
Extended exit strategy comparison — Signal 1 1d
Filters: ALL (score≥12), score≥13, score≥15
Strategies: A B C (original) + D E F G (new)
Equity: 5% position size, $10,000 starting capital
"""
from __future__ import annotations

import json
import sqlite3
from pathlib import Path
from typing import Optional

import numpy as np
import pandas as pd

DATA_DIR = Path("data/ohlcv")
DB_PATH  = Path("data/signals.db")
OUT_PATH = Path("data/exit_strategy_comparison2.json")

TIMEOUT      = 60
STARTING_CAP = 10_000.0
POSITION_PCT = 0.05       # 5% of current capital per trade


# ── OHLCV loading ──────────────────────────────────────────────────────────────

def load_ohlcv(symbol: str, exchange_id: str, timeframe: str) -> Optional[pd.DataFrame]:
    safe = symbol.replace("/", "")
    for path in [
        DATA_DIR / f"{safe}_{exchange_id}_{timeframe}.parquet",
        DATA_DIR / f"{safe}_{timeframe}.parquet",
    ]:
        if path.exists():
            return pd.read_parquet(path)
    for f in DATA_DIR.glob(f"{safe}_*_{timeframe}.parquet"):
        return pd.read_parquet(f)
    return None


# ── ATR14 ──────────────────────────────────────────────────────────────────────

def atr14(df: pd.DataFrame, bar_i: int) -> float:
    sub = df.iloc[max(0, bar_i - 14): bar_i + 1]
    if len(sub) < 2:
        return float("nan")
    h, l, c = sub["high"].values, sub["low"].values, sub["close"].values
    prev = np.concatenate([[c[0]], c[:-1]])
    tr = np.maximum(h - l, np.maximum(np.abs(h - prev), np.abs(l - prev)))
    a = tr[0]
    for t in tr[1:]:
        a = (a * 13 + t) / 14
    return a


# ── Exit simulators ────────────────────────────────────────────────────────────

def simulate_exit(df: pd.DataFrame, entry_bar: int, entry_price: float,
                  atr_val: float, strategy: str, bull_score: int) -> dict:
    closes = df["close"].values
    n      = len(closes)

    initial_stop = entry_price - 2.0 * atr_val

    # F: score-scaled initial stop width
    if strategy == "F":
        score_mult   = 1.0 + (bull_score - 12) * 0.25   # 12→1.0x 13→1.25x 14→1.5x 15→1.75x 16→2.0x
        initial_stop = entry_price - score_mult * atr_val

    trailing_stop = initial_stop
    highest_close = entry_price
    mfe_hit_15    = False   # for strategy E
    mae_price     = entry_price
    mfe_price     = entry_price

    for offset in range(1, TIMEOUT + 1):
        bar_i = entry_bar + offset
        if bar_i >= n:
            ep = closes[min(bar_i - 1, n - 1)]
            return _result(entry_price, ep, "DATA_END", offset, mae_price, mfe_price)

        c = closes[bar_i]
        highest_close = max(highest_close, c)
        mae_price     = min(mae_price, c)
        mfe_price     = max(mfe_price, c)

        current_mfe_pct = (mfe_price - entry_price) / entry_price * 100

        if strategy == "A":
            stop = initial_stop

        elif strategy == "B":
            new  = highest_close - 3.0 * atr_val
            trailing_stop = max(trailing_stop, new)
            stop = trailing_stop

        elif strategy == "C":
            if offset <= 10:
                stop = initial_stop
            else:
                new  = highest_close - 3.0 * atr_val
                trailing_stop = max(trailing_stop, new)
                stop = trailing_stop

        elif strategy == "D":    # COMBO_TIGHT: like C but chandelier at 2.0×
            if offset <= 10:
                stop = initial_stop
            else:
                new  = highest_close - 2.0 * atr_val
                trailing_stop = max(trailing_stop, new)
                stop = trailing_stop

        elif strategy == "E":    # MFE_TRIGGER: chandelier only after MFE > 15%
            if current_mfe_pct >= 15.0:
                mfe_hit_15 = True
            if mfe_hit_15:
                new  = highest_close - 3.0 * atr_val
                trailing_stop = max(trailing_stop, new)
                stop = trailing_stop
            else:
                stop = initial_stop

        elif strategy == "F":    # SCORE_SCALED: score-scaled stop then chandelier bar 11+
            if offset <= 10:
                stop = initial_stop
            else:
                new  = highest_close - 3.0 * atr_val
                trailing_stop = max(trailing_stop, new)
                stop = trailing_stop

        elif strategy == "G":    # PROFIT_TARGET: exit at +40% OR chandelier
            if current_mfe_pct >= 40.0 and c >= entry_price * 1.40:
                return _result(entry_price, c, "TARGET", offset, mae_price, mfe_price)
            new  = highest_close - 3.0 * atr_val
            trailing_stop = max(trailing_stop, new)
            stop = trailing_stop

        else:
            stop = initial_stop

        if c < stop:
            return _result(entry_price, c, "STOP", offset, mae_price, mfe_price)

    ep = closes[min(entry_bar + TIMEOUT, n - 1)]
    return _result(entry_price, ep, "TIMEOUT", TIMEOUT, mae_price, mfe_price)


def _result(entry, exit_p, cond, dur, mae_p, mfe_p):
    return {
        "exit_price":     exit_p,
        "exit_return":    (exit_p - entry) / entry * 100,
        "exit_condition": cond,
        "duration_bars":  dur,
        "mae":            (mae_p - entry) / entry * 100,
        "mfe":            (mfe_p - entry) / entry * 100,
    }


# ── Equity curve with fixed-fraction position sizing ──────────────────────────

def equity_stats(trades: list[dict], start: float = STARTING_CAP,
                 pos_pct: float = POSITION_PCT) -> dict:
    sorted_t = sorted(trades, key=lambda t: t["fired_at"])
    cap      = start
    peak     = cap
    max_dd   = 0.0
    dd_start = 0
    max_dd_dur = 0
    consec   = 0
    max_cons = 0

    for i, t in enumerate(sorted_t):
        ret  = t["exit_return"] / 100.0
        gain = cap * pos_pct * ret
        cap += gain

        if cap > peak:
            peak     = cap
            dd_start = i

        dd = (peak - cap) / peak * 100
        max_dd     = max(max_dd, dd)
        max_dd_dur = max(max_dd_dur, i - dd_start)

        if ret < 0:
            consec   += 1
            max_cons  = max(max_cons, consec)
        else:
            consec = 0

    return {
        "final_capital":      round(cap, 2),
        "final_return_pct":   round((cap - start) / start * 100, 2),
        "max_drawdown_pct":   round(-max_dd, 2),
        "max_dd_duration":    max_dd_dur,
        "max_consec_losses":  max_cons,
    }


# ── Stats for a list of trade results ─────────────────────────────────────────

def summarise(trades: list[dict], label: str, filter_name: str) -> dict:
    if not trades:
        return {}
    rets  = [t["exit_return"] for t in trades]
    wins  = [r for r in rets if r > 0]
    losses= [r for r in rets if r <= 0]
    wr    = len(wins) / len(rets) * 100
    avg_w = np.mean(wins)  if wins   else 0.0
    avg_l = np.mean(losses) if losses else 0.0
    wl    = avg_w / abs(avg_l) if avg_l else float("inf")
    eq    = equity_stats(trades)
    return {
        "strategy":       label,
        "filter":         filter_name,
        "n":              len(trades),
        "mean_exit_pct":  round(np.mean(rets), 2),
        "wr":             round(wr, 1),
        "wl":             round(wl, 2),
        "mae":            round(np.mean([t["mae"] for t in trades]), 2),
        "avg_bars":       round(np.mean([t["duration_bars"] for t in trades]), 1),
        **eq,
    }


# ── Main ───────────────────────────────────────────────────────────────────────

STRATEGIES = {
    "A": "ATR_ONLY",
    "B": "CHANDELIER",
    "C": "COMBINED",
    "D": "COMBO_TIGHT",
    "E": "MFE_TRIGGER",
    "F": "SCORE_SCALED",
    "G": "PROFIT_TARGET",
}

FILTERS = {
    "ALL":   0,
    "≥13":  13,
    "≥15":  15,
}


def main():
    univ = {}
    up = Path("data/universe_map.json")
    if up.exists():
        with open(up) as f:
            univ = json.load(f)

    def get_exch(sym):
        v = univ.get(sym, "binance")
        return v if isinstance(v, str) and "/" not in v else "binance"

    conn  = sqlite3.connect(DB_PATH)
    rows  = conn.execute("""
        SELECT signal_id, symbol, fired_at, entry_price, bull_score
        FROM signal_log
        WHERE signal_type=1 AND timeframe='1d' AND status='CLOSED'
        ORDER BY fired_at ASC
    """).fetchall()
    conn.close()
    print(f"Signal 1 1d CLOSED instances: {len(rows)}")

    ohlcv_cache: dict[str, pd.DataFrame | None] = {}
    raw: list[dict] = []   # one entry per instance per strategy

    skipped = 0
    for signal_id, symbol, fired_at, entry_price, bull_score in rows:
        bull_score = bull_score or 12
        exch       = get_exch(symbol)
        key        = f"{symbol}_{exch}"
        if key not in ohlcv_cache:
            ohlcv_cache[key] = load_ohlcv(symbol, exch, "1d")

        df = ohlcv_cache[key]
        if df is None:
            skipped += 1
            continue

        fired_ts = pd.Timestamp(fired_at)
        idx = df.index
        fired_ts = fired_ts.tz_convert(idx.tzinfo) if idx.tzinfo else fired_ts.tz_localize(None)

        matches = np.where(idx == fired_ts)[0]
        if len(matches) == 0:
            diffs = np.abs((idx - fired_ts).total_seconds())
            best  = int(np.argmin(diffs))
            if diffs[best] > 86400:
                skipped += 1
                continue
            entry_bar = best
        else:
            entry_bar = int(matches[0])

        if entry_bar < 14:
            skipped += 1
            continue

        atr_v = atr14(df, entry_bar)
        if np.isnan(atr_v) or atr_v <= 0:
            skipped += 1
            continue

        year = fired_ts.year
        for strat in STRATEGIES:
            r = simulate_exit(df, entry_bar, entry_price, atr_v, strat, bull_score)
            raw.append({
                "signal_id":  signal_id,
                "symbol":     symbol,
                "fired_at":   fired_at,
                "year":       year,
                "bull_score": bull_score,
                "strategy":   strat,
                **r,
            })

    print(f"Processed: {len(rows)-skipped}   Skipped: {skipped}\n")

    # ── Build result tables ────────────────────────────────────────────────────

    all_summaries = []
    # Collect trades per (strategy, filter)
    table_rows = []   # for the big comparison table

    header_line = (
        f"{'Strategy':<18} {'Filter':<6} {'N':>5} {'MeanExit%':>10} "
        f"{'WR':>7} {'W/L':>6} {'MAE':>7} {'AvgBars':>8} "
        f"{'FinalRet':>9} {'MaxDD':>8} {'MaxStreak':>10}"
    )
    separator = "-" * len(header_line)

    print("=" * len(header_line))
    print("SUMMARY: all strategies × all score filters   (5% position, $10k capital)")
    print("=" * len(header_line))
    print(header_line)
    print(separator)

    for filter_name, min_score in FILTERS.items():
        for strat, strat_name in STRATEGIES.items():
            subset = [r for r in raw if r["strategy"] == strat
                      and r["bull_score"] >= min_score]
            s = summarise(subset, f"{strat} {strat_name}", filter_name)
            if not s:
                continue
            all_summaries.append(s)
            print(
                f"{s['strategy']:<18} {s['filter']:<6} {s['n']:>5} "
                f"{s['mean_exit_pct']:>+10.1f}% {s['wr']:>6.1f}% "
                f"{s['wl']:>6.2f} {s['mae']:>+6.1f}% "
                f"{s['avg_bars']:>8.1f} "
                f"{s['final_return_pct']:>+8.1f}% "
                f"{s['max_drawdown_pct']:>+7.1f}% "
                f"{s['max_consec_losses']:>10}"
            )
        print(separator)

    # ── Per-year per-strategy (score≥13 filter) ────────────────────────────────

    print("\n")
    print("=" * 80)
    print("PER-YEAR BREAKDOWN  (score ≥ 13)")
    print("=" * 80)
    years = sorted({r["year"] for r in raw})
    strat_order = list(STRATEGIES.keys())
    col_w = 14

    header = f"{'Year':<6}" + "".join(f"{s+' '+STRATEGIES[s][:4]:>{col_w}}" for s in strat_order)
    print(header)
    print("-" * len(header))

    for yr in years:
        row_str = f"{yr:<6}"
        for strat in strat_order:
            subset = [r for r in raw if r["strategy"] == strat
                      and r["bull_score"] >= 13 and r["year"] == yr]
            if subset:
                mean_r = np.mean([r["exit_return"] for r in subset])
                row_str += f"{mean_r:>+{col_w-2}.1f}% ({len(subset):>3})"
            else:
                row_str += f"{'N/A':>{col_w}}"
        print(row_str)

    # ── MaxDD focus table at 5% ────────────────────────────────────────────────

    print("\n")
    print("=" * 70)
    print("MAX DRAWDOWN at 5% position size — key comparison")
    print("=" * 70)
    print(f"{'Strategy':<18} {'ALL':>10} {'≥13':>10} {'≥15':>10}")
    print("-" * 70)
    for strat, strat_name in STRATEGIES.items():
        cells = []
        for fn, ms in FILTERS.items():
            match = next((s for s in all_summaries
                          if s["strategy"] == f"{strat} {strat_name}"
                          and s["filter"] == fn), None)
            cells.append(f"{match['max_drawdown_pct']:>+8.1f}%" if match else "N/A")
        print(f"{strat} {strat_name:<14} {'  '.join(cells)}")

    # ── AKTUSDT 2023-07-27 ────────────────────────────────────────────────────

    akt_ts = "2023-07-27 00:00:00+00:00"
    print("\n")
    print("=" * 70)
    print("AKTUSDT 2023-07-27 — all 7 strategies")
    print("=" * 70)
    for strat, name in STRATEGIES.items():
        match = next((r for r in raw if r["strategy"] == strat
                      and r["symbol"] == "AKTUSDT" and r["fired_at"] == akt_ts), None)
        if match:
            print(f"  {strat} {name:<14}: {match['exit_return']:>+7.2f}%  "
                  f"cond={match['exit_condition']:<10} dur={match['duration_bars']:>3}bars  "
                  f"MFE={match['mfe']:>+7.2f}%")
        else:
            print(f"  {strat} {name}: not found")

    # ── Save ──────────────────────────────────────────────────────────────────

    with open(OUT_PATH, "w") as f:
        json.dump({"summaries": all_summaries, "trades": raw}, f, indent=2, default=str)
    print(f"\nFull results → {OUT_PATH}")


if __name__ == "__main__":
    main()
