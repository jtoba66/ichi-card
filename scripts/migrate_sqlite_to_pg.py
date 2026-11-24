"""One-off migration: copy all data from SQLite signals.db into PostgreSQL.

Run on HP after PostgreSQL is set up and init_db() has been called:

    cd ~/ichi-scorecard
    ICHI_DATABASE_URL=postgresql://ichi:ichi@localhost/ichi_signals \
        /home/joe/.local/bin/uv run python scripts/migrate_sqlite_to_pg.py
"""
from __future__ import annotations

import sqlite3
from pathlib import Path

import psycopg2
import psycopg2.extras

# ── Config ────────────────────────────────────────────────────────────────────

SQLITE_PATH = Path(__file__).parents[1] / "data" / "signals.db"

import os
PG_URL = os.environ.get(
    "ICHI_DATABASE_URL",
    "postgresql://ichi:ichi@localhost/ichi_signals",
)


def migrate() -> None:
    if not SQLITE_PATH.exists():
        print(f"SQLite DB not found at {SQLITE_PATH}. Nothing to migrate.")
        return

    print(f"Reading from SQLite: {SQLITE_PATH}")
    sq = sqlite3.connect(SQLITE_PATH)
    sq.row_factory = sqlite3.Row

    pg = psycopg2.connect(PG_URL)

    # ── signal_log ────────────────────────────────────────────────────────────
    rows = sq.execute("SELECT * FROM signal_log").fetchall()
    print(f"  signal_log: {len(rows)} rows")
    with pg.cursor() as cur:
        inserted = 0
        for r in rows:
            r = dict(r)
            cur.execute(
                """
                INSERT INTO signal_log
                    (signal_id, signal_type, signal_subtype, symbol, timeframe,
                     fired_at, entry_price, bull_score, cloud_state, signal_metadata,
                     hosoda_active, hosoda_number, hosoda_pivot_type,
                     return_7d, return_30d, status,
                     exit_tier, exit_condition, exit_bar, exit_price,
                     exit_return, exit_timestamp, warning_log,
                     is_backfill, logged_at, updated_at,
                     mae, mfe, duration_bars)
                VALUES
                    (%(signal_id)s, %(signal_type)s, %(signal_subtype)s, %(symbol)s, %(timeframe)s,
                     %(fired_at)s, %(entry_price)s, %(bull_score)s, %(cloud_state)s, %(signal_metadata)s,
                     %(hosoda_active)s, %(hosoda_number)s, %(hosoda_pivot_type)s,
                     %(return_7d)s, %(return_30d)s, %(status)s,
                     %(exit_tier)s, %(exit_condition)s, %(exit_bar)s, %(exit_price)s,
                     %(exit_return)s, %(exit_timestamp)s, %(warning_log)s,
                     %(is_backfill)s, %(logged_at)s, %(updated_at)s,
                     %(mae)s, %(mfe)s, %(duration_bars)s)
                ON CONFLICT (signal_id) DO NOTHING
                """,
                {
                    "signal_id": r.get("signal_id"),
                    "signal_type": r.get("signal_type"),
                    "signal_subtype": r.get("signal_subtype"),
                    "symbol": r.get("symbol"),
                    "timeframe": r.get("timeframe"),
                    "fired_at": r.get("fired_at"),
                    "entry_price": r.get("entry_price"),
                    "bull_score": r.get("bull_score"),
                    "cloud_state": r.get("cloud_state"),
                    "signal_metadata": r.get("signal_metadata"),
                    "hosoda_active": r.get("hosoda_active"),
                    "hosoda_number": r.get("hosoda_number"),
                    "hosoda_pivot_type": r.get("hosoda_pivot_type"),
                    "return_7d": r.get("return_7d"),
                    "return_30d": r.get("return_30d"),
                    "status": r.get("status"),
                    "exit_tier": r.get("exit_tier"),
                    "exit_condition": r.get("exit_condition"),
                    "exit_bar": r.get("exit_bar"),
                    "exit_price": r.get("exit_price"),
                    "exit_return": r.get("exit_return"),
                    "exit_timestamp": r.get("exit_timestamp"),
                    "warning_log": r.get("warning_log"),
                    "is_backfill": r.get("is_backfill"),
                    "logged_at": r.get("logged_at"),
                    "updated_at": r.get("updated_at"),
                    "mae": r.get("mae"),
                    "mfe": r.get("mfe"),
                    "duration_bars": r.get("duration_bars"),
                },
            )
            inserted += cur.rowcount
    pg.commit()
    print(f"  signal_log: {inserted} rows inserted (skipped duplicates)")

    # ── chikou_levels ─────────────────────────────────────────────────────────
    try:
        rows = sq.execute("SELECT * FROM chikou_levels").fetchall()
        print(f"  chikou_levels: {len(rows)} rows")
        with pg.cursor() as cur:
            inserted = 0
            for r in rows:
                r = dict(r)
                cur.execute(
                    """
                    INSERT INTO chikou_levels
                        (symbol, timeframe, level_price, first_bar, last_bar,
                         touch_count, duration_bars, significance_score,
                         level_type, last_updated)
                    VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)
                    """,
                    (
                        r.get("symbol"), r.get("timeframe"), r.get("level_price"),
                        r.get("first_bar"), r.get("last_bar"), r.get("touch_count"),
                        r.get("duration_bars"), r.get("significance_score"),
                        r.get("level_type"), r.get("last_updated"),
                    ),
                )
                inserted += cur.rowcount
        pg.commit()
        print(f"  chikou_levels: {inserted} rows inserted")
    except Exception as exc:
        print(f"  chikou_levels: skipped ({exc})")

    # ── cooccurrence_log ──────────────────────────────────────────────────────
    try:
        rows = sq.execute("SELECT * FROM cooccurrence_log").fetchall()
        print(f"  cooccurrence_log: {len(rows)} rows")
        with pg.cursor() as cur:
            inserted = 0
            for r in rows:
                r = dict(r)
                cur.execute(
                    """
                    INSERT INTO cooccurrence_log
                        (signal_id_a, signal_id_b, symbol, timeframe, bars_apart, logged_at)
                    VALUES (%s,%s,%s,%s,%s,%s)
                    ON CONFLICT (signal_id_a, signal_id_b) DO NOTHING
                    """,
                    (
                        r.get("signal_id_a"), r.get("signal_id_b"),
                        r.get("symbol"), r.get("timeframe"),
                        r.get("bars_apart"), r.get("logged_at"),
                    ),
                )
                inserted += cur.rowcount
        pg.commit()
        print(f"  cooccurrence_log: {inserted} rows inserted (skipped duplicates)")
    except Exception as exc:
        print(f"  cooccurrence_log: skipped ({exc})")

    sq.close()
    pg.close()
    print("\nMigration complete.")

    # ── Row-count verification ────────────────────────────────────────────────
    print("\nVerification:")
    sq2 = sqlite3.connect(SQLITE_PATH)
    pg2 = psycopg2.connect(PG_URL)
    for table in ("signal_log", "chikou_levels", "cooccurrence_log"):
        try:
            sq_n = sq2.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0]
        except Exception:
            sq_n = "N/A"
        try:
            with pg2.cursor() as cur:
                cur.execute(f"SELECT COUNT(*) FROM {table}")
                pg_n = cur.fetchone()[0]
        except Exception:
            pg_n = "N/A"
        match = "OK" if sq_n == pg_n else "MISMATCH"
        print(f"  {table:25s}  SQLite={sq_n}  PG={pg_n}  {match}")
    sq2.close()
    pg2.close()


if __name__ == "__main__":
    migrate()
