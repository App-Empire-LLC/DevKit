"""T028 [US3]: conflict vs rebase-error based on rebase-state."""
from __future__ import annotations

from aidevkit import sync as _sync


def test_conflict_remediation_message_shape():
    r = _sync.WorktreeResult(
        repo="DevKit",
        path=__import__("pathlib").Path("/abs/ws/DevKit"),
        branch="issue-DevKit-11",
        trunk="main",
        outcome="conflict",
        behind_count=1,
        message=(
            "rebase left /abs/ws/DevKit in rebase-in-progress state. "
            "Resolve conflicts and run `git rebase --continue`, "
            "or `git rebase --abort` to back out."
        ),
    )
    assert "/abs/ws/DevKit" in (r.message or "")
    assert "git rebase --continue" in (r.message or "")
    assert "git rebase --abort" in (r.message or "")


def test_format_conflict_remediation_includes_path_and_commands():
    r = _sync.WorktreeResult(
        repo="RepoA",
        path=__import__("pathlib").Path("/abs/ws/RepoA"),
        branch="issue-RepoA-42",
        trunk="main",
        outcome="conflict",
        behind_count=2,
        message="rebase left worktree in in-progress state.",
    )
    text = _sync._format_conflict_remediation(r)
    assert "/abs/ws/RepoA" in text
    assert "git rebase --continue" in text
    assert "git rebase --abort" in text
