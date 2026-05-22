from __future__ import annotations

from datetime import date, timedelta

import click
import pandas as pd

from ichi.calibration.params import apply_params, load_params
from ichi.data.universe import top_n_by_marketcap
from ichi.evaluation.ic import decile_spread, ic_summary
from ichi.evaluation.walk_forward import walk_forward, walk_forward_summary
from ichi.universe.snapshot import build_snapshot


@click.command(name="evaluate")
@click.option("--timeframe", "-t", default="1d", show_default=True)
@click.option("--top", "-n", default=20, show_default=True, help="Number of pairs to include")
@click.option("--years", default=3, show_default=True, help="Years of history to use")
@click.option("--save", default=None, help="Save snapshot to this parquet path")
@click.option("--load", default=None, help="Load snapshot from this parquet path (skip build)")
@click.option("--train-months", default=12, show_default=True, help="Walk-forward train window months")
@click.option("--val-months", default=3, show_default=True, help="Walk-forward validate window months")
@click.option("--step-months", default=3, show_default=True, help="Walk-forward step size months")
@click.option("--params", "params_path", default=None,
              help="Path to params.yaml (default: project root). Applied before building snapshot.")
def evaluate_cmd(timeframe: str, top: int, years: int, save: str | None, load: str | None,
                 train_months: int, val_months: int, step_months: int,
                 params_path: str | None) -> None:
    """Compute IC and walk-forward analysis across the universe.

    Examples:
        ichi evaluate
        ichi evaluate --top 50 --years 2
        ichi evaluate --save data/snapshot_1d.parquet
        ichi evaluate --load data/snapshot_1d_3y.parquet   (skip fetch, reuse snapshot)
    """
    # Apply rule params before building snapshot (or before IC if loading pre-built)
    params = load_params(params_path)
    apply_params(params)
    if not load:
        click.echo(f"  Using params: {params_path or 'project root params.yaml'}")

    if load:
        click.echo(f"\nLoading snapshot from {load}...")
        snapshot = pd.read_parquet(load)
        click.echo(f"Snapshot: {len(snapshot):,} rows  ({snapshot['symbol'].nunique()} symbols)\n")
    else:
        symbols = top_n_by_marketcap(n=top)
        end = date.today()
        start = date(end.year - years, end.month, end.day)

        click.echo(f"\nBuilding snapshot: {len(symbols)} symbols, {timeframe}, {start} → {end}")
        click.echo("(This may take a few minutes on first run while data is fetched...)\n")

        snapshot = build_snapshot(symbols, timeframe, start, end, max_workers=5)

        if snapshot.empty:
            click.echo("No data returned. Check connectivity and symbol list.", err=True)
            return

        click.echo(f"Snapshot: {len(snapshot):,} rows  ({snapshot['symbol'].nunique()} symbols)\n")

        if save:
            snapshot.to_parquet(save)
            click.echo(f"Snapshot saved to {save}\n")

    # IC summary
    ics = ic_summary(snapshot)
    click.echo("── Information Coefficient (Spearman) ──────────────────────")
    click.echo(f"  IC  1d fwd return:  {ics['ic_1d']:+.4f}")
    click.echo(f"  IC  7d fwd return:  {ics['ic_7d']:+.4f}")
    click.echo(f"  IC 30d fwd return:  {ics['ic_30d']:+.4f}")
    click.echo()

    # Decile spread
    ds = decile_spread(snapshot)
    if not ds.empty:
        click.echo("── Decile Spread (30d fwd return by score bucket) ──────────")
        click.echo(f"  {'Bucket':>6}  {'Score Range':>14}  {'Mean Ret%':>9}  {'Count':>6}")
        for _, row in ds.iterrows():
            click.echo(
                f"  {int(row['bucket']):>6}  "
                f"{row['score_min']:.2f}–{row['score_max']:.2f}  "
                f"{row['mean_return_pct']:>+8.2f}%  "
                f"{int(row['count']):>6}"
            )
        click.echo()

    # Walk-forward
    click.echo(f"── Walk-Forward ({train_months}m train / {val_months}m validate / {step_months}m step) ──")
    wf = walk_forward(snapshot, train_months=train_months, val_months=val_months, step_months=step_months)
    if wf.empty:
        click.echo("  Not enough history for walk-forward windows.")
    else:
        summary = walk_forward_summary(wf)
        click.echo(f"  Windows:          {summary['n_windows']}")
        click.echo(f"  Mean IC 30d:      {summary['mean_ic_30d']:+.4f}")
        click.echo(f"  Std  IC 30d:      {summary['std_ic_30d']:.4f}")
        click.echo(f"  Min  IC 30d:      {summary['min_ic_30d']:+.4f}")
        click.echo(f"  Max  IC 30d:      {summary['max_ic_30d']:+.4f}")
        click.echo(f"  % Positive 30d:   {summary['pct_positive_30d']*100:.0f}%")
        click.echo(f"  Total obs:        {summary['total_observations']:,}")

        click.echo()
        click.echo(f"  {'Train':>22}  {'Validate':>22}  {'IC 30d':>7}  {'N':>6}")
        for _, row in wf.iterrows():
            click.echo(
                f"  {str(row['train_start'])}–{str(row['train_end'])}  "
                f"{str(row['val_start'])}–{str(row['val_end'])}  "
                f"{row['ic_30d']:>+.4f}  "
                f"{int(row['n_observations']):>6}"
            )

    click.echo()
    _print_verdict(ics, wf)


def _print_verdict(ics: dict, wf) -> None:
    """Verdict based on walk-forward IC (out-of-sample), not in-sample IC.

    In-sample IC flatters the system — it's computed on the same data the rules
    were built against. Walk-forward IC is what matters for real-world use.
    Validated threshold: score ≥13/18 showed 100% positive OOS windows, mean IC +0.055.
    """
    is_ic30 = ics.get("ic_30d", float("nan"))
    click.echo("── Verdict ─────────────────────────────────────────────────")
    click.echo(f"  In-sample  IC 30d: {is_ic30:+.4f}  (biased — same data rules were tuned on)")

    if wf is None or (hasattr(wf, 'empty') and wf.empty):
        click.echo("  Walk-forward: not enough history. Cannot give reliable verdict.")
        return

    from ichi.evaluation.walk_forward import walk_forward_summary
    s = walk_forward_summary(wf)
    wf_ic = s["mean_ic_30d"]
    pct_pos = s["pct_positive_30d"]
    n_win = s["n_windows"]
    click.echo(f"  Walk-fwd   IC 30d: {wf_ic:+.4f}  ({pct_pos*100:.0f}% positive across {n_win} OOS windows)")
    click.echo()

    # Verdict is based on walk-forward, not in-sample
    if wf_ic > 0.04 and pct_pos >= 0.85:
        click.echo(f"  ✓  OOS signal confirmed. Mean WF IC {wf_ic:+.4f}, {pct_pos*100:.0f}% positive windows.")
        click.echo("     Use score ≥13/18 as the validated trading threshold.")
        click.echo("     Below 13: walk-forward shows noise. Above 13: consistent edge.")
    elif wf_ic > 0.02 and pct_pos >= 0.70:
        click.echo(f"  ~  Weak OOS signal. Mean WF IC {wf_ic:+.4f}, {pct_pos*100:.0f}% positive.")
        click.echo("     Consider raising threshold or gathering more data before trading.")
    elif wf_ic > 0:
        click.echo(f"  ~  Very weak OOS signal. Mean WF IC {wf_ic:+.4f}, {pct_pos*100:.0f}% positive.")
        click.echo("     Not enough consistency to trade with confidence. Debug rules.")
    else:
        click.echo(f"  ✗  No OOS signal. Mean WF IC {wf_ic:+.4f}.")
        click.echo("     Do NOT trade this. Examine rule implementations and data quality.")
