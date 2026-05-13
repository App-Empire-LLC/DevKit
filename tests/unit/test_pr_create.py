"""Unit tests for pr_create — T037/T038."""
from __future__ import annotations

import json
from pathlib import Path

import pytest
import typer

import aidevkit.pr_create as pc_mod
from aidevkit.epic import EpicGraph, EpicNode, read_epic_md, write_epic_md
from aidevkit.util import RunResult


# ---------------------------------------------------------------------------
# Helpers (shared with test_sub_checkout conventions)
# ---------------------------------------------------------------------------

def _setup_env(tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
               org_repos: list[tuple[str, str]]) -> None:
    rows = "\n".join(
        f"| {name} | git@github.com:{or_}.git | main | x |"
        for name, or_ in org_repos
    )
    projects = tmp_path / "projects"
    projects.mkdir(exist_ok=True)
    devkit_dir = projects / ".devkit"
    devkit_dir.mkdir(exist_ok=True)
    workspaces = tmp_path / "workspaces"
    workspaces.mkdir(exist_ok=True)
    (devkit_dir / "config.yaml").write_text(
        f"version: 1\norg: org\nworkspaces_home: {workspaces}\n"
    )
    (devkit_dir / "PROJECTS.md").write_text(
        "# Projects\n\n"
        "| name | git_url | default_branch | description |\n"
        "|------|---------|----------------|-------------|\n"
        + rows + "\n"
    )
    fake_home = tmp_path / "home"
    fake_home.mkdir(exist_ok=True)
    monkeypatch.setenv("PROJECTS_HOME", str(projects))
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


def _two_repo_graph(workspace: Path) -> EpicGraph:
    """top#1 → child#7 (effective: repoA, repoB), child#8 (effective: repoB)."""
    top = "org/repo#1"
    c7 = "org/repo#7"
    c8 = "org/repoB#8"
    nodes = {
        c7: EpicNode(ref=c7, type="issue",
                     own_repos=["org/repoA", "org/repoB"],
                     effective_repos=["org/repoA", "org/repoB"],
                     branch_name="issue-repo-7", parent=top, children=[],
                     status="in_progress"),
        c8: EpicNode(ref=c8, type="issue", own_repos=["org/repoB"],
                     effective_repos=["org/repoB"], branch_name="issue-repoB-8",
                     parent=top, children=[], status="not_started"),
        top: EpicNode(ref=top, type="epic",
                      own_repos=["org/repoA", "org/repoB"],
                      effective_repos=["org/repoA", "org/repoB"],
                      branch_name="issue-repo-1", parent=None,
                      children=[c7, c8], status="in_progress"),
    }
    graph = EpicGraph(top_epic=top, current_issue=c7,
                      execution_order=[c7, c8], nodes=nodes)
    write_epic_md(workspace, graph)
    return graph


def _single_repo_graph(workspace: Path) -> EpicGraph:
    """top#42 → child#7 (effective: repoA only)."""
    top = "org/repo#42"
    c7 = "org/repo#7"
    nodes = {
        c7: EpicNode(ref=c7, type="issue", own_repos=["org/repoA"],
                     effective_repos=["org/repoA"], branch_name="issue-repoA-7",
                     parent=top, children=[], status="in_progress"),
        top: EpicNode(ref=top, type="epic", own_repos=["org/repoA"],
                      effective_repos=["org/repoA"], branch_name="issue-repo-42",
                      parent=None, children=[c7], status="in_progress"),
    }
    graph = EpicGraph(top_epic=top, current_issue=c7,
                      execution_order=[c7], nodes=nodes)
    write_epic_md(workspace, graph)
    return graph


# ---------------------------------------------------------------------------
# T037 — base branch selection and cross-linking
# ---------------------------------------------------------------------------

class TestPrCreateBaseBranch:
    def test_non_top_node_uses_parent_branch_as_base(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Non-top node → base = parent's branch_name (SC-004)."""
        workspace = tmp_path / "ws"
        workspace.mkdir()
        graph = _single_repo_graph(workspace)

        _setup_env(tmp_path, monkeypatch, [("repoA", "org/repoA")])
        monkeypatch.setattr(pc_mod, "_infer_workspace", lambda: workspace)

        pr_calls: list[list[str]] = []
        issue_title_calls: list[list[str]] = []

        def _mock_run(cmd, *, check=False, cwd=None):
            if cmd[:3] == ["gh", "issue", "view"]:
                issue_title_calls.append(cmd)
                return RunResult(code=0, stdout=json.dumps({"title": "Test Issue"}), stderr="")
            if cmd[:3] == ["gh", "pr", "create"]:
                pr_calls.append(list(cmd))
                return RunResult(code=0, stdout="https://github.com/org/repoA/pull/1\n", stderr="")
            return RunResult(code=0, stdout="", stderr="")

        monkeypatch.setattr("aidevkit.util.run", _mock_run)

        result = pc_mod.cmd_pr_create(dry_run=False)
        assert result == 0

        # Verify --base is the parent's branch_name
        assert pr_calls, "gh pr create must have been called"
        base_idx = pr_calls[0].index("--base")
        assert pr_calls[0][base_idx + 1] == "issue-repo-42"  # parent's branch

    def test_top_epic_uses_origin_default_branch(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Top epic as current_issue → base = origin/<default_branch>."""
        workspace = tmp_path / "ws"
        workspace.mkdir()
        top = "org/repo#42"
        nodes = {
            top: EpicNode(ref=top, type="epic", own_repos=["org/repoA"],
                          effective_repos=["org/repoA"], branch_name="issue-repo-42",
                          parent=None, children=[], status="in_progress"),
        }
        graph = EpicGraph(top_epic=top, current_issue=top, execution_order=[], nodes=nodes)
        write_epic_md(workspace, graph)

        _setup_env(tmp_path, monkeypatch, [("repoA", "org/repoA")])
        monkeypatch.setattr(pc_mod, "_infer_workspace", lambda: workspace)

        pr_calls: list[list[str]] = []

        def _mock_run(cmd, *, check=False, cwd=None):
            if cmd[:3] == ["gh", "issue", "view"]:
                return RunResult(code=0, stdout=json.dumps({"title": "Top Epic"}), stderr="")
            if cmd[:3] == ["gh", "pr", "create"]:
                pr_calls.append(list(cmd))
                return RunResult(code=0, stdout="https://github.com/org/repoA/pull/99\n", stderr="")
            return RunResult(code=0, stdout="", stderr="")

        monkeypatch.setattr("aidevkit.util.run", _mock_run)

        pc_mod.cmd_pr_create(dry_run=False)

        assert pr_calls
        base_idx = pr_calls[0].index("--base")
        # Should be "origin/main" (catalog default_branch = main)
        assert pr_calls[0][base_idx + 1].startswith("origin/")

    def test_cross_links_appear_in_pr_bodies(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Multi-repo node → pass-2 gh pr edit updates each PR body with sibling links."""
        workspace = tmp_path / "ws"
        workspace.mkdir()
        _two_repo_graph(workspace)

        _setup_env(tmp_path, monkeypatch, [("repoA", "org/repoA"), ("repoB", "org/repoB")])
        monkeypatch.setattr(pc_mod, "_infer_workspace", lambda: workspace)

        edit_calls: list[list[str]] = []
        pr_counter = [0]

        def _mock_run(cmd, *, check=False, cwd=None):
            if cmd[:3] == ["gh", "issue", "view"]:
                return RunResult(code=0, stdout=json.dumps({"title": "Feature"}), stderr="")
            if cmd[:3] == ["gh", "pr", "create"]:
                pr_counter[0] += 1
                return RunResult(
                    code=0,
                    stdout=f"https://github.com/org/repo/pull/{pr_counter[0]}\n",
                    stderr="",
                )
            if cmd[:3] == ["gh", "pr", "edit"]:
                edit_calls.append(list(cmd))
                return RunResult(code=0, stdout="", stderr="")
            return RunResult(code=0, stdout="", stderr="")

        monkeypatch.setattr("aidevkit.util.run", _mock_run)

        pc_mod.cmd_pr_create(dry_run=False)

        # 2 PRs created → 2 edit calls for cross-linking
        assert len(edit_calls) == 2
        # Each edit call body should reference the sibling PR URL
        bodies = [c[c.index("--body") + 1] for c in edit_calls if "--body" in c]
        assert all("https://github.com" in b for b in bodies)

    def test_epic_md_status_set_to_in_review(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """After pr-create, EPIC.md node status → in_review (FR-021)."""
        workspace = tmp_path / "ws"
        workspace.mkdir()
        _single_repo_graph(workspace)

        _setup_env(tmp_path, monkeypatch, [("repoA", "org/repoA")])
        monkeypatch.setattr(pc_mod, "_infer_workspace", lambda: workspace)

        def _mock_run(cmd, *, check=False, cwd=None):
            if cmd[:3] == ["gh", "issue", "view"]:
                return RunResult(code=0, stdout=json.dumps({"title": "x"}), stderr="")
            if cmd[:3] == ["gh", "pr", "create"]:
                return RunResult(code=0, stdout="https://github.com/org/repoA/pull/1\n", stderr="")
            return RunResult(code=0, stdout="", stderr="")

        monkeypatch.setattr("aidevkit.util.run", _mock_run)
        pc_mod.cmd_pr_create(dry_run=False)

        updated = read_epic_md(workspace)
        assert updated.nodes["org/repo#7"].status == "in_review"


# ---------------------------------------------------------------------------
# T038 — edge cases
# ---------------------------------------------------------------------------

class TestPrCreateEdgeCases:
    def test_dry_run_skips_pr_create_calls(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """--dry-run → no gh pr create calls, but EPIC.md still updated."""
        workspace = tmp_path / "ws"
        workspace.mkdir()
        _single_repo_graph(workspace)

        _setup_env(tmp_path, monkeypatch, [("repoA", "org/repoA")])
        monkeypatch.setattr(pc_mod, "_infer_workspace", lambda: workspace)

        gh_calls: list[list[str]] = []

        def _mock_run(cmd, *, check=False, cwd=None):
            gh_calls.append(list(cmd))
            return RunResult(code=0, stdout=json.dumps({"title": "x"}), stderr="")

        monkeypatch.setattr("aidevkit.util.run", _mock_run)

        result = pc_mod.cmd_pr_create(dry_run=True)
        assert result == 0

        pr_create_calls = [c for c in gh_calls if c[:3] == ["gh", "pr", "create"]]
        assert pr_create_calls == [], "dry-run must not call gh pr create"

    def test_single_repo_no_cross_link_edit(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Single effective repo → no gh pr edit calls needed."""
        workspace = tmp_path / "ws"
        workspace.mkdir()
        _single_repo_graph(workspace)

        _setup_env(tmp_path, monkeypatch, [("repoA", "org/repoA")])
        monkeypatch.setattr(pc_mod, "_infer_workspace", lambda: workspace)

        edit_calls: list = []

        def _mock_run(cmd, *, check=False, cwd=None):
            if cmd[:3] == ["gh", "pr", "edit"]:
                edit_calls.append(cmd)
            if cmd[:3] == ["gh", "issue", "view"]:
                return RunResult(code=0, stdout=json.dumps({"title": "x"}), stderr="")
            if cmd[:3] == ["gh", "pr", "create"]:
                return RunResult(code=0, stdout="https://github.com/org/repoA/pull/1\n", stderr="")
            return RunResult(code=0, stdout="", stderr="")

        monkeypatch.setattr("aidevkit.util.run", _mock_run)

        pc_mod.cmd_pr_create(dry_run=False)
        assert edit_calls == [], "single-repo: no sibling cross-link edit should be called"
