"""
Heartbeat / health-check for the ichi system. Runs hourly via systemd timer.

Sends to ntfy:
  - ⚠️ IMMEDIATELY (priority high) if anything is unhealthy:
       * FastAPI not responding on :8000
       * last scan older than 40 min (scan loop stuck — e.g. the May-10 cache freeze)
       * Postgres unreachable
  - ✅ ONCE A DAY at 08:00 UTC (priority low) as a known pulse.
       If this daily pulse stops arriving, the box itself is down/offline.

Self-contained: posts directly to ntfy.sh, no dependency on notifier internals.
"""
from __future__ import annotations
import os, sys, json
from datetime import datetime, timezone
from urllib import request as urlreq

sys.path.insert(0, "/home/joe/ichi-scorecard/src")

NTFY_URL   = "https://ntfy.sh"
NTFY_TOPIC = os.environ.get("NTFY_TOPIC", "ichi-joe")
API_URL    = "http://localhost:8000/api/data"
SCAN_STALE_MIN = 40
PULSE_HOUR_UTC = 8


def _post(title, message, priority, tags):
    data = json.dumps({
        "topic": NTFY_TOPIC, "title": title, "message": message,
        "priority": priority, "tags": tags,
    }).encode()
    req = urlreq.Request(NTFY_URL, data=data, headers={"Content-Type": "application/json"})
    try:
        urlreq.urlopen(req, timeout=15)
    except Exception as e:
        print(f"ntfy post failed: {e}")


def check_api():
    try:
        with urlreq.urlopen(API_URL, timeout=15) as r:
            d = json.loads(r.read())
        sa = d.get("scanned_at")
        if not sa:
            return False, "API up but no scanned_at", None
        age_min = (datetime.now(timezone.utc) - datetime.fromisoformat(sa)).total_seconds() / 60
        return True, f"scan {age_min:.0f}m ago, {d.get('coin_count','?')} coins", age_min
    except Exception as e:
        return False, f"API unreachable: {e}", None


def check_db():
    try:
        from ichi.signal.db import get_conn
        conn = get_conn()
        cur = conn.cursor()
        cur.execute("SELECT count(*) FROM signal_log WHERE status='OPEN' AND is_backfill=0")
        n_open = cur.fetchone()[0]
        cur.execute("SELECT max(fired_at) FROM signal_log WHERE is_backfill=0")
        last = cur.fetchone()[0]
        conn.close()
        return True, f"{n_open} open, last signal {str(last)[:16]}"
    except Exception as e:
        return False, f"DB unreachable: {e}"


def btc_regime():
    try:
        from ichi.signal.filters import get_btc_1d_regime
        return get_btc_1d_regime()
    except Exception:
        return "?"


def main():
    problems = []
    api_ok, api_msg, age = check_api()
    if not api_ok:
        problems.append(f"API: {api_msg}")
    elif age is not None and age > SCAN_STALE_MIN:
        problems.append(f"scan STALE ({age:.0f}m > {SCAN_STALE_MIN}m) — scan loop stuck")

    db_ok, db_msg = check_db()
    if not db_ok:
        problems.append(db_msg)

    if problems:
        _post("⚠️ ichi system issue", "\n".join(problems), 5, ["warning"])
        print("UNHEALTHY:", problems)
        return

    # Healthy — daily pulse only
    if datetime.now(timezone.utc).hour == PULSE_HOUR_UTC:
        body = f"BTC: {btc_regime()} cloud\n{api_msg}\n{db_msg}"
        _post("✅ ichi alive", body, 1, ["white_check_mark"])
        print("PULSE sent:", body.replace("\n", " | "))
    else:
        print(f"healthy (no pulse this hour): {api_msg} | {db_msg}")


if __name__ == "__main__":
    main()
