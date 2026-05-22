"""Multi-timeframe scanner CLI command.

Usage:
    ichi mtfscan
    ichi mtfscan --timeframes 4h,1d,1w --top 30
    ichi mtfscan --min-aligned 2
    ichi mtfscan --params custom.yaml
"""
from __future__ import annotations

import logging
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import date

import click

from ichi.calibration.params import apply_params, load_params
from ichi.data.fetcher import fetch_ohlcv
from ichi.data.universe import top_n_by_marketcap
from ichi.indicators.ichimoku import ichimoku
from ichi.indicators.precompute import precompute
from ichi.rules.registry import RuleRegistry
from ichi.scoring.engine import Scorecard, evaluate

logger = logging.getLogger(__name__)


# ── Helpers ───────────────────────────────────────────────────────────────────

def _regime_icon(adx: float) -> str:
    if adx >= 40:
        return "🔥"
    if adx >= 25:
        return "↗"
    return "~"


def _score_symbol_tf(sym: str, timeframe: str, registry: RuleRegistry) -> dict | None:
    """Score a single symbol on a single timeframe. Returns None on failure."""
    try:
        df = fetch_ohlcv(sym, timeframe)
        if df is None or df.empty or len(df) < 60:
            return None
        df = ichimoku(df)
        precompute(df)
        i = len(df) - 1
        sc: Scorecard = evaluate(df, i, registry)
        adx_val = (
            float(df["_adx"].iat[i])
            if "_adx" in df.columns and not df["_adx"].isna().iat[i]
            else 0.0
        )
        return {
            "symbol": sym,
            "timeframe": timeframe,
            "bull": sc.bull_score,
            "total": sc.total_scoring_rules,
            "grade": sc.grade,
            "adx": adx_val,
        }
    except Exception as exc:
        logger.warning("%s [%s]: %s", sym, timeframe, exc)
        return None


def _score_all(
    symbols: list[str],
    timeframes: list[str],
    registry: RuleRegistry,
    workers: int,
) -> dict[str, dict[str, dict]]:
    """Return nested dict: results[symbol][timeframe] = row-dict."""
    results: dict[str, dict[str, dict]] = {sym: {} for sym in symbols}

    tasks = [(sym, tf) for sym in symbols for tf in timeframes]

    with ThreadPoolExecutor(max_workers=workers) as pool:
        futures = {
            pool.submit(_score_symbol_tf, sym, tf, registry): (sym, tf)
            for sym, tf in tasks
        }
        for fut in as_completed(futures):
            sym, tf = futures[fut]
            row = fut.result()
            if row:
                results[sym][tf] = row

    return results


# ── Output formatting ─────────────────────────────────────────────────────────

def _cell_str(row: dict | None) -> str:
    """Format a single score cell: '14/18 ↗' or '  —  ' if missing."""
    if row is None:
        return "   —   "
    icon = _regime_icon(row["adx"])
    return f"{row['bull']}/{row['total']} {icon}"


def _print_table(
    symbols: list[str],
    timeframes: list[str],
    results: dict[str, dict[str, dict]],
    min_aligned: int,
    today: str,
) -> list[str]:
    """Print the main results table. Returns list of fully-aligned symbols."""
    click.echo(f"\nMulti-TF Scanner — {today}\n")

    # Column widths
    tf_col_w = 12  # enough for "14/18 🔥" (emoji counts as 2)
    sym_col_w = 12

    # Header
    header_parts = [f"  {'Symbol':<{sym_col_w}}"]
    for tf in timeframes:
        header_parts.append(f"{'':>2}{tf:<{tf_col_w}}")
    header_parts.append(f"  {'Aligned':>8}  {'Avg':>5}")
    click.echo("".join(header_parts))

    sep_len = sym_col_w + 4 + len(timeframes) * (tf_col_w + 2) + 20
    click.echo("  " + "─" * sep_len)

    # Build sortable rows
    display_rows: list[tuple[int, float, str, list[str]]] = []
    fully_aligned: list[str] = []

    for sym in symbols:
        tf_data = results.get(sym, {})
        grades: list[float] = []
        aligned = 0
        cells: list[str] = []

        for tf in timeframes:
            row = tf_data.get(tf)
            cells.append(_cell_str(row))
            if row is not None:
                grades.append(row["grade"])
                if row["grade"] >= 0.6:
                    aligned += 1

        if not grades:
            continue

        avg_grade = sum(grades) / len(grades)
        n_tfs = len(timeframes)
        aligned_str = f"{aligned}/{n_tfs}"
        avg_pct = f"{avg_grade * 100:.0f}%"
        display_rows.append((aligned, avg_grade, sym, cells, aligned_str, avg_pct))

        if aligned == n_tfs:
            fully_aligned.append(sym)

    # Sort: aligned desc, avg_grade desc
    display_rows.sort(key=lambda r: (r[0], r[1]), reverse=True)

    # Filter by min-aligned
    shown = 0
    for aligned, avg_grade, sym, cells, aligned_str, avg_pct in display_rows:
        if aligned < min_aligned:
            continue
        short = sym.replace("/USDT", "")
        line = f"  {short:<{sym_col_w}}"
        for cell in cells:
            line += f"  {cell:<{tf_col_w}}"
        line += f"  {aligned_str:>8}  {avg_pct:>5}"
        click.echo(line)
        shown += 1

    if shown == 0:
        click.echo(f"  (no symbols with ≥ {min_aligned} aligned timeframes)")

    click.echo()
    return fully_aligned


def _print_summary(
    fully_aligned: list[str],
    timeframes: list[str],
    results: dict[str, dict[str, dict]],
) -> None:
    tf_label = "+".join(timeframes)
    click.echo(f"Full alignment (all TFs bullish):")
    if not fully_aligned:
        click.echo(f"  (none — no symbol is bullish across all {len(timeframes)} timeframes)")
    else:
        for sym in fully_aligned:
            tf_data = results[sym]
            scores = "→".join(
                str(tf_data[tf]["bull"]) if tf in tf_data else "?" for tf in timeframes
            )
            short = sym.replace("/USDT", "")
            click.echo(f"  {short:<12} {scores}  ({tf_label} all ≥ 60%)")
    click.echo()


# ── Command ───────────────────────────────────────────────────────────────────

@click.command("mtfscan")
@click.option(
    "--timeframes", "-t",
    default="4h,1d,1w",
    show_default=True,
    help="Comma-separated list of timeframes to scan",
)
@click.option("--top", "-n", default=200, show_default=True, help="Number of pairs to scan")
@click.option(
    "--min-aligned",
    default=0,
    show_default=True,
    help="Only show symbols with this many aligned (bullish) timeframes",
)
@click.option("--workers", default=8, show_default=True, help="Parallel fetch workers")
@click.option("--params", "params_path", default=None, help="Path to params.yaml")
def mtfscan(
    timeframes: str,
    top: int,
    min_aligned: int,
    workers: int,
    params_path: str | None,
) -> None:
    """Multi-timeframe scanner: rank pairs by Ichimoku bull score across TFs.

    A timeframe is 'aligned bullish' when grade >= 60%.
    Results are sorted by number of aligned timeframes, then average grade.

    Examples:
        ichi mtfscan
        ichi mtfscan --timeframes 4h,1d,1w --top 30
        ichi mtfscan --min-aligned 2
    """
    params = load_params(params_path)
    apply_params(params)
    registry = RuleRegistry.canonical()

    tf_list = [tf.strip() for tf in timeframes.split(",") if tf.strip()]
    if not tf_list:
        click.echo("No timeframes specified.", err=True)
        return

    today = date.today().isoformat()
    symbols = top_n_by_marketcap(n=top)

    click.echo(
        f"Fetching {len(symbols)} symbols × {len(tf_list)} timeframes "
        f"({workers} workers)…",
        err=True,
    )

    results = _score_all(symbols, tf_list, registry, workers)

    fully_aligned = _print_table(symbols, tf_list, results, min_aligned, today)
    _print_summary(fully_aligned, tf_list, results)

    total_cells = sum(len(v) for v in results.values())
    click.echo(f"{len(results)} symbols scanned, {total_cells} TF snapshots.")
