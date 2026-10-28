from datetime import datetime, timedelta, timezone

import pytest
from click.testing import CliRunner

from lzctl import auth
from lzctl.aws import AwsCredentials
from lzctl.cli import cli
from lzctl.credentials import read_profile

from .conftest import ROLE_A, ROLE_C

CONFIG = """
defaults: {idp: corp, region: us-west-2, username: alice}
idps:
  corp: {provider: form, url: "https://idp.example.com/start"}
accounts:
  dev: {id: "111111111111", role: Admin, tags: {env: nonprod}}
  prod: {id: "222222222222", tags: {env: prod}}
  workload: {id: "333333333333", via: dev, tags: {env: nonprod}}
"""


@pytest.fixture
def run(tmp_path, aws_files, monkeypatch):
    cfg = tmp_path / "config.yaml"
    cfg.write_text(CONFIG)
    monkeypatch.setenv("LZCTL_CONFIG", str(cfg))

    def invoke(*args, **kw):
        return CliRunner().invoke(cli, list(args), catch_exceptions=False, **kw)

    invoke.config = cfg
    return invoke


@pytest.fixture
def fake_aws(monkeypatch, assertion):
    exp = datetime.now(timezone.utc) + timedelta(hours=1)
    calls = {"auth": 0, "saml": [], "chain": []}

    def fake_authenticate(idp, url, prompter):
        calls["auth"] += 1
        return assertion

    def fake_saml(role, assertion_, region, duration, warn):
        calls["saml"].append((role.role_arn, region, duration))
        return AwsCredentials(f"AK{role.account_id}", "secret", "token", exp)

    def fake_chain(source, role_arn, region, **kw):
        calls["chain"].append((source.access_key_id, role_arn))
        return AwsCredentials("AKCHAIN", "secret", "token", exp)

    monkeypatch.setattr(auth, "authenticate", fake_authenticate)
    monkeypatch.setattr(auth, "assume_role_with_saml", fake_saml)
    monkeypatch.setattr(auth, "assume_role", fake_chain)
    return calls


def test_help(run):
    result = run("--help")
    assert result.exit_code == 0
    assert "login" in result.output and "ec2" in result.output


def test_accounts_list_and_filters(run):
    out = run("accounts", "list", "--tag", "env=nonprod").output
    assert "dev" in out and "workload" in out and "prod " not in out
    assert run("accounts", "list", "-o", "json", "w*").output.count('"name"') == 1


def test_accounts_add_rename_remove(run):
    assert run("accounts", "add", "sbx", "--id", "444444444444", "-t", "env=sandbox").exit_code == 0
    assert "444444444444" in run("accounts", "list").output
    run("accounts", "rename", "dev", "development")
    assert "via: development" in run.config.read_text()
    result = CliRunner().invoke(cli, ["accounts", "remove", "development"])
    assert result.exit_code != 0 and "used as 'via'" in result.output
    run("accounts", "remove", "sbx")
    assert "sbx" not in run("accounts", "list").output


def test_import_legacy_yaml(run, tmp_path):
    legacy = tmp_path / "accounts.yaml"
    legacy.write_text("lz001nonprod:\n  sn: lz001nonprod\n  acc: 555555555555\n")
    run("accounts", "import", str(legacy))
    assert "sn: lz001nonprod" in run.config.read_text()


def test_import_csv(run, tmp_path):
    csv_file = tmp_path / "a.csv"
    csv_file.write_text("name,id,role,tags\nshared,666666666666,ReadOnly,env=shared;team=platform\n")
    run("accounts", "import", str(csv_file))
    assert "team=platform" in run("accounts", "list", "shared").output


def test_login_single_password_and_chaining(run, fake_aws):
    result = run("login", "dev", "prod", "workload")
    assert result.exit_code == 0, result.output
    assert fake_aws["auth"] == 1  # one IdP url -> one authentication
    assert [c[0] for c in fake_aws["saml"]] == [ROLE_A, ROLE_C]
    assert fake_aws["saml"][0][2] == 7200  # SessionDuration from the assertion
    assert fake_aws["chain"] == [
        ("AK111111111111", "arn:aws:iam::333333333333:role/OrganizationAccountAccessRole")]
    assert read_profile("workload").access_key_id == "AKCHAIN"
    assert read_profile("prod").access_key_id == "AK222222222222"


def test_login_env_output(run, fake_aws):
    result = run("login", "dev", "--env", "--shell", "bash")
    assert "export AWS_ACCESS_KEY_ID=AK111111111111" in result.output
    assert "unset AWS_PROFILE" in result.output
    assert read_profile("dev") is None


def test_status_and_env(run, fake_aws):
    run("login", "dev")
    out = run("status").output
    assert "not logged in" in out and "dev" in out
    assert run("env", "dev", "--shell", "bash").output.startswith("export AWS_PROFILE=dev")


def test_import_aws_config(run, aws_files):
    aws_files.config.parent.mkdir(parents=True, exist_ok=True)
    aws_files.config.write_text(
        "[profile dev]\nregion = us-west-2\n\n"
        "[profile spoke-a]\nrole_arn = arn:aws:iam::777777777777:role/Deployer\n"
        "source_profile = dev\nregion = eu-west-1\n\n"
        "[profile orphan]\nrole_arn = arn:aws:iam::888888888888:role/X\nsource_profile = nope\n")
    result = CliRunner().invoke(cli, ["accounts", "import-aws-config"])
    assert "skip orphan" in result.output
    out = run("accounts", "list", "spoke-a", "-o", "json").output
    assert '"via": "dev"' in out and "777777777777" in out


def test_confirm_targets_production_gate(run):
    import click

    from lzctl.sdk import confirm_targets, pass_app, resolve_targets, target_options

    @click.command()
    @target_options
    @pass_app
    def danger(app, targets):
        confirm_targets(app, resolve_targets(app.config, targets), "do things")
        click.echo("DONE")

    cli.add_command(danger)
    try:
        # CliRunner stdin is not a TTY: must refuse without --yes
        result = CliRunner().invoke(cli, ["danger", "prod"])
        assert result.exit_code != 0 and "pass --yes" in result.output
        assert "PRODUCTION" in result.output
    finally:
        cli.commands.pop("danger")
