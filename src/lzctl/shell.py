"""Printing environment variables in the syntax of the user's shell."""

from __future__ import annotations

import os
import shlex
from pathlib import Path

SHELLS = ("bash", "zsh", "sh", "fish", "powershell", "cmd")

EVAL_HINTS = {
    "bash": 'eval "$({cmd})"',
    "zsh": 'eval "$({cmd})"',
    "sh": 'eval "$({cmd})"',
    "fish": "{cmd} | source",
    "powershell": "{cmd} | Invoke-Expression",
    "cmd": 'for /f "delims=" %i in (\'{cmd}\') do %i',
}


def detect_shell() -> str:
    shell = Path(os.environ.get("SHELL", "")).name.lower()
    if shell in ("bash", "zsh", "fish"):
        return shell  # also covers Git Bash / WSL on Windows
    if os.name == "nt":
        # cmd.exe defines PROMPT; PowerShell does not.
        return "cmd" if "PROMPT" in os.environ else "powershell"
    return "sh"


def _ps_quote(value: str) -> str:
    return "'" + value.replace("'", "''") + "'"


def format_env(variables: dict[str, str | None], shell: str | None = None) -> str:
    """Render ``variables`` as shell statements; a ``None`` value unsets the variable."""
    shell = shell or detect_shell()
    lines = []
    for key, value in variables.items():
        if shell == "fish":
            lines.append(f"set -e {key}" if value is None else f"set -gx {key} {shlex.quote(value)}")
        elif shell == "powershell":
            lines.append(
                f"Remove-Item Env:{key} -ErrorAction SilentlyContinue" if value is None
                else f"$env:{key} = {_ps_quote(value)}"
            )
        elif shell == "cmd":
            lines.append(f"set {key}=" if value is None else f"set {key}={value}")
        else:
            lines.append(f"unset {key}" if value is None else f"export {key}={shlex.quote(value)}")
    return "\n".join(lines)


def eval_hint(cmd: str, shell: str | None = None) -> str:
    return EVAL_HINTS[shell or detect_shell()].format(cmd=cmd)
