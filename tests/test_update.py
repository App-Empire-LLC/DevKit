"""Tests for `devkit update`."""
from __future__ import annotations

import pytest
from typer.testing import CliRunner

from aidevkit.cli import app
from aidevkit.util import E_DEP_MISSING, E_INSTALL_NOT_UV_TOOL, RunResult


@pytest.fixture
def runner(monkeypatch: pytest.MonkeyPatch) -> CliRunner:
    monkeypatch.setenv("NO_COLOR", "1")
    return CliRunner()


def test_update_not_manageable_exits_26(
    runner: CliRunner, subprocess_capture
) -> None:
    subprocess_capture.queue(RunResult(code=0, stdout="", stderr=""))
    subprocess_capture.queue(RunResult(code=1, stdout="", stderr="not found"))
    result = runner.invoke(app, ["update"])
    assert result.exit_code == E_INSTALL_NOT_UV_TOOL


def test_update_upgrade_then_doctor_success(
    runner: CliRunner, monkeypatch: pytest.MonkeyPatch
) -> None:
    call_counts: dict[str, int] = {"uv_tool_list": 0}

    def shell(cmd: list[str], **_: object) -> RunResult:
        if cmd[:3] == ["uv", "tool", "list"]:
            call_counts["uv_tool_list"] += 1
            # first call = before, second = after — pretend upgrade bumped to 0.3.1
            if call_counts["uv_tool_list"] == 1:
                return RunResult(code=0, stdout="aidevkit v0.3.0\n", stderr="")
            return RunResult(code=0, stdout="aidevkit v0.3.1\n", stderr="")
        if cmd[:3] == ["uv", "tool", "upgrade"]:
            return RunResult(code=0, stdout="Updated aidevkit v0.3.1\n", stderr="")
        # Doctor's git/gh checks — pretend all binaries/env present
        if cmd == ["gh", "auth", "status"]:
            return RunResult(
                code=0,
                stdout="",
                stderr="Logged in to github.com as ci\n",
            )
        return RunResult(code=0, stdout="", stderr="")

    monkeypatch.setattr("aidevkit.util.run", shell)
    # Doctor checks binaries via shutil.which and env vars
    monkeypatch.setattr("aidevkit.doctor.shutil.which", lambda n: "/bin/" + n)
    monkeypatch.setenv("APP_EMPIRE_PROJECTS", "/tmp")
    monkeypatch.setenv("APP_EMPIRE_WORKTREES_HOME", "/tmp")

    result = runner.invoke(app, ["update"])
    assert result.exit_code == 0, result.output
    assert "0.3.0 → 0.3.1" in result.output


def test_update_doctor_failure_propagates(
    runner: CliRunner, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Per FR-SELF-005: doctor failure must surface as non-zero exit; no rollback."""
    def shell(cmd: list[str], **_: object) -> RunResult:
        if cmd[:3] == ["uv", "tool", "list"]:
            return RunResult(code=0, stdout="aidevkit v0.3.0\n", stderr="")
        if cmd[:3] == ["uv", "tool", "upgrade"]:
            return RunResult(code=0, stdout="", stderr="")
        if cmd == ["gh", "auth", "status"]:
            return RunResult(code=1, stdout="", stderr="not authenticated")
        return RunResult(code=0, stdout="", stderr="")

    monkeypatch.setattr("aidevkit.util.run", shell)
    # Missing a required binary → doctor fails with E_DEP_MISSING
    monkeypatch.setattr(
        "aidevkit.doctor.shutil.which",
        lambda n: None if n == "jq" else "/bin/" + n,
    )
    monkeypatch.setenv("APP_EMPIRE_PROJECTS", "/tmp")
    monkeypatch.setenv("APP_EMPIRE_WORKTREES_HOME", "/tmp")

    result = runner.invoke(app, ["update"])
    assert result.exit_code == E_DEP_MISSING


def test_update_upgrade_failure_propagates(
    runner: CliRunner, monkeypatch: pytest.MonkeyPatch
) -> None:
    def shell(cmd: list[str], **_: object) -> RunResult:
        if cmd[:3] == ["uv", "tool", "list"]:
            return RunResult(code=0, stdout="aidevkit v0.3.0\n", stderr="")
        if cmd[:3] == ["uv", "tool", "upgrade"]:
            return RunResult(code=1, stdout="", stderr="network unreachable")
        return RunResult(code=0, stdout="", stderr="")

    monkeypatch.setattr("aidevkit.util.run", shell)
    result = runner.invoke(app, ["update"])
    assert result.exit_code == 1
