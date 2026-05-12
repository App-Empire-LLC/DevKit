"""Unit tests for aidevkit.epic — graph computation, I/O, branch naming."""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from aidevkit.epic import (
    EpicGraph,
    EpicGraphInvalid,
    EpicNode,
    _repo_slug_from_url,
    compute_effective_repos,
    compute_execution_order,
    fetch_sub_issues,
    read_epic_md,
    walk_graph,
    write_epic_md,
)
from aidevkit.util import RunResult


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _node(
    ref: str,
    own_repos: list[str],
    children: list[str],
    parent: str | None = None,
) -> EpicNode:
    return EpicNode(
        ref=ref,
        type="epic" if children else "issue",
        own_repos=own_repos,
        effective_repos=[],
        branch_name="",
        parent=parent,
        children=children,
        status="not_started",
    )


def _build_worked_example() -> dict[str, EpicNode]:
    """Reproduce the worked example from the spec/issue:

    top_epic#1   own: repoA, repoB
    └── sub_epic#2  own: repoA
        ├── issue#7   own: repoA, repoB
        └── issue#8   own: repoB
    """
    nodes: dict[str, EpicNode] = {
        "issue#7": _node("issue#7", ["repoA", "repoB"], [], parent="sub_epic#2"),
        "issue#8": _node("issue#8", ["repoB"], [], parent="sub_epic#2"),
        "sub_epic#2": _node("sub_epic#2", ["repoA"], ["issue#7", "issue#8"], parent="top_epic#1"),
        "top_epic#1": _node("top_epic#1", ["repoA", "repoB"], ["sub_epic#2"]),
    }
    return nodes


# ---------------------------------------------------------------------------
# T009 — compute_effective_repos
# ---------------------------------------------------------------------------

class TestComputeEffectiveRepos:
    def test_single_repo_leaf(self):
        nodes = {"n#1": _node("n#1", ["repoA"], [])}
        assert compute_effective_repos(nodes, "n#1") == ["repoA"]

    def test_multi_repo_leaf(self):
        nodes = {"n#1": _node("n#1", ["repoA", "repoB"], [])}
        result = compute_effective_repos(nodes, "n#1")
        assert result == ["repoA", "repoB"]

    def test_parent_inherits_from_child(self):
        nodes = {
            "child#1": _node("child#1", ["repoB"], []),
            "parent#1": _node("parent#1", ["repoA"], ["child#1"]),
        }
        result = compute_effective_repos(nodes, "parent#1")
        assert "repoA" in result
        assert "repoB" in result

    def test_worked_example_issue7(self):
        nodes = _build_worked_example()
        result = compute_effective_repos(nodes, "issue#7")
        assert set(result) == {"repoA", "repoB"}

    def test_worked_example_issue8(self):
        nodes = _build_worked_example()
        result = compute_effective_repos(nodes, "issue#8")
        assert result == ["repoB"]

    def test_worked_example_sub_epic2(self):
        nodes = _build_worked_example()
        result = compute_effective_repos(nodes, "sub_epic#2")
        # own: repoA; children add repoA, repoB → effective: repoA, repoB
        assert set(result) == {"repoA", "repoB"}

    def test_worked_example_top_epic1(self):
        nodes = _build_worked_example()
        result = compute_effective_repos(nodes, "top_epic#1")
        assert set(result) == {"repoA", "repoB"}

    def test_deduplication(self):
        """Repos appearing in both own and children are deduplicated."""
        nodes = {
            "child#1": _node("child#1", ["repoA"], []),
            "parent#1": _node("parent#1", ["repoA"], ["child#1"]),
        }
        result = compute_effective_repos(nodes, "parent#1")
        assert result.count("repoA") == 1


# ---------------------------------------------------------------------------
# T010 — compute_execution_order
# ---------------------------------------------------------------------------

class TestComputeExecutionOrder:
    def test_leaves_before_parents(self):
        nodes = _build_worked_example()
        order = compute_execution_order("top_epic#1", nodes)
        assert order.index("issue#7") < order.index("sub_epic#2")
        assert order.index("issue#8") < order.index("sub_epic#2")

    def test_top_epic_excluded(self):
        nodes = _build_worked_example()
        order = compute_execution_order("top_epic#1", nodes)
        assert "top_epic#1" not in order

    def test_all_non_top_included(self):
        nodes = _build_worked_example()
        order = compute_execution_order("top_epic#1", nodes)
        assert set(order) == {"issue#7", "issue#8", "sub_epic#2"}

    def test_sibling_order_matches_children_list(self):
        """Siblings appear in the order they appear in parent.children."""
        nodes = {
            "i#1": _node("i#1", ["R"], [], parent="p#1"),
            "i#2": _node("i#2", ["R"], [], parent="p#1"),
            "p#1": _node("p#1", ["R"], ["i#1", "i#2"]),
        }
        order = compute_execution_order("p#1", nodes)
        assert order.index("i#1") < order.index("i#2")

    def test_flat_single_child(self):
        nodes = {
            "child#1": _node("child#1", ["R"], []),
            "top#1": _node("top#1", ["R"], ["child#1"]),
        }
        order = compute_execution_order("top#1", nodes)
        assert order == ["child#1"]


# ---------------------------------------------------------------------------
# T011 — walk_graph (mocked via subprocess_capture)
# ---------------------------------------------------------------------------

class TestWalkGraph:
    def test_no_sub_issues_returns_none(self, subprocess_capture):
        subprocess_capture.set_default(RunResult(code=0, stdout="[]", stderr=""))
        result = walk_graph("org", "repo", 42, no_recursive=False)
        assert result is None

    def test_api_failure_returns_none(self, subprocess_capture):
        subprocess_capture.set_default(RunResult(code=1, stdout="", stderr="error"))
        result = walk_graph("org", "repo", 42, no_recursive=False)
        assert result is None

    def test_returns_epic_graph_when_sub_issues_exist(self, subprocess_capture):
        child = {
            "number": 7,
            "html_url": "https://github.com/org/repo/issues/7",
            "body": "## Affected Repos\n- org/repo\n",
        }
        # First call: sub_issues for top (returns child); second call: sub_issues for child (none)
        subprocess_capture.queue(RunResult(code=0, stdout=json.dumps([child]), stderr=""))
        subprocess_capture.queue(RunResult(code=0, stdout="[]", stderr=""))
        result = walk_graph("org", "repo", 42, no_recursive=False)
        assert result is not None
        assert "org/repo#42" in result.nodes
        assert "org/repo#7" in result.nodes

    def test_no_recursive_stops_at_depth_1(self, subprocess_capture):
        grandchild = {
            "number": 8,
            "html_url": "https://github.com/org/repo/issues/8",
            "body": "",
        }
        child = {
            "number": 7,
            "html_url": "https://github.com/org/repo/issues/7",
            "body": "## Affected Repos\n- org/repo\n",
        }
        # First call: sub_issues for top → [child]
        subprocess_capture.queue(RunResult(code=0, stdout=json.dumps([child]), stderr=""))
        # --no-recursive: should NOT call sub_issues for child
        result = walk_graph("org", "repo", 42, no_recursive=True)
        assert result is not None
        assert "org/repo#7" in result.nodes
        # grandchild should not be present
        assert "org/repo#8" not in result.nodes

    def test_execution_order_first_is_leaf(self, subprocess_capture):
        child = {
            "number": 7,
            "html_url": "https://github.com/org/repo/issues/7",
            "body": "",
        }
        subprocess_capture.queue(RunResult(code=0, stdout=json.dumps([child]), stderr=""))
        subprocess_capture.queue(RunResult(code=0, stdout="[]", stderr=""))
        result = walk_graph("org", "repo", 42, no_recursive=False)
        assert result is not None
        assert result.execution_order[0] == "org/repo#7"
        assert result.current_issue == "org/repo#7"

    def test_branch_name_format(self, subprocess_capture):
        child = {
            "number": 7,
            "html_url": "https://github.com/org/repo/issues/7",
            "body": "",
        }
        subprocess_capture.queue(RunResult(code=0, stdout=json.dumps([child]), stderr=""))
        subprocess_capture.queue(RunResult(code=0, stdout="[]", stderr=""))
        result = walk_graph("org", "repo", 42, no_recursive=False)
        assert result is not None
        assert result.nodes["org/repo#42"].branch_name == "issue-repo-42"
        assert result.nodes["org/repo#7"].branch_name == "issue-repo-7"

    def test_cross_repo_branch_name_from_html_url(self, subprocess_capture):
        """Sub-issue in a different repo uses that repo's slug for branch_name."""
        child = {
            "number": 8,
            "html_url": "https://github.com/org/appire_docs/issues/8",
            "body": "## Affected Repos\n- org/appire_docs\n",
        }
        subprocess_capture.queue(RunResult(code=0, stdout=json.dumps([child]), stderr=""))
        subprocess_capture.queue(RunResult(code=0, stdout="[]", stderr=""))
        result = walk_graph("org", "DevKit", 42, no_recursive=False)
        assert result is not None
        assert result.nodes["org/appire_docs#8"].branch_name == "issue-appire_docs-8"


# ---------------------------------------------------------------------------
# T012 — read_epic_md / write_epic_md round-trip
# ---------------------------------------------------------------------------

class TestEpicMdRoundTrip:
    def _make_graph(self) -> EpicGraph:
        nodes = {
            "org/repo#7": EpicNode(
                ref="org/repo#7",
                type="issue",
                own_repos=["org/repo"],
                effective_repos=["org/repo"],
                branch_name="issue-repo-7",
                parent="org/repo#42",
                children=[],
                status="not_started",
            ),
            "org/repo#42": EpicNode(
                ref="org/repo#42",
                type="epic",
                own_repos=["org/repo"],
                effective_repos=["org/repo"],
                branch_name="issue-repo-42",
                parent=None,
                children=["org/repo#7"],
                status="in_progress",
            ),
        }
        return EpicGraph(
            top_epic="org/repo#42",
            current_issue="org/repo#7",
            execution_order=["org/repo#7"],
            nodes=nodes,
        )

    def test_roundtrip_preserves_fields(self, tmp_path: Path):
        graph = self._make_graph()
        write_epic_md(tmp_path, graph, title="Test Epic")
        restored = read_epic_md(tmp_path)

        assert restored.top_epic == graph.top_epic
        assert restored.current_issue == graph.current_issue
        assert restored.execution_order == graph.execution_order
        assert set(restored.nodes.keys()) == set(graph.nodes.keys())

        n = restored.nodes["org/repo#7"]
        assert n.branch_name == "issue-repo-7"
        assert n.parent == "org/repo#42"
        assert n.status == "not_started"
        assert n.own_repos == ["org/repo"]

    def test_invalid_yaml_raises(self, tmp_path: Path):
        (tmp_path / "EPIC.md").write_text("---\n: broken: yaml: [\n---\n\n# body")
        with pytest.raises(EpicGraphInvalid):
            read_epic_md(tmp_path)

    def test_missing_field_raises(self, tmp_path: Path):
        (tmp_path / "EPIC.md").write_text("---\ntop_epic: x\n---\n\n# body")
        with pytest.raises(EpicGraphInvalid, match="missing required fields"):
            read_epic_md(tmp_path)

    def test_invalid_status_raises(self, tmp_path: Path):
        graph = self._make_graph()
        write_epic_md(tmp_path, graph)
        text = (tmp_path / "EPIC.md").read_text()
        text = text.replace("not_started", "bad_status")
        (tmp_path / "EPIC.md").write_text(text)
        with pytest.raises(EpicGraphInvalid, match="invalid status"):
            read_epic_md(tmp_path)

    def test_missing_file_raises(self, tmp_path: Path):
        with pytest.raises(EpicGraphInvalid, match="not found"):
            read_epic_md(tmp_path)

    def test_write_creates_valid_frontmatter_delimiters(self, tmp_path: Path):
        graph = self._make_graph()
        write_epic_md(tmp_path, graph)
        content = (tmp_path / "EPIC.md").read_text()
        assert content.startswith("---\n")
        parts = content.split("---\n", 2)
        assert len(parts) == 3


# ---------------------------------------------------------------------------
# T013 — branch naming and merge target resolution
# ---------------------------------------------------------------------------

class TestBranchNaming:
    def test_branch_name_format_issue_repo_N(self, subprocess_capture):
        child = {
            "number": 7,
            "html_url": "https://github.com/org/myrepo/issues/7",
            "body": "",
        }
        subprocess_capture.queue(RunResult(code=0, stdout=json.dumps([child]), stderr=""))
        subprocess_capture.queue(RunResult(code=0, stdout="[]", stderr=""))
        result = walk_graph("org", "myrepo", 42, no_recursive=False)
        assert result is not None
        assert result.nodes["org/myrepo#42"].branch_name == "issue-myrepo-42"
        assert result.nodes["org/myrepo#7"].branch_name == "issue-myrepo-7"

    def test_repo_slug_from_url(self):
        assert _repo_slug_from_url(
            "https://github.com/App-Empire-LLC/appire_docs/issues/8"
        ) == "appire_docs"
        assert _repo_slug_from_url(
            "https://github.com/org/DevKit/issues/42"
        ) == "DevKit"
        assert _repo_slug_from_url("not-a-url") is None

    def test_top_epic_parent_is_none(self, subprocess_capture):
        child = {"number": 7, "html_url": "https://github.com/org/repo/issues/7", "body": ""}
        subprocess_capture.queue(RunResult(code=0, stdout=json.dumps([child]), stderr=""))
        subprocess_capture.queue(RunResult(code=0, stdout="[]", stderr=""))
        result = walk_graph("org", "repo", 42, no_recursive=False)
        assert result is not None
        assert result.nodes["org/repo#42"].parent is None

    def test_child_parent_is_top_epic(self, subprocess_capture):
        child = {"number": 7, "html_url": "https://github.com/org/repo/issues/7", "body": ""}
        subprocess_capture.queue(RunResult(code=0, stdout=json.dumps([child]), stderr=""))
        subprocess_capture.queue(RunResult(code=0, stdout="[]", stderr=""))
        result = walk_graph("org", "repo", 42, no_recursive=False)
        assert result is not None
        assert result.nodes["org/repo#7"].parent == "org/repo#42"
