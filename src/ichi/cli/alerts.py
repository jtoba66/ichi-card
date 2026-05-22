"""Threshold alert command — ichi alerts.

Scans the universe, compares scores to a threshold, and reports symbols that
newly crossed the threshold since the last run. Results are appended to
data/alerts.log.

Usage:
    ichi alerts
    ichi alerts --min-score 14 --timeframe 1d --top 50
    ichi alerts --workers 8 --params custom.yaml
"""
from __future__ import annotations

import json
import logging
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import date
from pathlib import Path

import click

from ichi.calibration.params import apply_params, load_params
from ichi.data.fetcher import fetch_ohlcv
from ichi.data.universe import top_n_by_marketcap
from ichi.indicators.ichimoku import ichimoku
from ichi.indicators.precompute import precompute
from ichi.rules.registry import RuleRegistry
from ichi.scoring.engine import Scorecard, evaluate

logger = logging.getLogger(__name__)

_STATE_FILE = Path(__file__).parents[3] / "data" / "alerts_state.json"
_LOG_FILE = Path(__file__).parents[3] / "data" / "alerts.log"

_FLAG_MAP = {
    "perfect_setup": "⭐ PERFECT",
    "triple_sweep": "TRP↑",
    "sanyaku": "SNY↑",
    "cloud_curling": "☁↑",
    "kumo_trap": "TRAP",
    "no_bear_setup": None,  # informational only
}


@click.command()
@click.option("--min-score", default=14, show_default=True, help="Alert threshold (bull score)")
@click.option("--timeframe", "-t", default="1d", show_default=True, help="Timeframe to scan")
@click.option("--top", "-n", default=200, show_default=True, help="Number of pairs to scan")
@click.option("--workers", default=8, show_default=True, help="Parallel fetch workers")
@click.option("--params", "params_path", default=None, help="Path to params.yaml (default: project root)")
def alerts(
    min_score: int,
    timeframe: str,
    top: int,
    workers: int,
    params_path: str | None,
) -> None:
    """Threshold alert: report symbols that newly crossed --min-score.

    Compares current scores to the previous run (data/alerts_state.json) and
    prints NEW (crossed above) and DROPPED (fell below) symbols. Appends to
    data/alerts.log and saves updated state.

    Examples:
        ichi alerts
        ichi alerts --min-score 14 --top 50
        ichi alerts --timeframe 4h --min-score 12
    """
    params = load_params(params_path)
    apply_params(params)
    registry = RuleRegistry.canonical()
    adx_threshold = float(params.get("adx_trending_threshold", 25.0))
    adx_strong = float(params.get("adx_strong_threshold", 40.0))

    today = date.today().isoformat()
    click.echo(f"\nAlerts — {today}  [{timeframe}]  threshold={min_score}/18\n")

    symbols = top_n_by_marketcap(n=top)
    prev_scores = _load_prev_state(timeframe)

    rows = _score_all(symbols, timeframe, registry, workers)
    if not rows:
        click.echo("No data returned.", err=True)
        return

    # Partition into new alerts, dropped, above, and below
    new_alerts: list[dict] = []
    dropped: list[dict] = []
    already_above: list[dict] = []
    already_below: list[dict] = []

    for row in rows:
        sym = row["symbol"]
        curr = row["bull"]
        prev = prev_scores.get(sym, {}).get("bull")

        if curr >= min_score:
            if prev is None or prev < min_score:
                new_alerts.append(row)
            else:
                already_above.append(row)
        else:  # curr < min_score
            if prev is not None and prev >= min_score:
                dropped.append(row)
            else:
                already_below.append(row)

    # Sort new alerts by current score descending
    new_alerts.sort(key=lambda r: r["bull"], reverse=True)
    dropped.sort(key=lambda r: r["bull"], reverse=True)

    # Print NEW alerts
    click.echo(f"🔔 NEW (crossed above {min_score}):")
    if new_alerts:
        for row in new_alerts:
            sym = row["symbol"]
            prev_bull = prev_scores.get(sym, {}).get("bull")
            prev_str = str(prev_bull) if prev_bull is not None else "?"
            score_arrow = f"{prev_str}→{row['bull']}"
            chikou_str = f"chikou {row['chikou']:+.0f}°"
            adx_val = row["adx"]
            if adx_val >= adx_strong:
                regime_str = f"ADX {adx_val:.0f} 🔥"
            elif adx_val >= adx_threshold:
                regime_str = f"ADX {adx_val:.0f} ↗"
            else:
                regime_str = f"ADX {adx_val:.0f} ~"
            flags = "  ".join(row["flags"]) if row["flags"] else ""
            click.echo(
                f"  {sym:<6} {score_arrow:<8}  {chikou_str:<14}  {regime_str:<16}  {flags}"
            )
    else:
        click.echo("  (none)")
    click.echo()

    # Print DROPPED
    click.echo(f"📉 DROPPED (fell below {min_score}):")
    if dropped:
        for row in dropped:
            sym = row["symbol"]
            prev_bull = prev_scores.get(sym, {}).get("bull")
            prev_str = str(prev_bull) if prev_bull is not None else "?"
            score_arrow = f"{prev_str}→{row['bull']}"
            click.echo(f"  {sym:<6} {score_arrow}")
    else:
        click.echo("  (none)")
    click.echo()

    click.echo(
        f"No change: {len(already_above)} symbols already above / "
        f"{len(already_below)} below threshold."
    )
    click.echo()

    # Append to log
    log_count = _append_log(today, timeframe, min_score, new_alerts, dropped, prev_scores)
    if log_count > 0:
        click.echo(f"Appended {log_count} alerts to {_LOG_FILE}")
    else:
        click.echo(f"No new log entries (nothing crossed threshold).")

    # Save updated state
    _save_state(today, timeframe, rows)


# ── Scoring ───────────────────────────────────────────────────────────────────

def _score_symbol(sym: str, timeframe: str, registry: RuleRegistry) -> dict | None:
    try:
        df = fetch_ohlcv(sym, timeframe)
        if df.empty or len(df) < 60:
            return None
        df = ichimoku(df)
        precompute(df)
        i = len(df) - 1
        sc: Scorecard = evaluate(df, i, registry)
        flags = _extract_flags(sc)
        adx_val = (
            float(df["_adx"].iat[i])
            if "_adx" in df.columns and not df["_adx"].isna().iat[i]
            else 0.0
        )
        return {
            "symbol": sym.replace("/USDT", ""),
            "sym_full": sym,
            "bull": sc.bull_score,
            "bear": sc.bear_score,
            "total": sc.total_scoring_rules,
            "grade": sc.grade,
            "chikou": sc.chikou_angle_val,
            "adx": adx_val,
            "flags": flags,
            "rules": sc.rules,
        }
    except Exception as exc:
        logger.warning("%s: %s", sym, exc)
        return None


def _score_all(symbols: list[str], timeframe: str, registry: RuleRegistry, workers: int) -> list[dict]:
    rows: list[dict] = []
    with ThreadPoolExecutor(max_workers=workers) as pool:
        futures = {pool.submit(_score_symbol, sym, timeframe, registry): sym for sym in symbols}
        for fut in as_completed(futures):
            result = fut.result()
            if result:
                rows.append(result)
    return rows


# ── Flag extraction ───────────────────────────────────────────────────────────

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


# ── Log appending ─────────────────────────────────────────────────────────────

def _append_log(
    today: str,
    timeframe: str,
    min_score: int,
    new_alerts: list[dict],
    dropped: list[dict],
    prev_scores: dict,
) -> int:
    _LOG_FILE.parent.mkdir(parents=True, exist_ok=True)
    lines: list[str] = []

    for row in new_alerts:
        sym = row["symbol"]
        prev_bull = prev_scores.get(sym, {}).get("bull")
        prev_str = str(prev_bull) if prev_bull is not None else "?"
        adx_int = int(round(row["adx"]))
        lines.append(
            f"{today} {timeframe} threshold={min_score} NEW {sym} {prev_str}→{row['bull']} ADX={adx_int}\n"
        )

    for row in dropped:
        sym = row["symbol"]
        prev_bull = prev_scores.get(sym, {}).get("bull")
        prev_str = str(prev_bull) if prev_bull is not None else "?"
        lines.append(
            f"{today} {timeframe} threshold={min_score} DROPPED {sym} {prev_str}→{row['bull']}\n"
        )

    if lines:
        with open(_LOG_FILE, "a") as f:
            f.writelines(lines)

    return len(lines)
