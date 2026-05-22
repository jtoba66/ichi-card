import pandas as pd

from ichi.indicators.helpers import slope_pct
from ichi.rules.base import RuleResult


class PerfectSetupRule:
    """Meta-rule: fires when multiple bullish conditions align simultaneously.
    Composition: bull_stack AND above_cloud AND future_bull AND chikou_cleared AND
    angle_gte20 AND kj_aligned. [default-guess — tune in M4]"""

    rule_id = "perfect_setup"

    def __call__(self, df: pd.DataFrame, i: int) -> RuleResult:
        if i < 50:
            return RuleResult(rule_id=self.rule_id, state="NotPerfect", label="Not Perfect",
                              qualifies_bull=False, qualifies_bear=False)
        from ichi.indicators.helpers import momentum_angle, swing_pivots

        close = df["close"].iat[i]
        tk = df["tk"].iat[i]
        kj = df["kj"].iat[i]
        span_a = df["span_a"].iat[i]
        span_b = df["span_b"].iat[i]
        span_a_lead = df["span_a_lead"].iat[i]
        span_b_lead = df["span_b_lead"].iat[i]

        bull_stack = close > tk > kj
        above_cloud = close > max(span_a, span_b)
        future_bull = span_a_lead > span_b_lead

        # Chikou cleared: close (chikou value) > last 3 swing highs at chart position i-26
        chikou_index = i - 26
        cleared = False
        if chikou_index >= 5:
            window_start = max(0, chikou_index - 50)
            highs_window = df["high"].iloc[window_start: chikou_index + 1]
            if "_swing_high" in df.columns:
                pivot_mask = df["_swing_high"].iloc[window_start: chikou_index + 1]
                pivot_levels = highs_window[pivot_mask].nlargest(3).values.tolist()
            else:
                pivots = swing_pivots(highs_window, lookback=5, kind="high")
                pivot_levels = highs_window[pivots].nlargest(3).values.tolist()
            cleared = not pivot_levels or all(close > level for level in pivot_levels)

        angle_val = float((df["_momentum_angle"] if "_momentum_angle" in df.columns else momentum_angle(df["close"])).iat[i])
        angle_strong = angle_val >= 20.0

        # KJ aligned with 50-bar trend
        kj_slope = float(slope_pct(df["kj"], 10).iat[i]) if i >= 10 else 0.0
        trend_up = close > df["close"].iat[i - 50]
        kj_aligned = (trend_up and kj_slope > 0) or (not trend_up and kj_slope < 0)

        perfect = bool(bull_stack and above_cloud and future_bull and cleared and angle_strong and kj_aligned)
        return RuleResult(
            rule_id=self.rule_id,
            state="Perfect" if perfect else "NotPerfect",
            label="PERFECT SETUP" if perfect else "Not Perfect",
            qualifies_bull=perfect,
            qualifies_bear=False,
        )


class SanyakuRule:
    """Sanyaku Koten / Gyakuten: fresh three-line convergence within transition_window bars."""

    rule_id = "sanyaku"
    _TRANSITION_WINDOW = 5

    def __call__(self, df: pd.DataFrame, i: int) -> RuleResult:
        if i < 26:
            return RuleResult(rule_id=self.rule_id, state="Neutral", label="Sanyaku N/A",
                              qualifies_bull=False, qualifies_bear=False)

        # All three conditions bullish: price > cloud, TK > KJ, chikou > past price
        def all_bull(j: int) -> bool:
            if j < 26:
                return False
            cloud_top = max(df["span_a"].iat[j], df["span_b"].iat[j])
            return bool(
                df["close"].iat[j] > cloud_top
                and df["tk"].iat[j] > df["kj"].iat[j]
                and df["close"].iat[j] > df["close"].iat[j - 26]
            )

        # Fresh bullish break: all-bull now but not all-bull N bars ago
        currently_bull = all_bull(i)
        was_bull = all_bull(max(0, i - self._TRANSITION_WINDOW))
        fresh_bull = currently_bull and not was_bull

        if fresh_bull:
            return RuleResult(rule_id=self.rule_id, state="BullishBreak",
                              label="Sanyaku Break (bullish)",
                              qualifies_bull=True, qualifies_bear=False)
        elif currently_bull:
            return RuleResult(rule_id=self.rule_id, state="BullishStable",
                              label="Sanyaku Bullish (stable)",
                              qualifies_bull=True, qualifies_bear=False)
        else:
            return RuleResult(rule_id=self.rule_id, state="NoBreak",
                              label="No Active Sanyaku Break",
                              qualifies_bull=False, qualifies_bear=False)


class KumoTrapRule:
    """Price wicked into cloud in last N bars and closed back outside on the bullish side."""

    rule_id = "kumo_trap"
    _LOOKBACK = 5

    def __call__(self, df: pd.DataFrame, i: int) -> RuleResult:
        start = max(0, i - self._LOOKBACK)
        trap_fired = False
        for j in range(start, i + 1):
            span_a_j = df["span_a"].iat[j]
            span_b_j = df["span_b"].iat[j]
            if pd.isna(span_a_j) or pd.isna(span_b_j):
                continue
            cloud_top = max(span_a_j, span_b_j)
            cloud_bot = min(span_a_j, span_b_j)
            low_j = df["low"].iat[j]
            close_j = df["close"].iat[j]
            high_j = df["high"].iat[j]
            # Candle wicked into cloud (high or low entered cloud range) and closed above it
            wicked_in = low_j <= cloud_top and high_j >= cloud_bot
            if wicked_in and close_j > cloud_top:
                trap_fired = True
                break
        return RuleResult(
            rule_id=self.rule_id,
            state="Active" if trap_fired else "None",
            label="Active Kumo Trap Signal" if trap_fired else "No Kumo Trap",
            qualifies_bull=trap_fired,
            qualifies_bear=False,
        )


class CSClearRule:
    """Chikou is in clear space — not overlapping any candle body at its chart position."""

    rule_id = "cs_clear"

    def __call__(self, df: pd.DataFrame, i: int) -> RuleResult:
        chikou_index = i - 26
        if chikou_index < 0:
            return RuleResult(rule_id=self.rule_id, state="Neutral", label="CS Clear (n/a)",
                              qualifies_bull=False, qualifies_bear=False)
        chikou_val = df["close"].iat[i]
        # Body at chikou_index
        body_high = max(df["open"].iat[chikou_index], df["close"].iat[chikou_index])
        body_low = min(df["open"].iat[chikou_index], df["close"].iat[chikou_index])
        # Clear means chikou is above body_high or below body_low
        in_body = body_low <= chikou_val <= body_high
        clear = not in_body
        return RuleResult(
            rule_id=self.rule_id,
            state="Clear" if clear else "Overlapping",
            label="CS in Clear Space" if clear else "CS Overlapping Candles",
            qualifies_bull=bool(clear and chikou_val > body_high),
            qualifies_bear=bool(not clear),
        )


class SSBDirectionRule:
    """SpanB slope — three-state: Rising / Flat / Falling."""

    rule_id = "ssb_direction"
    _LOOKBACK = 10
    _THRESHOLD = 0.3   # % — [default-guess]

    def __call__(self, df: pd.DataFrame, i: int) -> RuleResult:
        if i < self._LOOKBACK:
            return RuleResult(rule_id=self.rule_id, state="Neutral", label="SSB (n/a)",
                              qualifies_bull=False, qualifies_bear=False)
        pct = float((df["_span_b_slope10"] if "_span_b_slope10" in df.columns else slope_pct(df["span_b"], self._LOOKBACK)).iat[i])
        if pct > self._THRESHOLD:
            return RuleResult(rule_id=self.rule_id, state="Rising",
                              label="SSB Rising (long-term bullish)",
                              qualifies_bull=True, qualifies_bear=False, detail=f"{pct:.2f}%")
        elif pct < -self._THRESHOLD:
            return RuleResult(rule_id=self.rule_id, state="Falling",
                              label="SSB Falling",
                              qualifies_bull=False, qualifies_bear=True, detail=f"{pct:.2f}%")
        else:
            return RuleResult(rule_id=self.rule_id, state="Flat",
                              label="SSB Flat",
                              qualifies_bull=False, qualifies_bear=False, detail=f"{pct:.2f}%")


class NoBearSetupRule:
    """Passes when the bear score is low (< 5). Computed by engine after all other rules."""

    rule_id = "no_bear_setup"
    _BEAR_THRESHOLD = 5

    def __call__(self, df: pd.DataFrame, i: int, bear_score: int = 0) -> RuleResult:  # type: ignore[override]
        passes = bear_score < self._BEAR_THRESHOLD
        return RuleResult(
            rule_id=self.rule_id,
            state="Bullish" if passes else "Bearish",
            label=f"No Bear Setup ({bear_score}/18)" if passes else f"Bear Setup Active ({bear_score}/18)",
            qualifies_bull=passes,
            qualifies_bear=not passes,
            detail=str(bear_score),
        )
