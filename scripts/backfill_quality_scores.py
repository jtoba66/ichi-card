"""
Backfill quality_score for all existing signals.
=========================================================
Loads each signal from signal_log, re-runs the scoring engine
at the entry bar, and computes quality_score using the IC lookup table.

Run once after deploying the quality_score column:
    cd ~/ichi-scorecard
    uv run python scripts/backfill_quality_scores.py

Progress is printed to stdout. Safe to re-run (skips already-scored signals).
"""
from __future__ import annotations

import os
import sys
from collections import defaultdict

import psycopg2
import psycopg2.extras

sys.stdout.reconfigure(line_buffering=True)  # type: ignore[attr-defined]

db_url = os.environ.get("ICHI_DATABASE_URL", "postgresql://ichi:ichi@localhost/ichi_signals")

print("Loading signals without quality_score...")
conn = psycopg2.connect(db_url)
with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
    cur.execute("""
        SELECT signal_id, signal_type, symbol, timeframe, fired_at, entry_price
        FROM signal_log
        WHERE quality_score IS NULL
        ORDER BY fired_at ASC
    """)
    signals = [dict(r) for r in cur.fetchall()]
conn.close()

print(f"  {len(signals)} signals need quality_score.")
if not signals:
    print("Nothing to do.")
    sys.exit(0)

# Group by (symbol, timeframe) to fetch OHLCV once per pair
by_sym_tf: dict[tuple, list] = defaultdict(list)
for sig in signals:
    by_sym_tf[(sig["symbol"], sig["timeframe"])].append(sig)

print(f"  {len(by_sym_tf)} unique (symbol, timeframe) pairs.")

from ichi.data.fetcher import fetch_ohlcv
from ichi.indicators.ichimoku import ichimoku
from ichi.indicators.precompute import precompute
from ichi.rules.registry import RuleRegistry
from ichi.scoring.engine import evaluate
from ichi.scoring.quality import compute_quality_score
from ichi.signal.jobs import _find_bar_by_timestamp

registry = RuleRegistry.canonical()

processed = skipped = fetch_errors = updated = 0
total = len(by_sym_tf)

# Collect updates in batches
BATCH_SIZE = 500
updates: list[tuple] = []   # (quality_score, signal_id)


def flush_updates(updates):
    if not updates:
        return
    conn2 = psycopg2.connect(db_url)
    try:
        with conn2.cursor() as cur:
            cur.executemany(
                "UPDATE signal_log SET quality_score = %s WHERE signal_id = %s",
                updates,
            )
        conn2.commit()
    finally:
        conn2.close()


for idx, ((symbol, timeframe), sigs) in enumerate(by_sym_tf.items()):
    if idx % 50 == 0:
        print(f"  [{idx+1}/{total}] {symbol} {timeframe}  (updated {updated} so far)")

    try:
        pair = symbol.replace("USDT", "/USDT")
        df = fetch_ohlcv(pair, timeframe)
        df = ichimoku(df)
        df = precompute(df)
    except Exception as exc:
        fetch_errors += 1
        if fetch_errors <= 5:
            print(f"  [fetch error] {symbol} {timeframe}: {exc}")
        skipped += len(sigs)
        continue

    for sig in sigs:
        entry_bar = _find_bar_by_timestamp(df, sig["fired_at"])
        if entry_bar is None or entry_bar < 1:
            skipped += 1
            continue

        try:
            scorecard = evaluate(df, entry_bar, registry)
        except Exception:
            skipped += 1
            continue

        fired_rules = {r.rule_id for r in scorecard.rules if r.qualifies_bull}
        qs = compute_quality_score(sig["signal_type"], timeframe, fired_rules)

        updates.append((qs, sig["signal_id"]))
        processed += 1
        updated += 1

        if len(updates) >= BATCH_SIZE:
            flush_updates(updates)
            updates.clear()

# Final flush
flush_updates(updates)

print(f"\nDone. Processed: {processed}  Skipped: {skipped}  Fetch errors: {fetch_errors}")
print(f"Total quality_score rows updated: {updated}")

# Quick sanity check
conn3 = psycopg2.connect(db_url)
with conn3.cursor() as cur:
    cur.execute("SELECT COUNT(*) FROM signal_log WHERE quality_score IS NOT NULL AND quality_score > 0")
    n_nonzero = cur.fetchone()[0]
    cur.execute("SELECT COUNT(*) FROM signal_log WHERE quality_score IS NOT NULL")
    n_total = cur.fetchone()[0]
conn3.close()
print(f"DB check: {n_nonzero} signals with quality_score>0  /  {n_total} total scored")
