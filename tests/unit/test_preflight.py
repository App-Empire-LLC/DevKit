"""Unit tests for `devkit preflight` (DevKit#27 US2).

Preflight detects whether the current issue branch is behind origin/main.
Detect-only — MUST NOT rebase, merge, reset, or mutate any ref outside of
`refs/remotes/origin/*` via fetch.
"""

from __future__ import annotations

import pytest
from typer.testing import CliRunner

from aidevkit.cli import app
from aidevkit.util import E_BEHIND_ORIGIN, E_PREFLIGHT_FAILED, RunResult


@pytest.fixture
def runner(monkeypatch: pytest.MonkeyPatch) -> CliRunner:
    monkeypatch.setenv("NO_COLOR", "1")
    return CliRunner()


def _script_happy_preflight(fake_run, behind_rev_list_stdout: str = "0\n") -> None:
    """Script the three shell calls preflight makes, plus the behind_count
    rev-list that `aidevkit.sync.behind_count` routes through the same seam."""
    fake_run.script_any_cwd(
        ("git", "rev-parse", "--is-inside-work-tree"),
        RunResult(code=0, stdout="true\n", stderr=""),
    )
    fake_run.script_any_cwd(
        ("git", "fetch", "origin"),
        RunResult(code=0, stdout="", stderr=""),
    )
    fake_run.script_any_cwd(
        ("git", "rev-parse", "--verify", "--quiet", "refs/remotes/origin/main"),
        RunResult(code=0, stdout="abc123\n", stderr=""),
    )
    fake_run.script_any_cwd(
        ("git", "rev-list", "--count", "HEAD..origin/main"),
        RunResult(code=0, stdout=behind_rev_list_stdout, stderr=""),
    )


# --- T015: up-to-date exits zero --------------------------------------------


def test_preflight_up_to_date_exits_zero(fake_run, runner: CliRunner) -> None:
    _script_happy_preflight(fake_run, behind_rev_list_stdout="0\n")
    result = runner.invoke(app, ["preflight"])
    assert result.exit_code == 0, result.output
    assert "up-to-date" in result.output


# --- T016: behind exits E_BEHIND_ORIGIN with count --------------------------


def test_preflight_behind_exits_nonzero_with_count(fake_run, runner: CliRunner) -> None:
    _script_happy_preflight(fake_run, behind_rev_list_stdout="3\n")
    result = runner.invoke(app, ["preflight"])
    assert result.exit_code == E_BEHIND_ORIGIN, result.output
    assert "behind origin/main by 3 commits" in result.output
    assert "rebase or merge manually" in result.output


# --- T017: fetch failure exits E_PREFLIGHT_FAILED ---------------------------


def test_preflight_fetch_failure(fake_run, runner: CliRunner) -> None:
    fake_run.script_any_cwd(
        ("git", "rev-parse", "--is-inside-work-tree"),
        RunResult(code=0, stdout="true\n", stderr=""),
    )
    fake_run.script_any_cwd(
        ("git", "fetch", "origin"),
        RunResult(
            code=128,
            stdout="",
            stderr="fatal: could not read from remote repository",
        ),
    )
    result = runner.invoke(app, ["preflight"])
    assert result.exit_code == E_PREFLIGHT_FAILED, result.output
    assert "fetch origin failed" in result.output


# --- T018: missing origin/main exits E_PREFLIGHT_FAILED ---------------------


def test_preflight_no_origin_main(fake_run, runner: CliRunner) -> None:
    fake_run.script_any_cwd(
        ("git", "rev-parse", "--is-inside-work-tree"),
        RunResult(code=0, stdout="true\n", stderr=""),
    )
    fake_run.script_any_cwd(
        ("git", "fetch", "origin"),
        RunResult(code=0, stdout="", stderr=""),
    )
    fake_run.script_any_cwd(
        ("git", "rev-parse", "--verify", "--quiet", "refs/remotes/origin/main"),
        RunResult(code=1, stdout="", stderr=""),
    )
    result = runner.invoke(app, ["preflight"])
    assert result.exit_code == E_PREFLIGHT_FAILED, result.output
    assert "origin/main not found" in result.output


# --- T019: preflight emits no mutating verbs --------------------------------


def test_preflight_no_mutations(fake_run, runner: CliRunner) -> None:
    """Run preflight in each of its four outcomes and inspect every call
    captured by fake_run. No mutating git verb (rebase, merge, reset, push,
    branch -D, update-ref) and no --force* flag may appear anywhere."""

    def _run_all_outcomes() -> None:
        # Clear calls between runs to keep assertions focused.
        fake_run.calls.clear()
        fake_run.scripts.clear()

        # (a) up-to-date
        _script_happy_preflight(fake_run, behind_rev_list_stdout="0\n")
        runner.invoke(app, ["preflight"])

        # (b) behind
        fake_run.calls.clear()
        fake_run.scripts.clear()
        _script_happy_preflight(fake_run, behind_rev_list_stdout="4\n")
        runner.invoke(app, ["preflight"])

        # (c) fetch failure
        fake_run.calls.clear()
        fake_run.scripts.clear()
        fake_run.script_any_cwd(
            ("git", "rev-parse", "--is-inside-work-tree"),
            RunResult(code=0, stdout="true\n", stderr=""),
        )
        fake_run.script_any_cwd(
            ("git", "fetch", "origin"),
            RunResult(code=128, stdout="", stderr="fatal"),
        )
        runner.invoke(app, ["preflight"])

    _run_all_outcomes()

    forbidden_verbs = {"rebase", "merge", "reset", "push", "tag", "reflog", "stash"}
    for cmd, _cwd in fake_run.calls:
        # cmd is a tuple of strings
        assert cmd[:1] == ("git",), f"non-git call observed: {cmd}"
        # No branch -D (branch deletion); branch reads are allowed but preflight shouldn't run any.
        if cmd[:2] == ("git", "branch"):
            assert "-D" not in cmd and "-d" not in cmd, f"branch deletion forbidden: {cmd}"
        # No update-ref (writes a ref directly).
        assert cmd[:2] != ("git", "update-ref"), f"update-ref forbidden: {cmd}"
        # No mutating top-level verb.
        if len(cmd) >= 2:
            assert cmd[1] not in forbidden_verbs, f"forbidden verb: {cmd}"
        # No --force* flag anywhere.
        for tok in cmd:
            assert not tok.startswith("--force"), f"forbidden --force flag: {cmd}"


# --- T020: outside-worktree exits E_PREFLIGHT_FAILED (both shapes) ----------


def test_preflight_outside_worktree_nonzero_exit(fake_run, runner: CliRunner) -> None:
    """Shape 1: git returns non-zero exit (not a git dir at all)."""
    fake_run.script_any_cwd(
        ("git", "rev-parse", "--is-inside-work-tree"),
        RunResult(code=128, stdout="", stderr="fatal: not a git repository"),
    )
    result = runner.invoke(app, ["preflight"])
    assert result.exit_code == E_PREFLIGHT_FAILED, result.output
    assert "not inside a git worktree" in result.output


def test_preflight_outside_worktree_false_stdout(fake_run, runner: CliRunner) -> None:
    """Shape 2 (analysis U1): git returns exit 0 but stdout is "false"
    (possible when cwd is under `.git/` itself)."""
    fake_run.script_any_cwd(
        ("git", "rev-parse", "--is-inside-work-tree"),
        RunResult(code=0, stdout="false\n", stderr=""),
    )
    result = runner.invoke(app, ["preflight"])
    assert result.exit_code == E_PREFLIGHT_FAILED, result.output
    assert "not inside a git worktree" in result.output
