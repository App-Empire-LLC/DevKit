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
│ review-issue  Review a GitHub issue against the App Empire issue-authoring   │
│               standard.                                                      │
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


# --- DevKit#37 T011: org-shorthand expansion ----------------------------------

def test_org_shorthand_expansion_bare_repo(monkeypatch: pytest.MonkeyPatch) -> None:
    from aidevkit import cli as _cli
    # Prime the lazy cache so we don't read real config.
    monkeypatch.setattr(_cli._resolve_org_lazy, "_cached", "MyOrg", raising=False)
    assert _cli._expand_bare_ref("repo#42") == "MyOrg/repo#42"
    assert _cli._expand_bare_ref("repo") == "MyOrg/repo"


def test_org_shorthand_expansion_passthrough(monkeypatch: pytest.MonkeyPatch) -> None:
    """Fully qualified refs are NOT expanded."""
    from aidevkit import cli as _cli
    monkeypatch.setattr(_cli._resolve_org_lazy, "_cached", "MyOrg", raising=False)
    assert _cli._expand_bare_ref("Other-Org/repo#42") == "Other-Org/repo#42"


def test_org_shorthand_expansion_csv(monkeypatch: pytest.MonkeyPatch) -> None:
    from aidevkit import cli as _cli
    monkeypatch.setattr(_cli._resolve_org_lazy, "_cached", "MyOrg", raising=False)
    assert _cli._expand_repos_csv("a,b") == "MyOrg/a,MyOrg/b"
    assert _cli._expand_repos_csv("Other/qualified,bare") == "Other/qualified,MyOrg/bare"


def test_org_shorthand_falls_back_when_no_config(monkeypatch: pytest.MonkeyPatch) -> None:
    """No config = bare refs flow through unchanged. Downstream parsers
    emit E_USAGE for unparseable inputs (preserving pre-#37 behavior)."""
    from aidevkit import cli as _cli
    monkeypatch.setattr(_cli._resolve_org_lazy, "_cached", None, raising=False)
    assert _cli._expand_bare_ref("repo#42") == "repo#42"


def test_org_shorthand_does_not_expand_empty(monkeypatch: pytest.MonkeyPatch) -> None:
    from aidevkit import cli as _cli
    monkeypatch.setattr(_cli._resolve_org_lazy, "_cached", "MyOrg", raising=False)
    assert _cli._expand_bare_ref("") == ""
    assert _cli._expand_repos_csv("") == ""
