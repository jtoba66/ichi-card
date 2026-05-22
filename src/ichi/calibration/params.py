"""Load and apply params.yaml to rule class/module attributes."""
from __future__ import annotations

from pathlib import Path
from typing import Any

import yaml

_DEFAULT_PARAMS_PATH = Path(__file__).parents[4] / "params.yaml"

_DEFAULTS: dict[str, Any] = {
    "slope_lookback": 5,
    "slope_rising_threshold": 0.3,
    "slope_falling_threshold": -0.3,
    "angle_gte10_threshold": 10.0,
    "angle_gte20_threshold": 20.0,
    "above_price_high_threshold": 0.05,
    "high_volume_multiplier": 1.5,
    "high_volume_sma_period": 20,
    "obv_lookback": 10,
    "no_div_window": 30,
    "no_div_pivot_lookback": 5,
    "triple_sweep_pivot_lookback": 20,
    "triple_sweep_window": 60,
    "triple_sweep_tolerance": 0.005,
    "tk_bounce_lookback": 5,
    "tk_bounce_tolerance": 0.01,
    "tk_bounce_vol_multiplier": 1.5,
    "tk_bounce_vol_sma": 20,
    "chikou_cleared_pivot_lookback": 5,
    "chikou_cleared_window": 50,
    "chikou_cleared_n_pivots": 3,
    "no_tk_cross_lookback": 10,
    "kijun_flat_lookback": 10,
    "kijun_flat_threshold": 0.3,
    "away_from_spanb_threshold": 0.03,
    "tk_magnet_warning_bars": 10,
    "tk_magnet_tolerance": 0.015,
    "kj_balanced_window": 50,
    "kj_balanced_low_pct": 0.30,
    "kj_balanced_high_pct": 0.70,
    "no_fakeout_lookback": 10,
    "no_fakeout_reversal_window": 3,
    "kj_aligned_trend_lookback": 50,
    "kj_aligned_slope_lookback": 10,
    "tk_no_curl_lookback": 3,
    "kj_no_curl_lookback": 3,
    "cloud_curling_just_turned_bars": 5,
    "cloud_curling_slope_lookback": 5,
    "fwd_thick_threshold": 0.01,
    "sanyaku_transition_window": 5,
    "kumo_trap_lookback": 5,
    "ssb_direction_lookback": 10,
    "ssb_direction_threshold": 0.3,
    "no_bear_setup_threshold": 5,
    "adx_period": 14,
    "adx_trending_threshold": 25.0,
    "adx_strong_threshold": 40.0,
}


def load_params(path: Path | str | None = None) -> dict[str, Any]:
    """Load params.yaml; fall back to built-in defaults for any missing key."""
    p = Path(path) if path else _DEFAULT_PARAMS_PATH
    if not p.exists():
        return dict(_DEFAULTS)
    with open(p) as f:
        loaded = yaml.safe_load(f) or {}
    return {**_DEFAULTS, **loaded}


def save_params(params: dict[str, Any], path: Path | str | None = None) -> None:
    """Write params to yaml, preserving numeric precision."""
    p = Path(path) if path else _DEFAULT_PARAMS_PATH
    with open(p, "w") as f:
        yaml.dump(params, f, default_flow_style=False, sort_keys=True)


def apply_params(params: dict[str, Any]) -> None:
    """Inject params into rule class attributes and shared module-level constants.

    Call this before RuleRegistry.canonical() to ensure fresh rule instances pick
    up the new values. Safe to call multiple times (idempotent given same params).
    """
    import ichi.rules.lines as lines_mod
    import ichi.rules.trend_position as tp_mod
    import ichi.rules.kumo as kumo_mod
    import ichi.rules.composites as comp_mod

    # ── lines.py module-level constants ───────────────────────────────────────
    lines_mod._SLOPE_LOOKBACK = int(params["slope_lookback"])
    lines_mod._SLOPE_RISING_THRESHOLD = float(params["slope_rising_threshold"])
    lines_mod._SLOPE_FALLING_THRESHOLD = float(params["slope_falling_threshold"])

    # ── trend_position rules ──────────────────────────────────────────────────
    tp_mod.AbovePriceRule._HIGH_THRESHOLD = float(params["above_price_high_threshold"])
    tp_mod.HighVolumeRule._MULTIPLIER = float(params["high_volume_multiplier"])
    tp_mod.HighVolumeRule._SMA_PERIOD = int(params["high_volume_sma_period"])
    tp_mod.OBVRisingRule._LOOKBACK = int(params["obv_lookback"])
    tp_mod.NoDivRule._WINDOW = int(params["no_div_window"])
    tp_mod.NoDivRule._PIVOT_LOOKBACK = int(params["no_div_pivot_lookback"])
    tp_mod.TripleSweepRule._PIVOT_LOOKBACK = int(params["triple_sweep_pivot_lookback"])
    tp_mod.TripleSweepRule._SWEEP_WINDOW = int(params["triple_sweep_window"])
    tp_mod.TripleSweepRule._TOLERANCE = float(params["triple_sweep_tolerance"])

    # Angle thresholds — AngleGte10 is in trend_position, AngleGte20 is in lines
    _patch_angle_rule(tp_mod, "AngleGte10Rule", float(params["angle_gte10_threshold"]))
    _patch_angle_rule(lines_mod, "AngleGte20Rule", float(params["angle_gte20_threshold"]))

    # ── lines rules ───────────────────────────────────────────────────────────
    lines_mod.TKBounceRule._LOOKBACK = int(params["tk_bounce_lookback"])
    lines_mod.TKBounceRule._TOLERANCE = float(params["tk_bounce_tolerance"])
    lines_mod.TKBounceRule._VOL_MULTIPLIER = float(params["tk_bounce_vol_multiplier"])
    lines_mod.TKBounceRule._VOL_SMA = int(params["tk_bounce_vol_sma"])
    lines_mod.ChikouClearedRule._PIVOT_LOOKBACK = int(params["chikou_cleared_pivot_lookback"])
    lines_mod.ChikouClearedRule._WINDOW = int(params["chikou_cleared_window"])
    lines_mod.ChikouClearedRule._N_PIVOTS = int(params["chikou_cleared_n_pivots"])
    lines_mod.NoTKCrossRule._LOOKBACK = int(params["no_tk_cross_lookback"])
    lines_mod.KijunFlatRule._LOOKBACK = int(params["kijun_flat_lookback"])
    lines_mod.KijunFlatRule._FLAT_THRESHOLD = float(params["kijun_flat_threshold"])
    lines_mod.AwayFromSpanBRule._THRESHOLD = float(params["away_from_spanb_threshold"])
    lines_mod.TKMagnetRule._WARNING_BARS = int(params["tk_magnet_warning_bars"])
    lines_mod.TKMagnetRule._TOLERANCE = float(params["tk_magnet_tolerance"])
    lines_mod.KJBalancedRule._WINDOW = int(params["kj_balanced_window"])
    lines_mod.KJBalancedRule._LOW_PCT = float(params["kj_balanced_low_pct"])
    lines_mod.KJBalancedRule._HIGH_PCT = float(params["kj_balanced_high_pct"])
    lines_mod.NoFakeoutRule._LOOKBACK = int(params["no_fakeout_lookback"])
    lines_mod.NoFakeoutRule._REVERSAL_WINDOW = int(params["no_fakeout_reversal_window"])
    lines_mod.KJAlignedRule._TREND_LOOKBACK = int(params["kj_aligned_trend_lookback"])
    lines_mod.KJAlignedRule._SLOPE_LOOKBACK = int(params["kj_aligned_slope_lookback"])
    lines_mod.TKNoCurlRule._LOOKBACK = int(params["tk_no_curl_lookback"])
    lines_mod.KJNoCurlRule._LOOKBACK = int(params["kj_no_curl_lookback"])

    # ── kumo rules ────────────────────────────────────────────────────────────
    kumo_mod.CloudCurlingRule._JUST_TURNED_BARS = int(params["cloud_curling_just_turned_bars"])
    kumo_mod.CloudCurlingRule._SLOPE_LOOKBACK = int(params["cloud_curling_slope_lookback"])
    kumo_mod.FwdThickRule._THRESHOLD = float(params["fwd_thick_threshold"])

    # ── composite rules ───────────────────────────────────────────────────────
    comp_mod.SanyakuRule._TRANSITION_WINDOW = int(params["sanyaku_transition_window"])
    comp_mod.KumoTrapRule._LOOKBACK = int(params["kumo_trap_lookback"])
    comp_mod.SSBDirectionRule._LOOKBACK = int(params["ssb_direction_lookback"])
    comp_mod.SSBDirectionRule._THRESHOLD = float(params["ssb_direction_threshold"])
    comp_mod.NoBearSetupRule._BEAR_THRESHOLD = int(params["no_bear_setup_threshold"])


def _patch_angle_rule(module: Any, class_name: str, threshold: float) -> None:
    """Patch an angle rule to use a different threshold by injecting a class attribute."""
    cls = getattr(module, class_name)
    cls._ANGLE_THRESHOLD = threshold
