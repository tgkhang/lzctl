"""Login orchestration: IdP -> SAML assertion -> STS -> (optional) role chaining.

Accounts that resolve to the same IdP URL share one authentication, so logging in
to twenty accounts behind one IdP asks for your password and MFA once. Accounts
with ``via`` are reached by assuming a role from their parent account's session
(the usual "hub account -> workload accounts" landing zone pattern).
"""

from __future__ import annotations

from collections.abc import Callable, Iterable
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from urllib.parse import urlencode

from . import providers
from .aws import AwsCredentials, assume_role, assume_role_with_saml
from .config import Account, Config, IdpConfig
from .errors import ConfigError, CredentialsRejected
from .prompts import Prompter
from .saml import SamlRole, parse_roles, select_role, session_duration

DEFAULT_DURATION = 3600
CHAIN_WORKERS = 8

Log = Callable[[str], None]


@dataclass
class LoginResult:
    account: Account
    role_arn: str
    credentials: AwsCredentials
    region: str


class _Template(dict):
    def __missing__(self, key: str) -> str:
        return ""


def build_idp_url(idp: IdpConfig, account: Account | None = None) -> str:
    """Append ``idp.url_params`` (templated) and ``account.url_params`` to the IdP URL.

    Templates may use {account_id}, {account_name} and any key of account.url_params.
    """
    values = _Template()
    params: dict[str, str] = {}
    if account:
        values.update(account.url_params, account_id=account.id, account_name=account.name)
    for key, template in idp.url_params.items():
        value = template.format_map(values)
        if value:
            params[key] = value
    if account:
        params.update(account.url_params)
    if not params:
        return idp.url
    return idp.url + ("&" if "?" in idp.url else "?") + urlencode(params)


def authenticate(idp: IdpConfig, url: str, prompter: Prompter) -> str:
    provider = providers.get(idp.provider)(idp)
    try:
        assertion = provider.authenticate(url, prompter)
    except CredentialsRejected:
        prompter.password_rejected()
        raise
    prompter.login_succeeded()
    return assertion


def with_parents(config: Config, accounts: Iterable[Account]) -> list[Account]:
    """Accounts plus everything they chain through, parents first."""
    ordered: list[Account] = []
    seen: set[str] = set()

    def visit(acct: Account, stack: tuple[str, ...]) -> None:
        if acct.name in stack:
            raise ConfigError(f"'via' loop: {' -> '.join((*stack, acct.name))}")
        if acct.name in seen:
            return
        if acct.via:
            visit(config.accounts[acct.via], (*stack, acct.name))
        seen.add(acct.name)
        ordered.append(acct)

    for acct in accounts:
        visit(acct, ())
    return ordered


def _depth(config: Config, acct: Account) -> int:
    depth = 0
    while acct.via:
        acct = config.accounts[acct.via]
        depth += 1
    return depth


class LoginRunner:
    def __init__(
        self,
        config: Config,
        prompter_for: Callable[[IdpConfig], Prompter],
        *,
        role_override: str | None = None,
        duration: int | None = None,
        log: Log = lambda _m: None,
    ):
        self.config = config
        self.prompter_for = prompter_for
        self.role_override = role_override
        self.duration = duration
        self.log = log
        self._prompters: dict[str, Prompter] = {}

    def prompter(self, idp: IdpConfig) -> Prompter:
        if idp.name not in self._prompters:
            self._prompters[idp.name] = self.prompter_for(idp)
        return self._prompters[idp.name]

    def _chooser(self, idp: IdpConfig) -> Callable[[list[SamlRole]], SamlRole]:
        def choose(roles: list[SamlRole]) -> SamlRole:
            labels = []
            for role in roles:
                acct = self.config.account_by_id(role.account_id)
                where = f"{acct.name} ({role.account_id})" if acct else role.account_id
                labels.append(f"{where}  {role.name}")
            return roles[self.prompter(idp).choose("Choose a role:", labels)]
        return choose

    def _duration(self, account: Account, idp: IdpConfig, assertion: str) -> int:
        return (self.duration or account.duration or idp.session_duration
                or session_duration(assertion) or DEFAULT_DURATION)

    def login(self, accounts: list[Account]) -> list[LoginResult]:
        requested = {a.name for a in accounts}
        ordered = with_parents(self.config, accounts)
        results: dict[str, LoginResult] = {}

        groups: dict[tuple[str, str], list[Account]] = {}
        for acct in (a for a in ordered if not a.via):
            idp = self.config.idp(account=acct)
            groups.setdefault((idp.name, build_idp_url(idp, acct)), []).append(acct)

        for (idp_name, url), group in groups.items():
            idp = self.config.idps[idp_name]
            names = ", ".join(a.name for a in group)
            self.log(f"Authenticating with {idp_name} for {names}")
            assertion = authenticate(idp, url, self.prompter(idp))
            roles = parse_roles(assertion)
            for acct in group:
                wanted = self.role_override if acct.name in requested and self.role_override \
                    else acct.role
                role = select_role(roles, account_id=acct.id, wanted=wanted,
                                   chooser=self._chooser(idp))
                region = self.config.region_for(acct)
                creds = assume_role_with_saml(role, assertion, region,
                                              self._duration(acct, idp, assertion), self.log)
                results[acct.name] = LoginResult(acct, role.role_arn, creds, region)

        chained = [a for a in ordered if a.via]
        for level in sorted({_depth(self.config, a) for a in chained}):
            batch = [a for a in chained if _depth(self.config, a) == level]
            with ThreadPoolExecutor(max_workers=CHAIN_WORKERS) as pool:
                for result in pool.map(lambda a: self._chain(a, results[a.via]), batch):
                    results[result.account.name] = result

        return [results[a.name] for a in ordered]

    def _chain(self, acct: Account, parent: LoginResult) -> LoginResult:
        role_arn = self.config.chain_role_for(acct)
        region = self.config.region_for(acct)
        idp = self.config.idp(account=self.config.accounts[acct.via])
        creds = assume_role(
            parent.credentials, role_arn, region,
            duration=self.duration or acct.duration or DEFAULT_DURATION,
            username=self.prompter(idp).known_username,
            external_id=acct.external_id,
        )
        return LoginResult(acct, role_arn, creds, region)

    def login_adhoc(self, idp: IdpConfig, profile: str | None = None) -> LoginResult:
        """No account given: authenticate and let the user pick any offered role."""
        assertion = authenticate(idp, build_idp_url(idp), self.prompter(idp))
        role = select_role(parse_roles(assertion), wanted=self.role_override,
                           chooser=self._chooser(idp))
        known = self.config.account_by_id(role.account_id)
        acct = known or Account(name=profile or role.account_id, id=role.account_id)
        if profile:
            acct = Account(**{**acct.__dict__, "profile": profile})
        region = self.config.region_for(acct)
        dur = self.duration or acct.duration or idp.session_duration \
            or session_duration(assertion) or DEFAULT_DURATION
        creds = assume_role_with_saml(role, assertion, region, dur, self.log)
        return LoginResult(acct, role.role_arn, creds, region)
