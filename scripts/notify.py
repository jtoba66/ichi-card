#!/usr/bin/env python3
"""
Push notifications via ntfy.sh for new/closed signals.
Usage: uv run python scripts/notify.py --since "2026-05-22T04:00:00+00:00" --topic ichi-joe
"""
import argparse, json, sqlite3, urllib.request
from pathlib import Path

DB_PATH = Path(__file__).resolve().parents[1] / "data" / "signals.db"

SIGNAL_NAMES = {
    1: "Sanyaku", 2: "Bal.Break", 3: "KJ Retest",
    4: "E2E", 5: "Twist", 6: "Curl",
    7: "4-Level", 9: "Chikou",
}

def push(topic: str, title: str, message: str, tag: str = "bell") -> None:
    data = json.dumps({"topic": topic, "title": title, "message": message, "tags": [tag]}).encode()
    req  = urllib.request.Request("https://ntfy.sh", data=data,
                                   headers={"Content-Type": "application/json"})
    try:
        urllib.request.urlopen(req, timeout=10)
    except Exception as e:
        print(f"  ntfy error: {e}")

def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--since", required=True)
    ap.add_argument("--topic", default="ichi-scorecard")
    args = ap.parse_args()

    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row

    # All new signals fired since last run — deduplicated by symbol+timeframe
    # (if same coin fires multiple signal types same bar, show once with highest score)
    raw_new = conn.execute("""
        SELECT symbol, signal_type, timeframe, entry_price, bull_score, fired_at
        FROM signal_log
        WHERE status='OPEN' AND fired_at >= ? AND is_backfill=0
        ORDER BY bull_score DESC, signal_type ASC
    """, (args.since,)).fetchall()

    # Deduplicate: keep highest-score signal per symbol+timeframe
    seen = {}
    for s in raw_new:
        key = (s["symbol"], s["timeframe"])
        if key not in seen:
            seen[key] = s
    new_sigs = list(seen.values())
    new_sigs.sort(key=lambda s: (-s["bull_score"], s["symbol"]))

    # All closed signals since last run — use exit_timestamp (not updated_at)
    # Deduplicated by symbol+timeframe, best return shown
    raw_closed = conn.execute("""
        SELECT symbol, signal_type, timeframe, exit_return,
               exit_condition, duration_bars, bull_score
        FROM signal_log
        WHERE status='CLOSED' AND exit_timestamp >= ? AND exit_return IS NOT NULL
        ORDER BY exit_return DESC
    """, (args.since,)).fetchall()

    seen_c = {}
    for s in raw_closed:
        key = (s["symbol"], s["timeframe"])
        if key not in seen_c:
            seen_c[key] = s
    closed_sigs = list(seen_c.values())
    closed_sigs.sort(key=lambda s: -(s["exit_return"] or 0))

    conn.close()

    MAX = 8

    if new_sigs:
        lines = []
        for s in new_sigs[:MAX]:
            name = SIGNAL_NAMES.get(s["signal_type"], f"S{s['signal_type']}")
            lines.append(f"{s['symbol']} {s['timeframe']} {name} sc{s['bull_score']} @{s['entry_price']}")
        if len(new_sigs) > MAX:
            lines.append(f"...+{len(new_sigs)-MAX} more")
        push(args.topic,
             f"🟢 {len(new_sigs)} new signal{'s' if len(new_sigs)>1 else ''}",
             "\n".join(lines), tag="bell")
        print(f"  Pushed: {len(new_sigs)} new signals")

    if closed_sigs:
        lines = []
        for s in closed_sigs[:MAX]:
            ret   = s["exit_return"]
            emoji = "✅" if ret and ret > 0 else "❌"
            lines.append(f"{emoji} {s['symbol']} {s['timeframe']} {ret:+.1f}% {s['duration_bars']}b")
        if len(closed_sigs) > MAX:
            lines.append(f"...+{len(closed_sigs)-MAX} more")
        push(args.topic,
             f"📊 {len(closed_sigs)} closed",
             "\n".join(lines), tag="bar_chart")
        print(f"  Pushed: {len(closed_sigs)} closed signals")

    if not new_sigs and not closed_sigs:
        print("  No new activity — no push sent")

if __name__ == "__main__":
    main()
