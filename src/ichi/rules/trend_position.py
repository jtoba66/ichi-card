import pandas as pd

from ichi.indicators.helpers import divergence, momentum_angle, obv, rsi, swing_pivots
from ichi.rules.base import RuleResult


class AboveCloudRule:
    rule_id = "above_cloud"

    def __call__(self, df: pd.DataFrame, i: int) -> RuleResult:
        cloud_top = max(df["span_a"].iat[i], df["span_b"].iat[i])
        is_above = bool(df["close"].iat[i] > cloud_top)
        return RuleResult(
            rule_id=self.rule_id,
            state="Bullish" if is_above else "Bearish",
            label="Above Cloud" if is_above else "Below Cloud",
            qualifies_bull=is_above,
            qualifies_bear=not is_above,
        )


class AbovePriceRule:
    """Close > close 26 bars ago (chikou > past price, from price's side)."""

    rule_id = "above_price"
    _HIGH_THRESHOLD = 0.05  # >5% above = "High" badge

    def __call__(self, df: pd.DataFrame, i: int) -> RuleResult:
        if i < 26:
            return RuleResult(rule_id=self.rule_id, state="Neutral", label="Above Price (n/a)",
                              qualifies_bull=False, qualifies_bear=False)
        close_now = df["close"].iat[i]
        close_past = df["close"].iat[i - 26]
        pct = (close_now - close_past) / close_past
        is_above = bool(pct > 0)
        badge = " (High)" if pct > self._HIGH_THRESHOLD else ""
        return RuleResult(
            rule_id=self.rule_id,
            state="Bullish" if is_above else "Bearish",
            label=f"Above Price{badge}" if is_above else "Below Past Price",
            qualifies_bull=is_above,
            qualifies_bear=not is_above,
            detail=f"{pct * 100:+.1f}%",
        )


class AngleGte10Rule:
    """Momentum angle of recent price action >= threshold. Uses momentum_angle(), NOT chikou_angle()."""

    rule_id = "angle_gte10"
    _ANGLE_THRESHOLD = 10.0

    def __call__(self, df: pd.DataFrame, i: int) -> RuleResult:
        angles = df["_momentum_angle"] if "_momentum_angle" in df.columns else momentum_angle(df["close"])
        angle = float(angles.iat[i]) if not pd.isna(angles.iat[i]) else 0.0
        passes = bool(angle >= self._ANGLE_THRESHOLD)
        t = self._ANGLE_THRESHOLD
        return RuleResult(
            rule_id=self.rule_id,
            state="Bullish" if passes else "Bearish",
            label=f"Angle ≥ {t:.0f}° ({angle:.1f}°)" if passes else f"Angle < {t:.0f}° ({angle:.1f}°)",
            qualifies_bull=passes,
            qualifies_bear=not passes,
            detail=f"{angle:.1f}°",
        )


class AboveKijunRule:
    rule_id = "above_kijun"

    def __call__(self, df: pd.DataFrame, i: int) -> RuleResult:
        is_above = bool(df["close"].iat[i] > df["kj"].iat[i])
        return RuleResult(
            rule_id=self.rule_id,
            state="Bullish" if is_above else "Bearish",
            label="Above Kijun" if is_above else "Below Kijun",
            qualifies_bull=is_above,
            qualifies_bear=not is_above,
        )


class TKBullishRule:
    rule_id = "tk_bullish"

    def __call__(self, df: pd.DataFrame, i: int) -> RuleResult:
        is_bull = bool(df["tk"].iat[i] > df["kj"].iat[i])
        return RuleResult(
            rule_id=self.rule_id,
            state="Bullish" if is_bull else "Bearish",
            label="TK Bullish" if is_bull else "TK Bearish",
            qualifies_bull=is_bull,
            qualifies_bear=not is_bull,
        )


class BullStackRule:
    rule_id = "bull_stack"

    def __call__(self, df: pd.DataFrame, i: int) -> RuleResult:
        close = df["close"].iat[i]
        tk = df["tk"].iat[i]
        kj = df["kj"].iat[i]
        is_bull = bool(close > tk > kj)
        return RuleResult(
            rule_id=self.rule_id,
            state="Bullish" if is_bull else "Bearish",
            label="P > TK > KJ (strong bull)" if is_bull else "No Bull Stack",
            qualifies_bull=is_bull,
            qualifies_bear=not is_bull,
        )


class HighVolumeRule:
    rule_id = "high_volume"
    _MULTIPLIER = 1.5
    _SMA_PERIOD = 20

    def __call__(self, df: pd.DataFrame, i: int) -> RuleResult:
        vol = df["volume"]
        if pd.isna(vol.iat[i]) or vol.iat[i] == 0:
            return RuleResult(rule_id=self.rule_id, state="Neutral", label="Volume N/A",
                              qualifies_bull=False, qualifies_bear=False)
        sma = vol.rolling(self._SMA_PERIOD).mean()
        sma_val = sma.iat[i]
        if pd.isna(sma_val) or sma_val == 0:
            return RuleResult(rule_id=self.rule_id, state="Neutral", label="Volume N/A",
                              qualifies_bull=False, qualifies_bear=False)
        is_high = bool(vol.iat[i] > self._MULTIPLIER * sma_val)
        ratio = vol.iat[i] / sma_val
        return RuleResult(
            rule_id=self.rule_id,
            state="Bullish" if is_high else "Bearish",
            label=f"High Volume ({ratio:.1f}×)" if is_high else f"Low Volume ({ratio:.1f}×)",
            qualifies_bull=is_high,
            qualifies_bear=not is_high,
            detail=f"{ratio:.1f}×",
        )


class OBVRisingRule:
    rule_id = "obv_rising"
    _LOOKBACK = 10

    def __call__(self, df: pd.DataFrame, i: int) -> RuleResult:
        if i < self._LOOKBACK:
            return RuleResult(rule_id=self.rule_id, state="Neutral", label="OBV N/A",
                              qualifies_bull=False, qualifies_bear=False)
        obv_series = df["_obv"] if "_obv" in df.columns else obv(df)
        is_rising = bool(obv_series.iat[i] > obv_series.iat[i - self._LOOKBACK])
        return RuleResult(
            rule_id=self.rule_id,
            state="Bullish" if is_rising else "Bearish",
            label="OBV Rising" if is_rising else "OBV Falling",
            qualifies_bull=is_rising,
            qualifies_bear=not is_rising,
        )


class NoDivRule:
    """No bearish RSI divergence in last 30 bars. Rule passes (no_div) when divergence absent."""

    rule_id = "no_div"
    _WINDOW = 30
    _PIVOT_LOOKBACK = 5

    def __call__(self, df: pd.DataFrame, i: int) -> RuleResult:
        if i < self._WINDOW + self._PIVOT_LOOKBACK * 2:
            return RuleResult(rule_id=self.rule_id, state="Neutral", label="No Div (n/a)",
                              qualifies_bull=False, qualifies_bear=False)
        if "_bearish_div" in df.columns:
            has_div = bool(df["_bearish_div"].iat[i])
        else:
            rsi_series = rsi(df["close"])
            div_series = divergence(df["close"], rsi_series,
                                    pivot_lookback=self._PIVOT_LOOKBACK,
                                    window=self._WINDOW, direction="bearish")
            has_div = bool(div_series.iat[i])
        passes = not has_div
        return RuleResult(
            rule_id=self.rule_id,
            state="Bullish" if passes else "Bearish",
            label="No Bearish Div" if passes else "Bearish Div Detected",
            qualifies_bull=passes,
            qualifies_bear=has_div,
        )


class TripleSweepRule:
    """Three-state: NONE / DOUBLE SWEEP / TRIPLE SWEEP. Only TRIPLE qualifies bull."""

    rule_id = "triple_sweep"
    _PIVOT_LOOKBACK = 20
    _SWEEP_WINDOW = 60
    _TOLERANCE = 0.005

    def __call__(self, df: pd.DataFrame, i: int) -> RuleResult:
        if i < self._SWEEP_WINDOW:
            return RuleResult(rule_id=self.rule_id, state="None", label="No Sweep",
                              qualifies_bull=False, qualifies_bear=False)

        if "_swing_low" in df.columns:
            # Fast path: use precomputed swing lows
            window_start = max(0, i - self._SWEEP_WINDOW)
            window_lows = df["low"].iloc[window_start: i + 1]
            window_closes = df["close"].iloc[window_start: i + 1]
            pivot_mask = df["_swing_low"].iloc[window_start: i + 1]
            pivot_levels = window_lows[pivot_mask].values.tolist()
            sweeps = _count_sweeps_from_levels(
                window_lows, window_closes, pivot_levels, self._TOLERANCE)
        else:
            window_df = df.iloc[max(0, i - self._SWEEP_WINDOW): i + 1]
            sweeps = _count_sweeps(window_df, self._PIVOT_LOOKBACK, self._TOLERANCE)

        if sweeps >= 3:
            return RuleResult(rule_id=self.rule_id, state="Triple", label="Sweep ×3 (triple base)",
                              qualifies_bull=True, qualifies_bear=False, detail=f"{sweeps}")
        elif sweeps == 2:
            return RuleResult(rule_id=self.rule_id, state="Double", label="Double Sweep",
                              qualifies_bull=False, qualifies_bear=False, detail="2")
        else:
            return RuleResult(rule_id=self.rule_id, state="None", label="No Sweep",
                              qualifies_bull=False, qualifies_bear=False)


def _count_sweeps(window_df: pd.DataFrame, pivot_lookback: int, tolerance: float) -> int:
    """Count distinct liquidity sweep events in a window."""
    if len(window_df) < pivot_lookback * 2 + 1:
        return 0
    lows = window_df["low"]
    closes = window_df["close"]
    pivots = swing_pivots(lows, lookback=pivot_lookback, kind="low")
    pivot_levels = lows[pivots].values.tolist()
    if not pivot_levels:
        return 0

    sweep_count = 0
    used_levels: list[float] = []
    for j in range(len(window_df)):
        low_j = lows.iloc[j]
        close_j = closes.iloc[j]
        for level in pivot_levels:
            if any(abs(level - u) / level < tolerance * 2 for u in used_levels):
                continue
            if low_j <= level * (1 + tolerance) and close_j > level:
                sweep_count += 1
                used_levels.append(level)
                break
    return sweep_count


def _count_sweeps_from_levels(
    lows: pd.Series,
    closes: pd.Series,
    pivot_levels: list[float],
    tolerance: float,
) -> int:
    """Fast sweep counter when pivot levels are already computed."""
    if not pivot_levels:
        return 0
    sweep_count = 0
    used_levels: list[float] = []
    for j in range(len(lows)):
        low_j = lows.iloc[j]
        close_j = closes.iloc[j]
        for level in pivot_levels:
            if any(abs(level - u) / max(level, 1e-10) < tolerance * 2 for u in used_levels):
                continue
            if low_j <= level * (1 + tolerance) and close_j > level:
                sweep_count += 1
                used_levels.append(level)
                break
    return sweep_count
