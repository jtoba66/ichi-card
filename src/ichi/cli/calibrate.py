"""Calibration loop runner — SPEC.md §10.

Usage:
    ichi calibrate                        # score all 40 cases with current params
    ichi calibrate --holdout              # score the 12 held-out cases instead
    ichi calibrate --charts               # also render chart PNGs to research/charts/
    ichi calibrate --propose              # print parameter-adjustment proposals
    ichi calibrate --apply                # apply proposed adjustments and write params.yaml
    ichi calibrate --params path/to.yaml  # use a custom params file
"""
from __future__ import annotations

import json
import math
from datetime import date, timedelta
from pathlib import Path
from typing import Any

import click
import pandas as pd

from ichi.calibration.params import apply_params, load_params, save_params
from ichi.data.fetcher import fetch_ohlcv
from ichi.indicators.ichimoku import ichimoku
from ichi.indicators.precompute import precompute
from ichi.rules.registry import RuleRegistry
from ichi.scoring.engine import Scorecard, evaluate

_RESEARCH_DIR = Path(__file__).parents[3] / "research"
_CHARTS_DIR = _RESEARCH_DIR / "charts"
_CAL_CASES = _RESEARCH_DIR / "calibration_cases.json"
_HOLDOUT_CASES = _RESEARCH_DIR / "holdout_cases.json"
_MAX_CHANGE_PCT = 0.20   # sanity guard: 20% max shift per param per iteration


@click.command(name="calibrate")
@click.option("--holdout", is_flag=True, help="Score the held-out set instead of calibration cases")
@click.option("--charts", is_flag=True, help="Render chart PNGs to research/charts/")
@click.option("--propose", is_flag=True, help="Print parameter-adjustment proposals")
@click.option("--apply", "apply_changes", is_flag=True,
              help="Apply proposals and write updated params.yaml (requires --propose)")
@click.option("--params", "params_path", default=None,
              help="Path to params.yaml (default: project root params.yaml)")
def calibrate_cmd(holdout: bool, charts: bool, propose: bool, apply_changes: bool,
                  params_path: str | None) -> None:
    """Run one iteration of the calibration loop.

    Scores every case with current params, prints accuracy by case type,
    and optionally proposes + applies parameter adjustments.
    """
    cases_path = _HOLDOUT_CASES if holdout else _CAL_CASES
    label = "held-out" if holdout else "calibration"

    if not cases_path.exists():
        click.echo(f"Case file not found: {cases_path}", err=True)
        return

    params = load_params(params_path)
    apply_params(params)
    registry = RuleRegistry.canonical()

    with open(cases_path) as f:
        cases: list[dict] = json.load(f)

    click.echo(f"\n── Calibration Loop ─ {label} set ({len(cases)} cases) ──────────────────")
    click.echo(f"  params.yaml: {params_path or 'project root'}\n")

    if charts:
        _CHARTS_DIR.mkdir(parents=True, exist_ok=True)

    results: list[dict] = []
    for case in cases:
        row = _score_case(case, registry, params, render_chart=charts)
        results.append(row)
        _print_case_row(row)

    click.echo()
    accuracy = _accuracy_report(results)
    _print_accuracy(accuracy)

    if propose or apply_changes:
        click.echo()
        proposals = _propose_adjustments(accuracy, params)
        _print_proposals(proposals)

        if apply_changes and proposals:
            new_params = _apply_proposals(params, proposals)
            save_params(new_params, params_path)
            click.echo(f"\n  params.yaml updated ({len(proposals)} changes written).")
        elif apply_changes:
            click.echo("\n  No changes to apply.")


# ── Scoring ───────────────────────────────────────────────────────────────────

def _score_case(case: dict, registry: RuleRegistry, params: dict,
                render_chart: bool = False) -> dict:
    symbol = case["symbol"]
    timeframe = case.get("timeframe", "1d")
    cutoff = date.fromisoformat(case["cutoff_date"])
    case_type = case["case_type"]
    fwd_30d = case.get("fwd_return_30d")

    try:
        df = fetch_ohlcv(symbol, timeframe)
    except Exception as exc:
        return _error_row(case, f"fetch failed: {exc}")

    if df.empty or len(df) < 60:
        return _error_row(case, "insufficient history")

    df = ichimoku(df)
    precompute(df)

    # Find bar index for cutoff date
    dates = df.index.date
    idx = next((i for i, d in enumerate(dates) if d >= cutoff), None)
    if idx is None:
        return _error_row(case, f"cutoff {cutoff} not in data")

    try:
        sc: Scorecard = evaluate(df, idx, registry)
    except Exception as exc:
        return _error_row(case, f"eval error: {exc}")

    grade = sc.grade
    adx_val = float(df["_adx"].iat[idx]) if "_adx" in df.columns and not df["_adx"].isna().iat[idx] else 0.0
    plus_di = float(df["_plus_di"].iat[idx]) if "_plus_di" in df.columns and not df["_plus_di"].isna().iat[idx] else 0.0
    minus_di = float(df["_minus_di"].iat[idx]) if "_minus_di" in df.columns and not df["_minus_di"].isna().iat[idx] else 0.0
    adx_threshold = float(params.get("adx_trending_threshold", 25.0))
    # Combined regime: ADX trending AND +DI leading (buyers in control)
    trending = adx_val >= adx_threshold and plus_di > minus_di

    # Directional prediction from grade
    if grade >= 0.72:
        predicted = "bull_strong"
    elif grade >= 0.56:
        predicted = "bull_weak"
    elif grade <= 0.28:
        predicted = "bear_strong"
    elif grade <= 0.39:
        predicted = "bear_weak"
    else:
        predicted = "neutral"

    # Regime-aware prediction: suppress bull_strong when market is choppy
    regime_correct = None
    if trending:
        regime_correct = _is_correct(case_type, predicted, fwd_30d)
    else:
        # In choppy regime, treat any bull signal as non-actionable (neutral)
        regime_predicted = "neutral" if predicted in ("bull_strong", "bull_weak") else predicted
        regime_correct = _is_correct(case_type, regime_predicted, fwd_30d)

    correct = _is_correct(case_type, predicted, fwd_30d)

    if render_chart:
        _render_chart(symbol, timeframe, df, idx, sc, case, grade)

    return {
        "id": case.get("id", f"{symbol}_{cutoff}"),
        "symbol": symbol,
        "cutoff": str(cutoff),
        "case_type": case_type,
        "grade": grade,
        "bull_score": sc.bull_score,
        "bear_score": sc.bear_score,
        "predicted": predicted,
        "fwd_30d": fwd_30d,
        "correct": correct,
        "adx": adx_val,
        "plus_di": plus_di,
        "minus_di": minus_di,
        "trending": trending,
        "regime_correct": regime_correct,
        "error": None,
    }


def _is_correct(case_type: str, predicted: str, fwd_30d: float | None) -> bool | None:
    """Return True/False/None based on whether prediction matches expected outcome."""
    if fwd_30d is None:
        return None
    if case_type == "worked_bull":
        return predicted in ("bull_strong", "bull_weak") and fwd_30d > 0.05
    if case_type == "worked_bear":
        return predicted in ("bear_strong", "bear_weak") and fwd_30d < -0.02
    if case_type == "trap":
        # Trap: looks bullish but failed. Correct = system should NOT give high grade
        return predicted not in ("bull_strong",)
    if case_type == "chop":
        # Chop: low conviction outcome. Correct = system gives neutral/mixed signal
        return predicted in ("neutral", "bull_weak", "bear_weak")
    return None


def _error_row(case: dict, msg: str) -> dict:
    return {
        "id": case.get("id", "?"),
        "symbol": case["symbol"],
        "cutoff": case["cutoff_date"],
        "case_type": case["case_type"],
        "grade": float("nan"),
        "bull_score": -1,
        "bear_score": -1,
        "predicted": "error",
        "fwd_30d": case.get("fwd_return_30d"),
        "correct": None,
        "adx": float("nan"),
        "plus_di": float("nan"),
        "minus_di": float("nan"),
        "trending": False,
        "regime_correct": None,
        "error": msg,
    }


# ── Accuracy ──────────────────────────────────────────────────────────────────

def _accuracy_report(results: list[dict]) -> dict[str, Any]:
    by_type: dict[str, list] = {}
    for r in results:
        ct = r["case_type"]
        by_type.setdefault(ct, []).append(r)

    report: dict[str, Any] = {}
    for ct, rows in by_type.items():
        decided = [r for r in rows if r["correct"] is not None]
        hits = sum(1 for r in decided if r["correct"])
        grades = [r["grade"] for r in rows if not math.isnan(r["grade"])]
        adx_vals = [r["adx"] for r in rows if not math.isnan(r["adx"])]
        # Regime-aware accuracy
        regime_decided = [r for r in rows if r["regime_correct"] is not None]
        regime_hits = sum(1 for r in regime_decided if r["regime_correct"])
        report[ct] = {
            "n": len(rows),
            "decided": len(decided),
            "hits": hits,
            "hit_rate": hits / len(decided) if decided else float("nan"),
            "mean_grade": sum(grades) / len(grades) if grades else float("nan"),
            "mean_adx": sum(adx_vals) / len(adx_vals) if adx_vals else float("nan"),
            "regime_decided": len(regime_decided),
            "regime_hits": regime_hits,
            "regime_hit_rate": regime_hits / len(regime_decided) if regime_decided else float("nan"),
        }
    all_decided = [r for r in results if r["correct"] is not None]
    all_hits = sum(1 for r in all_decided if r["correct"])
    all_regime_decided = [r for r in results if r["regime_correct"] is not None]
    all_regime_hits = sum(1 for r in all_regime_decided if r["regime_correct"])
    report["_overall"] = {
        "n": len(results),
        "decided": len(all_decided),
        "hits": all_hits,
        "hit_rate": all_hits / len(all_decided) if all_decided else float("nan"),
        "regime_decided": len(all_regime_decided),
        "regime_hits": all_regime_hits,
        "regime_hit_rate": all_regime_hits / len(all_regime_decided) if all_regime_decided else float("nan"),
    }
    return report


# ── Proposals ─────────────────────────────────────────────────────────────────

def _propose_adjustments(accuracy: dict, params: dict) -> list[dict]:
    """Heuristic proposals based on accuracy gaps per case type."""
    proposals: list[dict] = []

    worked_bull_rate = accuracy.get("worked_bull", {}).get("hit_rate", float("nan"))
    worked_bear_rate = accuracy.get("worked_bear", {}).get("hit_rate", float("nan"))
    trap_rate = accuracy.get("trap", {}).get("hit_rate", float("nan"))
    chop_rate = accuracy.get("chop", {}).get("hit_rate", float("nan"))

    worked_bull_grade = accuracy.get("worked_bull", {}).get("mean_grade", float("nan"))
    trap_grade = accuracy.get("trap", {}).get("mean_grade", float("nan"))

    TARGET = 0.70

    # Trap cases scoring too high → tighten slope threshold (make rising harder to qualify)
    if not math.isnan(trap_rate) and trap_rate < TARGET and not math.isnan(trap_grade) and trap_grade > 0.6:
        proposals.append({
            "param": "slope_rising_threshold",
            "old": params["slope_rising_threshold"],
            "new": _cap_change(params["slope_rising_threshold"], factor=1.10),
            "rationale": f"Trap cases avg grade={trap_grade:.2f} (too high, rate={trap_rate:.0%}). "
                         "Tightening slope_rising_threshold reduces false bull signals.",
        })

    # Worked bull cases scoring too low → loosen slope or angle threshold
    if not math.isnan(worked_bull_rate) and worked_bull_rate < TARGET:
        if not math.isnan(worked_bull_grade) and worked_bull_grade < 0.65:
            proposals.append({
                "param": "angle_gte10_threshold",
                "old": params["angle_gte10_threshold"],
                "new": _cap_change(params["angle_gte10_threshold"], factor=0.90),
                "rationale": f"Worked bull grade avg={worked_bull_grade:.2f} (too low, rate={worked_bull_rate:.0%}). "
                             "Loosening angle_gte10_threshold to capture more valid bull setups.",
            })

    # Chop cases scoring too high → raise neutral-band thresholds
    chop_grade = accuracy.get("chop", {}).get("mean_grade", float("nan"))
    if not math.isnan(chop_rate) and chop_rate < TARGET and not math.isnan(chop_grade) and chop_grade > 0.5:
        proposals.append({
            "param": "away_from_spanb_threshold",
            "old": params["away_from_spanb_threshold"],
            "new": _cap_change(params["away_from_spanb_threshold"], factor=1.10),
            "rationale": f"Chop cases avg grade={chop_grade:.2f} (too high, rate={chop_rate:.0%}). "
                         "Raising away_from_spanb_threshold makes chop less likely to pass.",
        })

    # Worked bear cases not getting low grades → loosen bear-side thresholds
    if not math.isnan(worked_bear_rate) and worked_bear_rate < TARGET:
        proposals.append({
            "param": "no_bear_setup_threshold",
            "old": params["no_bear_setup_threshold"],
            "new": _cap_change(params["no_bear_setup_threshold"], factor=0.90, integer=True),
            "rationale": f"Worked bear hit rate={worked_bear_rate:.0%}. "
                         "Lowering no_bear_setup_threshold to flag bear setups earlier.",
        })

    return proposals


def _cap_change(old: float, factor: float, integer: bool = False) -> float:
    """Apply factor but cap the change at _MAX_CHANGE_PCT."""
    raw = old * factor
    if factor > 1.0:
        raw = min(raw, old * (1 + _MAX_CHANGE_PCT))
    else:
        raw = max(raw, old * (1 - _MAX_CHANGE_PCT))
    return round(int(raw)) if integer else round(raw, 6)


def _apply_proposals(params: dict, proposals: list[dict]) -> dict:
    new_params = dict(params)
    for p in proposals:
        new_params[p["param"]] = p["new"]
    return new_params


# ── Chart rendering ───────────────────────────────────────────────────────────

def _render_chart(symbol: str, timeframe: str, df: pd.DataFrame, idx: int,
                  sc: Scorecard, case: dict, grade: float) -> None:
    try:
        from ichi.viz.chart import render_chart
        out_path = _CHARTS_DIR / f"{case.get('id', symbol + '_' + case['cutoff_date'])}.png"
        render_chart(df, symbol, timeframe, save_path=str(out_path), focus_index=idx)
    except Exception as exc:
        click.echo(f"  [chart error for {symbol}]: {exc}", err=True)


# ── Display ───────────────────────────────────────────────────────────────────

def _print_case_row(row: dict) -> None:
    if row["error"]:
        click.echo(f"  {row['id']:30s}  ERROR: {row['error']}")
        return
    grade_pct = f"{row['grade']*100:.0f}%"
    fwd = f"{row['fwd_30d']*100:+.1f}%" if row["fwd_30d"] is not None else "   n/a"
    correct_str = "✓" if row["correct"] else ("✗" if row["correct"] is False else "·")
    adx_str = f"ADX {row['adx']:.0f}" if not math.isnan(row["adx"]) else "ADX  ?"
    regime_str = "↗+DI" if row["trending"] else "~"
    # Show regime_correct only when it differs from plain correct
    regime_flag = ""
    if row["regime_correct"] is not None and row["regime_correct"] != row["correct"]:
        regime_flag = " [→✓ w/regime]" if row["regime_correct"] else " [→✗ w/regime]"
    click.echo(
        f"  {correct_str} {row['id']:30s}  "
        f"grade={grade_pct:>4s}  "
        f"({row['bull_score']:>2}/{row['bull_score']+row['bear_score']:>2})  "
        f"pred={row['predicted']:12s}  "
        f"fwd30d={fwd}  "
        f"{adx_str} {regime_str}  "
        f"[{row['case_type']}]{regime_flag}"
    )


def _print_accuracy(accuracy: dict) -> None:
    click.echo("── Accuracy by case type ─────────────────────────────────────────────────")
    click.echo(f"  {'':15s}  {'raw':>5s}  {'regime':>7s}  mean_grade  mean_ADX")
    for ct, stats in sorted(accuracy.items()):
        if ct == "_overall":
            continue
        rate = stats["hit_rate"]
        r_rate = stats["regime_hit_rate"]
        rate_str = f"{rate*100:.0f}%" if not math.isnan(rate) else " n/a"
        r_rate_str = f"{r_rate*100:.0f}%" if not math.isnan(r_rate) else " n/a"
        grade_str = f"{stats['mean_grade']*100:.0f}%" if not math.isnan(stats["mean_grade"]) else " n/a"
        adx_str = f"{stats['mean_adx']:.1f}" if not math.isnan(stats["mean_adx"]) else " n/a"
        flag = "✓" if not math.isnan(rate) and rate >= 0.70 else "✗"
        r_flag = "✓" if not math.isnan(r_rate) and r_rate >= 0.70 else "✗"
        click.echo(
            f"  {flag} {ct:15s}  {rate_str:>4s}   "
            f"{r_flag} {r_rate_str:>4s}   "
            f"{grade_str:>8s}   {adx_str}"
        )
    ov = accuracy.get("_overall", {})
    ov_rate = ov.get("hit_rate", float("nan"))
    ov_r_rate = ov.get("regime_hit_rate", float("nan"))
    ov_str = f"{ov_rate*100:.0f}%" if not math.isnan(ov_rate) else "n/a"
    ov_r_str = f"{ov_r_rate*100:.0f}%" if not math.isnan(ov_r_rate) else "n/a"
    click.echo(
        f"\n  Overall:  raw={ov_str} ({ov.get('hits', '?')}/{ov.get('decided', '?')})  "
        f"regime-aware={ov_r_str} ({ov.get('regime_hits', '?')}/{ov.get('regime_decided', '?')})"
    )


def _print_proposals(proposals: list[dict]) -> None:
    if not proposals:
        click.echo("── Parameter proposals ────────────────────────────────────────────────")
        click.echo("  No adjustments proposed — accuracy targets met or insufficient data.")
        return
    click.echo("── Parameter proposals (capped at ±20%) ─────────────────────────────────")
    for p in proposals:
        click.echo(f"  {p['param']:35s}  {p['old']} → {p['new']}")
        click.echo(f"      {p['rationale']}")
