"""Parsing the AWS-specific parts of a SAML 2.0 assertion."""

from __future__ import annotations

import base64
from collections.abc import Callable, Sequence
from dataclasses import dataclass

from defusedxml import DefusedXmlException
from defusedxml import ElementTree as ET

from .errors import AuthError

SAML_NS = "urn:oasis:names:tc:SAML:2.0:assertion"
ROLE_ATTR = "https://aws.amazon.com/SAML/Attributes/Role"
DURATION_ATTR = "https://aws.amazon.com/SAML/Attributes/SessionDuration"


@dataclass(frozen=True, order=True)
class SamlRole:
    role_arn: str
    principal_arn: str

    @property
    def account_id(self) -> str:
        return self.role_arn.split(":")[4]

    @property
    def name(self) -> str:
        return self.role_arn.rsplit("/", 1)[-1]


def _attributes(assertion: str) -> dict[str, list[str]]:
    try:
        root = ET.fromstring(base64.b64decode(assertion))
    except (ValueError, ET.ParseError, DefusedXmlException) as err:
        raise AuthError(f"The IdP returned an invalid SAMLResponse: {err}") from err
    attrs: dict[str, list[str]] = {}
    for attr in root.iter(f"{{{SAML_NS}}}Attribute"):
        values = [v.text.strip() for v in attr.iter(f"{{{SAML_NS}}}AttributeValue") if v.text]
        attrs.setdefault(attr.get("Name", ""), []).extend(values)
    return attrs


def parse_roles(assertion: str) -> list[SamlRole]:
    """Return the roles offered by the assertion, sorted for stable output.

    Each value is "role_arn,principal_arn", but IdPs disagree on the order.
    """
    roles = set()
    for value in _attributes(assertion).get(ROLE_ATTR, []):
        parts = [p.strip() for p in value.split(",")]
        role = next((p for p in parts if ":role/" in p), None)
        principal = next((p for p in parts if ":saml-provider/" in p), None)
        if role and principal:
            roles.add(SamlRole(role, principal))
    return sorted(roles)


def session_duration(assertion: str) -> int | None:
    values = _attributes(assertion).get(DURATION_ATTR)
    try:
        return int(values[0]) if values else None
    except ValueError:
        return None


def select_role(
    roles: Sequence[SamlRole],
    *,
    account_id: str | None = None,
    wanted: str | None = None,
    chooser: Callable[[list[SamlRole]], SamlRole] | None = None,
) -> SamlRole:
    """Pick one role.

    ``wanted`` may be a full ARN, an exact role name, or a substring of the ARN.
    When several roles remain, ``chooser`` decides (interactive prompt); without
    a chooser that is an error.
    """
    if not roles:
        raise AuthError(
            "The SAML assertion contains no AWS roles. Check that your IdP grants you "
            "access to AWS (group membership) and that you entered your MFA code if required."
        )
    candidates = [r for r in roles if account_id is None or r.account_id == account_id]
    if not candidates:
        offered = ", ".join(sorted({r.account_id for r in roles}))
        raise AuthError(f"The IdP offered no role in account {account_id}. Offered: {offered}")
    if wanted:
        exact = [r for r in candidates if wanted in (r.role_arn, r.name)]
        matches = exact or [r for r in candidates if wanted.lower() in r.role_arn.lower()]
        if not matches:
            offered = ", ".join(r.name for r in candidates)
            raise AuthError(f"Role {wanted!r} was not offered. Available: {offered}")
        candidates = matches
    if len(candidates) == 1:
        return candidates[0]
    if chooser is None:
        names = ", ".join(r.role_arn for r in candidates)
        raise AuthError(f"Several roles match, pass --role to pick one: {names}")
    return chooser(candidates)
