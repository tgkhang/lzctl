import pytest

from lzctl import providers
from lzctl.config import IdpConfig
from lzctl.errors import ConfigError, CredentialsRejected
from lzctl.prompts import Prompter

from .conftest import FakeHttp

LOGIN_PAGE = """
<form method="POST" action="/idp/AbC12/resumeSAML20/idp/startSSO.ping">
  <input type="text" name="pf.username"><input type="password" name="pf.pass">
  <input type="hidden" name="pf.ok" value=""><input type="hidden" name="pf.cancel" value="">
  <input type="hidden" name="csrf" value="xyz">
</form>"""
OTP_PAGE = """
<form method="POST" action="/idp/AbC12/resumeSAML20/idp/startSSO.ping">
  <p>Enter your verification code</p>
  <input type="text" name="pf.challengeResponse"><input type="hidden" name="pf.ok" value="">
</form>"""
SAML_PAGE = """
<form method="POST" action="https://signin.aws.amazon.com/saml">
  <input type="hidden" name="SAMLResponse" value="BASE64DATA">
</form>"""


class Answers(Prompter):
    def __init__(self, mfa="123456", **kw):
        super().__init__(username="alice", **kw)
        self._password = "secret"
        self._mfa_codes = [mfa]

    def mfa_code(self, hint=""):
        return self._mfa_codes.pop(0)


def make(name, pages, **idp_kw):
    idp = IdpConfig(name="t", provider=name, url="https://idp.example.com/start", **idp_kw)
    provider = providers.get(name)(idp)
    provider.session = FakeHttp(pages)
    return provider


def test_pingfederate_password_and_otp():
    provider = make("pingfederate", [LOGIN_PAGE, OTP_PAGE, SAML_PAGE])
    assert provider.authenticate(provider.idp.url, Answers()) == "BASE64DATA"
    login, otp = provider.session.calls[1], provider.session.calls[2]
    assert login.url == "https://idp.example.com/idp/AbC12/resumeSAML20/idp/startSSO.ping"
    assert login.data == {"pf.username": "alice", "pf.pass": "secret", "pf.ok": "clicked",
                          "pf.cancel": "", "csrf": "xyz"}
    assert otp.data == {"pf.challengeResponse": "123456", "pf.ok": "clicked"}


def test_wrong_password_detected():
    provider = make("pingfederate", [LOGIN_PAGE, LOGIN_PAGE])
    with pytest.raises(CredentialsRejected, match="password"):
        provider.authenticate(provider.idp.url, Answers())


def test_wrong_otp_detected():
    provider = make("pingfederate", [LOGIN_PAGE, OTP_PAGE, OTP_PAGE])
    with pytest.raises(CredentialsRejected, match="MFA"):
        provider.authenticate(provider.idp.url, Answers())


def test_generic_form_autodetects_fields():
    page = """<form method="post" action="login">
      <input name="email" type="email"><input name="pwd" type="password">
      <input name="totp_code" type="text"><button type="submit" name="go" value="1">Go</button>
    </form>"""
    provider = make("form", [page, SAML_PAGE])
    assert provider.authenticate(provider.idp.url, Answers()) == "BASE64DATA"
    assert provider.session.calls[1].data == {"email": "alice", "pwd": "secret",
                                              "totp_code": "123456", "go": "1"}


def test_options_override_field_names():
    page = '<form method="post"><input name="weird" type="text"><input name="p" type="password"></form>'
    provider = make("form", [page, SAML_PAGE], options={"username_fields": ["weird"]})
    provider.authenticate(provider.idp.url, Answers())
    assert provider.session.calls[1].data == {"weird": "alice", "p": "secret"}


def test_unknown_option_rejected():
    provider = make("form", [LOGIN_PAGE], options={"nope": 1})
    with pytest.raises(ConfigError):
        provider.authenticate(provider.idp.url, Answers())


def test_unknown_provider():
    with pytest.raises(ConfigError, match="Unknown provider"):
        providers.get("does-not-exist")


def test_manual_provider_reads_file(tmp_path):
    saml = tmp_path / "saml.txt"
    saml.write_text("SAMLResponse=abc%2Bdef%3D\n")
    provider = make("manual", [], options={"saml_file": str(saml)})
    assert provider.authenticate("", Answers()) == "abc+def="
