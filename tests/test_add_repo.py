"""Tests for `devkit add-repo`."""
from __future__ import annotations

from pathlib import Path

import pytest
import typer
from typer.testing import CliRunner

from aidevkit import add_repo as add_repo_mod
from aidevkit.cli import app
from aidevkit.util import (
    E_DEP_MISSING,
    E_NOT_IN_PER_ISSUE_WORKSPACE,
    E_REPO_NOT_FOUND,
    RunResult,
)


@pytest.fixture
def runner(monkeypatch: pytest.MonkeyPatch) -> CliRunner:
    monkeypatch.setenv("NO_COLOR", "1")
    return CliRunner()


# --- PerIssueContext detection ------------------------------------------------


def test_detect_context_direct_workspace(tmp_path: Path) -> None:
    home = tmp_path / "home"
    home.mkdir()
    workspace = home / "DevKit-issue-20"
    workspace.mkdir()
    ctx = add_repo_mod._detect_per_issue_context(workspace, home)
    assert ctx.home_repo_name == "DevKit"
    assert ctx.issue_number == 20
    assert ctx.branch == "issue-DevKit-20"


def test_detect_context_nested_subdir(tmp_path: Path) -> None:
    home = tmp_path / "home"
    home.mkdir()
    workspace = home / "DevKit-issue-20"
    nested = workspace / "DevKit" / "src"
    nested.mkdir(parents=True)
    ctx = add_repo_mod._detect_per_issue_context(nested, home)
    assert ctx.home_repo_name == "DevKit"
    assert ctx.workspace_dir == workspace.resolve()


def test_detect_context_outside_exits_24(tmp_path: Path) -> None:
    home = tmp_path / "home"
    home.mkdir()
    outside = tmp_path / "somewhere_else"
    outside.mkdir()
    with pytest.raises(typer.Exit) as excinfo:
        add_repo_mod._detect_per_issue_context(outside, home)
    assert excinfo.value.exit_code == E_NOT_IN_PER_ISSUE_WORKSPACE


def test_detect_context_archived_does_not_match(tmp_path: Path) -> None:
    home = tmp_path / "home"
    home.mkdir()
    archived = home / "_archived"
    archived.mkdir()
    old = archived / "DevKit-issue-1"
    old.mkdir()
    with pytest.raises(typer.Exit):
        add_repo_mod._detect_per_issue_context(old, home)


# --- Source-repo resolution ---------------------------------------------------


def test_resolve_source_repo_returns_path(tmp_path: Path) -> None:
    projects = tmp_path / "projects"
    (projects / "Repo").mkdir(parents=True)
    assert add_repo_mod._resolve_source_repo("Repo", projects) == projects / "Repo"


def test_resolve_source_repo_missing_exits_13(tmp_path: Path) -> None:
    projects = tmp_path / "projects"
    projects.mkdir()
    with pytest.raises(typer.Exit) as excinfo:
        add_repo_mod._resolve_source_repo("NoSuch", projects)
    assert excinfo.value.exit_code == E_REPO_NOT_FOUND


# --- Idempotent skip ----------------------------------------------------------


def test_target_points_into_detects_valid_worktree(tmp_path: Path) -> None:
    source = tmp_path / "source"
    (source / ".git" / "worktrees" / "Copy").mkdir(parents=True)
    target = tmp_path / "home" / "Repo-issue-1" / "Copy"
    target.mkdir(parents=True)
    (target / ".git").write_text(f"gitdir: {source}/.git/worktrees/Copy\n")
    assert add_repo_mod._target_points_into(source, target) is True


def test_target_points_into_rejects_unrelated_gitdir(tmp_path: Path) -> None:
    source = tmp_path / "source"
    source.mkdir()
    other = tmp_path / "other"
    other.mkdir()
    target = tmp_path / "home" / "Repo-issue-1" / "Copy"
    target.mkdir(parents=True)
    (target / ".git").write_text(f"gitdir: {other}/.git/worktrees/Copy\n")
    assert add_repo_mod._target_points_into(source, target) is False


# --- End-to-end via CLI -------------------------------------------------------


def _setup_env(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> tuple[Path, Path, Path]:
    home = tmp_path / "home"
    home.mkdir()
    projects = tmp_path / "projects"
    projects.mkdir()
    workspace = home / "DevKit-issue-20"
    workspace.mkdir()
    monkeypatch.setenv("APP_EMPIRE_WORKTREES_HOME", str(home))
    monkeypatch.setenv("APP_EMPIRE_PROJECTS", str(projects))
    monkeypatch.chdir(workspace)
    return home, projects, workspace


def test_add_repo_creates_worktree_when_branch_exists(
    runner: CliRunner,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    home, projects, workspace = _setup_env(monkeypatch, tmp_path)
    source = projects / "AuthService"
    source.mkdir()

    calls: list[list[str]] = []

    def shell(cmd: list[str], **_: object) -> RunResult:
        calls.append(list(cmd))
        if cmd[:2] == ["git", "show-ref"]:
            return RunResult(code=0, stdout="abc refs/heads/issue-DevKit-20\n", stderr="")
        if cmd[:3] == ["git", "worktree", "add"]:
            return RunResult(code=0, stdout="", stderr="")
        return RunResult(code=0, stdout="", stderr="")

    monkeypatch.setattr("aidevkit.util.run", shell)
    result = runner.invoke(app, ["add-repo", "AuthService"])
    assert result.exit_code == 0, result.output
    wt_cmd = [c for c in calls if c[:3] == ["git", "worktree", "add"]]
    assert len(wt_cmd) == 1
    # branch existed → no `-b` flag
    assert "-b" not in wt_cmd[0]


def test_add_repo_creates_branch_when_absent(
    runner: CliRunner,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    home, projects, workspace = _setup_env(monkeypatch, tmp_path)
    (projects / "AuthService").mkdir()

    calls: list[list[str]] = []

    def shell(cmd: list[str], **_: object) -> RunResult:
        calls.append(list(cmd))
        if cmd[:2] == ["git", "show-ref"]:
            return RunResult(code=1, stdout="", stderr="not found")
        if cmd[:3] == ["git", "worktree", "add"]:
            return RunResult(code=0, stdout="", stderr="")
        return RunResult(code=0, stdout="", stderr="")

    monkeypatch.setattr("aidevkit.util.run", shell)
    result = runner.invoke(app, ["add-repo", "AuthService"])
    assert result.exit_code == 0, result.output
    wt_cmd = [c for c in calls if c[:3] == ["git", "worktree", "add"]]
    assert len(wt_cmd) == 1
    assert "-b" in wt_cmd[0]
    assert "issue-DevKit-20" in wt_cmd[0]


def test_add_repo_idempotent_skip(
    runner: CliRunner,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    home, projects, workspace = _setup_env(monkeypatch, tmp_path)
    source = projects / "AuthService"
    (source / ".git" / "worktrees" / "AuthService").mkdir(parents=True)
    target = workspace / "AuthService"
    target.mkdir()
    (target / ".git").write_text(f"gitdir: {source}/.git/worktrees/AuthService\n")

    wt_add_calls: list[list[str]] = []

    def shell(cmd: list[str], **_: object) -> RunResult:
        if cmd[:3] == ["git", "worktree", "add"]:
            wt_add_calls.append(list(cmd))
        return RunResult(code=0, stdout="", stderr="")

    monkeypatch.setattr("aidevkit.util.run", shell)
    result = runner.invoke(app, ["add-repo", "AuthService"])
    assert result.exit_code == 0, result.output
    assert wt_add_calls == [], "idempotent skip must not invoke git worktree add"


def test_add_repo_missing_source_exits_13(
    runner: CliRunner,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    home, projects, workspace = _setup_env(monkeypatch, tmp_path)

    def shell(cmd: list[str], **_: object) -> RunResult:
        return RunResult(code=0, stdout="", stderr="")

    monkeypatch.setattr("aidevkit.util.run", shell)
    result = runner.invoke(app, ["add-repo", "NotThere"])
    assert result.exit_code == E_REPO_NOT_FOUND


def test_add_repo_outside_workspace_exits_24(
    runner: CliRunner,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    home = tmp_path / "home"
    home.mkdir()
    projects = tmp_path / "projects"
    projects.mkdir()
    (projects / "AuthService").mkdir()
    outside = tmp_path / "random"
    outside.mkdir()
    monkeypatch.setenv("APP_EMPIRE_WORKTREES_HOME", str(home))
    monkeypatch.setenv("APP_EMPIRE_PROJECTS", str(projects))
    monkeypatch.chdir(outside)

    def shell(cmd: list[str], **_: object) -> RunResult:
        return RunResult(code=0, stdout="", stderr="")

    monkeypatch.setattr("aidevkit.util.run", shell)
    result = runner.invoke(app, ["add-repo", "AuthService"])
    assert result.exit_code == E_NOT_IN_PER_ISSUE_WORKSPACE


def test_add_repo_missing_devkit_setup_exits_dep_missing(
    runner: CliRunner,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """DevKit#37: add-repo fails with E_DEP_MISSING when .devkit/ unreachable."""
    monkeypatch.delenv("APP_EMPIRE_WORKTREES_HOME", raising=False)
    monkeypatch.delenv("APP_EMPIRE_PROJECTS", raising=False)
    monkeypatch.delenv("PROJECTS_HOME", raising=False)

    def shell(cmd: list[str], **_: object) -> RunResult:
        return RunResult(code=0, stdout="", stderr="")

    monkeypatch.setattr("aidevkit.util.run", shell)
    result = runner.invoke(app, ["add-repo", "Any"])
    assert result.exit_code == E_DEP_MISSING
