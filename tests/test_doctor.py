"""Tests for the doctor subcommand — all-present and some-missing cases."""
from __future__ import annotations

from pathlib import Path

import pytest
from typer.testing import CliRunner

from aidevkit.cli import app
from aidevkit.util import RunResult


@pytest.fixture
def runner(monkeypatch: pytest.MonkeyPatch) -> CliRunner:
    monkeypatch.setenv("NO_COLOR", "1")
    return CliRunner()


def _all_present_which(tmp_path: Path) -> "callable":
    # Stand-in path for every expected binary.
    fake = str(tmp_path / "bin" / "stub")

    def _which(name: str) -> str | None:
        if name in {"bash", "git", "gh", "jq"}:
            return fake
        return None

    return _which


def test_doctor_all_present(
    runner: CliRunner,
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    subprocess_capture,
) -> None:
    projects = tmp_path / "projects"
    worktrees = tmp_path / "worktrees"
    projects.mkdir()
    worktrees.mkdir()

    monkeypatch.setattr("aidevkit.doctor.shutil.which", _all_present_which(tmp_path))
    monkeypatch.setenv("APP_EMPIRE_PROJECTS", str(projects))
    monkeypatch.setenv("APP_EMPIRE_WORKTREES_HOME", str(worktrees))

    subprocess_capture.set_default(
        RunResult(code=0, stdout="", stderr="Logged in to github.com as test-user")
    )

    result = runner.invoke(app, ["doctor"])

    assert result.exit_code == 0
    assert "[ok]" in result.output
    assert "[FAIL]" not in result.output
    # The gh auth status call was routed through the seam, not to the real CLI:
    gh_calls = [c for c in subprocess_capture.calls if c["cmd"][:2] == ["gh", "auth"]]
    assert gh_calls, "expected doctor to invoke `gh auth status` via util.gh"


def test_doctor_reports_missing_binary(
    runner: CliRunner,
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    subprocess_capture,
) -> None:
    projects = tmp_path / "projects"
    worktrees = tmp_path / "worktrees"
    projects.mkdir()
    worktrees.mkdir()

    def _which_missing_jq(name: str) -> str | None:
        if name == "jq":
            return None
        if name in {"bash", "git", "gh"}:
            return str(tmp_path / "bin" / name)
        return None

    monkeypatch.setattr("aidevkit.doctor.shutil.which", _which_missing_jq)
    monkeypatch.setenv("APP_EMPIRE_PROJECTS", str(projects))
    monkeypatch.setenv("APP_EMPIRE_WORKTREES_HOME", str(worktrees))
    subprocess_capture.set_default(
        RunResult(code=0, stdout="", stderr="Logged in to github.com as test-user")
    )

    result = runner.invoke(app, ["doctor"])

    assert result.exit_code != 0
    assert "[FAIL]" in result.output
    assert "jq" in result.output


def test_doctor_reports_missing_env_var(
    runner: CliRunner,
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    subprocess_capture,
) -> None:
    worktrees = tmp_path / "worktrees"
    worktrees.mkdir()

    monkeypatch.setattr("aidevkit.doctor.shutil.which", _all_present_which(tmp_path))
    monkeypatch.delenv("APP_EMPIRE_PROJECTS", raising=False)
    monkeypatch.setenv("APP_EMPIRE_WORKTREES_HOME", str(worktrees))
    subprocess_capture.set_default(
        RunResult(code=0, stdout="", stderr="Logged in to github.com as test-user")
    )

    result = runner.invoke(app, ["doctor"])

    assert result.exit_code != 0
    assert "[FAIL]" in result.output
    assert "APP_EMPIRE_PROJECTS" in result.output


def test_doctor_reports_gh_not_authed(
    runner: CliRunner,
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    subprocess_capture,
) -> None:
    projects = tmp_path / "projects"
    worktrees = tmp_path / "worktrees"
    projects.mkdir()
    worktrees.mkdir()

    monkeypatch.setattr("aidevkit.doctor.shutil.which", _all_present_which(tmp_path))
    monkeypatch.setenv("APP_EMPIRE_PROJECTS", str(projects))
    monkeypatch.setenv("APP_EMPIRE_WORKTREES_HOME", str(worktrees))
    subprocess_capture.set_default(
        RunResult(code=1, stdout="", stderr="You are not logged in.")
    )

    result = runner.invoke(app, ["doctor"])

    assert result.exit_code != 0
    assert "[FAIL]" in result.output
    assert "gh auth" in result.output
