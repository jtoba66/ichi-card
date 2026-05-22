import click

from ichi.cli.alerts import alerts
from ichi.cli.calibrate import calibrate_cmd
from ichi.cli.chart import chart
from ichi.cli.evaluate_cmd import evaluate_cmd
from ichi.cli.funding_cmd import funding_cmd
from ichi.cli.journal import journal
from ichi.cli.lagscan import lagscan
from ichi.cli.mtfscan import mtfscan
from ichi.cli.refresh import refresh
from ichi.cli.scan import scan
from ichi.cli.sectorscan import sectorscan
from ichi.cli.universe_cmd import universe_cmd


@click.group()
def cli() -> None:
    """ichi-scorecard CLI."""


cli.add_command(alerts)
cli.add_command(chart)
cli.add_command(scan)
cli.add_command(evaluate_cmd)
cli.add_command(calibrate_cmd)
cli.add_command(mtfscan)
cli.add_command(lagscan)
cli.add_command(sectorscan)
cli.add_command(funding_cmd, name="funding")
cli.add_command(journal)
cli.add_command(refresh)
cli.add_command(universe_cmd)
