# Roadmap

Where lzctl is going and in what order. Requirement IDs refer to [SRS.md](SRS.md). Dates are intentions, not promises. Priorities shift with user feedback, so open an issue to argue for something.

## Vision

> **One free, cross-platform CLI to log in to, see, and safely operate on every AWS account in a landing zone, whatever identity provider you use.**

The guiding principles:

1. **Many accounts first.** Every feature should work on 1 account and on 500.
2. **Standard files and plain AWS.** Write `~/.aws/*` and use AWS APIs directly. No lock-in and no server.
3. **Safe by default.** Read-only unless asked, production is visible, changes are planned and confirmed.
4. **Extensible.** Organisation-specific needs go into plugins, so the core stays generic.

## Where we are: v0.1 (current)

✅ Login through PingFederate / AD FS / Keycloak / generic forms / manual (any IdP)
✅ One login for many accounts, hub→spoke chaining, keyring, `--env` for every shell
✅ Account inventory: tags, globs, discover, CSV/YAML/aws-config import
✅ `status`, `env`, `whoami`, `console`, `ec2 list`
✅ `inventory` for 7 services with tag filters and Excel reports
✅ Production detection, a confirmation framework for commands that change things, `lzctl.sdk`, plugin entry points
✅ CI on Linux/macOS/Windows, secret scanning

## v0.2: "Daily driver" (next)

Goal: good enough to replace every hand-rolled script for login and switching.

| Item | Req |
| --- | --- |
| Publish to PyPI with trusted publishing and signed releases | SEC-8 |
| `credential_process` integration with a session cache, so the AWS SDK and Terraform refresh on demand | CRED-10 |
| `logout` command | SES-5 |
| Shell completion including account names | USE-4 |
| `lzctl.testing` module (FakeBoto, FakeHttp) for plugin authors | EXT-3 |
| Benchmark and tune fan-out (PERF-2), lazy-import boto3 for fast `--help` | PERF-2/3 |
| Comment-preserving config writes | CFG-8 |

## v0.3: "Any IdP"

Goal: remove the main reason to choose another tool, which is IdP coverage.

| Item | Req |
| --- | --- |
| Okta API provider (password + TOTP + push polling) | AUTH-13 |
| Microsoft Entra ID provider | AUTH-13 |
| Browser-capture provider (local listener or headless browser, no DevTools copy-paste) | AUTH-14 |
| IAM Identity Center provider (device-code flow), so SAML and SSO users share one tool | AUTH-15 |
| Compatibility guide: migrating from saml2aws / gimme-aws-creds configs | — |

## v0.4: "Operate"

Goal: safe write operations across accounts, starting with the most requested one.

| Item | Req |
| --- | --- |
| `patch status / scan / install` through SSM Patch Manager, using plan → dry-run → confirm | EXT-4, SAFE-3 |
| `exec -- <cmd>`: run any command (aws, terraform, scripts) per account with its credentials, in parallel | EXT-5 |
| Read-only accounts (`readonly: true`) block commands that change things | SAFE-5 |
| Local audit log for changes | SAFE-6 |

## v0.5: "See everything"

| Item | Req |
| --- | --- |
| More collectors: EKS, ECS, CloudFront, IAM, VPC, EIP, snapshots, KMS, SNS/SQS | INV-7 |
| `accounts import --org` from AWS Organizations (OUs as tags) | ACC-7 |
| Inventory diff between two runs | INV-8 |
| Cost and hygiene hints: unattached volumes, stopped instances, old snapshots | INV-9 |

## v1.0: "Stable"

- `lzctl.sdk` frozen under semantic versioning
- Standalone binaries (POR-4) and Homebrew / winget / Scoop packages
- Documentation site
- At least 80% test coverage of core modules (MNT-3)

## Ideas not yet scheduled 💡

- Config JSON Schema for editor completion (CFG-9)
- Account aliases during discovery (ACC-8)
- Automatic re-login when a fan-out run hits expired credentials (CRED-11)
- A TUI account picker (`lzctl pick`)
- Exporting `~/.aws/config` profiles for teams that also use plain AWS CLI chaining
- Multi-cloud (Azure/GCP) through the same account inventory. Big; would need its own design.

## How to influence the roadmap

Open an issue describing the problem (not just the feature), how many accounts or users it affects, and what you do today instead. A pull request that implements an item, with an SRS requirement ID and tests, is the fastest path.
