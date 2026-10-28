# Changelog

All notable changes are documented here. The format follows [Keep a Changelog](https://keepachangelog.com/en/1.1.0/).

## [Unreleased]

### Added
- First public version, rewritten as a cross-platform Python package.
- `login` with one authentication per IdP for many accounts, tag/glob selection, `--env` output.
- Providers: `pingfederate`, `adfs`, `keycloak`, generic `form`, `manual`. Plugin entry points for providers and commands.
- Hub → spoke role chaining (`via`).
- `accounts list/add/remove/rename/tag/import/discover`, `status`, `env`, `whoami`, `console`, `ec2 list`.
- Optional OS keychain password storage (`lzctl[keyring]`).
- `inventory`: EC2, EBS, RDS, S3, Lambda, DynamoDB and ELB collectors across accounts/regions, resource-tag filters, tag columns, table/JSON/CSV/Excel reports (`lzctl[excel]`). Collector plugins via `lzctl.collectors`.
- Production safety: accounts matching `defaults.production_tags` (default `env=prod*`) are flagged at login and in fan-out commands. `confirm_targets` gates commands that change things.
- `accounts import-aws-config` converts `role_arn`/`source_profile` profiles from `~/.aws/config`.
- `lzctl.sdk` public API and [docs/EXTENDING.md](docs/EXTENDING.md).
