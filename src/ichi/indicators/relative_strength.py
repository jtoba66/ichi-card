"""Relative strength of a coin vs BTC over multiple lookback periods."""
from __future__ import annotations

import pandas as pd


def relative_strength(
    coin_df: pd.DataFrame,
    btc_df: pd.DataFrame,
    periods: list[int] | None = None,
) -> dict[str, float]:
    """Compute coin return relative to BTC over multiple periods.

    Returns a dict keyed by period label:
        rs_7d   — 7-day excess return vs BTC
        rs_14d  — 14-day
        rs_30d  — 30-day
        rs_score — composite: +1 per period outperforming, 0 to 3

    Interpretation:
        coin_ret > btc_ret → outperforming (positive RS)
        coin_ret > 0 while btc_ret < 0 → holding while BTC dumps (strongest)
        rs_score = 3 → outperforming on all three timeframes
    """
    if periods is None:
        periods = [7, 14, 30]

    close_coin = coin_df["close"]
    close_btc = btc_df["close"]

    result: dict[str, float] = {}
    score = 0

    for p in periods:
        if len(close_coin) < p + 1 or len(close_btc) < p + 1:
            result[f"rs_{p}d"] = float("nan")
            continue

        coin_ret = (close_coin.iloc[-1] - close_coin.iloc[-p - 1]) / close_coin.iloc[-p - 1]
        btc_ret = (close_btc.iloc[-1] - close_btc.iloc[-p - 1]) / close_btc.iloc[-p - 1]

        # Excess return: how much coin outperformed BTC
        rs = coin_ret - btc_ret
        result[f"rs_{p}d"] = round(float(rs) * 100, 2)  # expressed as percentage points

        if coin_ret > btc_ret:
            score += 1

    result["rs_score"] = score
    return result


def rs_label(rs_7d: float, rs_14d: float) -> str:
    """Human-readable relative strength label based on 7d and 14d RS."""
    if rs_7d > 10 and rs_14d > 10:
        return "STRONG↑"
    if rs_7d > 5 or rs_14d > 5:
        return "leading"
    if rs_7d > 0 and rs_14d > 0:
        return "keeping up"
    if rs_7d < -10 or rs_14d < -10:
        return "WEAK↓"
    return "lagging"
