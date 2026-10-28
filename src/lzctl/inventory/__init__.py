"""Resource inventory: collectors gather resources per account/region, writers render reports.

Built-in collectors live in ``collectors.py``. Third-party packages can add more
through the ``lzctl.collectors`` entry point group; the entry point must resolve
to a :class:`Collector`.
"""

from __future__ import annotations

from collections.abc import Callable, Iterable
from dataclasses import dataclass, field
from importlib.metadata import entry_points
from typing import Any

import boto3

from ..errors import ConfigError

Resource = dict[str, Any]
BASE_COLUMNS = ("account", "account_id", "region", "service", "id", "name", "state", "created")


@dataclass(frozen=True)
class Collector:
    name: str
    description: str
    collect: Callable[[boto3.Session, str], Iterable[Resource]]
    #: service-specific columns, in report order
    columns: tuple[str, ...] = ()
    #: global services (S3) are collected once per account, not per region
    global_service: bool = False
    extra: dict[str, Any] = field(default_factory=dict)


_BUILTIN: dict[str, Collector] = {}


def collector(name: str, description: str, columns: tuple[str, ...] = (), global_service=False):
    """Decorator registering a built-in collector function ``f(session, region)``."""

    def register(func):
        _BUILTIN[name] = Collector(name, description, func, columns, global_service)
        return func

    return register


def available() -> dict[str, Collector]:
    from . import collectors  # noqa: F401 - registers built-ins

    found = dict(_BUILTIN)
    for ep in entry_points(group="lzctl.collectors"):
        if ep.name in found:
            continue
        obj = ep.load()
        if not isinstance(obj, Collector):
            raise ConfigError(f"Collector plugin {ep.name!r} is not a lzctl.inventory.Collector")
        found[ep.name] = obj
    return found


def select(names: Iterable[str]) -> list[Collector]:
    every = available()
    names = [n.strip() for name in names for n in name.split(",") if n.strip()]
    if not names or "all" in names:
        return list(every.values())
    unknown = [n for n in names if n not in every]
    if unknown:
        raise ConfigError(f"Unknown service(s): {', '.join(unknown)}. Available: {', '.join(every)}")
    return [every[n] for n in names]


def tags_of(items: Iterable[dict] | None) -> dict[str, str]:
    """Convert AWS ``[{"Key": k, "Value": v}]`` lists to a dict."""
    return {t["Key"]: t.get("Value", "") for t in items or []}
