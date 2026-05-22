import pandas as pd


def ichimoku(
    df: pd.DataFrame,
    tenkan_period: int = 9,
    kijun_period: int = 26,
    senkou_b_period: int = 52,
    displacement: int = 26,
) -> pd.DataFrame:
    """Add Ichimoku columns to a copy of the input OHLCV dataframe.

    Canonical parameters (9/26/52/26) are the defaults and should not be changed.

    Added columns:
        tk           — Tenkan-sen
        kj           — Kijun-sen
        span_a       — Senkou Span A shifted to current bar (cloud edge at bar i)
        span_b       — Senkou Span B shifted to current bar (cloud edge at bar i)
        span_a_lead  — Senkou Span A unshifted (leading edge: what cloud WILL be at i+displacement)
        span_b_lead  — Senkou Span B unshifted (leading edge)
        chikou       — Current close shifted back by displacement (lagging span)
    """
    out = df.copy()
    high = df["high"]
    low = df["low"]
    close = df["close"]

    out["tk"] = (high.rolling(tenkan_period).max() + low.rolling(tenkan_period).min()) / 2
    out["kj"] = (high.rolling(kijun_period).max() + low.rolling(kijun_period).min()) / 2

    # Leading edges — what the cloud WILL be displacement bars from now
    out["span_a_lead"] = (out["tk"] + out["kj"]) / 2
    out["span_b_lead"] = (
        high.rolling(senkou_b_period).max() + low.rolling(senkou_b_period).min()
    ) / 2

    # Cloud at current bar (shifted forward so index i = cloud edge visible at bar i)
    out["span_a"] = out["span_a_lead"].shift(displacement)
    out["span_b"] = out["span_b_lead"].shift(displacement)

    # Chikou: current close projected back displacement bars
    # shift(-displacement) places close[i] at index i-displacement, so at any bar i,
    # chikou[i] is the close from i+displacement bars in the future — matching TV behavior
    out["chikou"] = close.shift(-displacement)

    return out
