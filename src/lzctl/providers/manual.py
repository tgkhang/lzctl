"""Works with *any* IdP: you log in with your browser and hand lzctl the SAMLResponse.

Useful for push MFA, passkeys, or JavaScript-heavy login pages that the form
walker cannot drive. The SAMLResponse is read from (first match wins):
  1. options.saml_file / LZCTL_SAML_FILE (a file containing the value)
  2. stdin, when it is not a terminal:  pbpaste | lzctl login dev
  3. the clipboard, after you press Enter
"""

from __future__ import annotations

import os
import shutil
import subprocess
import sys
import webbrowser
from pathlib import Path
from urllib.parse import unquote

from ..errors import AuthError
from ..prompts import Prompter
from .base import Provider

INSTRUCTIONS = """\
1. Sign in to AWS through your IdP in a browser{url_hint}.
2. Before choosing a role, open DevTools > Network and find the POST to
   https://signin.aws.amazon.com/saml
3. Copy the value of the 'SAMLResponse' form field to the clipboard."""


def read_clipboard() -> str:
    if sys.platform == "darwin":
        commands = [["pbpaste"]]
    elif os.name == "nt":
        commands = [["powershell", "-NoProfile", "-Command", "Get-Clipboard -Raw"]]
    else:
        commands = [["wl-paste", "--no-newline"], ["xclip", "-o", "-selection", "clipboard"],
                    ["xsel", "--clipboard", "--output"]]
    for cmd in commands:
        if shutil.which(cmd[0]):
            result = subprocess.run(cmd, capture_output=True, text=True, check=False)
            if result.returncode == 0:
                return result.stdout
    raise AuthError(
        "Could not read the clipboard (install wl-clipboard or xclip on Linux). "
        "Save the SAMLResponse to a file and set LZCTL_SAML_FILE instead."
    )


class ManualProvider(Provider):
    name = "manual"
    description = "Any IdP: log in with your browser, paste the SAMLResponse"

    def authenticate(self, url: str, prompter: Prompter) -> str:
        path = self.idp.options.get("saml_file") or os.environ.get("LZCTL_SAML_FILE")
        if path:
            text = Path(path).expanduser().read_text(encoding="utf-8")
        elif not sys.stdin.isatty():
            text = sys.stdin.read()
        else:
            prompter.info(INSTRUCTIONS.format(url_hint=f" ({url})" if url else ""))
            if url and self.idp.options.get("open_browser", True):
                webbrowser.open(url)
            prompter.ask("Press Enter once the SAMLResponse is in your clipboard", default="")
            text = read_clipboard()
        # Values copied from a raw request body are URL-encoded.
        value = unquote(text.strip().removeprefix("SAMLResponse="))
        if not value:
            raise AuthError("No SAMLResponse provided")
        return value
