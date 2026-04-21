"""T038 [US2]: TRUNK.md precedence resolved against real git + real origins."""
from __future__ import annotations

import json

from aidevkit import sync as _sync


def test_worktree_trunk_overrides_workspace_trunk(fake_workspace, monkeypatch, capsys):
    # Workspace default: develop. RepoA overrides to master.
    fake_workspace.write_trunk_md("workspace", "develop")
    fake_workspace.write_trunk_md("RepoA", "master")
    fake_workspace.advance_trunk("RepoA", n=1, trunk="master")
    fake_workspace.advance_trunk("RepoB", n=1, trunk="develop")

    monkeypatch.chdir(fake_workspace.workspace_root)
    code = _sync.cmd_sync(json_output=True, dry_run=False)
    assert code == 0

    payload = json.loads(capsys.readouterr().out)
    by_repo = {w["repo"]: w for w in payload["worktrees"]}
    assert by_repo["RepoA"]["trunk"] == "master"
    assert by_repo["RepoB"]["trunk"] == "develop"
    assert by_repo["RepoA"]["outcome"] in {"rebased", "up-to-date", "fast-forwarded"}
    assert by_repo["RepoB"]["outcome"] in {"rebased", "up-to-date", "fast-forwarded"}


def test_malformed_trunk_md_produces_trunk_missing(fake_workspace, monkeypatch, capsys):
    (fake_workspace.workspace_root / "RepoA" / "TRUNK.md").write_text(
        "main # inline comment that breaks the grammar\n"
    )
    # RepoB is clean.
    monkeypatch.chdir(fake_workspace.workspace_root)
    code = _sync.cmd_sync(json_output=True, dry_run=False)
    assert code == 21

    payload = json.loads(capsys.readouterr().out)
    by_repo = {w["repo"]: w for w in payload["worktrees"]}
    assert by_repo["RepoA"]["outcome"] == "trunk-missing"
    assert "malformed TRUNK.md" in by_repo["RepoA"]["message"]
    assert by_repo["RepoB"]["outcome"] in {"rebased", "up-to-date", "fast-forwarded"}
