# Contributing to lzctl

Thanks for helping! Bug reports, IdP compatibility notes, docs fixes and new commands are all welcome.

## Ground rules

- **Never commit real data.** That means no real account ids, IdP hostnames, usernames, certificates, SAML responses or credentials, including in tests, issues and screenshots. Use `example.com` and account ids such as `111111111111`. The pre-commit hook runs [gitleaks](https://github.com/gitleaks/gitleaks) to help catch mistakes.
- Keep the core free of anything specific to one organisation. Org-specific behaviour belongs in config `options` or a plugin.
- It must work on Linux, macOS and Windows. CI runs on all three.

## Development setup

```bash
git clone https://github.com/tgkhang/lzctl && cd lzctl
python -m venv .venv
# Linux/macOS:           source .venv/bin/activate
# Windows PowerShell:    .venv\Scripts\Activate.ps1
pip install -e ".[dev,keyring]"
pip install pre-commit && pre-commit install

pytest                    # tests
ruff check . && ruff format --check .   # lint
lzctl --help
```

Use a scratch config while hacking so your real one stays safe:

```bash
export LZCTL_CONFIG=$PWD/dev-config.yaml          # PowerShell: $env:LZCTL_CONFIG="$PWD\dev-config.yaml"
export AWS_SHARED_CREDENTIALS_FILE=$PWD/dev-credentials
```

Both file names are already in `.gitignore`.

## Project layout

```
src/lzctl/
  cli.py            root command, registers commands + plugins
  config.py         config file model and validation
  auth.py           login orchestration (IdP -> SAML -> STS -> role chaining)
  saml.py           assertion parsing, role selection
  aws.py            STS / console helpers
  credentials.py    ~/.aws/credentials and ~/.aws/config writing
  multi.py          run a function across accounts x regions in parallel
  inventory/        resource collectors + Excel report writer
  sdk.py            stable public API for plugins and new commands
  shell.py          export syntax for bash/zsh/fish/PowerShell/cmd
  output.py         table / json / csv rendering
  prompts.py        username/password/MFA prompts (stderr only) + keyring
  providers/        identity providers (form walker, presets, manual)
  commands/         CLI commands
tests/              pytest; no network access, AWS and HTTP are faked
```

Conventions:
- **stdout is for results, stderr is for everything else** (prompts, progress, warnings). That keeps `eval "$(lzctl ...)"` and `-o json | jq` working.
- Raise `lzctl.errors.*` for expected failures. They print as a single `Error: ...` line, never a traceback.
- Tests must not touch the network or your real `~/.aws`. Use the `aws_files` fixture and fakes from `tests/conftest.py`.

## Adding commands, collectors and providers

See **[docs/EXTENDING.md](docs/EXTENDING.md)**. It covers the architecture, a read-only command in 5 minutes, the required pattern for commands that change things (plan → dry-run → confirm → execute), inventory collectors, IdP providers, plugins, the `lzctl.sdk` API and testing helpers.

Plugins and new code should import only from `lzctl.sdk`, the stable public API.

## Pull requests

1. Open an issue first for big changes, so we can agree on the approach.
2. Add or update tests. Keep `pytest` and `ruff check` green.
3. Update `README.md` and `CHANGELOG.md` for user-visible changes.
4. Keep commits focused, with a clear message explaining *why*.

## Reporting IdP compatibility

If a provider doesn't work with your IdP, open an issue with the IdP product and version, the provider you used, and the error. If you can, include the **structure** of the login form (field names and types) with every value removed.
