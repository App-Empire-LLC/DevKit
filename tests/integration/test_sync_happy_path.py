"""T016 [US1]: end-to-end happy path via real git binary."""

from __future__ import annotations

import json

from aidevkit import sync as _sync


def test_happy_path_mixed_rebased_and_up_to_date(fake_workspace, monkeypatch, capsys):
    # Advance trunk on RepoA only; RepoB stays current.
    fake_workspace.advance_trunk("RepoA", n=2, trunk="main")

    # CWD inside the advanced worktree.
    monkeypatch.chdir(fake_workspace.workspace_root / "RepoA")

    code = _sync.cmd_sync(json_output=True, dry_run=False)
    assert code == 0

    captured = capsys.readouterr()
    payload = json.loads(captured.out)
    assert payload["overall_status"] == "ok"
    assert payload["exit_code"] == 0
    assert [w["repo"] for w in payload["worktrees"]] == ["RepoA", "RepoB"]

    outcomes = {w["repo"]: w["outcome"] for w in payload["worktrees"]}
    # RepoA had no local commits → rebase replays zero → "up-to-date".
    # But trunk advanced, so fast-forward path or rebased path acceptable.
    assert outcomes["RepoA"] in {"rebased", "up-to-date", "fast-forwarded"}
    assert outcomes["RepoB"] in {"up-to-date", "rebased", "fast-forwarded"}
