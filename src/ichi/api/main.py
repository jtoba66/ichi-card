"""FastAPI app — serves live scan data to the dashboard.

Endpoints:
    GET  /api/health   — liveness probe
    GET  /api/data     — return cached scan result (or loading/error status)
    POST /api/refresh  — trigger a new background scan

Run:
    cd ichi-scorecard
    uvicorn ichi.api.main:app --reload --port 8000
"""
from __future__ import annotations

import json
import logging
import threading
import time
from datetime import datetime, timezone
from pathlib import Path

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel

from ichi.api.history import attach_history, save_history
from ichi.api.scanner import run_event_scan, run_full_scan
from ichi.signal.detector import init_db as _init_signal_db
from ichi.notifier import push_events, push_new_signals, push_confluence, push_morning_brief

logger = logging.getLogger(__name__)

app = FastAPI(title="ichi-scorecard API", version="0.1.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["GET", "POST"],
    allow_headers=["*"],
)

# ── In-memory scan caches ─────────────────────────────────────────────────────

_SCAN_CACHE_PATH = Path(__file__).parent.parent.parent.parent / "data" / "scan_cache.json"

_state: dict = {
    "status": "idle",       # idle | scanning | ready | error
    "data": None,
    "scanned_at": None,
    "error": None,
}
_lock = threading.Lock()


def _load_scan_cache() -> None:
    """Pre-populate _state from disk so the dashboard is instant on restart."""
    try:
        if _SCAN_CACHE_PATH.exists():
            payload = json.loads(_SCAN_CACHE_PATH.read_text())
            with _lock:
                _state["data"] = payload["coins"]
                _state["scanned_at"] = payload["scanned_at"]
                _state["status"] = "scanning"  # mark stale; fresh scan is in progress
    except Exception as exc:
        logger.warning("Could not load scan cache: %s", exc)


def _save_scan_cache(coins: list, scanned_at: str) -> None:
    try:
        _SCAN_CACHE_PATH.parent.mkdir(parents=True, exist_ok=True)
        def _default(obj):
            if hasattr(obj, "__dict__"):
                return obj.__dict__
            return str(obj)
        _SCAN_CACHE_PATH.write_text(json.dumps({"coins": coins, "scanned_at": scanned_at}, default=_default))
    except Exception as exc:
        logger.warning("Could not save scan cache: %s", exc)

_EMPTY_EVENTS = {
    "transition_events":  [],
    "retest_alerts":      [],
    "balance_map":        [],
    "kumo_twists":        [],
    "e2e_opportunities":  [],
    "cloud_curling":      [],
    "new_signals_data":   [],
    "new_signal_count":   0,
    "developing_setups":  [],
    "scanned_at":         None,
}

# ── Signal cache helpers ───────────────────────────────────────────────────────

_TF_SECONDS = {"1h": 3600, "4h": 14400, "1d": 86400, "1w": 604800}
# How many bars a signal stays "fresh" (still a valid entry opportunity)
_TF_FRESHNESS_BARS = {"4h": 3, "1d": 2, "1w": 1}


def _bars_since_fired(fired_at_str, timeframe: str) -> int | None:
    """Compute how many bars have elapsed since a signal fired."""
    try:
        from dateutil.parser import parse as _parse
        fa = _parse(str(fired_at_str)) if isinstance(fired_at_str, str) else fired_at_str
        if fa.tzinfo is None:
            fa = fa.replace(tzinfo=timezone.utc)
        elapsed = (datetime.now(timezone.utc) - fa).total_seconds()
        tf_secs = _TF_SECONDS.get(timeframe, 86400)
        return max(0, int(elapsed / tf_secs))
    except Exception:
        return None


def _approx_trail_stop(row: dict) -> float | None:
    """Estimate trail stop price from ATR% stored in signal filter metadata."""
    try:
        meta = row.get("signal_metadata") or {}
        if isinstance(meta, str):
            meta = json.loads(meta or "{}")
        filt  = meta.get("filter") or {}
        atr_p = filt.get("atr_pct")
        entry = row.get("entry_price")
        tf    = row.get("timeframe", "4h")
        if atr_p and entry and atr_p > 0:
            from ichi.signal.jobs import _TRAIL_ATR_MULT_BY_TF, _TRAIL_ATR_MULT_DEFAULT
            mult = _TRAIL_ATR_MULT_BY_TF.get(tf, _TRAIL_ATR_MULT_DEFAULT)
            return round(float(entry) * (1 - (atr_p / 100) * mult), 6)
    except Exception:
        pass
    return None
_events_cache: dict = dict(_EMPTY_EVENTS)
_events_lock = threading.Lock()

# ── Signals cache (avoids hitting SQLite under backfill lock contention) ──────

_signals_cache: dict = {
    "recent": None, "open": None, "setups": None,
    "history": None, "performance": None, "refreshed_at": None,
}
_signals_lock = threading.Lock()
SIGNALS_REFRESH_INTERVAL_S = 5 * 60  # 5 minutes


def _build_signals_cache() -> None:
    """Query PostgreSQL and populate _signals_cache. Runs in a background thread."""
    import json
    import psycopg2.extras
    from ichi.signal.db import get_conn

    try:
        conn = get_conn()

        # Track filters — mirrors _classify_track in notifier.py
        # With WATCH: used for SETUPS and OPEN (show E2E signals to monitor)
        # No WATCH: used for HISTORY and PERFORMANCE (only trades you actually take)
        _TRACK_FILTER = """
            AND (
                (sl.timeframe = '1d' AND sl.tier IN (1,2) AND sl.btc_regime = 'above')
                OR (sl.timeframe = '1d' AND sl.chikou_ok = 1 AND sl.quality_score >= 60
                    AND sl.btc_regime IN ('below','inside'))
                OR (sl.timeframe = '4h' AND sl.tier = 1 AND sl.bull_score >= 16)
                OR (sl.signal_type = 4)
            )
        """
        _TRACK_FILTER_NO_WATCH = """
            AND (
                (sl.timeframe = '1d' AND sl.tier IN (1,2) AND sl.btc_regime = 'above')
                OR (sl.timeframe = '1d' AND sl.chikou_ok = 1 AND sl.quality_score >= 60
                    AND sl.btc_regime IN ('below','inside'))
                OR (sl.timeframe = '4h' AND sl.tier = 1 AND sl.bull_score >= 16)
            )
        """

        with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
            _COOC_CTE = """
                WITH cooc AS (
                    SELECT signal_id, COUNT(*) AS cnt FROM (
                        SELECT signal_id_a AS signal_id FROM cooccurrence_log
                        UNION ALL
                        SELECT signal_id_b AS signal_id FROM cooccurrence_log
                    ) sub GROUP BY signal_id
                )
            """
            cur.execute(
                _COOC_CTE + """
                SELECT sl.*, COALESCE(co.cnt, 0) AS cooccurrence_count
                FROM signal_log sl
                LEFT JOIN cooc co ON co.signal_id = sl.signal_id
                WHERE sl.fired_at::timestamptz >= NOW() - INTERVAL '14 days'
                """ + _TRACK_FILTER + """
                ORDER BY sl.fired_at::timestamptz DESC
                LIMIT 200
                """
            )
            recent_rows = [dict(r) for r in cur.fetchall()]

            cur.execute(
                _COOC_CTE + """
                SELECT sl.*, COALESCE(co.cnt, 0) AS cooccurrence_count,
                       EXTRACT(DAY FROM NOW() - sl.fired_at::timestamptz)::int AS days_open
                FROM signal_log sl
                LEFT JOIN cooc co ON co.signal_id = sl.signal_id
                WHERE sl.status = 'OPEN'
                  AND sl.is_backfill = 0
                """ + _TRACK_FILTER + """
                ORDER BY sl.fired_at::timestamptz ASC
                """
            )
            open_rows = [dict(r) for r in cur.fetchall()]

            cur.execute(
                _COOC_CTE + """
                SELECT sl.*, COALESCE(co.cnt, 0) AS cooccurrence_count
                FROM signal_log sl
                LEFT JOIN cooc co ON co.signal_id = sl.signal_id
                WHERE sl.status = 'CLOSED'
                """ + _TRACK_FILTER_NO_WATCH + """
                ORDER BY sl.exit_timestamp::timestamptz DESC NULLS LAST
                LIMIT 500
                """
            )
            history_rows = [dict(r) for r in cur.fetchall()]

            cur.execute("SELECT DISTINCT signal_type FROM signal_log ORDER BY signal_type")
            type_rows = cur.fetchall()

        signal_names = {
            1: "Sanyaku", 2: "Balanced Breakout", 3: "KJ Break Retest",
            4: "E2E Entry", 5: "Twist Breakout", 6: "Cloud Curling",
            7: "Four-Level Retest", 9: "Chikou S/R Retest",
        }

        def _m(xs):
            return sum(xs) / len(xs) if xs else None

        def _pct(xs, p):
            if not xs:
                return None
            s = sorted(xs)
            idx = (len(s) - 1) * p / 100
            lo, hi = int(idx), min(int(idx) + 1, len(s) - 1)
            return s[lo] + (s[hi] - s[lo]) * (idx - lo)

        _PERF_TRACK_FILTER = """
            AND (
                (timeframe = '1d' AND tier IN (1,2) AND btc_regime = 'above')
                OR (timeframe = '1d' AND chikou_ok = 1 AND quality_score >= 60
                    AND btc_regime IN ('below','inside'))
                OR (timeframe = '4h' AND tier = 1 AND bull_score >= 16)
            )
        """

        stats = []
        for row in type_rows:
            sig_type = row["signal_type"]
            if sig_type == 4:
                continue  # WATCH signals excluded from performance stats
            with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
                cur.execute(
                    "SELECT * FROM signal_log WHERE signal_type = %s" + _PERF_TRACK_FILTER,
                    (sig_type,)
                )
                subset = [dict(r) for r in cur.fetchall()]
            closed = [r for r in subset if r["status"] == "CLOSED"]
            n = len(subset)
            n_closed = len(closed)
            if n == 0:
                continue

            returns_30d = [r["return_30d"] for r in subset if r["return_30d"] is not None]
            exit_returns = [r["exit_return"] for r in closed if r["exit_return"] is not None]
            exit_bars = [r["exit_bar"] for r in closed if r["exit_bar"] is not None]
            hosoda_yes = [r["return_30d"] for r in subset
                          if r["hosoda_active"] and r["return_30d"] is not None]
            hosoda_no = [r["return_30d"] for r in subset
                         if not r["hosoda_active"] and r["return_30d"] is not None]
            mae_vals = [r["mae"] for r in closed if r.get("mae") is not None]
            mfe_vals = [r["mfe"] for r in closed if r.get("mfe") is not None]
            dur_vals = [r["duration_bars"] for r in closed if r.get("duration_bars") is not None]

            # QS 60+ filtered stats — best proxy for T1/T2 tier performance using DB columns
            closed_qs60 = [r for r in closed if (r.get("quality_score") or 0) >= 60]
            exit_returns_qs60 = [r["exit_return"] for r in closed_qs60 if r["exit_return"] is not None]
            win_rate_qs60 = (
                sum(1 for r in exit_returns_qs60 if r > 0) / len(exit_returns_qs60)
                if exit_returns_qs60 else None
            )
            winners_qs60 = [r for r in exit_returns_qs60 if r > 0]
            losers_qs60  = [r for r in exit_returns_qs60 if r < 0]
            wl_qs60 = (
                round(abs(_m(winners_qs60) / _m(losers_qs60)), 2)
                if (winners_qs60 and losers_qs60) else None
            )

            mean_r30 = _m(returns_30d)
            win_rate = sum(1 for r in exit_returns if r > 0) / len(exit_returns) if exit_returns else None
            mean_exit_bars = _m(exit_bars)
            hosoda_lift = (_m(hosoda_yes), _m(hosoda_no))

            winners = [r for r in exit_returns if r > 0]
            losers  = [r for r in exit_returns if r < 0]
            mean_win  = _m(winners)
            mean_loss = _m(losers)
            win_loss_ratio = (
                round(abs(mean_win / mean_loss), 2)
                if (mean_win and mean_loss)
                else None
            )

            p75_mae = _pct(mae_vals, 75)
            lev_safe_est = (
                round(0.5 / abs(p75_mae / 100), 1)
                if (p75_mae is not None and p75_mae < 0)
                else None
            )

            _wr  = win_rate or 0
            _wlr = win_loss_ratio or 0

            if n < 20:
                grade = "INSUFFICIENT DATA"
            elif mean_r30 and mean_r30 > 5 and (
                _wr > 0.60
                or (_wr > 0.45 and _wlr > 1.5)
                or (_wr > 0.33 and _wlr > 3.5)
            ):
                grade = "STRONG"
            elif mean_r30 and mean_r30 > 2 and (
                _wr > 0.50
                or (_wr > 0.40 and _wlr > 1.3)
                or (_wr > 0.28 and _wlr > 2.5)
            ):
                grade = "MODERATE"
            else:
                grade = "WEAK"

            stats.append({
                "signal_type": sig_type,
                "signal_name": signal_names.get(sig_type, f"Signal {sig_type}"),
                "n_instances": n,
                "n_closed": n_closed,
                "mean_return_30d": round(mean_r30, 2) if mean_r30 is not None else None,
                "win_rate": round(win_rate, 3) if win_rate is not None else None,
                "mean_exit_bars": round(mean_exit_bars, 1) if mean_exit_bars is not None else None,
                "hosoda_yes_mean_30d": round(hosoda_lift[0], 2) if hosoda_lift[0] is not None else None,
                "hosoda_no_mean_30d": round(hosoda_lift[1], 2) if hosoda_lift[1] is not None else None,
                "mean_mae": round(_m(mae_vals), 2) if mae_vals else None,
                "p75_mae": round(p75_mae, 2) if p75_mae is not None else None,
                "mean_mfe": round(_m(mfe_vals), 2) if mfe_vals else None,
                "mean_duration": round(_m(dur_vals), 1) if dur_vals else None,
                "p75_duration": round(_pct(dur_vals, 75), 0) if dur_vals else None,
                "win_loss_ratio": win_loss_ratio,
                "lev_safe_est": lev_safe_est,
                "grade": grade,
                # QS60+ filtered — T1/T2 tier proxy (quality_score is a DB column)
                "n_closed_qs60": len(closed_qs60),
                "win_rate_qs60": round(win_rate_qs60, 3) if win_rate_qs60 is not None else None,
                "mean_exit_return_qs60": round(_m(exit_returns_qs60), 2) if exit_returns_qs60 else None,
                "win_loss_ratio_qs60": wl_qs60,
            })

        conn.close()

        # Enrich rows with computed fields
        for r in recent_rows + open_rows:
            r["bars_since_fired"] = _bars_since_fired(r.get("fired_at"), r.get("timeframe", "4h"))

        for r in open_rows:
            r["trail_stop_approx"] = _approx_trail_stop(r)

        for r in history_rows:
            r["bars_since_fired"] = _bars_since_fired(r.get("fired_at"), r.get("timeframe", "4h"))

        # Setups = open signals still within the freshness entry window
        setups_rows = [
            r for r in open_rows
            if (r.get("bars_since_fired") or 999) <= _TF_FRESHNESS_BARS.get(r.get("timeframe", ""), 2)
        ]
        # Sort setups: CONFIRMED first, then 4H-QUALITY, RECOVERY, WATCH, rest
        _TRACK_ORDER = {"CONFIRMED": 0, "4H-QUALITY": 1, "RECOVERY": 2, "WATCH": 3}

        def _classify_track_py(r):
            tf         = r.get("timeframe", "")
            tier       = r.get("tier")
            btc_regime = r.get("btc_regime", "unknown")
            chikou_ok  = r.get("chikou_ok")
            qs         = float(r.get("quality_score") or 0)
            bull_score = int(r.get("bull_score") or 0)
            sig_type   = r.get("signal_type")
            if tf == "1d" and tier in (1, 2) and btc_regime == "above":
                return "CONFIRMED"
            if tf == "1d" and chikou_ok and qs >= 60 and btc_regime in ("below", "inside"):
                return "RECOVERY"
            if tf == "4h" and tier == 1 and bull_score >= 16:
                return "4H-QUALITY"
            if sig_type == 4:
                return "WATCH"
            return "OTHER"

        def _setup_sort_key(r):
            track = _classify_track_py(r)
            return (_TRACK_ORDER.get(track, 9), r.get("bars_since_fired") or 99)
        setups_rows.sort(key=_setup_sort_key)

        with _signals_lock:
            _signals_cache["recent"] = recent_rows
            _signals_cache["open"] = open_rows
            _signals_cache["setups"] = setups_rows
            _signals_cache["history"] = history_rows
            _signals_cache["performance"] = stats
            _signals_cache["refreshed_at"] = datetime.now(timezone.utc).isoformat()

    except Exception as exc:
        logger.exception("Signals cache refresh failed: %s", exc)


def _signals_loop() -> None:
    while True:
        _build_signals_cache()
        time.sleep(SIGNALS_REFRESH_INTERVAL_S)


def _do_scan() -> None:
    with _lock:
        _state["status"] = "scanning"
        _state["error"] = None

    try:
        coins = run_full_scan()
        save_history(coins)
        attach_history(coins)
        scanned_at = datetime.now(timezone.utc).isoformat()
        with _lock:
            _state["data"] = coins
            _state["status"] = "ready"
            _state["scanned_at"] = scanned_at
        _save_scan_cache(coins, scanned_at)
    except Exception as exc:
        logger.exception("Scan failed: %s", exc)
        with _lock:
            _state["status"] = "error"
            _state["error"] = str(exc)
        return

    # Run event scan after full scan completes (non-blocking — already in background thread)
    try:
        events = run_event_scan()
        with _events_lock:
            _events_cache.update(events)
        # Push new dashboard events + any new signals to ntfy in real time
        try:
            push_events(events)
            push_new_signals()
            push_confluence()
            # Morning brief fires once daily at 08:00–08:10 UTC
            hour = datetime.now(timezone.utc).hour
            if hour == 8:
                push_morning_brief()
        except Exception as notif_exc:
            logger.warning("ntfy push failed (non-fatal): %s", notif_exc)
    except Exception as exc:
        logger.exception("Event scan failed: %s", exc)


# ── Background scan loop ───────────────────────────────────────────────────────

SCAN_INTERVAL_S = 10 * 60  # 10 minutes

def _scan_loop() -> None:
    """Run on startup, then repeat every SCAN_INTERVAL_S seconds."""
    while True:
        _do_scan()
        time.sleep(SCAN_INTERVAL_S)


# ── Startup ────────────────────────────────────────────────────────────────────

@app.on_event("startup")
def startup_scan() -> None:
    _init_signal_db()  # ensure signals.db tables exist before first scan
    _load_scan_cache()  # serve stale data immediately while fresh scan runs
    threading.Thread(target=_scan_loop, daemon=True).start()
    threading.Thread(target=_signals_loop, daemon=True).start()


# ── Routes ─────────────────────────────────────────────────────────────────────

class StatusResponse(BaseModel):
    status: str
    scanned_at: str | None = None
    error: str | None = None
    coin_count: int | None = None


@app.get("/api/health")
def health() -> dict:
    return {"ok": True}


@app.get("/api/data")
def get_data() -> dict:
    with _lock:
        status = _state["status"]
        data = _state["data"]
        scanned_at = _state["scanned_at"]
        error = _state["error"]

    if status == "ready" and data is not None:
        return {
            "status": "ready",
            "scanned_at": scanned_at,
            "coin_count": len(data),
            "coins": data,
        }
    # While scanning/idle, return stale data (from previous scan) so the dashboard
    # can render immediately instead of blocking on the spinner.
    return {
        "status": status,
        "scanned_at": scanned_at,
        "error": error,
        "coins": data if data is not None else [],
    }


@app.post("/api/refresh")
def refresh() -> StatusResponse:
    with _lock:
        if _state["status"] == "scanning":
            return StatusResponse(status="scanning", scanned_at=_state["scanned_at"])

    t = threading.Thread(target=_do_scan, daemon=True)
    t.start()
    return StatusResponse(status="scanning")


@app.get("/api/events")
def get_events() -> dict:
    with _events_lock:
        return dict(_events_cache)


@app.get("/api/events/poll")
def poll_events(since: str | None = None) -> dict:
    """Return events only if scanned_at > since, else return {changed: false}."""
    with _events_lock:
        scanned_at = _events_cache.get("scanned_at")

    if since and scanned_at and scanned_at <= since:
        return {"changed": False, "scanned_at": scanned_at}

    with _events_lock:
        return {"changed": True, **_events_cache}


@app.get("/api/signals")
def get_signals(tab: str = "recent") -> dict:
    """Signal log panel data — served from in-memory cache (refreshed every 5 min)."""
    from ichi.signal.filters import get_btc_1d_regime
    btc_regime = get_btc_1d_regime()

    with _signals_lock:
        refreshed_at = _signals_cache["refreshed_at"]
        if tab in ("recent", "open", "setups", "history"):
            key = tab
            rows = _signals_cache[key]
            if rows is None:
                return {"tab": tab, "rows": [], "loading": True, "btc_regime": btc_regime}
            return {"tab": tab, "rows": rows, "refreshed_at": refreshed_at, "btc_regime": btc_regime}
        if tab == "performance":
            stats = _signals_cache["performance"]
            if stats is None:
                return {"tab": tab, "stats": [], "loading": True, "btc_regime": btc_regime}
            return {"tab": tab, "stats": stats, "refreshed_at": refreshed_at, "btc_regime": btc_regime}
        if tab == "developing":
            with _events_lock:
                devs = _events_cache.get("developing_setups") or []
            return {"tab": tab, "rows": devs, "refreshed_at": refreshed_at, "btc_regime": btc_regime}
    return {"tab": tab, "error": "unknown tab", "btc_regime": btc_regime}
