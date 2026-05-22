import click

from ichi.data.fetcher import fetch_ohlcv
from ichi.indicators.ichimoku import ichimoku
from ichi.rules.registry import RuleRegistry
from ichi.scoring.engine import evaluate
from ichi.viz.chart import render_chart


def _normalize_symbol(raw: str) -> str:
    """Convert 'BTCUSDT' → 'BTC/USDT', leave 'BTC/USDT' unchanged."""
    if "/" in raw:
        return raw.upper()
    # Assume USDT suffix; split at the last 4 chars if they are USDT
    raw = raw.upper()
    if raw.endswith("USDT"):
        base = raw[:-4]
        return f"{base}/USDT"
    return raw


@click.command()
@click.argument("symbol")
@click.argument("timeframe")
@click.option("--output", "-o", default=None, help="Save PNG to this path instead of opening browser")
def chart(symbol: str, timeframe: str, output: str | None) -> None:
    """Render Ichimoku chart + scorecard panel for SYMBOL on TIMEFRAME.

    Examples:
        ichi chart BTCUSDT 1d
        ichi chart BTCUSDT 1d --output btc.png
        ichi chart ETH/USDT 4h -o eth_4h.png
    """
    ccxt_symbol = _normalize_symbol(symbol)
    click.echo(f"Fetching {ccxt_symbol} {timeframe}...")
    df = fetch_ohlcv(ccxt_symbol, timeframe)

    if df.empty:
        click.echo("No data returned.", err=True)
        raise SystemExit(1)

    click.echo(f"  {len(df)} candles loaded. Computing indicators...")
    df = ichimoku(df)

    registry = RuleRegistry.canonical()
    i = len(df) - 1
    scorecard = evaluate(df, i, registry)

    click.echo(
        f"  Bull Score: {scorecard.bull_score}/{scorecard.total_scoring_rules}  "
        f"Chikou angle: {scorecard.chikou_angle_val:+.1f}°"
    )
    render_chart(df, scorecard, ccxt_symbol, timeframe, output_path=output)
