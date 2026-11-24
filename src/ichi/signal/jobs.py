"""Background jobs for signal tracking.

CLI usage (run from ichi-scorecard/ root):

    # Nightly tracker — update open signals with returns and exit checks
    uv run python -m ichi.signal.jobs track

    # One-time historical backfill (slow ~1-2h for full universe)
    uv run python -m ichi.signal.jobs backfill [--top N] [--timeframes 1d,4h,1w]

    # Performance IC analysis
    uv run python -m ichi.signal.jobs signal-ic
"""
from __future__ import annotations

import json
import logging
import sys
from datetime import datetime, timezone
from typing import Optional

import pandas as pd
import psycopg2
import psycopg2.extras

from ichi.signal.db import get_conn
from ichi.signal.detector import (
    DB_PATH, _ONSET_TIME_COOLDOWN, detect_all_signals, init_db, log_signal,
)

logger = logging.getLogger(__name__)

# ── Exit condition checker ────────────────────────────────────────────────────

def _compute_atr14(df: pd.DataFrame, bar_i: int) -> float:
    """Wilder ATR(14) at bar_i. Returns 0.0 if not enough data."""
    start = max(0, bar_i - 14)
    sub = df.iloc[start: bar_i + 1]
    if len(sub) < 2:
        return 0.0
    import numpy as np
    h = sub["high"].values
    l = sub["low"].values
    c = sub["close"].values
    prev_c = np.concatenate([[c[0]], c[:-1]])
    tr = np.maximum(h - l, np.maximum(np.abs(h - prev_c), np.abs(l - prev_c)))
    atr = tr[0]
    for t in tr[1:]:
        atr = (atr * 13 + t) / 14
    return float(atr)


# Zombie backstop — only to catch trades that somehow escape the trailing stop.
# Based on simulation data: 4×ATR trail exits almost everything; this is a last resort.
_ZOMBIE_TIMEOUT_BARS: dict[str, int] = {
    "1h":  720,   # ~30 days
    "4h":  540,   # ~90 days
    "1d":  180,   # ~6 months
    "1w":  52,    # ~12 months
}
_DEFAULT_ZOMBIE_TIMEOUT = 300

# Trailing stop multiplier — timeframe-dependent, validated on 38k+ signals.
# 4h/1d: 6× (simulation: +2.15% → +2.15% on 4h, +17.78% → +31.12% on 1d)
# 1w: 4× (tighter is better on weekly, 6× gives back returns)
_TRAIL_ATR_MULT_BY_TF: dict[str, float] = {
    "1h": 6.0,
    "4h": 6.0,
    "1d": 6.0,
    "1w": 4.0,
}
_TRAIL_ATR_MULT_DEFAULT = 6.0


def check_exit_conditions(
    df: pd.DataFrame,
    entry_bar: int,
    current_bar: int,
    entry_price: float,
    signal_type: int,
    metadata: dict,
    timeframe: str = "1d",
) -> Optional[dict]:
    """ATR trailing stop — the only active exit rule.

    Multiplier is timeframe-dependent (6× on 4h/1d, 4× on 1w).
    Simulation across 38k+ signals showed this beats all alternatives:
    - Profit targets cut winners too early
    - Structural SL fires at the retest level itself for signals 3,4,7,9 (wrong)
    - Cloud reentry exit gives back 74% of peak profit on 1w
    - Kijun cross fires in 89% of trades, cuts winners short
    """
    mult = _TRAIL_ATR_MULT_BY_TF.get(timeframe, _TRAIL_ATR_MULT_DEFAULT)
    exit_label = f"TRAIL_STOP_{int(mult)}ATR"

    warning_log: list[dict] = []

    atr_val       = _compute_atr14(df, entry_bar)
    initial_stop  = entry_price - mult * atr_val if atr_val > 0 else None
    trailing_stop = initial_stop
    highest_close = entry_price

    for j in range(entry_bar + 1, current_bar + 1):
        if j >= len(df):
            break

        bars_from_entry = j - entry_bar
        close = float(df["close"].iat[j])
        kj    = float(df["kj"].iat[j])

        # ── Tier 1 warnings ──────────────────────────────────────────────
        try:
            if df["tk"].iat[j] < df["kj"].iat[j] and df["tk"].iat[j - 1] >= df["kj"].iat[j - 1]:
                _append_warning(warning_log, bars_from_entry, 1, "BEARISH_TK_CROSS")
        except Exception:
            pass
        try:
            kj_dist = (close - kj) / kj * 100 if kj else 0
            if kj_dist > 20:
                _append_warning(warning_log, bars_from_entry, 1, "OVEREXTENDED_KJ")
        except Exception:
            pass

        # ── Tier 2 warnings ──────────────────────────────────────────────
        if close < kj:
            _append_warning(warning_log, bars_from_entry, 2, "PRICE_BELOW_KJ")
        try:
            if (not bool(df["_chikou_above_past_price"].iat[j])
                    and bool(df["_chikou_above_past_price"].iat[j - 1])):
                _append_warning(warning_log, bars_from_entry, 2, "CHIKOU_CROSSED_BELOW_PAST_PRICE")
        except Exception:
            pass

        # ── Tier 3: ATR trailing stop ─────────────────────────────────────
        if initial_stop is not None:
            highest_close = max(highest_close, close)
            if bars_from_entry <= 10:
                active_stop = initial_stop
            else:
                new_trail     = highest_close - mult * atr_val
                trailing_stop = max(trailing_stop, new_trail)  # type: ignore[arg-type]
                active_stop   = trailing_stop

            if close < active_stop:
                mae, mfe, _ = _compute_excursions(df, entry_bar, j, entry_price)
                return _make_exit(
                    bars_from_entry, exit_label, close,
                    entry_price, warning_log, mae=mae, mfe=mfe,
                )

    return None


def _append_warning(log: list, bar: int, tier: int, condition: str) -> None:
    # Deduplicate: don't add same condition twice in a row
    if log and log[-1]["condition"] == condition:
        return
    log.append({"tier": tier, "condition": condition, "bar": bar})


def _compute_excursions(
    df: pd.DataFrame, entry_bar: int, end_bar: int, entry_price: float
) -> tuple:
    """Return (mae, mfe, duration_bars).

    MAE = (min_low  - entry_price) / entry_price * 100  — always ≤ 0
    MFE = (max_high - entry_price) / entry_price * 100  — always ≥ 0
    duration_bars = end_bar - entry_bar
    """
    duration = end_bar - entry_bar
    if entry_price <= 0 or end_bar <= entry_bar:
        return None, None, duration

    start = entry_bar + 1
    stop = min(end_bar + 1, len(df))
    if start >= stop:
        return None, None, duration

    lows  = df["low"].iloc[start:stop].values  if "low"  in df.columns else df["close"].iloc[start:stop].values
    highs = df["high"].iloc[start:stop].values if "high" in df.columns else df["close"].iloc[start:stop].values
    min_c = float(lows.min())
    max_c = float(highs.max())
    mae = round((min_c - entry_price) / entry_price * 100, 4)
    mfe = round((max_c - entry_price) / entry_price * 100, 4)
    return mae, mfe, duration


def _make_exit(
    bar: int, condition: str, exit_price: float, entry_price: float,
    warning_log: list,
    mae: Optional[float] = None,
    mfe: Optional[float] = None,
) -> dict:
    result = {
        "exit_tier": 3,
        "exit_condition": condition,
        "exit_bar": bar,
        "exit_price": exit_price,
        "exit_return": round((exit_price - entry_price) / entry_price * 100, 4) if entry_price else None,
        "exit_timestamp": datetime.now(timezone.utc).isoformat(),
        "status": "CLOSED",
        "warning_log": json.dumps(warning_log),
        "duration_bars": bar,
    }
    if mae is not None:
        result["mae"] = mae
    if mfe is not None:
        result["mfe"] = mfe
    return result


def _check_signal_specific_exit(
    df: pd.DataFrame, j: int, close: float, kj: float,
    cloud_top: float, cloud_bot: float,
    signal_type: int, metadata: dict,
) -> Optional[str]:
    """Return an exit condition name if the signal-specific exit fires, else None."""
    try:
        if signal_type in (2, 3):
            if close < kj:
                return "KJ_BREAK_RETEST_FAILED" if signal_type == 3 else "BREAKOUT_FAILED_BACK_TO_KJ"

        if signal_type == 4:
            # E2E: stop out if price drops back through cloud bottom
            if close < cloud_bot:
                return "E2E_EXIT_CLOUD_BELOW"
            # E2E: take profit at cloud top (edge-to-edge target)
            if close >= cloud_top:
                return "E2E_PROFIT_CLOUD_TOP"

        if signal_type == 7:
            # Use the level_price stored in metadata
            level_price = metadata.get("level_price") if isinstance(metadata, dict) else None
            if level_price is None:
                level_type = (metadata or {}).get("level_type", "")
                if level_type == "TK":
                    level_price = float(df["tk"].iat[j])
                elif level_type == "KJ":
                    level_price = float(df["kj"].iat[j])
                elif level_type == "CLOUD_TOP":
                    level_price = cloud_top
                elif level_type == "CLOUD_BOTTOM":
                    level_price = cloud_bot
            if level_price and close < level_price:
                return "LEVEL_RETEST_FAILED"

        if signal_type == 9:
            level_price = (metadata or {}).get("level_price")
            if level_price and close < level_price:
                return "CHIKOU_LEVEL_BREAK"

    except Exception:
        pass
    return None


def _find_bar_by_timestamp(df: pd.DataFrame, fired_at: str) -> Optional[int]:
    """Return the integer bar index matching the fired_at timestamp, or None."""
    try:
        ts = pd.Timestamp(fired_at)
        # Try exact match first
        matches = df.index.get_indexer([ts], method="nearest")
        if len(matches) > 0 and matches[0] >= 0:
            return int(matches[0])
    except Exception:
        pass
    return None


def _apply_updates(conn, signal_id: str, updates: dict) -> None:
    if not updates:
        return
    cols = ", ".join(f"{k} = %s" for k in updates)
    vals = list(updates.values()) + [signal_id]
    with conn.cursor() as cur:
        cur.execute(f"UPDATE signal_log SET {cols} WHERE signal_id = %s", vals)


# ── Job 1: Tracker ────────────────────────────────────────────────────────────

def run_tracker() -> dict:
    """Update every OPEN signal with forward returns and exit conditions.
    Also retroactively fills mae/mfe/duration_bars for CLOSED signals missing them.

    Returns summary dict with counts.
    """
    from ichi.data.fetcher import fetch_ohlcv
    from ichi.indicators.ichimoku import ichimoku
    from ichi.indicators.precompute import precompute

    conn = get_conn()
    with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
        cur.execute("SELECT * FROM signal_log WHERE status = 'OPEN'")
        open_signals = [dict(r) for r in cur.fetchall()]
        cur.execute(
            "SELECT * FROM signal_log WHERE status = 'CLOSED' AND mae IS NULL AND exit_bar IS NOT NULL"
        )
        retro_signals = [dict(r) for r in cur.fetchall()]
    conn.close()

    if not open_signals and not retro_signals:
        logger.info("Tracker: no signals to update")
        return {"updated": 0, "closed": 0, "errors": 0, "retro_filled": 0}

    updated = closed = errors = retro_filled = 0
    trail_profit_signals: list[dict] = []  # signals whose trail stop crossed into profit

    # Group by (symbol, timeframe) to avoid refetching same data multiple times
    by_sym_tf: dict[tuple, list[dict]] = {}
    for sig in open_signals:
        key = (sig["symbol"], sig["timeframe"])
        by_sym_tf.setdefault(key, []).append(sig)

    by_sym_tf_retro: dict[tuple, list[dict]] = {}
    for sig in retro_signals:
        key = (sig["symbol"], sig["timeframe"])
        by_sym_tf_retro.setdefault(key, []).append(sig)

    # Merge all unique sym/tf pairs so we only fetch once
    all_keys = set(by_sym_tf.keys()) | set(by_sym_tf_retro.keys())

    for (symbol, timeframe) in all_keys:
        try:
            pair = symbol.replace("USDT", "/USDT")
            df = fetch_ohlcv(pair, timeframe)
            df = ichimoku(df)
            df = precompute(df)
            current_bar = len(df) - 1
        except Exception as exc:
            logger.warning("tracker fetch failed %s %s: %s", symbol, timeframe, exc)
            sigs_count = len(by_sym_tf.get((symbol, timeframe), [])) + len(by_sym_tf_retro.get((symbol, timeframe), []))
            errors += sigs_count
            continue

        conn = get_conn()
        try:
            # ── OPEN signals ─────────────────────────────────────────────────
            for sig in by_sym_tf.get((symbol, timeframe), []):
                try:
                    entry_bar = _find_bar_by_timestamp(df, sig["fired_at"])
                    if entry_bar is None:
                        continue

                    bars_elapsed = current_bar - entry_bar
                    entry_price = float(sig["entry_price"])
                    current_price = float(df["close"].iat[current_bar])
                    meta = json.loads(sig["signal_metadata"] or "{}")

                    updates: dict = {"updated_at": datetime.now(timezone.utc).isoformat()}

                    # Running MAE/MFE/duration for still-open instance
                    run_mae, run_mfe, run_dur = _compute_excursions(df, entry_bar, current_bar, entry_price)
                    if run_mae is not None:
                        updates["mae"] = run_mae
                        updates["mfe"] = run_mfe
                    updates["duration_bars"] = run_dur

                    # Check if trailing stop has crossed above entry (free trade)
                    # Skip ntfy push for backfill signals
                    atr_val = _compute_atr14(df, entry_bar)
                    if atr_val > 0 and current_bar > entry_bar + 10 and not sig.get("is_backfill"):
                        peak = float(df["close"].iloc[entry_bar + 1: current_bar + 1].max())
                        tf_mult = _TRAIL_ATR_MULT_BY_TF.get(timeframe, _TRAIL_ATR_MULT_DEFAULT)
                        trail_now = peak - tf_mult * atr_val
                        if trail_now > entry_price:
                            trail_profit_signals.append({
                                "signal_id":  sig["signal_id"],
                                "symbol":     sig["symbol"],
                                "timeframe":  timeframe,
                                "signal_type": sig["signal_type"],
                                "entry_price": entry_price,
                                "trail_stop":  round(trail_now, 6),
                            })

                    # Fixed-horizon returns
                    if bars_elapsed >= 7 and sig["return_7d"] is None:
                        bar7 = min(entry_bar + 7, current_bar)
                        p7 = float(df["close"].iat[bar7])
                        updates["return_7d"] = round((p7 - entry_price) / entry_price * 100, 4)

                    if bars_elapsed >= 30 and sig["return_30d"] is None:
                        bar30 = min(entry_bar + 30, current_bar)
                        p30 = float(df["close"].iat[bar30])
                        updates["return_30d"] = round((p30 - entry_price) / entry_price * 100, 4)

                    # Exit condition check
                    exit_result = check_exit_conditions(
                        df, entry_bar, current_bar,
                        entry_price, sig["signal_type"], meta,
                        timeframe=timeframe,
                    )
                    zombie_bars = _ZOMBIE_TIMEOUT_BARS.get(timeframe, _DEFAULT_ZOMBIE_TIMEOUT)
                    if exit_result:
                        updates.update(exit_result)
                        closed += 1
                    elif bars_elapsed >= zombie_bars:
                        fin_mae, fin_mfe, fin_dur = _compute_excursions(df, entry_bar, current_bar, entry_price)
                        updates["status"] = "CLOSED"
                        updates["exit_tier"] = 3
                        updates["exit_condition"] = "TIMEOUT"
                        updates["exit_bar"] = bars_elapsed
                        updates["exit_price"] = current_price
                        updates["exit_return"] = round(
                            (current_price - entry_price) / entry_price * 100, 4
                        )
                        updates["exit_timestamp"] = datetime.now(timezone.utc).isoformat()
                        updates["warning_log"] = sig.get("warning_log") or "[]"
                        updates["duration_bars"] = fin_dur
                        if fin_mae is not None:
                            updates["mae"] = fin_mae
                            updates["mfe"] = fin_mfe
                        closed += 1

                    _apply_updates(conn, sig["signal_id"], updates)
                    updated += 1

                except Exception as exc:
                    logger.debug("tracker update failed %s: %s", sig.get("signal_id"), exc)
                    errors += 1

            # ── Retroactive MAE/MFE fill for CLOSED signals ──────────────────
            for sig in by_sym_tf_retro.get((symbol, timeframe), []):
                try:
                    entry_bar = _find_bar_by_timestamp(df, sig["fired_at"])
                    if entry_bar is None:
                        continue
                    abs_exit_bar = entry_bar + int(sig["exit_bar"])
                    mae, mfe, dur = _compute_excursions(df, entry_bar, abs_exit_bar, float(sig["entry_price"]))
                    if mae is not None:
                        _apply_updates(conn, sig["signal_id"], {
                            "mae": mae, "mfe": mfe, "duration_bars": dur,
                            "updated_at": datetime.now(timezone.utc).isoformat(),
                        })
                        retro_filled += 1
                except Exception as exc:
                    logger.debug("retro fill failed %s: %s", sig.get("signal_id"), exc)
                    errors += 1

            conn.commit()
        finally:
            conn.close()

    logger.info(
        "Tracker: updated=%d closed=%d retro_filled=%d errors=%d",
        updated, closed, retro_filled, errors,
    )
    # Push trail-profit notifications (non-fatal)
    if trail_profit_signals:
        try:
            from ichi.notifier import push_trail_profit
            push_trail_profit(trail_profit_signals)
        except Exception as exc:
            logger.warning("trail profit notify failed: %s", exc)

    return {"updated": updated, "closed": closed, "errors": errors, "retro_filled": retro_filled}


# ── Job 2: Backfill ───────────────────────────────────────────────────────────

def _log_signals_batch(signals: list) -> int:
    """Insert a list of signal dicts in a single transaction. Returns inserted count."""
    if not signals:
        return 0
    now = datetime.now(timezone.utc).isoformat()
    conn = get_conn()
    inserted = 0
    try:
        with conn.cursor() as cur:
            for sig in signals:
                cur.execute(
                    """INSERT INTO signal_log
                       (signal_id, signal_type, signal_subtype, symbol, timeframe,
                        fired_at, entry_price, bull_score, quality_score, cloud_state, signal_metadata,
                        hosoda_active, hosoda_number, hosoda_pivot_type,
                        is_backfill, logged_at, updated_at, status,
                        tier, btc_regime, chikou_ok, cloud_thickness_pct)
                       VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)
                       ON CONFLICT (signal_id) DO NOTHING""",
                    (
                        sig["signal_id"], sig["signal_type"], sig.get("signal_subtype"),
                        sig["symbol"], sig["timeframe"], sig["fired_at"], sig["entry_price"],
                        sig.get("bull_score"), sig.get("quality_score"), sig.get("cloud_state"),
                        json.dumps(sig.get("signal_metadata", {})),
                        int(sig.get("hosoda_active", False)), sig.get("hosoda_number"),
                        sig.get("hosoda_pivot_type"), int(sig.get("is_backfill", False)),
                        now, now, "OPEN",
                        sig.get("tier"), sig.get("btc_regime"),
                        int(sig.get("chikou_ok", 0)), sig.get("cloud_thickness_pct"),
                    ),
                )
                inserted += cur.rowcount
        conn.commit()
    finally:
        conn.close()
    return inserted


def _btc_regime_at_bar(btc_df, bar_i: int) -> str:
    """Return BTC cloud regime ('above'/'inside'/'below') at a specific historical bar."""
    try:
        row   = btc_df.iloc[bar_i]
        close = float(row["close"])
        top   = float(max(row["span_a"], row["span_b"]))
        bot   = float(min(row["span_a"], row["span_b"]))
        if close > top:
            return "above"
        elif close < bot:
            return "below"
        else:
            return "inside"
    except Exception:
        return "unknown"


def _btc_rvol_at_bar(btc_df, bar_i: int) -> float | None:
    """Return BTC 20-bar annualized realized vol at a specific historical bar.

    Reads pre-computed 'rvol_20' column added to btc_1d at load time.
    Returns None if unavailable (treated as vol_ok=True to avoid false suppression).
    """
    try:
        import math
        val = float(btc_df["rvol_20"].iat[bar_i])
        return None if math.isnan(val) else val
    except Exception:
        return None


def _backfill_one_pair(pair: str, timeframes: list, registry, btc_1d=None, since_dt=None) -> tuple:
    """Worker: process one pair across all timeframes.

    Returns (symbol, signals_list, chikou_caches_list, error_count).
    No DB writes happen here — caller batch-inserts on the main thread.
    btc_1d:   pre-fetched+ichimoku BTC/USDT 1d DataFrame (passed from main process).
    since_dt: datetime — only process bars on/after this date (faster partial backfill).
    """
    from ichi.data.fetcher import fetch_ohlcv
    from ichi.indicators.ichimoku import ichimoku
    from ichi.indicators.precompute import precompute
    from ichi.scoring.engine import evaluate
    from ichi.signal.filters import classify_signal
    from ichi.signal.levels import update_chikou_levels_to_bar

    symbol = pair.replace("/USDT", "USDT").replace("/", "")
    all_signals: list = []
    chikou_caches: list = []
    errors = 0

    for tf in timeframes:
        try:
            # cache_only=True — backfill reads local parquet, no API calls in workers
            df = fetch_ohlcv(pair, tf, cache_only=True)
            df = ichimoku(df)
            df = precompute(df)
            if len(df) < 52:
                continue

            # Build a timestamp → bar-index map for BTC 1d alignment
            btc_ts_index: dict = {}
            if btc_1d is not None:
                for idx, ts in enumerate(btc_1d.index):
                    btc_ts_index[str(ts)[:10]] = idx  # key = "YYYY-MM-DD"

            chikou_cache: list = []
            # sig_type → (entry_bar, close_bar_or_None, sig_idx_in_all_signals)
            active: dict = {}
            last_fire: dict = {}   # sig_type -> bar of last fire (time-cooldown types)

            # Determine start bar from --since date (still need 52 warmup bars before it)
            if since_dt is not None:
                import numpy as np
                since_aware = since_dt.replace(tzinfo=__import__('datetime').timezone.utc) if since_dt.tzinfo is None else since_dt
                start_bar = max(52, next((i for i, t in enumerate(df.index) if t >= since_aware), 52))
            else:
                start_bar = 52

            for i in range(start_bar, len(df)):
                # ── Onset blocked set + exit tracking ─────────────────────
                blocked: set = set()
                # Time-cooldown types (mean-reversion) block only within the
                # cooldown window, independent of open-position state.
                for _t, _cd in _ONSET_TIME_COOLDOWN.items():
                    if i - last_fire.get(_t, -10**9) < _cd:
                        blocked.add(_t)
                for sig_type, (entry_bar, close_bar, sig_idx) in list(active.items()):
                    if close_bar is None:
                        zombie_bars = _ZOMBIE_TIMEOUT_BARS.get(tf, _DEFAULT_ZOMBIE_TIMEOUT)
                        if i - entry_bar >= zombie_bars:
                            # Timeout — close the signal dict in-place
                            active[sig_type] = (entry_bar, i, sig_idx)
                            blocked.add(sig_type)
                            if sig_idx is not None:
                                s = all_signals[sig_idx]
                                if s.get("status") != "CLOSED":
                                    ep = float(s.get("entry_price") or 0)
                                    xp = float(df["close"].iat[i])
                                    s["status"]         = "CLOSED"
                                    s["exit_condition"] = "TIMEOUT"
                                    s["exit_tier"]      = 3
                                    s["exit_bar"]       = i - entry_bar
                                    s["exit_price"]     = xp
                                    s["exit_return"]    = round((xp - ep) / ep * 100, 4) if ep else None
                        else:
                            blocked.add(sig_type)
                    else:
                        if i - close_bar < 3:
                            blocked.add(sig_type)

                # Bull score — pass full df + explicit i (no slice)
                sc = evaluate(df, i, registry)
                bull = sc.bull_score
                fired_rules = {r.rule_id for r in sc.rules if r.qualifies_bull}

                # Chikou levels — pass full df + explicit i (no slice)
                update_chikou_levels_to_bar(df, i, symbol, tf, chikou_cache)

                # Signal detection — pass full df + explicit bar index (no slice or copy)
                sigs = detect_all_signals(
                    df, symbol, tf, bull,
                    is_backfill=True, _blocked_types=blocked, _bar_i=i,
                )
                for sig in sigs:
                    from ichi.scoring.quality import compute_quality_score
                    qs = compute_quality_score(sig["signal_type"], tf, fired_rules)
                    sig["quality_score"] = qs

                    # ── Historical BTC regime + vol at this bar ───────────
                    try:
                        bar_date = str(df.index[i])[:10]
                        btc_bar  = btc_ts_index.get(bar_date, -1)
                        if btc_bar >= 0:
                            hist_btc_regime = _btc_regime_at_bar(btc_1d, btc_bar)
                            hist_btc_rvol   = _btc_rvol_at_bar(btc_1d, btc_bar)
                        else:
                            hist_btc_regime = "unknown"
                            hist_btc_rvol   = None
                    except Exception:
                        hist_btc_regime = "unknown"
                        hist_btc_rvol   = None

                    # ── Classify signal (tier, chikou_ok, cloud_thickness) ─
                    try:
                        filt = classify_signal(
                            signal_type=sig["signal_type"],
                            symbol=symbol,
                            timeframe=tf,
                            quality_score=qs,
                            hosoda_active=bool(sig.get("hosoda_active")),
                            df=df,
                            bar_i=i,
                            btc_regime=hist_btc_regime,
                            eth_regime="unknown",   # not pre-fetched for backfill speed
                            btc_rvol=hist_btc_rvol,
                            bull_score=bull,
                        )
                        sig["tier"]               = filt.get("tier")
                        sig["btc_regime"]         = hist_btc_regime
                        sig["chikou_ok"]          = int(filt.get("chikou_ok", False))
                        sig["cloud_thickness_pct"] = filt.get("cloud_thickness")
                    except Exception:
                        sig["tier"]               = None
                        sig["btc_regime"]         = hist_btc_regime
                        sig["chikou_ok"]          = 0
                        sig["cloud_thickness_pct"] = None

                    all_signals.append(sig)
                    if sig["signal_type"] in _ONSET_TIME_COOLDOWN:
                        last_fire[sig["signal_type"]] = i   # exit filled by run_tracker
                    else:
                        active[sig["signal_type"]] = (i, None, len(all_signals) - 1)

            if chikou_cache:
                chikou_caches.append(chikou_cache)

        except Exception as exc:
            logger.debug("backfill %s %s: %s", symbol, tf, exc)
            errors += 1

    return symbol, all_signals, chikou_caches, errors


def clear_backfill() -> int:
    """Delete all backfill signal instances and their co-occurrences.

    Returns the number of signal rows deleted.
    """
    conn = get_conn()
    try:
        with conn.cursor() as cur:
            cur.execute(
                """DELETE FROM cooccurrence_log
                   WHERE signal_id_a IN (SELECT signal_id FROM signal_log WHERE is_backfill = 1)
                      OR signal_id_b IN (SELECT signal_id FROM signal_log WHERE is_backfill = 1)"""
            )
            cur.execute("DELETE FROM signal_log WHERE is_backfill = 1")
            n = cur.rowcount
        conn.commit()
        print(f"Cleared {n} backfill signals.")
        return n
    finally:
        conn.close()


def _backfill_worker(args: tuple) -> tuple:
    """Top-level picklable wrapper for ProcessPoolExecutor."""
    pair, timeframes, btc_1d, since_dt = args
    # Each process builds its own registry (not picklable across processes)
    from ichi.calibration.params import apply_params, load_params
    from ichi.rules.registry import RuleRegistry
    params = load_params(None)
    apply_params(params)
    registry = RuleRegistry.canonical()
    return _backfill_one_pair(pair, timeframes, registry, btc_1d=btc_1d, since_dt=since_dt)


def run_backfill(
    top_n: int = 200,
    timeframes: list[str] | None = None,
    verbose: bool = True,
    workers: int = 8,
    since: str | None = None,
) -> dict:
    """Scan full OHLCV history for all universe symbols, log all historical signals.

    Speed optimisations:
      • ProcessPoolExecutor — true parallelism, bypasses Python GIL for CPU-bound work.
      • No df.copy() in the inner loop — detectors receive the full df + explicit bar index.
      • Batch DB inserts — one transaction per symbol instead of one per signal.

    Onset-detection: only the FIRST bar of each new setup episode is logged
    (60-bar active window + 3-bar cooldown after close/timeout).

    No lookahead bias: at bar i, detectors and scoring only read data up to bar i.
    """
    from concurrent.futures import ProcessPoolExecutor, as_completed

    from ichi.data.universe import top_n_by_marketcap
    from ichi.signal.levels import save_chikou_levels

    if timeframes is None:
        timeframes = ["1d", "4h", "1w"]

    init_db()
    universe = top_n_by_marketcap(top_n)
    n = len(universe)

    total_logged = 0
    total_errors = 0
    done = 0

    # Parse --since date (limits how far back we scan — much faster partial backfills)
    since_dt = None
    if since:
        from datetime import datetime
        since_dt = datetime.strptime(since, "%Y-%m-%d")
        if verbose:
            print(f"Backfill since {since} — skipping bars before this date")

    # Pre-fetch BTC 1d ONCE in main process using cache_only — no API call, no rate limiting
    btc_1d = None
    try:
        import numpy as _np
        from ichi.data.fetcher import fetch_ohlcv
        from ichi.indicators.ichimoku import ichimoku
        btc_raw = fetch_ohlcv("BTC/USDT", "1d", cache_only=True)
        btc_1d  = ichimoku(btc_raw)
        # Pre-compute 20-bar annualized realized vol for BTC vol regime filter
        _log_ret = _np.log(btc_1d["close"] / btc_1d["close"].shift(1))
        btc_1d["rvol_20"] = _log_ret.rolling(20).std() * _np.sqrt(365)
        if verbose:
            print(f"BTC/USDT 1d loaded from cache ({len(btc_1d)} bars)")
    except Exception as e:
        if verbose:
            print(f"BTC/USDT cache load failed — btc_regime will be 'unknown': {e}")

    n_workers = min(workers, n)
    work_args = [(pair, timeframes, btc_1d, since_dt) for pair in universe]

    with ProcessPoolExecutor(max_workers=n_workers) as pool:
        futs = {
            pool.submit(_backfill_worker, args): args[0]
            for args in work_args
        }
        for fut in as_completed(futs):
            done += 1
            pair = futs[fut]
            try:
                symbol, signals, chikou_caches, errs = fut.result()
                total_errors += errs

                # Batch-insert all signals for this symbol (main-thread write)
                inserted = _log_signals_batch(signals)
                total_logged += inserted

                # Save chikou levels sequentially (main-thread write)
                for cache in chikou_caches:
                    save_chikou_levels(cache)

                if verbose:
                    print(f"[{done}/{n}] {symbol}  → {inserted} signals", flush=True)

            except Exception as exc:
                total_errors += 1
                symbol = pair.replace("/USDT", "USDT").replace("/", "")
                if verbose:
                    print(f"[{done}/{n}] {symbol}  ERROR: {exc}", flush=True)

    if verbose:
        print(f"\nBackfill complete. Total signals logged: {total_logged}  Errors: {total_errors}")

    # After backfill, run tracker to compute returns on closed instances
    if verbose:
        print("Running tracker pass to compute forward returns...")
    run_tracker()

    return {"total_logged": total_logged, "errors": total_errors}


# ── Job 3: Signal IC ──────────────────────────────────────────────────────────

_TF_SORT = {"1w": 0, "1d": 1, "4h": 2}


def _row_sector(symbol: str) -> str:
    """Map a signal_log symbol (e.g. 'BTCUSDT') to its sector."""
    from ichi.data.sectors import get_sector
    base = symbol[:-4] if symbol.endswith("USDT") else symbol
    return get_sector(base)


def run_signal_ic(
    verbose: bool = True,
    group_by: Optional[str] = None,
    signal_filter: Optional[int] = None,
    tf_filter: Optional[str] = None,
) -> list[dict]:
    """Compute performance statistics from signal_log.

    group_by=None    — one row per (signal_type, timeframe)  [default]
    group_by='sector'— one row per (signal_type, timeframe, sector)

    signal_filter and tf_filter narrow which rows are included.
    """
    conn = get_conn()
    with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
        cur.execute("SELECT * FROM signal_log")
        all_rows = [dict(r) for r in cur.fetchall()]
    conn.close()

    # Apply optional filters
    if signal_filter is not None:
        all_rows = [r for r in all_rows if r["signal_type"] == signal_filter]
    if tf_filter is not None:
        all_rows = [r for r in all_rows if r["timeframe"] == tf_filter]

    # Attach sector when needed
    if group_by == "sector":
        for r in all_rows:
            r["_sector"] = _row_sector(r["symbol"])

    signal_names = {
        1: "Sanyaku", 2: "Balanced Breakout", 3: "KJ Break Retest",
        4: "E2E Entry", 5: "Twist Breakout", 6: "Cloud Curling",
        7: "Four-Level Retest", 9: "Chikou S/R Retest",
    }

    if group_by == "sector":
        raw_combos = {(r["signal_type"], r["timeframe"], r["_sector"]) for r in all_rows}
        combos = sorted(raw_combos, key=lambda x: (x[0], _TF_SORT.get(x[1], 99), x[2]))
    else:
        raw_combos = {(r["signal_type"], r["timeframe"]) for r in all_rows}
        combos = sorted(raw_combos, key=lambda x: (x[0], _TF_SORT.get(x[1], 99)))

    results = []
    for combo in combos:
        if group_by == "sector":
            sig_type, tf, sector = combo
            subset = [r for r in all_rows
                      if r["signal_type"] == sig_type
                      and r["timeframe"] == tf
                      and r["_sector"] == sector]
        else:
            sig_type, tf = combo
            sector = None
            subset = [r for r in all_rows if r["signal_type"] == sig_type and r["timeframe"] == tf]

        closed  = [r for r in subset if r["status"] == "CLOSED"]

        returns_30d = [r["return_30d"] for r in subset if r["return_30d"] is not None]
        exit_rets   = [r["exit_return"] for r in closed if r["exit_return"] is not None]
        exit_bars   = [r["exit_bar"] for r in closed if r["exit_bar"] is not None]
        hosoda_yes  = [r["return_30d"] for r in subset if r["hosoda_active"] and r["return_30d"] is not None]
        hosoda_no   = [r["return_30d"] for r in subset if not r["hosoda_active"] and r["return_30d"] is not None]

        # MAE / MFE / duration from closed instances that have data
        mae_vals  = [r["mae"]  for r in closed if r.get("mae")  is not None]
        mfe_vals  = [r["mfe"]  for r in closed if r.get("mfe")  is not None]
        dur_vals  = [r["duration_bars"] for r in closed if r.get("duration_bars") is not None]

        scores  = [r["bull_score"] for r in subset if r["bull_score"] is not None and r["return_30d"] is not None]
        returns = [r["return_30d"] for r in subset if r["bull_score"] is not None and r["return_30d"] is not None]
        ic_30d = _spearman(scores, returns)

        n = len(subset)
        mean_r30 = _mean(returns_30d)
        win_rate = sum(1 for r in exit_rets if r > 0) / len(exit_rets) if exit_rets else None

        # W/L ratio: mean winner / abs(mean loser)
        winners = [r for r in exit_rets if r > 0]
        losers  = [r for r in exit_rets if r < 0]
        mean_win  = _mean(winners)
        mean_loss = _mean(losers)
        win_loss_ratio = (
            round(abs(mean_win / mean_loss), 2)
            if (mean_win is not None and mean_loss is not None and mean_loss != 0)
            else None
        )

        p75_mae = _percentile(mae_vals, 75)   # 75th pct = larger drawdown end
        lev_safe_est = (
            round(0.5 / abs(p75_mae / 100), 1)
            if (p75_mae is not None and p75_mae < 0)
            else None
        )

        wr  = win_rate or 0
        wlr = win_loss_ratio or 0

        if n < 20:
            grade = "INSUFFICIENT DATA"
        elif mean_r30 and mean_r30 > 5 and (
            wr > 0.60
            or (wr > 0.45 and wlr > 1.5)
            or (wr > 0.33 and wlr > 3.5)
        ):
            grade = "STRONG"
        elif mean_r30 and mean_r30 > 2 and (
            wr > 0.50
            or (wr > 0.40 and wlr > 1.3)
            or (wr > 0.28 and wlr > 2.5)
        ):
            grade = "MODERATE"
        else:
            grade = "WEAK"

        row = {
            "signal_type": sig_type,
            "timeframe": tf,
            "sector": sector,
            "signal_name": signal_names.get(sig_type, f"Signal {sig_type}"),
            "n_instances": n,
            "n_closed": len(closed),
            "ic_30d": round(ic_30d, 4) if ic_30d is not None else None,
            "mean_return_30d": round(mean_r30, 2) if mean_r30 is not None else None,
            "mean_exit_return": round(_mean(exit_rets), 2) if exit_rets else None,
            "win_rate": round(win_rate, 3) if win_rate is not None else None,
            "mean_exit_bars": round(_mean(exit_bars), 1) if exit_bars else None,
            "hosoda_yes_mean_30d": round(_mean(hosoda_yes), 2) if hosoda_yes else None,
            "hosoda_no_mean_30d": round(_mean(hosoda_no), 2) if hosoda_no else None,
            "mean_mae": round(_mean(mae_vals), 2) if mae_vals else None,
            "p75_mae": round(p75_mae, 2) if p75_mae is not None else None,
            "mean_mfe": round(_mean(mfe_vals), 2) if mfe_vals else None,
            "mean_duration": round(_mean(dur_vals), 1) if dur_vals else None,
            "p75_duration": round(_percentile(dur_vals, 75), 0) if dur_vals else None,
            "win_loss_ratio": win_loss_ratio,
            "lev_safe_est": lev_safe_est,
            "grade": grade,
        }
        results.append(row)

    if verbose:
        _print_ic_table(results)

    return results


def _mean(xs: list) -> Optional[float]:
    return sum(xs) / len(xs) if xs else None


def _percentile(xs: list, p: float) -> Optional[float]:
    """Return the p-th percentile (0–100) of xs using linear interpolation."""
    if not xs:
        return None
    s = sorted(xs)
    idx = (len(s) - 1) * p / 100
    lo, hi = int(idx), min(int(idx) + 1, len(s) - 1)
    frac = idx - lo
    return s[lo] + (s[hi] - s[lo]) * frac


def _spearman(x: list, y: list) -> Optional[float]:
    """Spearman rank correlation between two equal-length lists."""
    if len(x) < 5:
        return None
    try:
        import scipy.stats as stats
        r, _ = stats.spearmanr(x, y)
        return float(r) if r == r else None  # NaN check
    except ImportError:
        # Fallback: manual rank correlation
        def _rank(lst):
            sorted_lst = sorted(range(len(lst)), key=lambda i: lst[i])
            ranks = [0] * len(lst)
            for rank, idx in enumerate(sorted_lst):
                ranks[idx] = rank + 1
            return ranks
        rx, ry = _rank(x), _rank(y)
        n = len(x)
        d2 = sum((a - b) ** 2 for a, b in zip(rx, ry))
        return 1 - (6 * d2) / (n * (n * n - 1)) if n > 1 else None


def _print_ic_table(results: list[dict]) -> None:
    show_sector = any(r.get("sector") is not None for r in results)
    if show_sector:
        header = (
            f"{'Sig':<4} {'TF':<4} {'Sector':<14} {'N':>5} {'Cls':>5} {'IC30d':>6} "
            f"{'Ret30d':>7} {'WR':>6} {'W/L':>5} "
            f"{'MAE':>7} {'P75MAE':>7} {'MFE':>7} {'AvgBars':>7} {'Lev':>4}  Grade"
        )
    else:
        header = (
            f"{'Sig':<4} {'TF':<4} {'Name':<22} {'N':>5} {'Cls':>5} {'IC30d':>6} "
            f"{'Ret30d':>7} {'WR':>6} {'W/L':>5} "
            f"{'MAE':>7} {'P75MAE':>7} {'MFE':>7} {'AvgBars':>7} {'Lev':>4}  Grade"
        )
    print("\n=== Signal IC Results ===")
    print(header)
    print("-" * len(header))
    for r in results:
        ic    = f"{r['ic_30d']:+.3f}"       if r["ic_30d"]           is not None else "  n/a "
        ret   = f"{r['mean_return_30d']:+.1f}%" if r["mean_return_30d"] is not None else "  n/a "
        wr    = f"{r['win_rate']:.1%}"       if r["win_rate"]         is not None else "  n/a"
        wl    = f"{r['win_loss_ratio']:.2f}" if r["win_loss_ratio"]   is not None else " n/a"
        mae   = f"{r['mean_mae']:+.1f}%"     if r["mean_mae"]         is not None else "  n/a "
        p75m  = f"{r['p75_mae']:+.1f}%"      if r["p75_mae"]          is not None else "  n/a "
        mfe   = f"{r['mean_mfe']:+.1f}%"     if r["mean_mfe"]         is not None else "  n/a "
        bars  = f"{r['mean_exit_bars']:.0f}" if r["mean_exit_bars"]   is not None else "  n/a"
        lev   = f"{r['lev_safe_est']:.1f}x"  if r["lev_safe_est"]     is not None else " n/a"
        tf    = r.get("timeframe", "")
        if show_sector:
            label = r.get("sector") or ""
            print(
                f"  {r['signal_type']:<3} {tf:<4} {label:<14} {r['n_instances']:>5} "
                f"{r['n_closed']:>5} {ic:>6} {ret:>7} {wr:>6} {wl:>5} "
                f"{mae:>7} {p75m:>7} {mfe:>7} {bars:>7} {lev:>4}  {r['grade']}"
            )
        else:
            print(
                f"  {r['signal_type']:<3} {tf:<4} {r['signal_name']:<22} {r['n_instances']:>5} "
                f"{r['n_closed']:>5} {ic:>6} {ret:>7} {wr:>6} {wl:>5} "
                f"{mae:>7} {p75m:>7} {mfe:>7} {bars:>7} {lev:>4}  {r['grade']}"
            )


# ── Job 4: Equity Simulation ──────────────────────────────────────────────────

_POSITION_SIZES = [1, 2, 5, 10, 15, 20]
_MIN_CLOSED_EQUITY = 30


def _simulate_equity(trades: list[dict], position_size: float) -> dict:
    """Run one equity simulation pass at a given position size (%).

    trades must be sorted chronologically and have 'exit_return' values.
    Returns dict with final_return, max_drawdown, max_dd_duration,
    max_consec_loss, ruined (capital dropped below 50%).
    """
    capital = 1.0
    peak = 1.0
    max_dd = 0.0
    cur_dd_dur = 0
    max_dd_dur = 0
    consec_loss = 0
    max_consec_loss = 0
    ruined = False

    for trade in trades:
        ret = float(trade["exit_return"])
        capital *= 1.0 + (position_size / 100.0) * (ret / 100.0)

        if capital < peak:
            dd = (peak - capital) / peak * 100.0
            if dd > max_dd:
                max_dd = dd
            cur_dd_dur += 1
            if cur_dd_dur > max_dd_dur:
                max_dd_dur = cur_dd_dur
        else:
            peak = capital
            cur_dd_dur = 0

        if ret < 0:
            consec_loss += 1
            if consec_loss > max_consec_loss:
                max_consec_loss = consec_loss
        else:
            consec_loss = 0

        if capital < 0.5:
            ruined = True

    return {
        "position_size": position_size,
        "final_return": round((capital - 1.0) * 100.0, 2),
        "max_drawdown": round(max_dd, 2),
        "max_dd_duration": max_dd_dur,
        "max_consec_loss": max_consec_loss,
        "ruined": ruined,
    }


def run_signal_equity(
    signal_filter: Optional[int] = None,
    tf_filter: Optional[str] = None,
    sector_filter: Optional[str] = None,
    verbose: bool = True,
) -> list[dict]:
    """Equity simulation for closed signal instances.

    For each (signal_type, timeframe) combo with ≥30 closed instances,
    simulates fixed-fraction trading at position sizes 1/2/5/10/15/20%.
    Computes final_return, max_drawdown, max_dd_duration, max_consec_loss,
    and the ruin_threshold (first PS where capital fell below 50%).

    sector_filter — if set (e.g. 'L1'), only includes symbols in that sector.
    """
    signal_names = {
        1: "Sanyaku", 2: "Balanced Breakout", 3: "KJ Break Retest",
        4: "E2E Entry", 5: "Twist Breakout", 6: "Cloud Curling",
        7: "Four-Level Retest", 9: "Chikou S/R Retest",
    }

    conn = get_conn()
    with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
        cur.execute(
            "SELECT * FROM signal_log WHERE status = 'CLOSED' AND exit_return IS NOT NULL"
        )
        rows = [dict(r) for r in cur.fetchall()]
    conn.close()

    # Apply filters
    if signal_filter is not None:
        rows = [r for r in rows if r["signal_type"] == signal_filter]
    if tf_filter is not None:
        rows = [r for r in rows if r["timeframe"] == tf_filter]
    if sector_filter is not None:
        rows = [r for r in rows if _row_sector(r["symbol"]) == sector_filter]

    # Group by (signal_type, timeframe)
    from collections import defaultdict
    groups: dict[tuple, list] = defaultdict(list)
    for r in rows:
        groups[(r["signal_type"], r["timeframe"])].append(r)

    combos = sorted(
        groups.keys(),
        key=lambda x: (x[0], _TF_SORT.get(x[1], 99)),
    )

    results = []
    for (sig_type, tf) in combos:
        trades = sorted(groups[(sig_type, tf)], key=lambda r: r["fired_at"])
        n_closed = len(trades)

        if n_closed < _MIN_CLOSED_EQUITY:
            continue

        sims = [_simulate_equity(trades, ps) for ps in _POSITION_SIZES]

        # Ruin threshold: first PS where capital dropped below 50%
        ruin_ps = next((s["position_size"] for s in sims if s["ruined"]), None)

        results.append({
            "signal_type": sig_type,
            "signal_name": signal_names.get(sig_type, f"Signal {sig_type}"),
            "timeframe": tf,
            "n_closed": n_closed,
            "simulations": sims,
            "ruin_threshold": ruin_ps,
        })

    if verbose:
        _print_equity_table(results)

    return results


def _print_equity_table(results: list[dict]) -> None:
    print("\n=== Equity Simulation Results ===")
    for combo in results:
        sig_type  = combo["signal_type"]
        tf        = combo["timeframe"]
        name      = combo["signal_name"]
        n_closed  = combo["n_closed"]
        sims      = combo["simulations"]
        ruin_ps   = combo["ruin_threshold"]

        header = (
            f"\n  Signal {sig_type} {tf}  —  {name}  ({n_closed} closed trades)\n"
            f"  {'Size':>5}  {'FinalRet':>9}  {'MaxDD':>7}  {'DD Dur':>6}  {'MaxLoss':>7}  {'Ruined':>6}"
        )
        print(header)
        print("  " + "-" * 50)
        for s in sims:
            ruined_str = "YES" if s["ruined"] else "no"
            print(
                f"  {s['position_size']:>4}%  "
                f"{s['final_return']:>+8.1f}%  "
                f"{-s['max_drawdown']:>+7.1f}%  "
                f"{s['max_dd_duration']:>6}  "
                f"{s['max_consec_loss']:>7}  "
                f"{ruined_str:>6}"
            )

        # Plain-English summary
        safe_ps = max((s["position_size"] for s in sims if not s["ruined"]), default=None)
        ref = next((s for s in sims if s["position_size"] == 5), sims[0])
        ruin_str = (
            f"Ruined above {ruin_ps}%."
            if ruin_ps
            else "Capital survived all tested sizes."
        )
        safe_str = f"Safe up to {safe_ps}%." if safe_ps else "No safe size found."
        print(
            f"\n  Summary: Signal {sig_type} {tf}: at 5% size "
            f"max drawdown {-ref['max_drawdown']:+.0f}%, "
            f"longest losing streak {ref['max_consec_loss']}. "
            f"{safe_str} {ruin_str}"
        )


# ── CLI entry point ───────────────────────────────────────────────────────────

if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    cmd = sys.argv[1] if len(sys.argv) > 1 else ""

    if cmd == "track":
        result = run_tracker()
        print(f"Tracker: {result}")

    elif cmd == "backfill":
        top = 200
        tfs = ["1d", "4h", "1w"]
        workers = 8
        since = None
        for arg in sys.argv[2:]:
            if arg.startswith("--top"):
                top = int(arg.split("=")[-1])
            elif arg.startswith("--timeframes"):
                tfs = arg.split("=")[-1].split(",")
            elif arg.startswith("--workers"):
                workers = int(arg.split("=")[-1])
            elif arg.startswith("--since"):
                since = arg.split("=")[-1]  # e.g. --since=2024-01-01
        run_backfill(top_n=top, timeframes=tfs, workers=workers, since=since)

    elif cmd == "signal-ic":
        group_by = None
        sig_f = None
        tf_f = None
        for arg in sys.argv[2:]:
            if arg.startswith("--group-by"):
                group_by = arg.split("=")[-1]
            elif arg.startswith("--signal"):
                sig_f = int(arg.split("=")[-1])
            elif arg.startswith("--tf"):
                tf_f = arg.split("=")[-1]
        run_signal_ic(group_by=group_by, signal_filter=sig_f, tf_filter=tf_f)

    elif cmd == "signal-equity":
        sig_f = None
        tf_f = None
        sector_f = None
        for arg in sys.argv[2:]:
            if arg.startswith("--signal"):
                sig_f = int(arg.split("=")[-1])
            elif arg.startswith("--tf"):
                tf_f = arg.split("=")[-1]
            elif arg.startswith("--sector"):
                sector_f = arg.split("=")[-1]
        run_signal_equity(signal_filter=sig_f, tf_filter=tf_f, sector_filter=sector_f)

    elif cmd == "clear-backfill":
        n = clear_backfill()
        print(f"Deleted {n} backfill signals.")

    else:
        print("Usage: python -m ichi.signal.jobs [track | backfill | signal-ic | signal-equity | clear-backfill]")
        print("  backfill options:      --top=N  --timeframes=1d,4h,1w  --workers=N  --since=YYYY-MM-DD")
        print("  signal-ic options:     --signal=N  --tf=1d|4h|1w  --group-by=sector")
        print("  signal-equity options: --signal=N  --tf=1d|4h|1w")
        sys.exit(1)
