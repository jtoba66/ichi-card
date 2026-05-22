"""Universe management command — ichi universe.

Usage:
    ichi universe             # show cached universe map
    ichi universe --rebuild   # force rebuild from CoinGecko + exchange discovery
    ichi universe --top 100   # rebuild with top 100
"""
from __future__ import annotations

from pathlib import Path

import click

from ichi.data.universe import _UNIVERSE_MAP_FILE, build_universe, get_exchange_for


@click.command(name="universe")
@click.option("--rebuild", is_flag=True, help="Force rebuild from CoinGecko (ignore cache)")
@click.option("--top", "-n", default=200, show_default=True, help="Number of coins to include")
def universe_cmd(rebuild: bool, top: int) -> None:
    """Show or rebuild the CoinGecko market-cap universe map.

    The universe map caches which exchange has each top-N coin available,
    stored at data/universe_map.json with a 24-hour TTL.

    Examples:
        ichi universe
        ichi universe --rebuild
        ichi universe --top 100
    """
    import json
    import time

    if rebuild:
        click.echo(f"Rebuilding universe (top {top})…")
        pair_map = build_universe(n=top, force=True)
        click.echo(f"\nRebuilt: {len(pair_map)} pairs found.\n")
    else:
        if not _UNIVERSE_MAP_FILE.exists():
            click.echo("No cached universe map found. Run with --rebuild to create one.")
            return
        with open(_UNIVERSE_MAP_FILE) as f:
            state = json.load(f)
        age_hours = (time.time() - state.get("timestamp", 0)) / 3600
        pair_map = state.get("pairs", {})
        click.echo(f"Universe map — {len(pair_map)} pairs  (age: {age_hours:.1f}h)\n")

    # Count by exchange
    exchange_counts: dict[str, int] = {}
    for ex in pair_map.values():
        exchange_counts[ex] = exchange_counts.get(ex, 0) + 1

    click.echo("Exchange breakdown:")
    for ex, count in sorted(exchange_counts.items(), key=lambda x: -x[1]):
        click.echo(f"  {ex:<10} {count} pairs")
    click.echo()

    click.echo("Pairs (first 30):")
    for i, (pair, ex) in enumerate(list(pair_map.items())[:30]):
        base = pair.replace("/USDT", "")
        click.echo(f"  {i+1:>3}.  {base:<8}  {ex}")
    if len(pair_map) > 30:
        click.echo(f"  … and {len(pair_map) - 30} more")
