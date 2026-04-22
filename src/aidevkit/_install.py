"""Install-method detection for self-management commands.

Determines whether the running `aidevkit` was installed via `uv tool install`
(manageable), `pip` / source checkout (not manageable by DevKit), or an
unknown method. Used by `uninstall`, `update`, and `check-update` to decide
whether to proceed or print guidance per FR-SELF-010.
"""
from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path
from typing import Literal, Optional

from . import util

Method = Literal["uv-tool", "pip", "source", "unknown"]

_UV_TOOL_ENTRY_RE = re.compile(r"^([A-Za-z0-9_.-]+)\s+v?([0-9][^\s]*)")


@dataclass
class InstallInfo:
    method: Method
    installed_version: Optional[str]
    tool_venv_path: Optional[Path]
    manageable: bool


def _parse_uv_tool_list(text: str, package: str) -> Optional[str]:
    """Parse `uv tool list` output for `<package> v<version>`.

    `uv tool list` lines look like:
        aidevkit v0.3.0
        - devkit
    """
    for line in text.splitlines():
        stripped = line.strip()
        if not stripped or stripped.startswith("-"):
            continue
        m = _UV_TOOL_ENTRY_RE.match(stripped)
        if m and m.group(1) == package:
            return m.group(2)
    return None


def _parse_pip_show_version(text: str) -> Optional[str]:
    for line in text.splitlines():
        if line.lower().startswith("version:"):
            return line.split(":", 1)[1].strip()
    return None


def _parse_pip_show_location(text: str) -> Optional[str]:
    for line in text.splitlines():
        if line.lower().startswith("location:"):
            return line.split(":", 1)[1].strip()
    return None


def detect_install_info(package: str = "aidevkit") -> InstallInfo:
    """Detect how `package` is installed. Order: uv tool → pip → source → unknown."""
    uv_list = util.run(["uv", "tool", "list"])
    if uv_list.code == 0:
        version = _parse_uv_tool_list(uv_list.stdout, package)
        if version is not None:
            return InstallInfo(
                method="uv-tool",
                installed_version=version,
                tool_venv_path=None,
                manageable=True,
            )

    pip_show = util.run(["pip", "show", package])
    if pip_show.code == 0 and pip_show.stdout.strip():
        version = _parse_pip_show_version(pip_show.stdout)
        location = _parse_pip_show_location(pip_show.stdout)
        method: Method = "pip"
        if location and ("/site-packages" not in location):
            # `pip show` reports a location that does NOT look like a standard
            # venv/site-packages — treat as a source/editable checkout.
            method = "source"
        return InstallInfo(
            method=method,
            installed_version=version,
            tool_venv_path=None,
            manageable=False,
        )

    return InstallInfo(
        method="unknown",
        installed_version=None,
        tool_venv_path=None,
        manageable=False,
    )
