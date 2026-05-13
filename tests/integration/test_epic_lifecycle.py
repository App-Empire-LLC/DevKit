"""Integration tests for epic lifecycle — T055/T056/T057/T058.

Builds a bootstrapped epic workspace with real git, then exercises
sub-checkout and archive end-to-end.
"""
from __future__ import annotations

import json
import subprocess
from pathlib import Path

import pytest
import yaml

from aidevkit.bootstrap import cmd_bootstrap
from aidevkit.epic import EpicGraph, EpicNode, read_epic_md, write_epic_md
from aidevkit.sub_checkout import cmd_sub_checkout
from aidevkit.util import RunResult


# ---------------------------------------------------------------------------
# Helpers (shared with test_epic_bootstrap)
# ---------------------------------------------------------------------------

def _git(*args: str, cwd: Path) -> subprocess.CompletedProcess[str]:
    proc = subprocess.run(
        ["git", *args], cwd=cwd, capture_output=True, text=True, check=False,
    )
    if proc.returncode != 0:
        raise RuntimeError(
            f"git {' '.join(args)} failed in {cwd}: "
            f"{proc.stderr.strip() or proc.stdout.strip()}"
        )
    return proc


def _init_bare_origin(origin_path: Path) -> None:
    import shutil
    origin_path.mkdir(parents=True)
    _git("init", "--bare", "--initial-branch=main", cwd=origin_path)
    seed = origin_path.parent / f"_seed_{origin_path.name}"
    seed.mkdir()
    _git("init", "--initial-branch=main", cwd=seed)
    _git("config", "user.email", "test@example.com", cwd=seed)
    _git("config", "user.name", "Test", cwd=seed)
    (seed / "README.md").write_text("seed\n")
    _git("add", ".", cwd=seed)
    _git("commit", "-m", "initial", cwd=seed)
    _git("remote", "add", "origin", str(origin_path), cwd=seed)
    _git("push", "origin", "main", cwd=seed)
    shutil.rmtree(seed)


def _branches_in_repo(repo_path: Path) -> set[str]:
    result = _git("branch", "--list", "--format=%(refname:short)", cwd=repo_path)
    return {b.strip() for b in result.stdout.splitlines() if b.strip()}


def _current_branch(repo_path: Path) -> str:
    result = _git("rev-parse", "--abbrev-ref", "HEAD", cwd=repo_path)
    return result.stdout.strip()


def _setup_projects_env(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    workspaces_home: Path,
    repos: list[tuple[str, str, Path]],
) -> None:
    projects_home = tmp_path / "projects_home"
    projects_home.mkdir(exist_ok=True)
    devkit_dir = projects_home / ".devkit"
    devkit_dir.mkdir(exist_ok=True)
    (devkit_dir / "config.yaml").write_text(
        f"version: 1\norg: App-Empire-LLC\nworkspaces_home: {workspaces_home}\n"
    )
    rows = "\n".join(
        f"| {name} | git@github.com:{or_}.git | main | x |"
        for name, or_, _ in repos
    )
    (devkit_dir / "PROJECTS.md").write_text(
        "# Projects\n\n"
        "| name | git_url | default_branch | description |\n"
        "|------|---------|----------------|-------------|\n"
        + rows + "\n"
    )
    for name, _, clone_path in repos:
        link = projects_home / name
        if not link.exists():
            link.symlink_to(clone_path)
    fake_home = tmp_path / "home"
    fake_home.mkdir(exist_ok=True)
    monkeypatch.setenv("PROJECTS_HOME", str(projects_home))
    monkeypatch.setattr("pathlib.Path.home", classmethod(lambda cls: fake_home))
    monkeypatch.setattr(
        "aidevkit.config._GLOBAL_CONFIG_PATH",
        fake_home / ".devkit" / "config.yaml",
    )
    monkeypatch.delenv("APP_EMPIRE_WORKTREES_HOME", raising=False)
    monkeypatch.delenv("APP_EMPIRE_PROJECTS", raising=False)
    from aidevkit import cli as _cli
    if hasattr(_cli._resolve_org_lazy, "_cached"):
        delattr(_cli._resolve_org_lazy, "_cached")


def _make_real_run_with_gh_mock(top_payload: dict, sub_issues_map: dict[int, list]):
    """Pass git calls to real subprocess; intercept gh calls."""
    real_run = subprocess.run

    def _run(cmd, *, check=False, cwd=None):
        if cmd[0] == "git":
            proc = real_run(cmd, cwd=cwd, capture_output=True, text=True, check=False)
            return RunResult(proc.returncode, proc.stdout, proc.stderr)
        if cmd[0] == "gh":
            if cmd[:3] == ["gh", "issue", "view"]:
                return RunResult(0, json.dumps(top_payload), "")
            if "sub_issues" in " ".join(cmd):
                for part in cmd:
                    if "/issues/" in part and "/sub_issues" in part:
                        try:
                            num = int(part.split("/issues/")[1].split("/")[0])
                            return RunResult(0, json.dumps(sub_issues_map.get(num, [])), "")
                        except (ValueError, IndexError):
                            pass
                return RunResult(0, "[]", "")
            if cmd[:3] == ["gh", "issue", "comment"]:
                return RunResult(0, "ok", "")
            return RunResult(0, "", "")
        return RunResult(0, "", "")

    return _run


# ---------------------------------------------------------------------------
# T055: Shared bootstrap fixture for lifecycle tests
# ---------------------------------------------------------------------------

@pytest.fixture
def bootstrapped_epic(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    """Bootstrap a 2-node epic workspace (top#42 → child#7) and return context."""
    workspaces_home = tmp_path / "workspaces"
    workspaces_home.mkdir()

    # Single-repo epic for simplicity (both nodes touch only DevKit)
    dk_origin = tmp_path / "origins" / "DevKit.git"
    _init_bare_origin(dk_origin)
    dk_clone = tmp_path / "DevKit"
    _git("clone", str(dk_origin), str(dk_clone), cwd=tmp_path)
    _git("config", "user.email", "test@example.com", cwd=dk_clone)
    _git("config", "user.name", "Test", cwd=dk_clone)

    _setup_projects_env(
        tmp_path, monkeypatch, workspaces_home,
        repos=[("DevKit", "App-Empire-LLC/DevKit", dk_clone)],
    )

    top_payload = {
        "title": "Top Epic",
        "url": "https://github.com/App-Empire-LLC/DevKit/issues/42",
        "body": "## Affected Repos\n- App-Empire-LLC/DevKit\n",
    }
    child7 = {
        "number": 7,
        "html_url": "https://github.com/App-Empire-LLC/DevKit/issues/7",
        "title": "Sub-issue 7",
        "body": "## Affected Repos\n- App-Empire-LLC/DevKit\n",
        "state": "open",
    }

    monkeypatch.setattr(
        "aidevkit.util.run",
        _make_real_run_with_gh_mock(top_payload, {42: [child7], 7: []}),
    )
    monkeypatch.setattr("aidevkit.bootstrap.shutil.which", lambda x: f"/usr/bin/{x}")

    result = cmd_bootstrap(issue_arg="App-Empire-LLC/DevKit#42", no_ack=True)
    assert result == 0

    workspace = workspaces_home / "DevKit-issue-42"
    return {
        "workspace": workspace,
        "dk_clone": dk_clone,
        "workspaces_home": workspaces_home,
        "monkeypatch": monkeypatch,
    }


# ---------------------------------------------------------------------------
# T056: sub-checkout happy path
# ---------------------------------------------------------------------------

def test_sub_checkout_switches_worktree_branch(
    bootstrapped_epic: dict,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """T056: sub-checkout switches DevKit worktree to #7's branch; EPIC.md updated."""
    workspace = bootstrapped_epic["workspace"]
    dk_clone = bootstrapped_epic["dk_clone"]

    # After bootstrap, worktree should be on the top epic branch
    wt_path = workspace / "DevKit"
    initial_branch = _current_branch(wt_path)
    assert initial_branch == "issue-DevKit-42"

    # Patch _infer_workspace to return our workspace
    import aidevkit.sub_checkout as sc_mod
    monkeypatch.setattr(sc_mod, "_infer_workspace", lambda num=None: workspace)

    # All git calls are real; no gh calls needed for sub-checkout
    result = cmd_sub_checkout("7")
    assert result == 0

    # Worktree now on child branch
    switched_branch = _current_branch(wt_path)
    assert switched_branch == "issue-DevKit-7"

    # EPIC.md updated
    graph = read_epic_md(workspace)
    assert graph.current_issue == "App-Empire-LLC/DevKit#7"
    assert graph.nodes["App-Empire-LLC/DevKit#7"].status == "in_progress"


# ---------------------------------------------------------------------------
# T057: sub-merge advances current_issue (stub gh pr list as merged)
# ---------------------------------------------------------------------------

def test_sub_merge_advances_current_issue(
    bootstrapped_epic: dict,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """T057: sub-merge marks node merged, advances current_issue."""
    workspace = bootstrapped_epic["workspace"]

    import aidevkit.sub_merge as sm_mod
    monkeypatch.setattr(sm_mod, "_infer_workspace", lambda: workspace)
    monkeypatch.setattr(sm_mod, "_cascade_up", lambda ws, g, pr: None)

    # Mock gh pr list → MERGED; all git calls are real
    real_run = subprocess.run
    def _run(cmd, *, check=False, cwd=None):
        if cmd[0] == "git":
            proc = real_run(cmd, cwd=cwd, capture_output=True, text=True, check=False)
            return RunResult(proc.returncode, proc.stdout, proc.stderr)
        if cmd[:3] == ["gh", "pr", "list"]:
            return RunResult(0, json.dumps([{"number": 1, "state": "MERGED", "url": "https://gh/1"}]), "")
        return RunResult(0, "", "")

    monkeypatch.setattr("aidevkit.util.run", _run)

    result = sm_mod.cmd_sub_merge("7")
    assert result == 0

    graph = read_epic_md(workspace)
    assert graph.nodes["App-Empire-LLC/DevKit#7"].status == "merged"
    # execution_order exhausted → current_issue = top_epic
    assert graph.current_issue == "App-Empire-LLC/DevKit#42"


# ---------------------------------------------------------------------------
# T058: archive removes workspace after all nodes merged
# ---------------------------------------------------------------------------

def test_archive_sweep_removes_workspace(
    bootstrapped_epic: dict,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """T058: archive removes workspace when all nodes merged."""
    workspace = bootstrapped_epic["workspace"]
    dk_clone = bootstrapped_epic["dk_clone"]
    workspaces_home = bootstrapped_epic["workspaces_home"]

    # Mark all nodes merged in EPIC.md
    graph = read_epic_md(workspace)
    for node in graph.nodes.values():
        node.status = "merged"
    write_epic_md(workspace, graph)

    # Mock gh calls; git is real
    real_run = subprocess.run
    def _run(cmd, *, check=False, cwd=None):
        if cmd[0] == "git":
            proc = real_run(cmd, cwd=cwd, capture_output=True, text=True, check=False)
            return RunResult(proc.returncode, proc.stdout, proc.stderr)
        if cmd[:3] == ["gh", "pr", "list"]:
            return RunResult(0, json.dumps([{"number": 1, "state": "MERGED", "url": "https://gh/1"}]), "")
        if cmd[:3] == ["gh", "issue", "view"]:
            return RunResult(0, json.dumps({"state": "OPEN"}), "")
        if cmd[:3] == ["gh", "issue", "close"]:
            return RunResult(0, "", "")
        if cmd[:3] == ["gh", "issue", "comment"]:
            return RunResult(0, "", "")
        return RunResult(0, "", "")

    monkeypatch.setattr("aidevkit.util.run", _run)

    from aidevkit.archive import cmd_archive
    result = cmd_archive(
        issue_arg="App-Empire-LLC/DevKit#42",
        force=False,
        dry_run=False,
    )
    assert result == 0

    # Workspace moved to _archived/
    archived = workspaces_home / "_archived" / "DevKit-issue-42"
    assert archived.exists()
    assert not workspace.exists()
