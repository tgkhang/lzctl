"""init / config / providers."""

from __future__ import annotations

import click
import yaml

from .. import providers
from ..config import DEFAULT_REGION, Config
from ..errors import ConfigError
from ..output import echo_rows
from ..prompts import default_username
from ._common import AppContext, pass_app

URL_HINTS = {
    "pingfederate": "https://idp.example.com/idp/startSSO.ping?PartnerSpId=urn:amazon:webservices",
    "adfs": "https://adfs.example.com/adfs/ls/IdpInitiatedSignOn.aspx?loginToRp=urn:amazon:webservices",
    "keycloak": "https://sso.example.com/realms/REALM/protocol/saml/clients/amazon-aws",
    "form": "https://idp.example.com/path/to/aws/sso/start",
    "manual": "(optional) URL that starts AWS sign-in in your browser",
}


@click.command()
@click.option("--force", is_flag=True, help="Overwrite an existing config file.")
@pass_app
def init(app: AppContext, force):
    """Create a config file interactively."""
    path = app.config_path
    if path.exists() and not force:
        raise ConfigError(f"{path} already exists (use --force to overwrite)")
    names = sorted(providers.available())
    click.echo("Providers: " + ", ".join(names), err=True)
    provider = click.prompt("Provider", type=click.Choice(names), default="pingfederate", err=True)
    url = click.prompt(f"IdP login URL\n  e.g. {URL_HINTS.get(provider, '')}\n",
                       default="" if provider == "manual" else None, err=True)
    idp_name = click.prompt("Name for this IdP", default="default", err=True)
    username = click.prompt("Username", default=default_username() or "", err=True)
    region = click.prompt("Default AWS region", default=DEFAULT_REGION, err=True)

    idp: dict = {"provider": provider, "url": url}
    if click.confirm("Does your network inspect TLS (corporate proxy with its own CA)?",
                     default=False, err=True):
        idp["ca_bundle"] = click.prompt("Path to the CA bundle (PEM)", err=True)
    if click.confirm("Store your password in the OS keychain? (needs lzctl[keyring])",
                     default=False, err=True):
        idp["keyring"] = True

    defaults = {"idp": idp_name, "region": region}
    if username:
        defaults["username"] = username
    config = Config(path, {"defaults": defaults, "idps": {idp_name: idp}, "accounts": {}})
    config.save()
    click.echo(f"\nWrote {path}\nNext: 'lzctl accounts discover' or 'lzctl accounts add NAME "
               "--id 123456789012', then 'lzctl login NAME'.", err=True)


@click.group("config")
def config_group():
    """Inspect the config file."""


@config_group.command()
@pass_app
def path(app: AppContext):
    """Print the config file path."""
    click.echo(str(app.config_path))


@config_group.command()
@pass_app
def show(app: AppContext):
    """Print the effective config."""
    if not app.config.exists:
        raise ConfigError(f"No config at {app.config_path}; run 'lzctl init'")
    click.echo(yaml.safe_dump(app.config.data, sort_keys=False).rstrip())


@config_group.command()
@pass_app
def edit(app: AppContext):
    """Open the config file in $EDITOR."""
    if not app.config_path.exists():
        raise ConfigError(f"No config at {app.config_path}; run 'lzctl init'")
    click.edit(filename=str(app.config_path))
    Config.load(app.config_path)  # validate
    app.info("Config is valid")


@click.command("providers")
def providers_cmd():
    """List available identity provider types (built-in and plugins)."""
    rows = []
    for name, cls in sorted(providers.available().items()):
        description = getattr(cls, "description", "") or "(plugin)"
        rows.append({"provider": name, "description": description})
    echo_rows(rows, ["provider", "description"])


COMMANDS = [init, config_group, providers_cmd]
