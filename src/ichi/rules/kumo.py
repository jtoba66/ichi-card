import pandas as pd

from ichi.indicators.helpers import slope_pct
from ichi.rules.base import RuleResult


class KumoBullishRule:
    rule_id = "kumo_bullish"

    def __call__(self, df: pd.DataFrame, i: int) -> RuleResult:
        is_bull = bool(df["span_a"].iat[i] > df["span_b"].iat[i])
        return RuleResult(
            rule_id=self.rule_id,
            state="Bullish" if is_bull else "Bearish",
            label="Cloud Bullish" if is_bull else "Cloud Bearish",
            qualifies_bull=is_bull,
            qualifies_bear=not is_bull,
        )


class FutureBullRule:
    rule_id = "future_bull"

    def __call__(self, df: pd.DataFrame, i: int) -> RuleResult:
        is_bull = bool(df["span_a_lead"].iat[i] > df["span_b_lead"].iat[i])
        return RuleResult(
            rule_id=self.rule_id,
            state="Bullish" if is_bull else "Bearish",
            label="Future Bull" if is_bull else "Future Bear",
            qualifies_bull=is_bull,
            qualifies_bear=not is_bull,
        )


class CloudCurlingRule:
    """Three-state: current cloud bearish (or just turned) + future bull + SpanA_lead rising
    → 'Cloud Curling Up +' (powerful reversal signal)."""

    rule_id = "cloud_curling"
    _JUST_TURNED_BARS = 5
    _SLOPE_LOOKBACK = 5

    def __call__(self, df: pd.DataFrame, i: int) -> RuleResult:
        if i < self._SLOPE_LOOKBACK:
            return RuleResult(rule_id=self.rule_id, state="Neutral", label="Cloud (n/a)",
                              qualifies_bull=False, qualifies_bear=False)

        span_a = df["span_a"].iat[i]
        span_b = df["span_b"].iat[i]
        span_a_lead = df["span_a_lead"].iat[i]
        span_b_lead = df["span_b_lead"].iat[i]

        current_bearish = span_b > span_a
        future_bull = span_a_lead > span_b_lead

        # Check if cloud just turned bullish in the last N bars
        just_turned = False
        if not current_bearish:
            for k in range(1, self._JUST_TURNED_BARS + 1):
                if i - k >= 0 and df["span_b"].iat[i - k] > df["span_a"].iat[i - k]:
                    just_turned = True
                    break

        span_a_lead_slope = float(slope_pct(df["span_a_lead"], self._SLOPE_LOOKBACK).iat[i])
        lead_rising = span_a_lead_slope > 0

        curling = bool((current_bearish or just_turned) and future_bull and lead_rising)

        if curling:
            return RuleResult(rule_id=self.rule_id, state="CurlingUp",
                              label="Cloud Curling Up +",
                              qualifies_bull=True, qualifies_bear=False)
        elif current_bearish and not future_bull:
            return RuleResult(rule_id=self.rule_id, state="Bearish",
                              label="Cloud Bearish (no reversal)",
                              qualifies_bull=False, qualifies_bear=True)
        else:
            return RuleResult(rule_id=self.rule_id, state="Neutral",
                              label="Cloud Stable",
                              qualifies_bull=False, qualifies_bear=False)


class FwdThickRule:
    """Forward cloud thickness > 1% of price — indicates strong directional conviction."""

    rule_id = "fwd_thick"
    _THRESHOLD = 0.01   # 1% — [default-guess]

    def __call__(self, df: pd.DataFrame, i: int) -> RuleResult:
        span_a_lead = df["span_a_lead"].iat[i]
        span_b_lead = df["span_b_lead"].iat[i]
        close = df["close"].iat[i]
        if pd.isna(span_a_lead) or pd.isna(span_b_lead) or close == 0:
            return RuleResult(rule_id=self.rule_id, state="Neutral", label="Fwd Cloud (n/a)",
                              qualifies_bull=False, qualifies_bear=False)
        thickness = abs(span_a_lead - span_b_lead) / close
        thick = bool(thickness > self._THRESHOLD)
        # Only counts as bullish when the forward cloud is also bullish
        fwd_bull = span_a_lead > span_b_lead
        qualifies = bool(thick and fwd_bull)
        return RuleResult(
            rule_id=self.rule_id,
            state="Thick" if thick else "Thin",
            label=f"Fwd Cloud Thick ({thickness*100:.1f}%)" if thick else f"Fwd Cloud Thin ({thickness*100:.1f}%)",
            qualifies_bull=qualifies,
            qualifies_bear=bool(thick and not fwd_bull),
            detail=f"{thickness*100:.1f}%",
        )
