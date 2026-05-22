#!/usr/bin/env python3
"""
Cron fallback: push signal_log digest to ntfy.sh.
Real-time event notifications now fire directly from the API scan loop.

Usage: uv run python scripts/notify.py --since "2026-05-22T04:00:00+00:00"
"""
import argparse
import sys
from pathlib import Path

# Make sure project src is importable when called from cron
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from ichi.notifier import push_new_signals

def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--since", required=True,
                    help="ISO timestamp — push signals/exits after this time")
    ap.add_argument("--topic", default=None,
                    help="ntfy topic (overrides NTFY_TOPIC env, default: ichi-joe)")
    args = ap.parse_args()

    if args.topic:
        import ichi.notifier as _n
        _n.NTFY_TOPIC = args.topic

    push_new_signals(since=args.since)

if __name__ == "__main__":
    main()
