"""lzctl accounts ... : manage the account inventory."""

from __future__ import annotations

import configparser
import csv
from pathlib import Path

import click
import yaml

from ..auth import authenticate, build_idp_url
from ..config import Account, Config, normalize_account_id
from ..credentials import aws_config_path
from ..errors import ConfigError
from ..output import echo_rows, output_option
from ..prompts import Prompter
from ..saml import parse_roles
from ._common import AppContext, parse_tags, pass_app, resolve_targets, target_options

COLUMNS = ["name", "id", "role", "via", "region", "tags"]


@click.group()
def accounts():
    """List, add and import AWS accounts."""


@accounts.command("list")
@target_options
@output_option
@pass_app
def list_(app: AppContext, targets, fmt):
    """List configured accounts (filter with names, globs or --tag)."""
    config = app.config
    selected = resolve_targets(config, targets, required=False) or list(config.accounts.values())
    rows = [{**a.to_dict(), "name": a.name, "idp": a.idp, "profile": a.profile_name}
            for a in sorted(selected, key=lambda a: a.name)]
    echo_rows(rows, COLUMNS if fmt == "table" else [*COLUMNS, "idp", "profile"], fmt)


@accounts.command()
@click.argument("name")
@click.option("--id", "account_id", required=True, help="12-digit AWS account id.")
@click.option("--role", help="Role to pick (name, ARN or substring); for --via, the role to assume.")
@click.option("--via", help="Reach this account by assuming a role from another account.")
@click.option("--idp", help="Identity provider name.")
@click.option("--region")
@click.option("--profile", help="AWS profile name to write (default: NAME).")
@click.option("-t", "--tag", "tags", multiple=True, metavar="KEY=VALUE")
@click.option("--replace", is_flag=True, help="Overwrite an existing account with this name.")
@pass_app
def add(app: AppContext, name, account_id, role, via, idp, region, profile, tags, replace):
    """Add an account to the config."""
    config = app.config
    config.add_account(Account(name=name, id=normalize_account_id(account_id), role=role, via=via,
                               idp=idp, region=region, profile=profile, tags=parse_tags(tags)),
                       replace=replace)
    config.save()
    app.info(f"Added {name} to {config.path}")


@accounts.command()
@click.argument("name")
@pass_app
def remove(app: AppContext, name):
    """Remove an account from the config."""
    app.config.remove_account(name)
    app.config.save()
    app.info(f"Removed {name}")


@accounts.command()
@click.argument("old")
@click.argument("new")
@pass_app
def rename(app: AppContext, old, new):
    """Rename an account (keeps 'via' references working)."""
    config = app.config
    if old not in config.accounts:
        raise ConfigError(f"No account named {old!r}")
    if new in config.accounts:
        raise ConfigError(f"Account {new!r} already exists")
    acct = config.accounts.pop(old)
    acct.name = new
    config.accounts[new] = acct
    for other in config.accounts.values():
        if other.via == old:
            other.via = new
    config.save()
    app.info(f"Renamed {old} -> {new}")


@accounts.command()
@target_options
@click.option("-s", "--set", "set_tags", multiple=True, metavar="KEY=VALUE", required=True,
              help="Tag to set; an empty value removes the tag.")
@pass_app
def tag(app: AppContext, targets, set_tags):
    """Set tags on several accounts at once."""
    config = app.config
    changes = parse_tags(set_tags)
    selected = resolve_targets(config, targets)
    for acct in selected:
        for key, value in changes.items():
            if value:
                acct.tags[key] = value
            else:
                acct.tags.pop(key, None)
    config.save()
    app.info(f"Updated {len(selected)} account(s)")


def _rows_from_file(path: Path) -> list[Account]:
    """CSV (name,id[,role,region,via,idp,profile,tags]) or YAML.

    YAML may be an ``accounts:`` mapping as in the config file, or the older
    ``name: {sn: ..., acc: ...}`` format (sn/acc become url_params).
    """
    if path.suffix.lower() == ".csv":
        out = []
        with path.open(newline="", encoding="utf-8") as fh:
            for row in csv.DictReader(fh):
                row = {k.strip().lower(): (v or "").strip() for k, v in row.items() if k}
                tags = dict(t.split("=", 1) for t in row.pop("tags", "").split(";") if "=" in t)
                data = {k: v for k, v in row.items() if v and k != "name"}
                out.append(Account.from_dict(row["name"], {**data, "tags": tags}))
        return out
    data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    data = data.get("accounts", data)
    out = []
    for name, entry in data.items():
        if isinstance(entry, dict) and "acc" in entry and "id" not in entry:
            entry = {"id": entry["acc"],
                     "url_params": {k: v for k, v in entry.items() if k in ("sn", "acc")}}
        out.append(Account.from_dict(str(name), entry))
    return out


@accounts.command("import")
@click.argument("file", type=click.Path(exists=True, dir_okay=False, path_type=Path))
@click.option("--replace", is_flag=True, help="Overwrite accounts that already exist.")
@click.option("--dry-run", is_flag=True)
@pass_app
def import_(app: AppContext, file, replace, dry_run):
    """Import accounts from a CSV or YAML file."""
    config = app.config
    added = skipped = 0
    for acct in _rows_from_file(file):
        if acct.name in config.accounts and not replace:
            skipped += 1
            continue
        config.accounts[acct.name] = acct
        added += 1
    # re-validate cross references (via/idp) before touching the file
    Config(config.path, {**config.data, "accounts": {n: a.to_dict()
                                                       for n, a in config.accounts.items()}})
    if not dry_run:
        config.save()
    app.info(f"{'Would import' if dry_run else 'Imported'} {added}, skipped {skipped} existing")


@accounts.command()
@click.option("--idp", help="Identity provider to log in to.")
@click.option("-u", "--username")
@click.option("--prefix", default="", help="Prefix for new account names.")
@click.option("--dry-run", is_flag=True)
@pass_app
def discover(app: AppContext, idp, username, prefix, dry_run):
    """Log in once and add every account the IdP gives you a role in."""
    config = app.config
    idp_cfg = config.idp(idp)
    prompter = Prompter(idp_name=idp_cfg.name, use_keyring=idp_cfg.keyring,
                        username=username or idp_cfg.username or config.defaults.get("username"))
    roles = parse_roles(authenticate(idp_cfg, build_idp_url(idp_cfg), prompter))
    by_account: dict[str, list[str]] = {}
    for role in roles:
        by_account.setdefault(role.account_id, []).append(role.name)
    rows = []
    for account_id, names in sorted(by_account.items()):
        existing = config.account_by_id(account_id)
        if existing is None:
            name = f"{prefix}{account_id}"
            config.accounts[name] = Account(
                name=name, id=account_id, idp=idp if idp else None,
                role=names[0] if len(names) == 1 else None)
        rows.append({"name": existing.name if existing else f"{prefix}{account_id}",
                     "id": account_id, "roles": names, "new": existing is None})
    echo_rows(rows, ["name", "id", "new", "roles"])
    if not dry_run and any(r["new"] for r in rows):
        config.save()
        app.info("Saved. Give accounts friendly names with 'lzctl accounts rename ID NAME'.")


@accounts.command("import-aws-config")
@click.option("--source-profile", help="Only import profiles whose source_profile is this.")
@click.option("--via", "via_override",
              help="Chain every imported profile through this lzctl account "
                   "(default: the account whose profile matches source_profile).")
@click.option("--replace", is_flag=True, help="Overwrite accounts that already exist.")
@click.option("--dry-run", is_flag=True)
@pass_app
def import_aws_config(app: AppContext, source_profile, via_override, replace, dry_run):
    """Import role-chaining profiles from ~/.aws/config.

    Turns profiles such as

    \b
      [profile workload-dev]
      role_arn = arn:aws:iam::333333333333:role/Deployer
      source_profile = saml

    into accounts with 'via' pointing at the account that writes the 'saml' profile.
    """
    config = app.config
    parser = configparser.RawConfigParser()
    parser.read(aws_config_path(), encoding="utf-8")
    if via_override and via_override not in config.accounts:
        raise ConfigError(f"--via: unknown account {via_override!r}")
    rows = []
    for section in parser.sections():
        name = section.removeprefix("profile ").strip()
        role_arn = parser.get(section, "role_arn", fallback=None)
        source = parser.get(section, "source_profile", fallback=None)
        if not role_arn or (source_profile and source != source_profile):
            continue
        parent = config.accounts.get(via_override) if via_override else \
            next((a for a in config.accounts.values() if source in (a.profile_name, a.name)), None)
        if parent is None:
            app.warn(f"skip {name}: no lzctl account writes profile {source!r} (use --via)")
            continue
        if name in config.accounts and not replace:
            rows.append({"name": name, "id": role_arn.split(":")[4], "via": parent.name,
                         "result": "exists"})
            continue
        config.accounts[name] = Account(
            name=name, id=normalize_account_id(role_arn.split(":")[4], section), via=parent.name,
            role=role_arn, region=parser.get(section, "region", fallback=None),
            external_id=parser.get(section, "external_id", fallback=None))
        rows.append({"name": name, "id": config.accounts[name].id, "via": parent.name,
                     "result": "would add" if dry_run else "added"})
    echo_rows(rows, ["name", "id", "via", "result"])
    if not dry_run and any(r["result"] == "added" for r in rows):
        config.save()


COMMANDS = [accounts]
