import numpy as np
import pandas as pd


def slope_pct(series: pd.Series, lookback: int) -> pd.Series:
    """Percentage slope: (now - past) / past × 100 over lookback bars."""
    past = series.shift(lookback)
    return (series - past) / past.abs().replace(0, float("nan")) * 100


def momentum_angle(close: pd.Series, lookback: int = 5, scaling: float = 5.0) -> pd.Series:
    """Recent price action angle in degrees, normalized.
    angle = atan(pct_change_over_lookback × scaling) × 180 / π
    Used for 'Angle >= 10°' / 'Angle >= 20°' rules — NOT the chikou panel header."""
    pct = slope_pct(close, lookback) / 100.0
    return pd.Series(
        np.degrees(np.arctan(pct * scaling)),
        index=close.index,
    )


def chikou_angle(chikou: pd.Series, lookback: int = 10, scaling: float = 5.0) -> pd.Series:
    """Slope angle of the chikou line itself over lookback bars.
    Used for the panel header chikou angle indicator — NOT the Angle >= X° rules."""
    pct = slope_pct(chikou, lookback) / 100.0
    return pd.Series(
        np.degrees(np.arctan(pct * scaling)),
        index=chikou.index,
    )


def swing_pivots(
    series: pd.Series, lookback: int = 20, kind: str = "high"
) -> pd.Series:
    """Sparse boolean series: True at bars that are a local max (kind='high')
    or local min (kind='low') over a ±lookback window.
    Vectorized via centered rolling — O(n) instead of O(n²)."""
    window = 2 * lookback + 1
    if kind == "high":
        extreme = series.rolling(window, center=True, min_periods=window).max()
    else:
        extreme = series.rolling(window, center=True, min_periods=window).min()
    return (series == extreme).fillna(False)


def liquidity_sweeps(
    df: pd.DataFrame,
    pivot_lookback: int = 20,
    sweep_window: int = 60,
    tolerance: float = 0.005,
) -> pd.Series:
    """Boolean: True at bars where price wicked below a recent swing low and closed back above.
    O(n log k) via pre-computed pivot arrays + two-pointer window."""
    lows_arr = df["low"].to_numpy()
    closes_arr = df["close"].to_numpy()
    pivots = swing_pivots(df["low"], lookback=pivot_lookback, kind="low")
    pivot_pos = np.where(pivots.to_numpy())[0]
    pivot_vals = lows_arr[pivot_pos]
    result = np.zeros(len(df), dtype=bool)
    lo = 0

    for i in range(pivot_lookback, len(df)):
        cutoff = i - sweep_window
        while lo < len(pivot_pos) and pivot_pos[lo] < cutoff:
            lo += 1
        hi = int(np.searchsorted(pivot_pos, i, side="left"))
        if hi <= lo:
            continue
        nearest_pivot = pivot_vals[hi - 1]
        if lows_arr[i] <= nearest_pivot * (1 + tolerance) and closes_arr[i] > nearest_pivot:
            result[i] = True

    return pd.Series(result, index=df.index)


def consecutive_near_line(
    close: pd.Series,
    line: pd.Series,
    tolerance: float = 0.015,
    max_lookback: int = 100,
) -> pd.Series:
    """For each bar, count consecutive prior bars (going backward) where
    close was within tolerance of line. Used for TK Magnet.
    max_lookback caps the backward walk so this stays O(n × max_lookback)."""
    result = pd.Series(0, index=close.index, dtype=int)
    close_arr = close.to_numpy()
    line_arr = line.to_numpy()
    n = len(close_arr)
    for i in range(n):
        count = 0
        j = i
        stop = max(-1, i - max_lookback)
        while j > stop:
            line_val = line_arr[j]
            if line_val == 0:
                break
            if abs(close_arr[j] - line_val) / line_val <= tolerance:
                count += 1
                j -= 1
            else:
                break
        result.iloc[i] = count
    return result


def obv(df: pd.DataFrame) -> pd.Series:
    """On-Balance Volume."""
    close = df["close"]
    volume = df["volume"]
    direction = close.diff().apply(lambda x: 1 if x > 0 else (-1 if x < 0 else 0))
    return (direction * volume).cumsum()


def rsi(close: pd.Series, period: int = 14) -> pd.Series:
    """Relative Strength Index."""
    delta = close.diff()
    gain = delta.clip(lower=0)
    loss = -delta.clip(upper=0)
    avg_gain = gain.ewm(com=period - 1, min_periods=period).mean()
    avg_loss = loss.ewm(com=period - 1, min_periods=period).mean()
    rs = avg_gain / avg_loss.replace(0, float("nan"))
    return 100 - (100 / (1 + rs))


def adx(df: pd.DataFrame, period: int = 14) -> pd.DataFrame:
    """Average Directional Index (Wilder's smoothing).

    Returns a DataFrame with columns:
        adx    — trend strength (0–100). >25 = trending, <20 = choppy.
        plus_di  — +DI (bullish directional movement)
        minus_di — -DI (bearish directional movement)

    adx alone is regime: >25 trending, 20–25 developing, <20 choppy/ranging.
    """
    high, low, close = df["high"], df["low"], df["close"]
    prev_close = close.shift(1)
    prev_high = high.shift(1)
    prev_low = low.shift(1)

    tr = pd.concat([
        high - low,
        (high - prev_close).abs(),
        (low - prev_close).abs(),
    ], axis=1).max(axis=1)

    plus_dm = (high - prev_high).clip(lower=0).where(
        (high - prev_high) > (prev_low - low), 0.0
    )
    minus_dm = (prev_low - low).clip(lower=0).where(
        (prev_low - low) > (high - prev_high), 0.0
    )

    # Wilder's smoothed EMA (com = period - 1)
    atr = tr.ewm(com=period - 1, min_periods=period).mean()
    safe_atr = atr.replace(0, float("nan"))
    plus_di = 100 * plus_dm.ewm(com=period - 1, min_periods=period).mean() / safe_atr
    minus_di = 100 * minus_dm.ewm(com=period - 1, min_periods=period).mean() / safe_atr

    dx = (100 * (plus_di - minus_di).abs() / (plus_di + minus_di).replace(0, float("nan")))
    adx_series = dx.ewm(com=period - 1, min_periods=period).mean()

    return pd.DataFrame({"adx": adx_series, "plus_di": plus_di, "minus_di": minus_di},
                        index=df.index)


def divergence(
    price: pd.Series,
    indicator: pd.Series,
    pivot_lookback: int = 5,
    window: int = 30,
    direction: str = "bearish",
) -> pd.Series:
    """Detect divergence between price and indicator using the two most recent pivots.

    bearish: price makes higher high but indicator makes lower high → bearish divergence
    bullish: price makes lower low but indicator makes higher low → bullish divergence

    O(n log k) via pre-computed pivot position arrays + binary search.
    """
    kind = "high" if direction == "bearish" else "low"
    price_pivots = swing_pivots(price, lookback=pivot_lookback, kind=kind)
    ind_pivots = swing_pivots(indicator, lookback=pivot_lookback, kind=kind)

    price_arr = price.to_numpy()
    ind_arr = indicator.to_numpy()
    pp = np.where(price_pivots.to_numpy())[0]
    ip = np.where(ind_pivots.to_numpy())[0]
    result = np.zeros(len(price), dtype=bool)

    if len(pp) < 2 or len(ip) < 2:
        return pd.Series(result, index=price.index)

    lo_p = lo_i = 0
    for bar in range(window, len(price)):
        cutoff = bar - window
        while lo_p < len(pp) and pp[lo_p] < cutoff:
            lo_p += 1
        while lo_i < len(ip) and ip[lo_i] < cutoff:
            lo_i += 1
        hi_p = int(np.searchsorted(pp, bar + 1, side="left"))
        hi_i = int(np.searchsorted(ip, bar + 1, side="left"))
        if hi_p - lo_p < 2 or hi_i - lo_i < 2:
            continue
        p1, p2 = price_arr[pp[hi_p - 2]], price_arr[pp[hi_p - 1]]
        i1, i2 = ind_arr[ip[hi_i - 2]], ind_arr[ip[hi_i - 1]]
        if direction == "bearish" and p2 > p1 and i2 < i1:
            result[bar] = True
        elif direction == "bullish" and p2 < p1 and i2 > i1:
            result[bar] = True

    return pd.Series(result, index=price.index)


def bollinger(close: pd.Series, period: int = 20, std: float = 2.0) -> pd.DataFrame:
    """Bollinger Bands. Returns bb_upper, bb_lower, bb_mid, bb_width, bb_pct."""
    mid = close.rolling(period).mean()
    sigma = close.rolling(period).std()
    upper = mid + std * sigma
    lower = mid - std * sigma
    width = (upper - lower) / mid.replace(0, float("nan"))
    pct = (close - lower) / (upper - lower).replace(0, float("nan"))
    return pd.DataFrame(
        {"bb_upper": upper, "bb_lower": lower, "bb_mid": mid, "bb_width": width, "bb_pct": pct},
        index=close.index,
    )


def bars_since(bool_series: pd.Series, max_lookback: int = 50) -> pd.Series:
    """Count bars since last True value. Caps at max_lookback."""
    result = pd.Series(float(max_lookback), index=bool_series.index)
    arr = bool_series.to_numpy()
    last_true = -max_lookback
    for i, val in enumerate(arr):
        if val:
            last_true = i
        result.iloc[i] = i - last_true
    return result


def bb_squeeze(close: pd.Series, period: int = 20, lookback: int = 125) -> pd.Series:
    """True when BB width is within 5% of its narrowest in `lookback` bars (volatility compression)."""
    width = bollinger(close, period)["bb_width"]
    min_width = width.rolling(lookback, min_periods=30).min()
    return width <= min_width * 1.05
