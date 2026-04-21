"""T012 [US1]: `is_dirty` via `git diff --quiet HEAD` exit-code semantics."""
from __future__ import annotations

from pathlib import Path

import pytest

from aidevkit import sync as _sync
from aidevkit.util import RunResult


def test_clean_when_diff_exits_zero(fake_run):
    wt = Path("/fake/wt")
    fake_run.script(
        ("git", "diff", "--quiet", "HEAD"),
        wt,
        RunResult(code=0, stdout="", stderr=""),
    )
    assert _sync.is_dirty(wt) is False


def test_dirty_when_diff_exits_one(fake_run):
    wt = Path("/fake/wt")
    fake_run.script(
        ("git", "diff", "--quiet", "HEAD"),
        wt,
        RunResult(code=1, stdout="", stderr=""),
    )
    assert _sync.is_dirty(wt) is True


def test_git_error_does_not_silently_claim_clean(fake_run):
    wt = Path("/fake/wt")
    fake_run.script(
        ("git", "diff", "--quiet", "HEAD"),
        wt,
        RunResult(code=128, stdout="", stderr="fatal: something"),
    )
    with pytest.raises(RuntimeError):
        _sync.is_dirty(wt)
