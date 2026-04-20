from __future__ import annotations

import os
import shutil
from pathlib import Path

from .util import E_DEP_MISSING, err, gh, out

_LABEL_WIDTH = 28


def _ok(label: str, value: str) -> None:
    out.print(f"  [ok]   {label:<{_LABEL_WIDTH}} {value}")


def _fail(label: str, remediation: str) -> None:
    out.print(f"  [FAIL] {label:<{_LABEL_WIDTH}} {remediation}")


def _check_binary(name: str) -> bool:
    path = shutil.which(name)
    if path:
        _ok(name, path)
        return True
    _fail(name, "not found in PATH")
    return False


def _check_env_dir(var: str) -> bool:
    val = os.environ.get(var)
    if not val:
        _fail(f"${var}", "not set")
        return False
    if not Path(val).is_dir():
        _fail(f"${var}", f"not a directory: {val}")
        return False
    _ok(f"${var}", val)
    return True


def _check_gh_auth() -> bool:
    res = gh("auth", "status")
    if res.code != 0:
        _fail("gh auth", "not authenticated — run 'gh auth login'")
        return False
    user = _extract_gh_user(res.stderr or res.stdout)
    _ok("gh auth", f"authenticated as {user}" if user else "authenticated")
    return True


def _extract_gh_user(text: str) -> str:
    for line in text.splitlines():
        line = line.strip()
        if "Logged in to" in line and " as " in line:
            _, _, tail = line.partition(" as ")
            return tail.split()[0].rstrip(".")
        if line.startswith("account "):
            return line.split()[1]
    return ""


def cmd_doctor() -> int:
    out.print("[devkit] DevKit doctor — checking dependencies and environment")

    results: list[bool] = []
    for binary in ("bash", "git", "gh", "jq"):
        results.append(_check_binary(binary))

    for var in ("APP_EMPIRE_PROJECTS", "APP_EMPIRE_WORKTREES_HOME"):
        results.append(_check_env_dir(var))

    results.append(_check_gh_auth())

    failed = sum(1 for ok in results if not ok)
    if failed:
        err.print(f"[devkit] doctor: {failed} check(s) failed")
        return E_DEP_MISSING
    return 0
