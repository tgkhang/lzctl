from __future__ import annotations

import warnings
from abc import ABC, abstractmethod
from typing import ClassVar

import click
import requests

from .. import __version__
from ..config import IdpConfig
from ..errors import AuthError
from ..prompts import Prompter


class Provider(ABC):
    """Turns a login URL plus user credentials into a base64 SAMLResponse."""

    name: ClassVar[str] = ""
    #: shown by ``lzctl init`` / ``lzctl providers``
    description: ClassVar[str] = ""

    def __init__(self, idp: IdpConfig):
        self.idp = idp
        self.session = requests.Session()
        self.session.verify = idp.verify
        self.session.headers["User-Agent"] = f"lzctl/{__version__}"
        if idp.verify is False:
            warnings.filterwarnings("ignore", message="Unverified HTTPS request")
            click.secho(
                f"WARNING: TLS verification is disabled for idp {idp.name!r}. "
                "Prefer setting ca_bundle.",
                fg="yellow",
                err=True,
            )

    @abstractmethod
    def authenticate(self, url: str, prompter: Prompter) -> str:
        """Return the base64-encoded SAMLResponse destined for AWS."""

    def request(self, method: str, url: str, **kwargs) -> requests.Response:
        kwargs.setdefault("timeout", 30)
        try:
            resp = self.session.request(method, url, **kwargs)
        except requests.exceptions.SSLError as err:
            raise AuthError(
                f"TLS verification failed for {url}. If your network inspects TLS traffic, "
                f"set 'ca_bundle' for idp {self.idp.name!r}. ({err})"
            ) from err
        except requests.RequestException as err:
            raise AuthError(f"Request to {url} failed: {err}") from err
        if resp.status_code >= 500:
            raise AuthError(f"IdP returned HTTP {resp.status_code} for {resp.url}")
        return resp
