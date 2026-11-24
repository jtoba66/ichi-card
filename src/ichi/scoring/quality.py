"""Signal Quality Score
======================
Replaces the broken bull_score (which clusters at 10-17/18 and has no
predictive power) with a 0-100 score based on which rules actually predict
positive exit_return outcomes per (signal_type, timeframe).

Built from IC (Information Coefficient) analysis of 39,539 closed signals:
  - Only rules with IC ≥ 0.05 (STRONG or USEFUL) are included per pair
  - score = Σ fired_rule_IC / max_possible_IC × 100
  - 100 = all predictive rules fired; 0 = none fired (or no predictive rules)

Signals / timeframes with no predictive rules return 0.0. This is meaningful:
  Signal 3 4h, Signal 7 4h, Signal 9 4h have near-random outcomes regardless
  of which rules fire — the signal detection itself is the only predictor.
"""
from __future__ import annotations

# ── IC lookup: (signal_type, timeframe) → {rule_id: IC} ──────────────────────
# Only rules with IC ≥ 0.05 (STRONG/USEFUL) included.
# Source: rule_ic_analysis.py run on 39,539 closed signals.

RULE_IC: dict[tuple[int, str], dict[str, float]] = {

    # ── Signal 1: Sanyaku ────────────────────────────────────────────────────
    (1, "1w"): {
        "cloud_curling":  0.270,
        "kumo_trap":      0.246,
        "away_from_spanb":0.204,
        "perfect_setup":  0.167,
        "bull_stack":     0.109,
        "angle_gte20":    0.101,
        "angle_gte10":    0.091,
        "both_rising":    0.073,
        "kj_rising":      0.062,
        "obv_rising":     0.060,
        "no_div":         0.060,
        "above_kijun":    0.058,
    },
    (1, "1d"): {
        "kumo_trap":      0.134,
        "cloud_curling":  0.116,
        "angle_gte10":    0.095,
        "no_div":         0.085,
        "high_volume":    0.073,
        "tk_rising":      0.073,
        "angle_gte20":    0.051,
    },
    (1, "4h"): {
        "kumo_trap":      0.067,
    },

    # ── Signal 2: Balanced Breakout ──────────────────────────────────────────
    (2, "1d"): {
        "no_bear_setup":  0.163,
        "obv_rising":     0.153,
        "sanyaku":        0.140,
        "tk_bullish":     0.134,
        "bull_stack":     0.134,
        "angle_gte10":    0.124,
        "angle_gte20":    0.113,
        "above_kijun":    0.101,
        "perfect_setup":  0.087,
        "away_from_spanb":0.087,
        "kj_no_curl":     0.084,
        "no_tk_cross":    0.080,
        "above_cloud":    0.078,
        "kijun_flat":     0.072,
        "kj_aligned":     0.069,
        "tk_magnet":      0.068,
        "tk_rising":      0.065,
        "high_volume":    0.064,
        "kumo_trap":      0.062,
        "kj_balanced":    0.058,
        "above_price":    0.051,
        "cs_clear":       0.051,
        "chikou_cleared": 0.050,
    },
    (2, "4h"): {
        "perfect_setup":  0.068,
        "angle_gte20":    0.055,
    },

    # ── Signal 3: KJ Break Retest ────────────────────────────────────────────
    (3, "1d"): {
        "kj_balanced":    0.082,
        "angle_gte20":    0.073,
        "tk_rising":      0.069,
        "triple_sweep":   0.060,
    },
    (3, "4h"): {},   # No predictive rules on 4h — signal quality not differentiable

    # ── Signal 4: E2E Entry ──────────────────────────────────────────────────
    (4, "1d"): {
        "kj_no_curl":     0.095,
        "full_bull":      0.081,
        "angle_gte20":    0.064,
        "obv_rising":     0.051,
    },
    (4, "4h"): {
        "full_bull":      0.119,
        "kumo_bullish":   0.061,
        "no_div":         0.058,
    },

    # ── Signal 5: Twist Breakout ─────────────────────────────────────────────
    (5, "1d"): {
        "bull_stack":     0.185,
        "kumo_trap":      0.153,
        "angle_gte10":    0.143,
        "obv_rising":     0.121,
        "tk_rising":      0.090,
        "angle_gte20":    0.086,
        "high_volume":    0.085,
        "above_kijun":    0.081,
        "triple_sweep":   0.076,
        "tk_bounce":      0.071,
        "kj_balanced":    0.058,
        "ssb_direction":  0.056,
        "no_bear_setup":  0.052,
    },
    (5, "4h"): {
        "kj_balanced":    0.067,
    },

    # ── Signal 6: Cloud Curling ──────────────────────────────────────────────
    (6, "1d"): {
        "perfect_setup":  0.094,
        "ssb_direction":  0.091,
        "angle_gte20":    0.066,
        "bull_stack":     0.059,
        "angle_gte10":    0.056,
    },
    (6, "4h"): {
        "kj_balanced":    0.068,
        "perfect_setup":  0.067,
    },

    # ── Signal 7: Four-Level Retest ──────────────────────────────────────────
    (7, "1d"): {
        "kumo_trap":      0.172,
        "angle_gte10":    0.139,
        "high_volume":    0.135,
        "angle_gte20":    0.125,
        "cloud_curling":  0.059,
    },
    (7, "4h"): {},   # No predictive rules on 4h

    # ── Signal 9: Chikou S/R Retest ──────────────────────────────────────────
    (9, "1d"): {
        "high_volume":    0.101,
        "triple_sweep":   0.100,
        "kumo_trap":      0.077,
    },
    (9, "4h"): {},   # No predictive rules on 4h
}

# Pre-compute max possible IC per (signal_type, timeframe)
_MAX_IC: dict[tuple[int, str], float] = {
    key: sum(v.values()) for key, v in RULE_IC.items()
}


def compute_quality_score(
    signal_type: int,
    timeframe: str,
    fired_rules: set[str],
) -> float:
    """Return a 0-100 quality score for a signal.

    Parameters
    ----------
    signal_type:  integer signal type (1-9)
    timeframe:    '1h', '4h', '1d', '1w'
    fired_rules:  set of rule_ids that qualifies_bull at the entry bar

    Returns
    -------
    float in [0, 100] — 0 if no predictive rules exist for this pair,
    100 if all predictive rules fired.
    """
    key = (signal_type, timeframe)
    ic_map = RULE_IC.get(key, {})
    max_ic = _MAX_IC.get(key, 0.0)
    if not ic_map or max_ic == 0.0:
        return 0.0
    score = sum(ic_map.get(r, 0.0) for r in fired_rules)
    return round(min(score / max_ic * 100, 100.0), 1)


def quality_label(score: float) -> str:
    """Human-readable label for a quality score."""
    if score >= 80:
        return "★★★ Elite"
    if score >= 60:
        return "★★ Strong"
    if score >= 40:
        return "★ Solid"
    if score >= 20:
        return "Weak"
    return "—"
