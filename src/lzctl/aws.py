"""Thin wrappers around the few AWS calls lzctl needs."""

from __future__ import annotations

import contextlib
import json
import os
import re
from collections.abc import Callable, Iterator
from dataclasses import dataclass
from datetime import datetime
from urllib.parse import urlencode

import boto3
import botocore.exceptions
import requests
from botocore import UNSIGNED
from botocore.config import Config as BotoConfig

from .errors import AwsError
from .saml import SamlRole

MAX_CHAINED_DURATION = 3600
FEDERATION_URL = "https://signin.aws.amazon.com/federation"
CONSOLE_URL = "https://console.aws.amazon.com/"


@dataclass(frozen=True)
class AwsCredentials:
    access_key_id: str
    secret_access_key: str
    session_token: str | None = None
    expiration: datetime | None = None

    @classmethod
    def from_sts(cls, data: dict) -> AwsCredentials:
        return cls(data["AccessKeyId"], data["SecretAccessKey"], data["SessionToken"],
                   data.get("Expiration"))

    def client_kwargs(self) -> dict[str, str | None]:
        return {
            "aws_access_key_id": self.access_key_id,
            "aws_secret_access_key": self.secret_access_key,
            "aws_session_token": self.session_token,
        }


@contextlib.contextmanager
def _without_profile_env() -> Iterator[None]:
    """boto3 fails if AWS_PROFILE names a profile that does not exist yet,
    which is exactly the case on a first login."""
    saved = {k: os.environ.pop(k) for k in ("AWS_PROFILE", "AWS_DEFAULT_PROFILE") if k in os.environ}
    try:
        yield
    finally:
        os.environ.update(saved)


def _error_message(err: botocore.exceptions.ClientError) -> tuple[str, str]:
    info = err.response.get("Error", {})
    return info.get("Code", ""), info.get("Message", str(err))


def session_name(username: str | None) -> str:
    name = re.sub(r"[^\w+=,.@-]", "-", f"lzctl-{username or 'user'}")
    return name[:64]


def assume_role_with_saml(
    role: SamlRole,
    assertion: str,
    region: str,
    duration: int,
    warn: Callable[[str], None] = lambda _m: None,
) -> AwsCredentials:
    with _without_profile_env():
        sts = boto3.client("sts", region_name=region, config=BotoConfig(signature_version=UNSIGNED))
    try:
        resp = sts.assume_role_with_saml(
            RoleArn=role.role_arn,
            PrincipalArn=role.principal_arn,
            SAMLAssertion=assertion,
            DurationSeconds=duration,
        )
    except botocore.exceptions.ClientError as err:
        code, msg = _error_message(err)
        if code == "ValidationError" and "DurationSeconds" in msg and duration > 3600:
            warn(f"{role.role_arn} does not allow {duration}s sessions, retrying with 3600s")
            return assume_role_with_saml(role, assertion, region, 3600, warn)
        raise AwsError(f"AssumeRoleWithSAML failed for {role.role_arn}: {msg}") from err
    except botocore.exceptions.BotoCoreError as err:
        raise AwsError(f"AssumeRoleWithSAML failed for {role.role_arn}: {err}") from err
    return AwsCredentials.from_sts(resp["Credentials"])


def assume_role(
    source: AwsCredentials,
    role_arn: str,
    region: str,
    *,
    duration: int = MAX_CHAINED_DURATION,
    username: str | None = None,
    external_id: str | None = None,
) -> AwsCredentials:
    """Role chaining (hub -> spoke). AWS caps chained sessions at one hour."""
    with _without_profile_env():
        sts = boto3.client("sts", region_name=region, **source.client_kwargs())
    kwargs = {
        "RoleArn": role_arn,
        "RoleSessionName": session_name(username),
        "DurationSeconds": min(duration, MAX_CHAINED_DURATION),
    }
    if external_id:
        kwargs["ExternalId"] = external_id
    try:
        resp = sts.assume_role(**kwargs)
    except (botocore.exceptions.ClientError, botocore.exceptions.BotoCoreError) as err:
        msg = _error_message(err)[1] if isinstance(err, botocore.exceptions.ClientError) else err
        raise AwsError(f"AssumeRole failed for {role_arn}: {msg}") from err
    return AwsCredentials.from_sts(resp["Credentials"])


def session_for_profile(profile: str | None, region: str | None = None) -> boto3.Session:
    try:
        return boto3.Session(profile_name=profile, region_name=region)
    except botocore.exceptions.ProfileNotFound as err:
        raise AwsError(f"Profile {profile!r} not found, run 'lzctl login {profile}' first") from err


def caller_identity(session: boto3.Session) -> dict:
    try:
        return session.client("sts").get_caller_identity()
    except (botocore.exceptions.ClientError, botocore.exceptions.BotoCoreError) as err:
        raise AwsError(f"GetCallerIdentity failed: {err}") from err


def console_url(creds: AwsCredentials, destination: str = CONSOLE_URL, issuer: str = "lzctl") -> str:
    """Federated sign-in URL for the AWS console (works with temporary credentials)."""
    if not creds.session_token:
        raise AwsError("Console sign-in needs temporary credentials (a session token)")
    payload = json.dumps({
        "sessionId": creds.access_key_id,
        "sessionKey": creds.secret_access_key,
        "sessionToken": creds.session_token,
    })
    try:
        resp = requests.get(FEDERATION_URL, params={"Action": "getSigninToken", "Session": payload},
                            timeout=30)
        resp.raise_for_status()
        token = resp.json()["SigninToken"]
    except (requests.RequestException, ValueError, KeyError) as err:
        raise AwsError(f"Could not get a console sign-in token: {err}") from err
    query = urlencode({"Action": "login", "Issuer": issuer, "Destination": destination,
                       "SigninToken": token})
    return f"{FEDERATION_URL}?{query}"
