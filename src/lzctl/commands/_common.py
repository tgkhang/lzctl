"""Helpers shared by commands (and usable by plugins)."""

from __future__ import annotations

import fnmatch
import sys
from collections.abc import Sequence
from dataclasses import dataclass, field
from functools import wraps
from pathlib import Path

import click

from ..config import Account, Config
from ..errors import ConfigError, LzctlError


@dataclass
class AppContext:
    config_path: Path
    quiet: bool = False
    _config: Config | None = field(default=None, repr=False)

    @property
    def config(self) -> Config:
        if self._config is None:
            self._config = Config.load(self.config_path)
        return self._config

    def info(self, message: str) -> None:
        if not self.quiet:
            click.echo(message, err=True)

    def warn(self, message: str) -> None:
        click.secho(message, fg="yellow", err=True)


pass_app = click.make_pass_decorator(AppContext)


def parse_tags(values: Sequence[str]) -> dict[str, str]:
    tags = {}
    for value in values:
        key, sep, val = value.partition("=")
        if not sep or not key:
            raise click.BadParameter(f"expected KEY=VALUE, got {value!r}", param_hint="--tag")
        tags[key.strip()] = val.strip()
    return tags


def target_options(func):
    """Adds ``[ACCOUNTS]... --tag K=V --all``; the command receives ``targets``."""

    @click.argument("accounts", nargs=-1)
    @click.option("-t", "--tag", "tags", multiple=True, metavar="KEY=VALUE",
                  help="Select accounts by tag (glob values allowed, repeat to AND).")
    @click.option("--all", "all_accounts", is_flag=True, help="Select every configured account.")
    @wraps(func)
    def wrapper(*args, accounts, tags, all_accounts, **kwargs):
        return func(*args, targets=(tuple(accounts), parse_tags(tags), all_accounts), **kwargs)

    return wrapper


dry_run_option = click.option("--dry-run", is_flag=True,
                              help="Show what would change without changing anything.")
yes_option = click.option("-y", "--yes", is_flag=True,
                          help="Do not ask for confirmation (required in scripts).")


def confirm_targets(app: AppContext, accounts: Sequence[Account], action: str, *,
                    yes: bool = False) -> None:
    """Gate for commands that change things.

    Lists the accounts, then asks for confirmation. If any account is production
    (see ``defaults.production_tags``) the user has to type the number of
    production accounts, which is hard to do by reflex. ``--yes`` skips the
    prompts; without a terminal and without ``--yes`` this aborts.
    """
    prod = [a for a in accounts if app.config.is_production(a)]
    click.echo(f"About to {action} in {len(accounts)} account(s):", err=True)
    for acct in accounts:
        mark = click.style("  PRODUCTION", fg="red", bold=True) if acct in prod else ""
        click.echo(f"  - {acct.name} ({acct.id}){mark}", err=True)
    if yes:
        return
    if not sys.stdin.isatty():
        raise LzctlError("Refusing to continue without a terminal; pass --yes to confirm")
    if prod:
        answer = click.prompt(click.style(
            f"{len(prod)} production account(s) affected. Type {len(prod)} to continue",
            fg="red"), default="", show_default=False, err=True)
        if answer.strip() != str(len(prod)):
            raise click.Abort()
    elif not click.confirm("Continue?", default=False, err=True):
        raise click.Abort()


def resolve_targets(
    config: Config,
    targets: tuple[tuple[str, ...], dict[str, str], bool],
    *,
    required: bool = True,
) -> list[Account]:
    """Accounts by name, id, profile or glob pattern ("lz*-nonprod"), tag or --all."""
    names, tags, all_accounts = targets
    if not (names or tags or all_accounts):
        if required:
            raise LzctlError("Name at least one account, or use --tag / --all")
        return []
    pool = list(config.accounts.values())
    if names:
        picked: dict[str, Account] = {}
        for name in names:
            acct = config.find_account(name)
            matches = [acct] if acct else [
                a for a in pool if fnmatch.fnmatchcase(a.name, name)
            ]
            if not matches:
                raise ConfigError(f"No account matches {name!r}; see 'lzctl accounts list'")
            picked.update({a.name: a for a in matches})
        pool = list(picked.values())
    if tags:
        pool = [a for a in pool if a.matches_tags(tags)]
        if not pool:
            raise ConfigError(f"No account has tags {tags}")
    return pool
