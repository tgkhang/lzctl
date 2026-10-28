"""Identity provider plugins.

Built-in providers are listed in ``BUILTIN``. Third-party packages can add more
through the ``lzctl.providers`` entry point group (see CONTRIBUTING.md).
"""

from __future__ import annotations

from importlib.metadata import entry_points

from ..errors import ConfigError
from .base import Provider
from .form import AdfsProvider, FormProvider, KeycloakProvider, PingFederateProvider
from .manual import ManualProvider

BUILTIN: dict[str, type[Provider]] = {
    cls.name: cls
    for cls in (FormProvider, PingFederateProvider, AdfsProvider, KeycloakProvider, ManualProvider)
}


def available() -> dict[str, type[Provider]]:
    found = dict(BUILTIN)
    for ep in entry_points(group="lzctl.providers"):
        found.setdefault(ep.name, ep)  # loaded lazily in get()
    return found


def get(name: str) -> type[Provider]:
    if name in BUILTIN:
        return BUILTIN[name]
    for ep in entry_points(group="lzctl.providers"):
        if ep.name == name:
            cls = ep.load()
            if not (isinstance(cls, type) and issubclass(cls, Provider)):
                raise ConfigError(f"Provider plugin {name!r} is not a lzctl Provider subclass")
            return cls
    raise ConfigError(f"Unknown provider {name!r}. Available: {', '.join(sorted(available()))}")


__all__ = ["Provider", "available", "get"]
