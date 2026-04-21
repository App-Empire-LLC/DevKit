from __future__ import annotations

import typer

from . import __version__
from . import bootstrap as _bootstrap
from . import doctor as _doctor
from . import setup as _setup
from . import sync as _sync
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
    dry_run: bool = typer.Option(False, "--dry-run", help="Print planned actions without running git fetch or git rebase."),
) -> None:
    code = _sync.cmd_sync(json_output=json, dry_run=dry_run)
    raise typer.Exit(code=code)


@app.command(help="Print the installed aidevkit version.")
def version() -> None:
    info(f"aidevkit {__version__}")
    raise typer.Exit(code=0)
