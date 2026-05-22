"""Unit tests for signal-ic TF split (Fix 1) and signal-equity simulation (Fix 2).

Validates logic in isolation using synthetic signal_log rows — does NOT touch
the real signals.db or run a full backfill.
"""
from __future__ import annotations

import sys
import os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

from ichi.signal.jobs import (
    _TF_SORT,
    _simulate_equity,
    run_signal_ic,
    run_signal_equity,
)
from unittest.mock import patch


# ── Synthetic data ────────────────────────────────────────────────────────────

def _make_row(
    signal_type: int,
    timeframe: str,
    status: str = "CLOSED",
    return_30d: float | None = 5.0,
    exit_return: float | None = 4.0,
    exit_bar: int | None = 15,
    bull_score: int = 13,
    hosoda_active: bool = False,
    mae: float | None = -3.0,
    mfe: float | None = 8.0,
    duration_bars: int | None = 15,
    fired_at: str = "2024-01-01T00:00:00+00:00",
) -> dict:
    return {
        "signal_type": signal_type,
        "timeframe": timeframe,
        "symbol": "BTCUSDT",
        "status": status,
        "return_30d": return_30d,
        "exit_return": exit_return,
        "exit_bar": exit_bar,
        "bull_score": bull_score,
        "hosoda_active": hosoda_active,
        "mae": mae,
        "mfe": mfe,
        "duration_bars": duration_bars,
        "fired_at": fired_at,
        "signal_id": f"SIG{signal_type}_TEST_{timeframe}_{fired_at}",
    }


def _make_dataset() -> list[dict]:
    """20 rows: 2 signal types (1, 2) × 2 timeframes (1d, 4h), 5 rows each."""
    rows = []
    dates = [
        "2024-01-01T00:00:00+00:00",
        "2024-02-01T00:00:00+00:00",
        "2024-03-01T00:00:00+00:00",
        "2024-04-01T00:00:00+00:00",
        "2024-05-01T00:00:00+00:00",
    ]
    for sig_type in (1, 2):
        for tf in ("1d", "4h"):
            for i, d in enumerate(dates):
                # alternate wins and losses so stats are interesting
                exit_ret = 6.0 if i % 2 == 0 else -2.0
                rows.append(_make_row(
                    signal_type=sig_type,
                    timeframe=tf,
                    exit_return=exit_ret,
                    return_30d=exit_ret,
                    fired_at=d,
                ))
    return rows


# ── Fix 1: signal-ic TF split ─────────────────────────────────────────────────

def test_signal_ic_tf_split():
    """run_signal_ic must produce one row per (signal_type, timeframe)."""
    rows = _make_dataset()

    with patch("ichi.signal.jobs.sqlite3") as mock_sqlite:
        # Wire mock so the SELECT returns our synthetic rows
        mock_conn = mock_sqlite.connect.return_value.__enter__.return_value
        mock_conn = mock_sqlite.connect.return_value
        mock_conn.row_factory = None
        mock_conn.execute.return_value.fetchall.return_value = rows

        # run_signal_ic opens its own connection; monkeypatch at module level
        import ichi.signal.jobs as jobs
        original = jobs.sqlite3
        try:
            import sqlite3 as _real_sqlite3

            class _FakeConn:
                row_factory = None
                def execute(self, *a, **kw):
                    class _Cursor:
                        def fetchall(self_):
                            return rows
                    return _Cursor()
                def close(self): pass

            class _FakeSqlite:
                Row = dict
                @staticmethod
                def connect(*a, **kw):
                    return _FakeConn()
                OperationalError = _real_sqlite3.OperationalError

            jobs.sqlite3 = _FakeSqlite
            results = jobs.run_signal_ic(verbose=False)
        finally:
            jobs.sqlite3 = original

    # Expect 4 rows: (1,1d), (1,4h), (2,1d), (2,4h)
    assert len(results) == 4, f"Expected 4 rows, got {len(results)}: {[(r['signal_type'],r['timeframe']) for r in results]}"

    keys = [(r["signal_type"], r["timeframe"]) for r in results]
    assert (1, "1d") in keys
    assert (1, "4h") in keys
    assert (2, "1d") in keys
    assert (2, "4h") in keys

    # Verify sort order: signal_type ASC, then tf by _TF_SORT (1w→1d→4h)
    for i, r in enumerate(results):
        if i > 0:
            prev = results[i - 1]
            assert (r["signal_type"], _TF_SORT.get(r["timeframe"], 99)) >= (
                prev["signal_type"], _TF_SORT.get(prev["timeframe"], 99)
            ), f"Sort order wrong at index {i}: {prev} → {r}"

    print(f"  PASS: signal-ic TF split — {len(results)} rows, correct keys and sort order")


# ── Fix 2: equity simulation ───────────────────────────────────────────────────

def test_simulate_equity_basic():
    """_simulate_equity must compute correct final return and detect ruin."""
    # 5 trades all winning +10%
    all_wins = [{"exit_return": 10.0}] * 5
    result = _simulate_equity(all_wins, position_size=10.0)
    # capital = 1.0 * (1.01)^5
    expected = (1.01 ** 5 - 1) * 100
    assert abs(result["final_return"] - expected) < 0.01, f"final_return mismatch: {result['final_return']:.4f} vs {expected:.4f}"
    assert result["max_drawdown"] == 0.0
    assert result["max_consec_loss"] == 0
    assert not result["ruined"]
    print(f"  PASS: all-win equity  final={result['final_return']:+.2f}%  dd={result['max_drawdown']:.2f}%")


def test_simulate_equity_ruin():
    """Capital should drop below 50% with extreme position size on large-loss trades.

    20% size × -50% return → each trade: capital × (1 - 0.20*0.50) = capital × 0.90
    After 8 trades: 0.90^8 ≈ 0.43 < 0.50 → ruined.
    """
    all_losses = [{"exit_return": -50.0}] * 10
    result = _simulate_equity(all_losses, position_size=20.0)
    assert result["ruined"], (
        f"Should be ruined: 20% size × -50% return × 10 trades, "
        f"capital ended at {1.0 + result['final_return']/100:.3f}x"
    )
    assert result["max_consec_loss"] == 10
    print(f"  PASS: ruin detection — capital dropped to {1.0 + result['final_return']/100:.3f}x")


def test_simulate_equity_max_dd_duration():
    """max_dd_duration tracks longest stretch below equity peak."""
    # peak at trade 0, then 4 losses, then recovery
    trades = (
        [{"exit_return": 10.0}]    # peak
        + [{"exit_return": -2.0}] * 4   # 4 bars below peak
        + [{"exit_return": 20.0}]  # recovery
    )
    result = _simulate_equity(trades, position_size=5.0)
    assert result["max_dd_duration"] == 4, f"Expected max_dd_duration=4, got {result['max_dd_duration']}"
    print(f"  PASS: dd duration={result['max_dd_duration']} (expected 4)")


def test_run_signal_equity_skips_under_30():
    """run_signal_equity must skip combos with fewer than 30 closed instances."""
    # Only 5 rows per combo — should all be skipped
    rows = _make_dataset()  # 5 per (type, tf) → below 30 threshold

    import ichi.signal.jobs as jobs
    original = jobs.sqlite3
    try:
        import sqlite3 as _real_sqlite3

        class _FakeConn2:
            row_factory = None
            def execute(self, *a, **kw):
                class _Cursor:
                    def fetchall(self_):
                        return rows
                return _Cursor()
            def close(self): pass

        class _FakeSqlite2:
            Row = dict
            @staticmethod
            def connect(*a, **kw):
                return _FakeConn2()
            OperationalError = _real_sqlite3.OperationalError

        jobs.sqlite3 = _FakeSqlite2
        results = jobs.run_signal_equity(verbose=False)
    finally:
        jobs.sqlite3 = original

    assert results == [], f"Expected empty results (all combos <30), got {len(results)}"
    print("  PASS: signal-equity correctly skips combos with <30 closed instances")


def test_run_signal_equity_runs_on_large_sample():
    """run_signal_equity must run without errors when combos meet the 30-instance threshold."""
    # 35 rows per (type, tf) to pass the threshold
    rows = []
    dates = [f"2024-{str(i+1).zfill(2)}-01T00:00:00+00:00" for i in range(12)]
    extra = [f"2025-{str(i+1).zfill(2)}-01T00:00:00+00:00" for i in range(23)]
    all_dates = dates + extra

    for sig_type in (1, 2):
        for tf in ("1d", "4h"):
            for i, d in enumerate(all_dates):
                exit_ret = 5.0 if i % 3 != 0 else -3.0
                rows.append(_make_row(
                    signal_type=sig_type,
                    timeframe=tf,
                    exit_return=exit_ret,
                    return_30d=exit_ret,
                    fired_at=d,
                ))

    import ichi.signal.jobs as jobs
    original = jobs.sqlite3
    try:
        import sqlite3 as _real_sqlite3

        class _FakeConn3:
            row_factory = None
            def execute(self, *a, **kw):
                class _Cursor:
                    def fetchall(self_):
                        return rows
                return _Cursor()
            def close(self): pass

        class _FakeSqlite3:
            Row = dict
            @staticmethod
            def connect(*a, **kw):
                return _FakeConn3()
            OperationalError = _real_sqlite3.OperationalError

        jobs.sqlite3 = _FakeSqlite3
        results = jobs.run_signal_equity(verbose=False)
    finally:
        jobs.sqlite3 = original

    assert len(results) == 4, f"Expected 4 combos, got {len(results)}"
    for r in results:
        assert len(r["simulations"]) == len(jobs._POSITION_SIZES)
        assert "ruin_threshold" in r
    print(f"  PASS: signal-equity ran on {len(results)} combos with 35 trades each — no errors")


# ── Runner ────────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    print("\n=== Running signal jobs fix tests ===\n")
    test_signal_ic_tf_split()
    test_simulate_equity_basic()
    test_simulate_equity_ruin()
    test_simulate_equity_max_dd_duration()
    test_run_signal_equity_skips_under_30()
    test_run_signal_equity_runs_on_large_sample()
    print("\nAll tests passed.")
