"""Funding rate + open interest scanner — ichi funding.

Scans perp markets for funding rates and OI across top coins.
Key signals:
  - Negative funding + bullish Ichimoku = shorts paying longs = squeeze setup
  - Rising OI + bullish score = real directional conviction
  - High positive funding = market is overleveraged long = caution

Only works for coins with active perp markets (top ~100-120 by market cap).

Usage:
    ichi funding
    ichi funding --top 100 --min-score 10
    ichi funding --exchange bybit
"""
from __future__ import annotations

import logging
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import date

import click

from ichi.calibration.params import apply_params, load_params
from ichi.data.fetcher import fetch_ohlcv
from ichi.data.funding import fetch_funding_and_oi
from ichi.data.universe import get_exchange_for, top_n_by_marketcap
from ichi.indicators.ichimoku import ichimoku
from ichi.indicators.precompute import precompute
from ichi.rules.registry import RuleRegistry
from ichi.scoring.engine import Scorecard, evaluate

logger = logging.getLogger(__name__)

# Exchanges that support perp markets
_PERP_EXCHANGES = {"binance", "bybit", "okx"}


def _score_and_fund(sym: str, timeframe: str, registry: RuleRegistry) -> dict | None:
    try:
        # Score
        df = fetch_ohlcv(sym, timeframe)
        if df is None or df.empty or len(df) < 60:
            return None
        df = ichimoku(df)
        precompute(df)
        i = len(df) - 1
        sc: Scorecard = evaluate(df, i, registry)

        # Determine best exchange for perp data
        spot_ex = get_exchange_for(sym)
        perp_ex = spot_ex if spot_ex in _PERP_EXCHANGES else "binance"

        # Fetch funding + OI
        fund = fetch_funding_and_oi(sym, perp_ex)

        return {
            "symbol": sym.replace("/USDT", ""),
            "sym_full": sym,
            "bull": sc.bull_score,
            "bear": sc.bear_score,
            "total": sc.total_scoring_rules,
            "grade": sc.grade,
            "funding_pct": fund["funding_pct"],
            "oi_usd": fund["oi_usd"],
            "exchange": perp_ex,
        }
    except Exception as exc:
        logger.warning("%s: %s", sym, exc)
        return None


def _fmt_oi(oi_usd: float | None) -> str:
    if oi_usd is None:
        return "  —  "
    if oi_usd >= 1e9:
        return f"${oi_usd/1e9:.1f}B"
    if oi_usd >= 1e6:
        return f"${oi_usd/1e6:.0f}M"
    return f"${oi_usd/1e3:.0f}K"


def _fmt_funding(pct: float | None) -> str:
    if pct is None:
        return "  N/A "
    sign = "+" if pct >= 0 else ""
    return f"{sign}{pct:.4f}%"


@click.command(name="funding")
@click.option("--top", "-n", default=100, show_default=True,
              help="Universe size (perps only exist for top ~120)")
@click.option("--timeframe", "-t", default="1d", show_default=True, help="Timeframe for scoring")
@click.option("--min-score", default=0, show_default=True, help="Min bull score to include")
@click.option("--workers", default=6, show_default=True, help="Parallel workers")
@click.option("--squeeze-only", is_flag=True,
              help="Only show negative funding + bullish score (squeeze setups)")
@click.option("--params", "params_path", default=None, help="Path to params.yaml")
def funding_cmd(
    top: int,
    timeframe: str,
    min_score: int,
    workers: int,
    squeeze_only: bool,
    params_path: str | None,
) -> None:
    """Funding rate + OI scanner: find squeeze setups and overleveraged longs.

    Negative funding + high bull score = shorts paying longs into a strong
    Ichimoku structure = potential short squeeze catalyst.

    High positive funding + weak score = market overleveraged long = caution.

    Examples:
        ichi funding
        ichi funding --squeeze-only
        ichi funding --min-score 12 --top 100
    """
    params = load_params(params_path)
    apply_params(params)
    registry = RuleRegistry.canonical()

    today = date.today().isoformat()
    click.echo(f"\nFunding + OI Scanner — {today}  [{timeframe}]\n")

    symbols = top_n_by_marketcap(n=top)

    rows: list[dict] = []
    with ThreadPoolExecutor(max_workers=workers) as pool:
        futures = {pool.submit(_score_and_fund, sym, timeframe, registry): sym for sym in symbols}
        for fut in as_completed(futures):
            result = fut.result()
            if result:
                rows.append(result)

    if not rows:
        click.echo("No data returned.", err=True)
        return

    # Filter
    visible = [r for r in rows if r["bull"] >= min_score]
    if squeeze_only:
        visible = [r for r in visible if r["funding_pct"] is not None and r["funding_pct"] < 0]

    # Sort by bull score desc
    visible.sort(key=lambda r: r["bull"], reverse=True)

    has_fund = [r for r in rows if r["funding_pct"] is not None]

    click.echo(f"{'Symbol':<10}  {'Score':>6}  {'Funding':>9}  {'OI':>8}  Signal")
    click.echo("─" * 65)

    squeeze_count = 0
    overlong_count = 0

    for row in visible:
        sym = row["symbol"]
        score_str = f"{row['bull']}/{row['total']}"
        funding_str = _fmt_funding(row["funding_pct"])
        oi_str = _fmt_oi(row["oi_usd"])

        signal = ""
        if row["funding_pct"] is not None:
            if row["funding_pct"] < -0.01 and row["bull"] >= 11:
                signal = "🔥 SQUEEZE SETUP"
                squeeze_count += 1
            elif row["funding_pct"] < 0 and row["bull"] >= 8:
                signal = "⚡ neg funding"
            elif row["funding_pct"] > 0.05 and row["bull"] < 8:
                signal = "⚠️  overleveraged"
                overlong_count += 1
            elif row["funding_pct"] > 0.03:
                signal = "↑ longs crowded"

        click.echo(
            f"  {sym:<8}  {score_str:>6}  {funding_str:>9}  {oi_str:>8}  {signal}"
        )

    click.echo()
    click.echo(f"{len(visible)} symbols shown  ({len(rows)} total scored, {len(has_fund)} with perp data)")

    if squeeze_count:
        click.echo(f"\n🔥 {squeeze_count} squeeze setups (negative funding + bull score ≥ 11)")
    if overlong_count:
        click.echo(f"⚠️  {overlong_count} overleveraged long setups — potential flush risk")
