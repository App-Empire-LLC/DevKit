from __future__ import annotations

import shutil

import typer

from . import config as _config
from . import projects as _projects
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


def _check_devkit_setup() -> bool:
    """Resolve projects-home, validate config, parse PROJECTS.md.

    Returns True if all three pass; emits one `[ok]` or `[FAIL]` line each.
    """
    try:
        projects_home = _config.resolve_projects_home()
    except typer.Exit:
        _fail(
            "$PROJECTS_HOME",
            "not resolvable (set $PROJECTS_HOME or "
            "~/.devkit/config.yaml#projects_home)",
        )
        return False
    _ok("$PROJECTS_HOME", str(projects_home))

    try:
        cfg = _config.load_merged_config(projects_home)
    except typer.Exit:
        _fail(".devkit/config.yaml", "validation failed (see error above)")
        return False
    _ok(".devkit/config.yaml", f"schema v{cfg.version}, org={cfg.org}")

    catalog_path = projects_home / ".devkit" / "PROJECTS.md"
    try:
        catalog = _projects.parse_projects_md(catalog_path)
    except typer.Exit:
        _fail(".devkit/PROJECTS.md", f"parse failed: {catalog_path}")
        return False
    _ok(".devkit/PROJECTS.md", f"{len(catalog.entries)} repo(s) catalogued")

    return True


def cmd_doctor() -> int:
    out.print("[devkit] DevKit doctor — checking dependencies and environment")

    results: list[bool] = []
    for binary in ("bash", "git", "gh", "jq"):
        results.append(_check_binary(binary))

    results.append(_check_devkit_setup())
    results.append(_check_gh_auth())

    failed = sum(1 for ok in results if not ok)
    if failed:
        err.print(f"[devkit] doctor: {failed} check(s) failed")
        return E_DEP_MISSING
    return 0
