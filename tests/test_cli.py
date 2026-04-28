"""Tests for top-level CLI dispatch: --help snapshot, unknown command, version."""
from __future__ import annotations

import pytest
from typer.testing import CliRunner

from aidevkit import __version__
from aidevkit.cli import app


@pytest.fixture
def runner(monkeypatch: pytest.MonkeyPatch) -> CliRunner:
    monkeypatch.setenv("NO_COLOR", "1")
    return CliRunner()


EXPECTED_HELP = """\

 Usage: devkit [OPTIONS] COMMAND [ARGS]...

 DevKit — companion tooling for GitHub Spec-Kit.

╭─ Options ────────────────────────────────────────────────────────────────────╮
│ --help          Show this message and exit.                                  │
╰──────────────────────────────────────────────────────────────────────────────╯
╭─ Commands ───────────────────────────────────────────────────────────────────╮
│ bootstrap     Create a per-issue workspace directory with per-repo git       │
│               worktrees.                                                     │
│ doctor        Check dependencies, required env vars, and gh authentication.  │
│ setup         Link DevKit slash commands into ~/.claude/commands/ (runs      │
│               doctor first).                                                 │
│ sync          Fetch and rebase every worktree in the current workspace onto  │
│               its trunk.                                                     │
│ archive       Archive a completed per-issue workspace: post spec as issue    │
│               comment, move workspace to _archived/, prune registrations.    │
│ preflight     Check whether the current issue branch is behind origin/main   │
│               (detect-only; no mutation).                                    │
│ status        Summarize every active per-issue workspace: issue state,       │
│               branches, PRs.                                                 │
│ add-repo      Add a sibling repo's worktree to the current per-issue         │
│               workspace.                                                     │
│ purge         Remove archived workspaces older than the retention threshold. │
│ uninstall     Remove DevKit: uninstall aidevkit and unlink slash commands.   │
│ update        Upgrade DevKit to the latest release, then run doctor.         │
│ check-update  Check whether a newer aidevkit release is available.           │
│ version       Print the installed aidevkit version.                          │
╰──────────────────────────────────────────────────────────────────────────────╯
"""


def _normalize(output: str) -> str:
    return "\n".join(line.rstrip() for line in output.splitlines()).rstrip() + "\n"


def test_help_snapshot(runner: CliRunner) -> None:
    result = runner.invoke(app, ["--help"])
    assert result.exit_code == 0
    assert _normalize(result.output) == _normalize(EXPECTED_HELP)


def test_unknown_subcommand_exits_nonzero(runner: CliRunner) -> None:
    result = runner.invoke(app, ["notarealcommand"])
    assert result.exit_code != 0
    assert "No such command" in result.output
    assert "notarealcommand" in result.output


def test_version_prints_version_string(runner: CliRunner) -> None:
    result = runner.invoke(app, ["version"])
    assert result.exit_code == 0
    assert __version__ in result.output
