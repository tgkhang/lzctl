"""Loading, validating and saving the lzctl configuration file.

Location (first match wins):
  1. --config option / LZCTL_CONFIG environment variable
  2. Windows:      %APPDATA%\\lzctl\\config.yaml
     macOS/Linux:  $XDG_CONFIG_HOME/lzctl/config.yaml  (default ~/.config/lzctl/config.yaml)
"""

from __future__ import annotations

import fnmatch
import os
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import yaml

from .errors import ConfigError

ACCOUNT_ID_RE = re.compile(r"^\d{12}$")
DEFAULT_REGION = "us-east-1"
DEFAULT_CHAIN_ROLE = "OrganizationAccountAccessRole"
DEFAULT_PRODUCTION_TAGS = {"env": "prod*"}


def config_dir() -> Path:
    if os.name == "nt":
        base = os.environ.get("APPDATA") or str(Path.home() / "AppData" / "Roaming")
    else:
        base = os.environ.get("XDG_CONFIG_HOME") or str(Path.home() / ".config")
    return Path(base) / "lzctl"


def default_config_path() -> Path:
    env = os.environ.get("LZCTL_CONFIG")
    return Path(env).expanduser() if env else config_dir() / "config.yaml"


def normalize_account_id(value: Any, where: str = "account") -> str:
    # YAML turns unquoted 123456789012 into an int and drops leading zeros.
    if isinstance(value, int) and not isinstance(value, bool):
        value = str(value).zfill(12)
    value = str(value).strip()
    if not ACCOUNT_ID_RE.match(value):
        raise ConfigError(f"{where}: account id must be 12 digits, got {value!r}")
    return value


def _str_dict(value: Any, where: str) -> dict[str, str]:
    if value is None:
        return {}
    if not isinstance(value, dict):
        raise ConfigError(f"{where} must be a mapping")
    return {str(k): str(v) for k, v in value.items()}


def _opt_int(value: Any, where: str) -> int | None:
    if value is None:
        return None
    try:
        return int(value)
    except (TypeError, ValueError) as err:
        raise ConfigError(f"{where} must be an integer") from err


@dataclass
class IdpConfig:
    name: str
    provider: str
    url: str = ""
    url_params: dict[str, str] = field(default_factory=dict)
    username: str | None = None
    ca_bundle: str | None = None
    verify_ssl: bool = True
    keyring: bool = False
    session_duration: int | None = None
    options: dict[str, Any] = field(default_factory=dict)

    @property
    def verify(self) -> bool | str:
        """Value for requests' ``verify``: a CA bundle path or a bool."""
        if self.ca_bundle:
            return str(Path(self.ca_bundle).expanduser())
        return self.verify_ssl

    @classmethod
    def from_dict(cls, name: str, data: dict[str, Any]) -> IdpConfig:
        where = f"idps.{name}"
        if not isinstance(data, dict):
            raise ConfigError(f"{where} must be a mapping")
        if not data.get("provider"):
            raise ConfigError(f"{where}.provider is required")
        return cls(
            name=name,
            provider=str(data["provider"]),
            url=str(data.get("url") or ""),
            url_params=_str_dict(data.get("url_params"), f"{where}.url_params"),
            username=data.get("username"),
            ca_bundle=data.get("ca_bundle"),
            verify_ssl=bool(data.get("verify_ssl", True)),
            keyring=bool(data.get("keyring", False)),
            session_duration=_opt_int(data.get("session_duration"), f"{where}.session_duration"),
            options=dict(data.get("options") or {}),
        )


@dataclass
class Account:
    name: str
    id: str
    idp: str | None = None
    role: str | None = None
    region: str | None = None
    profile: str | None = None
    via: str | None = None
    tags: dict[str, str] = field(default_factory=dict)
    url_params: dict[str, str] = field(default_factory=dict)
    duration: int | None = None
    external_id: str | None = None

    @property
    def profile_name(self) -> str:
        return self.profile or self.name

    def matches_tags(self, wanted: dict[str, str]) -> bool:
        return all(
            fnmatch.fnmatchcase(self.tags.get(k, ""), v) and k in self.tags
            for k, v in wanted.items()
        )

    @classmethod
    def from_dict(cls, name: str, data: dict[str, Any]) -> Account:
        where = f"accounts.{name}"
        if not isinstance(data, dict):
            raise ConfigError(f"{where} must be a mapping")
        if "id" not in data:
            raise ConfigError(f"{where}.id is required")
        return cls(
            name=name,
            id=normalize_account_id(data["id"], where),
            idp=data.get("idp"),
            role=data.get("role"),
            region=data.get("region"),
            profile=data.get("profile"),
            via=data.get("via"),
            tags=_str_dict(data.get("tags"), f"{where}.tags"),
            url_params=_str_dict(data.get("url_params"), f"{where}.url_params"),
            duration=_opt_int(data.get("duration"), f"{where}.duration"),
            external_id=data.get("external_id"),
        )

    def to_dict(self) -> dict[str, Any]:
        out: dict[str, Any] = {"id": self.id}
        for key in ("idp", "role", "region", "profile", "via", "duration", "external_id"):
            value = getattr(self, key)
            if value is not None:
                out[key] = value
        if self.tags:
            out["tags"] = dict(self.tags)
        if self.url_params:
            out["url_params"] = dict(self.url_params)
        return out


class Config:
    def __init__(self, path: Path, data: dict[str, Any] | None = None):
        self.path = path
        self.data: dict[str, Any] = data or {}
        self.defaults: dict[str, Any] = dict(self.data.get("defaults") or {})
        self.idps: dict[str, IdpConfig] = {
            str(n): IdpConfig.from_dict(str(n), d) for n, d in (self.data.get("idps") or {}).items()
        }
        self.accounts: dict[str, Account] = {
            str(n): Account.from_dict(str(n), d)
            for n, d in (self.data.get("accounts") or {}).items()
        }
        self._validate()

    @classmethod
    def load(cls, path: Path | None = None) -> Config:
        path = path or default_config_path()
        if not path.exists():
            return cls(path, {})
        try:
            data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
        except yaml.YAMLError as err:
            raise ConfigError(f"{path}: invalid YAML: {err}") from err
        if not isinstance(data, dict):
            raise ConfigError(f"{path}: top level must be a mapping")
        return cls(path, data)

    @property
    def exists(self) -> bool:
        return self.path.exists()

    def _validate(self) -> None:
        for acct in self.accounts.values():
            if acct.idp and acct.idp not in self.idps:
                raise ConfigError(f"accounts.{acct.name}.idp: unknown idp {acct.idp!r}")
            if acct.via and acct.via not in self.accounts:
                raise ConfigError(f"accounts.{acct.name}.via: unknown account {acct.via!r}")
        default_idp = self.defaults.get("idp")
        if default_idp and default_idp not in self.idps:
            raise ConfigError(f"defaults.idp: unknown idp {default_idp!r}")

    # -- lookups ---------------------------------------------------------

    def idp(self, name: str | None = None, account: Account | None = None) -> IdpConfig:
        name = name or (account.idp if account else None) or self.defaults.get("idp")
        if name:
            if name not in self.idps:
                raise ConfigError(f"Unknown idp {name!r}. Configured: {', '.join(self.idps) or '-'}")
            return self.idps[name]
        if len(self.idps) == 1:
            return next(iter(self.idps.values()))
        if not self.idps:
            raise ConfigError(f"No identity provider configured. Run 'lzctl init' (config: {self.path})")
        raise ConfigError("Several idps configured; set defaults.idp or pass --idp")

    def region_for(self, account: Account | None = None) -> str:
        return (account.region if account else None) or self.defaults.get("region") or DEFAULT_REGION

    def chain_role_for(self, account: Account) -> str:
        role = account.role or self.defaults.get("chain_role") or DEFAULT_CHAIN_ROLE
        return role if role.startswith("arn:") else f"arn:aws:iam::{account.id}:role/{role}"

    @property
    def production_tags(self) -> dict[str, str]:
        return _str_dict(self.defaults.get("production_tags") or DEFAULT_PRODUCTION_TAGS,
                         "defaults.production_tags")

    def is_production(self, account: Account) -> bool:
        """Accounts matching ANY of ``defaults.production_tags`` (default env=prod*)."""
        return any(account.matches_tags({k: v}) for k, v in self.production_tags.items())

    def find_account(self, key: str) -> Account | None:
        if key in self.accounts:
            return self.accounts[key]
        for acct in self.accounts.values():
            if key in (acct.id, acct.profile):
                return acct
        return None

    def account_by_id(self, account_id: str) -> Account | None:
        return next((a for a in self.accounts.values() if a.id == account_id), None)

    # -- mutation --------------------------------------------------------

    def add_account(self, account: Account, replace: bool = False) -> None:
        if account.name in self.accounts and not replace:
            raise ConfigError(f"Account {account.name!r} already exists")
        if account.via and account.via not in self.accounts:
            raise ConfigError(f"via: unknown account {account.via!r}")
        if account.idp and account.idp not in self.idps:
            raise ConfigError(f"idp: unknown idp {account.idp!r}")
        self.accounts[account.name] = account

    def remove_account(self, name: str) -> None:
        if name not in self.accounts:
            raise ConfigError(f"No account named {name!r}")
        users = [a.name for a in self.accounts.values() if a.via == name]
        if users:
            raise ConfigError(f"{name!r} is used as 'via' by: {', '.join(users)}")
        del self.accounts[name]

    def save(self) -> None:
        data = dict(self.data)
        if self.defaults:
            data["defaults"] = self.defaults
        data["accounts"] = {name: a.to_dict() for name, a in self.accounts.items()}
        self.path.parent.mkdir(parents=True, exist_ok=True)
        text = yaml.safe_dump(data, sort_keys=False, default_flow_style=False)
        self.path.write_text(text, encoding="utf-8")
        self.data = data
