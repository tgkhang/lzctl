import pytest

from lzctl.auth import build_idp_url, with_parents
from lzctl.config import Config
from lzctl.errors import ConfigError

CONFIG = """
defaults:
  idp: corp
  region: ap-southeast-2
idps:
  corp:
    provider: pingfederate
    url: https://idp.example.com/idp/startSSO.ping?PartnerSpId=urn:amazon:webservices
    url_params: {sn: "{sn}", acc: "{account_id}"}
accounts:
  hub:
    id: "111111111111"
    url_params: {sn: hub-prod}
    tags: {env: prod}
  spoke:
    id: 012345678999
    via: hub
    tags: {env: nonprod, lz: lz001}
"""


@pytest.fixture
def config(tmp_path):
    path = tmp_path / "config.yaml"
    path.write_text(CONFIG)
    return Config.load(path)


def test_load(config):
    assert config.accounts["spoke"].id == "012345678999"
    assert config.region_for(config.accounts["hub"]) == "ap-southeast-2"
    assert config.chain_role_for(config.accounts["spoke"]) == \
        "arn:aws:iam::012345678999:role/OrganizationAccountAccessRole"


def test_idp_url_templating(config):
    url = build_idp_url(config.idps["corp"], config.accounts["hub"])
    assert url.endswith("PartnerSpId=urn:amazon:webservices&sn=hub-prod&acc=111111111111")
    # no account: templated params that resolve to "" are dropped
    assert build_idp_url(config.idps["corp"]) == config.idps["corp"].url


def test_with_parents_and_loops(config):
    assert [a.name for a in with_parents(config, [config.accounts["spoke"]])] == ["hub", "spoke"]
    config.accounts["hub"].via = "spoke"
    with pytest.raises(ConfigError, match="loop"):
        with_parents(config, [config.accounts["spoke"]])


def test_tags(config):
    assert config.accounts["spoke"].matches_tags({"lz": "lz*"})
    assert not config.accounts["hub"].matches_tags({"lz": "*"})


def test_validation(tmp_path):
    path = tmp_path / "c.yaml"
    path.write_text("accounts:\n  a: {id: '123'}\n")
    with pytest.raises(ConfigError, match="12 digits"):
        Config.load(path)
    path.write_text("accounts:\n  a: {id: '111111111111', via: nope}\n")
    with pytest.raises(ConfigError, match="unknown account"):
        Config.load(path)


def test_save_roundtrip(config):
    config.remove_account("spoke")
    config.save()
    again = Config.load(config.path)
    assert list(again.accounts) == ["hub"]
    assert again.accounts["hub"].url_params == {"sn": "hub-prod"}
