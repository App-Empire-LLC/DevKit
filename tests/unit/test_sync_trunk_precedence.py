"""T035 [US2]: `resolve_trunk` precedence across worktree/workspace/default."""

from __future__ import annotations

from aidevkit import sync as _sync


def test_worktree_trunk_beats_workspace_trunk(tmp_path):
    wt = tmp_path / "repo"
    wt.mkdir()
    (wt / "TRUNK.md").write_text("master\n")
    assert _sync.resolve_trunk(wt, workspace_default="develop") == "master"


def test_workspace_trunk_used_when_worktree_has_none(tmp_path):
    wt = tmp_path / "repo"
    wt.mkdir()
    assert _sync.resolve_trunk(wt, workspace_default="develop") == "develop"


def test_default_main_when_neither_present(tmp_path):
    wt = tmp_path / "repo"
    wt.mkdir()
    assert _sync.resolve_trunk(wt, workspace_default=None) == "main"


def test_malformed_worktree_trunk_falls_through_to_workspace(tmp_path):
    # resolve_trunk falls back when parse_trunk_file returns None. This keeps
    # the resolver itself robust; the orchestrator handles the user-visible
    # `trunk-missing` outcome separately when a malformed file is observed.
    wt = tmp_path / "repo"
    wt.mkdir()
    (wt / "TRUNK.md").write_text("main # with comment\n")
    assert _sync.resolve_trunk(wt, workspace_default="develop") == "develop"


def test_malformed_worktree_trunk_surfaced_by_orchestrator(tmp_path):
    """End-to-end confirmation that a malformed TRUNK.md produces outcome=trunk-missing."""
    wt = tmp_path / "repo"
    wt.mkdir()
    (wt / ".git").write_text("gitdir: ../\n")
    (wt / "TRUNK.md").write_text("main # has comment here\n")

    worktree = _sync.Worktree(path=wt, repo="repo", branch="issue-42", trunk="main")
    result = _sync._process_worktree(worktree, workspace_default_trunk="develop", dry_run=False)
    assert result.outcome == "trunk-missing"
    assert result.message and "malformed TRUNK.md" in result.message
