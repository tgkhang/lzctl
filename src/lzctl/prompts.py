"""Interactive input. Everything goes to stderr so stdout stays machine-readable
(``eval "$(lzctl login dev --env)"`` must keep working)."""

from __future__ import annotations

import contextlib
import getpass
import os
from collections.abc import Sequence

import click

from .errors import AuthError

KEYRING_SERVICE = "lzctl"


def _keyring():
    try:
        import keyring  # optional dependency: pip install "lzctl[keyring]"
    except ImportError:
        return None
    return keyring


def default_username() -> str | None:
    return os.environ.get("USERNAME" if os.name == "nt" else "USER") or None


class Prompter:
    """Asks for credentials lazily, so providers only prompt for what the IdP asks for.

    Username and password are cached for the run; MFA codes are one-time and never cached.
    """

    def __init__(
        self,
        *,
        idp_name: str = "default",
        username: str | None = None,
        use_keyring: bool = False,
        mfa_code: str | None = None,
        interactive: bool = True,
    ):
        self.idp_name = idp_name
        self.interactive = interactive
        self.use_keyring = use_keyring
        self._username = username
        self._password: str | None = None
        self._password_prompted = False
        self._mfa_code = mfa_code

    @property
    def _service(self) -> str:
        return f"{KEYRING_SERVICE}:{self.idp_name}"

    def ask(self, label: str, *, default: str | None = None, hide: bool = False) -> str:
        if not self.interactive:
            raise AuthError(f"{label} is required but input is disabled (--no-input)")
        value = click.prompt(label, default=default, hide_input=hide, err=True, show_default=True)
        return str(value).strip() if not hide else str(value)

    def info(self, message: str) -> None:
        click.echo(message, err=True)

    @property
    def known_username(self) -> str | None:
        """Username if already known, without prompting."""
        return self._username

    def username(self) -> str:
        if not self._username:
            self._username = self.ask("Username", default=default_username())
        return self._username

    def password(self) -> str:
        if self._password is None and self.use_keyring:
            kr = _keyring()
            if kr is None:
                self.info("keyring is enabled but not installed: pip install 'lzctl[keyring]'")
            else:
                self._password = kr.get_password(self._service, self.username())
        if self._password is None:
            if self.interactive:
                # getpass reads from the terminal directly on every platform
                self._password = getpass.getpass(f"Password for {self.username()}: ", stream=None)
            else:
                self.ask("Password")
            self._password_prompted = True
        if not self._password:
            raise AuthError("Password cannot be empty")
        return self._password

    def mfa_code(self, hint: str = "") -> str:
        if self._mfa_code:
            code, self._mfa_code = self._mfa_code, None
            return code
        label = "MFA code" + (f" ({hint})" if hint else "")
        code = self.ask(label)
        if not code:
            raise AuthError("MFA code cannot be empty")
        return code

    def login_succeeded(self) -> None:
        if self.use_keyring and self._password_prompted and self._password:
            kr = _keyring()
            if kr is not None:
                kr.set_password(self._service, self.username(), self._password)
                self._password_prompted = False

    def password_rejected(self) -> None:
        if self.use_keyring and not self._password_prompted:
            kr = _keyring()
            if kr is not None:
                with contextlib.suppress(Exception):  # backend specific errors
                    kr.delete_password(self._service, self.username())
        self._password = None

    def choose(self, title: str, options: Sequence[str]) -> int:
        """Return the 0-based index of the chosen option."""
        if not self.interactive:
            raise AuthError(f"{title}: several choices and input is disabled")
        self.info(title)
        for i, option in enumerate(options, 1):
            self.info(f"  [{i}] {option}")
        return click.prompt("Selection", type=click.IntRange(1, len(options)), err=True) - 1
