# Extending lzctl: adding new CLI functions

This guide is for adding new functionality: a new command (such as `s3 ls`, `iam audit` or patching), an inventory collector, or an identity provider. You can build it into lzctl itself or ship it as a separate plugin package.

- [1. How lzctl is put together](#1-how-lzctl-is-put-together)
- [2. Pick the right extension point](#2-pick-the-right-extension-point)
- [3. A read-only command in 5 minutes](#3-a-read-only-command-in-5-minutes)
- [4. Commands that change things (patching, cleanup, ...)](#4-commands-that-change-things)
- [5. Built-in or plugin?](#5-built-in-or-plugin)
- [6. Inventory collectors](#6-inventory-collectors)
- [7. Identity providers](#7-identity-providers)
- [8. The SDK reference](#8-the-sdk-reference)
- [9. Testing](#9-testing)
- [10. Checklist](#10-checklist)

---

## 1. How lzctl is put together

```text
            ┌──────────────────────────── lzctl CLI (click) ────────────────────────────┐
 commands:  │ init  login  env  status  accounts …  inventory  ec2 …   <your plugins>    │
            └──────┬───────────────┬───────────────────┬─────────────────────┬──────────┘
                   │               │                   │                     │
  lzctl.sdk ──►  config        auth (login)        multi.for_each_account   output
  (stable API)   accounts,     IdP → SAML →        accounts × regions in     table/json/csv
                 tags, prod    STS → chaining      parallel, per-account     (xlsx for
                 detection          │              error handling            inventory)
                                    ▼
                              providers/  (pingfederate, adfs, keycloak, form, manual, <plugin>)
```

There are two halves:

1. **Getting credentials.** `lzctl login` writes one AWS profile per account into `~/.aws/credentials`.
2. **Using them.** Every other command looks the account up in the config, opens `boto3.Session(profile_name=account.profile_name)`, and calls AWS.

This means **a new command never has to deal with SAML, IdPs or STS.** It works with accounts and boto3 sessions only.

## 2. Pick the right extension point

| You want to... | Write a... | Where |
| --- | --- | --- |
| Add `lzctl something ...` | **command** (click) | `src/lzctl/commands/` or a plugin (`lzctl.commands` entry point) |
| Add a resource type to `lzctl inventory` (e.g. EKS clusters) | **collector** | `src/lzctl/inventory/collectors.py` or a plugin (`lzctl.collectors`) |
| Log in through a new kind of IdP | **provider** | `src/lzctl/providers/` or a plugin (`lzctl.providers`) |
| Support a new form-based IdP | **config only**: `provider: form` + `options` | your config file |

## 3. A read-only command in 5 minutes

Example: list S3 buckets in any set of accounts.

```python
# src/lzctl/commands/s3.py   (or your plugin module)
import click

from lzctl.sdk import echo_rows, for_each_account, output_option, pass_app, resolve_targets, target_options


def _buckets(session, account, region):
    """Runs once per (account, region), in a worker thread, with that account's session."""
    s3 = session.client("s3", region_name=region)
    for bucket in s3.list_buckets()["Buckets"]:
        yield {"account": account.name, "bucket": bucket["Name"], "created": bucket["CreationDate"]}


@click.group()
def s3():
    """S3 commands across accounts."""


@s3.command("ls")
@target_options          # adds: [ACCOUNTS]...  --tag K=V  --all
@output_option           # adds: -o table|json|csv
@pass_app                # injects AppContext (config, quiet, info/warn)
def ls(app, targets, fmt):
    """List S3 buckets in the selected accounts."""
    accounts = resolve_targets(app.config, targets)       # names, globs, tags, --all
    rows = for_each_account(app, accounts, _buckets)       # parallel, errors reported per account
    echo_rows(rows, ["account", "bucket", "created"], fmt)


COMMANDS = [s3]
```

Register a built-in by adding the module to `BUILTIN_MODULES` in [src/lzctl/cli.py](../src/lzctl/cli.py):

```python
from .commands import accounts, ec2, inventory, login, s3, setup
BUILTIN_MODULES = (setup, login, accounts, inventory, ec2, s3)
```

Now this works:

```bash
lzctl s3 ls --tag env=prod -o csv > buckets.csv
lzctl s3 ls 'lz*' dev
```

### What you get for free

| Feature | Comes from |
| --- | --- |
| Selection by name, id, glob, `--tag`, `--all` | `target_options` + `resolve_targets` |
| Parallelism (16 workers), one boto3 session per job (thread-safe) | `for_each_account` |
| "session expired, run `lzctl login dev`" messages, other accounts keep going | `for_each_account` / `explain` |
| Production-account warning | `for_each_account` (uses `defaults.production_tags`) |
| `-o table/json/csv`, results on stdout, messages on stderr | `output_option` + `echo_rows` |
| `--region` fan-out | pass `regions=` to `for_each_account` |

Multi-region: add `@click.option("--region", "regions", multiple=True)` and pass `regions=regions`. Each account defaults to its configured region.

## 4. Commands that change things

Anything that writes (patching, stopping instances, deleting snapshots, rotating keys...) **must** follow these four steps:

```python
from lzctl.sdk import (LzctlError, confirm_targets, dry_run_option, echo_rows, for_each_account,
                       pass_app, resolve_targets, target_options, yes_option)


@click.command("stop-idle")
@target_options
@dry_run_option          # --dry-run
@yes_option              # -y/--yes for scripts and CI
@pass_app
def stop_idle(app, targets, dry_run, yes):
    """Stop instances tagged AutoStop=true."""
    accounts = resolve_targets(app.config, targets)

    # 1. PLAN (read-only): find exactly what would change
    plan = for_each_account(app, accounts, find_candidates)
    echo_rows(plan, ["account", "region", "instance", "name"])
    if not plan:
        raise LzctlError("Nothing to do")

    # 2. DRY RUN: stop here if asked
    if dry_run:
        app.info(f"Dry run: would stop {len(plan)} instance(s)")
        return

    # 3. CONFIRM: lists accounts, marks PRODUCTION, requires typed confirmation for prod,
    #    refuses to run without a terminal unless --yes
    affected = [a for a in accounts if any(p["account"] == a.name for p in plan)]
    confirm_targets(app, affected, f"stop {len(plan)} instance(s)", yes=yes)

    # 4. EXECUTE only the planned items, and report what happened
    rows = for_each_account(app, affected, lambda s, a, r: stop(s, a, r, plan))
    echo_rows(rows, ["account", "region", "instance", "result"])
```

Rules:
- **Execute only what was planned.** Don't re-query and act on new results.
- Never make `--yes` the default. Never skip `confirm_targets` for production.
- Make the action idempotent where possible (re-running is safe).
- Prefer AWS's own guard rails, such as `MaxConcurrency`/`MaxErrors` for SSM, or `DryRun=True` for EC2 APIs that support it.
- Production is decided by `defaults.production_tags` (default `env: prod*`). Users control it in config, so don't hard-code account names.

## 5. Built-in or plugin?

| | Built-in (`src/lzctl/commands/`) | Plugin (separate package) |
| --- | --- | --- |
| Good for | General AWS features useful to everyone | Company-specific workflows, experimental, private |
| Ships with | lzctl releases | Your own repo / internal index |
| Install | — | `pipx inject lzctl my-plugin` or `pip install my-plugin` |

A plugin is an ordinary Python package with an entry point:

```toml
# pyproject.toml of your plugin
[project]
name = "lzctl-mycompany"
dependencies = ["lzctl>=0.1"]

[project.entry-points."lzctl.commands"]
s3 = "lzctl_mycompany.s3:s3"            # name = "module:click_object"

[project.entry-points."lzctl.collectors"]
eks = "lzctl_mycompany.collectors:EKS"   # a lzctl.sdk.Collector instance

[project.entry-points."lzctl.providers"]
myidp = "lzctl_mycompany.idp:MyIdp"      # a lzctl.sdk.Provider subclass
```

- Built-in names win over plugins with the same name.
- A plugin that fails to import prints a warning, and the rest of the CLI still works.
- **Only import from `lzctl.sdk`.** Internal modules may change between versions.

**Keep company-internal things in a plugin**, such as your IdP quirks, naming rules, ticket references and internal roles. The open-source core stays generic, and you can still have everything at work.

## 6. Inventory collectors

A collector returns resources for one account and region. `lzctl inventory` handles everything else: fan-out, tag filters, tag columns, and table/JSON/CSV/Excel output.

Built-in (in [src/lzctl/inventory/collectors.py](../src/lzctl/inventory/collectors.py)):

```python
from . import collector, tags_of

@collector("eks", "EKS clusters", ("version", "endpoint_public"))
def eks_clusters(session, region):
    eks = session.client("eks", region_name=region)
    for page in eks.get_paginator("list_clusters").paginate():
        for name in page["clusters"]:
            c = eks.describe_cluster(name=name)["cluster"]
            yield {
                # base keys, used by every report
                "id": name, "name": name, "state": c["status"],
                "created": c["createdAt"].strftime("%Y-%m-%d %H:%M"),
                "tags": c.get("tags", {}),            # dict, used by --resource-tag / --tag-column
                # your columns, as declared in the decorator
                "version": c["version"],
                "endpoint_public": c["resourcesVpcConfig"]["endpointPublicAccess"],
            }
```

As a plugin, create the object yourself:

```python
from lzctl.sdk import Collector
EKS = Collector("eks", "EKS clusters", eks_clusters, columns=("version", "endpoint_public"))
```

Rules: use paginators, stay read-only, return `tags` as a dict (`tags_of()` converts AWS `[{Key, Value}]` lists), and set `global_service=True` for global services such as S3 or IAM so they are collected once per account. Catch `ClientError` around optional extra calls (like tag lookups) so one missing permission doesn't drop the whole collector.

## 7. Identity providers

Most IdPs need **no code**. Use `provider: form` with `options` (field names, extra fields, error strings). See the README. Write a provider only for API-based logins (Okta Authn API, Entra ID, Duo, ...):

```python
from lzctl.sdk import AuthError, CredentialsRejected, Provider

class OktaApi(Provider):
    name = "okta-api"
    description = "Okta via the Authn API"

    def authenticate(self, url, prompter):
        r = self.request("POST", f"{self.idp.options['org_url']}/api/v1/authn",
                         json={"username": prompter.username(), "password": prompter.password()})
        if r.status_code == 401:
            raise CredentialsRejected("Okta rejected the password")   # clears a saved keyring password
        ...
        return saml_response_base64
```

- `self.request()` gives you TLS/CA-bundle handling and readable network errors. `self.idp.options` holds any extra config.
- `prompter.username()` / `password()` / `mfa_code()` ask only when called, and handle keyring and `--no-input`.
- Raise `CredentialsRejected` for wrong credentials and `AuthError` for everything else.

## 8. The SDK reference

`from lzctl.sdk import ...`:

| Name | What it is |
| --- | --- |
| `pass_app` | click decorator that injects `AppContext` (`.config`, `.quiet`, `.info(msg)`, `.warn(msg)`) |
| `target_options` | adds `[ACCOUNTS]... --tag/-t --all`; your function receives `targets` |
| `resolve_targets(config, targets, required=True)` | turns `targets` into `list[Account]` |
| `for_each_account(app, accounts, task, regions=(), max_workers=16)` | runs `task(session, account, region)` in parallel and returns all yielded rows |
| `explain(err, account)` / `EXPIRED_CODES` | friendly per-account error text / expired-credential error codes |
| `dry_run_option`, `yes_option`, `confirm_targets(app, accounts, action, yes=)` | safety for commands that change things |
| `output_option`, `echo_rows(rows, columns, fmt)`, `render(...)` | standard output formats |
| `parse_tags(["K=V"])` | `{"K": "V"}` for your own tag options |
| `session_for_profile(profile, region)` | a boto3 session with a friendly "not logged in" error |
| `Account` | `.name .id .role .via .region .tags .profile_name` |
| `Config` | `.accounts .idps .defaults .region_for(a) .is_production(a) .find_account(key)` |
| `Collector`, `tags_of` | inventory extension |
| `Provider`, `FormProvider`, `FormRules`, `Prompter` | IdP extension |
| `LzctlError`, `ConfigError`, `AuthError`, `CredentialsRejected`, `AwsError` | raise these for clean `Error: ...` output |

## 9. Testing

Tests must not call AWS or a real IdP. See `tests/` for patterns:

- **Commands**: `click.testing.CliRunner().invoke(cli, [...])`, with `LZCTL_CONFIG` pointing at a temporary config, and the `aws_files` fixture so `~/.aws` is never touched.
- **AWS calls**: monkeypatch `boto3.Session` with `FakeBoto` from `tests/conftest.py`, which returns canned API responses and paginators.
- **Providers**: feed handwritten HTML pages through `FakeHttp`.

```python
def test_s3_ls(run, monkeypatch):
    monkeypatch.setattr("boto3.Session", FakeBoto.factory(
        {"s3": {"list_buckets": {"Buckets": [{"Name": "b1", "CreationDate": "2024-01-01"}]}}}))
    assert "b1" in run("s3", "ls", "dev").output
```

## 10. Checklist

- [ ] Results go to **stdout**. Prompts, progress and warnings go to **stderr** (`app.info` / `app.warn`).
- [ ] Expected failures raise `LzctlError` (or a subclass), never print a traceback.
- [ ] Uses `target_options` + `resolve_targets` + `for_each_account`, not custom loops.
- [ ] Supports `-o table|json|csv` for listing commands.
- [ ] Paginates every list API.
- [ ] Commands that change things: plan → `--dry-run` → `confirm_targets` → execute the plan only.
- [ ] Nothing organisation-specific in core: no account ids, hostnames or role names.
- [ ] Tests without network access, and the docs (README / this guide / CHANGELOG) updated.
