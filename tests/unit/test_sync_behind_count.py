"""T014 [US1]: `behind_count` surface for DevKit#27 consumer."""

from __future__ import annotations

from pathlib import Path

from aidevkit import sync as _sync
from aidevkit.util import RunResult


def test_behind_count_returns_integer(fake_run):
    wt = Path("/fake/wt")
    fake_run.script(
        ("git", "rev-list", "--count", "HEAD..origin/main"),
        wt,
        RunResult(code=0, stdout="7\n", stderr=""),
    )
    assert _sync.behind_count(wt, "main") == 7


def test_behind_count_zero_when_range_empty(fake_run):
    wt = Path("/fake/wt")
    fake_run.script(
        ("git", "rev-list", "--count", "HEAD..origin/main"),
        wt,
        RunResult(code=0, stdout="0\n", stderr=""),
    )
    assert _sync.behind_count(wt, "main") == 0


def test_behind_count_zero_on_git_error(fake_run):
    wt = Path("/fake/wt")
    fake_run.script(
        ("git", "rev-list", "--count", "HEAD..origin/main"),
        wt,
        RunResult(code=128, stdout="", stderr="fatal: unknown revision"),
    )
    assert _sync.behind_count(wt, "main") == 0
