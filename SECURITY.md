# Security policy

lzctl handles IdP passwords, MFA codes and AWS credentials, so we take security reports seriously.

## Reporting a vulnerability

Please **do not open a public issue**. Report privately through
[GitHub Security Advisories](https://github.com/tgkhang/lzctl/security/advisories/new).
We aim to reply within 7 days.

Please include affected versions, reproduction steps and impact. Never include real credentials, SAML responses or account ids. Use placeholders.

## Scope and design

- Passwords live in process memory only, unless `keyring: true` stores them in the OS keychain.
- MFA codes are never stored.
- Temporary STS credentials are written to the standard AWS credentials file (mode `0600` on POSIX) and expire.
- lzctl only talks to your configured IdP, AWS STS and AWS sign-in (for `console`). There is no telemetry.
- `verify_ssl: false` disables TLS verification and prints a warning. Use `ca_bundle` instead.
