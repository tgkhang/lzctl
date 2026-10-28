import pytest

from lzctl.errors import AuthError
from lzctl.saml import parse_roles, select_role, session_duration

from .conftest import PRINCIPAL_1, ROLE_A, ROLE_B, ROLE_C


def test_parse_roles_normalizes_order(assertion):
    roles = parse_roles(assertion)
    assert [r.role_arn for r in roles] == [ROLE_A, ROLE_B, ROLE_C]
    assert all(r.principal_arn.endswith(":saml-provider/MyIdP") for r in roles)
    assert roles[1].principal_arn == PRINCIPAL_1
    assert roles[2].account_id == "222222222222"
    assert roles[0].name == "Admin"


def test_session_duration(assertion):
    assert session_duration(assertion) == 7200


def test_invalid_assertion():
    with pytest.raises(AuthError):
        parse_roles("not base64 xml!!")


def test_select_by_account_and_name(assertion):
    roles = parse_roles(assertion)
    assert select_role(roles, account_id="111111111111", wanted="ReadOnly").role_arn == ROLE_B
    assert select_role(roles, account_id="222222222222").role_arn == ROLE_C


def test_select_substring_and_ambiguous(assertion):
    roles = parse_roles(assertion)
    assert select_role(roles, wanted="readonly").role_arn == ROLE_B
    with pytest.raises(AuthError, match="Several roles"):
        select_role(roles, wanted="Admin")
    picked = select_role(roles, wanted="Admin", chooser=lambda c: c[-1])
    assert picked.role_arn == ROLE_C


def test_select_errors(assertion):
    roles = parse_roles(assertion)
    with pytest.raises(AuthError, match="no role in account"):
        select_role(roles, account_id="999999999999")
    with pytest.raises(AuthError, match="not offered"):
        select_role(roles, account_id="111111111111", wanted="Billing")
    with pytest.raises(AuthError, match="no AWS roles"):
        select_role([])
