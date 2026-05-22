"""Daily scanner CLI — SPEC.md §12.1.

Usage:
    ichi scan
    ichi scan --timeframe 4h --top 50
    ichi scan --min-score 12
    ichi scan --no-save          # skip writing state file (no state-change tracking)
    ichi scan --params custom.yaml
"""
from __future__ import annotations

import json
import logging
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import date
from pathlib import Path

import pandas as pd
import click

from ichi.calibration.params import apply_params, load_params
from ichi.data.fetcher import fetch_ohlcv
from ichi.data.universe import top_n_by_marketcap
from ichi.indicators.ichimoku import ichimoku
from ichi.indicators.precompute import precompute
from ichi.indicators.relative_strength import relative_strength, rs_label
from ichi.rules.registry import RuleRegistry
from ichi.scoring.engine import Scorecard, evaluate

logger = logging.getLogger(__name__)

_STATE_FILE = Path(__file__).parents[3] / "data" / "scan_state.json"

_FLAG_MAP = {
    "perfect_setup": "⭐ PERFECT",
    "triple_sweep": "TRP↑",
    "sanyaku": "SNY↑",
    "cloud_curling": "☁↑",
    "kumo_trap": "TRAP",
    "no_bear_setup": None,   # informational only, not a flag
}

_CHANGE_THRESHOLD = 3   # minimum bull score delta to appear in "Notable State Changes"


@click.command()
@click.option("--timeframe", "-t", default="1d", show_default=True, help="Timeframe to scan")
@click.option("--top", "-n", default=200, show_default=True, help="Number of pairs to scan")
@click.option("--min-score", default=0, show_default=True, help="Min bull score to show in top-bull section")
@click.option("--workers", default=8, show_default=True, help="Parallel fetch workers")
@click.option("--no-save", "skip_save", is_flag=True, help="Skip saving state file")
@click.option("--regime-filter", is_flag=True,
              help="Only show symbols in trending regime (ADX >= threshold)")
@click.option("--params", "params_path", default=None,
              help="Path to params.yaml (default: project root)")
def scan(timeframe: str, top: int, min_score: int, workers: int,
         skip_save: bool, regime_filter: bool, params_path: str | None) -> None:
    """Daily scanner: rank top N USDT pairs by Ichimoku bull/bear score.

    Saves state to data/scan_state.json and shows notable changes vs previous run.

    Examples:
        ichi scan
        ichi scan --timeframe 4h --top 50
        ichi scan --min-score 12
        ichi scan --regime-filter     (only trending markets)
    """
    params = load_params(params_path)
    apply_params(params)
    registry = RuleRegistry.canonical()
    adx_threshold = float(params.get("adx_trending_threshold", 25.0))
    adx_strong = float(params.get("adx_strong_threshold", 40.0))

    today = date.today().isoformat()
    click.echo(f"\nDaily Scanner — {today}  [{timeframe}]\n")

    symbols = top_n_by_marketcap(n=top)
    prev_state = _load_prev_state(timeframe)

    btc_df = fetch_ohlcv("BTC/USDT", timeframe)
    rows = _score_all(symbols, timeframe, registry, workers, btc_df)

    if not rows:
        click.echo("No data returned.", err=True)
        return

    rows.sort(key=lambda r: (r["bull"], r["grade"]), reverse=True)

    if regime_filter:
        before = len(rows)
        rows_display = [r for r in rows if r["adx"] >= adx_threshold]
        click.echo(f"Regime filter ON (ADX ≥ {adx_threshold:.0f}): "
                   f"{len(rows_display)}/{before} symbols in trending regime\n")
    else:
        rows_display = rows

    _print_top_bull(rows_display, min_score, adx_threshold, adx_strong)
    _print_top_bear(rows_display)
    _print_state_changes(rows, prev_state)  # always compare full set for state changes

    click.echo(f"\n{len(rows)} symbols scanned.")

    if not skip_save:
        _save_state(today, timeframe, rows)


# ── Scoring ───────────────────────────────────────────────────────────────────

def _score_symbol(sym: str, timeframe: str, registry: RuleRegistry,
                  btc_df: pd.DataFrame | None) -> dict | None:
    try:
        df = fetch_ohlcv(sym, timeframe)
        if df.empty or len(df) < 60:
            return None
        df = ichimoku(df)
        precompute(df)
        i = len(df) - 1
        sc: Scorecard = evaluate(df, i, registry)
        flags = _extract_flags(sc)
        adx_val = float(df["_adx"].iat[i]) if "_adx" in df.columns and not df["_adx"].isna().iat[i] else 0.0
        plus_di = float(df["_plus_di"].iat[i]) if "_plus_di" in df.columns and not df["_plus_di"].isna().iat[i] else 0.0
        minus_di = float(df["_minus_di"].iat[i]) if "_minus_di" in df.columns and not df["_minus_di"].isna().iat[i] else 0.0
        di_confirmed = plus_di > minus_di
        vol_ratio = float(df["_vol_ratio"].iat[i]) if "_vol_ratio" in df.columns and not df["_vol_ratio"].isna().iat[i] else 1.0
        bb_squeeze_val = bool(df["_bb_squeeze"].iat[i]) if "_bb_squeeze" in df.columns and not pd.isna(df["_bb_squeeze"].iat[i]) else False
        bullish_div = bool(df["_bullish_div"].iat[i]) if "_bullish_div" in df.columns and not pd.isna(df["_bullish_div"].iat[i]) else False
        bearish_div = bool(df["_bearish_div"].iat[i]) if "_bearish_div" in df.columns and not pd.isna(df["_bearish_div"].iat[i]) else False

        # Cloud position: price vs current cloud
        close_val = float(df["close"].iat[i])
        span_a_val = float(df["span_a"].iat[i]) if "span_a" in df.columns and not pd.isna(df["span_a"].iat[i]) else None
        span_b_val = float(df["span_b"].iat[i]) if "span_b" in df.columns and not pd.isna(df["span_b"].iat[i]) else None
        if span_a_val is not None and span_b_val is not None:
            cloud_top = max(span_a_val, span_b_val)
            cloud_bot = min(span_a_val, span_b_val)
            if close_val > cloud_top:
                cloud = "ABOVE"
            elif close_val < cloud_bot:
                cloud = "BELOW"
            else:
                cloud = "IN"
        else:
            cloud = "UNKNOWN"

        # Forward cloud direction
        span_a_lead = float(df["span_a_lead"].iat[i]) if "span_a_lead" in df.columns and not pd.isna(df["span_a_lead"].iat[i]) else None
        span_b_lead = float(df["span_b_lead"].iat[i]) if "span_b_lead" in df.columns and not pd.isna(df["span_b_lead"].iat[i]) else None
        if span_a_lead is not None and span_b_lead is not None:
            fwd_cloud = "BULL" if span_a_lead > span_b_lead else "BEAR"
        else:
            fwd_cloud = "UNKNOWN"

        rs = relative_strength(df, btc_df) if btc_df is not None and not btc_df.empty else {}
        rs_lbl = rs_label(rs.get("rs_7d", float("nan")), rs.get("rs_14d", float("nan"))) if rs else ""

        return {
            "symbol": sym.replace("/USDT", ""),
            "sym_full": sym,
            "bull": sc.bull_score,
            "bear": sc.bear_score,
            "total": sc.total_scoring_rules,
            "grade": sc.grade,
            "chikou": sc.chikou_angle_val,
            "adx": adx_val,
            "plus_di": plus_di,
            "minus_di": minus_di,
            "di_confirmed": di_confirmed,
            "vol_ratio": vol_ratio,
            "bb_squeeze": bb_squeeze_val,
            "bullish_div": bullish_div,
            "bearish_div": bearish_div,
            "cloud": cloud,
            "fwd_cloud": fwd_cloud,
            "rs_label": rs_lbl,
            "rs_score": rs.get("rs_score", 0),
            "flags": flags,
            "rules": sc.rules,
        }
    except Exception as exc:
        logger.warning("%s: %s", sym, exc)
        return None


def _score_all(symbols: list[str], timeframe: str, registry: RuleRegistry,
               workers: int, btc_df: pd.DataFrame | None = None) -> list[dict]:
    rows: list[dict] = []
    with ThreadPoolExecutor(max_workers=workers) as pool:
        futures = {pool.submit(_score_symbol, sym, timeframe, registry, btc_df): sym for sym in symbols}
        for fut in as_completed(futures):
            result = fut.result()
            if result:
                rows.append(result)
    return rows


# ── Output formatting ─────────────────────────────────────────────────────────

def _print_top_bull(rows: list[dict], min_score: int,
                    adx_threshold: float = 25.0, adx_strong: float = 40.0) -> None:
    click.echo("Top Bull Scores:")
    shown = 0
    for row in rows:
        if row["bull"] < min_score:
            continue
        flags = list(row["flags"]) if row["flags"] else []
        if row.get("bb_squeeze"):
            flags.append("SQUEEZE")
        if row.get("vol_ratio", 1.0) >= 2.0:
            flags.append(f"VOL {row['vol_ratio']:.1f}x")
        if row.get("bullish_div"):
            flags.append("RSI-DIV↑")
        lbl = row.get("rs_label", "")
        if lbl in ("STRONG↑", "WEAK↓"):
            flags.append(f"RS:{lbl}")
        flags_str = "  ".join(flags)
        chikou_str = f"{row['chikou']:+.0f}°"
        score_str = f"{row['bull']}/{row['total']}"
        adx_val = row["adx"]
        if adx_val >= adx_strong:
            regime_str = f"ADX {adx_val:.0f} 🔥"
        elif adx_val >= adx_threshold:
            regime_str = f"ADX {adx_val:.0f} ↗"
        else:
            regime_str = f"ADX {adx_val:.0f} ~"
        di_str = f"+DI {row['plus_di']:.0f}>{row['minus_di']:.0f}" if row["di_confirmed"] else f"-DI {row['minus_di']:.0f}>{row['plus_di']:.0f}"
        click.echo(
            f"  {row['symbol']:<12} {score_str:>6}  chikou {chikou_str:>5}  "
            f"{regime_str:<14}  {di_str:<16}  {flags_str}"
        )
        shown += 1
    if shown == 0:
        click.echo(f"  (none above min-score={min_score})")
    click.echo()


def _print_top_bear(rows: list[dict]) -> None:
    click.echo("Top Bear Scores:")
    bear_rows = sorted(rows, key=lambda r: r["bear"], reverse=True)
    shown = 0
    for row in bear_rows[:5]:
        if row["bear"] == 0:
            break
        chikou_str = f"{row['chikou']:+.0f}°"
        score_str = f"{row['bear']}/{row['total']}"
        click.echo(f"  {row['symbol']:<12} {score_str:>6}  chikou {chikou_str:>5}")
        shown += 1
    if shown == 0:
        click.echo("  (no meaningful bear signals)")
    click.echo()


def _print_state_changes(rows: list[dict], prev_state: dict) -> None:
    if not prev_state:
        click.echo("Notable State Changes: (no previous state — run again tomorrow)")
        return

    click.echo("Notable State Changes (vs previous run):")
    changes: list[tuple[int, str]] = []
    for row in rows:
        sym = row["symbol"]
        prev = prev_state.get(sym, {})
        prev_bull = prev.get("bull")
        if prev_bull is None:
            continue
        delta = row["bull"] - prev_bull
        if abs(delta) >= _CHANGE_THRESHOLD:
            new_flags = "  ".join(row["flags"]) if row["flags"] else ""
            delta_str = f"{delta:+d}"
            line = f"  {sym:<12} {prev_bull}→{row['bull']} ({delta_str})  {new_flags}"
            changes.append((abs(delta), line))

    if changes:
        for _, line in sorted(changes, reverse=True):
            click.echo(line)
    else:
        click.echo(f"  (no changes ≥ {_CHANGE_THRESHOLD} points vs previous run)")
    click.echo()


def _extract_flags(sc: Scorecard) -> list[str]:
    flags: list[str] = []
    for rule in sc.rules:
        label = _FLAG_MAP.get(rule.rule_id)
        if label and rule.qualifies_bull:
            flags.append(label)
    return flags


# ── State persistence ─────────────────────────────────────────────────────────

def _load_prev_state(timeframe: str) -> dict:
    if not _STATE_FILE.exists():
        return {}
    try:
        with open(_STATE_FILE) as f:
            state = json.load(f)
        if state.get("timeframe") != timeframe:
            return {}
        return state.get("scores", {})
    except Exception:
        return {}


def _save_state(today: str, timeframe: str, rows: list[dict]) -> None:
    _STATE_FILE.parent.mkdir(parents=True, exist_ok=True)
    scores = {
        row["symbol"]: {"bull": row["bull"], "bear": row["bear"], "total": row["total"]}
        for row in rows
    }
    with open(_STATE_FILE, "w") as f:
        json.dump({"date": today, "timeframe": timeframe, "scores": scores}, f, indent=2)
