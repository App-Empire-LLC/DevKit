"""T013 [US1]: `classify_clean_outcome` decision rules."""

from __future__ import annotations

from pathlib import Path

from aidevkit import sync as _sync
from aidevkit.util import RunResult


def test_before_equals_after_is_up_to_date(fake_run):
    wt = Path("/fake/wt")
    outcome, replayed = _sync.classify_clean_outcome(
        before_sha="a" * 40,
        after_sha="a" * 40,
        trunk_sha="b" * 40,
        worktree=wt,
    )
    assert outcome == "up-to-date"
    assert replayed is None


def test_rebased_with_replay_count(fake_run):
    wt = Path("/fake/wt")
    before = "a" * 40
    after = "c" * 40
    fake_run.script(
        ("git", "rev-list", "--count", f"{before}..{after}"),
        wt,
        RunResult(code=0, stdout="3\n", stderr=""),
    )
    outcome, replayed = _sync.classify_clean_outcome(
        before_sha=before,
        after_sha=after,
        trunk_sha="b" * 40,
        worktree=wt,
    )
    assert outcome == "rebased"
    assert replayed == 3
