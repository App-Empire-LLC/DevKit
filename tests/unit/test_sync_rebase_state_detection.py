"""T027 [US3]: `detect_rebase_state` interprets rebase-merge/-apply presence."""
from __future__ import annotations

from aidevkit import sync as _sync
from aidevkit.util import RunResult


def test_detect_rebase_merge(fake_run, tmp_path):
    wt = tmp_path / "wt"
    wt.mkdir()
    merge = wt / ".git" / "rebase-merge"
    merge.mkdir(parents=True)
    fake_run.script(
        ("git", "rev-parse", "--git-path", "rebase-merge"),
        wt,
        RunResult(code=0, stdout=f"{merge}\n", stderr=""),
    )
    assert _sync.detect_rebase_state(wt) == "merge"


def test_detect_rebase_apply(fake_run, tmp_path):
    wt = tmp_path / "wt"
    wt.mkdir()
    apply_dir = wt / ".git" / "rebase-apply"
    apply_dir.mkdir(parents=True)
    fake_run.script(
        ("git", "rev-parse", "--git-path", "rebase-merge"),
        wt,
        RunResult(code=0, stdout=f"{wt}/.git/rebase-merge\n", stderr=""),
    )
    fake_run.script(
        ("git", "rev-parse", "--git-path", "rebase-apply"),
        wt,
        RunResult(code=0, stdout=f"{apply_dir}\n", stderr=""),
    )
    assert _sync.detect_rebase_state(wt) == "apply"


def test_detect_rebase_none(fake_run, tmp_path):
    wt = tmp_path / "wt"
    wt.mkdir()
    (wt / ".git").mkdir()
    fake_run.script(
        ("git", "rev-parse", "--git-path", "rebase-merge"),
        wt,
        RunResult(code=0, stdout=f"{wt}/.git/rebase-merge\n", stderr=""),
    )
    fake_run.script(
        ("git", "rev-parse", "--git-path", "rebase-apply"),
        wt,
        RunResult(code=0, stdout=f"{wt}/.git/rebase-apply\n", stderr=""),
    )
    assert _sync.detect_rebase_state(wt) == "none"
