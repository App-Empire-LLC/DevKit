"""Integration test for `devkit add-repo`: real git + real filesystem."""
from __future__ import annotations

import subprocess
from pathlib import Path

import pytest

from aidevkit import add_repo as add_repo_mod
from aidevkit.util import RunResult


def _real_run(cmd: list[str], *, check: bool = False, cwd: Path | None = None) -> RunResult:
    proc = subprocess.run(
        cmd, cwd=cwd, capture_output=True, text=True, check=check,
    )
    return RunResult(code=proc.returncode, stdout=proc.stdout, stderr=proc.stderr)


def test_add_repo_creates_real_git_worktree(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    # Seed a real source repo
    projects = tmp_path / "projects"
    projects.mkdir()
    source = projects / "AuthService"
    source.mkdir()
    for cmd in (
        ["git", "init", "--initial-branch=main"],
        ["git", "config", "user.email", "t@t.t"],
        ["git", "config", "user.name", "T"],
    ):
        subprocess.run(cmd, cwd=source, check=True, capture_output=True)
    (source / "README.md").write_text("hello\n")
    subprocess.run(["git", "add", "."], cwd=source, check=True, capture_output=True)
    subprocess.run(
        ["git", "commit", "-m", "seed"],
        cwd=source, check=True, capture_output=True,
    )

    # Build the per-issue workspace
    home = tmp_path / "worktrees_home"
    home.mkdir()
    workspace = home / "DevKit-issue-77"
    workspace.mkdir()

    monkeypatch.setenv("APP_EMPIRE_WORKTREES_HOME", str(home))
    monkeypatch.setenv("APP_EMPIRE_PROJECTS", str(projects))
    monkeypatch.chdir(workspace)
    monkeypatch.setattr("aidevkit.util.run", _real_run)

    exit_code = add_repo_mod.cmd_add_repo("AuthService")
    assert exit_code == 0

    target = workspace / "AuthService"
    assert target.is_dir()
    assert (target / ".git").is_file()

    # Verify registration in source via `git worktree list`
    listing = subprocess.run(
        ["git", "worktree", "list"],
        cwd=source, check=True, capture_output=True, text=True,
    )
    assert str(target) in listing.stdout

    # Re-run → idempotent skip
    second = add_repo_mod.cmd_add_repo("AuthService")
    assert second == 0
    # Worktree still exists, no duplicate registration
    listing2 = subprocess.run(
        ["git", "worktree", "list"],
        cwd=source, check=True, capture_output=True, text=True,
    )
    # Count occurrences — still exactly one matching line
    assert listing2.stdout.count(str(target)) == 1
