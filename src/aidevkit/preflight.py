"""`devkit preflight` — detect-only staleness check before `git push` (DevKit#27).

The command answers one question: is the current branch behind ``origin/main``?

It MUST NOT rebase, merge, reset, or mutate any ref outside of
``refs/remotes/origin/*`` via fetch. All shell calls route through
``aidevkit.util.run`` (the canonical seam).
"""

from __future__ import annotations

from pathlib import Path

from .sync import behind_count
from .util import (
    E_BEHIND_ORIGIN,
    E_PREFLIGHT_FAILED,
    die,
    git,
    info,
)

_TRUNK = "main"


def cmd_preflight() -> int:
    cwd = Path.cwd()

    # 1) Refuse to run outside a git worktree. Check both the exit code and
    #    stdout value — `git rev-parse --is-inside-work-tree` may return
    #    exit 0 with stdout "false" when cwd is inside `.git/` itself
    #    (analysis U1).
    inside_res = git("rev-parse", "--is-inside-work-tree", cwd=cwd)
    if inside_res.code != 0 or inside_res.stdout.strip() != "true":
        die(f"not inside a git worktree (cwd: {cwd})", code=E_PREFLIGHT_FAILED)

    # 2) Refresh remote-tracking refs. Only mutation permitted by this command.
    fetch_res = git("fetch", "origin", cwd=cwd)
    if fetch_res.code != 0:
        detail = fetch_res.stderr.strip() or fetch_res.stdout.strip() or "(no detail)"
        die(f"fetch origin failed: {detail}", code=E_PREFLIGHT_FAILED)

    # 3) Verify origin/main exists as a remote-tracking ref.
    verify_res = git(
        "rev-parse", "--verify", "--quiet", f"refs/remotes/origin/{_TRUNK}",
        cwd=cwd,
    )
    if verify_res.code != 0:
        die(
            f"origin/{_TRUNK} not found after fetch — is {_TRUNK} the trunk?",
            code=E_PREFLIGHT_FAILED,
        )

    # 4) Delegate behind-count to the landed `aidevkit.sync` primitive.
    n = behind_count(cwd, _TRUNK)
    if n == 0:
        info(f"branch is up-to-date with origin/{_TRUNK}")
        return 0

    die(
        f"branch is behind origin/{_TRUNK} by {n} commits — "
        f"rebase or merge manually before pushing",
        code=E_BEHIND_ORIGIN,
    )
    return 1  # unreachable; die() raises typer.Exit
