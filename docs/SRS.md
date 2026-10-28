# Software Requirements Specification: lzctl

| | |
| --- | --- |
| Document | Software Requirements Specification (SRS) |
| Product | lzctl, SAML 2.0 login and multi-account tooling for AWS |
| Version | 0.1 (covers lzctl 0.1.x and planned work) |
| Status | Living document, updated with each release |
| Structure | Loosely follows ISO/IEC/IEEE 29148 |

**Requirement status keys** used throughout:

- ✅ **Implemented**: in the current code, covered by tests where noted
- 🟡 **Partial**: implemented with known limitations
- 🔜 **Planned**: accepted for a future release (see [ROADMAP.md](ROADMAP.md))
- 💡 **Proposed**: under discussion, not committed

Priority: **M** = must, **S** = should, **C** = could.

---

## 1. Introduction

### 1.1 Purpose

This document defines what lzctl must do (functional requirements), how well it must do it (non-functional requirements), and the constraints it works within. It is the reference for contributors deciding whether a change fits the product, and for reviewers checking that a release meets its requirements.

### 1.2 Scope

lzctl is a command-line tool. It:

1. authenticates a person against a SAML 2.0 identity provider (IdP) and exchanges the SAML assertion for temporary AWS credentials, for one or **many** AWS accounts in one run;
2. keeps an **inventory of AWS accounts** (names, ids, tags, how to reach them) so they can be selected by name, pattern or tag;
3. runs **read-only and write operations across many accounts and regions** in parallel (for example EC2 listing and resource inventory reports);
4. is **extensible**: new commands, inventory collectors and IdP providers can be added built-in or as plugins.

Out of scope:
- managing IdP configuration or AWS IAM/SAML provider setup;
- long-lived IAM user access keys (other tools handle these);
- a graphical user interface;
- a hosted service or server component. lzctl runs only on the user's machine.

### 1.3 Definitions

| Term | Meaning |
| --- | --- |
| **IdP** | Identity provider that issues SAML assertions (PingFederate, AD FS, Keycloak, Okta, Entra ID, ...) |
| **SAML assertion / SAMLResponse** | Signed XML document from the IdP, base64-encoded, listing AWS roles the user may assume |
| **STS** | AWS Security Token Service; `AssumeRoleWithSAML` and `AssumeRole` issue temporary credentials |
| **Landing zone** | A multi-account AWS environment (often AWS Organizations / Control Tower) |
| **Hub / spoke** | Pattern where users log in to a hub account and assume roles into spoke (workload) accounts |
| **Role chaining** | Assuming a role using credentials that came from another assumed role (max 1 h session) |
| **Profile** | Named credential set in `~/.aws/credentials` / `~/.aws/config` |
| **Fan-out** | Running the same operation against many account × region pairs |
| **Collector** | Function that lists one resource type in one account/region for the inventory |
| **Provider** | Plug-in that turns credentials and an IdP URL into a SAMLResponse |
| **Production account** | An account matching `defaults.production_tags` (default `env=prod*`) |

### 1.4 References

- [README.md](../README.md): user documentation
- [EXTENDING.md](EXTENDING.md): developer guide for new commands, collectors and providers
- [ARCHITECTURE.md](ARCHITECTURE.md): design and key decisions
- [ROADMAP.md](ROADMAP.md): planned work
- [MARKET_RESEARCH.md](MARKET_RESEARCH.md): comparable products
- AWS STS API reference: `AssumeRoleWithSAML`, `AssumeRole`
- OASIS SAML 2.0 core specification

---

## 2. Overall description

### 2.1 Product perspective

lzctl sits between three external systems and the user's existing AWS tooling:

```text
  ┌────────┐  username/password/MFA   ┌────────────┐
  │  User  │ ───────────────────────► │    IdP     │  (PingFederate, AD FS, Keycloak, any via browser)
  └───┬────┘                          └─────┬──────┘
      │ lzctl CLI                           │ SAMLResponse
      ▼                                     ▼
  ┌──────────────────────────────────────────────┐   AssumeRoleWithSAML / AssumeRole   ┌──────────┐
  │                     lzctl                    │ ──────────────────────────────────► │ AWS STS  │
  │  config (accounts, tags)  ·  fan-out engine  │ ◄────────────── temp credentials ── └──────────┘
  └───────┬───────────────────────────┬──────────┘
          │ writes                     │ Describe*/List* (+ writes for gated commands)
          ▼                            ▼
  ~/.aws/credentials, ~/.aws/config    AWS service APIs (EC2, RDS, S3, ...)
          │
          ▼
  AWS CLI, SDKs, Terraform, ... (unchanged; use the profiles lzctl writes)
```

It **complements** the AWS CLI and SDKs rather than replacing them. Credentials go into the standard files, so every other tool works unchanged.

### 2.2 Product functions (summary)

| Area | Functions |
| --- | --- |
| Setup | Interactive `init`; config `path/show/edit`; `providers` list |
| Authentication | `login` to one or many accounts, ad-hoc role pick, `--env` output, keyring |
| Account inventory | `accounts list/add/remove/rename/tag/import/import-aws-config/discover` |
| Session tools | `status`, `env`, `whoami`, `console` |
| Fan-out operations | `ec2 list`, `inventory` (table/JSON/CSV/Excel) |
| Safety | Production detection, typed confirmation for changes, dry-run convention |
| Extensibility | `lzctl.sdk` API; plugin entry points for commands, collectors, providers |

### 2.3 User classes

| User class | Description | Key needs |
| --- | --- | --- |
| **Cloud / platform engineer** (primary) | Works across 10–500 accounts daily | One login for many accounts; switching quickly; fan-out queries |
| **Developer** | Uses 1–5 accounts | Simple `login dev`; works on their OS; little configuration |
| **Operations / support** | Answers tickets: "what runs in account X with tag Y?" | Inventory reports in Excel; read-only safety; clear prod warnings |
| **Small company / individual** | One IdP (often Keycloak or a hosted IdP), a few accounts | Free, easy install, no server |
| **Contributor / plugin author** | Extends lzctl | Stable SDK, docs, tests that run offline |

### 2.4 Operating environment

- **OS:** Linux, macOS, Windows 10/11 (PowerShell, cmd, Git Bash, WSL).
- **Runtime:** Python ≥ 3.10, installed with pipx, uv or pip.
- **Network:** HTTPS to the IdP, AWS STS, AWS sign-in (console), and AWS service endpoints. It must work behind TLS-inspecting corporate proxies when given a CA bundle.

### 2.5 Design and implementation constraints

- C-1: Credentials are written only in the standard AWS shared-file formats.
- C-2: There is no server component and no telemetry.
- C-3: Dependencies must be permissively licensed (MIT/BSD/Apache/MPL) and widely used. Currently: boto3, requests, beautifulsoup4, click, PyYAML, defusedxml; optionally keyring and openpyxl.
- C-4: The core must contain nothing specific to one organisation. Such behaviour goes into configuration or plugins.
- C-5: The public extension API is `lzctl.sdk`. Other modules are internal.

### 2.6 Assumptions and dependencies

- A-1: The organisation's IdP is federated with AWS IAM through SAML 2.0 (an IAM SAML provider plus roles trusting it).
- A-2: For role chaining, spoke accounts have a role trusting the hub role (for example `OrganizationAccountAccessRole`).
- A-3: Form-based IdPs present HTML forms that work without JavaScript. Otherwise the `manual` provider is used.
- A-4: Push-only MFA (number matching, Duo push) cannot be automated by the form walker.

---

## 3. Functional requirements

### 3.1 Configuration (CFG)

| ID | Requirement | Pri | Status |
| --- | --- | --- | --- |
| CFG-1 | The system shall store configuration in a YAML file at a per-OS default location (`%APPDATA%\lzctl\config.yaml` on Windows, `$XDG_CONFIG_HOME/lzctl/config.yaml` or `~/.config/lzctl/config.yaml` elsewhere), overridable by `--config` / `LZCTL_CONFIG`. | M | ✅ |
| CFG-2 | The configuration shall define `defaults`, named `idps` and named `accounts`. | M | ✅ |
| CFG-3 | Account ids shall be validated as 12-digit strings. Unquoted YAML integers shall be zero-padded. | M | ✅ `test_config` |
| CFG-4 | References (`via`, `idp`, `defaults.idp`) shall be validated on load, with clear errors. | M | ✅ `test_validation` |
| CFG-5 | `lzctl init` shall create a working config interactively (provider, URL, username, region, CA bundle, keyring). | S | ✅ |
| CFG-6 | `lzctl config path/show/edit` shall locate, print and edit the config. Edits are validated after saving. | S | ✅ |
| CFG-7 | Saving shall preserve unknown top-level keys. | S | ✅ |
| CFG-8 | Saving shall preserve YAML comments. | C | 🔜 (needs a round-trip YAML library) |
| CFG-9 | A JSON Schema for the config shall be published for editor auto-completion. | C | 💡 |

### 3.2 Authentication (AUTH)

| ID | Requirement | Pri | Status |
| --- | --- | --- | --- |
| AUTH-1 | The system shall authenticate against an IdP using a configurable provider and return a base64 SAMLResponse. | M | ✅ |
| AUTH-2 | Built-in providers: `pingfederate`, `adfs`, `keycloak`, generic `form`, `manual`. | M | ✅ `test_providers` |
| AUTH-3 | The `form` provider shall walk HTML forms, keep hidden fields, auto-detect username/password/OTP fields, and allow overriding field names, extra fields and error markers through `options`. | M | ✅ |
| AUTH-4 | The system shall detect rejected passwords and rejected MFA codes (the same form returned again, or an error marker), and report them without prompting again. | M | ✅ `test_wrong_password_detected`, `test_wrong_otp_detected` |
| AUTH-5 | The `manual` provider shall accept a SAMLResponse from a file, stdin or the clipboard (macOS, Windows, Linux Wayland/X11), including URL-encoded values. | M | ✅ |
| AUTH-6 | Credentials shall be requested lazily: only the fields the IdP asks for are prompted. | M | ✅ |
| AUTH-7 | Accounts that resolve to the same IdP URL shall share one authentication per run. Different URLs shall authenticate separately. | M | ✅ `test_login_single_password_and_chaining` |
| AUTH-8 | IdP URLs shall support per-account query parameters (`url_params` templated with `{account_id}`, `{account_name}` and account keys). | M | ✅ `test_idp_url_templating` |
| AUTH-9 | Passwords may be stored in and read from the OS keychain (`keyring: true`). A rejected stored password shall be deleted. | S | ✅ |
| AUTH-10 | Non-interactive mode (`--no-input`) shall fail instead of prompting. `--mfa-code` shall supply a code. | S | ✅ |
| AUTH-11 | TLS verification shall be on by default. A custom CA bundle shall be configurable per IdP. Disabling verification shall print a warning. | M | ✅ |
| AUTH-12 | Providers shall be pluggable through the `lzctl.providers` entry point group. | M | ✅ |
| AUTH-13 | API-based providers for Okta and Microsoft Entra ID. | S | 🔜 |
| AUTH-14 | A browser-capture provider (local listener or embedded browser) so that `manual` needs no DevTools. | S | 🔜 |
| AUTH-15 | AWS IAM Identity Center (SSO OIDC device flow) as a provider, so one tool serves both SAML and Identity Center users. | S | 🔜 |

### 3.3 Role selection and credentials (CRED)

| ID | Requirement | Pri | Status |
| --- | --- | --- | --- |
| CRED-1 | The system shall parse AWS roles from the assertion, whatever order the role and principal ARNs appear in. | M | ✅ `test_parse_roles_normalizes_order` |
| CRED-2 | Role selection by full ARN, exact role name or case-insensitive ARN substring. It prompts interactively when ambiguous, and errors in non-interactive mode. | M | ✅ `test_select_*` |
| CRED-3 | Session duration precedence: `--duration` > account > IdP > assertion `SessionDuration` > 3600 s. If a role refuses a long session, retry once with 3600 s. | M | ✅ |
| CRED-4 | Role chaining: accounts with `via` are reached by `AssumeRole` from the parent's credentials, parents first, with cycles detected and the session capped at 1 h. | M | ✅ `test_with_parents_and_loops` |
| CRED-5 | Chained logins at the same depth shall run in parallel. | S | ✅ |
| CRED-6 | Credentials shall be written atomically to the shared credentials file (`AWS_SHARED_CREDENTIALS_FILE` honoured), with mode 0600 on POSIX, other profiles left untouched, and the expiry recorded. | M | ✅ `test_write_and_read_profile` |
| CRED-7 | The region shall be written to `~/.aws/config` only if the profile has none. | S | ✅ `test_region_not_clobbered` |
| CRED-8 | `--env` shall print credentials as shell statements instead of writing files, for bash/zsh/sh, fish, PowerShell and cmd. | M | ✅ `test_login_env_output`, `test_format_env_all_shells` |
| CRED-9 | Ad-hoc login without a configured account shall let the user pick any offered role. | S | ✅ |
| CRED-10 | `credential_process` support, so the AWS SDK fetches credentials on demand from a cached session. | S | 🔜 |
| CRED-11 | Automatic re-login when credentials expire during long fan-out runs. | C | 💡 |

### 3.4 Account inventory (ACC)

| ID | Requirement | Pri | Status |
| --- | --- | --- | --- |
| ACC-1 | `accounts list` with table/JSON/CSV output. | M | ✅ |
| ACC-2 | Target selection by name, id, profile, glob pattern, tag (AND, glob values) or `--all`, shared by every multi-account command. | M | ✅ `test_accounts_list_and_filters` |
| ACC-3 | `accounts add/remove/rename/tag`. Rename updates `via` references, and remove refuses while the account is referenced. | M | ✅ `test_accounts_add_rename_remove` |
| ACC-4 | `accounts import` from CSV and YAML, including the legacy `name: {sn, acc}` format. | S | ✅ `test_import_*` |
| ACC-5 | `accounts discover`: log in once and add every account that has an offered role. | S | ✅ |
| ACC-6 | `accounts import-aws-config`: convert `role_arn` + `source_profile` profiles into accounts with `via`. | S | ✅ `test_import_aws_config` |
| ACC-7 | Import from AWS Organizations (names, OUs as tags). | S | 🔜 |
| ACC-8 | Fetch account aliases during discovery for friendlier names. | C | 💡 |

### 3.5 Session tools (SES)

| ID | Requirement | Pri | Status |
| --- | --- | --- | --- |
| SES-1 | `status` shows each account's credential state (valid with time left, expired, not logged in). | M | ✅ `test_status_and_env` |
| SES-2 | `env ACCOUNT` prints statements setting `AWS_PROFILE`/region. `--credentials` exports keys, `--unset` clears them. | M | ✅ |
| SES-3 | `whoami` calls `sts:GetCallerIdentity`. | S | ✅ |
| SES-4 | `console ACCOUNT` opens the AWS web console through a federation sign-in URL. `--print` prints the URL instead. | S | ✅ |
| SES-5 | `logout`: remove credentials for selected accounts. | S | 🔜 |

### 3.6 Fan-out and inventory (FAN / INV)

| ID | Requirement | Pri | Status |
| --- | --- | --- | --- |
| FAN-1 | The engine shall run a task for every account × region pair in parallel (default 16 workers), with one boto3 session per job. | M | ✅ |
| FAN-2 | A failure in one account shall not stop the others. Each failure shows an actionable message (for example "session expired, run `lzctl login X`"). The exit code is non-zero only if every job failed. | M | ✅ |
| FAN-3 | `ec2 list` with region and state filters and table/JSON/CSV output. | M | ✅ |
| INV-1 | `inventory` shall collect EC2, EBS, RDS, S3, Lambda, DynamoDB and ELBv2 resources. | M | ✅ `test_inventory` |
| INV-2 | Global services (S3) shall be collected once per account. | M | ✅ `test_global_service_collected_once` |
| INV-3 | Resource tag filters (`-f K=V`, glob, AND) and tag columns (`-c KEY`, default from `defaults.inventory_tag_columns`). | M | ✅ |
| INV-4 | Output as table, JSON, CSV or Excel. Excel has a summary sheet (resources per account × service) and one filterable sheet per service, named `<label>_inventory_YYYYMMDD_HHMMSS.xlsx`. | M | ✅ `test_inventory_xlsx` |
| INV-5 | A missing permission for one service shall skip that service with a warning, not fail the account. | M | ✅ |
| INV-6 | Collectors shall be pluggable through `lzctl.collectors`. | M | ✅ |
| INV-7 | More collectors: EKS, ECS, CloudFront, IAM roles/users, VPC/subnets, EIPs, snapshots, KMS, SNS/SQS. | S | 🔜 |
| INV-8 | Report diff between two inventory runs (what was added, removed or changed). | C | 💡 |
| INV-9 | Cost-related columns (instance pricing, unattached volumes, idle resources). | C | 💡 |

### 3.7 Safety (SAFE)

| ID | Requirement | Pri | Status |
| --- | --- | --- | --- |
| SAFE-1 | Production accounts are identified by configurable tags (`defaults.production_tags`, default `env=prod*`), never by hard-coded names. | M | ✅ |
| SAFE-2 | Login and fan-out commands shall warn when production accounts are involved. | M | ✅ `test_production_warning` |
| SAFE-3 | Commands that change resources shall follow plan → dry-run → confirm → execute, using `confirm_targets`. | M | ✅ (framework) |
| SAFE-4 | `confirm_targets` shall list the accounts and mark production ones. For production it shall require typing the number of production accounts. Without a TTY it shall refuse unless `--yes` is given. | M | ✅ `test_confirm_targets_production_gate` |
| SAFE-5 | Read-only mode per account (`readonly: true`) that blocks commands that change resources. | S | 🔜 |
| SAFE-6 | Audit log of commands that changed things (who, what, which accounts, when) to a local file. | S | 🔜 |

### 3.8 Extensibility (EXT)

| ID | Requirement | Pri | Status |
| --- | --- | --- | --- |
| EXT-1 | Plugin commands through the `lzctl.commands` entry point group. Built-in names take precedence, and a broken plugin only produces a warning. | M | ✅ |
| EXT-2 | A stable public API, `lzctl.sdk`, documented in [EXTENDING.md](EXTENDING.md). | M | ✅ |
| EXT-3 | Testing helpers for plugins (`FakeBoto`, `FakeHttp`) shipped as `lzctl.testing`. | S | 🔜 (currently in `tests/conftest.py`) |
| EXT-4 | A command for patching through SSM Patch Manager (scan/install), following SAFE-3. | S | 🔜 |
| EXT-5 | `exec -- <command>`: run any shell command with each account's credentials. | S | 🔜 |

---

## 4. Non-functional requirements

### 4.1 Security (SEC)

| ID | Requirement | Status |
| --- | --- | --- |
| SEC-1 | Passwords live only in process memory unless the user enables keyring. MFA codes are never stored. | ✅ |
| SEC-2 | SAML XML is parsed with `defusedxml` (no XXE or entity expansion). | ✅ |
| SEC-3 | Credential files are written atomically with mode 0600 on POSIX. | ✅ |
| SEC-4 | No telemetry. Network calls go only to the configured IdP, AWS STS and sign-in, and the AWS APIs a command uses. | ✅ |
| SEC-5 | TLS verification is on by default. Disabling it warns every time. | ✅ |
| SEC-6 | The repository blocks committing secrets (gitleaks in pre-commit and CI; `.gitignore` covers configs, certificates and SAML captures). | ✅ |
| SEC-7 | Vulnerability reports go through private GitHub advisories ([SECURITY.md](../SECURITY.md)). | ✅ |
| SEC-8 | Release artifacts are signed and have provenance (Sigstore / PyPI trusted publishing). | 🔜 |

### 4.2 Portability (POR)

| ID | Requirement | Status |
| --- | --- | --- |
| POR-1 | Runs on Linux, macOS and Windows with no OS-specific installation steps beyond Python. | ✅ |
| POR-2 | CI tests the oldest and newest supported Python on all three OSes. | ✅ |
| POR-3 | Shell output for bash, zsh, sh, fish, PowerShell and cmd, with auto-detection. | ✅ |
| POR-4 | Standalone binaries for users without Python. | 🔜 |

### 4.3 Usability (USE)

| ID | Requirement | Status |
| --- | --- | --- |
| USE-1 | Results go to stdout, and prompts, progress and warnings go to stderr, so output can be piped and `eval`'d. | ✅ |
| USE-2 | Expected errors show one `Error: ...` line, never a traceback. | ✅ |
| USE-3 | Every command has `--help` with examples. | ✅ |
| USE-4 | Shell completion (bash/zsh/fish/PowerShell) including account names. | 🔜 |

### 4.4 Performance (PERF)

| ID | Requirement | Status |
| --- | --- | --- |
| PERF-1 | Logging in to N accounts behind one IdP URL performs one IdP authentication. | ✅ |
| PERF-2 | Fan-out runs in parallel. Target: 100 accounts × 1 region `ec2 list` in under 30 s on a normal connection. | 🟡 (not benchmarked) |
| PERF-3 | `lzctl --help` starts in under 1 s (boto3 is the main cost). | 🟡 |

### 4.5 Reliability and maintainability (REL / MNT)

| ID | Requirement | Status |
| --- | --- | --- |
| REL-1 | A failing account or service never aborts other accounts. | ✅ |
| REL-2 | Writes to credential and config files are atomic, or at least validated before being written. | ✅ |
| MNT-1 | Tests need no network and no real AWS. The full suite runs in seconds. | ✅ (42 tests) |
| MNT-2 | Lint with ruff is enforced in CI. | ✅ |
| MNT-3 | Line coverage ≥ 80% for core modules. | 🔜 |

---

## 5. External interfaces

### 5.1 User interface (CLI)

`lzctl [--config FILE] [--quiet] COMMAND [ARGS]`. Commands: `init`, `providers`, `config`, `login`, `status`, `env`, `whoami`, `console`, `accounts`, `inventory`, `ec2`, plus plugins. The full reference is in the [README](../README.md#commands).

Exit codes: `0` success, `1` expected error (`LzctlError`), `2` usage error (click), `130`/`1` aborted by the user.

### 5.2 Files

| File | Access | Format |
| --- | --- | --- |
| lzctl config | read/write | YAML (see §6) |
| `~/.aws/credentials` (or `AWS_SHARED_CREDENTIALS_FILE`) | read/write own profiles | INI. Keys: `aws_access_key_id`, `aws_secret_access_key`, `aws_session_token`, `x_lzctl_expiration` |
| `~/.aws/config` (or `AWS_CONFIG_FILE`) | read; writes `region` only if missing | INI |
| Inventory reports | write | `.xlsx` |

### 5.3 Software interfaces

| System | Interface |
| --- | --- |
| IdP | HTTPS, HTML forms (form providers), or a provider-specific API (plugins) |
| AWS STS | `AssumeRoleWithSAML` (unsigned), `AssumeRole`, `GetCallerIdentity` |
| AWS sign-in | `https://signin.aws.amazon.com/federation` (getSigninToken / login) |
| AWS services | Read-only `Describe*`/`List*`/`Get*` for EC2, RDS, S3, Lambda, DynamoDB, ELBv2 |
| OS keychain | `keyring` library (macOS Keychain, Windows Credential Manager, Secret Service) |
| Clipboard | `pbpaste`, PowerShell `Get-Clipboard`, `wl-paste` / `xclip` / `xsel` |

---

## 6. Data model (configuration)

```yaml
defaults:
  idp: <idp name>                    # default IdP
  region: <aws region>               # default region (fallback us-east-1)
  username: <idp username>
  chain_role: <role name or ARN>     # default OrganizationAccountAccessRole
  production_tags: {KEY: GLOB, ...}  # default {env: "prod*"}
  inventory_tag_columns: [KEY, ...]

idps:
  <name>:
    provider: pingfederate | adfs | keycloak | form | manual | <plugin>
    url: <IdP-initiated SSO URL>
    url_params: {param: "<template>"}   # {account_id} {account_name} {<account url_params key>}
    username: <override>
    ca_bundle: <path to PEM>
    verify_ssl: true
    keyring: false
    session_duration: <seconds>
    options: {...}                      # provider specific

accounts:
  <name>:
    id: "<12 digits>"                   # required
    idp: <idp name>
    role: <name | ARN | substring>      # SAML role, or role to assume when `via` is set
    via: <account name>                 # role chaining parent
    region: <aws region>
    profile: <profile name>             # default: account name
    tags: {KEY: VALUE}
    duration: <seconds>
    external_id: <string>
    url_params: {param: value}
```

---

## 7. Key use cases

**UC-1 Daily multi-account login.** The engineer runs `lzctl login --tag env=nonprod`. lzctl groups the accounts by IdP URL and prompts once per group. It picks each account's role, assumes the `via` accounts in parallel, writes the profiles and prints a summary with expiry times. *(AUTH-7, CRED-4, CRED-6)*

**UC-2 Separate prod login.** Prod and non-prod accounts use different IdP URLs. `lzctl login nonprod-hub prod-hub` prompts twice, then warns that production credentials were written. *(AUTH-7, AUTH-8, SAFE-2)*

**UC-3 Ticket: inventory for an application.** Support runs `lzctl inventory prod -f Application=billing -c CostCentre -o xlsx` and attaches `reports/prod_inventory_<ts>.xlsx` to the ticket. *(INV-3, INV-4)*

**UC-4 Onboarding a new team member.** They run `lzctl init`, then `lzctl accounts discover`, rename the important accounts, and log in. *(CFG-5, ACC-5)*

**UC-5 Migrating from hand-written AWS profiles.** `lzctl accounts import-aws-config --source-profile saml` converts existing chained profiles. *(ACC-6)*

**UC-6 Change across accounts (future, for example patching).** The command builds a plan and shows it. `--dry-run` stops there. Otherwise `confirm_targets` asks for typed confirmation for production, and the command executes only the planned items. *(SAFE-3, SAFE-4, EXT-4)*

**UC-7 Any IdP with push MFA.** The IdP uses `provider: manual`. The user signs in with the browser, copies the SAMLResponse, and lzctl reads it from the clipboard. *(AUTH-5)*

---

## 8. Verification

- Automated: `pytest` (offline, faked HTTP/AWS) and `ruff`, run in CI on Linux, macOS and Windows. The test names in the tables above trace requirements to tests.
- Manual before a release: log in against at least one real IdP of each built-in type that maintainers can access, plus `manual`. Run `inventory -o xlsx` against a sandbox account.
- New requirements get an ID in this document in the same pull request that implements them.
