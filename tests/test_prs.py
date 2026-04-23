"""Tests for the shared `_prs` helpers."""
from __future__ import annotations

import json
from pathlib import Path

from aidevkit import _prs
from aidevkit.util import RunResult


def test_check_prs_merged_all_merged_returns_empty(subprocess_capture) -> None:
    subprocess_capture.queue(
        RunResult(
            code=0,
            stdout=json.dumps([{"number": 1, "state": "MERGED", "url": "https://x/1"}]),
            stderr="",
        )
    )
    blockers = _prs.check_prs_merged(
        [("owner/Repo", Path("/tmp"))], "issue-Repo-1"
    )
    assert blockers == []


def test_check_prs_merged_open_is_blocker(subprocess_capture) -> None:
    subprocess_capture.queue(
        RunResult(
            code=0,
            stdout=json.dumps([{"number": 2, "state": "OPEN", "url": "https://x/2"}]),
            stderr="",
        )
    )
    blockers = _prs.check_prs_merged(
        [("owner/Repo", Path("/tmp"))], "issue-Repo-1"
    )
    assert len(blockers) == 1
    assert "#2" in blockers[0] and "OPEN" in blockers[0]


def test_check_prs_merged_gh_failure_is_blocker(subprocess_capture) -> None:
    subprocess_capture.queue(RunResult(code=1, stdout="", stderr="boom"))
    blockers = _prs.check_prs_merged(
        [("owner/Repo", Path("/tmp"))], "issue-Repo-1"
    )
    assert len(blockers) == 1
    assert "failed to query PRs" in blockers[0]


def test_check_prs_merged_unparseable_is_blocker(subprocess_capture) -> None:
    subprocess_capture.queue(RunResult(code=0, stdout="not json", stderr=""))
    blockers = _prs.check_prs_merged(
        [("owner/Repo", Path("/tmp"))], "issue-Repo-1"
    )
    assert len(blockers) == 1
    assert "unparseable" in blockers[0]


def test_prs_for_branch_normalizes_states(subprocess_capture) -> None:
    subprocess_capture.queue(
        RunResult(
            code=0,
            stdout=json.dumps(
                [
                    {"number": 10, "state": "MERGED", "url": "https://x/10"},
                    {"number": 11, "state": "OPEN", "url": "https://x/11"},
                    {"number": 12, "state": "CLOSED", "url": "https://x/12"},
                ]
            ),
            stderr="",
        )
    )
    result = _prs.prs_for_branch(
        [("owner/Repo", Path("/tmp"))], "issue-Repo-1"
    )
    assert set(result.keys()) == {"owner/Repo"}
    prs = result["owner/Repo"]
    states = {pr.number: pr.state for pr in prs}
    assert states == {10: "merged", 11: "open", 12: "closed"}


def test_prs_for_branch_gh_failure_yields_empty_list(subprocess_capture) -> None:
    subprocess_capture.queue(RunResult(code=1, stdout="", stderr="boom"))
    result = _prs.prs_for_branch(
        [("owner/Repo", Path("/tmp"))], "issue-Repo-1"
    )
    assert result == {"owner/Repo": []}


def test_prs_for_branch_multiple_repos(subprocess_capture) -> None:
    subprocess_capture.queue(
        RunResult(code=0, stdout=json.dumps([
            {"number": 1, "state": "MERGED", "url": "https://x/1"},
        ]), stderr="")
    )
    subprocess_capture.queue(
        RunResult(code=0, stdout=json.dumps([]), stderr="")
    )
    result = _prs.prs_for_branch(
        [
            ("owner/A", Path("/tmp/a")),
            ("owner/B", Path("/tmp/b")),
        ],
        "issue-A-1",
    )
    assert list(result.keys()) == ["owner/A", "owner/B"]
    assert len(result["owner/A"]) == 1
    assert result["owner/A"][0].state == "merged"
    assert result["owner/B"] == []
