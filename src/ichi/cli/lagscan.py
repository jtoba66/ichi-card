"""Laggard / coiled-spring scanner — ichi lagscan.

Finds coins where the weekly structure is already bullish but the daily/4h
hasn't fired yet.  These are compressed, primed setups that haven't moved.

Ranking (coil score):
  + weekly bull score          (higher = better macro setup)
  + gap: weekly - daily score  (bigger gap = more room to move)
  + 3 if price is IN the cloud on daily   (classic compression zone)
  + 2 if future cloud (26 bars ahead) is bullish on daily
  + 2 if ADX < 20 on daily    (not trending yet — maximum compression)
  + 1 if 20 ≤ ADX < 28 on daily
  + 1 if +DI > -DI on daily   (direction already shifted bullish)

Filters:
  weekly_bull  ≥ min_weekly  (default 6)
  daily_bull   ≤ max_daily   (default 12)
  plus_di > minus_di on daily (directional bias must be bullish)

Usage:
    ichi lagscan
    ichi lagscan --top 200 --min-weekly 8 --max-daily 10
    ichi lagscan --timeframes 1d,1w --workers 4
"""
from __future__ import annotations

import logging
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import date

import click
import pandas as pd

from ichi.calibration.params import apply_params, load_params
from ichi.data.fetcher import fetch_ohlcv
from ichi.data.universe import top_n_by_marketcap
from ichi.indicators.ichimoku import ichimoku
from ichi.indicators.precompute import precompute
from ichi.indicators.relative_strength import relative_strength, rs_label
from ichi.rules.registry import RuleRegistry
from ichi.scoring.engine import Scorecard, evaluate

logger = logging.getLogger(__name__)


# ── Coil scoring ──────────────────────────────────────────────────────────────

def _cloud_position(df: pd.DataFrame, i: int) -> str:
    """Return 'above', 'in', or 'below' relative to the Kumo at bar i."""
    close = df["close"].iat[i]
    span_a = df["span_a"].iat[i] if "span_a" in df.columns else float("nan")
    span_b = df["span_b"].iat[i] if "span_b" in df.columns else float("nan")
    if pd.isna(span_a) or pd.isna(span_b):
        return "unknown"
    top = max(span_a, span_b)
    bot = min(span_a, span_b)
    if close > top:
        return "above"
    if close < bot:
        return "below"
    return "in"


def _future_cloud_bullish(df: pd.DataFrame, i: int) -> bool:
    """True if the cloud 26 bars ahead is bullish (span_a_lead > span_b_lead at bar i).

    span_a_lead / span_b_lead are the unshifted leading values — they represent
    what the cloud WILL look like 26 bars from now, already in the DataFrame.
    """
    span_a = df["span_a_lead"].iat[i] if "span_a_lead" in df.columns else float("nan")
    span_b = df["span_b_lead"].iat[i] if "span_b_lead" in df.columns else float("nan")
    if pd.isna(span_a) or pd.isna(span_b):
        return False
    return float(span_a) > float(span_b)


def _coil_score(
    weekly_bull: int,
    daily_bull: int,
    adx: float,
    plus_di: float,
    minus_di: float,
    cloud_pos: str,
    future_cloud_bull: bool,
    bb_squeeze: bool = False,
    bullish_div: bool = False,
    vol_ratio: float = 1.0,
) -> float:
    score = 0.0
    score += weekly_bull                          # macro structure
    score += max(0, weekly_bull - daily_bull)     # gap = unspent potential
    if cloud_pos == "in":
        score += 3                                # in the compression zone
    if future_cloud_bull:
        score += 2                                # upcoming cloud provides support
    if adx < 20:
        score += 2                                # maximum compression
    elif adx < 28:
        score += 1                                # mild trend beginning
    if plus_di > minus_di:
        score += 1                                # direction already shifted
    if bb_squeeze:
        score += 3                                # Bollinger squeeze = coiled volatility
    if bullish_div:
        score += 2                                # RSI divergence = momentum turning
    if vol_ratio >= 1.5:
        score += 1                                # volume starting to pick up
    return score


# ── Per-symbol analysis ───────────────────────────────────────────────────────

def _analyse_symbol(sym: str, registry: RuleRegistry,
                    btc_1d: pd.DataFrame | None = None) -> dict | None:
    try:
        df_1d = fetch_ohlcv(sym, "1d")
        df_1w = fetch_ohlcv(sym, "1w")
        df_4h = fetch_ohlcv(sym, "4h")

        # Need at least 60 daily bars for a valid Ichimoku signal
        if df_1d is None or df_1d.empty or len(df_1d) < 60:
            return None
        if df_1w is None or df_1w.empty or len(df_1w) < 26:
            return None

        # Score daily
        df_1d = ichimoku(df_1d)
        precompute(df_1d)
        i_1d = len(df_1d) - 1
        sc_1d: Scorecard = evaluate(df_1d, i_1d, registry)

        # Score weekly
        df_1w = ichimoku(df_1w)
        precompute(df_1w)
        i_1w = len(df_1w) - 1
        sc_1w: Scorecard = evaluate(df_1w, i_1w, registry)

        # Score 4h (optional — may not exist)
        bull_4h: int | None = None
        if df_4h is not None and not df_4h.empty and len(df_4h) >= 60:
            df_4h = ichimoku(df_4h)
            precompute(df_4h)
            sc_4h: Scorecard = evaluate(df_4h, len(df_4h) - 1, registry)
            bull_4h = sc_4h.bull_score

        adx_val = (
            float(df_1d["_adx"].iat[i_1d])
            if "_adx" in df_1d.columns and not df_1d["_adx"].isna().iat[i_1d]
            else 0.0
        )
        plus_di = (
            float(df_1d["_plus_di"].iat[i_1d])
            if "_plus_di" in df_1d.columns and not df_1d["_plus_di"].isna().iat[i_1d]
            else 0.0
        )
        minus_di = (
            float(df_1d["_minus_di"].iat[i_1d])
            if "_minus_di" in df_1d.columns and not df_1d["_minus_di"].isna().iat[i_1d]
            else 0.0
        )

        cloud_pos = _cloud_position(df_1d, i_1d)
        future_bull = _future_cloud_bullish(df_1d, i_1d)
        bb_squeeze_val = bool(df_1d["_bb_squeeze"].iat[i_1d]) if "_bb_squeeze" in df_1d.columns else False
        bullish_div = bool(df_1d["_bullish_div"].iat[i_1d]) if "_bullish_div" in df_1d.columns else False
        vol_ratio = float(df_1d["_vol_ratio"].iat[i_1d]) if "_vol_ratio" in df_1d.columns and not df_1d["_vol_ratio"].isna().iat[i_1d] else 1.0

        coil = _coil_score(
            sc_1w.bull_score, sc_1d.bull_score,
            adx_val, plus_di, minus_di,
            cloud_pos, future_bull,
            bb_squeeze=bb_squeeze_val,
            bullish_div=bullish_div,
            vol_ratio=vol_ratio,
        )

        rs = relative_strength(df_1d, btc_1d) if btc_1d is not None and not btc_1d.empty else {}
        rs_lbl = rs_label(rs.get("rs_7d", float("nan")), rs.get("rs_14d", float("nan"))) if rs else ""

        return {
            "symbol": sym.replace("/USDT", ""),
            "sym_full": sym,
            "bull_1w": sc_1w.bull_score,
            "bull_1d": sc_1d.bull_score,
            "bull_4h": bull_4h,
            "total": sc_1d.total_scoring_rules,
            "adx": adx_val,
            "plus_di": plus_di,
            "minus_di": minus_di,
            "cloud_pos": cloud_pos,
            "future_cloud_bull": future_bull,
            "bb_squeeze": bb_squeeze_val,
            "bullish_div": bullish_div,
            "vol_ratio": vol_ratio,
            "coil": coil,
            "rs_label": rs_lbl,
        }
    except Exception as exc:
        logger.warning("%s: %s", sym, exc)
        return None


def _score_all(symbols: list[str], registry: RuleRegistry, workers: int,
               btc_1d: pd.DataFrame | None = None) -> list[dict]:
    rows: list[dict] = []
    with ThreadPoolExecutor(max_workers=workers) as pool:
        futures = {pool.submit(_analyse_symbol, sym, registry, btc_1d): sym for sym in symbols}
        for fut in as_completed(futures):
            result = fut.result()
            if result:
                rows.append(result)
    return rows


# ── CLI ───────────────────────────────────────────────────────────────────────

@click.command(name="lagscan")
@click.option("--top", "-n", default=200, show_default=True, help="Universe size")
@click.option("--min-weekly", default=6, show_default=True,
              help="Minimum weekly bull score (macro structure must be there)")
@click.option("--max-daily", default=12, show_default=True,
              help="Maximum daily bull score (hasn't fired yet)")
@click.option("--workers", default=6, show_default=True, help="Parallel workers")
@click.option("--params", "params_path", default=None, help="Path to params.yaml")
@click.option("--show", default=30, show_default=True, help="Number of results to display")
def lagscan(
    top: int,
    min_weekly: int,
    max_daily: int,
    workers: int,
    params_path: str | None,
    show: int,
) -> None:
    """Coiled-spring scanner: find coins primed to move but not yet moving.

    Looks for weekly bullish structure + daily compression + low ADX.
    These are the laggards — the weekly setup is there but daily/4h
    hasn't caught up yet.

    Examples:
        ichi lagscan
        ichi lagscan --min-weekly 8 --max-daily 10
        ichi lagscan --top 200 --show 20
    """
    params = load_params(params_path)
    apply_params(params)
    registry = RuleRegistry.canonical()

    today = date.today().isoformat()
    click.echo(f"\nCoiled-Spring Scanner — {today}\n")
    click.echo(
        f"Filters: weekly_bull ≥ {min_weekly}  |  daily_bull ≤ {max_daily}"
        f"  |  +DI > -DI on daily\n"
    )

    symbols = top_n_by_marketcap(n=top)
    click.echo(f"Scoring {len(symbols)} symbols across 1w + 1d + 4h…\n")

    btc_1d = fetch_ohlcv("BTC/USDT", "1d")
    rows = _score_all(symbols, registry, workers, btc_1d)
    if not rows:
        click.echo("No data returned.", err=True)
        return

    # Apply filters
    filtered = [
        r for r in rows
        if r["bull_1w"] >= min_weekly
        and r["bull_1d"] <= max_daily
        and r["plus_di"] > r["minus_di"]
    ]

    filtered.sort(key=lambda r: r["coil"], reverse=True)

    if not filtered:
        click.echo(
            f"No symbols passed filters (weekly≥{min_weekly}, daily≤{max_daily}, +DI>-DI).\n"
            "Try lowering --min-weekly or raising --max-daily."
        )
        return

    # Header
    click.echo(
        f"{'Symbol':<12}  {'1w':>5}  {'1d':>5}  {'4h':>5}  "
        f"{'ADX':>6}  {'Cloud':<7}  {'FutCloud':<9}  {'Coil':>5}  Signals"
    )
    click.echo("─" * 95)

    for row in filtered[:show]:
        sym = row["symbol"]
        w = f"{row['bull_1w']}/18"
        d = f"{row['bull_1d']}/18"
        h = f"{row['bull_4h']}/18" if row["bull_4h"] is not None else "  —  "
        adx_str = f"{row['adx']:.0f}"
        if row["adx"] >= 40:
            adx_str += " 🔥"
        elif row["adx"] >= 25:
            adx_str += " ↗"
        else:
            adx_str += " ~"

        cloud_icon = {"above": "Above☁", "in": "IN ☁ ←", "below": "Below☁", "unknown": "?"}
        cloud_str = cloud_icon.get(row["cloud_pos"], "?")
        fut_str = "✓ bull" if row["future_cloud_bull"] else "✗ bear"

        signals = []
        if row.get("bb_squeeze"):
            signals.append("SQUEEZE")
        if row.get("bullish_div"):
            signals.append("RSI-DIV↑")
        if row.get("vol_ratio", 1.0) >= 1.5:
            signals.append(f"VOL {row['vol_ratio']:.1f}x")
        lbl = row.get("rs_label", "")
        if lbl in ("STRONG↑", "WEAK↓"):
            signals.append(f"RS:{lbl}")
        signals_str = "  ".join(signals)

        click.echo(
            f"  {sym:<10}  {w:>5}  {d:>5}  {h:>5}  "
            f"{adx_str:<8}  {cloud_str:<9}  {fut_str:<9}  {row['coil']:>5.0f}  {signals_str}"
        )

    click.echo()
    click.echo(
        f"{len(filtered)} symbols matched filters  "
        f"({len(rows)} total scored, {len(symbols) - len(rows)} skipped)"
    )

    # Summary buckets
    in_cloud = [r for r in filtered if r["cloud_pos"] == "in"]
    fut_bull = [r for r in filtered if r["future_cloud_bull"]]
    ultra_low_adx = [r for r in filtered if r["adx"] < 20]

    click.echo()
    bb_sq = [r for r in filtered if r.get("bb_squeeze")]
    rsi_div = [r for r in filtered if r.get("bullish_div")]

    click.echo(f"  Price inside cloud (max compression):   {len(in_cloud)} symbols")
    click.echo(f"  Future cloud bullish (upcoming support): {len(fut_bull)} symbols")
    click.echo(f"  ADX < 20 (fully compressed):            {len(ultra_low_adx)} symbols")
    click.echo(f"  Bollinger squeeze active:               {len(bb_sq)} symbols")
    click.echo(f"  Bullish RSI divergence:                 {len(rsi_div)} symbols")
