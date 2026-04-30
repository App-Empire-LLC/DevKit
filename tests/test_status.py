"""Tests for `devkit status`."""
from __future__ import annotations

import json
from importlib.resources import as_file, files
from pathlib import Path

import jsonschema
import pytest
from typer.testing import CliRunner

from aidevkit import status as status_mod
from aidevkit.cli import app
from aidevkit.util import RunResult


@pytest.fixture
def runner(monkeypatch: pytest.MonkeyPatch) -> CliRunner:
    monkeypatch.setenv("NO_COLOR", "1")
    return CliRunner()


def _load_schema() -> dict:
    schema_res = files("aidevkit.schemas") / "status.schema.json"
    with as_file(schema_res) as path:
        return json.loads(Path(path).read_text())


def _make_workspace(
    home: Path,
    repo: str,
    num: int,
    *,
    upstream_root: Path | None = None,
    extra_repo: tuple[str, Path] | None = None,
) -> Path:
    """Create a minimal per-issue workspace tree.

    If `upstream_root` is provided, create a `.git` file in the subdir pointing
    at `<upstream>/.git/worktrees/<subdir>/`. Otherwise the subdir exists but
    has no `.git`, simulating a missing worktree.
    """
    workspace = home / f"{repo}-issue-{num}"
    workspace.mkdir()
    subdir = workspace / repo
    subdir.mkdir()
    if upstream_root is not None:
        gitdir = upstream_root / ".git" / "worktrees" / repo
        gitdir.mkdir(parents=True, exist_ok=True)
        (subdir / ".git").write_text(f"gitdir: {gitdir}\n")
    if extra_repo is not None:
        name, extra_upstream = extra_repo
        extra_sub = workspace / name
        extra_sub.mkdir()
        extra_gitdir = extra_upstream / ".git" / "worktrees" / name
        extra_gitdir.mkdir(parents=True, exist_ok=True)
        (extra_sub / ".git").write_text(f"gitdir: {extra_gitdir}\n")
    return workspace


def _make_upstream(tmp_path: Path, repo: str) -> Path:
    root = tmp_path / "projects" / repo
    (root / ".git").mkdir(parents=True)
    return root


# --- Enumeration --------------------------------------------------------------


def test_enumerate_skips_archived_and_non_matching(tmp_path: Path) -> None:
    home = tmp_path / "home"
    home.mkdir()
    (home / "_archived").mkdir()
    (home / "_archived" / "Old-issue-1").mkdir()
    (home / "DevKit-issue-20").mkdir()
    (home / "AuthService-issue-2").mkdir()
    (home / "random-file").write_text("x")
    (home / "some-other-dir").mkdir()

    found = status_mod._enumerate_workspaces(home.resolve())
    names = {p.name for p in found}
    assert names == {"DevKit-issue-20", "AuthService-issue-2"}


def test_parse_dir_name_matches_pattern() -> None:
    assert status_mod._parse_dir_name("DevKit-issue-20") == ("DevKit", 20)
    assert status_mod._parse_dir_name("App.Empire_LLC-issue-5") == ("App.Empire_LLC", 5)
    assert status_mod._parse_dir_name("_archived") is None
    assert status_mod._parse_dir_name("not-an-issue") is None


# --- Branch state collection --------------------------------------------------


def test_collect_branch_state_reports_clean_tree(
    tmp_path: Path, subprocess_capture
) -> None:
    worktree = tmp_path / "wt"
    worktree.mkdir()
    (worktree / ".git").write_text("gitdir: x")
    # status --porcelain, rev-parse --abbrev-ref HEAD, rev-list --left-right --count
    subprocess_capture.queue(RunResult(code=0, stdout="", stderr=""))
    subprocess_capture.queue(RunResult(code=0, stdout="issue-X-1\n", stderr=""))
    subprocess_capture.queue(RunResult(code=0, stdout="0\t3\n", stderr=""))
    bs = status_mod._collect_branch_state(worktree, "issue-X-1")
    assert bs is not None
    assert bs.ahead == 3 and bs.behind == 0
    assert bs.dirty is False and bs.missing is False


def test_collect_branch_state_reports_dirty(
    tmp_path: Path, subprocess_capture
) -> None:
    worktree = tmp_path / "wt"
    worktree.mkdir()
    (worktree / ".git").write_text("gitdir: x")
    subprocess_capture.queue(RunResult(code=0, stdout=" M file\n", stderr=""))
    subprocess_capture.queue(RunResult(code=0, stdout="issue-X-1\n", stderr=""))
    subprocess_capture.queue(RunResult(code=0, stdout="2\t1\n", stderr=""))
    bs = status_mod._collect_branch_state(worktree, "issue-X-1")
    assert bs is not None
    assert bs.dirty is True
    assert bs.behind == 2 and bs.ahead == 1


def test_collect_branch_state_missing_upstream(
    tmp_path: Path, subprocess_capture
) -> None:
    worktree = tmp_path / "wt"
    worktree.mkdir()
    (worktree / ".git").write_text("gitdir: x")
    subprocess_capture.queue(RunResult(code=0, stdout="", stderr=""))
    subprocess_capture.queue(RunResult(code=0, stdout="issue-X-1\n", stderr=""))
    subprocess_capture.queue(RunResult(code=1, stdout="", stderr="unknown ref"))
    bs = status_mod._collect_branch_state(worktree, "issue-X-1")
    assert bs is not None
    assert bs.missing is True


def test_collect_branch_state_returns_none_when_no_git(tmp_path: Path) -> None:
    worktree = tmp_path / "wt"
    worktree.mkdir()
    # no .git file — looks like external deletion
    bs = status_mod._collect_branch_state(worktree, "issue-X-1")
    assert bs is None


# --- Archivable derivation ----------------------------------------------------


def test_derive_archivable_requires_closed_issue() -> None:
    from aidevkit._prs import PR
    ws = status_mod.Workspace(
        dir_name="X-issue-1",
        issue=status_mod.Issue(
            owner_repo="o/X", number=1, title="", state="open"
        ),
        branch="issue-X-1",
        archivable=False,
        repos=[
            status_mod.RepoStatus(
                name="X",
                worktree_present=True,
                branch_state=status_mod.BranchState(0, 0, False, False),
                prs=[PR(number=1, state="merged", url="https://x")],
            )
        ],
    )
    assert status_mod._derive_archivable(ws) is False


def test_derive_archivable_requires_merged_pr_per_repo() -> None:
    from aidevkit._prs import PR
    ws = status_mod.Workspace(
        dir_name="X-issue-1",
        issue=status_mod.Issue(
            owner_repo="o/X", number=1, title="", state="closed"
        ),
        branch="issue-X-1",
        archivable=False,
        repos=[
            status_mod.RepoStatus(
                name="X",
                worktree_present=True,
                branch_state=status_mod.BranchState(0, 0, False, False),
                prs=[PR(number=1, state="merged", url="https://x")],
            ),
            status_mod.RepoStatus(
                name="Y",
                worktree_present=True,
                branch_state=status_mod.BranchState(0, 0, False, False),
                prs=[PR(number=2, state="open", url="https://y")],
            ),
        ],
    )
    assert status_mod._derive_archivable(ws) is False


def test_derive_archivable_true_when_closed_and_all_merged() -> None:
    from aidevkit._prs import PR
    ws = status_mod.Workspace(
        dir_name="X-issue-1",
        issue=status_mod.Issue(
            owner_repo="o/X", number=1, title="", state="closed"
        ),
        branch="issue-X-1",
        archivable=False,
        repos=[
            status_mod.RepoStatus(
                name="X",
                worktree_present=True,
                branch_state=status_mod.BranchState(0, 0, False, False),
                prs=[PR(number=1, state="merged", url="https://x")],
            )
        ],
    )
    assert status_mod._derive_archivable(ws) is True


def test_derive_archivable_false_without_repos() -> None:
    ws = status_mod.Workspace(
        dir_name="X-issue-1",
        issue=status_mod.Issue(
            owner_repo="o/X", number=1, title="", state="closed"
        ),
        branch="issue-X-1",
        archivable=False,
        repos=[],
    )
    assert status_mod._derive_archivable(ws) is False


# --- End-to-end via CLI -------------------------------------------------------


def _status_shell_factory(
    *,
    issue_state: str = "OPEN",
    issue_title: str = "Test issue",
    pr_state: str = "MERGED",
    git_ahead: int = 0,
    git_behind: int = 0,
    git_dirty: bool = False,
    gh_fails: bool = False,
):
    """Build a dispatching shell fake.

    Covers: `git remote get-url origin`, `git status --porcelain`,
    `git rev-parse --abbrev-ref HEAD`, `git rev-list --left-right --count`,
    `gh issue view`, `gh pr list`.
    """
    def shell(cmd: list[str], **_: object) -> RunResult:
        if cmd[:3] == ["git", "remote", "get-url"]:
            return RunResult(
                code=0,
                stdout="https://github.com/Owner/Repo.git\n",
                stderr="",
            )
        if cmd[:2] == ["git", "status"]:
            return RunResult(
                code=0, stdout=" M file\n" if git_dirty else "", stderr=""
            )
        if cmd[:2] == ["git", "rev-parse"]:
            return RunResult(code=0, stdout="issue-Repo-1\n", stderr="")
        if cmd[:2] == ["git", "rev-list"]:
            return RunResult(
                code=0, stdout=f"{git_behind}\t{git_ahead}\n", stderr=""
            )
        if cmd[:3] == ["gh", "issue", "view"]:
            if gh_fails:
                return RunResult(code=1, stdout="", stderr="network")
            return RunResult(
                code=0,
                stdout=json.dumps({"state": issue_state, "title": issue_title}),
                stderr="",
            )
        if cmd[:3] == ["gh", "pr", "list"]:
            if gh_fails:
                return RunResult(code=1, stdout="", stderr="network")
            return RunResult(
                code=0,
                stdout=json.dumps(
                    [{"number": 5, "state": pr_state, "url": "https://x/5"}]
                ),
                stderr="",
            )
        return RunResult(code=0, stdout="", stderr="")
    return shell


def test_status_multi_workspace_json_validates_against_schema(
    runner: CliRunner,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    home = tmp_path / "home"
    home.mkdir()
    upstream_a = _make_upstream(tmp_path, "Repo")
    upstream_b = _make_upstream(tmp_path, "Other")
    _make_workspace(home, "Repo", 1, upstream_root=upstream_a)
    ws2 = home / "Other-issue-2"
    ws2.mkdir()
    sub2 = ws2 / "Other"
    sub2.mkdir()
    gitdir2 = upstream_b / ".git" / "worktrees" / "Other"
    gitdir2.mkdir(parents=True)
    (sub2 / ".git").write_text(f"gitdir: {gitdir2}\n")

    monkeypatch.setenv("APP_EMPIRE_WORKTREES_HOME", str(home))
    monkeypatch.setattr(
        "aidevkit.util.run", _status_shell_factory(issue_state="CLOSED")
    )

    result = runner.invoke(app, ["status", "--json"])
    assert result.exit_code == 0, result.output
    payload = json.loads(result.output)
    jsonschema.validate(payload, _load_schema())
    assert payload["version"] == 1
    names = {w["dir_name"] for w in payload["workspaces"]}
    assert names == {"Repo-issue-1", "Other-issue-2"}


def test_status_missing_worktree_reported_without_crash(
    runner: CliRunner,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    home = tmp_path / "home"
    home.mkdir()
    # Workspace exists but no `.git` inside the repo subdir — simulates external deletion
    workspace = home / "Repo-issue-1"
    workspace.mkdir()
    (workspace / "Repo").mkdir()  # no .git file

    monkeypatch.setenv("APP_EMPIRE_WORKTREES_HOME", str(home))
    monkeypatch.setattr(
        "aidevkit.util.run", _status_shell_factory(issue_state="OPEN")
    )

    result = runner.invoke(app, ["status", "--json"])
    assert result.exit_code == 0, result.output
    payload = json.loads(result.output)
    # Workspace appears even though the subdir has no .git — and has zero repos
    # discovered (not a crash).
    workspaces = {w["dir_name"]: w for w in payload["workspaces"]}
    assert "Repo-issue-1" in workspaces
    assert workspaces["Repo-issue-1"]["repos"] == []


def test_status_archived_excluded(
    runner: CliRunner,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    home = tmp_path / "home"
    home.mkdir()
    upstream = _make_upstream(tmp_path, "Repo")
    _make_workspace(home, "Repo", 1, upstream_root=upstream)
    archived = home / "_archived"
    archived.mkdir()
    (archived / "Repo-issue-99").mkdir()

    monkeypatch.setenv("APP_EMPIRE_WORKTREES_HOME", str(home))
    monkeypatch.setattr("aidevkit.util.run", _status_shell_factory())

    result = runner.invoke(app, ["status", "--json"])
    assert result.exit_code == 0, result.output
    payload = json.loads(result.output)
    names = {w["dir_name"] for w in payload["workspaces"]}
    assert names == {"Repo-issue-1"}


def test_status_gh_unreachable_sets_unknown(
    runner: CliRunner,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    home = tmp_path / "home"
    home.mkdir()
    upstream = _make_upstream(tmp_path, "Repo")
    _make_workspace(home, "Repo", 1, upstream_root=upstream)

    monkeypatch.setenv("APP_EMPIRE_WORKTREES_HOME", str(home))
    monkeypatch.setattr("aidevkit.util.run", _status_shell_factory(gh_fails=True))

    result = runner.invoke(app, ["status", "--json"])
    assert result.exit_code == 0, result.output
    payload = json.loads(result.output)
    ws = payload["workspaces"][0]
    assert ws["issue"]["state"] == "unknown"
    assert ws["archivable"] is False


def test_status_text_output_shows_archivable_tag(
    runner: CliRunner,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    home = tmp_path / "home"
    home.mkdir()
    upstream = _make_upstream(tmp_path, "Repo")
    _make_workspace(home, "Repo", 1, upstream_root=upstream)

    monkeypatch.setenv("APP_EMPIRE_WORKTREES_HOME", str(home))
    monkeypatch.setattr(
        "aidevkit.util.run",
        _status_shell_factory(issue_state="CLOSED", pr_state="MERGED"),
    )

    result = runner.invoke(app, ["status"])
    assert result.exit_code == 0, result.output
    assert "Repo-issue-1" in result.output
    assert "archivable" in result.output


def test_status_no_workspaces_is_not_an_error(
    runner: CliRunner,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    home = tmp_path / "home"
    home.mkdir()
    monkeypatch.setenv("APP_EMPIRE_WORKTREES_HOME", str(home))
    monkeypatch.setattr("aidevkit.util.run", _status_shell_factory())

    result = runner.invoke(app, ["status", "--json"])
    assert result.exit_code == 0, result.output
    payload = json.loads(result.output)
    assert payload == {"version": 1, "workspaces": []}


def test_status_missing_devkit_setup_exits_dep_missing(
    runner: CliRunner,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """DevKit#37: status fails with E_DEP_MISSING (12) when .devkit/ is
    unreachable. (Was E_WORKSPACE_MISSING/16 under the legacy
    $APP_EMPIRE_WORKTREES_HOME check.)"""
    monkeypatch.delenv("APP_EMPIRE_WORKTREES_HOME", raising=False)
    monkeypatch.delenv("PROJECTS_HOME", raising=False)
    monkeypatch.setattr("aidevkit.util.run", _status_shell_factory())
    result = runner.invoke(app, ["status"])
    assert result.exit_code == 12  # E_DEP_MISSING
