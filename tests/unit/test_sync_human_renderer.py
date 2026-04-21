"""T033 [US3]: human renderer surfaces conflict remediation on indented lines."""
from __future__ import annotations

from pathlib import Path

from aidevkit import sync as _sync


def test_render_human_conflict_contains_remediation(capsys, monkeypatch):
    # util.info prints via `out` which writes to stdout; capsys captures stdout.
    # Console soft-wraps so we need to confirm substring presence, not exact lines.
    report = _sync.SyncReport(
        workspace_root=Path("/abs/ws"),
        overall_status="partial",
        exit_code=21,
        worktrees=[
            _sync.WorktreeResult(
                repo="RepoA",
                path=Path("/abs/ws/RepoA"),
                branch="issue-RepoA-42",
                trunk="main",
                outcome="conflict",
                behind_count=1,
                message="rebase left /abs/ws/RepoA in rebase-in-progress state.",
            ),
        ],
    )
    _sync._render_human(report)
    captured = capsys.readouterr().out
    assert "conflict" in captured
    assert "/abs/ws/RepoA" in captured
    assert "git rebase --continue" in captured
    assert "git rebase --abort" in captured
    assert "1 worktree" in captured  # attention line
