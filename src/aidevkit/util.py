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
E_WORKTREE_EXISTS = 11
E_DEP_MISSING = 12
E_REPO_NOT_FOUND = 13

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


def run(cmd: list[str], *, check: bool = False, cwd: Optional[Path] = None) -> RunResult:
    proc = subprocess.run(
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
