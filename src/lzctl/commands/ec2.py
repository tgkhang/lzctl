"""lzctl ec2 ... : EC2 across many accounts and regions.

This module doubles as the reference for writing new multi-account commands:
resolve targets, fan out with ``for_each_account``, render with ``echo_rows``.
"""

from __future__ import annotations

import click

from ..multi import for_each_account
from ..output import echo_rows, output_option
from ._common import AppContext, pass_app, resolve_targets, target_options

COLUMNS = ["account", "region", "instance_id", "name", "state", "type", "private_ip",
           "public_ip", "launched"]


def _instances(session, account, region, states):
    ec2 = session.client("ec2", region_name=region)
    filters = [{"Name": "instance-state-name", "Values": list(states)}] if states else []
    rows = []
    for page in ec2.get_paginator("describe_instances").paginate(Filters=filters):
        for reservation in page["Reservations"]:
            for inst in reservation["Instances"]:
                tags = {t["Key"]: t["Value"] for t in inst.get("Tags", [])}
                rows.append({
                    "account": account.name,
                    "region": region,
                    "instance_id": inst["InstanceId"],
                    "name": tags.get("Name"),
                    "state": inst["State"]["Name"],
                    "type": inst["InstanceType"],
                    "private_ip": inst.get("PrivateIpAddress"),
                    "public_ip": inst.get("PublicIpAddress"),
                    "launched": inst["LaunchTime"].strftime("%Y-%m-%d %H:%M"),
                })
    return rows


@click.group()
def ec2():
    """EC2 commands that work across accounts."""


@ec2.command("list")
@target_options
@click.option("--region", "regions", multiple=True,
              help="Region(s) to query; repeat for several (default: each account's region).")
@click.option("--state", "states", multiple=True,
              type=click.Choice(["pending", "running", "stopping", "stopped", "shutting-down",
                                 "terminated"]),
              help="Only instances in this state; repeatable.")
@output_option
@pass_app
def list_(app: AppContext, targets, regions, states, fmt):
    """List EC2 instances in the selected accounts.

    \b
    lzctl ec2 list dev
    lzctl ec2 list --tag env=prod --region us-east-1 --region eu-west-1 --state running
    lzctl ec2 list --all -o csv > instances.csv
    """
    accounts = resolve_targets(app.config, targets)
    rows = for_each_account(
        app, accounts, lambda s, a, r: _instances(s, a, r, states), regions=regions)
    rows.sort(key=lambda r: (r["account"], r["region"], r["name"] or "", r["instance_id"]))
    echo_rows(rows, COLUMNS, fmt)


COMMANDS = [ec2]
