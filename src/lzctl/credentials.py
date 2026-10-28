"""Reading and writing the shared AWS credentials/config files."""

from __future__ import annotations

import configparser
import os
import tempfile
from datetime import datetime, timezone
from pathlib import Path

from .aws import AwsCredentials

EXPIRATION_KEY = "x_lzctl_expiration"


def credentials_path() -> Path:
    env = os.environ.get("AWS_SHARED_CREDENTIALS_FILE")
    return Path(env).expanduser() if env else Path.home() / ".aws" / "credentials"


def aws_config_path() -> Path:
    env = os.environ.get("AWS_CONFIG_FILE")
    return Path(env).expanduser() if env else Path.home() / ".aws" / "config"


def _read(path: Path) -> configparser.RawConfigParser:
    parser = configparser.RawConfigParser()
    if path.exists():
        parser.read(path, encoding="utf-8")
    return parser


def _write(path: Path, parser: configparser.RawConfigParser) -> None:
    """Atomic write, readable only by the current user on POSIX."""
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=path.parent, prefix=f".{path.name}.")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as fh:
            parser.write(fh)
        if os.name != "nt":
            os.chmod(tmp, 0o600)
        os.replace(tmp, path)
    except BaseException:
        Path(tmp).unlink(missing_ok=True)
        raise


def write_profile(profile: str, creds: AwsCredentials, path: Path | None = None) -> Path:
    path = path or credentials_path()
    parser = _read(path)
    if not parser.has_section(profile):
        parser.add_section(profile)
    parser.set(profile, "aws_access_key_id", creds.access_key_id)
    parser.set(profile, "aws_secret_access_key", creds.secret_access_key)
    if creds.session_token:
        parser.set(profile, "aws_session_token", creds.session_token)
    else:
        parser.remove_option(profile, "aws_session_token")
    if creds.expiration:
        parser.set(profile, EXPIRATION_KEY, creds.expiration.isoformat())
    _write(path, parser)
    return path


def ensure_profile_region(profile: str, region: str, path: Path | None = None) -> None:
    """Set the region in ~/.aws/config unless the user already chose one."""
    path = path or aws_config_path()
    parser = _read(path)
    section = profile if profile == "default" else f"profile {profile}"
    if parser.has_section(section) and parser.has_option(section, "region"):
        return
    if not parser.has_section(section):
        parser.add_section(section)
    parser.set(section, "region", region)
    _write(path, parser)


def read_profile(profile: str, path: Path | None = None) -> AwsCredentials | None:
    parser = _read(path or credentials_path())
    if not parser.has_section(profile) or not parser.has_option(profile, "aws_access_key_id"):
        return None
    get = lambda key: parser.get(profile, key, fallback=None)  # noqa: E731
    expiration = get(EXPIRATION_KEY)
    return AwsCredentials(
        get("aws_access_key_id"),
        get("aws_secret_access_key"),
        get("aws_session_token"),
        datetime.fromisoformat(expiration) if expiration else None,
    )


def expirations(path: Path | None = None) -> dict[str, datetime | None]:
    """Profiles in the credentials file and when (if known) they expire."""
    parser = _read(path or credentials_path())
    out: dict[str, datetime | None] = {}
    for section in parser.sections():
        value = parser.get(section, EXPIRATION_KEY, fallback=None)
        try:
            out[section] = datetime.fromisoformat(value) if value else None
        except ValueError:
            out[section] = None
    return out


def remaining(expiration: datetime | None) -> str:
    if expiration is None:
        return "unknown"
    if expiration.tzinfo is None:
        expiration = expiration.replace(tzinfo=timezone.utc)
    seconds = int((expiration - datetime.now(timezone.utc)).total_seconds())
    if seconds <= 0:
        return "expired"
    hours, rest = divmod(seconds, 3600)
    return f"{hours}h{rest // 60:02d}m" if hours else f"{rest // 60}m"
