"""Precompute expensive derived series into the dataframe before per-bar rule evaluation.

Rules check for these columns (prefixed with "_") and use them instead of recomputing.
This converts O(n_bars × n) work into O(n) work per symbol for snapshot/batch use.
"""
from __future__ import annotations

import pandas as pd

from ichi.indicators.helpers import (
    adx,
    bars_since,
    bb_squeeze,
    bollinger,
    chikou_angle,
    consecutive_near_line,
    divergence,
    momentum_angle,
    obv,
    rsi,
    slope_pct,
    swing_pivots,
)


def precompute(df: pd.DataFrame) -> pd.DataFrame:
    """Add precomputed indicator columns to df in-place. Returns df.

    Columns added (all prefixed with '_' to distinguish from raw OHLCV):
        _rsi               RSI(14)
        _obv               On-Balance Volume
        _bearish_div       True where bearish RSI divergence detected
        _momentum_angle    momentum_angle(close, 5)
        _chikou_angle      chikou_angle(chikou, 10)
        _tk_slope5         slope_pct(tk, 5)
        _kj_slope5         slope_pct(kj, 5)
        _kj_slope10        slope_pct(kj, 10)
        _span_a_lead_slope slope_pct(span_a_lead, 5)
        _span_b_slope10    slope_pct(span_b, 10)
        _tk_near_count     consecutive_near_line count for TK Magnet
        _swing_high        swing pivot highs (lookback=5) over full series
        _swing_low         swing pivot lows (lookback=20) over full series
        _adx               ADX(14) — trend strength. >25 trending, <20 choppy.
        _plus_di           +DI directional indicator
        _minus_di          -DI directional indicator
    """
    df["_rsi"] = rsi(df["close"])
    df["_obv"] = obv(df)
    df["_bearish_div"] = divergence(df["close"], df["_rsi"], pivot_lookback=5, window=30,
                                    direction="bearish")
    df["_momentum_angle"] = momentum_angle(df["close"], lookback=5)
    df["_chikou_angle"] = chikou_angle(df["chikou"], lookback=10)
    df["_tk_slope5"] = slope_pct(df["tk"], 5)
    df["_kj_slope5"] = slope_pct(df["kj"], 5)
    df["_kj_slope10"] = slope_pct(df["kj"], 10)
    df["_span_a_lead_slope5"] = slope_pct(df["span_a_lead"], 5)
    df["_span_b_slope10"] = slope_pct(df["span_b"], 10)
    df["_tk_near_count"] = consecutive_near_line(df["close"], df["tk"], tolerance=0.015, max_lookback=100)
    df["_swing_high"] = swing_pivots(df["high"], lookback=5, kind="high")
    df["_swing_low"] = swing_pivots(df["low"], lookback=20, kind="low")
    adx_df = adx(df, period=14)
    df["_adx"] = adx_df["adx"]
    df["_plus_di"] = adx_df["plus_di"]
    df["_minus_di"] = adx_df["minus_di"]

    # Bollinger Bands
    bb = bollinger(df["close"])
    df["_bb_upper"] = bb["bb_upper"]
    df["_bb_lower"] = bb["bb_lower"]
    df["_bb_width"] = bb["bb_width"]
    df["_bb_pct"] = bb["bb_pct"]
    df["_bb_squeeze"] = bb_squeeze(df["close"])

    # Bullish RSI divergence (price lower low, RSI higher low)
    df["_bullish_div"] = divergence(df["close"], df["_rsi"], pivot_lookback=5, window=30,
                                    direction="bullish")

    # Volume ratio: current bar vs 20-bar rolling average
    df["_vol_ratio"] = df["volume"] / df["volume"].rolling(20, min_periods=5).mean().replace(0, float("nan"))

    # ── Dashboard B precomputed columns ──────────────────────────────────────

    # Balance / Imbalance distances
    df["_kj_distance_pct"] = (df["close"] - df["kj"]) / df["kj"].replace(0, float("nan")) * 100
    df["_prev_kj_distance_pct"] = df["_kj_distance_pct"].shift(1)
    df["_tk_distance_pct"] = (df["close"] - df["tk"]) / df["tk"].replace(0, float("nan")) * 100

    # TK Cross detection
    df["_tk_cross_bullish"] = (df["tk"] > df["kj"]) & (df["tk"].shift(1) <= df["kj"].shift(1))
    df["_tk_cross_bullish_bars_ago"] = bars_since(df["_tk_cross_bullish"])

    # Chikou cloud position (chikou is close shifted back 26 bars — compare against span_a/b at same index)
    _cs = df["chikou"]
    _cs_cloud_min = df[["span_a", "span_b"]].min(axis=1)
    _cs_cloud_max = df[["span_a", "span_b"]].max(axis=1)
    df["_chikou_in_cloud"] = (_cs >= _cs_cloud_min) & (_cs <= _cs_cloud_max)
    df["_chikou_above_cloud"] = _cs > _cs_cloud_max

    # Chikou above past price: current close vs close 26 bars ago (same geometric check as chikou span)
    df["_chikou_above_past_price"] = df["close"] > df["close"].shift(26)

    # Cloud curling and twist (using leading spans)
    df["_cloud_curling_up"] = (
        (df["span_a"] < df["span_b"]) &
        (df["_span_a_lead_slope5"] > 0)
    )
    df["_cloud_just_twisted_bull"] = (
        (df["span_a"] > df["span_b"]) &
        (df["span_a"].shift(1) <= df["span_b"].shift(1))
    )
    df["_cloud_twist_bull_bars_ago"] = bars_since(df["_cloud_just_twisted_bull"])

    # Cloud edges
    df["_cloud_top"]    = df[["span_a", "span_b"]].max(axis=1)
    df["_cloud_bottom"] = df[["span_a", "span_b"]].min(axis=1)
    df["_cloud_top_distance_pct"]    = (df["close"] - df["_cloud_top"])    / df["_cloud_top"].replace(0, float("nan"))    * 100
    df["_cloud_bottom_distance_pct"] = (df["close"] - df["_cloud_bottom"]) / df["_cloud_bottom"].replace(0, float("nan")) * 100

    # E2E entry detection
    _in_cloud = (df["close"] >= df["_cloud_bottom"]) & (df["close"] <= df["_cloud_top"])
    df["_e2e_entry_from_below"] = _in_cloud & (df["close"].shift(1) < df["_cloud_bottom"].shift(1))
    df["_e2e_entry_from_above"] = _in_cloud & (df["close"].shift(1) > df["_cloud_top"].shift(1))
    df["_cloud_thickness_pct"]  = (df["span_a"] - df["span_b"]).abs() / df["close"].replace(0, float("nan")) * 100

    return df
