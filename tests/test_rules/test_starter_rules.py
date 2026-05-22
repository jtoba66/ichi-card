import pandas as pd
import pytest

from ichi.indicators.ichimoku import ichimoku
from ichi.rules.kumo import FutureBullRule, KumoBullishRule
from ichi.rules.trend_position import AboveCloudRule, AboveKijunRule, BullStackRule, TKBullishRule


def _make_df(close: float, tk: float, kj: float, span_a: float, span_b: float) -> pd.DataFrame:
    """Build a minimal one-bar DataFrame with pre-set indicator columns."""
    return pd.DataFrame({
        "open": [close - 1],
        "high": [close + 1],
        "low": [close - 1],
        "close": [close],
        "volume": [1000.0],
        "tk": [tk],
        "kj": [kj],
        "span_a": [span_a],
        "span_b": [span_b],
        "span_a_lead": [span_a + 1],
        "span_b_lead": [span_b],
        "chikou": [close],
    })


class TestAboveCloudRule:
    def test_bullish(self) -> None:
        df = _make_df(close=110, tk=105, kj=100, span_a=90, span_b=85)
        result = AboveCloudRule()(df, 0)
        assert result.qualifies_bull is True
        assert result.qualifies_bear is False
        assert result.label == "Above Cloud"

    def test_bearish(self) -> None:
        df = _make_df(close=80, tk=85, kj=90, span_a=95, span_b=100)
        result = AboveCloudRule()(df, 0)
        assert result.qualifies_bull is False
        assert result.qualifies_bear is True
        assert result.label == "Below Cloud"


class TestAboveKijunRule:
    def test_bullish(self) -> None:
        df = _make_df(close=110, tk=105, kj=100, span_a=90, span_b=85)
        result = AboveKijunRule()(df, 0)
        assert result.qualifies_bull is True

    def test_bearish(self) -> None:
        df = _make_df(close=90, tk=95, kj=100, span_a=105, span_b=110)
        result = AboveKijunRule()(df, 0)
        assert result.qualifies_bear is True


class TestTKBullishRule:
    def test_tk_above_kj(self) -> None:
        df = _make_df(close=110, tk=105, kj=100, span_a=90, span_b=85)
        result = TKBullishRule()(df, 0)
        assert result.qualifies_bull is True

    def test_tk_below_kj(self) -> None:
        df = _make_df(close=110, tk=95, kj=100, span_a=90, span_b=85)
        result = TKBullishRule()(df, 0)
        assert result.qualifies_bear is True


class TestBullStackRule:
    def test_full_bull_stack(self) -> None:
        df = _make_df(close=110, tk=105, kj=100, span_a=90, span_b=85)
        result = BullStackRule()(df, 0)
        assert result.qualifies_bull is True
        assert "P > TK > KJ" in result.label

    def test_no_stack_close_below_tk(self) -> None:
        df = _make_df(close=102, tk=105, kj=100, span_a=90, span_b=85)
        result = BullStackRule()(df, 0)
        assert result.qualifies_bull is False


class TestKumoBullishRule:
    def test_bullish_cloud(self) -> None:
        df = _make_df(close=110, tk=105, kj=100, span_a=95, span_b=85)
        result = KumoBullishRule()(df, 0)
        assert result.qualifies_bull is True
        assert result.label == "Cloud Bullish"

    def test_bearish_cloud(self) -> None:
        df = _make_df(close=110, tk=105, kj=100, span_a=80, span_b=90)
        result = KumoBullishRule()(df, 0)
        assert result.qualifies_bear is True
        assert result.label == "Cloud Bearish"


class TestFutureBullRule:
    def test_future_bull(self) -> None:
        # span_a_lead > span_b_lead → future bull
        df = _make_df(close=110, tk=105, kj=100, span_a=90, span_b=85)
        # span_a_lead is set to span_a + 1 = 91, span_b_lead = span_b = 85 in _make_df
        result = FutureBullRule()(df, 0)
        assert result.qualifies_bull is True

    def test_future_bear(self) -> None:
        df = pd.DataFrame({
            "close": [80.0], "open": [79.0], "high": [81.0], "low": [79.0],
            "volume": [1000.0], "tk": [85.0], "kj": [90.0],
            "span_a": [70.0], "span_b": [75.0],
            "span_a_lead": [70.0], "span_b_lead": [80.0],  # span_b_lead > span_a_lead
            "chikou": [80.0],
        })
        result = FutureBullRule()(df, 0)
        assert result.qualifies_bear is True
