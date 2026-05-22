"""Real-time ntfy.sh push notifications.

Called from the API scan loop (every ~10 min) so alerts fire as soon as
the event scanner picks them up — no waiting for the 4h cron.

Also used by scripts/notify.py for the signal_log digest.
"""
from __future__ import annotations

import json
import sqlite3
import urllib.request
from datetime import datetime, timezone, timedelta
from pathlib import Path

_NTFY_URL   = "https://ntfy.sh"
_STATE_PATH = Path(__file__).resolve().parents[2] / "data" / "notif_state.json"
_DB_PATH    = Path(__file__).resolve().parents[2] / "data" / "signals.db"

# Read topic from env or fall back to default
import os
NTFY_TOPIC = os.environ.get("NTFY_TOPIC", "ichi-joe")

SIGNAL_NAMES = {
    1: "Sanyaku", 2: "Bal.Break", 3: "KJ Retest",
    4: "E2E",     5: "Twist",     6: "Curl",
    7: "4-Level", 9: "Chikou",
}


# ── ntfy push ─────────────────────────────────────────────────────────────────

def _push(title: str, message: str, tag: str = "bell") -> None:
    data = json.dumps({
        "topic":   NTFY_TOPIC,
        "title":   title,
        "message": message,
        "tags":    [tag],
        "priority": 3,
    }).encode()
    req = urllib.request.Request(
        _NTFY_URL, data=data,
        headers={"Content-Type": "application/json"},
    )
    try:
        urllib.request.urlopen(req, timeout=10)
    except Exception as e:
        print(f"  [ntfy] error: {e}")


# ── State management ──────────────────────────────────────────────────────────

def _load_state() -> dict:
    if _STATE_PATH.exists():
        try:
            with open(_STATE_PATH) as f:
                return json.load(f)
        except Exception:
            pass
    return {"pushed_events": {}, "last_signal_ts": None}


def _save_state(state: dict) -> None:
    _STATE_PATH.parent.mkdir(parents=True, exist_ok=True)
    with open(_STATE_PATH, "w") as f:
        json.dump(state, f)


def _prune_old(pushed: dict, max_age_hours: int = 24) -> dict:
    """Drop events older than max_age_hours so they can re-fire."""
    cutoff = datetime.now(timezone.utc) - timedelta(hours=max_age_hours)
    out = {}
    for k, v in pushed.items():
        try:
            ts = datetime.fromisoformat(v)
            if ts.tzinfo is None:
                ts = ts.replace(tzinfo=timezone.utc)
            if ts > cutoff:
                out[k] = v
        except Exception:
            pass
    return out


# ── Dashboard event push (called every 10 min by API scan loop) ───────────────

def push_events(events: dict) -> None:
    """Push new dashboard B events to ntfy. Deduplicates within 24h."""
    state   = _load_state()
    pushed  = _prune_old(state.get("pushed_events", {}))
    now_str = datetime.now(timezone.utc).isoformat()
    lines: list[str] = []

    # 1. Kumo transitions (price crossed above/below cloud)
    for r in events.get("transitions", []):
        direction = r.get("direction", "")
        key = f"trans:{r['symbol']}:{r['timeframe']}:{direction}"
        if key not in pushed:
            emoji = "🟢" if direction == "ABOVE" else "🔴"
            sym = r["symbol"].replace("/USDT", "")
            lines.append(f"{emoji} {sym} {r['timeframe']} broke {direction.lower()} cloud")
            pushed[key] = now_str

    # 2. Imminent kumo twists (≤5 bars)
    for r in events.get("kumo_twists", []):
        bars = r.get("bars_until_twist", 99)
        if bars <= 5:
            direction = r.get("twist_direction", "")
            key = f"twist:{r['symbol']}:{r['timeframe']}:{direction}"
            if key not in pushed:
                d_emoji = "📈" if direction == "BULL_TWIST" else "📉"
                sym = r["symbol"].replace("/USDT", "")
                lines.append(f"{d_emoji} {sym} {r['timeframe']} twist in {bars}b ({direction.replace('_',' ').lower()})")
                pushed[key] = now_str

    # 3. Line retests
    for r in events.get("retest_alerts", []):
        rtype = r.get("retest_type", "")
        key = f"retest:{r['symbol']}:{r['timeframe']}:{rtype}"
        if key not in pushed:
            sym = r["symbol"].replace("/USDT", "")
            lines.append(f"↩️ {sym} {r['timeframe']} retest {rtype.replace('_',' ').lower()}")
            pushed[key] = now_str

    if lines:
        MAX = 8
        body = "\n".join(lines[:MAX])
        if len(lines) > MAX:
            body += f"\n...+{len(lines)-MAX} more"
        _push(
            f"⚡ {len(lines)} new event{'s' if len(lines) > 1 else ''}",
            body,
            tag="zap",
        )
        print(f"  [ntfy] pushed {len(lines)} dashboard events")

    state["pushed_events"] = pushed
    _save_state(state)


# ── Signal log push (called after tracker runs) ───────────────────────────────

def push_new_signals(since: str | None = None) -> None:
    """Push new/closed signals from signal_log since last push."""
    if not _DB_PATH.exists():
        return

    state   = _load_state()
    last_ts = since or state.get("last_signal_ts") or "2020-01-01T00:00:00+00:00"
    now_str = datetime.now(timezone.utc).isoformat()

    conn = sqlite3.connect(_DB_PATH)
    conn.row_factory = sqlite3.Row

    raw_new = conn.execute("""
        SELECT symbol, signal_type, timeframe, entry_price, bull_score, fired_at
        FROM signal_log
        WHERE status='OPEN' AND fired_at > ? AND is_backfill=0
        ORDER BY bull_score DESC, fired_at DESC
    """, (last_ts,)).fetchall()

    raw_closed = conn.execute("""
        SELECT symbol, signal_type, timeframe, exit_return,
               exit_condition, duration_bars, bull_score, exit_timestamp
        FROM signal_log
        WHERE status='CLOSED' AND exit_timestamp > ? AND exit_return IS NOT NULL AND is_backfill=0
        ORDER BY exit_return DESC
    """, (last_ts,)).fetchall()

    conn.close()

    # Dedup new: one push per symbol+timeframe (highest score)
    seen: dict = {}
    for s in raw_new:
        key = (s["symbol"], s["timeframe"])
        if key not in seen:
            seen[key] = s
    new_sigs = sorted(seen.values(), key=lambda s: -(s["bull_score"] or 0))

    if new_sigs:
        MAX = 8
        lines = []
        for s in new_sigs[:MAX]:
            name = SIGNAL_NAMES.get(s["signal_type"], f"S{s['signal_type']}")
            sym  = s["symbol"].replace("/USDT", "")
            lines.append(f"{sym} {s['timeframe']} {name} sc{s['bull_score']} @{s['entry_price']:.4f}")
        if len(new_sigs) > MAX:
            lines.append(f"...+{len(new_sigs)-MAX} more")
        _push(
            f"🟢 {len(new_sigs)} new signal{'s' if len(new_sigs) > 1 else ''}",
            "\n".join(lines),
            tag="bell",
        )
        print(f"  [ntfy] pushed {len(new_sigs)} new signals")

    # Dedup closed: one push per symbol+timeframe (best return)
    seen_c: dict = {}
    for s in raw_closed:
        key = (s["symbol"], s["timeframe"])
        if key not in seen_c:
            seen_c[key] = s
    closed_sigs = sorted(seen_c.values(), key=lambda s: -(s["exit_return"] or 0))

    if closed_sigs:
        MAX = 8
        lines = []
        for s in closed_sigs[:MAX]:
            ret   = s["exit_return"]
            emoji = "✅" if ret and ret > 0 else "❌"
            sym   = s["symbol"].replace("/USDT", "")
            lines.append(f"{emoji} {sym} {s['timeframe']} {ret:+.1f}% {s['duration_bars']}b")
        if len(closed_sigs) > MAX:
            lines.append(f"...+{len(closed_sigs)-MAX} more")
        _push(
            f"📊 {len(closed_sigs)} closed",
            "\n".join(lines),
            tag="bar_chart",
        )
        print(f"  [ntfy] pushed {len(closed_sigs)} closed signals")

    if not new_sigs and not closed_sigs:
        print("  [ntfy] no new signal activity")

    state["last_signal_ts"] = now_str
    _save_state(state)
