from __future__ import annotations

import re

import typer

from . import __version__
from . import add_repo as _add_repo
from . import archive as _archive
from . import bootstrap as _bootstrap
from . import check_update as _check_update
from . import config as _config
from . import doctor as _doctor
from . import pr_create as _pr_create
from . import preflight as _preflight
from . import purge as _purge
from . import refresh_issue_meta as _refresh_issue_meta
from . import review_issue as _review_issue
from . import setup as _setup
from . import status as _status
from . import sub_checkout as _sub_checkout
from . import sub_merge as _sub_merge
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


# Bare ref like "DevKit#42" or just "DevKit"; expanded via `org` config.
_BARE_REPO_RE = re.compile(r"^[^/\s#]+(?:#\d+)?$")


def _resolve_org_lazy() -> str | None:
    """Load `.devkit/config.yaml` once per CLI invocation and return `org`.

    Returns None when the config is not resolvable — callers fall back to
    leaving the input unchanged so the downstream parser can emit a clear
    format error (preserving today's E_USAGE behavior for invalid inputs
    when there's no config to consult).
    """
    cached = getattr(_resolve_org_lazy, "_cached", "__sentinel__")
    if cached != "__sentinel__":
        return cached
    try:
        projects_home = _config.resolve_projects_home()
        cfg = _config.load_merged_config(projects_home)
        _resolve_org_lazy._cached = cfg.org
        return cfg.org
    except typer.Exit:
        # Config not resolvable — bare refs flow through unchanged. The
        # subsequent format validation will catch genuinely bad input.
        _resolve_org_lazy._cached = None
        return None


def _expand_bare_ref(value: str) -> str:
    """If ``value`` is a bare repo (no ``owner/`` prefix), expand via `org`.

    Used for ``bootstrap``/``archive`` issue refs and ``--repos`` entries.
    Fully qualified references pass through unchanged. When ``org`` is
    unavailable, the bare ref also passes through unchanged.
    """
    if value and _BARE_REPO_RE.match(value):
        org = _resolve_org_lazy()
        if org:
            return f"{org}/{value}"
    return value


def _expand_repos_csv(value: str) -> str:
    """Apply ``_expand_bare_ref`` to each comma-separated entry in --repos."""
    if not value:
        return value
    parts = [p.strip() for p in value.split(",") if p.strip()]
    expanded = [_expand_bare_ref(p) for p in parts]
    return ",".join(expanded)


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
    no_epic: bool = typer.Option(
        False,
        "--no-epic",
        help="Skip epic detection; treat the issue as a regular non-epic workspace.",
    ),
    no_recursive: bool = typer.Option(
        False,
        "--no-recursive",
        help="When bootstrapping an epic, only include direct children (not nested epics).",
    ),
) -> None:
    issue_arg = _expand_bare_ref(issue_arg)
    repos = _expand_repos_csv(repos)
    code = _bootstrap.cmd_bootstrap(
        issue_arg=issue_arg,
        repos_override=repos,
        dry_run=dry_run,
        no_ack=no_ack,
        no_epic=no_epic,
        no_recursive=no_recursive,
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
    issue_arg = _expand_bare_ref(issue_arg)
    code = _archive.cmd_archive(issue_arg=issue_arg, force=force, dry_run=dry_run)
    raise typer.Exit(code=code)


@app.command(
    help="Check whether the current issue branch is behind origin/main "
    "(detect-only; no mutation).",
)
def preflight() -> None:
    code = _preflight.cmd_preflight()
    raise typer.Exit(code=code)


@app.command(
    "refresh-issue-meta",
    help="Refresh issue_title / issue_url in WORKSPACE.md from the current GitHub issue state.",
)
def refresh_issue_meta() -> None:
    _refresh_issue_meta.cmd_refresh_issue_meta()


@app.command(help="Summarize every active per-issue workspace: issue state, branches, PRs.")
def status(
    json: bool = typer.Option(
        False, "--json", help="Emit machine-readable JSON per the v1 schema."
    ),
) -> None:
    code = _status.cmd_status(json_output=json)
    raise typer.Exit(code=code)


@app.command(
    "pr-create",
    help="Open PRs for the current sub-issue in an epic workspace with correct base branches.",
)
def pr_create(
    dry_run: bool = typer.Option(
        False, "--dry-run",
        help="Print planned actions without creating PRs.",
    ),
) -> None:
    code = _pr_create.cmd_pr_create(dry_run=dry_run)
    raise typer.Exit(code=code)


@app.command(
    "sub-merge",
    help="Verify PRs merged for the current sub-issue, advance epic pointer, cascade-up.",
)
def sub_merge(
    issue_arg: str = typer.Argument(
        ...,
        metavar="N or OWNER/REPO#N",
        help="Sub-issue to mark merged: bare number, #N, or owner/repo#N.",
    ),
) -> None:
    code = _sub_merge.cmd_sub_merge(issue_arg=issue_arg)
    raise typer.Exit(code=code)


@app.command(
    "sub-checkout",
    help="Switch all worktrees in an epic workspace to a sub-issue's branch.",
)
def sub_checkout(
    issue_arg: str = typer.Argument(
        ...,
        metavar="N or OWNER/REPO#N",
        help="Sub-issue to check out: bare number (7), #7, or owner/repo#7.",
    ),
) -> None:
    code = _sub_checkout.cmd_sub_checkout(issue_arg=issue_arg)
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


# review-issue: pre-SpecKit issue quality gate (DevKit#17). Two subcommands
# (`inspect` and `post`) compose into the `/devkit.review-issue` slash command.
review_issue_app = typer.Typer(
    name="review-issue",
    help="Review a GitHub issue against the App Empire issue-authoring standard.",
    no_args_is_help=True,
)
app.add_typer(review_issue_app, name="review-issue")


@review_issue_app.command("inspect", help="Fetch issue + prior runs, emit JSON for the LLM.")
def review_issue_inspect(
    issue_arg: str = typer.Argument(
        ...,
        metavar="OWNER/REPO#N",
        help="GitHub issue reference, e.g. 'App-Empire-LLC/DevKit#17'.",
    ),
    reviewer_id: str = typer.Option(
        None,
        "--reviewer-id",
        help="Override reviewer-id (default: 'claude' or value from .devkit/config.yaml).",
    ),
) -> None:
    issue_arg = _expand_bare_ref(issue_arg)
    code = _review_issue.cmd_review_issue_inspect(
        ref=issue_arg, reviewer_id=reviewer_id,
    )
    raise typer.Exit(code=code)


@review_issue_app.command(
    "post",
    help="Validate findings JSON on stdin and post the consolidated review comment.",
)
def review_issue_post(
    issue_arg: str = typer.Argument(
        ...,
        metavar="OWNER/REPO#N",
        help="GitHub issue reference, e.g. 'App-Empire-LLC/DevKit#17'.",
    ),
    findings_stdin: bool = typer.Option(
        False,
        "--findings-stdin",
        help="Required marker indicating findings JSON is being read from stdin.",
    ),
    reviewer_id: str = typer.Option(
        None,
        "--reviewer-id",
        help=(
            "Override reviewer-id (must match the value used in the "
            "corresponding `inspect` call)."
        ),
    ),
    dry_run: bool = typer.Option(
        False, "--dry-run", help="Render the consolidated comment to stdout; do NOT post.",
    ),
    json_output: bool = typer.Option(
        False, "--json", help="Emit the full JSON envelope to stdout.",
    ),
    verbose: bool = typer.Option(
        False, "--verbose", help="Include nit-level findings as full rows in the comment table.",
    ),
    min_severity: str = typer.Option(
        "warning",
        "--min-severity",
        help=(
            "One of blocker/warning/nit. If all findings are below the threshold, "
            "the comment is NOT posted."
        ),
    ),
) -> None:
    issue_arg = _expand_bare_ref(issue_arg)
    if not findings_stdin:
        from .util import die as _die
        _die(
            "`--findings-stdin` is required (this reserves space for a future "
            "`--findings <path>` form). Pipe a findings JSON document into stdin.",
            code=2,
        )
    code = _review_issue.cmd_review_issue_post(
        ref=issue_arg,
        reviewer_id=reviewer_id,
        dry_run=dry_run,
        json_output=json_output,
        verbose=verbose,
        min_severity=min_severity,
    )
    raise typer.Exit(code=code)
