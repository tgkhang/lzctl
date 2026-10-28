"""lzctl inventory : collect resources across accounts and write a report."""

from __future__ import annotations

import fnmatch
import json
import re
from datetime import datetime
from pathlib import Path

import botocore.exceptions
import click

from .. import inventory
from ..errors import LzctlError
from ..inventory.report import columns_for, flatten, write_xlsx
from ..multi import EXPIRED_CODES, for_each_account
from ..output import render
from ._common import AppContext, parse_tags, pass_app, resolve_targets, target_options

TABLE_COLUMNS = ["account", "region", "service", "id", "name", "state"]


def _matches(resource: dict, wanted: dict[str, str]) -> bool:
    tags = resource.get("tags") or {}
    return all(k in tags and fnmatch.fnmatchcase(tags[k], v) for k, v in wanted.items())


@click.command("inventory")
@target_options
@click.option("-s", "--service", "services", multiple=True, metavar="NAME",
              help="Services to collect (comma separated or repeated; default: all). "
                   "See 'lzctl inventory --list-services'.")
@click.option("--region", "regions", multiple=True,
              help="Region(s) to scan; repeatable (default: each account's region).")
@click.option("-f", "--resource-tag", "resource_tags", multiple=True, metavar="KEY=VALUE",
              help="Only resources with this tag (glob values allowed, repeat to AND).")
@click.option("-c", "--tag-column", "tag_columns", multiple=True, metavar="KEY",
              help="Show this resource tag as its own column (default: defaults.inventory_tag_columns).")
@click.option("-o", "--output", "fmt", type=click.Choice(["table", "json", "csv", "xlsx"]),
              default="table", show_default=True)
@click.option("--out", "out_path", type=click.Path(path_type=Path),
              help="xlsx: output file or directory (default: ./reports/).")
@click.option("--list-services", is_flag=True, help="List available collectors and exit.")
@pass_app
def inventory_cmd(app: AppContext, targets, services, regions, resource_tags, tag_columns, fmt,
                  out_path, list_services):
    """Inventory resources across accounts and regions.

    \b
    lzctl inventory dev
    lzctl inventory --tag env=prod -s ec2,rds -f CostCentre=FIN* -o xlsx
    lzctl inventory --all -f Application=billing -c Application -c Owner -o csv > billing.csv
    """
    if list_services:
        for coll in inventory.available().values():
            scope = " (global)" if coll.global_service else ""
            click.echo(f"{coll.name:10} {coll.description}{scope}")
        return

    config = app.config
    collectors = inventory.select(services)
    wanted = parse_tags(resource_tags)
    tag_cols = list(tag_columns or config.defaults.get("inventory_tag_columns") or [])
    accounts = resolve_targets(config, targets)

    def first_region(acct):
        return regions[0] if regions else config.region_for(acct)

    def task(session, acct, region):
        rows = []
        for coll in collectors:
            if coll.global_service and region != first_region(acct):
                continue
            try:
                for res in coll.collect(session, region):
                    if _matches(res, wanted):
                        rows.append({"account": acct.name, "account_id": acct.id,
                                     "region": "global" if coll.global_service else region,
                                     "service": coll.name, **res})
            except botocore.exceptions.ClientError as err:
                code = err.response.get("Error", {}).get("Code", "")
                if code in EXPIRED_CODES:
                    raise  # reported once per account by for_each_account
                app.warn(f"{acct.name} ({region}) {coll.name}: {code or err}")
        return rows

    resources = for_each_account(app, accounts, task, regions=regions)
    resources.sort(key=lambda r: (r["account"], r["service"], r["region"], str(r.get("name") or r["id"])))
    app.info(f"{len(resources)} resource(s) in {len(accounts)} account(s)")

    if fmt == "xlsx":
        label = accounts[0].name if len(accounts) == 1 else "multi-account"
        stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        filename = f"{re.sub(r'[^A-Za-z0-9_.-]', '_', label)}_inventory_{stamp}.xlsx"
        path = out_path or Path("reports")
        if path.suffix.lower() != ".xlsx":
            path = path / filename
        title = f"Inventory: {', '.join(a.name for a in accounts)} ({stamp})"
        write_xlsx(path, resources, collectors, tag_cols, title)
        app.info(f"Wrote {path}")
        click.echo(str(path))
        return
    if out_path:
        raise LzctlError("--out is only used with -o xlsx; redirect stdout for other formats")

    if fmt == "json":
        click.echo(json.dumps(resources, indent=2, default=str))
    elif fmt == "csv":
        extra = [c for coll in collectors for c in coll.columns]
        columns = list(dict.fromkeys([*columns_for(None, tag_cols)[:-1], *extra, "tags"]))
        click.echo(render([flatten(r, tag_cols) for r in resources], columns, "csv"))
    elif resources:
        columns = TABLE_COLUMNS + [f"tag:{k}" for k in tag_cols]
        click.echo(render([flatten(r, tag_cols) for r in resources], columns))


COMMANDS = [inventory_cmd]
