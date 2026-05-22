#!/usr/bin/env python3
"""
Push notifications via ntfy.sh for new/closed signals.
Usage: uv run python scripts/notify.py --since "2026-05-22T04:00:00+00:00" --topic ichi-joe
"""
import argparse, json, sqlite3, urllib.request
from pathlib import Path

DB_PATH = Path(__file__).resolve().parents[1] / "data" / "signals.db"

SIGNAL_NAMES = {
    1: "Sanyaku", 2: "Balanced Breakout", 3: "KJ Break Retest",
    4: "E2E Entry", 5: "Twist Breakout", 6: "Cloud Curling",
    7: "Four-Level Retest", 9: "Chikou S/R Retest",
}

def push(topic: str, title: str, message: str, tags: str = "chart_with_upwards_trend") -> None:
    data = json.dumps({"topic": topic, "title": title, "message": message, "tags": [tags]}).encode()
    req  = urllib.request.Request("https://ntfy.sh", data=data,
                                   headers={"Content-Type": "application/json"})
    try:
        urllib.request.urlopen(req, timeout=10)
    except Exception as e:
        print(f"  ntfy error: {e}")

def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--since",  required=True, help="ISO timestamp — check signals updated after this")
    ap.add_argument("--topic",  default="ichi-scorecard", help="ntfy.sh topic name")
    args = ap.parse_args()

    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row

    # New Signal 1 (Sanyaku) fires — the only validated signal worth pushing
    new_sigs = conn.execute("""
        SELECT symbol, signal_type, timeframe, entry_price, bull_score, fired_at
        FROM signal_log
        WHERE signal_type=1 AND bull_score >= 13
          AND status='OPEN' AND fired_at >= ? AND is_backfill=0
        ORDER BY bull_score DESC, fired_at DESC
    """, (args.since,)).fetchall()

    # Signal 1 closes since last run
    closed_sigs = conn.execute("""
        SELECT symbol, signal_type, timeframe, entry_price, exit_return,
               exit_condition, duration_bars, bull_score
        FROM signal_log
        WHERE signal_type=1
          AND status='CLOSED' AND updated_at >= ? AND exit_return IS NOT NULL
        ORDER BY exit_return DESC
    """, (args.since,)).fetchall()
    conn.close()

    MAX_LINES = 8  # ntfy free tier ~4KB body limit

    if new_sigs:
        lines = []
        for s in list(new_sigs)[:MAX_LINES]:
            name = SIGNAL_NAMES.get(s["signal_type"], f"Sig{s['signal_type']}")
            lines.append(f"{s['symbol']} {name} {s['timeframe']} sc{s['bull_score']} @{s['entry_price']}")
        if len(new_sigs) > MAX_LINES:
            lines.append(f"...+{len(new_sigs)-MAX_LINES} more")
        push(args.topic,
             f"🟢 {len(new_sigs)} new signal{'s' if len(new_sigs)>1 else ''}",
             "\n".join(lines),
             tags="bell")
        print(f"  Pushed: {len(new_sigs)} new signals")

    if closed_sigs:
        lines = []
        for s in list(closed_sigs)[:MAX_LINES]:
            ret   = s["exit_return"]
            emoji = "✅" if ret and ret > 0 else "❌"
            lines.append(f"{emoji} {s['symbol']} {s['timeframe']} {ret:+.1f}% {s['duration_bars']}bars")
        if len(closed_sigs) > MAX_LINES:
            lines.append(f"...+{len(closed_sigs)-MAX_LINES} more")
        push(args.topic,
             f"📊 {len(closed_sigs)} signal{'s' if len(closed_sigs)>1 else ''} closed",
             "\n".join(lines),
             tags="bar_chart")
        print(f"  Pushed: {len(closed_sigs)} closed signals")

    if not new_sigs and not closed_sigs:
        print("  No new activity — no push sent")

if __name__ == "__main__":
    main()
