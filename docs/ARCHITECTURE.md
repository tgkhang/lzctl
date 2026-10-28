# Architecture

How lzctl is structured and why. For *how to add things*, see [EXTENDING.md](EXTENDING.md).

## Module map

```text
src/lzctl/
├── cli.py              root click group; registers BUILTIN_MODULES and plugin entry points
├── sdk.py              stable public API (re-exports), the only import surface for plugins
├── config.py           Config / IdpConfig / Account model, validation, production detection
├── auth.py             LoginRunner: group by IdP URL → authenticate → pick roles → STS → chain
├── saml.py             assertion parsing (defusedxml), role selection
├── aws.py              STS calls, console federation URL
├── credentials.py      ~/.aws/credentials + ~/.aws/config read/write (atomic, 0600)
├── multi.py            for_each_account: accounts × regions thread pool, error explanation
├── prompts.py          Prompter: lazy username/password/MFA on stderr, keyring
├── shell.py            export syntax per shell, shell detection
├── output.py           table / json / csv rendering
├── providers/          IdP plug-ins
│   ├── base.py         Provider ABC, HTTP with TLS handling
│   ├── form.py         generic HTML form walker + PingFederate/AD FS/Keycloak presets
│   └── manual.py       paste/clipboard/file SAMLResponse
├── inventory/          resource inventory
│   ├── __init__.py     Collector type, registry, plugin loading
│   ├── collectors.py   built-in collectors (ec2, ebs, rds, s3, lambda, dynamodb, elb)
│   └── report.py       flattening + Excel writer
└── commands/           CLI commands; each module exports COMMANDS
    ├── _common.py      AppContext, target selection, safety helpers
    ├── setup.py        init, config, providers
    ├── login.py        login, env, status, whoami, console
    ├── accounts.py     accounts …
    ├── inventory.py    inventory
    └── ec2.py          ec2 list
```

Dependencies only point **downwards**: commands → (auth, multi, inventory, output) → (config, aws, credentials, saml, providers). Nothing in the lower layers imports click commands.

## Login flow

```text
lzctl login dev prod workload
        │
        ▼
resolve_targets ──► [dev, prod, workload(via dev)]
        │
with_parents ─────► ordered: dev, prod, workload   (cycle check)
        │
group direct accounts by (idp, build_idp_url(idp, account))
        │                         ┌──────────────────────────────┐
        ├── group 1 ─────────────►│ Provider.authenticate(url)    │──► SAMLResponse
        │                         └──────────────────────────────┘
        │   parse_roles → select_role per account → AssumeRoleWithSAML
        │
chained accounts, level by level (parallel within a level)
        │   AssumeRole(parent credentials, chain role)   [≤ 1 h]
        ▼
write_profile + ensure_profile_region   (or --env: print exports)
```

## Fan-out flow

```text
command → resolve_targets → for_each_account(app, accounts, task, regions)
             │
             ├─ fail fast: missing profiles → "run lzctl login X"
             ├─ warn: production accounts involved
             └─ ThreadPool(16): task(boto3.Session(profile), account, region) → rows
                    └─ per-job errors explained, others continue
           → echo_rows / write_xlsx
```

## Key design decisions

### D1. Write standard AWS files instead of running a credential daemon
**Decision:** Credentials go to `~/.aws/credentials` under one profile per account.
**Why:** Every AWS tool already understands this file, so there is nothing to integrate and nothing to keep running.
**Trade-off:** The keys sit on disk until they expire, protected by file permissions (0600) and short lifetimes. `credential_process` (roadmap) offers an on-demand alternative.

### D2. Python, not Go
**Decision:** Python ≥ 3.10 with boto3.
**Why:** boto3 covers every AWS API, it's easy for ops engineers to read and extend, and plugins are just packages. The original tool was Python too.
**Trade-off:** It needs a Python runtime (pipx makes this painless), and startup is slower than a Go binary. Standalone binaries are on the roadmap.

### D3. A generic form walker instead of one class per IdP
**Decision:** One `FormProvider` that walks HTML forms, plus thin presets that only set field names.
**Why:** Most enterprise IdPs are plain forms with different field names. Configuration (`options`) covers new IdPs without code.
**Trade-off:** JavaScript-only logins and push MFA need `manual` or a dedicated API provider.

### D4. One authentication per IdP URL
**Decision:** Group accounts by the *resolved* IdP URL.
**Why:** This gives one prompt for 50 accounts when the IdP issues all roles at once. When the URL contains the account (`url_params`), you naturally get a separate login per account. That covers the "prod and non-prod need separate logins" requirement without special cases.

### D5. Production is a tag, not a name
**Decision:** `defaults.production_tags` (default `env=prod*`) decides what counts as production.
**Why:** Guessing from names (`"prod" in name`) breaks on names like `nonprod` and on organisation-specific naming. Tags are explicit and configurable.

### D6. Safety for changes lives in the framework
**Decision:** `confirm_targets`, `dry_run_option` and `yes_option` live in the SDK, and the plan → dry-run → confirm → execute pattern is documented as mandatory.
**Why:** Future write commands (patching, cleanup) get consistent, reviewed safety, instead of each author inventing their own.

### D7. stdout for data, stderr for humans
**Why:** `eval "$(lzctl login --env)"`, `-o json | jq`, and `> report.csv` must keep working even with prompts and warnings.

### D8. Plugins through entry points; `lzctl.sdk` is the contract
**Why:** This is the standard Python mechanism, with no plugin manager to maintain. A single re-export module lets internals be refactored freely.

### D9. One boto3 session per fan-out job
**Why:** boto3 sessions aren't thread-safe. Creating them per job is cheap compared to the API calls.

## Error handling

- Expected failures raise `LzctlError` subclasses (`ConfigError`, `AuthError`, `CredentialsRejected`, `AwsError`). click renders them as one `Error:` line with exit code 1.
- In fan-out, errors are caught per job and explained by `multi.explain`. The command fails only if everything failed.
- `CredentialsRejected` also clears a keyring password that has stopped working.

## Testing strategy

- Pure logic (SAML parsing, role selection, URL templating, shell quoting, rendering) is unit-tested directly.
- Providers are tested with handwritten HTML pages through `FakeHttp`.
- Commands are tested end-to-end with click's `CliRunner`, a temporary config and AWS files, and `FakeBoto` / monkeypatched STS.
- No test touches the network, the real `~/.aws`, or the user's config.
