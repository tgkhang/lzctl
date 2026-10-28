from __future__ import annotations

import base64
from types import SimpleNamespace

import pytest

ROLE_A = "arn:aws:iam::111111111111:role/Admin"
ROLE_B = "arn:aws:iam::111111111111:role/ReadOnly"
ROLE_C = "arn:aws:iam::222222222222:role/Admin"
PRINCIPAL_1 = "arn:aws:iam::111111111111:saml-provider/MyIdP"
PRINCIPAL_2 = "arn:aws:iam::222222222222:saml-provider/MyIdP"


def make_assertion(role_values, duration=None) -> str:
    values = "".join(f"<saml:AttributeValue>{v}</saml:AttributeValue>" for v in role_values)
    duration_attr = (
        '<saml:Attribute Name="https://aws.amazon.com/SAML/Attributes/SessionDuration">'
        f"<saml:AttributeValue>{duration}</saml:AttributeValue></saml:Attribute>"
        if duration else ""
    )
    xml = (
        '<samlp:Response xmlns:samlp="urn:oasis:names:tc:SAML:2.0:protocol" '
        'xmlns:saml="urn:oasis:names:tc:SAML:2.0:assertion"><saml:Assertion>'
        "<saml:AttributeStatement>"
        f'<saml:Attribute Name="https://aws.amazon.com/SAML/Attributes/Role">{values}</saml:Attribute>'
        f"{duration_attr}</saml:AttributeStatement></saml:Assertion></samlp:Response>"
    )
    return base64.b64encode(xml.encode()).decode()


@pytest.fixture
def assertion() -> str:
    return make_assertion([
        f"{ROLE_A},{PRINCIPAL_1}",
        f"{PRINCIPAL_1},{ROLE_B}",  # reversed order, as some IdPs send it
        f"{ROLE_C},{PRINCIPAL_2}",
    ], duration=7200)


class FakeHttp:
    """Stands in for requests.Session: serves canned pages, records requests."""

    def __init__(self, pages):
        self.pages = list(pages)
        self.calls = []

    def request(self, method, url, **kwargs):
        self.calls.append(SimpleNamespace(method=method, url=url, **kwargs))
        page = self.pages.pop(0)
        return SimpleNamespace(text=page, url=url, status_code=200)


@pytest.fixture
def aws_files(tmp_path, monkeypatch):
    creds = tmp_path / "aws" / "credentials"
    cfg = tmp_path / "aws" / "config"
    monkeypatch.setenv("AWS_SHARED_CREDENTIALS_FILE", str(creds))
    monkeypatch.setenv("AWS_CONFIG_FILE", str(cfg))
    return SimpleNamespace(credentials=creds, config=cfg)


class FakeBoto:
    """Stands in for boto3.Session. ``responses`` maps service -> operation -> result,
    where a result is a dict, a list of pages (for paginators), or a callable(**kwargs)."""

    def __init__(self, responses, profile_name=None, region_name=None):
        self.responses = responses
        self.profile_name = profile_name

    @classmethod
    def factory(cls, responses):
        return lambda profile_name=None, region_name=None: cls(responses, profile_name, region_name)

    def client(self, service, region_name=None):
        ops = self.responses.get(service, {})

        def call(op, **kwargs):
            result = ops[op]
            return result(**kwargs) if callable(result) else result

        class Paginator:
            def __init__(self, op):
                self.op = op

            def paginate(self, **kwargs):
                pages = call(self.op, **kwargs)
                return pages if isinstance(pages, list) else [pages]

        client = SimpleNamespace(get_paginator=Paginator)
        for op in ops:
            setattr(client, op, lambda _op=op, **kw: call(_op, **kw))
        return client
