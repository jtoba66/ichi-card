"""Pre-fetch and cache OHLCV data for all universe symbols.

Usage:
    ichi refresh
    ichi refresh --timeframes 1d,4h,1w --top 50 --workers 8
"""
from __future__ import annotations

import time
from concurrent.futures import ThreadPoolExecutor, as_completed

import click

from ichi.data.fetcher import fetch_ohlcv
from ichi.data.universe import top_n_by_marketcap


def _fetch_one(symbol: str, timeframe: str) -> tuple[str, str, int, float, str | None]:
    """Fetch a single symbol/timeframe. Returns (symbol, tf, rows, elapsed, error_msg)."""
    t0 = time.time()
    try:
        df = fetch_ohlcv(symbol, timeframe)
        elapsed = time.time() - t0
        return symbol, timeframe, len(df), elapsed, None
    except Exception as exc:
        elapsed = time.time() - t0
        return symbol, timeframe, 0, elapsed, str(exc)


@click.command(name="refresh")
@click.option(
    "--timeframes",
    default="1d",
    show_default=True,
    help="Comma-separated timeframes to fetch, e.g. 1d,4h,1w",
)
@click.option(
    "--top",
    default=200,
    show_default=True,
    type=int,
    help="Number of top pairs by market cap to fetch",
)
@click.option(
    "--workers",
    default=8,
    show_default=True,
    type=int,
    help="Number of parallel worker threads",
)
def refresh(timeframes: str, top: int, workers: int) -> None:
    """Pre-fetch and cache OHLCV data so morning scan runs from cache."""
    tf_list = [tf.strip() for tf in timeframes.split(",") if tf.strip()]
    total_tasks = top * len(tf_list)

    click.echo(
        f"Refreshing {top} symbols × {len(tf_list)} timeframe(s) ({workers} workers)…\n"
    )

    symbols = top_n_by_marketcap(n=top)
    tasks = [(sym, tf) for sym in symbols for tf in tf_list]

    updated = 0
    errors = 0
    wall_start = time.time()

    with ThreadPoolExecutor(max_workers=workers) as pool:
        futures = {pool.submit(_fetch_one, sym, tf): (sym, tf) for sym, tf in tasks}
        for fut in as_completed(futures):
            symbol, tf, rows, elapsed, err = fut.result()
            sym_display = symbol.ljust(12)
            tf_display = tf.ljust(4)
            if err is None:
                rows_display = f"{rows:,}"
                click.echo(
                    f"  ✓ {sym_display}  {tf_display}  {rows_display} rows  ({elapsed:.1f}s)"
                )
                updated += 1
            else:
                click.echo(
                    f"  ✗ {sym_display}  {tf_display}  fetch failed: {err}"
                )
                errors += 1

    wall_elapsed = time.time() - wall_start
    click.echo(
        f"\nDone in {wall_elapsed:.0f}s — {updated}/{total_tasks} updated, {errors} errors."
    )
