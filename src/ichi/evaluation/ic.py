from __future__ import annotations

import pandas as pd
from scipy.stats import spearmanr


def information_coefficient(
    snapshot: pd.DataFrame,
    score_col: str = "grade",
    return_col: str = "fwd_return_30d",
) -> float:
    """Spearman rank correlation between score and forward return.

    Drops rows where either column is NaN before computing.
    Returns float in [-1, 1]; positive = score predicts returns.
    """
    clean = snapshot[[score_col, return_col]].dropna()
    if len(clean) < 10:
        return float("nan")
    rho, _ = spearmanr(clean[score_col], clean[return_col])
    return float(rho)


def decile_spread(
    snapshot: pd.DataFrame,
    score_col: str = "grade",
    return_col: str = "fwd_return_30d",
    n_buckets: int = 10,
) -> pd.DataFrame:
    """Bucket observations by score into n_buckets quantiles.
    Returns a DataFrame with columns: [bucket, mean_return, count, score_min, score_max].

    A monotonically increasing mean_return across buckets = scorecard has signal.
    """
    clean = snapshot[[score_col, return_col]].dropna().copy()
    if len(clean) < n_buckets * 2:
        return pd.DataFrame()

    clean["bucket"] = pd.qcut(clean[score_col], q=n_buckets, labels=False, duplicates="drop")
    summary = (
        clean.groupby("bucket")
        .agg(
            mean_return=(return_col, "mean"),
            count=(return_col, "count"),
            score_min=(score_col, "min"),
            score_max=(score_col, "max"),
        )
        .reset_index()
    )
    summary["mean_return_pct"] = summary["mean_return"] * 100
    return summary


def ic_summary(snapshot: pd.DataFrame) -> dict[str, float]:
    """Compute IC for all three forward-return horizons."""
    return {
        "ic_1d": information_coefficient(snapshot, return_col="fwd_return_1d"),
        "ic_7d": information_coefficient(snapshot, return_col="fwd_return_7d"),
        "ic_30d": information_coefficient(snapshot, return_col="fwd_return_30d"),
    }
