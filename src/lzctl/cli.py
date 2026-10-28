"""Entry point. Built-in commands are registered here; third-party packages can
add commands through the ``lzctl.commands`` entry point group."""

from __future__ import annotations

from importlib.metadata import entry_points
from pathlib import Path

import click

from . import __version__
from .commands import accounts, ec2, inventory, login, setup
from .commands._common import AppContext
from .config import default_config_path


@click.group(context_settings={"help_option_names": ["-h", "--help"], "max_content_width": 100})
@click.version_option(__version__, prog_name="lzctl")
@click.option("-c", "--config", "config_path", type=click.Path(dir_okay=False, path_type=Path),
              help="Config file (default: $LZCTL_CONFIG or the per-user config dir).")
@click.option("-q", "--quiet", is_flag=True, help="Only print results and errors.")
@click.pass_context
def cli(ctx: click.Context, config_path: Path | None, quiet: bool):
    """SAML 2.0 login and multi-account tooling for AWS.

    \b
    Get started:
      lzctl init                  configure your identity provider
      lzctl accounts discover     import every account your IdP grants
      lzctl login dev             get credentials for 'dev'
      lzctl ec2 list --all        query all accounts at once
    """
    ctx.obj = AppContext(config_path or default_config_path(), quiet)


# Built-in command modules; each exposes COMMANDS = [click commands/groups].
BUILTIN_MODULES = (setup, login, accounts, inventory, ec2)

for module in BUILTIN_MODULES:
    for command in module.COMMANDS:
        cli.add_command(command)


def _load_plugins() -> None:
    for ep in entry_points(group="lzctl.commands"):
        if ep.name in cli.commands:
            continue  # built-ins win
        try:
            command = ep.load()
        except Exception as err:  # noqa: BLE001 - a broken plugin must not break the CLI
            click.secho(f"lzctl: could not load plugin {ep.name!r}: {err}", fg="yellow", err=True)
            continue
        if isinstance(command, click.Command):
            cli.add_command(command, ep.name)


_load_plugins()


def main() -> None:
    cli()
