"""Chikou S/R level library — Signal 9 dependency.

Derives significant support/resistance levels from historical chikou span
peaks and troughs (which map to price swing highs/lows). Levels are stored
in the chikou_levels SQLite table and used by detect_signal_9().

Key design: levels are built incrementally up to bar i during backfill so
there is no lookahead bias. For live use, build_chikou_levels() can be
called on the full history and the table rebuilt periodically (weekly).
"""
from __future__ import annotations

import sqlite3
from datetime import datetime, timezone
from typing import Optional

import pandas as pd

from ichi.signal.detector import DB_PATH


# ── Level derivation ──────────────────────────────────────────────────────────

def _derive_levels(df: pd.DataFrame, symbol: str, timeframe: str,
                   up_to_bar: Optional[int] = None) -> list[dict]:
    """
    Derive S/R levels from swing high/low pivots in df up to (and including)
    bar `up_to_bar`. When None, uses the full dataframe.

    Each level requires ≥2 touches or ≥26 bars of duration to qualify.
    """
    end = (up_to_bar + 1) if up_to_bar is not None else len(df)
    sub = df.iloc[:end]

    swing_high_idx = list(sub.index[sub["_swing_high"] == True])
    swing_low_idx  = list(sub.index[sub["_swing_low"]  == True])

    levels: list[dict] = []
    now = datetime.now(timezone.utc).isoformat()

    for raw_idx in swing_high_idx + swing_low_idx:
        # Convert label-index to integer position within sub
        pos = sub.index.get_loc(raw_idx)
        level_price = float(sub["close"].iat[pos])
        if level_price <= 0:
            continue

        touch_count = 0
        first_bar = pos
        last_bar = pos

        scan_end = min(pos + 200, end)
        for j in range(pos, scan_end):
            current = float(sub["close"].iat[j])
            if abs(current - level_price) / level_price <= 0.01:
                touch_count += 1
                last_bar = j
            # Level broken when price closes >3% through it
            if j > pos + 5 and (current > level_price * 1.03 or current < level_price * 0.97):
                break

        duration_bars = last_bar - first_bar
        if touch_count < 2 and duration_bars < 26:
            continue

        significance_score = touch_count * max(duration_bars, 1)
        level_type = "SWING_HIGH" if raw_idx in swing_high_idx else "SWING_LOW"

        levels.append({
            "symbol": symbol,
            "timeframe": timeframe,
            "level_price": level_price,
            "first_bar": first_bar,
            "last_bar": last_bar,
            "touch_count": touch_count,
            "duration_bars": duration_bars,
            "significance_score": significance_score,
            "level_type": level_type,
            "last_updated": now,
        })

    return levels


# ── Public API ────────────────────────────────────────────────────────────────

def build_chikou_levels(df: pd.DataFrame, symbol: str, timeframe: str) -> list[dict]:
    """Build the full level library for a symbol/tf from the complete history."""
    return _derive_levels(df, symbol, timeframe, up_to_bar=None)


def update_chikou_levels_to_bar(df: pd.DataFrame, i: int, symbol: str,
                                 timeframe: str,
                                 cache: list[dict]) -> list[dict]:
    """
    Incremental version for backfill: rebuild levels up to bar i and append
    any new ones to `cache`. Returns the updated cache list.
    Used to avoid lookahead bias — the detector at bar i can only see levels
    derived from bars 0..i.
    """
    current_prices = {round(l["level_price"], 8) for l in cache}
    new_levels = _derive_levels(df, symbol, timeframe, up_to_bar=i)
    for lv in new_levels:
        if round(lv["level_price"], 8) not in current_prices:
            cache.append(lv)
            current_prices.add(round(lv["level_price"], 8))
    return cache


def save_chikou_levels(levels: list[dict]) -> int:
    """Upsert a list of level dicts into the chikou_levels table.

    Uses INSERT OR REPLACE keyed on (symbol, timeframe, level_price rounded
    to 8 significant figures). Returns number of rows written.
    """
    if not levels:
        return 0
    conn = sqlite3.connect(DB_PATH)
    try:
        conn.execute("DELETE FROM chikou_levels WHERE symbol = ? AND timeframe = ?",
                     (levels[0]["symbol"], levels[0]["timeframe"]))
        conn.executemany(
            """
            INSERT INTO chikou_levels
            (symbol, timeframe, level_price, first_bar, last_bar,
             touch_count, duration_bars, significance_score, level_type, last_updated)
            VALUES (?,?,?,?,?,?,?,?,?,?)
            """,
            [
                (lv["symbol"], lv["timeframe"], lv["level_price"],
                 lv["first_bar"], lv["last_bar"], lv["touch_count"],
                 lv["duration_bars"], lv["significance_score"],
                 lv["level_type"], lv["last_updated"])
                for lv in levels
            ],
        )
        conn.commit()
        return len(levels)
    finally:
        conn.close()


def rebuild_levels_for(symbol: str, timeframe: str,
                        df: Optional[pd.DataFrame] = None) -> int:
    """Convenience: fetch+precompute if df not provided, then rebuild table."""
    if df is None:
        from ichi.data.fetcher import fetch_ohlcv
        from ichi.indicators.ichimoku import ichimoku
        from ichi.indicators.precompute import precompute
        df = fetch_ohlcv(symbol.replace("USDT", "/USDT"), timeframe)
        df = ichimoku(df)
        df = precompute(df)
    levels = build_chikou_levels(df, symbol, timeframe)
    return save_chikou_levels(levels)
