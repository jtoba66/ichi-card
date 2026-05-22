from __future__ import annotations

import time
from datetime import datetime, timezone

import ccxt
import pandas as pd

from ichi.data.cache import load_ohlcv, save_ohlcv
from ichi.data.universe import get_exchange_for

_THREE_YEARS_MS = 3 * 365 * 24 * 60 * 60 * 1000
_COLUMNS = ["timestamp", "open", "high", "low", "close", "volume"]


def _make_exchange(exchange_id: str) -> ccxt.Exchange:
    exchange_class = getattr(ccxt, exchange_id)
    return exchange_class({"enableRateLimit": True, "timeout": 30000})  # 30s hard timeout


def _fetch_all(
    exchange: ccxt.Exchange,
    symbol: str,
    timeframe: str,
    since_ms: int,
) -> pd.DataFrame:
    """Fetch all candles from since_ms to now, paginating as needed."""
    all_candles: list[list[float]] = []
    retries = 3

    while True:
        for attempt in range(retries):
            try:
                candles = exchange.fetch_ohlcv(symbol, timeframe, since=since_ms, limit=1000)
                break
            except Exception as exc:
                if "does not have market symbol" in str(exc) or isinstance(exc, ccxt.BadSymbol):
                    return pd.DataFrame(columns=_COLUMNS[1:])
                if attempt == retries - 1:
                    raise
                time.sleep(2 ** attempt)

        if not candles:
            break
        all_candles.extend(candles)
        last_ts = int(candles[-1][0])
        if last_ts < since_ms or len(candles) < 1000:
            break
        since_ms = last_ts + 1

    if not all_candles:
        return pd.DataFrame(columns=_COLUMNS[1:])

    df = pd.DataFrame(all_candles, columns=_COLUMNS)
    df["timestamp"] = pd.to_datetime(df["timestamp"], unit="ms", utc=True)
    df = df.set_index("timestamp").sort_index()
    df = df[~df.index.duplicated(keep="last")]
    return df


def fetch_ohlcv(
    symbol: str,
    timeframe: str,
    exchange_id: str | None = None,
) -> pd.DataFrame:
    """Fetch OHLCV from exchange, using local parquet cache for incremental updates.

    If exchange_id is None, looks up the exchange from the universe map (defaults to binance).
    Returns DataFrame indexed by UTC timestamp with columns: open, high, low, close, volume.
    """
    if exchange_id is None:
        exchange_id = get_exchange_for(symbol)

    exchange = _make_exchange(exchange_id)
    existing = load_ohlcv(symbol, timeframe, exchange_id)

    if existing is not None and not existing.empty:
        last_ts = existing.index[-1]
        since_ms = int(last_ts.timestamp() * 1000) + 1
    else:
        since_ms = int(datetime.now(tz=timezone.utc).timestamp() * 1000) - _THREE_YEARS_MS

    new_data = _fetch_all(exchange, symbol, timeframe, since_ms)

    if new_data.empty:
        return existing if existing is not None else new_data

    if existing is not None and not existing.empty:
        combined = pd.concat([existing, new_data])
        combined = combined[~combined.index.duplicated(keep="last")].sort_index()
    else:
        combined = new_data

    save_ohlcv(symbol, timeframe, combined, exchange_id)
    return combined
