"""Integration test for `devkit purge`: real filesystem, mixed marker states."""
from __future__ import annotations

import datetime
import subprocess
from pathlib import Path

import pytest

from aidevkit import purge as purge_mod
from aidevkit.util import RunResult


def _real_run(cmd: list[str], *, check: bool = False, cwd: Path | None = None) -> RunResult:
    proc = subprocess.run(
        cmd, cwd=cwd, capture_output=True, text=True, check=check,
    )
    return RunResult(code=proc.returncode, stdout=proc.stdout, stderr=proc.stderr)


def test_purge_mixed_marker_states_real_fs(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    home = tmp_path / "home"
    home.mkdir()
    archived = home / "_archived"
    archived.mkdir()

    old = archived / "OldDir"
    old.mkdir()
    old_ts = (datetime.datetime.now(datetime.UTC) - datetime.timedelta(days=60))
    (old / ".devkit-archived").write_text(
        old_ts.strftime("%Y-%m-%dT%H:%M:%SZ") + "\n"
    )
    (old / "some-file.txt").write_text("content")

    young = archived / "YoungDir"
    young.mkdir()
    young_ts = (datetime.datetime.now(datetime.UTC) - datetime.timedelta(days=5))
    (young / ".devkit-archived").write_text(
        young_ts.strftime("%Y-%m-%dT%H:%M:%SZ") + "\n"
    )

    no_marker = archived / "NoMarker"
    no_marker.mkdir()
    (no_marker / "file.txt").write_text("x")

    active = home / "Active-issue-1"
    active.mkdir()

    monkeypatch.setenv("APP_EMPIRE_WORKTREES_HOME", str(home))
    monkeypatch.setattr("aidevkit.util.run", _real_run)

    exit_code = purge_mod.cmd_purge(days=30, yes=True)
    assert exit_code == 0

    assert not old.exists(), "old marker-present dir should be deleted"
    assert young.exists(), "young dir should be preserved"
    assert no_marker.exists(), "no-marker dir must never be touched"
    assert active.exists(), "active workspace must never be touched"
