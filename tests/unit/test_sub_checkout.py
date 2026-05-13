"""Unit tests for sub_checkout — T030/T031."""
from __future__ import annotations

from pathlib import Path

import pytest
import typer

import aidevkit.sub_checkout as sc_mod
from aidevkit.epic import EpicGraph, EpicNode, read_epic_md, write_epic_md
from aidevkit.util import (
    E_DIRTY_WORKTREE,
    E_EPIC_GRAPH_INVALID,
    E_NODE_NOT_FOUND,
    E_NOT_IN_WORKSPACE,
    E_USAGE,
    RunResult,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_workspace(tmp_path: Path) -> Path:
    ws = tmp_path / "ws"
    ws.mkdir(parents=True, exist_ok=True)
    return ws


def _make_graph(workspace: Path) -> EpicGraph:
    """2-node epic graph written to workspace/EPIC.md."""
    child_ref = "org/repo#7"
    top_ref = "org/repo#42"
    nodes = {
        child_ref: EpicNode(
            ref=child_ref, type="issue",
            own_repos=["org/repoA"], effective_repos=["org/repoA"],
            branch_name="issue-repoA-7", parent=top_ref, children=[],
            status="not_started",
        ),
        top_ref: EpicNode(
            ref=top_ref, type="epic",
            own_repos=["org/repoA"], effective_repos=["org/repoA"],
            branch_name="issue-repo-42", parent=None, children=[child_ref],
            status="in_progress",
        ),
    }
    graph = EpicGraph(
        top_epic=top_ref, current_issue=child_ref,
        execution_order=[child_ref], nodes=nodes,
    )
    write_epic_md(workspace, graph, title="Test Epic")
    return graph


def _make_two_child_graph(workspace: Path) -> EpicGraph:
    """top → child#7 (repoA only) + child#8 (repoB only)."""
    top_ref = "org/repo#1"
    c7 = "org/repo#7"
    c8 = "org/repoB#8"
    nodes = {
        c7: EpicNode(ref=c7, type="issue", own_repos=["org/repoA"],
                     effective_repos=["org/repoA"], branch_name="issue-repoA-7",
                     parent=top_ref, children=[], status="not_started"),
        c8: EpicNode(ref=c8, type="issue", own_repos=["org/repoB"],
                     effective_repos=["org/repoB"], branch_name="issue-repoB-8",
                     parent=top_ref, children=[], status="not_started"),
        top_ref: EpicNode(ref=top_ref, type="epic", own_repos=["org/repoA"],
                          effective_repos=["org/repoA", "org/repoB"],
                          branch_name="issue-repo-1", parent=None,
                          children=[c7, c8], status="in_progress"),
    }
    graph = EpicGraph(top_epic=top_ref, current_issue=c7,
                      execution_order=[c7, c8], nodes=nodes)
    write_epic_md(workspace, graph)
    return graph


def _setup_projects_home(
    tmp_path: Path,
    org_repos: list[tuple[str, str]],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    rows = "\n".join(
        f"| {name} | git@github.com:{or_}.git | main | x |"
        for name, or_ in org_repos
    )
    catalog = (
        "# Projects\n\n"
        "| name | git_url | default_branch | description |\n"
        "|------|---------|----------------|-------------|\n"
        + rows + "\n"
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
    (devkit_dir / "PROJECTS.md").write_text(catalog)

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


# ---------------------------------------------------------------------------
# T030 — happy path
# ---------------------------------------------------------------------------

class TestSubCheckoutHappyPath:
    def test_switches_effective_repos_to_node_branch(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch, subprocess_capture
    ) -> None:
        workspace = _make_workspace(tmp_path)
        _make_graph(workspace)
        (workspace / "repoA").mkdir()

        _setup_projects_home(tmp_path, [("repoA", "org/repoA")], monkeypatch)
        monkeypatch.setattr(sc_mod, "_infer_workspace", lambda num=None: workspace)
        subprocess_capture.set_default(RunResult(code=0, stdout="", stderr=""))

        result = sc_mod.cmd_sub_checkout("7")
        assert result == 0

        checkout_calls = [
            c for c in subprocess_capture.calls
            if c["cmd"][:2] == ["git", "checkout"]
        ]
        assert any("issue-repoA-7" in c["cmd"] for c in checkout_calls)

    def test_epic_md_updated_after_checkout(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch, subprocess_capture
    ) -> None:
        workspace = _make_workspace(tmp_path)
        _make_graph(workspace)
        (workspace / "repoA").mkdir()

        _setup_projects_home(tmp_path, [("repoA", "org/repoA")], monkeypatch)
        monkeypatch.setattr(sc_mod, "_infer_workspace", lambda num=None: workspace)
        subprocess_capture.set_default(RunResult(code=0, stdout="", stderr=""))

        sc_mod.cmd_sub_checkout("7")

        updated = read_epic_md(workspace)
        assert updated.current_issue == "org/repo#7"
        assert updated.nodes["org/repo#7"].status == "in_progress"

    def test_repos_outside_effective_n_not_switched(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch, subprocess_capture
    ) -> None:
        workspace = _make_workspace(tmp_path)
        _make_two_child_graph(workspace)
        (workspace / "repoA").mkdir()
        (workspace / "repoB").mkdir()

        _setup_projects_home(
            tmp_path, [("repoA", "org/repoA"), ("repoB", "org/repoB")], monkeypatch
        )
        monkeypatch.setattr(sc_mod, "_infer_workspace", lambda num=None: workspace)
        subprocess_capture.set_default(RunResult(code=0, stdout="", stderr=""))

        sc_mod.cmd_sub_checkout("7")  # only touches repoA

        checkout_calls = [
            c for c in subprocess_capture.calls
            if c["cmd"][:2] == ["git", "checkout"]
        ]
        assert any(c["cwd"] == workspace / "repoA" for c in checkout_calls)
        assert not any(c["cwd"] == workspace / "repoB" for c in checkout_calls)


# ---------------------------------------------------------------------------
# T031 — error paths
# ---------------------------------------------------------------------------

class TestSubCheckoutErrors:
    def test_dirty_effective_repo_blocks_checkout(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch, subprocess_capture
    ) -> None:
        workspace = _make_workspace(tmp_path)
        _make_graph(workspace)
        (workspace / "repoA").mkdir()

        _setup_projects_home(tmp_path, [("repoA", "org/repoA")], monkeypatch)
        monkeypatch.setattr(sc_mod, "_infer_workspace", lambda num=None: workspace)
        # git status → dirty
        subprocess_capture.set_default(
            RunResult(code=0, stdout=" M somefile.py\n", stderr="")
        )

        with pytest.raises(typer.Exit) as exc_info:
            sc_mod.cmd_sub_checkout("7")
        assert exc_info.value.exit_code == E_DIRTY_WORKTREE

        # No git checkout should have been called
        assert not any(
            c["cmd"][:2] == ["git", "checkout"]
            for c in subprocess_capture.calls
        )

    def test_dirty_outside_effective_n_does_not_block(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch, subprocess_capture
    ) -> None:
        """Dirty repo outside effective(N) does NOT block (clarification Q2)."""
        workspace = _make_workspace(tmp_path)
        _make_two_child_graph(workspace)
        (workspace / "repoA").mkdir()
        (workspace / "repoB").mkdir()

        _setup_projects_home(
            tmp_path, [("repoA", "org/repoA"), ("repoB", "org/repoB")], monkeypatch
        )
        monkeypatch.setattr(sc_mod, "_infer_workspace", lambda num=None: workspace)

        # repoA (effective for #7) is clean; repoB is dirty but outside effective(#7)
        def _status_mock(cmd, *, check=False, cwd=None):
            if cmd[:2] == ["git", "status"] and cwd == workspace / "repoB":
                return RunResult(code=0, stdout=" M dirty.py\n", stderr="")
            return RunResult(code=0, stdout="", stderr="")

        monkeypatch.setattr("aidevkit.util.run", _status_mock)

        result = sc_mod.cmd_sub_checkout("7")
        assert result == 0

    def test_unknown_node_ref_exits(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch, subprocess_capture
    ) -> None:
        workspace = _make_workspace(tmp_path)
        _make_graph(workspace)

        _setup_projects_home(tmp_path, [("repoA", "org/repoA")], monkeypatch)
        monkeypatch.setattr(sc_mod, "_infer_workspace", lambda num=None: workspace)

        with pytest.raises(typer.Exit) as exc_info:
            sc_mod.cmd_sub_checkout("999")
        assert exc_info.value.exit_code == E_NODE_NOT_FOUND

    def test_wrong_node_serial_enforcement(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch, subprocess_capture
    ) -> None:
        """N ≠ current_issue → E_USAGE (FR-030)."""
        workspace = _make_workspace(tmp_path)
        _make_two_child_graph(workspace)  # current_issue = #7, try checkout #8

        _setup_projects_home(
            tmp_path, [("repoA", "org/repoA"), ("repoB", "org/repoB")], monkeypatch
        )
        monkeypatch.setattr(sc_mod, "_infer_workspace", lambda num=None: workspace)

        with pytest.raises(typer.Exit) as exc_info:
            sc_mod.cmd_sub_checkout("8")
        assert exc_info.value.exit_code == E_USAGE

    def test_current_issue_is_top_epic_shows_guidance(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch, subprocess_capture
    ) -> None:
        """current_issue == top_epic → E_USAGE with guidance message."""
        workspace = _make_workspace(tmp_path)
        graph = _make_graph(workspace)
        # Override current_issue to be the top epic
        graph.current_issue = graph.top_epic
        write_epic_md(workspace, graph)

        _setup_projects_home(tmp_path, [("repoA", "org/repoA")], monkeypatch)
        monkeypatch.setattr(sc_mod, "_infer_workspace", lambda num=None: workspace)

        with pytest.raises(typer.Exit) as exc_info:
            sc_mod.cmd_sub_checkout("7")
        assert exc_info.value.exit_code == E_USAGE

    def test_no_epic_md_exits(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch, subprocess_capture
    ) -> None:
        """Workspace without EPIC.md → E_EPIC_GRAPH_INVALID (C2)."""
        workspace = _make_workspace(tmp_path)
        _setup_projects_home(tmp_path, [], monkeypatch)
        monkeypatch.setattr(sc_mod, "_infer_workspace", lambda num=None: workspace)

        with pytest.raises(typer.Exit) as exc_info:
            sc_mod.cmd_sub_checkout("7")
        assert exc_info.value.exit_code == E_EPIC_GRAPH_INVALID

    def test_no_workspace_exits(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch, subprocess_capture
    ) -> None:
        """Not inside any workspace → E_NOT_IN_WORKSPACE."""
        _setup_projects_home(tmp_path, [], monkeypatch)
        monkeypatch.setattr(sc_mod, "_infer_workspace", lambda num=None: None)

        with pytest.raises(typer.Exit) as exc_info:
            sc_mod.cmd_sub_checkout("7")
        assert exc_info.value.exit_code == E_NOT_IN_WORKSPACE
