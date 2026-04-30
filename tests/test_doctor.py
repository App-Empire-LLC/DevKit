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


def _seed_devkit(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> dict:
    """Seed a valid .devkit/ + worktrees dir, set $PROJECTS_HOME, mock HOME."""
    projects = tmp_path / "projects"
    worktrees = tmp_path / "worktrees"
    fake_home = tmp_path / "fake-home"
    projects.mkdir()
    worktrees.mkdir()
    fake_home.mkdir()
    devkit_dir = projects / ".devkit"
    devkit_dir.mkdir()
    (devkit_dir / "config.yaml").write_text(
        f"version: 1\norg: TestOrg\nworkspaces_home: {worktrees}\n"
    )
    (devkit_dir / "PROJECTS.md").write_text(
        "# Projects\n\n"
        "| name | git_url | description |\n|------|---------|-------------|\n"
        "| repo | git@github.com:TestOrg/repo.git | r |\n"
    )
    monkeypatch.setenv("PROJECTS_HOME", str(projects))
    monkeypatch.setattr("pathlib.Path.home", classmethod(lambda cls: fake_home))
    monkeypatch.setattr(
        "aidevkit.config._GLOBAL_CONFIG_PATH", fake_home / ".devkit" / "config.yaml"
    )
    return {"projects": projects, "worktrees": worktrees, "fake_home": fake_home}


def test_doctor_all_present(
    runner: CliRunner,
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    subprocess_capture,
) -> None:
    _seed_devkit(tmp_path, monkeypatch)
    monkeypatch.setattr("aidevkit.doctor.shutil.which", _all_present_which(tmp_path))
    subprocess_capture.set_default(
        RunResult(code=0, stdout="", stderr="Logged in to github.com as test-user")
    )

    result = runner.invoke(app, ["doctor"])

    assert result.exit_code == 0, result.output
    assert "[ok]" in result.output
    assert "[FAIL]" not in result.output
    gh_calls = [c for c in subprocess_capture.calls if c["cmd"][:2] == ["gh", "auth"]]
    assert gh_calls, "expected doctor to invoke `gh auth status` via util.gh"


def test_doctor_reports_missing_binary(
    runner: CliRunner,
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    subprocess_capture,
) -> None:
    _seed_devkit(tmp_path, monkeypatch)

    def _which_missing_jq(name: str) -> str | None:
        if name == "jq":
            return None
        if name in {"bash", "git", "gh"}:
            return str(tmp_path / "bin" / name)
        return None

    monkeypatch.setattr("aidevkit.doctor.shutil.which", _which_missing_jq)
    subprocess_capture.set_default(
        RunResult(code=0, stdout="", stderr="Logged in to github.com as test-user")
    )

    result = runner.invoke(app, ["doctor"])

    assert result.exit_code != 0
    assert "[FAIL]" in result.output
    assert "jq" in result.output


def test_doctor_reports_missing_projects_home(
    runner: CliRunner,
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    subprocess_capture,
) -> None:
    """DevKit#37: doctor checks $PROJECTS_HOME resolution, not $APP_EMPIRE_*."""
    fake_home = tmp_path / "fake-home"
    fake_home.mkdir()
    monkeypatch.delenv("PROJECTS_HOME", raising=False)
    monkeypatch.setattr("pathlib.Path.home", classmethod(lambda cls: fake_home))
    monkeypatch.setattr(
        "aidevkit.config._GLOBAL_CONFIG_PATH", fake_home / ".devkit" / "config.yaml"
    )
    monkeypatch.setattr("aidevkit.doctor.shutil.which", _all_present_which(tmp_path))
    subprocess_capture.set_default(
        RunResult(code=0, stdout="", stderr="Logged in to github.com as test-user")
    )

    result = runner.invoke(app, ["doctor"])

    assert result.exit_code != 0
    assert "[FAIL]" in result.output
    assert "PROJECTS_HOME" in result.output


def test_doctor_reports_invalid_config(
    runner: CliRunner,
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    subprocess_capture,
) -> None:
    """DevKit#37: doctor surfaces config schema failures."""
    seeded = _seed_devkit(tmp_path, monkeypatch)
    # Break the config: workspaces_home points at a nonexistent path.
    (seeded["projects"] / ".devkit" / "config.yaml").write_text(
        "version: 1\norg: TestOrg\nworkspaces_home: /no-such-dir-xyz\n"
    )
    monkeypatch.setattr("aidevkit.doctor.shutil.which", _all_present_which(tmp_path))
    subprocess_capture.set_default(
        RunResult(code=0, stdout="", stderr="Logged in to github.com as test-user")
    )

    result = runner.invoke(app, ["doctor"])

    assert result.exit_code != 0
    assert "[FAIL]" in result.output
    assert ".devkit/config.yaml" in result.output


def test_doctor_no_longer_checks_app_empire_envs(
    runner: CliRunner,
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    subprocess_capture,
) -> None:
    """FR-003: doctor must not error when $APP_EMPIRE_* envs are unset."""
    _seed_devkit(tmp_path, monkeypatch)
    monkeypatch.delenv("APP_EMPIRE_PROJECTS", raising=False)
    monkeypatch.delenv("APP_EMPIRE_WORKTREES_HOME", raising=False)
    monkeypatch.setattr("aidevkit.doctor.shutil.which", _all_present_which(tmp_path))
    subprocess_capture.set_default(
        RunResult(code=0, stdout="", stderr="Logged in to github.com as test-user")
    )

    result = runner.invoke(app, ["doctor"])

    assert result.exit_code == 0, result.output
    assert "APP_EMPIRE" not in result.output


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
