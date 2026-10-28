"""Running a function against many account/region pairs in parallel."""

from __future__ import annotations

from collections.abc import Callable, Iterable, Sequence
from concurrent.futures import ThreadPoolExecutor, as_completed
from typing import Any

import boto3
import botocore.exceptions

from .config import Account
from .errors import LzctlError

MAX_WORKERS = 16
EXPIRED_CODES = frozenset({"ExpiredToken", "ExpiredTokenException", "RequestExpired",
                           "InvalidClientTokenId", "UnrecognizedClientException"})

Task = Callable[[boto3.Session, Account, str], Iterable[dict[str, Any]]]


def explain(err: Exception, account: Account) -> str:
    """A short, actionable message for a per-account failure."""
    relogin = f"run 'lzctl login {account.name}'"
    if isinstance(err, botocore.exceptions.ProfileNotFound):
        return f"not logged in, {relogin}"
    if isinstance(err, botocore.exceptions.NoCredentialsError):
        return f"no credentials, {relogin}"
    if isinstance(err, botocore.exceptions.ClientError):
        info = err.response.get("Error", {})
        if info.get("Code") in EXPIRED_CODES:
            return f"session expired or invalid, {relogin}"
        return f"{info.get('Code')}: {info.get('Message', err)}"
    return str(err)


def for_each_account(
    app,
    accounts: Sequence[Account],
    task: Task,
    *,
    regions: Sequence[str] = (),
    max_workers: int = MAX_WORKERS,
) -> list[dict[str, Any]]:
    """Run ``task(session, account, region)`` for every pair and collect the rows.

    A failure in one account is reported on stderr and does not stop the others.
    Raises LzctlError only when *every* job failed.
    """
    ready: list[Account] = []
    failures = 0
    for acct in accounts:
        try:
            boto3.Session(profile_name=acct.profile_name)  # fail fast on missing profiles
            ready.append(acct)
        except botocore.exceptions.ProfileNotFound as err:
            app.warn(f"{acct.name}: {explain(err, acct)}")
            failures += 1

    prod = [a.name for a in ready if app.config.is_production(a)]
    if prod:
        app.warn(f"Production account(s): {', '.join(prod)}")

    jobs = [(a, r) for a in ready for r in (regions or [app.config.region_for(a)])]

    def run(acct: Account, region: str):
        # boto3 sessions are not thread-safe: one per job
        return list(task(boto3.Session(profile_name=acct.profile_name), acct, region))

    rows: list[dict[str, Any]] = []
    with ThreadPoolExecutor(max_workers=max_workers) as pool:
        futures = {pool.submit(run, a, r): (a, r) for a, r in jobs}
        for future in as_completed(futures):
            acct, region = futures[future]
            try:
                rows.extend(future.result())
            except Exception as err:  # noqa: BLE001 - reported per account
                app.warn(f"{acct.name} ({region}): {explain(err, acct)}")
                failures += 1
    if failures:
        app.warn(f"{failures} account/region(s) failed")
        if not rows and failures >= len(jobs) + (len(accounts) - len(ready)):
            raise LzctlError("Every selected account failed")
    return rows
