"""login / env / status / whoami / console."""

from __future__ import annotations

import webbrowser

import click

from ..auth import LoginResult, LoginRunner
from ..aws import AwsCredentials, caller_identity, console_url, session_for_profile
from ..config import IdpConfig
from ..credentials import (
    ensure_profile_region,
    expirations,
    read_profile,
    remaining,
    write_profile,
)
from ..errors import LzctlError
from ..output import echo_rows, output_option
from ..prompts import Prompter
from ..shell import SHELLS, eval_hint, format_env
from ._common import AppContext, pass_app, resolve_targets, target_options

shell_option = click.option("--shell", type=click.Choice(SHELLS),
                            help="Shell syntax for exported variables (default: auto-detect).")


def _env_vars(result: LoginResult) -> dict[str, str | None]:
    creds = result.credentials
    return {
        "AWS_ACCESS_KEY_ID": creds.access_key_id,
        "AWS_SECRET_ACCESS_KEY": creds.secret_access_key,
        "AWS_SESSION_TOKEN": creds.session_token,
        "AWS_REGION": result.region,
        "AWS_DEFAULT_REGION": result.region,
        "AWS_PROFILE": None,
    }


@click.command()
@target_options
@click.option("--idp", help="Identity provider to use (default: from config).")
@click.option("-r", "--role", help="Role ARN, exact role name or substring of the ARN.")
@click.option("-p", "--profile", help="Profile name to write (single account only).")
@click.option("-u", "--username", help="IdP username (default: config, then $USER/%USERNAME%).")
@click.option("-d", "--duration", type=click.IntRange(900, 43200), help="Session length in seconds.")
@click.option("--mfa-code", help="One-time code, to avoid the prompt.")
@click.option("--env", "as_env", is_flag=True,
              help="Print credentials as shell variables instead of writing ~/.aws/credentials.")
@shell_option
@click.option("--no-input", is_flag=True, help="Fail instead of prompting.")
@pass_app
def login(app: AppContext, targets, idp, role, profile, username, duration, mfa_code, as_env,
          shell, no_input):
    """Log in through your IdP and get temporary AWS credentials.

    \b
    lzctl login                       pick any role the IdP offers
    lzctl login dev prod              named accounts (one password/MFA prompt per IdP)
    lzctl login --tag env=nonprod     every account tagged env=nonprod
    lzctl login 'lz*'                 glob on account names
    eval "$(lzctl login dev --env)"   export variables instead of writing a profile
    """
    config = app.config

    def prompter_for(idp_cfg: IdpConfig) -> Prompter:
        return Prompter(
            idp_name=idp_cfg.name,
            username=username or idp_cfg.username or config.defaults.get("username"),
            use_keyring=idp_cfg.keyring,
            mfa_code=mfa_code,
            interactive=not no_input,
        )

    runner = LoginRunner(config, prompter_for, role_override=role, duration=duration, log=app.info)
    accounts = resolve_targets(config, targets, required=False)
    if idp:
        config.idp(idp)  # validate the name early
        for acct in accounts:
            acct.idp = idp
    if profile and len(accounts) > 1:
        raise click.UsageError("--profile can only be used with a single account")

    if accounts:
        results = runner.login(accounts)
        if profile:
            results[-1].account.profile = profile
    else:
        results = [runner.login_adhoc(config.idp(idp), profile)]

    if as_env:
        requested = [r for r in results if r.account.name in {a.name for a in accounts}] or results
        if len(requested) != 1:
            raise click.UsageError("--env works with exactly one account")
        click.echo(format_env(_env_vars(requested[-1]), shell))
        return

    rows = []
    for result in results:
        name = result.account.profile_name
        write_profile(name, result.credentials)
        ensure_profile_region(name, result.region)
        rows.append({"profile": name, "account": result.account.id, "role": result.role_arn,
                     "expires": remaining(result.credentials.expiration)})
    prod = [r.account.name for r in results if config.is_production(r.account)]
    if prod:
        app.warn(f"PRODUCTION credentials written for: {', '.join(prod)}")
    if not app.quiet:
        click.echo(err=True)
        echo_rows(rows, ["profile", "account", "role", "expires"])
        last = results[-1].account.profile_name
        click.echo(f"\nUse it:  {eval_hint(f'lzctl env {last}', shell)}", err=True)
        click.echo(f"     or:  aws --profile {last} sts get-caller-identity", err=True)


@click.command()
@click.argument("account", required=False)
@click.option("--credentials", "with_creds", is_flag=True,
              help="Export the keys themselves (for tools that ignore AWS_PROFILE).")
@click.option("--unset", is_flag=True, help="Clear all AWS_* variables lzctl sets.")
@shell_option
@pass_app
def env(app: AppContext, account, with_creds, unset, shell):
    """Print shell statements that switch to ACCOUNT's profile.

    \b
    bash/zsh:    eval "$(lzctl env dev)"
    fish:        lzctl env dev | source
    PowerShell:  lzctl env dev | Invoke-Expression
    """
    keys = ("AWS_PROFILE", "AWS_REGION", "AWS_DEFAULT_REGION", "AWS_ACCESS_KEY_ID",
            "AWS_SECRET_ACCESS_KEY", "AWS_SESSION_TOKEN")
    if unset:
        click.echo(format_env(dict.fromkeys(keys), shell))
        return
    if not account:
        raise click.UsageError("ACCOUNT is required (or pass --unset)")
    acct = app.config.find_account(account)
    profile = acct.profile_name if acct else account
    region = app.config.region_for(acct)
    variables: dict[str, str | None] = {"AWS_PROFILE": profile, "AWS_REGION": region,
                                        "AWS_DEFAULT_REGION": region}
    if with_creds:
        creds = read_profile(profile)
        if creds is None:
            raise LzctlError(f"No credentials for profile {profile!r}; run 'lzctl login {account}'")
        variables.update(AWS_PROFILE=None, AWS_ACCESS_KEY_ID=creds.access_key_id,
                         AWS_SECRET_ACCESS_KEY=creds.secret_access_key,
                         AWS_SESSION_TOKEN=creds.session_token)
    else:
        variables.update(AWS_ACCESS_KEY_ID=None, AWS_SECRET_ACCESS_KEY=None, AWS_SESSION_TOKEN=None)
    click.echo(format_env(variables, shell))


@click.command()
@target_options
@output_option
@pass_app
def status(app: AppContext, targets, fmt):
    """Show which accounts have valid credentials and for how long."""
    config = app.config
    accounts = resolve_targets(config, targets, required=False) or list(config.accounts.values())
    known = expirations()
    rows = []
    for acct in accounts:
        exp = known.get(acct.profile_name)
        state = remaining(exp) if acct.profile_name in known else "not logged in"
        rows.append({"account": acct.name, "id": acct.id, "profile": acct.profile_name,
                     "status": state, "expires": exp.isoformat() if exp else None,
                     "tags": acct.tags})
    echo_rows(rows, ["account", "id", "profile", "status", "tags"] if fmt == "table"
              else ["account", "id", "profile", "status", "expires", "tags"], fmt)


@click.command()
@click.argument("account", required=False)
@pass_app
def whoami(app: AppContext, account):
    """Call sts:GetCallerIdentity for ACCOUNT (default: current environment)."""
    acct = app.config.find_account(account) if account else None
    profile = acct.profile_name if acct else account
    ident = caller_identity(session_for_profile(profile))
    for key in ("Account", "Arn", "UserId"):
        click.echo(f"{key:8} {ident[key]}")


@click.command()
@click.argument("account")
@click.option("--print", "print_only", is_flag=True, help="Print the URL instead of opening it.")
@click.option("--service", default="", help="Console path to open, e.g. 'ec2' or 's3'.")
@pass_app
def console(app: AppContext, account, print_only, service):
    """Open the AWS web console signed in as ACCOUNT's profile."""
    acct = app.config.find_account(account)
    profile = acct.profile_name if acct else account
    creds = read_profile(profile)
    if creds is None:
        raise LzctlError(f"No credentials for profile {profile!r}; run 'lzctl login {account}'")
    region = app.config.region_for(acct)
    dest = f"https://{region}.console.aws.amazon.com/{service.strip('/')}/home?region={region}" \
        if service else f"https://{region}.console.aws.amazon.com/console/home?region={region}"
    url = console_url(AwsCredentials(creds.access_key_id, creds.secret_access_key,
                                     creds.session_token), destination=dest)
    if print_only or not webbrowser.open(url):
        click.echo(url)


COMMANDS = [login, env, status, whoami, console]
