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

import logging
import threading
import time
from datetime import datetime, timezone

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel

from ichi.api.history import attach_history, save_history
from ichi.api.scanner import run_event_scan, run_full_scan
from ichi.signal.detector import init_db as _init_signal_db

logger = logging.getLogger(__name__)

app = FastAPI(title="ichi-scorecard API", version="0.1.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["GET", "POST"],
    allow_headers=["*"],
)

# ── In-memory scan caches ─────────────────────────────────────────────────────

_state: dict = {
    "status": "idle",       # idle | scanning | ready | error
    "data": None,
    "scanned_at": None,
    "error": None,
}
_lock = threading.Lock()

_EMPTY_EVENTS = {
    "transition_events":  [],
    "retest_alerts":      [],
    "balance_map":        [],
    "kumo_twists":        [],
    "e2e_opportunities":  [],
    "cloud_curling":      [],
    "new_signals_data":   [],
    "new_signal_count":   0,
    "scanned_at":         None,
}
_events_cache: dict = dict(_EMPTY_EVENTS)
_events_lock = threading.Lock()


def _do_scan() -> None:
    with _lock:
        _state["status"] = "scanning"
        _state["error"] = None

    try:
        coins = run_full_scan()
        save_history(coins)
        attach_history(coins)
        with _lock:
            _state["data"] = coins
            _state["status"] = "ready"
            _state["scanned_at"] = datetime.now(timezone.utc).isoformat()
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
    t = threading.Thread(target=_scan_loop, daemon=True)
    t.start()


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
    return {
        "status": status,
        "scanned_at": scanned_at,
        "error": error,
        "coins": [],
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
    """Signal log panel data.

    tab=recent     — signals fired in the last 14 days, newest first
    tab=open       — all currently open instances, sorted by days open
    tab=performance — per-signal-type stats (requires ≥20 closed instances)
    """
    import json
    import sqlite3
    from ichi.signal.detector import DB_PATH

    if not DB_PATH.exists():
        return {"tab": tab, "rows": [], "stats": []}

    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row

    try:
        if tab == "recent":
            rows = conn.execute(
                """
                SELECT sl.*, COUNT(c.id) AS cooccurrence_count
                FROM signal_log sl
                LEFT JOIN cooccurrence_log c
                  ON (c.signal_id_a = sl.signal_id OR c.signal_id_b = sl.signal_id)
                WHERE sl.fired_at >= datetime('now', '-14 days')
                GROUP BY sl.signal_id
                ORDER BY sl.fired_at DESC
                LIMIT 100
                """
            ).fetchall()
            return {"tab": tab, "rows": [dict(r) for r in rows]}

        if tab == "open":
            rows = conn.execute(
                """
                SELECT sl.*, COUNT(c.id) AS cooccurrence_count,
                       CAST((julianday('now') - julianday(sl.fired_at)) AS INTEGER) AS days_open
                FROM signal_log sl
                LEFT JOIN cooccurrence_log c
                  ON (c.signal_id_a = sl.signal_id OR c.signal_id_b = sl.signal_id)
                WHERE sl.status = 'OPEN'
                GROUP BY sl.signal_id
                ORDER BY sl.fired_at ASC
                """
            ).fetchall()
            return {"tab": tab, "rows": [dict(r) for r in rows]}

        if tab == "performance":
            stats = []
            signal_names = {
                1: "Sanyaku", 2: "Balanced Breakout", 3: "KJ Break Retest",
                4: "E2E Entry", 5: "Twist Breakout", 6: "Cloud Curling",
                7: "Four-Level Retest", 9: "Chikou S/R Retest",
            }
            types = conn.execute(
                "SELECT DISTINCT signal_type FROM signal_log ORDER BY signal_type"
            ).fetchall()
            for (sig_type,) in types:
                subset = conn.execute(
                    "SELECT * FROM signal_log WHERE signal_type = ?", (sig_type,)
                ).fetchall()
                closed = [r for r in subset if dict(r)["status"] == "CLOSED"]
                n = len(subset)
                n_closed = len(closed)
                if n == 0:
                    continue

                def _m(xs):
                    return sum(xs) / len(xs) if xs else None

                def _pct(xs, p):
                    if not xs:
                        return None
                    s = sorted(xs)
                    idx = (len(s) - 1) * p / 100
                    lo, hi = int(idx), min(int(idx) + 1, len(s) - 1)
                    return s[lo] + (s[hi] - s[lo]) * (idx - lo)

                returns_30d = [dict(r)["return_30d"] for r in subset if dict(r)["return_30d"] is not None]
                exit_returns = [dict(r)["exit_return"] for r in closed if dict(r)["exit_return"] is not None]
                exit_bars = [dict(r)["exit_bar"] for r in closed if dict(r)["exit_bar"] is not None]
                hosoda_yes = [dict(r)["return_30d"] for r in subset
                              if dict(r)["hosoda_active"] and dict(r)["return_30d"] is not None]
                hosoda_no = [dict(r)["return_30d"] for r in subset
                             if not dict(r)["hosoda_active"] and dict(r)["return_30d"] is not None]
                mae_vals = [dict(r)["mae"] for r in closed if dict(r).get("mae") is not None]
                mfe_vals = [dict(r)["mfe"] for r in closed if dict(r).get("mfe") is not None]
                dur_vals = [dict(r)["duration_bars"] for r in closed if dict(r).get("duration_bars") is not None]

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
                })
            return {"tab": tab, "stats": stats}

        return {"tab": tab, "error": "unknown tab"}

    finally:
        conn.close()
