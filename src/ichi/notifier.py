"""Real-time ntfy.sh push notifications.

Three alert tracks (validated on 9k+ backfill signals):
  CONFIRMED   — 1d, T1 or T2, BTC above cloud        → priority 4 (buzz)
  RECOVERY    — 1d, chikou_ok, QS≥60, BTC below/inside → priority 4 (buzz)
  4H-QUALITY  — 4h, T1, bull_score≥16                → priority 4 (buzz)
  WATCHLIST   — E2E entries + market events (twists/retests/transitions) → priority 2 (silent)
  SUPPRESS    — everything else (T3, low-score 4h, 1w, noise) → not pushed

Flagged coins (poor historical performers) get a warning tag in the message body.
"""
from __future__ import annotations

import json
import os
import urllib.request
from datetime import datetime, timezone, timedelta
from pathlib import Path

_NTFY_URL   = "https://ntfy.sh"
_STATE_PATH = Path(__file__).resolve().parents[2] / "data" / "notif_state.json"

# ── Dynamic per-track track records (realized exit_return, cached) ─────────────
# Quotes win-rate + median (the honest "typical" outcome) in alerts, refreshed
# from the journal so the numbers never go stale. Filters mirror the production
# track definitions (and main.py's dashboard filters).
_TRACK_STATS_PATH = Path(__file__).resolve().parents[2] / "data" / "track_stats.json"
_TRACK_STATS_TTL  = 12 * 3600   # recompute at most every 12h
_TRACK_STAT_FILTERS = {
    "CONFIRMED":   "timeframe='1d' AND tier IN (1,2) AND btc_regime='above'",
    "RECOVERY":    "timeframe='1d' AND chikou_ok=1 AND quality_score>=60 AND btc_regime IN ('below','inside')",
    "4H_QUALITY":  "timeframe='4h' AND tier=1 AND bull_score>=16",
    "CHOP_BOUNCE": "signal_type=10 AND timeframe='1d' AND btc_regime='inside'",
}


def _refresh_track_stats() -> dict:
    """Recompute realized-exit track records from the journal and cache them."""
    import time
    from ichi.signal.db import get_conn
    out: dict = {"updated_at": time.time()}
    conn = get_conn()
    try:
        with conn.cursor() as cur:
            for _name, _filt in _TRACK_STAT_FILTERS.items():
                cur.execute(
                    "SELECT count(*), avg((exit_return>0)::int)*100, "
                    "percentile_cont(0.5) within group (order by exit_return), "
                    "avg(exit_return) FROM signal_log "
                    "WHERE status='CLOSED' AND exit_return IS NOT NULL AND " + _filt)
                _n, _win, _med, _mean = cur.fetchone()
                out[_name] = {"n": int(_n or 0), "win": round(float(_win or 0)),
                              "median": round(float(_med or 0), 1),
                              "mean": round(float(_mean or 0), 1)}
    finally:
        conn.close()
    try:
        _TRACK_STATS_PATH.parent.mkdir(parents=True, exist_ok=True)
        _TRACK_STATS_PATH.write_text(json.dumps(out))
    except Exception:
        pass
    return out


def _track_stats() -> dict:
    """Cached track stats; refresh if older than the TTL. Never raises."""
    import time
    try:
        if _TRACK_STATS_PATH.exists():
            d = json.loads(_TRACK_STATS_PATH.read_text())
            if time.time() - float(d.get("updated_at", 0)) < _TRACK_STATS_TTL:
                return d
    except Exception:
        pass
    try:
        return _refresh_track_stats()
    except Exception:
        try:
            return json.loads(_TRACK_STATS_PATH.read_text())
        except Exception:
            return {}


def _stat_line(track: str) -> str:
    """Honest one-liner: win-rate + median (typical), noting the tail skew."""
    s = _track_stats().get(track) or {}
    if not s.get("n"):
        return ""
    return (f"Track record (n={s['n']}): {s['win']:.0f}% win · "
            f"{s['median']:+.1f}% typical · avg skewed up by big winners")

NTFY_TOPIC = os.environ.get("NTFY_TOPIC", "ichi-joe")

SIGNAL_NAMES = {
    1: "Sanyaku", 2: "Bal.Breakout", 3: "KJ Retest",
    4: "E2E",     5: "Twist",        6: "Cloud Curl",
    7: "4-Level", 9: "Chikou",
}

_TIER_LABELS = {1: "T1", 2: "T2", 3: "T3"}


# ── ntfy push ─────────────────────────────────────────────────────────────────

def _push(title: str, message: str, tag: str = "bell", priority: int = 3) -> None:
    data = json.dumps({
        "topic":    NTFY_TOPIC,
        "title":    title,
        "message":  message,
        "tags":     [tag],
        "priority": priority,
    }).encode()
    req = urllib.request.Request(
        _NTFY_URL, data=data,
        headers={"Content-Type": "application/json"},
    )
    try:
        urllib.request.urlopen(req, timeout=10)
    except Exception as e:
        print(f"  [ntfy] push error: {e}")


# ── State management ──────────────────────────────────────────────────────────

def _load_state() -> dict:
    if _STATE_PATH.exists():
        try:
            return json.loads(_STATE_PATH.read_text())
        except Exception:
            pass
    return {"pushed_signal_ids": {}, "pushed_events": {}, "last_signal_ts": None}


def _save_state(state: dict) -> None:
    _STATE_PATH.parent.mkdir(parents=True, exist_ok=True)
    _STATE_PATH.write_text(json.dumps(state))


def _prune_old(pushed: dict, max_age_hours: int = 48) -> dict:
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


# ── Track classification ──────────────────────────────────────────────────────

def _classify_track(sig: dict, filt: dict) -> str:
    """Return CONFIRMED / RECOVERY / 4H_QUALITY / WATCHLIST / SUPPRESS."""
    tf         = sig.get("timeframe", "")
    sig_type   = sig.get("signal_type")
    qs         = float(sig.get("quality_score") or 0)
    bull_score = int(sig.get("bull_score") or 0)
    tier       = filt.get("tier")
    chikou_ok  = filt.get("chikou_ok", False)
    btc_regime = filt.get("btc_regime", "unknown")

    if tf == "1d" and tier in (1, 2) and btc_regime == "above":
        return "CONFIRMED"
    if tf == "1d" and chikou_ok and qs >= 60 and btc_regime in ("below", "inside"):
        return "RECOVERY"
    if tf == "4h" and tier == 1 and bull_score >= 16:
        return "4H_QUALITY"
    # Signal 10 (RSI Bounce) — chop-only mean-reversion overlay (1d, BTC inside cloud)
    if sig_type == 10 and tf == "1d" and btc_regime == "inside" and not filt.get("skip", False):
        return "CHOP_BOUNCE"
    # E2E that bypassed regime gate but BTC is against it → watchlist
    if sig_type == 4:
        return "WATCHLIST"
    return "SUPPRESS"


# ── Helpers ───────────────────────────────────────────────────────────────────

def _stop_info(entry_price: float, atr: float | None, timeframe: str = "4h") -> str:
    from ichi.signal.jobs import _TRAIL_ATR_MULT_BY_TF, _TRAIL_ATR_MULT_DEFAULT
    mult = _TRAIL_ATR_MULT_BY_TF.get(timeframe, _TRAIL_ATR_MULT_DEFAULT)
    if not atr or atr <= 0:
        return "stop: n/a"
    stop = entry_price - mult * atr
    pct  = (stop - entry_price) / entry_price * 100
    return f"stop ${stop:,.4g} ({pct:+.1f}%)"


def _btc_regime_line() -> str | None:
    from ichi.signal.filters import get_btc_1d_regime
    regime = get_btc_1d_regime()
    if regime == "below":
        return "⚠️ BTC below cloud"
    if regime == "inside":
        return "⚠️ BTC inside cloud"
    return None


# ── New signal notifications ──────────────────────────────────────────────────

def push_new_signals(since: str | None = None) -> None:
    """Push qualifying signals to ntfy. Only CONFIRMED, RECOVERY, and 4H-QUALITY
    tracks generate alerts. Everything else is silently marked as handled."""
    import psycopg2
    import psycopg2.extras
    from ichi.signal.db import get_conn
    from ichi.signal.filters import FLAGGED_COINS

    state      = _load_state()
    pushed_ids = _prune_old(state.get("pushed_signal_ids", {}))
    last_ts    = since or state.get("last_signal_ts") or "2020-01-01T00:00:00+00:00"
    now_str    = datetime.now(timezone.utc).isoformat()

    try:
        conn = get_conn()
        with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
            cur.execute("""
                SELECT signal_id, symbol, signal_type, timeframe,
                       entry_price, bull_score, quality_score, fired_at, signal_metadata
                FROM signal_log
                WHERE status = 'OPEN'
                  AND is_backfill = 0
                  AND fired_at::timestamptz > %s::timestamptz
                ORDER BY quality_score DESC NULLS LAST, fired_at DESC
            """, (last_ts,))
            new_sigs = [dict(r) for r in cur.fetchall()]

            cur.execute("""
                SELECT signal_id, symbol, signal_type, timeframe,
                       exit_return, exit_condition, exit_bar,
                       entry_price, exit_price, bull_score, exit_timestamp
                FROM signal_log
                WHERE status = 'CLOSED'
                  AND is_backfill = 0
                  AND exit_timestamp::timestamptz > %s::timestamptz
                  AND exit_return IS NOT NULL
                ORDER BY exit_return DESC
            """, (last_ts,))
            closed_sigs = [dict(r) for r in cur.fetchall()]
        conn.close()
    except Exception as exc:
        print(f"  [ntfy] db error: {exc}")
        return

    alerted = suppressed = watchlisted = closed_pushed = 0

    for s in new_sigs:
        sig_id = s["signal_id"]
        if sig_id in pushed_ids:
            continue

        sym      = s["symbol"].replace("USDT", "")
        name     = SIGNAL_NAMES.get(s["signal_type"], f"S{s['signal_type']}")
        tf       = s["timeframe"]
        qs       = float(s.get("quality_score") or 0)
        entry    = float(s["entry_price"])
        is_flagged = s["symbol"] in FLAGGED_COINS

        # Read pre-computed filter metadata
        filt: dict = {}
        atr: float | None = None
        try:
            meta = json.loads(s["signal_metadata"] or "{}")
            atr  = meta.get("atr") or meta.get("atr14")
            filt = meta.get("filter") or {}
        except Exception:
            meta = {}

        # Fallback if filter metadata missing
        if not filt:
            from ichi.signal.filters import get_btc_1d_regime
            btc_r = get_btc_1d_regime()
            tier  = 1 if (qs >= 60 and s.get("hosoda_active")) else (2 if qs >= 60 else 3)
            filt  = {
                "tier": tier, "btc_regime": btc_r,
                "chikou_ok": False, "skip": False,
                "priority_boost": False, "priority_reduce": False,
                "twist": None, "eth_boost": False, "cloud_thickness": 0.0,
            }

        if filt.get("skip"):
            pushed_ids[sig_id] = now_str
            suppressed += 1
            continue

        track = _classify_track(s, filt)

        if track == "SUPPRESS":
            pushed_ids[sig_id] = now_str
            suppressed += 1
            continue

        tier           = filt.get("tier")
        chikou_ok      = filt.get("chikou_ok", False)
        priority_boost = filt.get("priority_boost", False)
        priority_reduce = filt.get("priority_reduce", False)
        thickness      = filt.get("cloud_thickness", 0.0)
        twist          = filt.get("twist")
        eth_boost      = filt.get("eth_boost", False)
        btc_regime     = filt.get("btc_regime", "unknown")

        if track == "WATCHLIST":
            title = f"👀 WATCH ONLY · {sym} · E2E · {tf}"
            body_lines = [
                "⏳ Do NOT trade yet — BTC is not in bull position",
                f"Price entering cloud — watch for it to break above",
                f"Entry zone: ${entry:,.4g}  |  Quality: {qs:.0f}/100",
                "When BTC recovers above cloud this may become a buy signal",
            ]
            if is_flagged:
                body_lines.append("⚠️ Caution: historically weak coin — reduce size if you trade")
            _push(title, "\n".join(body_lines), tag="eyes", priority=2)
            pushed_ids[sig_id] = now_str
            watchlisted += 1
            continue

        if track == "CHOP_BOUNCE":
            title = f"🔵 DIP BUY · {sym} · 1D · RSI Bounce"
            body_lines = [
                "👉 Oversold bounce inside an uptrend — mean-reversion setup",
                f"Entry: ${entry:,.4g}  |  {_stop_info(entry, atr, tf)}",
                "Works while BTC ranges (chop).",
            ]
            _sl = _stat_line("CHOP_BOUNCE")
            if _sl:
                body_lines.append(_sl)
            if is_flagged:
                body_lines.append("⚠️ Caution: historically weak coin — reduce size")
            _push(title, "\n".join(body_lines), tag="large_blue_circle", priority=3)
            pushed_ids[sig_id] = now_str
            alerted += 1
            continue

        # ── CONFIRMED / RECOVERY / 4H_QUALITY ─────────────────────────────────
        tier_str = _TIER_LABELS.get(tier, "")
        stop_line = _stop_info(entry, atr, tf)

        if track == "CONFIRMED":
            title = f"🟢 BUY SIGNAL · {sym} · {tf.upper()} {tier_str}"
            action = "👉 Enter a position — BTC is in bull market, setup fully confirmed"
            context_lines = [_stat_line("CONFIRMED")]
        elif track == "RECOVERY":
            title = f"🚀 ALT SIGNAL · {sym} · {tf.upper()}"
            action = "👉 Enter position — this alt is moving despite weak BTC"
            context_lines = ["Higher risk, bigger potential.", _stat_line("RECOVERY")]
        else:  # 4H_QUALITY
            title = f"⚡ BUY SIGNAL · {sym} · 4H {tier_str}"
            action = "👉 Enter position — strong 4h setup (days, not weeks)"
            context_lines = [_stat_line("4H_QUALITY")]

        body_lines = [
            action,
            f"Entry: ${entry:,.4g}  |  {stop_line}",
            f"Quality: {qs:.0f}/100",
        ]

        if chikou_ok:
            body_lines.append("✓ Momentum clear — no resistance above")
        if float(thickness or 0) >= 5.0:
            body_lines.append(f"✓ Cloud solid ({thickness:.1f}% thick) — strong support")
        if twist and twist.get("bucket") == "bearish_6_10":
            body_lines.append("⚡ Cloud recently turned bullish — good timing")
        elif twist and twist.get("bucket") == "bullish_0_5":
            body_lines.append("↗ Cloud just flipped — early, slightly weaker setup")
        if eth_boost:
            body_lines.append("⚡ ETH consolidating — alt season conditions")
        if btc_regime != "above":
            body_lines.append(f"⚠️ BTC {btc_regime} cloud — higher risk than normal")
        if is_flagged:
            body_lines.append("⚠️ Caution: historically weak coin — reduce position size")

        body_lines += [x for x in context_lines if x]

        priority = 4 if track in ("CONFIRMED", "4H_QUALITY") else 3
        if priority_boost:
            priority = min(priority + 1, 5)
        if priority_reduce:
            priority = max(priority - 1, 2)

        _push(title, "\n".join(body_lines), tag="bell", priority=priority)
        pushed_ids[sig_id] = now_str
        alerted += 1

    # ── Closures ──────────────────────────────────────────────────────────────
    for s in closed_sigs:
        sig_id = f"close:{s['signal_id']}"
        if sig_id in pushed_ids:
            continue

        sym   = s["symbol"].replace("USDT", "")
        name  = SIGNAL_NAMES.get(s["signal_type"], f"S{s['signal_type']}")
        tf    = s["timeframe"]
        ret   = float(s["exit_return"])
        bars  = s["exit_bar"] or "?"
        emoji = "✅" if ret > 0 else "❌"

        exit_labels = {
            "TRAIL_STOP_4ATR": "trailing stop hit",
            "TRAIL_STOP_6ATR": "trailing stop hit",
            "COMBO_TIGHT_STOP": "trailing stop hit",
            "TIMEOUT": "timed out — no movement",
            "PROFIT_TARGET": "profit target hit",
        }
        reason = exit_labels.get(s["exit_condition"] or "", s["exit_condition"] or "")

        if ret > 0:
            title = f"💰 TRADE CLOSED +{ret:.1f}% · {sym} {tf}"
            body  = f"Profit taken — {reason} after {bars} bars\nNo action needed"
        else:
            title = f"🛑 TRADE CLOSED {ret:+.1f}% · {sym} {tf}"
            body  = f"Loss limited — {reason} after {bars} bars\nNormal — the wins make it back"
        if s.get("exit_price") and s.get("entry_price"):
            body += f"\n${float(s['entry_price']):,.4g} → ${float(s['exit_price']):,.4g}"

        _push(title, body,
              tag="chart_with_upwards_trend" if ret > 0 else "chart_with_downwards_trend",
              priority=3)
        pushed_ids[sig_id] = now_str
        closed_pushed += 1

    total = alerted + suppressed + watchlisted + closed_pushed
    if total:
        print(f"  [ntfy] {alerted} alerts  {watchlisted} watchlist  {suppressed} suppressed  {closed_pushed} closures")
    else:
        print("  [ntfy] no new signal activity")

    state["pushed_signal_ids"] = pushed_ids
    state["last_signal_ts"]    = now_str
    _save_state(state)


# ── Market events — individual watchlist pushes ───────────────────────────────

def push_events(events: dict) -> None:
    """Push kumo twists, retests, and cloud transitions as individual
    low-priority watchlist notifications. Each event gets its own push."""
    state   = _load_state()
    pushed  = _prune_old(state.get("pushed_events", {}))
    now_str = datetime.now(timezone.utc).isoformat()
    count   = 0

    for r in events.get("transition_events", []):
        direction = r.get("direction", "")
        key = f"trans:{r.get('symbol')}:{r.get('timeframe')}:{direction}"
        if key in pushed:
            continue
        sym   = str(r.get("symbol", "")).replace("USDT", "")
        tf    = r.get("timeframe", "")
        emoji = "🟢" if direction == "ABOVE" else "🔴"
        action = "Watch for BUY SIGNALS in the coming days" if direction == "ABOVE" else "Avoid new longs — market turned bearish"
        _push(
            f"📊 REGIME CHANGE · {sym} {tf} {'above' if direction == 'ABOVE' else 'below'} cloud",
            f"Background info — no trade needed right now\n{action}",
            tag="chart_with_upwards_trend" if direction == "ABOVE" else "chart_with_downwards_trend",
            priority=2,
        )
        pushed[key] = now_str
        count += 1

    for r in events.get("kumo_twists", []):
        bars = r.get("bars_until_twist", 99)
        if bars > 5:
            continue
        direction = r.get("twist_direction", "")
        key = f"twist:{r.get('symbol')}:{r.get('timeframe')}:{direction}"
        if key in pushed:
            continue
        sym   = str(r.get("symbol", "")).replace("USDT", "")
        tf    = r.get("timeframe", "")
        emoji = "📈" if direction == "BULL_TWIST" else "📉"
        bull = direction == "BULL_TWIST"
        _push(
            f"📊 CLOUD FLIPPING · {sym} {tf} in {bars} bars",
            f"Background info — no trade needed yet\n"
            f"Ichimoku cloud about to turn {'bullish — watch for a BUY SIGNAL to follow' if bull else 'bearish — avoid new longs'}",
            tag="eyes",
            priority=2,
        )
        pushed[key] = now_str
        count += 1

    for r in events.get("retest_alerts", []):
        rtype = r.get("retest_type", "")
        key = f"retest:{r.get('symbol')}:{r.get('timeframe')}:{rtype}"
        if key in pushed:
            continue
        sym = str(r.get("symbol", "")).replace("USDT", "")
        tf  = r.get("timeframe", "")
        level = rtype.replace("_", " ").title()
        _push(
            f"🔄 PULLBACK · {sym} {tf} retesting {level}",
            f"Background info — no trade needed yet\n"
            f"Price pulling back to a key Ichimoku level\n"
            f"If it holds here a BUY SIGNAL may follow",
            tag="eyes",
            priority=2,
        )
        pushed[key] = now_str
        count += 1

    if count:
        print(f"  [ntfy] pushed {count} individual watchlist event(s)")

    state["pushed_events"] = pushed
    _save_state(state)


# ── Confluence alerts ─────────────────────────────────────────────────────────

def push_confluence(recent_window_minutes: int = 25) -> None:
    """Fire when the same coin signals on 2+ timeframes — highest-conviction setups."""
    import psycopg2.extras
    from ichi.signal.db import get_conn

    state      = _load_state()
    pushed_ids = _prune_old(state.get("pushed_signal_ids", {}))
    now_str    = datetime.now(timezone.utc).isoformat()
    cutoff     = (datetime.now(timezone.utc) - timedelta(minutes=recent_window_minutes)).isoformat()

    try:
        conn = get_conn()
        with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
            cur.execute("""
                SELECT symbol, timeframe, signal_type, bull_score, quality_score, entry_price, signal_id
                FROM signal_log
                WHERE status = 'OPEN'
                  AND is_backfill = 0
                  AND fired_at::timestamptz >= %s::timestamptz
                ORDER BY symbol, fired_at DESC
            """, (cutoff,))
            recent = [dict(r) for r in cur.fetchall()]
        conn.close()
    except Exception as exc:
        print(f"  [ntfy] confluence db error: {exc}")
        return

    by_sym: dict[str, list] = {}
    for r in recent:
        by_sym.setdefault(r["symbol"], []).append(r)

    fired = 0
    for symbol, sigs in by_sym.items():
        timeframes = list({s["timeframe"] for s in sigs})
        if len(timeframes) < 2:
            continue

        key = f"confluence:{symbol}:{','.join(sorted(timeframes))}"
        if key in pushed_ids:
            continue

        sym    = symbol.replace("USDT", "")
        tf_str = " + ".join(sorted(timeframes))
        names  = " / ".join(SIGNAL_NAMES.get(s["signal_type"], f"S{s['signal_type']}") for s in sigs)
        avg_qs = sum(s.get("quality_score") or 0.0 for s in sigs) / len(sigs)
        entry  = float(sigs[0]["entry_price"])

        body = (
            f"👉 Same coin signaling on {len(timeframes)} timeframes at once — rare and strong\n"
            f"Consider a LARGER position than normal\n"
            f"Entry: ${entry:,.4g}  |  Avg quality: {avg_qs:.0f}/100\n"
            f"Signals: {names}  ({tf_str})"
        )
        regime_line = _btc_regime_line()
        if regime_line:
            body += f"\n{regime_line}"

        _push(f"🔥 STRONG BUY · {sym} · {tf_str}", body, tag="fire", priority=5)
        pushed_ids[key] = now_str
        fired += 1

    if fired:
        print(f"  [ntfy] pushed {fired} confluence alert(s)")

    state["pushed_signal_ids"] = pushed_ids
    _save_state(state)


# ── Market regime helper ──────────────────────────────────────────────────────

def _btc_regime_line() -> str | None:
    from ichi.signal.filters import get_btc_1d_regime
    regime = get_btc_1d_regime()
    if regime == "below":
        return "⚠️ BTC below cloud — long signals are riskier"
    if regime == "inside":
        return "⚠️ BTC inside cloud — mixed regime"
    return None


# ── Morning brief ─────────────────────────────────────────────────────────────

def push_morning_brief() -> None:
    """Daily 8am UTC summary: open positions, unrealised P&L, biggest mover."""
    import psycopg2.extras
    from ichi.signal.db import get_conn

    state = _load_state()
    today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    if state.get("morning_brief_date") == today:
        return

    try:
        conn = get_conn()
        with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
            cur.execute("""
                SELECT symbol, timeframe, signal_type, entry_price,
                       mfe, mae, duration_bars, quality_score
                FROM signal_log
                WHERE status = 'OPEN' AND is_backfill = 0
                ORDER BY quality_score DESC NULLS LAST, mfe DESC NULLS LAST
            """)
            open_sigs = [dict(r) for r in cur.fetchall()]

            cur.execute("""
                SELECT exit_return, exit_condition
                FROM signal_log
                WHERE status = 'CLOSED'
                  AND is_backfill = 0
                  AND exit_timestamp::timestamptz >= NOW() - INTERVAL '24 hours'
                  AND exit_return IS NOT NULL
            """)
            closed_24h = [dict(r) for r in cur.fetchall()]
        conn.close()
    except Exception as exc:
        print(f"  [ntfy] morning brief db error: {exc}")
        return

    n_open = len(open_sigs)
    if n_open == 0 and not closed_24h:
        state["morning_brief_date"] = today
        _save_state(state)
        return

    mfe_vals = [s["mfe"] for s in open_sigs if s.get("mfe") is not None]
    mae_vals = [s["mae"] for s in open_sigs if s.get("mae") is not None]

    lines = [f"You have {n_open} open trades — no action needed unless one closes"]
    if mfe_vals:
        lines.append(f"Avg best gain reached so far: +{sum(mfe_vals)/len(mfe_vals):.1f}%")
    if mae_vals:
        lines.append(f"Avg deepest dip: {sum(mae_vals)/len(mae_vals):.1f}% (normal, stop will protect you)")

    if open_sigs and open_sigs[0].get("mfe") is not None:
        best = open_sigs[0]
        sym  = best["symbol"].replace("USDT", "")
        lines.append(f"Best open trade: {sym} +{best['mfe']:.1f}% from entry")

    if closed_24h:
        returns = [r["exit_return"] for r in closed_24h if r["exit_return"] is not None]
        winners = [r for r in returns if r > 0]
        lines.append(f"\nYesterday: {len(closed_24h)} trade(s) closed")
        if returns:
            lines.append(f"  {len(winners)} wins, {len(returns)-len(winners)} losses ({len(winners)/len(returns)*100:.0f}% win rate)")
            lines.append(f"  Average return: {sum(returns)/len(returns):+.1f}%")

    regime_line = _btc_regime_line()
    if regime_line:
        lines.append(f"\n{regime_line} — be cautious with new entries")

    _push("📋 Your positions", "\n".join(lines), tag="calendar", priority=3)
    print("  [ntfy] sent morning brief")

    state["morning_brief_date"] = today
    _save_state(state)


# ── Trail profit notifications ────────────────────────────────────────────────

def push_trail_profit(signals_in_profit: list[dict]) -> None:
    """Called when a signal's ATR trail moves above entry — free trade."""
    if not signals_in_profit:
        return

    state      = _load_state()
    pushed_ids = _prune_old(state.get("pushed_signal_ids", {}))
    now_str    = datetime.now(timezone.utc).isoformat()
    fired      = 0

    for s in signals_in_profit:
        key = f"trail_profit:{s['signal_id']}"
        if key in pushed_ids:
            continue

        sym        = s["symbol"].replace("USDT", "")
        name       = SIGNAL_NAMES.get(s["signal_type"], f"S{s['signal_type']}")
        tf         = s["timeframe"]
        entry      = s["entry_price"]
        trail_stop = s["trail_stop"]
        locked_pct = (trail_stop - entry) / entry * 100

        _push(
            f"🔒 STOP SECURED · {sym} {tf}",
            f"Your stop loss is now above your entry price\n"
            f"Stop locked at ${trail_stop:,.4g} — {locked_pct:.1f}% profit guaranteed\n"
            f"Entry was ${entry:,.4g} — you CANNOT lose on this trade now\n"
            f"No action needed — let it run",
            tag="lock",
            priority=3,
        )
        pushed_ids[key] = now_str
        fired += 1

    if fired:
        print(f"  [ntfy] pushed {fired} trail-in-profit alert(s)")

    state["pushed_signal_ids"] = pushed_ids
    _save_state(state)
