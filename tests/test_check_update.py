"""Tests for `devkit check-update`."""
from __future__ import annotations

import json

import pytest
from typer.testing import CliRunner

from aidevkit.cli import app
from aidevkit.util import E_CHECK_UPDATE_INDEX_UNAVAILABLE, RunResult


@pytest.fixture
def runner(monkeypatch: pytest.MonkeyPatch) -> CliRunner:
    monkeypatch.setenv("NO_COLOR", "1")
    return CliRunner()


def test_check_update_update_available(
    runner: CliRunner, monkeypatch: pytest.MonkeyPatch
) -> None:
    def shell(cmd: list[str], **_: object) -> RunResult:
        if cmd[:3] == ["uv", "tool", "list"]:
            return RunResult(code=0, stdout="aidevkit v0.2.0\n", stderr="")
        if cmd[:4] == ["uv", "tool", "upgrade", "--dry-run"]:
            return RunResult(
                code=0, stdout="Would install aidevkit==0.3.0\n", stderr=""
            )
        return RunResult(code=0, stdout="", stderr="")

    monkeypatch.setattr("aidevkit.util.run", shell)
    result = runner.invoke(app, ["check-update"])
    assert result.exit_code == 0, result.output
    assert "0.2.0 → 0.3.0" in result.output


def test_check_update_up_to_date(
    runner: CliRunner, monkeypatch: pytest.MonkeyPatch
) -> None:
    def shell(cmd: list[str], **_: object) -> RunResult:
        if cmd[:3] == ["uv", "tool", "list"]:
            return RunResult(code=0, stdout="aidevkit v0.3.0\n", stderr="")
        if cmd[:4] == ["uv", "tool", "upgrade", "--dry-run"]:
            return RunResult(code=0, stdout="aidevkit is up to date\n", stderr="")
        return RunResult(code=0, stdout="", stderr="")

    monkeypatch.setattr("aidevkit.util.run", shell)
    result = runner.invoke(app, ["check-update"])
    assert result.exit_code == 0, result.output
    assert "up to date" in result.output.lower()


def test_check_update_parse_failure_exits_27(
    runner: CliRunner, monkeypatch: pytest.MonkeyPatch
) -> None:
    def shell(cmd: list[str], **_: object) -> RunResult:
        if cmd[:3] == ["uv", "tool", "list"]:
            return RunResult(code=0, stdout="aidevkit v0.3.0\n", stderr="")
        if cmd[:4] == ["uv", "tool", "upgrade", "--dry-run"]:
            return RunResult(
                code=1, stdout="", stderr="error: index unreachable\n"
            )
        return RunResult(code=0, stdout="", stderr="")

    monkeypatch.setattr("aidevkit.util.run", shell)
    result = runner.invoke(app, ["check-update"])
    assert result.exit_code == E_CHECK_UPDATE_INDEX_UNAVAILABLE


def test_check_update_json_output_shape(
    runner: CliRunner, monkeypatch: pytest.MonkeyPatch
) -> None:
    def shell(cmd: list[str], **_: object) -> RunResult:
        if cmd[:3] == ["uv", "tool", "list"]:
            return RunResult(code=0, stdout="aidevkit v0.2.0\n", stderr="")
        if cmd[:4] == ["uv", "tool", "upgrade", "--dry-run"]:
            return RunResult(
                code=0, stdout="Would install aidevkit==0.3.0\n", stderr=""
            )
        return RunResult(code=0, stdout="", stderr="")

    monkeypatch.setattr("aidevkit.util.run", shell)
    result = runner.invoke(app, ["check-update", "--json"])
    assert result.exit_code == 0, result.output
    payload = json.loads(result.output)
    assert payload == {
        "installed": "0.2.0",
        "latest": "0.3.0",
        "update_available": True,
        "unresolvable_reason": None,
    }
