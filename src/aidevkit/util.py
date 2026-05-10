"""Shared helpers for DevKit CLI.

This module is the **canonical shell seam** for DevKit. All `git`, `gh`, and
other subprocess invocations MUST flow through `run()` (or its wrappers `git()`
/ `gh()`). Other modules MUST NOT `import subprocess` directly — doing so
bypasses the seam that tests use to enforce hermeticity (see
`tests/conftest.py::_fail_on_unmocked_shell`).
"""
from __future__ import annotations

import subprocess
from dataclasses import dataclass
from pathlib import Path
from typing import Optional

import typer
from rich.console import Console

E_USAGE = 2
E_REPOS_MISSING = 10
E_WORKSPACE_EXISTS = 11
E_DEP_MISSING = 12
E_REPO_NOT_FOUND = 13
E_PRS_NOT_MERGED = 14
E_ARCHIVE_COLLISION = 15
E_WORKSPACE_MISSING = 16
E_ORIGIN_MAIN_UNAVAILABLE = 17
E_NOT_IN_WORKSPACE = 20
E_SYNC_PARTIAL = 21
E_BEHIND_ORIGIN = 22
E_PREFLIGHT_FAILED = 23
E_NOT_IN_PER_ISSUE_WORKSPACE = 24
E_INSTALL_NOT_UV_TOOL = 26
E_CHECK_UPDATE_INDEX_UNAVAILABLE = 27
E_CONFIG_INVALID = 70
E_CATALOG_INVALID = 71
E_TEMPLATE_COLLISION = 72
E_FINDINGS_INVALID = 74
E_GH_COMMENT_FAILED = 75

out = Console(markup=False, highlight=False, soft_wrap=True)
err = Console(stderr=True, markup=False, highlight=False, soft_wrap=True)


def log(msg: str) -> None:
    err.print(f"[devkit] {msg}")


def info(msg: str) -> None:
    out.print(f"[devkit] {msg}")


def die(msg: str, code: int = 1) -> None:
    err.print(f"[devkit] ERROR: {msg}")
    raise typer.Exit(code=code)


@dataclass
class RunResult:
    code: int
    stdout: str
    stderr: str


class _Runner:
    """Instance-scoped wrapper around subprocess.run.

    The hermeticity guard in tests/conftest.py patches this instance's `run`
    attribute. Using an instance method instead of a module-level reference to
    subprocess.run prevents the patch from leaking into the global subprocess
    module — integration-test fixtures that call subprocess.run directly are
    unaffected.
    """

    def run(self, *args, **kwargs):
        return subprocess.run(*args, **kwargs)


_runner = _Runner()


def run(cmd: list[str], *, check: bool = False, cwd: Optional[Path] = None) -> RunResult:
    proc = _runner.run(
        cmd,
        cwd=cwd,
        capture_output=True,
        text=True,
        check=check,
    )
    return RunResult(proc.returncode, proc.stdout, proc.stderr)


def git(*args: str, check: bool = False, cwd: Optional[Path] = None) -> RunResult:
    return run(["git", *args], check=check, cwd=cwd)


def gh(*args: str, check: bool = False, cwd: Optional[Path] = None) -> RunResult:
    return run(["gh", *args], check=check, cwd=cwd)
