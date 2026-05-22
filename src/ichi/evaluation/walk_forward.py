from __future__ import annotations

from dataclasses import dataclass
from datetime import date, timedelta

import pandas as pd

from ichi.evaluation.ic import decile_spread, information_coefficient


@dataclass
class WalkForwardWindow:
    train_start: date
    train_end: date
    val_start: date
    val_end: date
    ic_1d: float
    ic_7d: float
    ic_30d: float
    n_observations: int


def walk_forward(
    snapshot: pd.DataFrame,
    train_months: int = 18,
    val_months: int = 6,
    step_months: int = 6,
    score_col: str = "grade",
) -> pd.DataFrame:
    """Rolling walk-forward IC analysis.

    Splits snapshot into (train_months) + (val_months) windows, rolls by step_months.
    Computes IC on the validation period only.

    Returns a DataFrame of WalkForwardWindow results, one row per window.
    """
    if snapshot.empty or "date" not in snapshot.columns:
        return pd.DataFrame()

    dates = pd.to_datetime(snapshot["date"])
    global_start = dates.min().date()
    global_end = dates.max().date()

    results: list[dict] = []
    cursor = global_start

    while True:
        train_start = cursor
        train_end = _add_months(cursor, train_months) - timedelta(days=1)
        val_start = train_end + timedelta(days=1)
        val_end = _add_months(val_start, val_months) - timedelta(days=1)

        if val_end > global_end:
            break

        val_mask = (pd.to_datetime(snapshot["date"]).dt.date >= val_start) & \
                   (pd.to_datetime(snapshot["date"]).dt.date <= val_end)
        val_data = snapshot[val_mask]

        if len(val_data) < 20:
            cursor = _add_months(cursor, step_months)
            continue

        results.append({
            "train_start": train_start,
            "train_end": train_end,
            "val_start": val_start,
            "val_end": val_end,
            "ic_1d": information_coefficient(val_data, score_col, "fwd_return_1d"),
            "ic_7d": information_coefficient(val_data, score_col, "fwd_return_7d"),
            "ic_30d": information_coefficient(val_data, score_col, "fwd_return_30d"),
            "n_observations": len(val_data),
        })
        cursor = _add_months(cursor, step_months)

    return pd.DataFrame(results)


def walk_forward_summary(wf: pd.DataFrame) -> dict[str, float | int]:
    """Aggregate walk-forward results into a single report dict."""
    if wf.empty:
        return {}
    return {
        "n_windows": len(wf),
        "mean_ic_1d": float(wf["ic_1d"].mean()),
        "mean_ic_7d": float(wf["ic_7d"].mean()),
        "mean_ic_30d": float(wf["ic_30d"].mean()),
        "std_ic_30d": float(wf["ic_30d"].std()),
        "min_ic_30d": float(wf["ic_30d"].min()),
        "max_ic_30d": float(wf["ic_30d"].max()),
        "pct_positive_30d": float((wf["ic_30d"] > 0).mean()),
        "total_observations": int(wf["n_observations"].sum()),
    }


def _add_months(d: date, months: int) -> date:
    month = d.month - 1 + months
    year = d.year + month // 12
    month = month % 12 + 1
    import calendar
    day = min(d.day, calendar.monthrange(year, month)[1])
    return date(year, month, day)
