import pandas as pd

from ichi.indicators.helpers import momentum_angle, slope_pct, swing_pivots
from ichi.rules.base import RuleResult

_SLOPE_LOOKBACK = 5
_SLOPE_RISING_THRESHOLD = 0.3   # % — [default-guess]
_SLOPE_FALLING_THRESHOLD = -0.3


class TKRisingRule:
    rule_id = "tk_rising"

    def __call__(self, df: pd.DataFrame, i: int) -> RuleResult:
        if i < _SLOPE_LOOKBACK:
            return RuleResult(rule_id=self.rule_id, state="Neutral", label="TK (n/a)",
                              qualifies_bull=False, qualifies_bear=False)
        pct = float((df["_tk_slope5"] if "_tk_slope5" in df.columns else slope_pct(df["tk"], _SLOPE_LOOKBACK)).iat[i])
        if pct > _SLOPE_RISING_THRESHOLD:
            state, label, bull, bear = "Rising", f"TK ↗ Rising ({pct:.1f}%)", True, False
        elif pct < _SLOPE_FALLING_THRESHOLD:
            state, label, bull, bear = "Falling", f"TK ↘ Falling ({pct:.1f}%)", False, True
        else:
            state, label, bull, bear = "Flat", f"TK → Flat ({pct:.1f}%)", False, False
        return RuleResult(rule_id=self.rule_id, state=state, label=label,
                          qualifies_bull=bull, qualifies_bear=bear, detail=f"{pct:.1f}%")


class KJRisingRule:
    rule_id = "kj_rising"

    def __call__(self, df: pd.DataFrame, i: int) -> RuleResult:
        if i < _SLOPE_LOOKBACK:
            return RuleResult(rule_id=self.rule_id, state="Neutral", label="KJ (n/a)",
                              qualifies_bull=False, qualifies_bear=False)
        pct = float((df["_kj_slope5"] if "_kj_slope5" in df.columns else slope_pct(df["kj"], _SLOPE_LOOKBACK)).iat[i])
        if pct > _SLOPE_RISING_THRESHOLD:
            state, label, bull, bear = "Rising", f"KJ ↗ Rising ({pct:.1f}%)", True, False
        elif pct < _SLOPE_FALLING_THRESHOLD:
            state, label, bull, bear = "Falling", f"KJ ↘ Falling ({pct:.1f}%)", False, True
        else:
            state, label, bull, bear = "Flat", f"KJ → Flat ({pct:.1f}%)", False, False
        return RuleResult(rule_id=self.rule_id, state=state, label=label,
                          qualifies_bull=bull, qualifies_bear=bear, detail=f"{pct:.1f}%")


class TKBounceRule:
    rule_id = "tk_bounce"
    _LOOKBACK = 5
    _TOLERANCE = 0.01   # 1% — [default-guess]
    _VOL_MULTIPLIER = 1.5
    _VOL_SMA = 20

    def __call__(self, df: pd.DataFrame, i: int) -> RuleResult:
        if i < self._LOOKBACK:
            return RuleResult(rule_id=self.rule_id, state="None", label="No TK Bounce",
                              qualifies_bull=False, qualifies_bear=False)
        bounced = False
        super_strong = False
        for j in range(max(0, i - self._LOOKBACK), i + 1):
            tk_val = df["tk"].iat[j]
            low_j = df["low"].iat[j]
            close_j = df["close"].iat[j]
            if tk_val == 0:
                continue
            near_tk = abs(low_j - tk_val) / tk_val <= self._TOLERANCE
            closed_above = close_j > tk_val
            if near_tk and closed_above:
                bounced = True
                # Super strong: bounce + TK rising + volume above average
                tk_rising = bool(slope_pct(df["tk"], _SLOPE_LOOKBACK).iat[j] > _SLOPE_RISING_THRESHOLD)
                vol_sma = df["volume"].rolling(self._VOL_SMA).mean().iat[j]
                vol_high = not pd.isna(vol_sma) and vol_sma > 0 and df["volume"].iat[j] > self._VOL_MULTIPLIER * vol_sma
                if tk_rising and vol_high:
                    super_strong = True
                break

        if super_strong:
            label = "TK Bounce (super strong)"
        elif bounced:
            label = "TK Bounce"
        else:
            label = "No TK Bounce"

        return RuleResult(
            rule_id=self.rule_id,
            state="SuperStrong" if super_strong else ("Bounce" if bounced else "None"),
            label=label,
            qualifies_bull=bounced,
            qualifies_bear=False,
        )


class ChikouClearedRule:
    """Chikou is above the last 3 swing-high pivots in a 50-bar lookback."""

    rule_id = "chikou_cleared"
    _PIVOT_LOOKBACK = 5
    _WINDOW = 50
    _N_PIVOTS = 3

    def __call__(self, df: pd.DataFrame, i: int) -> RuleResult:
        # Chikou at bar i is the close projected back: chikou[i] = close[i+26]
        # At bar i, chikou plots at position i-26 on the chart, so compare to past price at i-26
        chikou_index = i - 26
        if chikou_index < 0:
            return RuleResult(rule_id=self.rule_id, state="Neutral", label="Chikou Cleared (n/a)",
                              qualifies_bull=False, qualifies_bear=False)
        chikou_val = df["close"].iat[i]   # chikou's value = current close
        # The chart position of chikou is chikou_index; check price levels there
        window_start = max(0, chikou_index - self._WINDOW)
        highs_window = df["high"].iloc[window_start: chikou_index + 1]
        if "_swing_high" in df.columns:
            pivot_mask = df["_swing_high"].iloc[window_start: chikou_index + 1]
            pivot_levels = highs_window[pivot_mask].nlargest(self._N_PIVOTS).values.tolist()
        else:
            pivots = swing_pivots(highs_window, lookback=self._PIVOT_LOOKBACK, kind="high")
            pivot_levels = highs_window[pivots].nlargest(self._N_PIVOTS).values.tolist()
        if not pivot_levels:
            return RuleResult(rule_id=self.rule_id, state="Bullish", label="Chikou > past S/R (cleared)",
                              qualifies_bull=True, qualifies_bear=False)
        cleared = bool(all(chikou_val > level for level in pivot_levels))
        return RuleResult(
            rule_id=self.rule_id,
            state="Bullish" if cleared else "Bearish",
            label="Chikou > past S/R (cleared)" if cleared else "Chikou Overlapping S/R",
            qualifies_bull=cleared,
            qualifies_bear=not cleared,
        )


class FullBullRule:
    """Both TK and KJ are above the entire cloud: min(TK, KJ) > max(SpanA, SpanB)."""

    rule_id = "full_bull"

    def __call__(self, df: pd.DataFrame, i: int) -> RuleResult:
        lines_min = min(df["tk"].iat[i], df["kj"].iat[i])
        cloud_top = max(df["span_a"].iat[i], df["span_b"].iat[i])
        is_bull = bool(lines_min > cloud_top)
        return RuleResult(
            rule_id=self.rule_id,
            state="Bullish" if is_bull else "Bearish",
            label="Full Bull: KJ + TK above cloud" if is_bull else "Lines Not Above Cloud",
            qualifies_bull=is_bull,
            qualifies_bear=not is_bull,
        )


class NoTKCrossRule:
    """No bearish TK/KJ cross (TK dropped below KJ) within last lookback bars."""

    rule_id = "no_tk_cross"
    _LOOKBACK = 10

    def __call__(self, df: pd.DataFrame, i: int) -> RuleResult:
        start = max(1, i - self._LOOKBACK + 1)
        had_bearish_cross = False
        for j in range(start, i + 1):
            # Bearish cross: TK crossed below KJ between bar j-1 and bar j
            if df["tk"].iat[j - 1] >= df["kj"].iat[j - 1] and df["tk"].iat[j] < df["kj"].iat[j]:
                had_bearish_cross = True
                break
        passes = not had_bearish_cross
        return RuleResult(
            rule_id=self.rule_id,
            state="Bullish" if passes else "Bearish",
            label="No TK Cross" if passes else "TK Cross (bearish, recent)",
            qualifies_bull=passes,
            qualifies_bear=had_bearish_cross,
        )


class KijunFlatRule:
    rule_id = "kijun_flat"
    _LOOKBACK = 10
    _FLAT_THRESHOLD = 0.3   # % — [default-guess]

    def __call__(self, df: pd.DataFrame, i: int) -> RuleResult:
        if i < self._LOOKBACK:
            return RuleResult(rule_id=self.rule_id, state="Neutral", label="Kijun (n/a)",
                              qualifies_bull=False, qualifies_bear=False)
        pct = abs(float(slope_pct(df["kj"], self._LOOKBACK).iat[i]))
        is_flat = pct < self._FLAT_THRESHOLD
        close = df["close"].iat[i]
        kj = df["kj"].iat[i]
        if is_flat:
            # Flat KJ passes when price is above it (magnet pulling price up to it is bullish)
            passes = bool(close > kj)
            return RuleResult(
                rule_id=self.rule_id,
                state="Flat" if passes else "FlatBearish",
                label="Kijun FLAT (magnet)" if passes else "Kijun FLAT (below)",
                qualifies_bull=passes,
                qualifies_bear=not passes,
            )
        else:
            sloping_up = bool(slope_pct(df["kj"], self._LOOKBACK).iat[i] > 0)
            return RuleResult(
                rule_id=self.rule_id,
                state="SlopingUp" if sloping_up else "SlopingDown",
                label="Kijun Sloping ↗" if sloping_up else "Kijun Sloping ↘",
                qualifies_bull=sloping_up,
                qualifies_bear=not sloping_up,
            )


class AwayFromSpanBRule:
    rule_id = "away_from_spanb"
    _THRESHOLD = 0.03   # 3% — [default-guess]

    def __call__(self, df: pd.DataFrame, i: int) -> RuleResult:
        close = df["close"].iat[i]
        span_b = df["span_b"].iat[i]
        if pd.isna(span_b) or span_b == 0:
            return RuleResult(rule_id=self.rule_id, state="Neutral", label="SpanB (n/a)",
                              qualifies_bull=False, qualifies_bear=False)
        distance = abs(close - span_b) / close
        away = bool(distance > self._THRESHOLD)
        return RuleResult(
            rule_id=self.rule_id,
            state="Bullish" if away else "Bearish",
            label=f"Away from SpanB ({distance*100:.1f}%)" if away else f"Near SpanB ({distance*100:.1f}%)",
            qualifies_bull=away,
            qualifies_bear=not away,
            detail=f"{distance*100:.1f}%",
        )


class AngleGte20Rule:
    rule_id = "angle_gte20"
    _ANGLE_THRESHOLD = 20.0

    def __call__(self, df: pd.DataFrame, i: int) -> RuleResult:
        angles = df["_momentum_angle"] if "_momentum_angle" in df.columns else momentum_angle(df["close"])
        angle = float(angles.iat[i]) if not pd.isna(angles.iat[i]) else 0.0
        passes = bool(angle >= self._ANGLE_THRESHOLD)
        t = self._ANGLE_THRESHOLD
        return RuleResult(
            rule_id=self.rule_id,
            state="Bullish" if passes else "Bearish",
            label=f"Angle ≥ {t:.0f}° (strong, {angle:.1f}°)" if passes else f"Angle < {t:.0f}° ({angle:.1f}°)",
            qualifies_bull=passes,
            qualifies_bear=not passes,
            detail=f"{angle:.1f}°",
        )


class TKMagnetRule:
    """Counts consecutive bars near TK. Fires warning at >= 10 bars (bearish for bull score)."""

    rule_id = "tk_magnet"
    _WARNING_BARS = 10
    _TOLERANCE = 0.015   # 1.5% — [default-guess]

    def __call__(self, df: pd.DataFrame, i: int) -> RuleResult:
        if "_tk_near_count" in df.columns:
            count = int(df["_tk_near_count"].iat[i])
        else:
            count = 0
            j = i
            while j >= 0:
                tk_val = df["tk"].iat[j]
                if tk_val == 0 or pd.isna(tk_val):
                    break
                if abs(df["close"].iat[j] - tk_val) / tk_val <= self._TOLERANCE:
                    count += 1
                    j -= 1
                else:
                    break
        warning = count >= self._WARNING_BARS
        return RuleResult(
            rule_id=self.rule_id,
            state="Warning" if warning else "Clear",
            label=f"TK Magnet ({count} bars — retrace likely)" if warning else "TK Magnet: N/A",
            qualifies_bull=not warning,
            qualifies_bear=warning,
            detail=str(count) if warning else None,
        )


class KJBalancedRule:
    """KJ positioned within 30-70% percentile of last 50-bar range."""

    rule_id = "kj_balanced"
    _WINDOW = 50
    _LOW_PCT = 0.30
    _HIGH_PCT = 0.70

    def __call__(self, df: pd.DataFrame, i: int) -> RuleResult:
        if i < self._WINDOW:
            return RuleResult(rule_id=self.rule_id, state="Neutral", label="KJ Balanced (n/a)",
                              qualifies_bull=False, qualifies_bear=False)
        kj = df["kj"].iat[i]
        window_high = df["high"].iloc[i - self._WINDOW: i + 1].max()
        window_low = df["low"].iloc[i - self._WINDOW: i + 1].min()
        rng = window_high - window_low
        if rng == 0:
            return RuleResult(rule_id=self.rule_id, state="Neutral", label="KJ Balanced (n/a)",
                              qualifies_bull=False, qualifies_bear=False)
        percentile = (kj - window_low) / rng
        balanced = bool(self._LOW_PCT <= percentile <= self._HIGH_PCT)
        return RuleResult(
            rule_id=self.rule_id,
            state="Balanced" if balanced else "Extreme",
            label=f"KJ Balanced ({percentile*100:.0f}%ile)" if balanced else f"KJ Extreme ({percentile*100:.0f}%ile)",
            qualifies_bull=balanced,
            qualifies_bear=not balanced,
        )


class NoFakeoutRule:
    """No candle closed across cloud and reversed back within 3 bars in the last 10 bars."""

    rule_id = "no_fakeout"
    _LOOKBACK = 10
    _REVERSAL_WINDOW = 3

    def __call__(self, df: pd.DataFrame, i: int) -> RuleResult:
        start = max(0, i - self._LOOKBACK)
        fakeout = False
        for j in range(start, i + 1):
            span_a_j = df["span_a"].iat[j]
            span_b_j = df["span_b"].iat[j]
            if pd.isna(span_a_j) or pd.isna(span_b_j):
                continue
            cloud_top = max(span_a_j, span_b_j)
            cloud_bot = min(span_a_j, span_b_j)
            close_j = df["close"].iat[j]
            # Check if this bar closed above the cloud
            if close_j > cloud_top:
                # Look forward up to _REVERSAL_WINDOW bars for a reversal below cloud
                for k in range(j + 1, min(j + self._REVERSAL_WINDOW + 1, i + 1)):
                    if df["close"].iat[k] < cloud_bot:
                        fakeout = True
                        break
            if fakeout:
                break
        passes = not fakeout
        return RuleResult(
            rule_id=self.rule_id,
            state="Bullish" if passes else "Bearish",
            label="No Fakeout Risk" if passes else "Fakeout Detected",
            qualifies_bull=passes,
            qualifies_bear=fakeout,
        )


class KJAlignedRule:
    """KJ slope direction matches the 50-bar price trend direction."""

    rule_id = "kj_aligned"
    _TREND_LOOKBACK = 50
    _SLOPE_LOOKBACK = 10

    def __call__(self, df: pd.DataFrame, i: int) -> RuleResult:
        if i < max(self._TREND_LOOKBACK, self._SLOPE_LOOKBACK):
            return RuleResult(rule_id=self.rule_id, state="Neutral", label="KJ Aligned (n/a)",
                              qualifies_bull=False, qualifies_bear=False)
        trend_up = bool(df["close"].iat[i] > df["close"].iat[i - self._TREND_LOOKBACK])
        kj_slope = float(slope_pct(df["kj"], self._SLOPE_LOOKBACK).iat[i])
        kj_up = kj_slope > 0
        aligned = bool(trend_up == kj_up)
        return RuleResult(
            rule_id=self.rule_id,
            state="Aligned" if aligned else "Diverging",
            label="KJ Aligned with Trend" if aligned else "KJ Diverging from Trend",
            qualifies_bull=aligned,
            qualifies_bear=not aligned,
        )


# ── TK/KJ Slope sub-section ────────────────────────────────────────────────────

class TKNoCurlRule:
    """TK slope sign unchanged in the last 3 bars."""

    rule_id = "tk_no_curl"
    _LOOKBACK = 3

    def __call__(self, df: pd.DataFrame, i: int) -> RuleResult:
        if i < self._LOOKBACK + _SLOPE_LOOKBACK:
            return RuleResult(rule_id=self.rule_id, state="Neutral", label="TK No Curl (n/a)",
                              qualifies_bull=False, qualifies_bear=False)
        slopes = slope_pct(df["tk"], _SLOPE_LOOKBACK)
        signs = [slopes.iat[i - k] > 0 for k in range(self._LOOKBACK)]
        no_curl = len(set(signs)) == 1
        return RuleResult(
            rule_id=self.rule_id,
            state="Stable" if no_curl else "Curling",
            label="TK No Curl" if no_curl else "TK Curling",
            qualifies_bull=no_curl,
            qualifies_bear=not no_curl,
        )


class KJNoCurlRule:
    rule_id = "kj_no_curl"
    _LOOKBACK = 3

    def __call__(self, df: pd.DataFrame, i: int) -> RuleResult:
        if i < self._LOOKBACK + _SLOPE_LOOKBACK:
            return RuleResult(rule_id=self.rule_id, state="Neutral", label="KJ No Curl (n/a)",
                              qualifies_bull=False, qualifies_bear=False)
        slopes = slope_pct(df["kj"], _SLOPE_LOOKBACK)
        signs = [slopes.iat[i - k] > 0 for k in range(self._LOOKBACK)]
        no_curl = len(set(signs)) == 1
        return RuleResult(
            rule_id=self.rule_id,
            state="Stable" if no_curl else "Curling",
            label="KJ No Curl" if no_curl else "KJ Curling",
            qualifies_bull=no_curl,
            qualifies_bear=not no_curl,
        )


class BothRisingRule:
    """Composite: both TK and KJ rising → 'Both Rising — Confirmed Trend'.
    This is the 18th scoring rule [default-guess]."""

    rule_id = "both_rising"

    def __call__(self, df: pd.DataFrame, i: int) -> RuleResult:
        if i < _SLOPE_LOOKBACK:
            return RuleResult(rule_id=self.rule_id, state="Neutral", label="Slope (n/a)",
                              qualifies_bull=False, qualifies_bear=False)
        tk_pct = float((df["_tk_slope5"] if "_tk_slope5" in df.columns else slope_pct(df["tk"], _SLOPE_LOOKBACK)).iat[i])
        kj_pct = float((df["_kj_slope5"] if "_kj_slope5" in df.columns else slope_pct(df["kj"], _SLOPE_LOOKBACK)).iat[i])
        tk_rising = tk_pct > _SLOPE_RISING_THRESHOLD
        kj_rising = kj_pct > _SLOPE_RISING_THRESHOLD
        tk_falling = tk_pct < _SLOPE_FALLING_THRESHOLD
        kj_falling = kj_pct < _SLOPE_FALLING_THRESHOLD

        if tk_rising and kj_rising:
            return RuleResult(rule_id=self.rule_id, state="BothRising",
                              label="Both Rising — Confirmed Trend",
                              qualifies_bull=True, qualifies_bear=False)
        elif tk_falling and kj_falling:
            return RuleResult(rule_id=self.rule_id, state="BothFalling",
                              label="Both Falling — Confirmed Bear",
                              qualifies_bull=False, qualifies_bear=True)
        else:
            return RuleResult(rule_id=self.rule_id, state="Mixed",
                              label="Mixed — No Confirmed Trend",
                              qualifies_bull=False, qualifies_bear=False)
