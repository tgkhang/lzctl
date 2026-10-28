"""Exceptions. All of them render as a clean "Error: ..." line on the CLI."""

import click


class LzctlError(click.ClickException):
    """Base class for expected, user-facing failures."""


class ConfigError(LzctlError):
    """The configuration file is missing, malformed or inconsistent."""


class AuthError(LzctlError):
    """Authentication with the identity provider failed."""


class CredentialsRejected(AuthError):
    """The IdP rejected the username/password (or MFA code)."""


class AwsError(LzctlError):
    """An AWS API call failed."""
