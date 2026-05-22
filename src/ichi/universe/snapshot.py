from __future__ import annotations

import logging
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import date

import pandas as pd

from ichi.data.fetcher import fetch_ohlcv
from ichi.indicators.ichimoku import ichimoku
from ichi.indicators.precompute import precompute
from ichi.rules.registry import RuleRegistry
from ichi.scoring.engine import Scorecard, evaluate

logger = logging.getLogger(__name__)

_COLUMNS = [
    "symbol", "timeframe", "date",
    "bull_score", "bear_score", "grade", "chikou_angle",
    "fwd_return_1d", "fwd_return_7d", "fwd_return_30d",
]


def _score_symbol(
    symbol: str,
    timeframe: str,
    registry: RuleRegistry,
    start: date,
    end: date,
) -> pd.DataFrame:
    """Compute daily scorecard rows for one symbol over [start, end]."""
    try:
        df = fetch_ohlcv(symbol, timeframe)
    except Exception as exc:
        logger.warning("Failed to fetch %s %s: %s", symbol, timeframe, exc)
        return pd.DataFrame(columns=_COLUMNS)

    if df.empty or len(df) < 60:
        return pd.DataFrame(columns=_COLUMNS)

    df = ichimoku(df)
    precompute(df)   # bake expensive derived series into columns once per symbol

    # Restrict to date range
    mask = (df.index.date >= start) & (df.index.date <= end)
    indices = [i for i, in_range in enumerate(mask) if in_range]

    rows = []
    for i in indices:
        try:
            sc: Scorecard = evaluate(df, i, registry)
        except Exception as exc:
            logger.debug("Rule eval error at %s %s bar %d: %s", symbol, timeframe, i, exc)
            continue

        close_now = df["close"].iat[i]

        def fwd_return(n: int) -> float | None:
            j = i + n
            if j >= len(df):
                return None
            future_close = df["close"].iat[j]
            return (future_close - close_now) / close_now

        rows.append({
            "symbol": symbol,
            "timeframe": timeframe,
            "date": df.index[i].date(),
            "bull_score": sc.bull_score,
            "bear_score": sc.bear_score,
            "grade": sc.grade,
            "chikou_angle": sc.chikou_angle_val,
            "fwd_return_1d": fwd_return(1),
            "fwd_return_7d": fwd_return(7),
            "fwd_return_30d": fwd_return(30),
        })

    return pd.DataFrame(rows, columns=_COLUMNS) if rows else pd.DataFrame(columns=_COLUMNS)


def build_snapshot(
    symbols: list[str],
    timeframe: str,
    start: date,
    end: date,
    max_workers: int = 5,
) -> pd.DataFrame:
    """Score all symbols over [start, end] and return a flat DataFrame.

    Runs symbol fetches in parallel (max_workers) but evaluates rules sequentially
    per symbol to avoid contention on shared state.
    """
    registry = RuleRegistry.canonical()
    frames: list[pd.DataFrame] = []

    with ThreadPoolExecutor(max_workers=max_workers) as pool:
        futures = {
            pool.submit(_score_symbol, sym, timeframe, registry, start, end): sym
            for sym in symbols
        }
        for fut in as_completed(futures):
            sym = futures[fut]
            try:
                result = fut.result()
                if not result.empty:
                    frames.append(result)
                    logger.info("Scored %s: %d rows", sym, len(result))
            except Exception as exc:
                logger.warning("Snapshot error for %s: %s", sym, exc)

    if not frames:
        return pd.DataFrame(columns=_COLUMNS)

    snapshot = pd.concat(frames, ignore_index=True)
    snapshot = snapshot.sort_values(["symbol", "date"]).reset_index(drop=True)
    return snapshot
