"""Trade journal validator — SPEC.md §12.2.

Scores your historical trades against what the indicator said at entry.
Reveals alignment between your decisions and the system, and where you diverge.

Usage:
    ichi journal --file trades.csv
    ichi journal --file trades.csv --min-score 12
    ichi journal --file trades.json

CSV format (minimal):
    date,symbol,direction,outcome
    2024-09-13,SUI/USDT,long,win
    2024-07-27,BNB/USDT,short,win
    2024-02-18,ADA/USDT,long,loss

CSV format (with prices, outcome computed automatically):
    date,symbol,direction,entry_price,exit_price
    2024-09-13,SUI/USDT,long,0.85,2.10
    2024-07-27,BNB/USDT,short,220.0,198.0

JSON format: list of objects with same fields.

Fields:
    date         — entry date (YYYY-MM-DD)
    symbol       — e.g. BTC/USDT or BTCUSDT (normalised automatically)
    direction    — long / short
    outcome      — win / loss / scratch  (OR provide entry_price + exit_price)
    entry_price  — optional, used to compute outcome if outcome not given
    exit_price   — optional
    notes        — optional, shown in output
"""
from __future__ import annotations

import csv
import json
import math
from datetime import date
from pathlib import Path
from typing import Any

import click
import pandas as pd

from ichi.calibration.params import apply_params, load_params
from ichi.data.fetcher import fetch_ohlcv
from ichi.indicators.ichimoku import ichimoku
from ichi.indicators.precompute import precompute
from ichi.rules.registry import RuleRegistry
from ichi.scoring.engine import evaluate


@click.command()
@click.option("--file", "-f", "trades_file", required=True,
              help="Path to CSV or JSON file of trades")
@click.option("--timeframe", "-t", default="1d", show_default=True,
              help="Timeframe to score trades on")
@click.option("--min-score", default=0, show_default=True,
              help="Highlight trades where system scored >= this")
@click.option("--params", "params_path", default=None,
              help="Path to params.yaml (default: project root)")
def journal(trades_file: str, timeframe: str, min_score: int, params_path: str | None) -> None:
    """Validate historical trades against the Ichimoku scorecard.

    Shows what the system said at each entry and whether it agreed with your trade.
    Surfaces alignment rate, score-bucket win rates, and divergence cases.

    Examples:
        ichi journal --file trades.csv
        ichi journal --file trades.json --min-score 12
    """
    params = load_params(params_path)
    apply_params(params)
    registry = RuleRegistry.canonical()

    trades = _load_trades(trades_file)
    if not trades:
        click.echo("No trades loaded — check file format.", err=True)
        return

    click.echo(f"\n── Trade Journal Validator ── {len(trades)} trades  [{timeframe}] ──────────────")
    click.echo()

    results = _score_trades(trades, timeframe, registry)

    _print_trade_rows(results, min_score)
    click.echo()
    _print_stats(results)
    _print_divergence(results)
    _print_score_bucket_table(results)


# ── Loading ───────────────────────────────────────────────────────────────────

def _load_trades(path: str) -> list[dict]:
    p = Path(path)
    if not p.exists():
        raise click.BadParameter(f"File not found: {path}", param_hint="--file")

    if p.suffix.lower() == ".json":
        with open(p) as f:
            raw = json.load(f)
    else:
        with open(p, newline="") as f:
            raw = list(csv.DictReader(f))

    trades = []
    for i, row in enumerate(raw):
        try:
            trade = _normalise_trade(row, i)
            trades.append(trade)
        except Exception as exc:
            click.echo(f"  [row {i+1} skipped]: {exc}", err=True)
    return trades


def _normalise_trade(row: dict, idx: int) -> dict:
    """Normalise a raw row into a canonical trade dict."""
    entry_date = date.fromisoformat(str(row.get("date", "")).strip())
    symbol = str(row.get("symbol", "")).strip().upper()
    if not symbol.endswith("/USDT") and not symbol.endswith("USDT"):
        symbol = symbol + "/USDT"
    elif symbol.endswith("USDT") and "/" not in symbol:
        symbol = symbol[:-4] + "/USDT"

    direction = str(row.get("direction", "long")).strip().lower()
    if direction not in ("long", "short"):
        raise ValueError(f"direction must be long/short, got '{direction}'")

    # Resolve outcome
    outcome = str(row.get("outcome", "")).strip().lower()
    entry_price = row.get("entry_price")
    exit_price = row.get("exit_price")

    if outcome in ("win", "loss", "scratch"):
        pass
    elif entry_price and exit_price:
        ep, xp = float(entry_price), float(exit_price)
        pnl_pct = (xp - ep) / ep * (1 if direction == "long" else -1)
        outcome = "win" if pnl_pct > 0.005 else ("loss" if pnl_pct < -0.005 else "scratch")
    else:
        outcome = "unknown"

    return {
        "id": f"trade_{idx+1:03d}",
        "date": entry_date,
        "symbol": symbol,
        "direction": direction,
        "outcome": outcome,
        "notes": str(row.get("notes", "")).strip(),
    }


# ── Scoring ───────────────────────────────────────────────────────────────────

def _score_trades(trades: list[dict], timeframe: str, registry: RuleRegistry) -> list[dict]:
    # Cache fetched dataframes per symbol to avoid repeated fetches
    cache: dict[str, pd.DataFrame | None] = {}
    results = []

    for trade in trades:
        sym = trade["symbol"]
        if sym not in cache:
            try:
                df = fetch_ohlcv(sym, timeframe)
                if df.empty or len(df) < 60:
                    cache[sym] = None
                else:
                    df = ichimoku(df)
                    precompute(df)
                    cache[sym] = df
            except Exception as exc:
                click.echo(f"  [{sym}] fetch error: {exc}", err=True)
                cache[sym] = None

        df = cache[sym]
        if df is None:
            results.append(_error_result(trade, "data unavailable"))
            continue

        entry_date = trade["date"]
        dates = df.index.date
        idx = next((i for i, d in enumerate(dates) if d >= entry_date), None)
        if idx is None:
            results.append(_error_result(trade, f"date {entry_date} not in data"))
            continue

        try:
            sc = evaluate(df, idx, registry)
        except Exception as exc:
            results.append(_error_result(trade, f"eval error: {exc}"))
            continue

        adx_val = float(df["_adx"].iat[idx]) if "_adx" in df.columns and not df["_adx"].isna().iat[idx] else 0.0
        bull_score = sc.bull_score
        grade = sc.grade
        total = sc.total_scoring_rules

        # System's directional call
        if grade >= 0.72:
            sys_call = "bull_strong"
        elif grade >= 0.56:
            sys_call = "bull_weak"
        elif grade <= 0.28:
            sys_call = "bear_strong"
        elif grade <= 0.39:
            sys_call = "bear_weak"
        else:
            sys_call = "neutral"

        # Did system agree with the trade direction?
        agreed = _system_agreed(trade["direction"], sys_call)

        # Combined verdict: agreed + correct outcome
        if agreed and trade["outcome"] == "win":
            verdict = "aligned_win"
        elif agreed and trade["outcome"] == "loss":
            verdict = "aligned_loss"
        elif not agreed and trade["outcome"] == "win":
            verdict = "diverged_win"
        elif not agreed and trade["outcome"] == "loss":
            verdict = "diverged_loss"
        else:
            verdict = "neutral_or_unknown"

        results.append({
            **trade,
            "bull_score": bull_score,
            "total": total,
            "grade": grade,
            "adx": adx_val,
            "sys_call": sys_call,
            "agreed": agreed,
            "verdict": verdict,
            "error": None,
        })

    return results


def _system_agreed(direction: str, sys_call: str) -> bool:
    if direction == "long":
        return sys_call in ("bull_strong", "bull_weak")
    if direction == "short":
        return sys_call in ("bear_strong", "bear_weak")
    return False


def _error_result(trade: dict, msg: str) -> dict:
    return {
        **trade,
        "bull_score": -1,
        "total": 18,
        "grade": float("nan"),
        "adx": float("nan"),
        "sys_call": "error",
        "agreed": False,
        "verdict": "error",
        "error": msg,
    }


# ── Display ───────────────────────────────────────────────────────────────────

def _print_trade_rows(results: list[dict], min_score: int) -> None:
    click.echo(f"  {'#':>4}  {'Date':<12} {'Symbol':<10} {'Dir':>5}  "
               f"{'Score':>6}  {'Sys':>11}  {'ADX':>6}  {'Outcome':>7}  Verdict")
    click.echo("  " + "─" * 90)

    for r in results:
        if r["error"]:
            click.echo(f"  {r['id']:>4}  {str(r['date']):<12} {r['symbol']:<10}  ERROR: {r['error']}")
            continue

        score_str = f"{r['bull_score']}/{r['total']}" if r["bull_score"] >= 0 else " n/a"
        adx_str = f"{r['adx']:.0f}" if not math.isnan(r["adx"]) else " ?"
        highlight = "★" if r["bull_score"] >= min_score and min_score > 0 else " "
        verdict_icon = {
            "aligned_win": "✓✓",
            "aligned_loss": "✓✗",
            "diverged_win": "✗✓",
            "diverged_loss": "✗✗",
        }.get(r["verdict"], " ·")

        click.echo(
            f"  {highlight}{r['id']:>4}  {str(r['date']):<12} "
            f"{r['symbol'].replace('/USDT',''):<10} "
            f"{r['direction']:>5}  "
            f"{score_str:>6}  "
            f"{r['sys_call']:>11}  "
            f"ADX {adx_str:>3}  "
            f"{r['outcome']:>7}  "
            f"{verdict_icon}"
        )


def _print_stats(results: list[dict]) -> None:
    valid = [r for r in results if not r["error"] and r["outcome"] != "unknown"]

    wins = [r for r in valid if r["outcome"] == "win"]
    losses = [r for r in valid if r["outcome"] == "loss"]
    agreed = [r for r in valid if r["agreed"]]
    disagreed = [r for r in valid if not r["agreed"]]

    win_rate = len(wins) / len(valid) if valid else float("nan")
    align_rate = len(agreed) / len(valid) if valid else float("nan")

    # Win rate when system agreed vs disagreed
    agreed_wins = sum(1 for r in agreed if r["outcome"] == "win")
    agreed_win_rate = agreed_wins / len(agreed) if agreed else float("nan")
    disagreed_wins = sum(1 for r in disagreed if r["outcome"] == "win")
    disagreed_win_rate = disagreed_wins / len(disagreed) if disagreed else float("nan")

    click.echo("── Summary ──────────────────────────────────────────────────────────────────")
    click.echo(f"  Trades evaluated:      {len(valid)}")
    click.echo(f"  Your win rate:         {win_rate*100:.0f}%  ({len(wins)} wins / {len(losses)} losses)")
    click.echo(f"  System alignment rate: {align_rate*100:.0f}%  ({len(agreed)} agreed / {len(disagreed)} disagreed)")
    click.echo()
    click.echo(f"  Win rate when system AGREED:    {agreed_win_rate*100:.0f}%  ({agreed_wins}/{len(agreed)})")
    click.echo(f"  Win rate when system DISAGREED: {disagreed_win_rate*100:.0f}%  ({disagreed_wins}/{len(disagreed)})")

    if not math.isnan(agreed_win_rate) and not math.isnan(disagreed_win_rate):
        edge = agreed_win_rate - disagreed_win_rate
        if edge > 0.10:
            click.echo(f"\n  ✓ System adds edge: +{edge*100:.0f}pp win rate when followed")
        elif edge > 0:
            click.echo(f"\n  ~ Weak edge: +{edge*100:.0f}pp when system agreed")
        else:
            click.echo(f"\n  ✗ No edge detected: {edge*100:.0f}pp (consider reviewing rules)")
    click.echo()


def _print_divergence(results: list[dict]) -> None:
    """Highlight the most instructive divergence cases."""
    diverged = [r for r in results if not r.get("error") and not r["agreed"]
                and r["outcome"] not in ("unknown", "scratch")]
    if not diverged:
        return

    click.echo("── Divergence cases (you vs system) ─────────────────────────────────────────")
    click.echo("  These are trades where you and the system disagreed — most instructive:\n")
    for r in sorted(diverged, key=lambda x: x["grade"], reverse=True):
        icon = "✗✓ missed" if r["outcome"] == "win" else "✗✗ both wrong"
        score_str = f"{r['bull_score']}/{r['total']}"
        click.echo(
            f"  {str(r['date'])}  {r['symbol'].replace('/USDT',''):<8}  "
            f"{r['direction']:>5}  score={score_str}  sys={r['sys_call']:>11}  "
            f"outcome={r['outcome']:>4}  [{icon}]"
            + (f"  {r['notes']}" if r["notes"] else "")
        )
    click.echo()


def _print_score_bucket_table(results: list[dict]) -> None:
    """Win rate by bull score bucket — the key predictive signal."""
    valid = [r for r in results
             if not r.get("error") and r["outcome"] in ("win", "loss")
             and r["direction"] == "long"]   # only longs map cleanly to bull score
    if len(valid) < 4:
        return

    buckets: dict[str, list] = {"0–8 (low)": [], "9–12 (mid)": [], "13–15 (high)": [], "16–18 (top)": []}
    for r in valid:
        s = r["bull_score"]
        if s <= 8:
            buckets["0–8 (low)"].append(r)
        elif s <= 12:
            buckets["9–12 (mid)"].append(r)
        elif s <= 15:
            buckets["13–15 (high)"].append(r)
        else:
            buckets["16–18 (top)"].append(r)

    click.echo("── Long trade win rate by bull score bucket ─────────────────────────────────")
    click.echo(f"  {'Bucket':<18}  {'Win rate':>9}  {'N':>4}")
    for label, rows in buckets.items():
        if not rows:
            continue
        wins = sum(1 for r in rows if r["outcome"] == "win")
        rate = wins / len(rows)
        bar = "█" * int(rate * 20)
        click.echo(f"  {label:<18}  {rate*100:>7.0f}%  {len(rows):>4}  {bar}")
    click.echo()
