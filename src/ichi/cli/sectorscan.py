"""Sector rotation scanner — ichi sectorscan.

Groups coins by sector and shows which sectors are leading vs lagging.
Helps identify rotation: where is smart money moving?

Usage:
    ichi sectorscan
    ichi sectorscan --top 200 --timeframe 1d
    ichi sectorscan --min-score 8
"""
from __future__ import annotations

import logging
from collections import defaultdict
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import date

import click

from ichi.calibration.params import apply_params, load_params
from ichi.data.fetcher import fetch_ohlcv
from ichi.data.sectors import all_sectors, get_sector
from ichi.data.universe import top_n_by_marketcap
from ichi.indicators.ichimoku import ichimoku
from ichi.indicators.precompute import precompute
from ichi.rules.registry import RuleRegistry
from ichi.scoring.engine import Scorecard, evaluate

logger = logging.getLogger(__name__)


def _score_symbol(sym: str, timeframe: str, registry: RuleRegistry) -> dict | None:
    try:
        df = fetch_ohlcv(sym, timeframe)
        if df is None or df.empty or len(df) < 60:
            return None
        df = ichimoku(df)
        precompute(df)
        i = len(df) - 1
        sc: Scorecard = evaluate(df, i, registry)
        adx_val = float(df["_adx"].iat[i]) if "_adx" in df.columns and not df["_adx"].isna().iat[i] else 0.0
        return {
            "symbol": sym.replace("/USDT", ""),
            "sector": get_sector(sym.replace("/USDT", "")),
            "bull": sc.bull_score,
            "bear": sc.bear_score,
            "total": sc.total_scoring_rules,
            "grade": sc.grade,
            "adx": adx_val,
        }
    except Exception as exc:
        logger.warning("%s: %s", sym, exc)
        return None


@click.command(name="sectorscan")
@click.option("--top", "-n", default=200, show_default=True, help="Universe size")
@click.option("--timeframe", "-t", default="1d", show_default=True, help="Timeframe")
@click.option("--workers", default=8, show_default=True, help="Parallel workers")
@click.option("--min-coins", default=2, show_default=True,
              help="Minimum coins in sector to display")
@click.option("--params", "params_path", default=None, help="Path to params.yaml")
def sectorscan(
    top: int,
    timeframe: str,
    workers: int,
    min_coins: int,
    params_path: str | None,
) -> None:
    """Sector rotation: which categories are leading vs lagging?

    Groups coins by sector (L1, L2, DeFi, Meme, AI, Gaming, Exchange, etc.)
    and ranks by average bull score. Identifies where momentum is concentrated.

    Examples:
        ichi sectorscan
        ichi sectorscan --timeframe 4h
    """
    params = load_params(params_path)
    apply_params(params)
    registry = RuleRegistry.canonical()

    today = date.today().isoformat()
    click.echo(f"\nSector Rotation Scanner — {today}  [{timeframe}]\n")

    symbols = top_n_by_marketcap(n=top)

    rows: list[dict] = []
    with ThreadPoolExecutor(max_workers=workers) as pool:
        futures = {pool.submit(_score_symbol, sym, timeframe, registry): sym for sym in symbols}
        for fut in as_completed(futures):
            result = fut.result()
            if result:
                rows.append(result)

    if not rows:
        click.echo("No data returned.", err=True)
        return

    # Group by sector
    by_sector: dict[str, list[dict]] = defaultdict(list)
    for row in rows:
        by_sector[row["sector"]].append(row)

    # Aggregate per sector
    sector_stats = []
    for sector, coins in by_sector.items():
        if len(coins) < min_coins:
            continue
        avg_bull = sum(c["bull"] for c in coins) / len(coins)
        avg_grade = sum(c["grade"] for c in coins) / len(coins)
        avg_adx = sum(c["adx"] for c in coins) / len(coins)
        bull_pct = sum(1 for c in coins if c["bull"] >= 11) / len(coins) * 100
        top_coins = sorted(coins, key=lambda c: c["bull"], reverse=True)[:4]
        sector_stats.append({
            "sector": sector,
            "count": len(coins),
            "avg_bull": avg_bull,
            "avg_grade": avg_grade,
            "avg_adx": avg_adx,
            "bull_pct": bull_pct,
            "top_coins": top_coins,
        })

    sector_stats.sort(key=lambda s: s["avg_bull"], reverse=True)

    # Sector overview table
    click.echo(f"{'Sector':<16}  {'Coins':>5}  {'AvgBull':>7}  {'≥11/18%':>7}  {'AvgADX':>7}  Top coins")
    click.echo("─" * 85)

    for s in sector_stats:
        top_str = "  ".join(c["symbol"] for c in s["top_coins"])
        adx_icon = "🔥" if s["avg_adx"] >= 40 else ("↗" if s["avg_adx"] >= 25 else "~")
        click.echo(
            f"  {s['sector']:<14}  {s['count']:>5}  {s['avg_bull']:>7.1f}  "
            f"{s['bull_pct']:>6.0f}%  {s['avg_adx']:>5.0f}{adx_icon}  {top_str}"
        )

    click.echo()
    click.echo(f"{len(rows)} symbols scored across {len(sector_stats)} sectors.\n")

    # Leading vs lagging summary
    if len(sector_stats) >= 2:
        leader = sector_stats[0]
        lagger = sector_stats[-1]
        click.echo(
            f"Leading:  {leader['sector']} (avg {leader['avg_bull']:.1f}/18, "
            f"{leader['bull_pct']:.0f}% above 11)"
        )
        click.echo(
            f"Lagging:  {lagger['sector']} (avg {lagger['avg_bull']:.1f}/18, "
            f"{lagger['bull_pct']:.0f}% above 11)"
        )
        click.echo()

    # Drill-down: top 5 coins per leading sector
    click.echo("Top 3 sectors — coin breakdown:")
    for s in sector_stats[:3]:
        click.echo(f"\n  {s['sector']}:")
        all_coins = sorted(s["top_coins"], key=lambda c: c["bull"], reverse=True)
        for c in all_coins[:5]:
            grade_str = f"{c['bull']}/18"
            adx_str = f"ADX {c['adx']:.0f}"
            click.echo(f"    {c['symbol']:<10}  {grade_str:>5}  {adx_str}")
