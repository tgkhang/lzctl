import json
from datetime import datetime

import pytest
from click.testing import CliRunner

from lzctl.cli import cli

from .conftest import FakeBoto

CONFIG = """
defaults: {region: us-east-1, inventory_tag_columns: [Application]}
accounts:
  dev: {id: "111111111111", tags: {env: nonprod}}
  prod: {id: "222222222222", tags: {env: prod}}
"""

T0 = datetime(2026, 1, 2, 3, 4)
RESPONSES = {
    "ec2": {
        "describe_instances": [{"Reservations": [{"Instances": [
            {"InstanceId": "i-1", "State": {"Name": "running"}, "InstanceType": "t3.micro",
             "LaunchTime": T0, "Tags": [{"Key": "Name", "Value": "web"},
                                        {"Key": "Application", "Value": "billing"}]},
            {"InstanceId": "i-2", "State": {"Name": "stopped"}, "InstanceType": "t3.large",
             "LaunchTime": T0, "Tags": [{"Key": "Application", "Value": "hr"}]},
        ]}]}],
        "describe_volumes": [{"Volumes": [{"VolumeId": "vol-1", "State": "in-use", "Size": 8,
                                           "CreateTime": T0, "Attachments": [{"InstanceId": "i-1"}]}]}],
    },
    "s3": {
        "list_buckets": {"Buckets": [{"Name": "logs", "CreationDate": T0}]},
        "get_bucket_location": {"LocationConstraint": "eu-west-1"},
        "get_bucket_tagging": {"TagSet": [{"Key": "Application", "Value": "billing"}]},
    },
}


@pytest.fixture
def run(tmp_path, aws_files, monkeypatch):
    cfg = tmp_path / "config.yaml"
    cfg.write_text(CONFIG)
    monkeypatch.setenv("LZCTL_CONFIG", str(cfg))
    monkeypatch.setattr("boto3.Session", FakeBoto.factory(RESPONSES))
    monkeypatch.chdir(tmp_path)
    return lambda *args: CliRunner().invoke(cli, list(args), catch_exceptions=False)


def test_inventory_json_and_resource_tag_filter(run):
    result = run("inventory", "dev", "-s", "ec2,ebs,s3", "-f", "Application=bill*", "-o", "json")
    rows = json.loads(result.stdout)
    assert {(r["service"], r["id"]) for r in rows} == {("ec2", "i-1"), ("s3", "logs")}
    s3 = next(r for r in rows if r["service"] == "s3")
    assert s3["region"] == "global" and s3["bucket_region"] == "eu-west-1"


def test_global_service_collected_once(run):
    result = run("inventory", "dev", "-s", "s3", "--region", "us-east-1", "--region", "eu-west-1",
                 "-o", "json")
    assert len(json.loads(result.stdout)) == 1


def test_inventory_table_has_tag_columns(run):
    out = run("inventory", "dev", "-s", "ec2").stdout
    assert "TAG:APPLICATION" in out and "billing" in out


def test_inventory_csv_columns(run):
    header = run("inventory", "dev", "-s", "ec2", "-o", "csv").stdout.splitlines()[0]
    assert header.startswith("account,account_id,region,service,id,name,state,created")
    assert "tag:Application" in header and "instance_type" not in header and "type" in header


def test_inventory_xlsx(run, tmp_path):
    openpyxl = pytest.importorskip("openpyxl")
    result = run("inventory", "dev", "prod", "-s", "ec2,s3", "-o", "xlsx")
    path = tmp_path / result.stdout.strip()
    assert path.parent.name == "reports" and path.name.startswith("multi-account_inventory_")
    wb = openpyxl.load_workbook(path)
    assert wb.sheetnames == ["Summary", "ec2", "s3"]
    summary = [[c.value for c in row] for row in wb["Summary"].iter_rows(min_row=3)]
    assert summary[0] == ["account", "ec2", "s3", "total"]
    assert summary[-1] == ["total", 4, 2, 6]
    assert wb["ec2"].max_row == 5  # header + 2 instances x 2 accounts


def test_production_warning(run):
    result = run("inventory", "prod", "-s", "ec2")
    assert "Production account(s): prod" in result.stderr


def test_unknown_service(run):
    result = CliRunner().invoke(cli, ["inventory", "dev", "-s", "nope"])
    assert result.exit_code != 0 and "Unknown service" in result.output
