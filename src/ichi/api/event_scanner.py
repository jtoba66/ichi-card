"""Dashboard B event detection functions.

Each function takes a precomputed DataFrame (single symbol/TF) and returns
a dict (or list of dicts) describing events detected at the latest bar.
All functions expect precompute() to have been called on df first.
"""
from __future__ import annotations

import numpy as np
import pandas as pd


def _slope_label(val: float) -> str:
    if val > 0.3:
        return "RISING"
    if val < -0.3:
        return "FALLING"
    return "FLAT"


def get_transition_events(
    df: pd.DataFrame,
    symbol: str,
    timeframe: str,
    max_bars_ago: int = 10,
    min_conditions: int = 2,
) -> dict | None:
    """Fresh TK cross + chikou near/inside cloud + cloud curling upward.

    Returns None if fewer than min_conditions are met.
    Full cluster = all 3 conditions met.
    """
    if len(df) < 52:
        return None
    i = len(df) - 1

    tk_bars_ago = int(df["_tk_cross_bullish_bars_ago"].iat[i])
    tk_ok = tk_bars_ago <= max_bars_ago

    cs_in    = bool(df["_chikou_in_cloud"].iat[i])    if not pd.isna(df["_chikou_in_cloud"].iat[i])    else False
    cs_above = bool(df["_chikou_above_cloud"].iat[i]) if not pd.isna(df["_chikou_above_cloud"].iat[i]) else False
    cs_ok    = cs_in or cs_above

    curl    = bool(df["_cloud_curling_up"].iat[i])       if not pd.isna(df["_cloud_curling_up"].iat[i])       else False
    twisted = bool(df["_cloud_just_twisted_bull"].iat[i]) if not pd.isna(df["_cloud_just_twisted_bull"].iat[i]) else False
    cloud_ok = curl or twisted

    conditions_met = sum([tk_ok, cs_ok, cloud_ok])
    if conditions_met < min_conditions:
        return None

    close     = float(df["close"].iat[i])
    cloud_top = float(df["_cloud_top"].iat[i])
    cloud_bot = float(df["_cloud_bottom"].iat[i])
    cloud_pos = "ABOVE" if close > cloud_top else ("BELOW" if close < cloud_bot else "IN")
    vol = float(df["_vol_ratio"].iat[i]) if "_vol_ratio" in df.columns and not pd.isna(df["_vol_ratio"].iat[i]) else None

    return {
        "symbol":            symbol,
        "timeframe":         timeframe,
        "bars_ago":          tk_bars_ago if tk_ok else max_bars_ago,
        "tk_cross_ok":       tk_ok,
        "tk_cross_bars_ago": tk_bars_ago,
        "chikou_ok":         cs_ok,
        "chikou_state":      "ABOVE" if cs_above else ("IN" if cs_in else "BELOW"),
        "cloud_curl_ok":     cloud_ok,
        "cloud_curl_state":  "TWISTED" if twisted else ("CURLING" if curl else "FLAT"),
        "conditions_met":    conditions_met,
        "full_cluster":      conditions_met == 3,
        "cloud_position":    cloud_pos,
        "vol_ratio":         round(vol, 2) if vol is not None else None,
    }


def get_retest_alerts(
    df: pd.DataFrame,
    symbol: str,
    timeframe: str,
    bull_score: int,
    max_distance_pct: float = 2.0,
    cloud_break_lookback: int = 10,
) -> list[dict]:
    """Price retesting TK / KJ / cloud top / cloud bottom from above.

    Returns a list — one dict per level being tested simultaneously.
    Group A: confirmed uptrend (bull_score >= 13 + above cloud).
    Group B: recent breakout (broke above cloud within lookback bars).
    """
    if len(df) < 52:
        return []
    i = len(df) - 1
    close     = float(df["close"].iat[i])
    cloud_top = float(df["_cloud_top"].iat[i])
    cloud_bot = float(df["_cloud_bottom"].iat[i])
    above_cloud = close > cloud_top
    results = []

    tk = float(df["tk"].iat[i])
    kj = float(df["kj"].iat[i])
    tk_sl = _slope_label(float(df["_tk_slope5"].iat[i]) if not pd.isna(df["_tk_slope5"].iat[i]) else 0)
    kj_sl = _slope_label(float(df["_kj_slope5"].iat[i]) if not pd.isna(df["_kj_slope5"].iat[i]) else 0)
    bb = bool(df["_tk_near_count"].iat[i] > 0) if "_tk_near_count" in df.columns else False

    broke_out_bars_ago = None
    if above_cloud:
        for j in range(1, cloud_break_lookback + 1):
            if i - j < 0:
                break
            if float(df["close"].iat[i - j]) <= float(df["_cloud_top"].iat[i - j]):
                broke_out_bars_ago = j
                break

    def check(level_price: float, label: str, sl: str, critical: bool = False) -> None:
        if level_price <= 0:
            return
        dist = (close - level_price) / level_price * 100
        if not (0 <= dist <= max_distance_pct and close >= level_price):
            return
        base = {
            "symbol": symbol, "timeframe": timeframe,
            "level": label, "distance_pct": round(dist, 2),
            "slope": sl, "bull_score": bull_score,
            "bounce_history": bb, "critical": critical,
        }
        if bull_score >= 13 and above_cloud:
            results.append({**base, "group": "A", "broke_out_bars_ago": None})
        elif above_cloud and broke_out_bars_ago is not None:
            results.append({**base, "group": "B", "broke_out_bars_ago": broke_out_bars_ago})

    check(tk,        "TK",           tk_sl)
    check(kj,        "KJ",           kj_sl)
    check(cloud_top, "CLOUD TOP",    "FLAT")
    check(cloud_bot, "CLOUD BOTTOM", "FLAT", critical=True)

    return results


def get_balance_map(
    df: pd.DataFrame,
    symbol: str,
    timeframe: str,
    bull_score: int,
) -> dict | None:
    """Price distance from Kijun — equilibrium / imbalance monitor."""
    if len(df) < 26:
        return None
    i = len(df) - 1
    kj_dist = float(df["_kj_distance_pct"].iat[i]) if not pd.isna(df["_kj_distance_pct"].iat[i]) else 0.0
    tk_dist = float(df["_tk_distance_pct"].iat[i]) if not pd.isna(df["_tk_distance_pct"].iat[i]) else 0.0
    if kj_dist > 15:
        zone = "EXTENDED"
    elif kj_dist >= 5:
        zone = "ABOVE"       # above KJ but not overextended (+5 to +15%)
    elif kj_dist >= -5:
        zone = "BALANCED"
    else:
        zone = "BELOW"
    kj_sv = float(df["_kj_slope5"].iat[i]) if not pd.isna(df["_kj_slope5"].iat[i]) else 0.0
    return {
        "symbol":          symbol,
        "timeframe":       timeframe,
        "zone":            zone,
        "kj_distance_pct": round(kj_dist, 1),
        "tk_distance_pct": round(tk_dist, 1),
        "kj_slope":        _slope_label(kj_sv),
        "bull_score":      bull_score,
    }


def get_kumo_twist(
    df: pd.DataFrame,
    symbol: str,
    timeframe: str,
    bull_score: int,
    max_bars_ahead: int = 20,
) -> dict | None:
    """Upcoming kumo twist — date when leading cloud changes polarity."""
    if len(df) < 52:
        return None
    i = len(df) - 1

    span_a_lead = df["span_a_lead"]
    span_b_lead = df["span_b_lead"]

    # Current cloud direction from the shifted columns (span_a[i] = span_a_lead[i-26])
    current_cloud_bull = float(df["span_a"].iat[i]) > float(df["span_b"].iat[i])
    current_sign = 1 if current_cloud_bull else -1

    # The projected cloud k bars ahead = span_a_lead[i - 26 + k] for k = 1..26
    # (because span_a[i+k] = span_a_lead.shift(26)[i+k] = span_a_lead[i+k-26])
    # All these indices are within the existing dataframe — no lookahead needed.
    DISPLACEMENT = 26
    bars_until = None
    twist_dir  = None
    for k in range(1, min(max_bars_ahead + 1, DISPLACEMENT + 1)):
        lead_idx = i - DISPLACEMENT + k
        if lead_idx < 0:
            continue
        future_sign = np.sign(float(span_a_lead.iat[lead_idx]) - float(span_b_lead.iat[lead_idx]))
        if future_sign != current_sign and future_sign != 0:
            bars_until = k
            twist_dir  = "BULL_TWIST" if future_sign > 0 else "BEAR_TWIST"
            break

    if bars_until is None:
        return None

    notes = {
        ("BULL_TWIST", False): "Bull twist from bear cloud — watch for breakout",
        ("BULL_TWIST", True):  "Bull cloud accelerating — continuation likely",
        ("BEAR_TWIST", True):  "Bear twist approaching — watch for distribution",
        ("BEAR_TWIST", False): "Bear cloud deepening — avoid longs",
    }
    return {
        "symbol":           symbol,
        "timeframe":        timeframe,
        "bars_until_twist": bars_until,
        "twist_direction":  twist_dir,
        "current_cloud":    "BULL" if current_cloud_bull else "BEAR",
        "action_note":      notes[(twist_dir, current_cloud_bull)],
        "bull_score":       bull_score,
    }


def get_e2e_opportunity(
    df: pd.DataFrame,
    symbol: str,
    timeframe: str,
    bull_score: int,
    max_bars_ago: int = 5,
) -> dict | None:
    """Price just entered the kumo from below — E2E trade setup."""
    if len(df) < 52:
        return None
    i = len(df) - 1

    for bars_ago in range(0, max_bars_ago + 1):
        idx = i - bars_ago
        if idx < 1:
            break
        from_below = bool(df["_e2e_entry_from_below"].iat[idx]) if not pd.isna(df["_e2e_entry_from_below"].iat[idx]) else False
        if not from_below:
            continue

        entry     = float(df["close"].iat[idx])
        target    = float(df["_cloud_top"].iat[idx])
        target_pct = (target - entry) / entry * 100
        thickness  = float(df["_cloud_thickness_pct"].iat[idx]) if not pd.isna(df["_cloud_thickness_pct"].iat[idx]) else 0.0

        if target_pct <= 1.0:
            continue

        future_bull = float(df["span_a_lead"].iat[i]) > float(df["span_b_lead"].iat[i])
        confirmed   = bull_score >= 10 and future_bull and bars_ago == 0

        return {
            "symbol":              symbol,
            "timeframe":           timeframe,
            "direction":           "FROM_BELOW",
            "entry_price":         round(entry, 6),
            "target_price":        round(target, 6),
            "target_pct":          round(target_pct, 2),
            "cloud_thickness_pct": round(thickness, 2),
            "entered_bars_ago":    bars_ago,
            "bull_score":          bull_score,
            "confirmed":           confirmed,
        }

    return None


def get_cloud_curling(
    df: pd.DataFrame,
    symbol: str,
    timeframe: str,
    bull_score: int,
) -> dict | None:
    """Leading cloud transitioning from bearish to bullish — early warning."""
    if len(df) < 52:
        return None
    i = len(df) - 1

    just_twisted = bool(df["_cloud_just_twisted_bull"].iat[i]) if not pd.isna(df["_cloud_just_twisted_bull"].iat[i]) else False
    curling      = bool(df["_cloud_curling_up"].iat[i])         if not pd.isna(df["_cloud_curling_up"].iat[i])         else False

    if not just_twisted and not curling:
        return None

    if just_twisted:
        state = "JUST_TWISTED"
        bars_to_twist = 0
    else:
        current_sign  = np.sign(float(df["span_a_lead"].iat[i]) - float(df["span_b_lead"].iat[i]))
        bars_to_twist = 99
        for j in range(1, 20):
            if i + j >= len(df):
                break
            future_sign = np.sign(float(df["span_a_lead"].iat[i + j]) - float(df["span_b_lead"].iat[i + j]))
            if future_sign != current_sign:
                bars_to_twist = j
                break
        state = "IMMINENT" if bars_to_twist <= 5 else "EARLY"

    close     = float(df["close"].iat[i])
    cloud_top = float(df["_cloud_top"].iat[i])
    cloud_bot = float(df["_cloud_bottom"].iat[i])
    price_pos = "ABOVE" if close > cloud_top else ("BELOW" if close < cloud_bot else "IN")

    span_a_slope = float(df["_span_a_lead_slope5"].iat[i]) if not pd.isna(df["_span_a_lead_slope5"].iat[i]) else 0.0
    thickness    = float(df["_cloud_thickness_pct"].iat[i]) if not pd.isna(df["_cloud_thickness_pct"].iat[i]) else 0.0

    return {
        "symbol":              symbol,
        "timeframe":           timeframe,
        "state":               state,
        "bars_to_twist":       bars_to_twist,
        "span_a_lead_slope":   round(span_a_slope, 3),
        "cloud_thickness_pct": round(thickness, 2),
        "bull_score":          bull_score,
        "price_position":      price_pos,
    }
