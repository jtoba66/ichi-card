"""Signal detector — all 8 named Ichimoku signal types.

Signals 1-7 and 9 (Signal 8 removed; Hosoda counts are a modifier tag).
Each detector receives a fully precomputed dataframe and returns a signal
dict if the conditions are met at the latest bar, or None.
"""
from __future__ import annotations

import json
import sqlite3
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

import pandas as pd

DB_PATH = Path(__file__).parents[3] / "data" / "signals.db"

HOSODA_NUMBERS = {9, 17, 26, 33, 42, 51, 65, 76, 83, 97, 101, 129, 172}

_SIGNAL_NAMES = {
    1: "Sanyaku Confirmation",
    2: "Balanced Breakout",
    3: "KJ Break Retest",
    4: "E2E Entry",
    5: "Twist Breakout",
    6: "Cloud Curling Confirmed",
    7: "Four-Level Retest",
    9: "Chikou S/R Retest",
}

# ── Database ──────────────────────────────────────────────────────────────────

_CREATE_SIGNAL_LOG = """
CREATE TABLE IF NOT EXISTS signal_log (
    signal_id        TEXT PRIMARY KEY,
    signal_type      INTEGER NOT NULL,
    signal_subtype   TEXT,
    symbol           TEXT NOT NULL,
    timeframe        TEXT NOT NULL,
    fired_at         TEXT NOT NULL,
    entry_price      REAL NOT NULL,
    bull_score       INTEGER,
    cloud_state      TEXT,
    signal_metadata  TEXT,
    hosoda_active    INTEGER DEFAULT 0,
    hosoda_number    INTEGER,
    hosoda_pivot_type TEXT,
    return_7d        REAL,
    return_30d       REAL,
    status           TEXT DEFAULT 'OPEN',
    exit_tier        INTEGER,
    exit_condition   TEXT,
    exit_bar         INTEGER,
    exit_price       REAL,
    exit_return      REAL,
    exit_timestamp   TEXT,
    warning_log      TEXT,
    is_backfill      INTEGER DEFAULT 0,
    logged_at        TEXT NOT NULL,
    updated_at       TEXT NOT NULL
);
"""

_CREATE_SIGNAL_LOG_INDEXES = """
CREATE INDEX IF NOT EXISTS idx_signal_type ON signal_log(signal_type);
CREATE INDEX IF NOT EXISTS idx_symbol      ON signal_log(symbol, timeframe);
CREATE INDEX IF NOT EXISTS idx_status      ON signal_log(status);
CREATE INDEX IF NOT EXISTS idx_fired_at    ON signal_log(fired_at);
"""

_CREATE_CHIKOU_LEVELS = """
CREATE TABLE IF NOT EXISTS chikou_levels (
    level_id           INTEGER PRIMARY KEY AUTOINCREMENT,
    symbol             TEXT NOT NULL,
    timeframe          TEXT NOT NULL,
    level_price        REAL NOT NULL,
    first_bar          INTEGER,
    last_bar           INTEGER,
    touch_count        INTEGER,
    duration_bars      INTEGER,
    significance_score INTEGER,
    level_type         TEXT,
    last_updated       TEXT
);
CREATE INDEX IF NOT EXISTS idx_chikou_symbol ON chikou_levels(symbol, timeframe);
"""

_CREATE_COOCCURRENCE_LOG = """
CREATE TABLE IF NOT EXISTS cooccurrence_log (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    signal_id_a TEXT REFERENCES signal_log(signal_id),
    signal_id_b TEXT REFERENCES signal_log(signal_id),
    symbol      TEXT,
    timeframe   TEXT,
    bars_apart  INTEGER,
    logged_at   TEXT
);
"""


def init_db() -> None:
    """Create all tables and indexes. Safe to call repeatedly (IF NOT EXISTS)."""
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(DB_PATH)
    try:
        conn.executescript(_CREATE_SIGNAL_LOG)
        conn.executescript(_CREATE_SIGNAL_LOG_INDEXES)
        conn.executescript(_CREATE_CHIKOU_LEVELS)
        conn.executescript(_CREATE_COOCCURRENCE_LOG)
        # Safe migrations for columns added after initial release
        for col, typedef in [
            ("mae",           "REAL"),
            ("mfe",           "REAL"),
            ("duration_bars", "INTEGER"),
        ]:
            try:
                conn.execute(f"ALTER TABLE signal_log ADD COLUMN {col} {typedef}")
            except sqlite3.OperationalError:
                pass  # column already exists
        conn.commit()
    finally:
        conn.close()


# ── Helpers ───────────────────────────────────────────────────────────────────

def make_signal_id(signal_type: int | str, symbol: str, timeframe: str, epoch: float) -> str:
    return f"SIG{signal_type}_{symbol}_{timeframe}_{int(epoch)}"


def get_hosoda_state(df: pd.DataFrame, i: int) -> dict:
    recent_low_bar: Optional[int] = None
    recent_high_bar: Optional[int] = None
    for j in range(i, max(i - 200, -1), -1):
        if recent_low_bar is None and bool(df["_swing_low"].iat[j]):
            recent_low_bar = j
        if recent_high_bar is None and bool(df["_swing_high"].iat[j]):
            recent_high_bar = j
        if recent_low_bar is not None and recent_high_bar is not None:
            break

    base = {"hosoda_active": False, "hosoda_number": None,
            "hosoda_pivot_type": None, "hosoda_bars_from_pivot": None}

    for pivot_bar, pivot_type in [(recent_low_bar, "LOW"), (recent_high_bar, "HIGH")]:
        if pivot_bar is None:
            continue
        count = i - pivot_bar
        for h in HOSODA_NUMBERS:
            if abs(count - h) <= 1:
                base["hosoda_active"] = True
                base["hosoda_number"] = h
                base["hosoda_pivot_type"] = pivot_type
                base["hosoda_bars_from_pivot"] = count
                return base
    return base


def _cloud_state(df: pd.DataFrame, i: int) -> str:
    c = float(df["close"].iat[i])
    top = float(df["_cloud_top"].iat[i])
    bot = float(df["_cloud_bottom"].iat[i])
    if c > top:
        return "ABOVE"
    if c < bot:
        return "BELOW"
    return "IN"


def _safe(val) -> Optional[float]:
    try:
        v = float(val)
        return None if pd.isna(v) else v
    except Exception:
        return None


def log_signal(signal_dict: dict) -> bool:
    """Insert signal into DB. Returns True if newly inserted, False if duplicate."""
    conn = sqlite3.connect(DB_PATH)
    try:
        now = datetime.now(timezone.utc).isoformat()
        cur = conn.execute(
            """
            INSERT OR IGNORE INTO signal_log
            (signal_id, signal_type, signal_subtype, symbol, timeframe,
             fired_at, entry_price, bull_score, cloud_state, signal_metadata,
             hosoda_active, hosoda_number, hosoda_pivot_type,
             is_backfill, logged_at, updated_at, status)
            VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
            """,
            (
                signal_dict["signal_id"],
                signal_dict["signal_type"],
                signal_dict.get("signal_subtype"),
                signal_dict["symbol"],
                signal_dict["timeframe"],
                signal_dict["fired_at"],
                signal_dict["entry_price"],
                signal_dict.get("bull_score"),
                signal_dict.get("cloud_state"),
                json.dumps(signal_dict.get("signal_metadata", {})),
                int(signal_dict.get("hosoda_active", False)),
                signal_dict.get("hosoda_number"),
                signal_dict.get("hosoda_pivot_type"),
                int(signal_dict.get("is_backfill", False)),
                now, now,
                "OPEN",
            ),
        )
        conn.commit()
        return cur.rowcount > 0
    finally:
        conn.close()
    return False


def check_cooccurrence(
    signal_id: str, symbol: str, timeframe: str,
    fired_at: str, signal_type_exclude: int, window_bars: int = 5
) -> None:
    """Log co-occurrences: other signals on same symbol/tf within window_bars bars."""
    tf_minutes = {"1d": 1440, "4h": 240, "1w": 10080}
    mins = tf_minutes.get(timeframe, 1440)
    window_secs = window_bars * mins * 60

    conn = sqlite3.connect(DB_PATH)
    try:
        rows = conn.execute(
            """
            SELECT signal_id, fired_at FROM signal_log
            WHERE symbol = ? AND timeframe = ? AND signal_id != ?
            ORDER BY fired_at DESC LIMIT 50
            """,
            (symbol, timeframe, signal_id),
        ).fetchall()

        try:
            t_self = datetime.fromisoformat(fired_at).timestamp()
        except Exception:
            return

        now = datetime.now(timezone.utc).isoformat()
        for other_id, other_fired in rows:
            try:
                t_other = datetime.fromisoformat(other_fired).timestamp()
            except Exception:
                continue
            diff_secs = abs(t_self - t_other)
            if diff_secs <= window_secs:
                bars_apart = max(1, round(diff_secs / (mins * 60)))
                conn.execute(
                    """
                    INSERT OR IGNORE INTO cooccurrence_log
                    (signal_id_a, signal_id_b, symbol, timeframe, bars_apart, logged_at)
                    VALUES (?,?,?,?,?,?)
                    """,
                    (signal_id, other_id, symbol, timeframe, bars_apart, now),
                )
        conn.commit()
    finally:
        conn.close()


# ── Signal Detectors ──────────────────────────────────────────────────────────

def detect_signal_1(df: pd.DataFrame, symbol: str, tf: str, bull_score: int,
                    is_backfill: bool = False, _bar_i: int = -1) -> Optional[dict]:
    """Signal 1 — Full Sanyaku Confirmation."""
    i = len(df) - 1 if _bar_i < 0 else _bar_i
    if i < 26:
        return None
    try:
        if not (
            df["close"].iat[i] > max(df["span_a"].iat[i], df["span_b"].iat[i])
            and bool(df["_chikou_above_past_price"].iat[i])
            and bool(df["_chikou_above_cloud"].iat[i])
            and df["tk"].iat[i] > df["kj"].iat[i]
            and df["span_a_lead"].iat[i] > df["span_b_lead"].iat[i]
            and bull_score >= 12
        ):
            return None
        hosoda = get_hosoda_state(df, i)
        return {
            "signal_type": 1,
            "symbol": symbol, "timeframe": tf,
            "fired_at": str(df.index[i]),
            "entry_price": float(df["close"].iat[i]),
            "bull_score": bull_score,
            "cloud_state": "ABOVE",
            "signal_metadata": {
                "tk_cross_bars_ago": _safe(df["_tk_cross_bullish_bars_ago"].iat[i]),
                "chikou_angle": _safe(df["_chikou_angle"].iat[i]),
                "cloud_thickness_pct": _safe(df["_cloud_thickness_pct"].iat[i]),
            },
            **hosoda, "is_backfill": is_backfill,
        }
    except Exception:
        return None


def detect_signal_2(df: pd.DataFrame, symbol: str, tf: str, bull_score: int,
                    is_backfill: bool = False, _bar_i: int = -1) -> Optional[dict]:
    """Signal 2 — Balanced Breakout."""
    i = len(df) - 1 if _bar_i < 0 else _bar_i
    if i < 5:
        return None
    try:
        prev_kj_dist = _safe(df["_prev_kj_distance_pct"].iat[i])
        if prev_kj_dist is None:
            return None
        if not (
            -5.0 <= prev_kj_dist <= 5.0
            and df["close"].iat[i] > df["tk"].iat[i]
            and df["close"].iat[i - 1] <= df["tk"].iat[i - 1]
            and df["span_a"].iat[i] > df["span_b"].iat[i]
            and df["span_a_lead"].iat[i] > df["span_b_lead"].iat[i]
            and (_safe(df["_vol_ratio"].iat[i]) or 0) > 1.3
            and (_safe(df["_kj_slope5"].iat[i]) or -999) >= -0.3
        ):
            return None
        hosoda = get_hosoda_state(df, i)
        return {
            "signal_type": 2,
            "symbol": symbol, "timeframe": tf,
            "fired_at": str(df.index[i]),
            "entry_price": float(df["close"].iat[i]),
            "bull_score": bull_score,
            "cloud_state": _cloud_state(df, i),
            "signal_metadata": {
                "kj_distance_at_break": prev_kj_dist,
                "vol_ratio": _safe(df["_vol_ratio"].iat[i]),
                "bull_score": bull_score,
            },
            **hosoda, "is_backfill": is_backfill,
        }
    except Exception:
        return None


def _bars_since_kj_break(df: pd.DataFrame, i: int, lookback: int = 20) -> int:
    for j in range(1, lookback + 1):
        if i - j < 1:
            break
        if (df["close"].iat[i - j] > df["kj"].iat[i - j]
                and df["close"].iat[i - j - 1] <= df["kj"].iat[i - j - 1]):
            return j
    return 999


def detect_signal_3(df: pd.DataFrame, symbol: str, tf: str, bull_score: int,
                    is_backfill: bool = False, _bar_i: int = -1) -> Optional[dict]:
    """Signal 3 — Kijun Break and Retest."""
    i = len(df) - 1 if _bar_i < 0 else _bar_i
    if i < 25:
        return None
    try:
        kj = float(df["kj"].iat[i])
        close = float(df["close"].iat[i])
        kj_break_bars = _bars_since_kj_break(df, i)
        if not (
            kj <= close <= kj * 1.02
            and close >= kj
            and kj_break_bars <= 20
            and (df["span_a"].iat[i] > df["span_b"].iat[i] or bool(df["_cloud_curling_up"].iat[i]))
            and (_safe(df["_kj_slope5"].iat[i]) or -999) >= 0
            and bull_score >= 9
        ):
            return None
        hosoda = get_hosoda_state(df, i)
        cloud_top = float(df["_cloud_top"].iat[i])
        return {
            "signal_type": 3,
            "symbol": symbol, "timeframe": tf,
            "fired_at": str(df.index[i]),
            "entry_price": close,
            "bull_score": bull_score,
            "cloud_state": _cloud_state(df, i),
            "signal_metadata": {
                "kj_break_bars_ago": kj_break_bars,
                "cloud_top_target": cloud_top,
                "bull_score": bull_score,
            },
            **hosoda, "is_backfill": is_backfill,
        }
    except Exception:
        return None


def detect_signal_4(df: pd.DataFrame, symbol: str, tf: str, bull_score: int,
                    is_backfill: bool = False, _bar_i: int = -1) -> Optional[dict]:
    """Signal 4 — E2E Entry."""
    i = len(df) - 1 if _bar_i < 0 else _bar_i
    if i < 5:
        return None
    try:
        # E2E entry must have occurred within the last 3 bars
        entered_bars_ago = None
        for offset in range(3):
            idx = i - offset
            if idx < 1:
                break
            if bool(df["_e2e_entry_from_below"].iat[idx]):
                entered_bars_ago = offset
                break
        if entered_bars_ago is None:
            return None
        thick = _safe(df["_cloud_thickness_pct"].iat[i])
        if not (
            (thick or 0) >= 5.0
            and df["span_a_lead"].iat[i] > df["span_b_lead"].iat[i]
            and bull_score >= 8
        ):
            return None
        entry_price = float(df["close"].iat[i - entered_bars_ago])
        target = float(df["_cloud_top"].iat[i])
        hosoda = get_hosoda_state(df, i)
        return {
            "signal_type": 4,
            "symbol": symbol, "timeframe": tf,
            "fired_at": str(df.index[i]),
            "entry_price": float(df["close"].iat[i]),
            "bull_score": bull_score,
            "cloud_state": "IN",
            "signal_metadata": {
                "entry_price_at_signal": entry_price,
                "target_price": target,
                "target_pct": round((target - entry_price) / entry_price * 100, 2) if entry_price else None,
                "cloud_thickness_pct": thick,
                "entered_bars_ago": entered_bars_ago,
            },
            **hosoda, "is_backfill": is_backfill,
        }
    except Exception:
        return None


def detect_signal_5(df: pd.DataFrame, symbol: str, tf: str, bull_score: int,
                    is_backfill: bool = False, _bar_i: int = -1) -> Optional[dict]:
    """Signal 5 — Kumo Twist Breakout."""
    i = len(df) - 1 if _bar_i < 0 else _bar_i
    if i < 5:
        return None
    try:
        # Recent twist (within last 3 bars) OR imminent (bars_until <= 3)
        twist_bars_ago = _safe(df["_cloud_twist_bull_bars_ago"].iat[i])
        recent_twist = twist_bars_ago is not None and twist_bars_ago <= 3

        # Imminent twist: span_a_lead about to cross span_b_lead
        bars_until_twist = None
        if not recent_twist:
            # Check next 3 projected bars in lead columns
            # We look at whether span_a_lead is approaching span_b_lead from below
            sa_lead = float(df["span_a_lead"].iat[i])
            sb_lead = float(df["span_b_lead"].iat[i])
            if sa_lead < sb_lead:  # currently bearish cloud ahead
                # rough heuristic: if span_a_lead slope positive and close to sb_lead
                slope = _safe(df["_span_a_lead_slope5"].iat[i]) or 0
                gap_pct = abs(sa_lead - sb_lead) / max(sb_lead, 1) * 100
                if slope > 0 and gap_pct < 0.5:
                    bars_until_twist = 2  # imminent
        if not recent_twist and bars_until_twist is None:
            return None
        if not (
            df["close"].iat[i] > max(df["span_a"].iat[i], df["span_b"].iat[i])
            and df["tk"].iat[i] > df["kj"].iat[i]
            and bull_score >= 10
        ):
            return None
        hosoda = get_hosoda_state(df, i)
        bars_to_from = -int(twist_bars_ago) if recent_twist else (bars_until_twist or 0)
        return {
            "signal_type": 5,
            "symbol": symbol, "timeframe": tf,
            "fired_at": str(df.index[i]),
            "entry_price": float(df["close"].iat[i]),
            "bull_score": bull_score,
            "cloud_state": "ABOVE",
            "signal_metadata": {
                "bars_to_or_from_twist": bars_to_from,
                "cloud_thickness_pct": _safe(df["_cloud_thickness_pct"].iat[i]),
                "tk_cross_bars_ago": _safe(df["_tk_cross_bullish_bars_ago"].iat[i]),
            },
            **hosoda, "is_backfill": is_backfill,
        }
    except Exception:
        return None


def detect_signal_6(df: pd.DataFrame, symbol: str, tf: str, bull_score: int,
                    is_backfill: bool = False, _bar_i: int = -1) -> Optional[dict]:
    """Signal 6 — Cloud Curling Confirmed."""
    i = len(df) - 1 if _bar_i < 0 else _bar_i
    if i < 5:
        return None
    try:
        twist_bars = _safe(df["_cloud_twist_bull_bars_ago"].iat[i])
        span_a_lead_slope = _safe(df["_span_a_lead_slope5"].iat[i])
        if not (
            twist_bars is not None and twist_bars <= 3
            and df["close"].iat[i] > max(df["span_a"].iat[i], df["span_b"].iat[i])
            and df["span_a_lead"].iat[i] > df["span_b_lead"].iat[i]
            and (span_a_lead_slope or 0) > 0
            and bull_score >= 11
        ):
            return None
        hosoda = get_hosoda_state(df, i)
        return {
            "signal_type": 6,
            "symbol": symbol, "timeframe": tf,
            "fired_at": str(df.index[i]),
            "entry_price": float(df["close"].iat[i]),
            "bull_score": bull_score,
            "cloud_state": "ABOVE",
            "signal_metadata": {
                "bars_since_twist": int(twist_bars),
                "cloud_thickness_pct": _safe(df["_cloud_thickness_pct"].iat[i]),
            },
            **hosoda, "is_backfill": is_backfill,
        }
    except Exception:
        return None


def _detect_signal_7_sub(df: pd.DataFrame, symbol: str, tf: str, bull_score: int,
                          subtype: str, is_backfill: bool, _bar_i: int = -1) -> Optional[dict]:
    """Shared logic for Signal 7 sub-types (7a/7b/7c/7d)."""
    i = len(df) - 1 if _bar_i < 0 else _bar_i
    if i < 5:
        return None
    close = float(df["close"].iat[i])
    cloud_top = float(df["_cloud_top"].iat[i])

    # Common: must be above cloud
    if close <= cloud_top or bull_score < 13:
        return None

    level_price: Optional[float] = None
    distance_pct: Optional[float] = None
    level_slope: str = "FLAT"
    extra_meta: dict = {}

    try:
        if subtype == "7a":
            tk = float(df["tk"].iat[i])
            dist = (close - tk) / tk * 100 if tk else None
            slope_val = _safe(df["_tk_slope5"].iat[i]) or 0
            if dist is None or not (0 <= dist <= 2.0) or slope_val < -0.3:
                return None
            level_price, distance_pct = tk, dist
            level_slope = "RISING" if slope_val > 0.1 else ("FALLING" if slope_val < -0.1 else "FLAT")

        elif subtype == "7b":
            kj = float(df["kj"].iat[i])
            dist = (close - kj) / kj * 100 if kj else None
            slope_val = _safe(df["_kj_slope5"].iat[i]) or 0
            if dist is None or not (0 <= dist <= 2.0) or slope_val < -0.3:
                return None
            level_price, distance_pct = kj, dist
            level_slope = "RISING" if slope_val > 0.1 else ("FALLING" if slope_val < -0.1 else "FLAT")

        elif subtype == "7c":
            dist = _safe(df["_cloud_top_distance_pct"].iat[i])
            if dist is None or not (0 <= dist <= 2.0):
                return None
            if not (df["span_a_lead"].iat[i] > df["span_b_lead"].iat[i]):
                return None
            level_price, distance_pct = cloud_top, dist

        elif subtype == "7d":
            cloud_bot = float(df["_cloud_bottom"].iat[i])
            dist = _safe(df["_cloud_bottom_distance_pct"].iat[i])
            thick = _safe(df["_cloud_thickness_pct"].iat[i]) or 0
            if dist is None or not (0 <= dist <= 2.0) or thick < 2.0:
                return None
            level_price, distance_pct = cloud_bot, dist
            extra_meta["cloud_thickness_pct"] = thick

        if level_price is None:
            return None

        # Bounce: close >= level_price * 0.99
        if close < level_price * 0.99:
            return None

        hosoda = get_hosoda_state(df, i)
        return {
            "signal_type": 7,
            "signal_subtype": subtype,
            "symbol": symbol, "timeframe": tf,
            "fired_at": str(df.index[i]),
            "entry_price": close,
            "bull_score": bull_score,
            "cloud_state": "ABOVE",
            "signal_metadata": {
                "level_type": {"7a": "TK", "7b": "KJ", "7c": "CLOUD_TOP", "7d": "CLOUD_BOTTOM"}[subtype],
                "distance_pct": distance_pct,
                "level_slope": level_slope,
                "bull_score": bull_score,
                **extra_meta,
            },
            **hosoda, "is_backfill": is_backfill,
        }
    except Exception:
        return None


def detect_signal_7a(df, symbol, tf, bull_score, is_backfill=False, _bar_i=-1):
    """Signal 7a — TK retest."""
    return _detect_signal_7_sub(df, symbol, tf, bull_score, "7a", is_backfill, _bar_i)


def detect_signal_7b(df, symbol, tf, bull_score, is_backfill=False, _bar_i=-1):
    """Signal 7b — KJ retest."""
    return _detect_signal_7_sub(df, symbol, tf, bull_score, "7b", is_backfill, _bar_i)


def detect_signal_7c(df, symbol, tf, bull_score, is_backfill=False, _bar_i=-1):
    """Signal 7c — Cloud top retest."""
    return _detect_signal_7_sub(df, symbol, tf, bull_score, "7c", is_backfill, _bar_i)


def detect_signal_7d(df, symbol, tf, bull_score, is_backfill=False, _bar_i=-1):
    """Signal 7d — Cloud bottom retest (CRITICAL)."""
    return _detect_signal_7_sub(df, symbol, tf, bull_score, "7d", is_backfill, _bar_i)


def detect_signal_9(df: pd.DataFrame, symbol: str, tf: str, bull_score: int,
                    is_backfill: bool = False, _bar_i: int = -1) -> Optional[dict]:
    """Signal 9 — Chikou S/R Break and Retest. Requires chikou_levels table to be populated."""
    i = len(df) - 1 if _bar_i < 0 else _bar_i
    if i < 26:
        return None
    try:
        close = float(df["close"].iat[i])
        if close <= max(float(df["span_a"].iat[i]), float(df["span_b"].iat[i])):
            return None
        if bull_score < 11:
            return None

        conn = sqlite3.connect(DB_PATH)
        levels = conn.execute(
            """
            SELECT level_price, significance_score, touch_count, duration_bars
            FROM chikou_levels
            WHERE symbol = ? AND timeframe = ?
              AND (significance_score >= 20 OR touch_count >= 3)
              AND level_price < ?
            ORDER BY ABS(level_price - ?) ASC
            LIMIT 5
            """,
            (symbol, tf, close, close),
        ).fetchall()
        conn.close()

        if not levels:
            return None

        for lp, sig_score, touch_count, duration_bars in levels:
            dist_pct = (close - lp) / lp * 100
            if not (0 <= dist_pct <= 2.0):
                continue
            if close < lp * 0.99:
                continue

            # Verify breakout within last 20 bars
            broke_above_bars = 999
            for j in range(1, min(21, i)):
                prev_close = float(df["close"].iat[i - j])
                if prev_close <= lp:
                    broke_above_bars = j
                    break
            if broke_above_bars > 20:
                continue

            hosoda = get_hosoda_state(df, i)
            return {
                "signal_type": 9,
                "symbol": symbol, "timeframe": tf,
                "fired_at": str(df.index[i]),
                "entry_price": close,
                "bull_score": bull_score,
                "cloud_state": "ABOVE",
                "signal_metadata": {
                    "level_price": lp,
                    "significance_score": sig_score,
                    "touch_count": touch_count,
                    "duration_bars": duration_bars,
                    "bars_since_breakout": broke_above_bars,
                    "distance_pct": round(dist_pct, 3),
                },
                **hosoda, "is_backfill": is_backfill,
            }
    except Exception:
        return None
    return None


# ── Onset-detection helpers ───────────────────────────────────────────────────

_TF_SECS = {"1d": 86400, "4h": 14400, "1w": 604800}


def _db_onset_blocked(
    signal_type: int, symbol: str, tf: str,
    current_ts: float, tf_secs: int,
    current_price: float = 0.0,
) -> bool:
    """Query DB for most recent instance of (type, symbol, tf).

    Returns True (block) when:
      - status=OPEN and fired < 60 bars ago  (still active)
      - status=CLOSED and price hasn't displaced ≥5% from last entry
        (same zone lingering — not a genuine new setup)
        with a hard minimum 3-bar cooldown to prevent same-bar duplicates
    """
    try:
        conn = sqlite3.connect(DB_PATH)
        row = conn.execute(
            """SELECT status, fired_at, exit_bar, exit_timestamp, entry_price
               FROM signal_log
               WHERE signal_type = ? AND symbol = ? AND timeframe = ?
               ORDER BY fired_at DESC LIMIT 1""",
            (signal_type, symbol, tf),
        ).fetchone()
        conn.close()
        if row is None:
            return False
        status, fired_at_str, exit_bar, exit_ts_str, entry_price = row
        fired_ts = datetime.fromisoformat(fired_at_str).timestamp()

        if status == "OPEN":
            return (current_ts - fired_ts) / tf_secs < 60

        # CLOSED — price displacement gate
        # Hard minimum: 3-bar cooldown regardless of price
        if exit_ts_str:
            exit_ts = datetime.fromisoformat(exit_ts_str).timestamp()
        elif exit_bar is not None:
            exit_ts = fired_ts + exit_bar * tf_secs
        else:
            exit_ts = fired_ts

        bars_since_exit = (current_ts - exit_ts) / tf_secs
        if bars_since_exit < 3:
            return True  # always block same-bar / immediate re-fires

        # Price displacement check: allow re-fire only if price moved ≥5% away
        # from the last entry (genuine new setup) — otherwise it's the same zone
        if current_price > 0 and entry_price and entry_price > 0:
            displacement = abs(current_price - entry_price) / entry_price * 100
            if displacement < 5.0:
                return True  # same zone — block

        return False
    except Exception:
        return False


# ── Main entry point ──────────────────────────────────────────────────────────

def detect_all_signals(
    df: pd.DataFrame, symbol: str, tf: str,
    bull_score: int, is_backfill: bool = False,
    _blocked_types: "set | None" = None,
    _bar_i: int = -1,
) -> list[dict]:
    """Run all detectors and return list of signal dicts that fired.

    Onset-detection gate prevents re-firing the same signal type on consecutive
    bars or before a cooldown period has elapsed.

    _blocked_types — set of signal_type ints to suppress (supplied by run_backfill
                     from its in-memory active-signal tracker).  When None and
                     is_backfill=False, the gate queries the DB directly (live scan).
    _bar_i — explicit bar index; pass the full df and this avoids any slicing.
              Defaults to len(df)-1 when -1.
    """
    detectors = [
        detect_signal_1, detect_signal_2, detect_signal_3,
        detect_signal_4, detect_signal_5, detect_signal_6,
        detect_signal_7a, detect_signal_7b, detect_signal_7c, detect_signal_7d,
        detect_signal_9,
    ]
    results = []
    i = len(df) - 1 if _bar_i < 0 else _bar_i
    if i < 1:
        return results

    tf_secs = _TF_SECS.get(tf, 86400)
    current_ts = float(pd.Timestamp(df.index[i]).timestamp())

    for fn in detectors:
        try:
            result = fn(df, symbol, tf, bull_score, is_backfill, _bar_i=i)
            if result:
                sig_type = result["signal_type"]

                # ── Onset-detection gate ──────────────────────────────────
                if _blocked_types is not None:
                    # Backfill mode: caller manages the active-signal state
                    if sig_type in _blocked_types:
                        continue
                elif not is_backfill:
                    # Live scan: query DB with current price for displacement gate
                    current_price = float(df["close"].iat[i])
                    if _db_onset_blocked(sig_type, symbol, tf, current_ts, tf_secs, current_price):
                        continue
                # (is_backfill=True with _blocked_types=None → no gate; shouldn't occur)

                # Build type key: "7a", "7b" etc for Signal 7 sub-types, plain "1"–"9" otherwise
                subtype = result.get("signal_subtype") or ""
                type_str = str(result["signal_type"])
                # subtype stores "7a"/"7b"/…; strip the leading digit so ID is "7a" not "77a"
                letter = subtype[len(type_str):] if subtype.startswith(type_str) else subtype
                type_key = type_str + letter
                result["signal_id"] = make_signal_id(
                    type_key, symbol, tf, current_ts,
                )
                results.append(result)
        except Exception:
            pass
    return results
