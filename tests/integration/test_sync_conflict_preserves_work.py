"""T029 [US3]: a conflicting worktree is left in rebase-in-progress state, the
other worktree syncs normally, and the user's pre-sync HEAD is recoverable
via `git rebase --abort` (SC-003)."""
from __future__ import annotations

import json
import subprocess

from aidevkit import sync as _sync


def _git(*args, cwd):
    return subprocess.run(
        ["git", *args], cwd=cwd, capture_output=True, text=True, check=False
    )


def test_conflict_preserves_work(fake_workspace, monkeypatch, capsys):
    # Make RepoA's issue branch conflict with an advanced trunk.
    fake_workspace.commit_on_worktree(
        "RepoA", "CONFLICT.txt", "branch side\n", "branch side of conflict"
    )
    fake_workspace.make_conflicting_commit("RepoA", trunk="main")

    # Capture pre-sync HEAD for later recovery check.
    pre_sync_head = _git(
        "rev-parse", "HEAD", cwd=fake_workspace.workspace_root / "RepoA"
    ).stdout.strip()
    assert pre_sync_head

    # RepoB stays clean.
    fake_workspace.advance_trunk("RepoB", n=1, trunk="main")

    monkeypatch.chdir(fake_workspace.workspace_root)
    code = _sync.cmd_sync(json_output=True, dry_run=False)
    assert code == 21

    payload = json.loads(capsys.readouterr().out)
    outcomes = {w["repo"]: w for w in payload["worktrees"]}

    assert outcomes["RepoA"]["outcome"] == "conflict"
    msg = outcomes["RepoA"]["message"]
    assert "git rebase --continue" in msg
    assert "git rebase --abort" in msg
    assert str(fake_workspace.workspace_root / "RepoA") in msg

    assert outcomes["RepoB"]["outcome"] in {"rebased", "up-to-date", "fast-forwarded"}

    # Verify the conflicting worktree has a rebase-in-progress directory.
    worktree_a = fake_workspace.workspace_root / "RepoA"
    git_dir = _git("rev-parse", "--git-path", "rebase-merge", cwd=worktree_a).stdout.strip()
    from pathlib import Path
    probe = Path(git_dir)
    if not probe.is_absolute():
        probe = worktree_a / probe
    assert probe.exists(), f"expected rebase-merge state at {probe}"

    # Abort the rebase — user's pre-sync HEAD must be recoverable.
    abort = _git("rebase", "--abort", cwd=worktree_a)
    assert abort.returncode == 0, abort.stderr

    post_abort_head = _git("rev-parse", "HEAD", cwd=worktree_a).stdout.strip()
    assert post_abort_head == pre_sync_head, "abort must restore pre-sync HEAD (SC-003)"
