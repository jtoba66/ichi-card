import pandas as pd
import pytest

from ichi.indicators.ichimoku import ichimoku


@pytest.fixture
def simple_df() -> pd.DataFrame:
    n = 100
    close = pd.Series([100.0 + i * 0.5 for i in range(n)])
    return pd.DataFrame({
        "open": close - 0.2,
        "high": close + 1.0,
        "low": close - 1.0,
        "close": close,
        "volume": [1000.0] * n,
    })


def test_columns_added(simple_df: pd.DataFrame) -> None:
    result = ichimoku(simple_df)
    for col in ["tk", "kj", "span_a", "span_b", "span_a_lead", "span_b_lead", "chikou"]:
        assert col in result.columns, f"Missing column: {col}"


def test_original_df_unchanged(simple_df: pd.DataFrame) -> None:
    original_cols = set(simple_df.columns)
    ichimoku(simple_df)
    assert set(simple_df.columns) == original_cols


def test_span_a_nan_before_displacement(simple_df: pd.DataFrame) -> None:
    result = ichimoku(simple_df)
    assert result["span_a"].iloc[:26].isna().all()


def test_tk_above_kj_in_uptrend(simple_df: pd.DataFrame) -> None:
    result = ichimoku(simple_df)
    last = result.iloc[-1]
    assert last["tk"] > last["kj"]


def test_chikou_is_close_shifted_back() -> None:
    n = 80
    close = pd.Series([float(i) for i in range(n)])
    df = pd.DataFrame({
        "open": close, "high": close, "low": close,
        "close": close, "volume": close,
    })
    result = ichimoku(df)
    assert result["chikou"].iloc[0] == pytest.approx(26.0)
    assert result["chikou"].iloc[10] == pytest.approx(36.0)
    assert result["chikou"].iloc[-26:].isna().all()


def test_span_a_lead_equals_avg_tk_kj(simple_df: pd.DataFrame) -> None:
    result = ichimoku(simple_df)
    expected = (result["tk"] + result["kj"]) / 2
    pd.testing.assert_series_equal(result["span_a_lead"], expected, check_names=False)
