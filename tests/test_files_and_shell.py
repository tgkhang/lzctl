import os
from datetime import datetime, timedelta, timezone

from lzctl.aws import AwsCredentials
from lzctl.credentials import (
    ensure_profile_region,
    expirations,
    read_profile,
    remaining,
    write_profile,
)
from lzctl.output import render
from lzctl.shell import format_env


def test_write_and_read_profile(aws_files):
    exp = datetime.now(timezone.utc) + timedelta(hours=1)
    aws_files.credentials.parent.mkdir(parents=True)
    aws_files.credentials.write_text("[other]\naws_access_key_id = KEEP\n")
    write_profile("dev", AwsCredentials("AKIA", "s3cr%t", "tok", exp))
    creds = read_profile("dev")
    assert creds == AwsCredentials("AKIA", "s3cr%t", "tok", exp)
    assert read_profile("other").access_key_id == "KEEP"
    assert set(expirations()) == {"other", "dev"}
    if os.name != "nt":
        assert oct(aws_files.credentials.stat().st_mode & 0o777) == "0o600"


def test_region_not_clobbered(aws_files):
    ensure_profile_region("dev", "eu-west-1")
    ensure_profile_region("dev", "us-east-1")
    assert "region = eu-west-1" in aws_files.config.read_text()
    assert "[profile dev]" in aws_files.config.read_text()


def test_remaining():
    assert remaining(None) == "unknown"
    assert remaining(datetime.now(timezone.utc) - timedelta(seconds=1)) == "expired"
    assert remaining(datetime.now(timezone.utc) + timedelta(minutes=90, seconds=5)) == "1h30m"


def test_format_env_all_shells():
    v = {"AWS_PROFILE": "it's", "AWS_SESSION_TOKEN": None}
    assert format_env(v, "bash") == "export AWS_PROFILE='it'\"'\"'s'\nunset AWS_SESSION_TOKEN"
    assert format_env(v, "powershell") == (
        "$env:AWS_PROFILE = 'it''s'\nRemove-Item Env:AWS_SESSION_TOKEN -ErrorAction SilentlyContinue"
    )
    assert format_env(v, "fish").startswith("set -gx AWS_PROFILE ")
    assert format_env(v, "cmd") == "set AWS_PROFILE=it's\nset AWS_SESSION_TOKEN="


def test_render_formats():
    rows = [{"a": "x", "b": {"k": "v"}}, {"a": "longer", "b": None}]
    assert render(rows, ["a", "b"]).splitlines() == ["A       B", "x       k=v", "longer  -"]
    assert render(rows, ["a"], "csv") == "a\nx\nlonger"
    assert '"a": "x"' in render(rows, ["a"], "json")
