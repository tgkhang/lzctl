"""The public API for lzctl plugins and new commands.

Import from here, not from internal modules: everything listed in ``__all__`` is
kept backwards compatible within a major version. See docs/EXTENDING.md.

    from lzctl.sdk import pass_app, target_options, resolve_targets, for_each_account
"""

from .aws import AwsCredentials, session_for_profile
from .commands._common import (
    AppContext,
    confirm_targets,
    dry_run_option,
    parse_tags,
    pass_app,
    resolve_targets,
    target_options,
    yes_option,
)
from .config import Account, Config, IdpConfig
from .errors import AuthError, AwsError, ConfigError, CredentialsRejected, LzctlError
from .inventory import Collector, tags_of
from .multi import EXPIRED_CODES, explain, for_each_account
from .output import echo_rows, output_option, render
from .prompts import Prompter
from .providers.base import Provider
from .providers.form import FormProvider, FormRules

__all__ = [
    # CLI plumbing
    "AppContext", "pass_app", "target_options", "resolve_targets", "parse_tags",
    "dry_run_option", "yes_option", "confirm_targets",
    # running across accounts
    "for_each_account", "explain", "EXPIRED_CODES", "session_for_profile", "AwsCredentials",
    # output
    "echo_rows", "output_option", "render",
    # config model
    "Account", "Config", "IdpConfig",
    # extension base classes
    "Provider", "FormProvider", "FormRules", "Prompter", "Collector", "tags_of",
    # errors
    "LzctlError", "ConfigError", "AuthError", "CredentialsRejected", "AwsError",
]
