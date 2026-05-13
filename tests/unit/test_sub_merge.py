"""Unit tests for sub_merge — T045/T046/T047."""
from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import patch

import pytest
import typer

import aidevkit.sub_merge as sm_mod
from aidevkit.epic import EpicGraph, EpicNode, read_epic_md, write_epic_md
from aidevkit.util import E_EPIC_GRAPH_INVALID, E_NODE_NOT_FOUND, E_NOT_IN_WORKSPACE, RunResult


# ---------------------------------------------------------------------------
# Helpers
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


def _two_leaf_graph(workspace: Path) -> EpicGraph:
    """top#1 → child#7 (repoA) + child#8 (repoA); execution_order=[#7, #8, sub, top]."""
    top = "org/repo#1"
    c7 = "org/repo#7"
    c8 = "org/repo#8"
    nodes = {
        c7: EpicNode(ref=c7, type="issue", own_repos=["org/repoA"],
                     effective_repos=["org/repoA"], branch_name="issue-repoA-7",
                     parent=top, children=[], status="in_progress"),
        c8: EpicNode(ref=c8, type="issue", own_repos=["org/repoA"],
                     effective_repos=["org/repoA"], branch_name="issue-repoA-8",
                     parent=top, children=[], status="not_started"),
        top: EpicNode(ref=top, type="epic", own_repos=["org/repoA"],
                      effective_repos=["org/repoA"], branch_name="issue-repo-1",
                      parent=None, children=[c7, c8], status="in_progress"),
    }
    graph = EpicGraph(top_epic=top, current_issue=c7,
                      execution_order=[c7, c8], nodes=nodes)
    write_epic_md(workspace, graph)
    return graph


# ---------------------------------------------------------------------------
# T045 — happy path
# ---------------------------------------------------------------------------

class TestSubMergeHappyPath:
    def test_all_prs_merged_advances_current_issue(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        workspace = tmp_path / "ws"
        workspace.mkdir()
        _two_leaf_graph(workspace)

        _setup_env(tmp_path, monkeypatch, [("repoA", "org/repoA")])
        (tmp_path / "projects" / "repoA" / ".git").mkdir(parents=True, exist_ok=True)
        monkeypatch.setattr(sm_mod, "_infer_workspace", lambda: workspace)

        # All PRs merged: gh pr list returns [{"state": "MERGED", ...}]
        def _mock_run(cmd, *, check=False, cwd=None):
            if cmd[:3] == ["gh", "pr", "list"]:
                return RunResult(
                    code=0,
                    stdout=json.dumps([{"number": 1, "state": "MERGED", "url": "https://gh/1"}]),
                    stderr="",
                )
            if cmd[:3] == ["gh", "issue", "view"]:
                return RunResult(code=0, stdout=json.dumps({"title": "x"}), stderr="")
            if cmd[:3] == ["gh", "pr", "create"]:
                return RunResult(code=0, stdout="https://gh/99\n", stderr="")
            return RunResult(code=0, stdout="", stderr="")

        monkeypatch.setattr("aidevkit.util.run", _mock_run)
        # Prevent cascade from actually opening PRs for parent
        monkeypatch.setattr(sm_mod, "_cascade_up", lambda ws, g, pr: None)

        result = sm_mod.cmd_sub_merge("7")
        assert result == 0

        updated = read_epic_md(workspace)
        assert updated.nodes["org/repo#7"].status == "merged"
        assert updated.current_issue == "org/repo#8"  # advanced

    def test_some_prs_open_returns_prs_not_merged(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """PRs still open → E_PRS_NOT_MERGED; EPIC.md unchanged."""
        workspace = tmp_path / "ws"
        workspace.mkdir()
        _two_leaf_graph(workspace)

        _setup_env(tmp_path, monkeypatch, [("repoA", "org/repoA")])
        (tmp_path / "projects" / "repoA" / ".git").mkdir(parents=True, exist_ok=True)
        monkeypatch.setattr(sm_mod, "_infer_workspace", lambda: workspace)

        def _mock_run(cmd, *, check=False, cwd=None):
            if cmd[:3] == ["gh", "pr", "list"]:
                return RunResult(
                    code=0,
                    stdout=json.dumps([{"number": 1, "state": "OPEN", "url": "https://gh/1"}]),
                    stderr="",
                )
            return RunResult(code=0, stdout="", stderr="")

        monkeypatch.setattr("aidevkit.util.run", _mock_run)

        from aidevkit.util import E_PRS_NOT_MERGED
        result = sm_mod.cmd_sub_merge("7")
        assert result == E_PRS_NOT_MERGED

        # EPIC.md must be unchanged
        unchanged = read_epic_md(workspace)
        assert unchanged.nodes["org/repo#7"].status == "in_progress"
        assert unchanged.current_issue == "org/repo#7"


# ---------------------------------------------------------------------------
# T046 — cascade-up
# ---------------------------------------------------------------------------

class TestSubMergeCascadeUp:
    def test_cascade_fires_when_all_siblings_merged(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """All siblings merged → _cascade_up calls _open_prs_for for parent."""
        workspace = tmp_path / "ws"
        workspace.mkdir()
        graph = _two_leaf_graph(workspace)
        # Pre-merge sibling c8 so cascade fires when c7 is merged
        graph.nodes["org/repo#8"].status = "merged"
        write_epic_md(workspace, graph)

        _setup_env(tmp_path, monkeypatch, [("repoA", "org/repoA")])
        (tmp_path / "projects" / "repoA" / ".git").mkdir(parents=True, exist_ok=True)
        monkeypatch.setattr(sm_mod, "_infer_workspace", lambda: workspace)

        prs_opened_for: list[str] = []

        def _mock_open_prs(ws, g, node_ref, dry_run=False):
            prs_opened_for.append(node_ref)

        def _mock_run(cmd, *, check=False, cwd=None):
            if cmd[:3] == ["gh", "pr", "list"]:
                return RunResult(
                    code=0,
                    stdout=json.dumps([{"number": 1, "state": "MERGED", "url": "https://gh/1"}]),
                    stderr="",
                )
            return RunResult(code=0, stdout="", stderr="")

        monkeypatch.setattr("aidevkit.util.run", _mock_run)
        monkeypatch.setattr(sm_mod, "_open_prs_for", _mock_open_prs)

        result = sm_mod.cmd_sub_merge("7")
        assert result == 0

        # Cascade should have opened PRs for the parent (top)
        assert "org/repo#1" in prs_opened_for

        updated = read_epic_md(workspace)
        assert updated.nodes["org/repo#1"].status == "in_review"

    def test_cascade_does_not_fire_when_sibling_unmerged(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Sibling still not_started → cascade does NOT fire."""
        workspace = tmp_path / "ws"
        workspace.mkdir()
        _two_leaf_graph(workspace)  # c8 is not_started

        _setup_env(tmp_path, monkeypatch, [("repoA", "org/repoA")])
        (tmp_path / "projects" / "repoA" / ".git").mkdir(parents=True, exist_ok=True)
        monkeypatch.setattr(sm_mod, "_infer_workspace", lambda: workspace)

        cascade_calls: list = []

        def _mock_run(cmd, *, check=False, cwd=None):
            if cmd[:3] == ["gh", "pr", "list"]:
                return RunResult(
                    code=0,
                    stdout=json.dumps([{"number": 1, "state": "MERGED", "url": "https://gh/1"}]),
                    stderr="",
                )
            return RunResult(code=0, stdout="", stderr="")

        def _mock_open_prs(ws, g, node_ref, dry_run=False):
            cascade_calls.append(node_ref)

        monkeypatch.setattr("aidevkit.util.run", _mock_run)
        monkeypatch.setattr(sm_mod, "_open_prs_for", _mock_open_prs)

        sm_mod.cmd_sub_merge("7")

        # c8 is still not_started, so cascade should NOT have opened parent PRs
        assert cascade_calls == []

    def test_cascade_does_not_auto_mark_parent_merged(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """cascade-up sets parent to in_review, NOT merged (FR-024 clarification)."""
        workspace = tmp_path / "ws"
        workspace.mkdir()
        graph = _two_leaf_graph(workspace)
        graph.nodes["org/repo#8"].status = "merged"
        write_epic_md(workspace, graph)

        _setup_env(tmp_path, monkeypatch, [("repoA", "org/repoA")])
        (tmp_path / "projects" / "repoA" / ".git").mkdir(parents=True, exist_ok=True)
        monkeypatch.setattr(sm_mod, "_infer_workspace", lambda: workspace)

        def _mock_run(cmd, *, check=False, cwd=None):
            if cmd[:3] == ["gh", "pr", "list"]:
                return RunResult(
                    code=0,
                    stdout=json.dumps([{"number": 1, "state": "MERGED", "url": "https://gh/1"}]),
                    stderr="",
                )
            return RunResult(code=0, stdout="", stderr="")

        monkeypatch.setattr("aidevkit.util.run", _mock_run)
        monkeypatch.setattr(sm_mod, "_open_prs_for",
                            lambda ws, g, ref, dry_run=False: None)

        sm_mod.cmd_sub_merge("7")

        updated = read_epic_md(workspace)
        # Parent should be in_review, NOT merged
        assert updated.nodes["org/repo#1"].status == "in_review"
        assert updated.nodes["org/repo#1"].status != "merged"


# ---------------------------------------------------------------------------
# T047 — edge cases
# ---------------------------------------------------------------------------

class TestSubMergeEdgeCases:
    def test_last_leaf_sets_current_issue_to_top_epic(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """execution_order exhausted → current_issue = top_epic (clarification Q5)."""
        workspace = tmp_path / "ws"
        workspace.mkdir()
        # Single-child graph: only c7 in execution_order
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
        graph = EpicGraph(top_epic=top, current_issue=c7, execution_order=[c7], nodes=nodes)
        write_epic_md(workspace, graph)

        _setup_env(tmp_path, monkeypatch, [("repoA", "org/repoA")])
        (tmp_path / "projects" / "repoA" / ".git").mkdir(parents=True, exist_ok=True)
        monkeypatch.setattr(sm_mod, "_infer_workspace", lambda: workspace)
        monkeypatch.setattr(sm_mod, "_cascade_up", lambda ws, g, pr: None)

        def _mock_run(cmd, *, check=False, cwd=None):
            if cmd[:3] == ["gh", "pr", "list"]:
                return RunResult(
                    code=0,
                    stdout=json.dumps([{"number": 1, "state": "MERGED", "url": "https://gh/1"}]),
                    stderr="",
                )
            return RunResult(code=0, stdout="", stderr="")

        monkeypatch.setattr("aidevkit.util.run", _mock_run)

        result = sm_mod.cmd_sub_merge("7")
        assert result == 0

        updated = read_epic_md(workspace)
        # current_issue should point to top_epic
        assert updated.current_issue == top

    def test_unknown_node_ref(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        workspace = tmp_path / "ws"
        workspace.mkdir()
        _two_leaf_graph(workspace)
        _setup_env(tmp_path, monkeypatch, [("repoA", "org/repoA")])
        monkeypatch.setattr(sm_mod, "_infer_workspace", lambda: workspace)

        with pytest.raises(typer.Exit) as exc_info:
            sm_mod.cmd_sub_merge("999")
        assert exc_info.value.exit_code == E_NODE_NOT_FOUND

    def test_no_epic_md_exits(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        workspace = tmp_path / "ws"
        workspace.mkdir()
        _setup_env(tmp_path, monkeypatch, [])
        monkeypatch.setattr(sm_mod, "_infer_workspace", lambda: workspace)

        with pytest.raises(typer.Exit) as exc_info:
            sm_mod.cmd_sub_merge("7")
        assert exc_info.value.exit_code == E_EPIC_GRAPH_INVALID
