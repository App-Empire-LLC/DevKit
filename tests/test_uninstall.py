"""Tests for `devkit uninstall`."""
from __future__ import annotations

from pathlib import Path

import pytest
from typer.testing import CliRunner

from aidevkit import uninstall as uninstall_mod
from aidevkit.cli import app
from aidevkit.util import E_INSTALL_NOT_UV_TOOL, RunResult


@pytest.fixture
def runner(monkeypatch: pytest.MonkeyPatch) -> CliRunner:
    monkeypatch.setenv("NO_COLOR", "1")
    return CliRunner()


def _make_fake_commands_dir(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> tuple[Path, Path]:
    """Populate a fake home's `.claude/commands/` with a mix of relevant/irrelevant links."""
    home = tmp_path / "home"
    home.mkdir()
    monkeypatch.setattr("pathlib.Path.home", staticmethod(lambda: home))

    cmd_dir = home / ".claude" / "commands"
    cmd_dir.mkdir(parents=True)

    # Fake aidevkit install tree
    aidevkit_install = tmp_path / "install" / "aidevkit"
    (aidevkit_install / "commands").mkdir(parents=True)
    archive_md = aidevkit_install / "commands" / "devkit.archive.md"
    archive_md.write_text("archive")
    status_md = aidevkit_install / "commands" / "devkit.status.md"
    status_md.write_text("status")

    # Legitimate DevKit symlinks (matches /aidevkit/commands/ substring)
    (cmd_dir / "devkit.archive.md").symlink_to(archive_md)
    (cmd_dir / "devkit.status.md").symlink_to(status_md)

    # Unrelated symlink — must not be touched
    other = tmp_path / "other.md"
    other.write_text("other")
    (cmd_dir / "user.md").symlink_to(other)

    # Regular file — must not be touched
    (cmd_dir / "userfile.md").write_text("mine")

    return cmd_dir, aidevkit_install


def test_uninstall_not_uv_tool_exits_26(
    runner: CliRunner, subprocess_capture
) -> None:
    # detect_install_info: uv tool list returns nothing; pip show fails → unknown
    subprocess_capture.queue(RunResult(code=0, stdout="", stderr=""))
    subprocess_capture.queue(RunResult(code=1, stdout="", stderr="not found"))
    result = runner.invoke(app, ["uninstall"])
    assert result.exit_code == E_INSTALL_NOT_UV_TOOL


def test_uninstall_removes_symlinks_and_ignores_others(
    runner: CliRunner,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    cmd_dir, _install = _make_fake_commands_dir(tmp_path, monkeypatch)

    def shell(cmd: list[str], **_: object) -> RunResult:
        if cmd[:3] == ["uv", "tool", "list"]:
            return RunResult(code=0, stdout="aidevkit v0.3.0\n", stderr="")
        if cmd[:3] == ["uv", "tool", "uninstall"]:
            return RunResult(code=0, stdout="", stderr="")
        return RunResult(code=0, stdout="", stderr="")

    monkeypatch.setattr("aidevkit.util.run", shell)
    result = runner.invoke(app, ["uninstall"])
    assert result.exit_code == 0, result.output
    assert not (cmd_dir / "devkit.archive.md").exists()
    assert not (cmd_dir / "devkit.status.md").exists()
    # Unrelated symlink and regular file preserved
    assert (cmd_dir / "user.md").is_symlink()
    assert (cmd_dir / "userfile.md").is_file()


def test_uninstall_idempotent_already_gone(
    runner: CliRunner,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    cmd_dir, _install = _make_fake_commands_dir(tmp_path, monkeypatch)
    # Remove links first to simulate already-uninstalled state
    (cmd_dir / "devkit.archive.md").unlink()
    (cmd_dir / "devkit.status.md").unlink()

    def shell(cmd: list[str], **_: object) -> RunResult:
        if cmd[:3] == ["uv", "tool", "list"]:
            return RunResult(code=0, stdout="aidevkit v0.3.0\n", stderr="")
        if cmd[:3] == ["uv", "tool", "uninstall"]:
            return RunResult(code=1, stdout="", stderr="aidevkit is not installed")
        return RunResult(code=0, stdout="", stderr="")

    monkeypatch.setattr("aidevkit.util.run", shell)
    result = runner.invoke(app, ["uninstall"])
    assert result.exit_code == 0, result.output


def test_uninstall_is_non_interactive(
    runner: CliRunner,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    cmd_dir, _install = _make_fake_commands_dir(tmp_path, monkeypatch)

    def shell(cmd: list[str], **_: object) -> RunResult:
        if cmd[:3] == ["uv", "tool", "list"]:
            return RunResult(code=0, stdout="aidevkit v0.3.0\n", stderr="")
        if cmd[:3] == ["uv", "tool", "uninstall"]:
            return RunResult(code=0, stdout="", stderr="")
        return RunResult(code=0, stdout="", stderr="")

    monkeypatch.setattr("aidevkit.util.run", shell)
    # No stdin provided — command must still succeed without prompting.
    result = runner.invoke(app, ["uninstall"], input="")
    assert result.exit_code == 0, result.output


def test_devkit_symlinks_helper(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    cmd_dir, _install = _make_fake_commands_dir(tmp_path, monkeypatch)
    found = uninstall_mod._devkit_symlinks(cmd_dir)
    names = {p.name for p in found}
    assert names == {"devkit.archive.md", "devkit.status.md"}
