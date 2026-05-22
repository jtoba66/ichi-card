"""Concurrent 3-timeframe scanner for the API layer."""
from __future__ import annotations

import logging
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timezone

from ichi.api.event_scanner import (
    get_balance_map,
    get_cloud_curling,
    get_e2e_opportunity,
    get_kumo_twist,
    get_retest_alerts,
    get_transition_events,
)
from ichi.calibration.params import apply_params, load_params
from ichi.cli.scan import _score_all
from ichi.scoring.engine import evaluate
from ichi.data.fetcher import fetch_ohlcv
from ichi.data.funding import fetch_funding_and_oi
from ichi.data.sectors import get_sector
from ichi.data.universe import get_exchange_for, top_n_by_marketcap
from ichi.indicators.ichimoku import ichimoku
from ichi.indicators.precompute import precompute
from ichi.rules.registry import RuleRegistry
from ichi.signal.detector import detect_all_signals, log_signal, check_cooccurrence, init_db
from ichi.signal.levels import build_chikou_levels, save_chikou_levels

logger = logging.getLogger(__name__)

TIMEFRAMES = ["1d", "4h", "1w"]
EVENT_TIMEFRAMES = ["1d", "4h"]


def run_full_scan(top: int = 200, workers: int = 8) -> list[dict]:
    """Scan top N symbols across 1d/4h/1w, merge into per-coin dicts, attach funding/OI."""
    params = load_params(None)
    apply_params(params)
    registry = RuleRegistry.canonical()

    symbols = top_n_by_marketcap(n=top)

    # Fetch BTC reference once (used by relative-strength)
    try:
        btc_df = fetch_ohlcv("BTC/USDT", "1d")
    except Exception:
        btc_df = None

    # Run 3 timeframe scans concurrently
    tf_results: dict[str, list[dict]] = {}
    with ThreadPoolExecutor(max_workers=3) as outer:
        futures = {
            outer.submit(_score_all, symbols, tf, registry, workers, btc_df): tf
            for tf in TIMEFRAMES
        }
        for fut in as_completed(futures):
            tf = futures[fut]
            try:
                tf_results[tf] = fut.result()
            except Exception as exc:
                logger.warning("scan %s failed: %s", tf, exc)
                tf_results[tf] = []

    # Index each TF by symbol
    by_sym: dict[str, dict] = {}
    for tf in TIMEFRAMES:
        for row in tf_results.get(tf, []):
            sym = row["symbol"]
            if sym not in by_sym:
                by_sym[sym] = {"symbol": sym, "sym_full": row["sym_full"]}
            by_sym[sym][tf] = row

    # Attach funding/OI and sector — use 1d data as canonical for common fields
    coins: list[dict] = []
    for sym, coin in by_sym.items():
        canonical = coin.get("1d") or coin.get("4h") or coin.get("1w") or {}
        sym_full = coin["sym_full"]
        exchange_id = get_exchange_for(sym_full) if sym_full else "binance"

        try:
            fi = fetch_funding_and_oi(sym_full, exchange_id)
        except Exception:
            fi = {"funding_rate": None, "oi_usd": None}

        coins.append({
            "symbol": sym,
            "sym_full": sym_full,
            "sector": get_sector(sym),
            "funding_rate": fi.get("funding_rate"),
            "oi_usd": fi.get("oi_usd"),
            # Per-timeframe score dicts
            "1d": coin.get("1d"),
            "4h": coin.get("4h"),
            "1w": coin.get("1w"),
            # Convenience: canonical (1d) values surfaced at top level
            "bull": canonical.get("bull", 0),
            "bear": canonical.get("bear", 0),
            "total": canonical.get("total", 18),
            "grade": canonical.get("grade", "F"),
            "chikou": canonical.get("chikou", 0.0),
            "adx": canonical.get("adx", 0.0),
            "cloud": canonical.get("cloud", "UNKNOWN"),
            "fwd_cloud": canonical.get("fwd_cloud", "UNKNOWN"),
            "flags": canonical.get("flags", []),
            "rs_label": canonical.get("rs_label", ""),
            "rs_score": canonical.get("rs_score", 0),
            "bullish_div": canonical.get("bullish_div", False),
            "bearish_div": canonical.get("bearish_div", False),
            "bb_squeeze": canonical.get("bb_squeeze", False),
            "vol_ratio": canonical.get("vol_ratio", 1.0),
        })

    return coins


def _scan_events_for(sym: str, timeframe: str, registry: RuleRegistry) -> dict:
    """Fetch + score one (symbol, timeframe) pair, run event detectors, and detect signals."""
    try:
        df = fetch_ohlcv(sym, timeframe)
        if df.empty or len(df) < 52:
            return {}
        df = ichimoku(df)
        precompute(df)
        i = len(df) - 1
        sc = evaluate(df, i, registry)
        bull_score = sc.bull_score

        results = {}
        ev = get_transition_events(df, sym, timeframe)
        if ev:
            results["transition"] = ev

        alerts = get_retest_alerts(df, sym, timeframe, bull_score)
        if alerts:
            results["retest"] = alerts

        bm = get_balance_map(df, sym, timeframe, bull_score)
        if bm:
            results["balance"] = bm

        kt = get_kumo_twist(df, sym, timeframe, bull_score)
        if kt:
            results["kumo_twist"] = kt

        e2e = get_e2e_opportunity(df, sym, timeframe, bull_score)
        if e2e:
            results["e2e"] = e2e

        cc = get_cloud_curling(df, sym, timeframe, bull_score)
        if cc:
            results["cloud_curling"] = cc

        # Refresh chikou levels then detect named signals
        try:
            sym_clean = sym.replace("/USDT", "USDT").replace("/", "")
            levels = build_chikou_levels(df, sym_clean, timeframe)
            save_chikou_levels(levels)
            signals = detect_all_signals(df, sym_clean, timeframe, bull_score)
            if signals:
                results["signals"] = signals
        except Exception as exc:
            logger.debug("signal detect %s %s failed: %s", sym, timeframe, exc)

        return results
    except Exception as exc:
        logger.debug("event scan %s %s failed: %s", sym, timeframe, exc)
        return {}


def run_event_scan(symbols: list[str] | None = None, workers: int = 8) -> dict:
    """Run event detection across symbols × EVENT_TIMEFRAMES. Returns 6 categorised lists.

    Also detects and logs named signals (1-7, 9) and checks for co-occurrences.
    """
    params = load_params(None)
    apply_params(params)
    registry = RuleRegistry.canonical()
    init_db()  # ensure DB tables exist (no-op if already created)

    if symbols is None:
        symbols = top_n_by_marketcap(n=200)

    pairs = [(sym, tf) for sym in symbols for tf in EVENT_TIMEFRAMES]

    transition_events: list[dict] = []
    retest_alerts: list[dict] = []
    balance_map: list[dict] = []
    kumo_twists: list[dict] = []
    e2e_opportunities: list[dict] = []
    cloud_curling: list[dict] = []
    new_signals: list[dict] = []

    with ThreadPoolExecutor(max_workers=workers) as pool:
        futures = {
            pool.submit(_scan_events_for, sym, tf, registry): (sym, tf)
            for sym, tf in pairs
        }
        for fut in as_completed(futures):
            res = fut.result()
            if not res:
                continue
            if "transition" in res:
                transition_events.append(res["transition"])
            if "retest" in res:
                retest_alerts.extend(res["retest"])
            if "balance" in res:
                balance_map.append(res["balance"])
            if "kumo_twist" in res:
                kumo_twists.append(res["kumo_twist"])
            if "e2e" in res:
                e2e_opportunities.append(res["e2e"])
            if "cloud_curling" in res:
                cloud_curling.append(res["cloud_curling"])
            if "signals" in res:
                new_signals.extend(res["signals"])

    # Log new signals — only keep truly-new ones (INSERT OR IGNORE returns rowcount=1)
    truly_new: list[dict] = []
    for sig in new_signals:
        try:
            inserted = log_signal(sig)
            if inserted:
                truly_new.append(sig)
                check_cooccurrence(
                    sig["signal_id"], sig["symbol"], sig["timeframe"], sig["fired_at"],
                    signal_type_exclude=sig["signal_type"],
                )
        except Exception as exc:
            logger.debug("signal log failed %s: %s", sig.get("signal_id"), exc)

    if truly_new:
        logger.info("Logged %d new signal instance(s) this scan", len(truly_new))

    return {
        "transition_events":  transition_events,
        "retest_alerts":      retest_alerts,
        "balance_map":        balance_map,
        "kumo_twists":        kumo_twists,
        "e2e_opportunities":  e2e_opportunities,
        "cloud_curling":      cloud_curling,
        "scanned_at":         datetime.now(timezone.utc).isoformat(),
        "new_signal_count":   len(truly_new),
        "new_signals_data":   truly_new,  # consumed by alerts.js to fire SIGNAL notifications
    }
