"""Signal performance journal — reads directly from signals.db.

Shows the system's own tracked signals: entries, exits, P&L, MAE/MFE,
win rates, and score-bucket breakdowns. No manual input required.

Usage:
    ichi journal
    ichi journal --timeframe 1d
    ichi journal --signal-type 1
    ichi journal --since 2025-01-01
    ichi journal --min-score 13
    ichi journal --status CLOSED
    ichi journal --sort ret
"""
from __future__ import annotations

import math
import sqlite3
from datetime import datetime, timezone
from pathlib import Path

import click

DB_PATH = Path(__file__).resolve().parents[3] / "data" / "signals.db"

SIGNAL_NAMES = {
    1: "Sanyaku",
    2: "Bal.Break",
    3: "KJ Retest",
    4: "E2E",
    5: "Twist",
    6: "Curl",
    7: "4-Level",
    9: "Chikou",
}

EXIT_SHORT = {
    "COMBO_TIGHT_STOP":  "CT-stop",
    "TIMEOUT":           "timeout",
    "CLOUD_BREAK":       "cloud",
    "CHANDELIER_STOP":   "chandelier",
    "ATR_STOP":          "ATR",
    "PROFIT_TARGET":     "target",
    None:                "—",
}


def _db() -> sqlite3.Connection:
    if not DB_PATH.exists():
        raise click.ClickException(f"signals.db not found at {DB_PATH}")
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn


def _pct(val: float | None) -> str:
    if val is None or (isinstance(val, float) and math.isnan(val)):
        return "  —  "
    sign = "+" if val > 0 else ""
    return f"{sign}{val:.1f}%"


def _bars(val: int | None) -> str:
    return str(val) if val is not None else "—"


def _score_bucket(score: int | None) -> str:
    if score is None:
        return "unknown"
    if score <= 8:
        return "0–8"
    if score <= 12:
        return "9–12"
    if score <= 15:
        return "13–15"
    return "16–18"


# ── CLI ───────────────────────────────────────────────────────────────────────

@click.command()
@click.option("--timeframe", "-t", default=None,
              help="Filter by timeframe, e.g. 1d, 4h, 1w")
@click.option("--signal-type", "-s", "signal_type", default=None, type=int,
              help="Filter by signal type (1-9)")
@click.option("--since", default=None,
              help="Only signals fired on or after this date (YYYY-MM-DD)")
@click.option("--min-score", default=0, show_default=True,
              help="Only signals with bull_score >= this value")
@click.option("--status", default="CLOSED",
              type=click.Choice(["CLOSED", "OPEN", "ALL"], case_sensitive=False),
              show_default=True,
              help="Which signals to include")
@click.option("--sort", default="date",
              type=click.Choice(["date", "ret", "score", "dur"], case_sensitive=False),
              show_default=True,
              help="Sort detail rows by: date | ret (return) | score | dur (duration)")
@click.option("--limit", default=50, show_default=True,
              help="Max detail rows to print (0 = all)")
@click.option("--symbol", default=None,
              help="Filter to a single symbol, e.g. BTC/USDT")
def journal(
    timeframe: str | None,
    signal_type: int | None,
    since: str | None,
    min_score: int,
    status: str,
    sort: str,
    limit: int,
    symbol: str | None,
) -> None:
    """Signal performance journal.

    Reads the system's own tracked signals from signals.db and presents
    a full performance breakdown — no manual trade input needed.

    Examples:
        ichi journal
        ichi journal --timeframe 1d --min-score 13
        ichi journal --signal-type 1 --since 2025-01-01
        ichi journal --status OPEN
        ichi journal --sort ret --limit 20
    """
    conn = _db()

    # ── Build query ───────────────────────────────────────────────────────────
    where_clauses = []
    params: list = []

    status_upper = status.upper()
    if status_upper != "ALL":
        where_clauses.append("status = ?")
        params.append(status_upper)
    if timeframe:
        where_clauses.append("timeframe = ?")
        params.append(timeframe)
    if signal_type is not None:
        where_clauses.append("signal_type = ?")
        params.append(signal_type)
    if since:
        where_clauses.append("fired_at >= ?")
        params.append(since)
    if min_score > 0:
        where_clauses.append("bull_score >= ?")
        params.append(min_score)
    if symbol:
        sym = symbol.upper()
        if not sym.endswith("/USDT") and not sym.endswith("USDT"):
            sym += "/USDT"
        where_clauses.append("symbol = ?")
        params.append(sym)

    where_sql = ("WHERE " + " AND ".join(where_clauses)) if where_clauses else ""

    rows = conn.execute(f"""
        SELECT signal_id, signal_type, symbol, timeframe,
               fired_at, entry_price, exit_price, exit_return,
               exit_condition, duration_bars, bull_score,
               mae, mfe, status, cloud_state, is_backfill
        FROM signal_log
        {where_sql}
        ORDER BY fired_at DESC
    """, params).fetchall()

    conn.close()

    if not rows:
        click.echo("No signals found for the given filters.")
        return

    # ── Print header ──────────────────────────────────────────────────────────
    filters = []
    if timeframe:
        filters.append(f"TF={timeframe}")
    if signal_type:
        filters.append(f"signal={SIGNAL_NAMES.get(signal_type, signal_type)}")
    if symbol:
        filters.append(f"symbol={symbol.upper()}")
    if since:
        filters.append(f"since={since}")
    if min_score > 0:
        filters.append(f"score≥{min_score}")
    filter_str = "  " + "  ".join(filters) if filters else ""

    click.echo()
    click.echo(f"── Signal Journal ── {len(rows)} signals  [{status.upper()}]{filter_str} ──────────────────────")
    click.echo()

    # ── Detail rows ───────────────────────────────────────────────────────────
    sort_key = {
        "date": lambda r: r["fired_at"] or "",
        "ret":  lambda r: r["exit_return"] if r["exit_return"] is not None else -999,
        "score": lambda r: r["bull_score"] if r["bull_score"] is not None else -1,
        "dur":  lambda r: r["duration_bars"] if r["duration_bars"] is not None else -1,
    }[sort]
    reverse = sort in ("ret", "score", "dur")
    sorted_rows = sorted(rows, key=sort_key, reverse=reverse)

    display_rows = sorted_rows if limit == 0 else sorted_rows[:limit]

    click.echo(
        f"  {'Date':<12} {'Symbol':<10} {'TF':>3}  {'Signal':<10} "
        f"{'Score':>5}  {'Entry':>10}  {'Exit':>10}  {'Return':>7}  "
        f"{'MAE':>6}  {'MFE':>6}  {'Bars':>4}  Exit"
    )
    click.echo("  " + "─" * 107)

    for r in display_rows:
        sig_name = SIGNAL_NAMES.get(r["signal_type"], f"S{r['signal_type']}")
        date_str = (r["fired_at"] or "")[:10]
        score_str = str(r["bull_score"]) if r["bull_score"] is not None else "—"
        entry_str = f"{r['entry_price']:.4f}" if r["entry_price"] else "—"
        exit_p_str = f"{r['exit_price']:.4f}" if r["exit_price"] else "—"
        ret_str = _pct(r["exit_return"])
        mae_str = _pct(r["mae"])
        mfe_str = _pct(r["mfe"])
        bars_str = _bars(r["duration_bars"])
        exit_str = EXIT_SHORT.get(r["exit_condition"], r["exit_condition"] or "—")

        # Colour the return
        ret_col = ""
        ret_reset = ""
        if r["exit_return"] is not None:
            if r["exit_return"] > 0:
                ret_col = "\033[32m"   # green
                ret_reset = "\033[0m"
            elif r["exit_return"] < 0:
                ret_col = "\033[31m"   # red
                ret_reset = "\033[0m"

        sym_short = r["symbol"].replace("/USDT", "")

        click.echo(
            f"  {date_str:<12} {sym_short:<10} {r['timeframe']:>3}  "
            f"{sig_name:<10} {score_str:>5}  "
            f"{entry_str:>10}  {exit_p_str:>10}  "
            f"{ret_col}{ret_str:>7}{ret_reset}  "
            f"{mae_str:>6}  {mfe_str:>6}  {bars_str:>4}  {exit_str}"
        )

    if limit > 0 and len(rows) > limit:
        click.echo(f"\n  ... {len(rows) - limit} more rows (use --limit 0 to show all)")

    # ── Summary stats ─────────────────────────────────────────────────────────
    _print_summary(rows)

    # ── By signal type ────────────────────────────────────────────────────────
    _print_by_signal_type(rows)

    # ── By score bucket ───────────────────────────────────────────────────────
    closed = [r for r in rows if r["status"] == "CLOSED" and r["exit_return"] is not None]
    if closed:
        _print_by_score_bucket(closed)

    # ── By timeframe (if not filtered to one) ─────────────────────────────────
    tfs = set(r["timeframe"] for r in rows)
    if len(tfs) > 1:
        _print_by_timeframe(rows)

    # ── Best / worst ──────────────────────────────────────────────────────────
    if closed:
        _print_best_worst(closed)


# ── Display helpers ───────────────────────────────────────────────────────────

def _stats(rows: list) -> dict:
    """Compute stats dict from a list of sqlite3.Row objects."""
    closed = [r for r in rows if r["status"] == "CLOSED" and r["exit_return"] is not None]
    open_ = [r for r in rows if r["status"] == "OPEN"]
    wins = [r for r in closed if r["exit_return"] > 0]
    losses = [r for r in closed if r["exit_return"] <= 0]
    rets = [r["exit_return"] for r in closed]
    maes = [r["mae"] for r in closed if r["mae"] is not None]
    mfes = [r["mfe"] for r in closed if r["mfe"] is not None]
    durs = [r["duration_bars"] for r in closed if r["duration_bars"] is not None]

    avg_ret = sum(rets) / len(rets) if rets else None
    avg_win = sum(r["exit_return"] for r in wins) / len(wins) if wins else None
    avg_loss = sum(r["exit_return"] for r in losses) / len(losses) if losses else None
    win_rate = len(wins) / len(closed) if closed else None
    avg_mae = sum(maes) / len(maes) if maes else None
    avg_mfe = sum(mfes) / len(mfes) if mfes else None
    avg_dur = sum(durs) / len(durs) if durs else None

    wl_ratio = None
    if avg_win is not None and avg_loss is not None and avg_loss != 0:
        wl_ratio = abs(avg_win / avg_loss)

    return {
        "total": len(rows),
        "closed": len(closed),
        "open": len(open_),
        "wins": len(wins),
        "losses": len(losses),
        "win_rate": win_rate,
        "avg_ret": avg_ret,
        "avg_win": avg_win,
        "avg_loss": avg_loss,
        "wl_ratio": wl_ratio,
        "avg_mae": avg_mae,
        "avg_mfe": avg_mfe,
        "avg_dur": avg_dur,
        "best": max(rets) if rets else None,
        "worst": min(rets) if rets else None,
    }


def _print_summary(rows: list) -> None:
    s = _stats(rows)
    click.echo()
    click.echo("── Summary ──────────────────────────────────────────────────────────────────")
    click.echo(f"  Total signals :  {s['total']}  (closed: {s['closed']}, open: {s['open']})")
    if s["closed"] == 0:
        click.echo("  No closed signals to compute performance stats.")
        return

    wr_str = f"{s['win_rate']*100:.0f}%" if s["win_rate"] is not None else "—"
    ret_str = _pct(s["avg_ret"])
    win_str = _pct(s["avg_win"])
    loss_str = _pct(s["avg_loss"])
    wl_str = f"{s['wl_ratio']:.2f}" if s["wl_ratio"] is not None else "—"
    mae_str = _pct(s["avg_mae"])
    mfe_str = _pct(s["avg_mfe"])
    dur_str = f"{s['avg_dur']:.1f} bars" if s["avg_dur"] is not None else "—"
    best_str = _pct(s["best"])
    worst_str = _pct(s["worst"])

    click.echo(f"  Win rate      :  {wr_str}  ({s['wins']} wins / {s['losses']} losses)")
    click.echo(f"  Avg return    :  {ret_str}  (win: {win_str}  loss: {loss_str}  W/L: {wl_str})")
    click.echo(f"  Avg MAE/MFE   :  {mae_str} / {mfe_str}")
    click.echo(f"  Avg duration  :  {dur_str}")
    click.echo(f"  Best / Worst  :  {best_str} / {worst_str}")
    click.echo()


def _print_by_signal_type(rows: list) -> None:
    by_type: dict[int, list] = {}
    for r in rows:
        by_type.setdefault(r["signal_type"], []).append(r)

    if len(by_type) <= 1:
        return

    click.echo("── By signal type ───────────────────────────────────────────────────────────")
    click.echo(f"  {'Signal':<12} {'N':>4}  {'WR':>6}  {'AvgRet':>8}  {'AvgWin':>8}  {'AvgLoss':>9}  {'AvgDur':>7}")
    click.echo("  " + "─" * 68)
    for sig_t in sorted(by_type):
        s = _stats(by_type[sig_t])
        name = SIGNAL_NAMES.get(sig_t, f"S{sig_t}")
        wr = f"{s['win_rate']*100:.0f}%" if s["win_rate"] is not None else "—"
        dur_s = f"{s['avg_dur']:.0f}b" if s['avg_dur'] else "—"
        click.echo(
            f"  {name:<12} {s['closed']:>4}  {wr:>6}  "
            f"{_pct(s['avg_ret']):>8}  {_pct(s['avg_win']):>8}  "
            f"{_pct(s['avg_loss']):>9}  "
            f"{dur_s:>7}"
        )
    click.echo()


def _print_by_score_bucket(closed: list) -> None:
    buckets: dict[str, list] = {"0–8": [], "9–12": [], "13–15": [], "16–18": []}
    for r in closed:
        buckets[_score_bucket(r["bull_score"])].append(r)

    # Only print if we have multiple buckets with data
    filled = [k for k, v in buckets.items() if v]
    if len(filled) <= 1:
        return

    click.echo("── By score bucket (closed signals) ─────────────────────────────────────────")
    click.echo(f"  {'Bucket':<8} {'N':>4}  {'WR':>6}  {'AvgRet':>8}  {'AvgMFE':>8}  Bar")
    click.echo("  " + "─" * 50)
    for label in ["0–8", "9–12", "13–15", "16–18"]:
        rows = buckets[label]
        if not rows:
            continue
        s = _stats(rows)
        wr = f"{s['win_rate']*100:.0f}%" if s["win_rate"] is not None else "—"
        bar = "█" * int((s["win_rate"] or 0) * 16)
        click.echo(
            f"  {label:<8} {s['closed']:>4}  {wr:>6}  "
            f"{_pct(s['avg_ret']):>8}  {_pct(s['avg_mfe']):>8}  {bar}"
        )
    click.echo()


def _print_by_timeframe(rows: list) -> None:
    by_tf: dict[str, list] = {}
    for r in rows:
        by_tf.setdefault(r["timeframe"], []).append(r)

    if len(by_tf) <= 1:
        return

    click.echo("── By timeframe ─────────────────────────────────────────────────────────────")
    click.echo(f"  {'TF':<5} {'N':>4}  {'WR':>6}  {'AvgRet':>8}  {'AvgDur':>7}")
    click.echo("  " + "─" * 36)
    for tf in sorted(by_tf, key=lambda x: {"1w": 0, "1d": 1, "4h": 2}.get(x, 9)):
        s = _stats(by_tf[tf])
        wr = f"{s['win_rate']*100:.0f}%" if s["win_rate"] is not None else "—"
        dur = f"{s['avg_dur']:.0f}b" if s["avg_dur"] else "—"
        click.echo(f"  {tf:<5} {s['closed']:>4}  {wr:>6}  {_pct(s['avg_ret']):>8}  {dur:>7}")
    click.echo()


def _print_best_worst(closed: list) -> None:
    by_ret = sorted(closed, key=lambda r: r["exit_return"], reverse=True)
    top5 = by_ret[:5]
    bot5 = by_ret[-5:][::-1]

    click.echo("── Top 5 / Bottom 5 (by return) ─────────────────────────────────────────────")
    click.echo(f"  {'Date':<12} {'Symbol':<10} {'TF':>3}  {'Signal':<10} {'Score':>5}  {'Return':>8}  {'MFE':>6}  {'Bars':>4}")
    click.echo("  " + "─" * 72)

    def _row(r, col):
        sig_name = SIGNAL_NAMES.get(r["signal_type"], f"S{r['signal_type']}")
        return (
            f"  {(r['fired_at'] or '')[:10]:<12} "
            f"{r['symbol'].replace('/USDT',''):<10} "
            f"{r['timeframe']:>3}  {sig_name:<10} "
            f"{str(r['bull_score'] or '—'):>5}  "
            f"{col}{_pct(r['exit_return']):>8}\033[0m  "
            f"{_pct(r['mfe']):>6}  {_bars(r['duration_bars']):>4}"
        )

    click.echo("  ▲ Best:")
    for r in top5:
        click.echo(_row(r, "\033[32m"))
    click.echo("  ▼ Worst:")
    for r in bot5:
        click.echo(_row(r, "\033[31m"))
    click.echo()
