from __future__ import annotations

import typer

from . import __version__
from . import add_repo as _add_repo
from . import archive as _archive
from . import bootstrap as _bootstrap
from . import check_update as _check_update
from . import doctor as _doctor
from . import preflight as _preflight
from . import purge as _purge
from . import setup as _setup
from . import status as _status
from . import sync as _sync
from . import uninstall as _uninstall
from . import update as _update
from .util import info

app = typer.Typer(
    name="devkit",
    help="DevKit — companion tooling for GitHub Spec-Kit.",
    no_args_is_help=True,
    add_completion=False,
)


@app.command(help="Create a per-issue workspace directory with per-repo git worktrees.")
def bootstrap(
    issue_arg: str = typer.Argument(
        ...,
        metavar="OWNER/REPO#N",
        help="GitHub issue reference, e.g. 'App-Empire-LLC/DevKit#21'.",
    ),
    repos: str = typer.Option(
        "",
        "--repos",
        help="Comma-separated owner/repo list overriding the issue body's "
        "'## Affected Repos' section.",
    ),
    dry_run: bool = typer.Option(
        False,
        "--dry-run",
        help="Print planned actions without making changes.",
    ),
    no_ack: bool = typer.Option(
        False,
        "--no-ack",
        help="Skip posting the acknowledgement comment on the issue.",
    ),
) -> None:
    code = _bootstrap.cmd_bootstrap(
        issue_arg=issue_arg,
        repos_override=repos,
        dry_run=dry_run,
        no_ack=no_ack,
    )
    raise typer.Exit(code=code)


@app.command(help="Check dependencies, required env vars, and gh authentication.")
def doctor() -> None:
    code = _doctor.cmd_doctor()
    raise typer.Exit(code=code)


@app.command(help="Link DevKit slash commands into ~/.claude/commands/ (runs doctor first).")
def setup() -> None:
    code = _setup.cmd_setup()
    raise typer.Exit(code=code)


@app.command(help="Fetch and rebase every worktree in the current workspace onto its trunk.")
def sync(
    json: bool = typer.Option(False, "--json", help="Emit a single JSON document on stdout."),
    dry_run: bool = typer.Option(
        False,
        "--dry-run",
        help="Print planned actions without running git fetch or git rebase.",
    ),
) -> None:
    code = _sync.cmd_sync(json_output=json, dry_run=dry_run)
    raise typer.Exit(code=code)


@app.command(
    help="Archive a completed per-issue workspace: post spec as issue comment, "
    "move workspace to _archived/, prune registrations.",
)
def archive(
    issue_arg: str = typer.Argument(
        ...,
        metavar="OWNER/REPO#N",
        help="GitHub issue reference, e.g. 'App-Empire-LLC/DevKit#4'. "
        "Bare '#N' (or 'N') infers the repo from the current worktree.",
    ),
    force: bool = typer.Option(
        False,
        "--force",
        help="Override the PR-merged guardrail. Does NOT override the "
        "_archived/ collision check.",
    ),
    dry_run: bool = typer.Option(
        False,
        "--dry-run",
        help="Print planned actions without making changes.",
    ),
) -> None:
    code = _archive.cmd_archive(issue_arg=issue_arg, force=force, dry_run=dry_run)
    raise typer.Exit(code=code)


@app.command(
    help="Check whether the current issue branch is behind origin/main "
    "(detect-only; no mutation).",
)
def preflight() -> None:
    code = _preflight.cmd_preflight()
    raise typer.Exit(code=code)


@app.command(help="Summarize every active per-issue workspace: issue state, branches, PRs.")
def status(
    json: bool = typer.Option(
        False, "--json", help="Emit machine-readable JSON per the v1 schema."
    ),
) -> None:
    code = _status.cmd_status(json_output=json)
    raise typer.Exit(code=code)


@app.command("add-repo", help="Add a sibling repo's worktree to the current per-issue workspace.")
def add_repo(
    repo_name: str = typer.Argument(
        ...,
        metavar="REPO_NAME",
        help="Sibling repo directory name under $APP_EMPIRE_PROJECTS.",
    ),
) -> None:
    code = _add_repo.cmd_add_repo(repo_name=repo_name)
    raise typer.Exit(code=code)


@app.command(help="Remove archived workspaces older than the retention threshold.")
def purge(
    days: int = typer.Option(30, "--days", help="Retention threshold in days (default: 30)."),
    yes: bool = typer.Option(
        False, "--yes", help="Actually delete. Without this flag the command is a dry-run."
    ),
) -> None:
    code = _purge.cmd_purge(days=days, yes=yes)
    raise typer.Exit(code=code)


@app.command(help="Remove DevKit: uninstall aidevkit and unlink slash commands.")
def uninstall() -> None:
    code = _uninstall.cmd_uninstall()
    raise typer.Exit(code=code)


@app.command(help="Upgrade DevKit to the latest release, then run doctor.")
def update() -> None:
    code = _update.cmd_update()
    raise typer.Exit(code=code)


@app.command("check-update", help="Check whether a newer aidevkit release is available.")
def check_update(
    json: bool = typer.Option(
        False, "--json", help="Emit machine-readable JSON."
    ),
) -> None:
    code = _check_update.cmd_check_update(json_output=json)
    raise typer.Exit(code=code)


@app.command(help="Print the installed aidevkit version.")
def version() -> None:
    info(f"aidevkit {__version__}")
    raise typer.Exit(code=0)
