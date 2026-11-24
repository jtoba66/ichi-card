"""Signal filter and tier classification.

Applies validated backtest filters to classify signals into alert tiers:
  Tier 1 (T1): BTC above + QS 60+ + Hosoda  (+20.71% avg/trade)
  Tier 2 (T2): BTC above + QS 60+            (+22.61% avg/trade)
  Tier 3 (T3): BTC above, all quality        (+9.76% avg/trade)
  None:         BTC below/inside — suppress (all signal types)

Special rules (all validated on 9k+ backtest signals, ATR trail-stop exits):
  - Signal 6 on 1w → always skip (-25% avg)
  - 1w timeframe → Hosoda NOT required for T1 (no-Hosoda = +152% on 1w)
  - FLAGGED_COINS → tagged in notifications, NOT blocked (tag only)
  - Bearish twist 6-10 bars ago → boost alert priority (+8.20% avg, W/L 9.28)
  - Fresh bullish twist (0-5 bars) → reduce priority (+0.34%, weakest bucket)
  - 4h weak types (3/4/7/9): require QS≥60 or skip
      Type 3 (KJ Retest):  -1.82% avg on 4h without QS filter
      Type 4 (E2E):        -0.64% avg on 4h without QS filter
      Type 7 (4-Level):    -0.06% avg on 4h without QS filter
      Type 9 (Chikou):     -0.11% avg on 4h without QS filter
      Same types on 1d/1w are fine — timeframe-specific rule only
  - BTC vol floor (rvol_20 < 36% ann.) → HARD SKIP (skip=True, skip_reason="btc_low_vol")
      Low BTC vol = low alt momentum = signals don't follow through
      Validated: low-vol bucket = 42% win vs 61% for high-vol (9k+ signals)
      55.0% win kept (60% of signals) vs 49.3% baseline — consistent across all regimes
  - 4h bull_score < 16 → HARD SKIP (skip=True, skip_reason="4h_low_bull_score")
      Validated: 4h T1 at score 11-12 = -4.5% median; at ≥16 = 63.5% win
"""
from __future__ import annotations

import time
from typing import Optional

import numpy as np
import pandas as pd

# ── Flagged coins ──────────────────────────────────────────────────────────────
# Poor performers — tagged in notifications but NOT blocked.
# These coins have bad historical win rates even in BTC bull regime.
# The notifier adds a warning when any of these fires.
FLAGGED_COINS: frozenset[str] = frozenset({
    "EIGENUSDT", "SFPUSDT", "FFUSDT", "APEUSDT", "XMRUSDT", "BATUSDT",
    "SYRUPUSDT", "VIRTUALUSDT", "TIAUSDT", "TRUMPUSDT",
    "JUPUSDT", "POLUSDT", "FARTCOINUSDT", "GRASSUSDT",
    "CHEEMSUSDT", "WLFIUSDT", "WIFUSDT",
})
BAD_COINS = FLAGGED_COINS  # backward-compat alias

# ── 4h weak types ──────────────────────────────────────────────────────────────
# These signal types underperform on 4h without quality filter (negative or near-zero avg).
# On 1d/1w they perform well — this rule is 4h-only.
_4H_WEAK_TYPES: frozenset[int] = frozenset({3, 4, 7, 9})

# ── BTC vol floor ─────────────────────────────────────────────────────────────
# 33rd percentile of BTC 20-bar annualized realized vol (from 2627-signal backtest).
# Below this threshold: win rate drops to 42% vs 61% above — mark priority_reduce.
BTC_RVOL_FLOOR: float = 0.36  # 36% annualized

# ── BTC/ETH 1d regime caches ──────────────────────────────────────────────────
_btc_regime_cache: dict = {"regime": "unknown", "expires": 0.0}
_eth_regime_cache: dict = {"regime": "unknown", "expires": 0.0}
_btc_vol_cache:   dict = {"rvol": None, "expires": 0.0}
_BTC_CACHE_TTL = 300  # 5 minutes — safe to reuse across one scan cycle


def _get_regime(pair: str, cache: dict, force_refresh: bool = False) -> str:
    """Generic cached 1d cloud regime check for any pair."""
    now = time.monotonic()
    if not force_refresh and now < cache["expires"]:
        return cache["regime"]
    try:
        from ichi.data.fetcher import fetch_ohlcv
        from ichi.indicators.ichimoku import ichimoku
        df  = fetch_ohlcv(pair, "1d")
        df  = ichimoku(df)
        last  = df.iloc[-1]
        close = float(last["close"])
        top   = float(max(last["span_a"], last["span_b"]))
        bot   = float(min(last["span_a"], last["span_b"]))
        if close > top:
            regime = "above"
        elif close < bot:
            regime = "below"
        else:
            regime = "inside"
    except Exception:
        regime = "unknown"
    cache["regime"]  = regime
    cache["expires"] = now + _BTC_CACHE_TTL
    return regime


def get_btc_1d_regime(force_refresh: bool = False) -> str:
    """Return 'above', 'inside', 'below', or 'unknown'. Cached for 5 min."""
    return _get_regime("BTC/USDT", _btc_regime_cache, force_refresh)


def get_eth_1d_regime(force_refresh: bool = False) -> str:
    """Return 'above', 'inside', 'below', or 'unknown'. Cached for 5 min."""
    return _get_regime("ETH/USDT", _eth_regime_cache, force_refresh)


def get_btc_rvol(force_refresh: bool = False) -> float | None:
    """Return BTC 20-bar annualized realized vol. Cached 5 min.

    Used by live scanner to check vol regime at signal time.
    Returns None if BTC data unavailable (treated as vol_ok=True to avoid false suppression).
    """
    now = time.monotonic()
    if not force_refresh and now < _btc_vol_cache["expires"]:
        return _btc_vol_cache["rvol"]
    try:
        from ichi.data.fetcher import fetch_ohlcv
        df      = fetch_ohlcv("BTC/USDT", "1d")
        log_ret = np.log(df["close"] / df["close"].shift(1))
        rvol    = float(log_ret.tail(21).std() * np.sqrt(365))  # ~20 diffs from 21 bars
        if np.isnan(rvol):
            rvol = None
    except Exception:
        rvol = None
    _btc_vol_cache["rvol"]    = rvol
    _btc_vol_cache["expires"] = now + _BTC_CACHE_TTL
    return rvol


# ── Cloud thickness ────────────────────────────────────────────────────────────

def cloud_thickness_pct(df: pd.DataFrame, bar_i: int) -> float:
    """Return abs(span_a - span_b) / close * 100 at bar_i. Thick cloud = better structure."""
    try:
        close = float(df["close"].iat[bar_i])
        sa    = float(df["span_a"].iat[bar_i])
        sb    = float(df["span_b"].iat[bar_i])
        if close > 0:
            return abs(sa - sb) / close * 100
    except Exception:
        pass
    return 0.0


# ── Chikou confirmation ────────────────────────────────────────────────────────

def chikou_confirmed(df: pd.DataFrame, bar_i: int) -> bool:
    """True if close[bar_i] > cloud top 26 bars ago AND > close 26 bars ago.

    Chikou above past cloud + past price means no overhead resistance — momentum is clear.
    Filters ~15k weak signals in backtest (+2.75% when confirmed vs baseline).
    """
    try:
        lag = bar_i - 26
        if lag < 0:
            return False
        close_now      = float(df["close"].iat[bar_i])
        close_past     = float(df["close"].iat[lag])
        cloud_top_past = float(max(df["span_a"].iat[lag], df["span_b"].iat[lag]))
        return close_now > cloud_top_past and close_now > close_past
    except Exception:
        return False


# ── Kumo twist age ─────────────────────────────────────────────────────────────

def kumo_twist_age(df: pd.DataFrame, bar_i: int) -> Optional[dict]:
    """Find the most recent kumo twist within the last 20 bars.

    Returns:
        direction: 'bearish' (span_a < span_b crossing) or 'bullish'
        bars_ago: int
        bucket: 'bearish_6_10' | 'bearish_0_5' | 'bullish_0_5' | 'other'
    or None if no twist in last 20 bars.

    Bearish twist 6-10 bars ago = strong bullish context (+8.20% avg, W/L 9.28).
    Fresh bullish twist 0-5 bars ago = weakest bucket (+0.34% avg).
    """
    try:
        sa = df["span_a"].values
        sb = df["span_b"].values
        for j in range(bar_i, max(bar_i - 20, 1), -1):
            a_now  = float(sa[j])
            b_now  = float(sb[j])
            a_prev = float(sa[j - 1])
            b_prev = float(sb[j - 1])
            if a_now < b_now and a_prev >= b_prev:
                age = bar_i - j
                if 6 <= age <= 10:
                    bucket = "bearish_6_10"
                elif age <= 5:
                    bucket = "bearish_0_5"
                else:
                    bucket = "other"
                return {"direction": "bearish", "bars_ago": age, "bucket": bucket}
            if a_now > b_now and a_prev <= b_prev:
                age = bar_i - j
                bucket = "bullish_0_5" if age <= 5 else "other"
                return {"direction": "bullish", "bars_ago": age, "bucket": bucket}
    except Exception:
        pass
    return None


# ── ATR% ───────────────────────────────────────────────────────────────────────

def atr_pct(df: pd.DataFrame, bar_i: int) -> float:
    """Return ATR(14) / close * 100. High ATR (>5%) = higher volatility = bigger expected wins."""
    try:
        from ichi.signal.jobs import _compute_atr14
        close = float(df["close"].iat[bar_i])
        atr   = _compute_atr14(df, bar_i)
        if close > 0 and atr > 0:
            return atr / close * 100
    except Exception:
        pass
    return 0.0


# ── Main classifier ────────────────────────────────────────────────────────────

def classify_signal(
    signal_type: int,
    symbol: str,
    timeframe: str,
    quality_score: float | None,
    hosoda_active: bool,
    df: pd.DataFrame,
    bar_i: int,
    btc_regime: str | None = None,
    eth_regime: str | None = None,
    btc_rvol: float | None = None,
    bull_score: int = 0,
) -> dict:
    """Classify a signal into a tier and compute all filter metadata.

    Args:
        signal_type:   1-9 ichimoku signal number
        symbol:        e.g. 'BTCUSDT'
        timeframe:     '4h', '1d', '1w'
        quality_score: 0-100 IC-weighted score (None = unscored)
        hosoda_active: whether Hosoda timing is active at entry
        df:            ichimoku DataFrame for this symbol/timeframe
        bar_i:         current bar index (entry bar)
        btc_regime:    override BTC regime (if already fetched this scan cycle)
        eth_regime:    override ETH regime (if already fetched this scan cycle)
        btc_rvol:      BTC 20-bar annualized realized vol at signal time (None = fetch live)

    Returns dict with:
        tier:             1 | 2 | 3 | None (None = suppress)
        skip:             bool
        skip_reason:      str | None
        btc_regime:       'above' | 'inside' | 'below' | 'unknown'
        eth_regime:       'above' | 'inside' | 'below' | 'unknown'
        is_flagged:       bool  (coin is in FLAGGED_COINS — tag in alerts, not blocked)
        cloud_thickness:  float (% of price)
        chikou_ok:        bool
        twist:            dict | None  {direction, bars_ago, bucket}
        atr_pct:          float
        priority_boost:   bool  (bearish twist 6-10b OR ETH inside+BTC above → boost)
        priority_reduce:  bool  (low BTC vol OR fresh bullish twist 0-5 bars → lower alert)
        eth_boost:        bool  (ETH inside cloud + BTC above — alts very strong)
        btc_vol_ok:       bool  (True if BTC rvol >= BTC_RVOL_FLOOR or unknown)
        btc_rvol:         float | None  (annualized realized vol at signal time)
    """
    qs       = quality_score or 0.0
    regime   = btc_regime if btc_regime is not None else get_btc_1d_regime()
    eth_reg  = eth_regime if eth_regime is not None else get_eth_1d_regime()

    # BTC vol — fetch live if not provided (live scanner path)
    if btc_rvol is None:
        btc_rvol = get_btc_rvol()
    # Unknown vol (None) → treat as ok to avoid false suppression
    btc_vol_ok = (btc_rvol is None) or (btc_rvol >= BTC_RVOL_FLOOR)

    # ── Signal 10 (RSI Bounce) — chop-only mean-reversion overlay ───────────────
    # INVERTED regime vs the trend signals: its only validated edge is when BTC is
    # INSIDE the cloud (chop). 1d only — 4h/1w are unvalidated, so they're logged
    # but not alerted. Validated 1d (research/signal10_validation_2026-06-09):
    # chop median +15.5% / 78% win; bull mediocre; bear -17.7%. Bypasses the trend
    # gates (BTC-above, vol floor, 4h score) which don't apply to mean reversion.
    if signal_type == 10:
        ok = (timeframe == "1d" and regime == "inside")
        reason = None if ok else ("sig10_not_1d" if timeframe != "1d"
                                  else f"sig10_needs_chop_{regime}")
        return _build_result(
            tier=(2 if ok else None), skip=(not ok), skip_reason=reason,
            regime=regime, eth_regime=eth_reg, symbol=symbol, df=df, bar_i=bar_i,
            btc_vol_ok=btc_vol_ok, btc_rvol=btc_rvol,
        )

    # ── Hard skips ─────────────────────────────────────────────────────────────
    if signal_type == 6 and timeframe == "1w":
        return _build_result(
            tier=None, skip=True, skip_reason="signal6_1w_suppressed",
            regime=regime, eth_regime=eth_reg, symbol=symbol, df=df, bar_i=bar_i,
            btc_vol_ok=btc_vol_ok, btc_rvol=btc_rvol,
        )

    # 4h weak-type gate — types 3/4/7/9 require QS≥60 on 4h (validated: all are
    # negative or near-zero avg without quality filter on this timeframe)
    if timeframe == "4h" and signal_type in _4H_WEAK_TYPES and qs < 60:
        return _build_result(
            tier=None, skip=True, skip_reason=f"4h_type{signal_type}_needs_qs60",
            regime=regime, eth_regime=eth_reg, symbol=symbol, df=df, bar_i=bar_i,
            btc_vol_ok=btc_vol_ok, btc_rvol=btc_rvol,
        )

    # BTC vol gate — hard block when market has no momentum
    # Validated: low rvol_20 (<36%) signals win only 42% vs 61% above floor
    # Consistent across BTC bull, bear, and sideways regimes
    if not btc_vol_ok:
        return _build_result(
            tier=None, skip=True, skip_reason="btc_low_vol",
            regime=regime, eth_regime=eth_reg, symbol=symbol, df=df, bar_i=bar_i,
            btc_vol_ok=btc_vol_ok, btc_rvol=btc_rvol,
        )

    # 4h bull_score gate — 4h signals need score ≥16; <16 = -4.5% median on 4h T1
    if timeframe == "4h" and bull_score < 16:
        return _build_result(
            tier=None, skip=True, skip_reason="4h_low_bull_score",
            regime=regime, eth_regime=eth_reg, symbol=symbol, df=df, bar_i=bar_i,
            btc_vol_ok=btc_vol_ok, btc_rvol=btc_rvol,
        )

    # BTC regime gate — blocks all signals when BTC is below/inside cloud,
    # EXCEPT 1d signals with chikou confirmed + QS≥60 (RECOVERY track).
    # E2E exemption was removed (contradicted by frozen journal). RECOVERY is
    # allowed through because the track is specifically designed for chop/bear
    # conditions; alerts are marked higher-risk in the notifier body.
    if regime in ("below", "inside"):
        if timeframe == "1d" and qs >= 60 and chikou_confirmed(df, bar_i):
            # RECOVERY-eligible — pass as tier=2, notifier will classify track
            return _build_result(
                tier=2, skip=False, skip_reason=None,
                regime=regime, eth_regime=eth_reg, symbol=symbol, df=df, bar_i=bar_i,
                btc_vol_ok=btc_vol_ok, btc_rvol=btc_rvol,
            )
        return _build_result(
            tier=None, skip=True, skip_reason=f"btc_{regime}_cloud",
            regime=regime, eth_regime=eth_reg, symbol=symbol, df=df, bar_i=bar_i,
            btc_vol_ok=btc_vol_ok, btc_rvol=btc_rvol,
        )

    # ── Tier classification ────────────────────────────────────────────────────
    qs_ok = qs >= 60
    # On 1w, Hosoda inverts — no-Hosoda = +152%, so don't require it for T1 on weekly
    hosoda_ok = hosoda_active if timeframe != "1w" else True

    if qs_ok and hosoda_ok:
        tier = 1
    elif qs_ok:
        tier = 2
    else:
        tier = 3

    return _build_result(
        tier=tier, skip=False, skip_reason=None,
        regime=regime, eth_regime=eth_reg, symbol=symbol, df=df, bar_i=bar_i,
        btc_vol_ok=btc_vol_ok, btc_rvol=btc_rvol,
    )


def _build_result(
    tier: int | None, skip: bool, skip_reason: str | None,
    regime: str, eth_regime: str, symbol: str,
    df: pd.DataFrame, bar_i: int,
    btc_vol_ok: bool = True,
    btc_rvol: float | None = None,
) -> dict:
    thickness = cloud_thickness_pct(df, bar_i)
    chikou_ok = chikou_confirmed(df, bar_i)
    twist     = kumo_twist_age(df, bar_i)
    atr_p     = atr_pct(df, bar_i)

    # ETH inside cloud + BTC above = +3.88%, W/L 5.25 — alts very strong in this combo
    eth_boost = (regime == "above" and eth_regime == "inside")

    priority_boost  = (twist is not None and twist["bucket"] == "bearish_6_10") or eth_boost
    # priority_reduce: fresh bullish twist (low BTC vol is now a hard skip, never reaches here)
    priority_reduce = (twist is not None and twist["bucket"] == "bullish_0_5") or (not btc_vol_ok)

    return {
        "tier":            tier,
        "skip":            skip,
        "skip_reason":     skip_reason,
        "btc_regime":      regime,
        "eth_regime":      eth_regime,
        "is_flagged":      symbol in FLAGGED_COINS,
        "cloud_thickness": round(thickness, 2),
        "chikou_ok":       chikou_ok,
        "twist":           twist,
        "atr_pct":         round(atr_p, 2),
        "priority_boost":  priority_boost,
        "priority_reduce": priority_reduce,
        "eth_boost":       eth_boost,
        "btc_vol_ok":      btc_vol_ok,
        "btc_rvol":        round(btc_rvol, 4) if btc_rvol is not None else None,
    }
