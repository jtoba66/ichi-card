from __future__ import annotations

from pathlib import Path

import pandas as pd

DATA_DIR = Path(__file__).resolve().parents[3] / "data" / "ohlcv"


def _path(symbol: str, timeframe: str, exchange_id: str = "binance") -> Path:
    safe_symbol = symbol.replace("/", "")
    return DATA_DIR / f"{safe_symbol}_{exchange_id}_{timeframe}.parquet"


def load_ohlcv(symbol: str, timeframe: str, exchange_id: str = "binance") -> pd.DataFrame | None:
    p = _path(symbol, timeframe, exchange_id)
    if not p.exists():
        # Backward-compat: fall back to old path format (no exchange in name)
        old = DATA_DIR / f"{symbol.replace('/', '')}_{timeframe}.parquet"
        if old.exists():
            return pd.read_parquet(old)
        return None
    return pd.read_parquet(p)


def save_ohlcv(symbol: str, timeframe: str, df: pd.DataFrame, exchange_id: str = "binance") -> None:
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    df.to_parquet(_path(symbol, timeframe, exchange_id))
