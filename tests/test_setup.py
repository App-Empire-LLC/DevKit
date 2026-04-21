"""Tests for the setup subcommand — doctor ordering and symlink targets."""
from __future__ import annotations

from pathlib import Path

import pytest
from typer.testing import CliRunner

from aidevkit.cli import app


@pytest.fixture
def runner(monkeypatch: pytest.MonkeyPatch) -> CliRunner:
    monkeypatch.setenv("NO_COLOR", "1")
    return CliRunner()


def test_setup_invokes_doctor_first(
    runner: CliRunner,
    monkeypatch: pytest.MonkeyPatch,
    tmp_workspace: Path,
) -> None:
    order: list[str] = []

    def fake_doctor() -> int:
        order.append("doctor")
        return 0

    from aidevkit import setup as setup_module

    monkeypatch.setattr(setup_module.doctor, "cmd_doctor", fake_doctor)
    monkeypatch.setenv("HOME", str(tmp_workspace))

    # Wrap the symlink step so we can assert doctor ran before any link work.
    original_link = Path.symlink_to

    def recording_symlink(self: Path, target, target_is_directory: bool = False) -> None:
        order.append(f"link:{self.name}")
        return original_link(self, target, target_is_directory)

    monkeypatch.setattr(Path, "symlink_to", recording_symlink)

    result = runner.invoke(app, ["setup"])
    assert result.exit_code == 0, result.output
    assert order[0] == "doctor", f"doctor must run first, got order: {order}"


def test_setup_creates_symlinks_under_fake_home(
    runner: CliRunner,
    monkeypatch: pytest.MonkeyPatch,
    tmp_workspace: Path,
) -> None:
    from aidevkit import setup as setup_module

    monkeypatch.setattr(setup_module.doctor, "cmd_doctor", lambda: 0)
    monkeypatch.setenv("HOME", str(tmp_workspace))

    result = runner.invoke(app, ["setup"])
    assert result.exit_code == 0, result.output

    cmd_dir = tmp_workspace / ".claude" / "commands"
    assert cmd_dir.is_dir()
    linked = list(cmd_dir.iterdir())
    assert linked, "setup should have created at least one symlink"
    linked_names = {entry.name for entry in linked}
    assert "devkit.bootstrap.md" in linked_names
    assert "devkit.archive.md" in linked_names
    for entry in linked:
        assert entry.is_symlink()
        assert entry.name.endswith(".md")
        # Real ~/.claude/commands/ must never be touched.
        assert str(entry).startswith(str(tmp_workspace))


def test_setup_exits_with_doctor_failure(
    runner: CliRunner,
    monkeypatch: pytest.MonkeyPatch,
    tmp_workspace: Path,
) -> None:
    from aidevkit import setup as setup_module

    monkeypatch.setattr(setup_module.doctor, "cmd_doctor", lambda: 12)
    monkeypatch.setenv("HOME", str(tmp_workspace))

    result = runner.invoke(app, ["setup"])
    assert result.exit_code == 12

    # No symlinks when doctor fails.
    cmd_dir = tmp_workspace / ".claude" / "commands"
    assert not cmd_dir.exists() or not any(cmd_dir.iterdir())
