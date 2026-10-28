"""Rendering rows as a table, JSON or CSV. Shared by all list-style commands."""

from __future__ import annotations

import csv
import io
import json
from collections.abc import Sequence
from typing import Any

import click

FORMATS = ("table", "json", "csv")

output_option = click.option(
    "-o", "--output", "fmt", type=click.Choice(FORMATS), default="table", show_default=True,
    help="Output format.",
)


def _cell(value: Any) -> str:
    if value is None:
        return "-"
    if isinstance(value, dict):
        return ",".join(f"{k}={v}" for k, v in value.items()) or "-"
    if isinstance(value, (list, tuple)):
        return ",".join(map(str, value)) or "-"
    return str(value)


def render(rows: Sequence[dict[str, Any]], columns: Sequence[str], fmt: str = "table") -> str:
    if fmt == "json":
        return json.dumps([{c: r.get(c) for c in columns} for r in rows], indent=2, default=str)
    if fmt == "csv":
        buf = io.StringIO()
        writer = csv.writer(buf, lineterminator="\n")
        writer.writerow(columns)
        writer.writerows([[_cell(r.get(c)) for c in columns] for r in rows])
        return buf.getvalue().rstrip("\n")
    cells = [[_cell(r.get(c)) for c in columns] for r in rows]
    headers = [c.upper() for c in columns]
    widths = [max(len(h), *(len(row[i]) for row in cells)) if cells else len(h)
              for i, h in enumerate(headers)]
    lines = ["  ".join(h.ljust(w) for h, w in zip(headers, widths, strict=True)).rstrip()]
    lines += ["  ".join(v.ljust(w) for v, w in zip(row, widths, strict=True)).rstrip() for row in cells]
    return "\n".join(lines)


def echo_rows(rows: Sequence[dict[str, Any]], columns: Sequence[str], fmt: str = "table") -> None:
    if not rows and fmt == "table":
        click.echo("(nothing to show)", err=True)
        return
    click.echo(render(rows, columns, fmt))
