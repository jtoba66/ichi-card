"""File-based 7-day score history for sparkline data."""
from __future__ import annotations

import json
from datetime import date, timedelta
from pathlib import Path

_HISTORY_FILE = Path(__file__).parents[3] / "data" / "score_history.json"
_KEEP_DAYS = 7


def load_history() -> dict[str, list[dict]]:
    """Return {symbol: [{date, bull, bear}, ...]} sorted oldest-first."""
    if not _HISTORY_FILE.exists():
        return {}
    try:
        with open(_HISTORY_FILE) as f:
            return json.load(f)
    except Exception:
        return {}


def save_history(coins: list[dict]) -> None:
    """Append today's scores for each coin, prune entries older than KEEP_DAYS."""
    history = load_history()
    today = date.today().isoformat()
    cutoff = (date.today() - timedelta(days=_KEEP_DAYS)).isoformat()

    for coin in coins:
        sym = coin["symbol"]
        entries = history.get(sym, [])
        # Remove today's entry if it already exists (overwrite)
        entries = [e for e in entries if e["date"] != today]
        entries.append({"date": today, "bull": coin["bull"], "bear": coin["bear"]})
        # Prune old entries
        entries = [e for e in entries if e["date"] >= cutoff]
        history[sym] = entries

    _HISTORY_FILE.parent.mkdir(parents=True, exist_ok=True)
    with open(_HISTORY_FILE, "w") as f:
        json.dump(history, f)


def attach_history(coins: list[dict]) -> list[dict]:
    """Add a 'history' key [{date, bull, bear}] to each coin dict (in place)."""
    history = load_history()
    for coin in coins:
        coin["history"] = history.get(coin["symbol"], [])
    return coins
