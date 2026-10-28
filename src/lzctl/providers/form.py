"""A generic HTML-form walker for IdPs that log in with plain forms.

Starting at the IdP-initiated SSO URL it repeatedly:
  1. stops when the page contains a SAMLResponse,
  2. otherwise finds the login form, fills username / password / one-time-code
     fields it recognises, keeps hidden fields, and submits it.

Most PingFederate, ADFS, Keycloak, Shibboleth and SimpleSAMLphp setups work this
way. The subclasses only pin down field names and error messages. Every rule can
be overridden per IdP through ``options`` in the config file.

Push-style MFA (number matching, Duo push, ...) and JavaScript-only login pages
cannot be automated this way; use the ``manual`` provider for those.
"""

from __future__ import annotations

from dataclasses import dataclass, field, fields, replace
from typing import Any
from urllib.parse import urljoin

from bs4 import BeautifulSoup, Tag

from ..errors import AuthError, ConfigError, CredentialsRejected
from ..prompts import Prompter
from .base import Provider

OTP_HINTS = ("otp", "totp", "passcode", "token", "challengeresponse", "verificationcode", "mfa")
USERNAME_HINTS = ("user", "login", "email", "identifier", "uid", "account")
VISIBLE_TYPES = ("text", "email", "tel", "number", "password")


@dataclass(frozen=True)
class FormRules:
    username_fields: tuple[str, ...] = ()
    password_fields: tuple[str, ...] = ()
    otp_fields: tuple[str, ...] = ()
    extra_fields: dict[str, str] = field(default_factory=dict)
    error_markers: tuple[str, ...] = ()
    otp_rejected_markers: tuple[str, ...] = ()
    max_steps: int = 10

    def with_options(self, options: dict[str, Any]) -> FormRules:
        known = {f.name for f in fields(self)}
        unknown = set(options) - known - {"saml_file", "open_browser"}
        if unknown:
            raise ConfigError(f"Unknown provider options: {', '.join(sorted(unknown))}")
        changes: dict[str, Any] = {}
        for key, value in options.items():
            if key not in known:
                continue
            if key == "extra_fields":
                changes[key] = {str(k): str(v) for k, v in (value or {}).items()}
            elif key == "max_steps":
                changes[key] = int(value)
            else:
                changes[key] = tuple([value] if isinstance(value, str) else value or ())
        return replace(self, **changes)


def find_saml_response(soup: BeautifulSoup) -> str | None:
    tag = soup.find("input", attrs={"name": "SAMLResponse"})
    return tag.get("value") if isinstance(tag, Tag) and tag.get("value") else None


class FormProvider(Provider):
    name = "form"
    description = "Generic HTML login forms (auto-detects fields)"
    rules = FormRules()

    def authenticate(self, url: str, prompter: Prompter) -> str:
        if not url:
            raise ConfigError(f"idps.{self.idp.name}.url is required")
        rules = self.rules.with_options(self.idp.options)
        resp = self.request("GET", url)
        submitted: set[str] = set()

        for _ in range(rules.max_steps):
            soup = BeautifulSoup(resp.text, "html.parser")
            assertion = find_saml_response(soup)
            if assertion:
                return assertion
            if submitted:
                self._check_errors(resp.text, rules, submitted)

            form = select_form(soup, rules)
            if form is None:
                raise AuthError(
                    f"The IdP page at {resp.url} has neither a login form nor a SAMLResponse. "
                    "It may need JavaScript or push MFA; try provider 'manual'."
                )
            # The same kind of form came back: the IdP did not accept it.
            repeated = form_kinds(form, rules) & submitted & {"password", "otp"}
            if "otp" in repeated:
                raise CredentialsRejected("The MFA code was rejected")
            if repeated:
                raise CredentialsRejected("Username or password was rejected")
            data, kinds = fill_form(form, rules, prompter)
            submitted |= kinds

            action = urljoin(resp.url, form.get("action") or resp.url)
            if (form.get("method") or "get").lower() == "post":
                resp = self.request("POST", action, data=data)
            else:
                resp = self.request("GET", action, params=data)

        raise AuthError(f"Gave up after {rules.max_steps} pages without receiving a SAMLResponse")

    @staticmethod
    def _check_errors(html: str, rules: FormRules, submitted: set[str]) -> None:
        if "otp" in submitted:
            for marker in rules.otp_rejected_markers:
                if marker in html:
                    raise CredentialsRejected(f"The MFA code was rejected ({marker!r})")
        for marker in rules.error_markers:
            if marker in html:
                raise CredentialsRejected(f"The IdP reported an error: {marker!r}")


def _classify(inp: Tag, rules: FormRules) -> str | None:
    name = inp.get("name") or ""
    if name in rules.password_fields:
        return "password"
    if name in rules.otp_fields:
        return "otp"
    if name in rules.username_fields:
        return "username"
    kind = (inp.get("type") or "text").lower()
    if kind not in VISIBLE_TYPES:
        return None
    lname = name.lower()
    if inp.get("autocomplete") == "one-time-code" or any(h in lname for h in OTP_HINTS):
        return "otp"
    if kind == "password":
        return "password" if not rules.password_fields else None
    if kind in ("text", "email") and any(h in lname for h in USERNAME_HINTS):
        return "username" if not rules.username_fields else None
    return None


def form_kinds(form: Tag, rules: FormRules) -> set[str]:
    return {k for k in (_classify(i, rules) for i in form.find_all("input")) if k}


def select_form(soup: BeautifulSoup, rules: FormRules) -> Tag | None:
    forms = [f for f in soup.find_all("form") if isinstance(f, Tag)]
    for form in forms:
        if any(_classify(i, rules) for i in form.find_all("input")):
            return form
    # e.g. "JavaScript is disabled, press Continue" relay pages
    return next((f for f in forms if (f.get("method") or "").lower() == "post"), None)


def fill_form(form: Tag, rules: FormRules, prompter: Prompter) -> tuple[dict[str, str], set[str]]:
    data: dict[str, str] = {}
    kinds: set[str] = set()
    for inp in form.find_all(["input", "select", "textarea"]):
        name = inp.get("name")
        if not name:
            continue
        kind = (inp.get("type") or "text").lower()
        if kind in ("submit", "button", "image", "reset"):
            continue
        if kind in ("checkbox", "radio") and not inp.has_attr("checked"):
            continue
        role = _classify(inp, rules) if inp.name == "input" else None
        if role == "username":
            data[name] = prompter.username()
        elif role == "password":
            data[name] = prompter.password()
        elif role == "otp":
            data[name] = prompter.mfa_code()
        elif inp.name == "select":
            option = inp.find("option", selected=True) or inp.find("option")
            data[name] = option.get("value", option.text) if isinstance(option, Tag) else ""
        else:
            data[name] = inp.get("value", "") if inp.name == "input" else inp.text
        if role:
            kinds.add(role)
    button = form.find(["button", "input"], attrs={"type": "submit", "name": True})
    if isinstance(button, Tag):
        data.setdefault(button["name"], button.get("value", ""))
    for key, value in rules.extra_fields.items():
        if key in data or not kinds:
            data[key] = value
    return data, kinds


class PingFederateProvider(FormProvider):
    name = "pingfederate"
    description = "PingFederate / PingOne (startSSO.ping) with optional OTP"
    rules = FormRules(
        username_fields=("pf.username",),
        password_fields=("pf.pass",),
        otp_fields=("pf.challengeResponse", "pf.otp", "otp"),
        extra_fields={"pf.ok": "clicked", "pf.cancel": ""},
        error_markers=(
            "Your session could not be established",
            "Due to user inactivity, your session expired",
        ),
    )


class AdfsProvider(FormProvider):
    name = "adfs"
    description = "Microsoft AD FS (IdpInitiatedSignOn.aspx), forms authentication"
    rules = FormRules(
        username_fields=("UserName",),
        password_fields=("Password",),
        otp_fields=("VerificationCode", "Otp", "SecurityCode"),
        error_markers=("Incorrect user ID or password",),
    )


class KeycloakProvider(FormProvider):
    name = "keycloak"
    description = "Keycloak (IdP-initiated client URL) with optional OTP"
    rules = FormRules(
        username_fields=("username",),
        password_fields=("password",),
        otp_fields=("otp", "totp"),
        otp_rejected_markers=("Invalid authenticator code",),
        error_markers=("Invalid username or password",),
    )
