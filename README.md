# lzctl

**Log in to many AWS accounts through any SAML 2.0 identity provider, then run commands across your whole landing zone.**

Many organisations run dozens or hundreds of AWS accounts (a "landing zone") behind a corporate SAML IdP such as PingFederate, AD FS or Keycloak. Getting CLI credentials usually means a browser, a role picker and copying keys, once per account. `lzctl` does it from the terminal, on Linux, macOS and Windows:

```console
$ lzctl login --tag env=nonprod
Authenticating with corp for dev, test, sandbox
Username [alice]:
Password for alice:
MFA code: 123456

PROFILE   ACCOUNT       ROLE                                    EXPIRES
dev       111111111111  arn:aws:iam::111111111111:role/Admin    1h00m
test      222222222222  arn:aws:iam::222222222222:role/Admin    1h00m
sandbox   333333333333  arn:aws:iam::333333333333:role/OrgAdmin 1h00m

$ lzctl ec2 list --tag env=nonprod --state running
ACCOUNT  REGION     INSTANCE_ID          NAME     STATE    TYPE      PRIVATE_IP  ...
dev      us-east-1  i-0abc123def4567890  web-1    running  t3.small  10.0.1.12
test     us-east-1  i-0fed987cba6543210  batch    running  m6i.large 10.1.4.7
```

## Features

- **One password, many accounts.** Accounts behind the same IdP share one login and one MFA prompt.
- **Account inventory.** Give accounts names and tags, then select them by name, glob (`'lz*-prod'`), tag (`--tag env=prod`) or `--all`.
- **`accounts discover`.** Log in once and import every account your IdP grants you a role in.
- **Hub → spoke role chaining.** Reach workload accounts by assuming a role from a hub account (`via: hub`), the usual AWS Organizations / Control Tower setup.
- **Pluggable IdPs.** PingFederate, AD FS, Keycloak, a generic HTML-form walker, and a `manual` mode that works with *any* IdP (push MFA, passkeys...).
- **Inventory reports.** `lzctl inventory` collects EC2, EBS, RDS, S3, Lambda, DynamoDB and load balancers across accounts and regions. Filter by resource tag, add tag columns, and export a table, JSON, CSV or an **Excel** workbook with a summary sheet.
- **Production safety.** Accounts tagged as production are flagged at login and in every cross-account command. Commands that change things require a typed confirmation for production.
- **Cross-account commands.** `ec2 list` and friends run across accounts and regions in parallel. Adding a new command is about 30 lines of code, and plugins are supported. See [docs/EXTENDING.md](docs/EXTENDING.md).
- **Shell-friendly.** `lzctl env dev` prints `export`, `set -gx`, `$env:` or `set` statements for bash/zsh, fish, PowerShell or cmd.
- **Console sign-in.** `lzctl console prod` opens the AWS web console with your CLI session.
- **Optional keychain.** Store your IdP password in macOS Keychain, Windows Credential Manager or Secret Service.
- **Writes standard files.** Credentials go to `~/.aws/credentials`, so the AWS CLI, SDKs, Terraform and so on just work.

## Install

Requires Python 3.10+. [pipx](https://pipx.pypa.io) or [uv](https://docs.astral.sh/uv/) installs it as an isolated CLI on every OS:

```bash
pipx install "git+https://github.com/tgkhang/lzctl"            # or
uv tool install "git+https://github.com/tgkhang/lzctl"
# with extras: OS keychain password storage, Excel inventory reports
pipx install "lzctl[keyring,excel] @ git+https://github.com/tgkhang/lzctl"
```

### Platform notes

- **macOS**: `brew install pipx` first if needed.
- **Linux**: `sudo apt install pipx` (Debian/Ubuntu) or `pip install --user pipx`. The `manual` provider reads the clipboard with `wl-paste`, `xclip` or `xsel`.
- **Windows**: `py -m pip install --user pipx && py -m pipx ensurepath`, then open a new terminal. PowerShell, cmd and Git Bash all work.

## Quick start

```bash
lzctl init                       # 1. describe your IdP (writes the config file)
lzctl accounts discover          # 2. import accounts the IdP gives you roles in
lzctl accounts rename 111111111111 dev
lzctl accounts tag dev --set env=nonprod
lzctl login dev                  # 3. get credentials
aws --profile dev sts get-caller-identity
```

Switch your shell to an account:

| Shell | Command |
| --- | --- |
| bash / zsh | `eval "$(lzctl env dev)"` |
| fish | `lzctl env dev \| source` |
| PowerShell | `lzctl env dev \| Invoke-Expression` |
| cmd | `for /f "delims=" %i in ('lzctl env dev') do %i` |

Handy aliases:

```bash
# ~/.bashrc or ~/.zshrc
lz() { eval "$(lzctl env "$@")"; }             # lz dev
```

```powershell
# $PROFILE
function lz { lzctl env @args | Invoke-Expression }
```

## Configuration

The config file lives at:

| OS | Path |
| --- | --- |
| Linux / macOS | `~/.config/lzctl/config.yaml` (honours `$XDG_CONFIG_HOME`) |
| Windows | `%APPDATA%\lzctl\config.yaml` |

Override it with `--config FILE` or `LZCTL_CONFIG`. `lzctl config path|show|edit` helps. A full annotated example is in [examples/config.example.yaml](examples/config.example.yaml):

```yaml
defaults:
  idp: corp
  region: eu-west-1
  username: alice

idps:
  corp:
    provider: pingfederate
    url: https://idp.example.com/idp/startSSO.ping?PartnerSpId=urn:amazon:webservices
    ca_bundle: ~/certs/corporate-root.pem   # only if your network inspects TLS
    keyring: true                            # remember the password in the OS keychain

accounts:
  hub:
    id: "111111111111"        # always quote account ids
    role: PlatformAdmin
    tags: {env: prod, lz: core}
  dev:
    id: "222222222222"
    via: hub                  # assume OrganizationAccountAccessRole from hub
    tags: {env: nonprod, lz: workloads}
```

### Identity providers

| `provider` | Use for | `url` |
| --- | --- | --- |
| `pingfederate` | PingFederate / PingOne, password + optional OTP | `.../idp/startSSO.ping?PartnerSpId=urn:amazon:webservices` |
| `adfs` | Microsoft AD FS forms authentication | `.../adfs/ls/IdpInitiatedSignOn.aspx?loginToRp=urn:amazon:webservices` |
| `keycloak` | Keycloak, password + optional OTP | `.../realms/REALM/protocol/saml/clients/amazon-aws` |
| `form` | Other form-based IdPs (Shibboleth, SimpleSAMLphp...); fields are auto-detected | IdP-initiated SSO URL |
| `manual` | **Anything else**: push MFA, passkeys, Okta/Entra ID with conditional access | optional |

The form-based providers accept `options` to override field detection:

```yaml
idps:
  custom:
    provider: form
    url: https://login.example.com/sso/aws
    options:
      username_fields: [j_username]
      password_fields: [j_password]
      otp_fields: [code]
      extra_fields: {_eventId: submit}
      error_markers: ["Invalid credentials"]
```

**Per-account IdP URLs.** Some IdPs need the account in the URL (`...&sn=NAME&acc=ID`). Use `url_params` with `{account_id}`, `{account_name}` or any key from the account's own `url_params`:

```yaml
idps:
  corp:
    provider: pingfederate
    url: https://idp.example.com/idp/startSSO.ping?PartnerSpId=urn%3Aamazon%3Awebservices
    url_params: {acc: "{account_id}", sn: "{sn}"}
accounts:
  lz001nonprod: {id: "123456789012", url_params: {sn: lz001nonprod}}
```

**The `manual` provider** opens the IdP in your browser. Before you pick a role, copy the `SAMLResponse` form field of the POST to `https://signin.aws.amazon.com/saml` from DevTools → Network, then press Enter: lzctl reads it from the clipboard. You can also pipe it (`pbpaste | lzctl login dev`) or point `LZCTL_SAML_FILE` at a file.

### Production accounts and separate logins

Accounts matching `defaults.production_tags` (default `env: prod*`) count as production. lzctl prints a warning when it writes their credentials or runs a command against them. Commands that change resources make you type a confirmation for them.

```yaml
defaults:
  production_tags: {env: "prod*", tier: critical}   # any match = production
```

Prod and non-prod often need **separate logins**, for example when the IdP URL carries the account (`url_params`) or the accounts sit behind different IdPs. lzctl handles this automatically. Accounts that resolve to the same IdP URL share one login, and each different URL gets its own password/MFA prompt. So `lzctl login nonprod-hub prod-hub` simply asks twice. When a session expires, every command tells you exactly which `lzctl login <account>` to run.

Already have role-chaining profiles in `~/.aws/config` (`role_arn` + `source_profile`)? Import them:

```bash
lzctl accounts import-aws-config --source-profile saml --dry-run
```

### Account fields

| Field | Meaning |
| --- | --- |
| `id` | 12-digit account id (**quote it** so YAML keeps leading zeros) |
| `role` | Role name, ARN or ARN substring to pick from the SAML roles. With `via`, the role to assume (default `defaults.chain_role` or `OrganizationAccountAccessRole`). |
| `via` | Parent account to chain from. Chained sessions last at most 1 hour (an AWS limit). |
| `idp` | IdP name (default `defaults.idp`) |
| `region` | Region written to `~/.aws/config` and used by commands |
| `profile` | Profile name to write (default: account name) |
| `tags` | Free-form key/values for `--tag` selection (glob values allowed) |
| `duration` | Session seconds (default: IdP's SessionDuration attribute, else 3600) |
| `external_id` | ExternalId for chained AssumeRole |
| `url_params` | Extra IdP URL query parameters (see above) |

## Commands

```text
lzctl init                         create a config file interactively
lzctl providers                    list IdP types (incl. plugins)
lzctl config path|show|edit

lzctl login [ACCOUNTS] [-t K=V] [--all]   get credentials (no account: pick any role)
        [-r ROLE] [-p PROFILE] [-d SECONDS] [--env] [--mfa-code CODE] [--no-input]
lzctl status [ACCOUNTS]            who is logged in and for how long
lzctl env ACCOUNT [--credentials] | --unset
lzctl whoami [ACCOUNT]
lzctl console ACCOUNT [--service ec2] [--print]

lzctl accounts list|add|remove|rename|tag|import|import-aws-config|discover
lzctl inventory [ACCOUNTS] [-s ec2,rds,...] [--region R]... [-f TAG=VALUE] [-c TAGKEY]
                [-o table|json|csv|xlsx] [--out reports/]
lzctl ec2 list [ACCOUNTS] [--region R]... [--state running] [-o table|json|csv]
```

Run `lzctl COMMAND --help` for details. `accounts import` reads CSV (`name,id,role,region,via,tags` with `tags` as `k=v;k=v`) or YAML. That includes the older `name: {sn: ..., acc: ...}` format.

## Inventory reports

```bash
lzctl inventory --list-services
lzctl inventory dev                                         # table on screen
lzctl inventory --tag env=nonprod -s ec2,rds,ebs -o xlsx    # reports/multi-account_inventory_20260101_120000.xlsx
lzctl inventory prod -f Application=billing -c Application -c CostCentre -o xlsx --out billing.xlsx
lzctl inventory --all -o json | jq '[.[] | select(.state=="stopped")]'
```

- `-f/--resource-tag K=V` keeps only resources with that tag (glob values, repeat to AND). `--tag` still selects *accounts*.
- `-c/--tag-column KEY` shows a resource tag as its own column. Set defaults with `defaults.inventory_tag_columns: [Application, Owner]`.
- The Excel workbook has a **Summary** sheet (resources per account and service) and one filterable sheet per service. It needs the `excel` extra.
- Inventory is read-only. Each service needs only `Describe*`/`List*` permissions; a missing permission skips that service with a warning.

## Extending

New commands, inventory collectors and identity providers can be built in or shipped as plugins. See **[docs/EXTENDING.md](docs/EXTENDING.md)** for the architecture, a 5-minute example, the safe pattern for commands that change things, and the `lzctl.sdk` API.

## Security notes

- Credentials are temporary STS keys written to `~/.aws/credentials` (mode `0600` on POSIX). Nothing is sent anywhere except your IdP and AWS STS.
- Passwords are kept in memory only, unless you enable `keyring`.
- Leave `verify_ssl` on. If a corporate proxy re-signs TLS, set `ca_bundle` to its root certificate instead. For AWS calls, set `AWS_CA_BUNDLE` too.
- See [SECURITY.md](SECURITY.md) for reporting vulnerabilities.

## How does this compare to...?

There are good tools in this space. Pick the one that fits:

| Tool | Best at |
| --- | --- |
| [saml2aws](https://github.com/Versent/saml2aws) | The most IdP integrations, single Go binary, one account at a time |
| [Granted](https://github.com/fwdcloudsec/granted) | Fast profile switching, especially with **IAM Identity Center** |
| [aws-vault](https://github.com/ByteNess/aws-vault) | Keeping long-lived IAM user keys in the OS keychain |
| [awsrun](https://github.com/fidelity/awsrun) | A Python framework for running your own code across accounts |
| [Steampipe](https://steampipe.io) | SQL queries over cloud APIs |

`lzctl` focuses on the **many-accounts workflow**: one login for many accounts, an inventory with tags and globs, hub/spoke chaining, discovery, inventory reports, and commands that fan out across accounts, with production safety built in. See [docs/MARKET_RESEARCH.md](docs/MARKET_RESEARCH.md) for the full comparison, including paid products.

## Documentation and roadmap

- [docs/SRS.md](docs/SRS.md): requirements and their implementation status
- [docs/ROADMAP.md](docs/ROADMAP.md): what's next (PyPI release, `credential_process`, Okta/Entra/Identity Center, patching, `exec`, more collectors)
- [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md) · [docs/EXTENDING.md](docs/EXTENDING.md)

## Contributing

See [CONTRIBUTING.md](CONTRIBUTING.md). It covers dev setup, tests, and how to write a provider or command plugin.

## License

[MIT](LICENSE)
