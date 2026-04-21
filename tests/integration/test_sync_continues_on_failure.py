"""T032 [US3]: cmd_sync must process every worktree even when one fails."""
from __future__ import annotations

from aidevkit import sync as _sync


def test_all_worktrees_processed_even_when_one_fails(fake_workspace, monkeypatch, capsys):
    # Advance trunk on both; leave no local divergence → both should end up clean.
    fake_workspace.advance_trunk("RepoA", n=1, trunk="main")
    fake_workspace.advance_trunk("RepoB", n=1, trunk="main")

    # Simulate a broken remote on RepoA by deleting its origin. fetch will fail
    # for RepoA but should still continue to RepoB.
    origin_a = fake_workspace.origins["RepoA"]
    (origin_a / "HEAD").unlink()

    monkeypatch.chdir(fake_workspace.workspace_root)

    code = _sync.cmd_sync(json_output=True, dry_run=False)
    assert code == 21  # E_SYNC_PARTIAL

    import json as _json
    payload = _json.loads(capsys.readouterr().out)
    repos = [w["repo"] for w in payload["worktrees"]]
    assert repos == ["RepoA", "RepoB"]
    # RepoA fetch should have failed; RepoB should still have been processed.
    outcomes = {w["repo"]: w["outcome"] for w in payload["worktrees"]}
    assert outcomes["RepoA"] == "fetch-failed"
    assert outcomes["RepoB"] in {"rebased", "up-to-date", "fast-forwarded"}
