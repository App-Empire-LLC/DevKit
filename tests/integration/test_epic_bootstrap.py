"""Integration tests for epic bootstrap — T052/T053/T054.

Uses real git binary for worktree/branch operations; mocks gh API calls.
"""
from __future__ import annotations

import json
import subprocess
from pathlib import Path

import pytest
import yaml

import aidevkit.bootstrap as _bootstrap_mod
import aidevkit.util as _util_mod
from aidevkit.bootstrap import cmd_bootstrap
from aidevkit.epic import EpicGraphInvalid, read_epic_md


# ---------------------------------------------------------------------------
# Helpers
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
    import shutil
    shutil.rmtree(seed)


def _branches_in_repo(repo_path: Path) -> set[str]:
    result = _git("branch", "--list", "--format=%(refname:short)", cwd=repo_path)
    return {b.strip() for b in result.stdout.splitlines() if b.strip()}


def _setup_projects_env(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    workspaces_home: Path,
    repos: list[tuple[str, str, Path]],  # (name, owner_repo, source_clone_path)
) -> None:
    """Configure PROJECTS_HOME with config.yaml and PROJECTS.md."""
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
    # Source clones at projects_home/<name>/
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


def _gh_mock(
    top_issue_payload: dict,
    sub_issues: list[dict],
    sub_sub_issues: dict[int, list[dict]] | None = None,
):
    """Return a run() mock that passes git through but intercepts gh calls."""
    sub_sub_issues = sub_sub_issues or {}
    real_run = subprocess.run

    def _run(cmd, *, check=False, cwd=None):
        from aidevkit.util import RunResult
        if cmd[0] == "git":
            proc = real_run(cmd, cwd=cwd, capture_output=True, text=True, check=False)
            return RunResult(proc.returncode, proc.stdout, proc.stderr)

        if cmd[0] == "gh":
            # gh issue view → top issue payload
            if cmd[:3] == ["gh", "issue", "view"]:
                return RunResult(code=0, stdout=json.dumps(top_issue_payload), stderr="")
            # gh api sub_issues
            if cmd[0] == "gh" and "sub_issues" in " ".join(cmd):
                # Extract issue num from URL pattern
                for part in cmd:
                    if "/issues/" in part and "/sub_issues" in part:
                        num_str = part.split("/issues/")[1].split("/")[0]
                        num = int(num_str)
                        result = sub_sub_issues.get(num, sub_issues if num == top_issue_payload.get("_top_num", 42) else [])
                        return RunResult(code=0, stdout=json.dumps(result), stderr="")
                return RunResult(code=0, stdout="[]", stderr="")
            # gh issue comment → ack
            if cmd[:3] == ["gh", "issue", "comment"]:
                return RunResult(code=0, stdout="ok", stderr="")
            # everything else → success
            return RunResult(code=0, stdout="", stderr="")

        return RunResult(code=0, stdout="", stderr="")

    return _run


# ---------------------------------------------------------------------------
# T052/T053: Bootstrap 2-level nested epic with mixed coverage
# ---------------------------------------------------------------------------

@pytest.fixture
def epic_origins(tmp_path: Path):
    """Two bare git origins: DevKit and appire_docs."""
    origins_dir = tmp_path / "origins"
    origins_dir.mkdir()
    dk_origin = origins_dir / "DevKit.git"
    ad_origin = origins_dir / "appire_docs.git"
    _init_bare_origin(dk_origin)
    _init_bare_origin(ad_origin)

    # Source clones (what projects_home/<name>/ points to)
    dk_clone = tmp_path / "DevKit"
    ad_clone = tmp_path / "appire_docs"
    _git("clone", str(dk_origin), str(dk_clone), cwd=tmp_path)
    _git("clone", str(ad_origin), str(ad_clone), cwd=tmp_path)
    _git("config", "user.email", "test@example.com", cwd=dk_clone)
    _git("config", "user.name", "Test", cwd=dk_clone)
    _git("config", "user.email", "test@example.com", cwd=ad_clone)
    _git("config", "user.name", "Test", cwd=ad_clone)

    return {
        "dk_origin": dk_origin,
        "ad_origin": ad_origin,
        "dk_clone": dk_clone,
        "ad_clone": ad_clone,
    }


def _build_epic_payloads():
    """Build gh API payloads for a 2-level epic:
      top#42 (DevKit) → issue#7 (DevKit+appire_docs), issue#8 (appire_docs)
    """
    top_payload = {
        "_top_num": 42,
        "title": "Top Epic",
        "url": "https://github.com/App-Empire-LLC/DevKit/issues/42",
        "body": (
            "## Affected Repos\n"
            "- App-Empire-LLC/DevKit\n"
            "- App-Empire-LLC/appire_docs\n"
        ),
    }
    child7 = {
        "number": 7,
        "html_url": "https://github.com/App-Empire-LLC/DevKit/issues/7",
        "title": "Sub-issue 7",
        "body": (
            "## Affected Repos\n"
            "- App-Empire-LLC/DevKit\n"
            "- App-Empire-LLC/appire_docs\n"
        ),
        "state": "open",
    }
    child8 = {
        "number": 8,
        "html_url": "https://github.com/App-Empire-LLC/appire_docs/issues/8",
        "title": "Sub-issue 8",
        "body": (
            "## Affected Repos\n"
            "- App-Empire-LLC/appire_docs\n"
        ),
        "state": "open",
    }
    return top_payload, [child7, child8]


def test_epic_bootstrap_creates_workspace_with_all_branches(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    epic_origins: dict,
) -> None:
    """T053: bootstrap 2-level epic → workspace + worktrees + stacked branches."""
    workspaces_home = tmp_path / "workspaces"
    workspaces_home.mkdir()

    _setup_projects_env(
        tmp_path, monkeypatch, workspaces_home,
        repos=[
            ("DevKit", "App-Empire-LLC/DevKit", epic_origins["dk_clone"]),
            ("appire_docs", "App-Empire-LLC/appire_docs", epic_origins["ad_clone"]),
        ],
    )

    top_payload, sub_issues = _build_epic_payloads()
    # sub_issues endpoint for top (#42) → [child7, child8]
    # sub_issues endpoint for child7 (#7) → [] (leaf)
    # sub_issues endpoint for child8 (#8) → [] (leaf)
    monkeypatch.setattr(
        "aidevkit.util.run",
        _gh_mock(top_payload, sub_issues, sub_sub_issues={42: sub_issues, 7: [], 8: []}),
    )
    monkeypatch.setattr("aidevkit.bootstrap.shutil.which", lambda x: f"/usr/bin/{x}")

    result = cmd_bootstrap(
        issue_arg="App-Empire-LLC/DevKit#42",
        no_ack=True,
    )
    assert result == 0

    workspace = workspaces_home / "DevKit-issue-42"
    assert workspace.exists(), "workspace dir must be created"

    # Worktrees exist for both repos
    assert (workspace / "DevKit").exists()
    assert (workspace / "appire_docs").exists()

    # EPIC.md is valid and parseable
    graph = read_epic_md(workspace)
    assert graph.top_epic == "App-Empire-LLC/DevKit#42"
    assert "App-Empire-LLC/DevKit#7" in graph.nodes
    assert "App-Empire-LLC/appire_docs#8" in graph.nodes

    # WORKSPACE.md has is_epic: true
    ws_text = (workspace / "WORKSPACE.md").read_text()
    fm_text = ws_text.split("---\n")[1]
    fm = yaml.safe_load(fm_text)
    assert fm.get("is_epic") is True
    assert fm.get("epic_top_issue") == "App-Empire-LLC/DevKit#42"

    # Stacked branches in DevKit: top + issue7
    dk_branches = _branches_in_repo(epic_origins["dk_clone"])
    assert "issue-DevKit-42" in dk_branches
    assert "issue-DevKit-7" in dk_branches

    # Stacked branches in appire_docs: top + issue7 + issue8
    ad_branches = _branches_in_repo(epic_origins["ad_clone"])
    assert "issue-DevKit-42" in ad_branches
    assert "issue-DevKit-7" in ad_branches
    assert "issue-appire_docs-8" in ad_branches


def test_no_epic_flag_produces_non_epic_workspace(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    epic_origins: dict,
) -> None:
    """T054: --no-epic → no EPIC.md, no is_epic in WORKSPACE.md (SC-007)."""
    workspaces_home = tmp_path / "workspaces"
    workspaces_home.mkdir()

    _setup_projects_env(
        tmp_path, monkeypatch, workspaces_home,
        repos=[
            ("DevKit", "App-Empire-LLC/DevKit", epic_origins["dk_clone"]),
            ("appire_docs", "App-Empire-LLC/appire_docs", epic_origins["ad_clone"]),
        ],
    )

    top_payload, sub_issues = _build_epic_payloads()
    monkeypatch.setattr(
        "aidevkit.util.run",
        _gh_mock(top_payload, sub_issues, sub_sub_issues={42: sub_issues, 7: [], 8: []}),
    )
    monkeypatch.setattr("aidevkit.bootstrap.shutil.which", lambda x: f"/usr/bin/{x}")

    result = cmd_bootstrap(
        issue_arg="App-Empire-LLC/DevKit#42",
        no_ack=True,
        no_epic=True,
    )
    assert result == 0

    workspace = workspaces_home / "DevKit-issue-42"
    assert workspace.exists()

    # No EPIC.md
    assert not (workspace / "EPIC.md").exists()

    # WORKSPACE.md must NOT have is_epic
    ws_text = (workspace / "WORKSPACE.md").read_text()
    fm_text = ws_text.split("---\n")[1]
    fm = yaml.safe_load(fm_text)
    assert "is_epic" not in fm or fm.get("is_epic") is False

    # Only the top-level branch (no stacked children)
    dk_branches = _branches_in_repo(epic_origins["dk_clone"])
    assert "issue-DevKit-42" in dk_branches
    # Child branches should NOT exist (non-epic path doesn't create them)
    assert "issue-DevKit-7" not in dk_branches
