"""Archive a completed per-issue worktree.

Reads spec.md files from the worktree, posts them as comments on the target
GitHub issue (splitting oversized specs into multiple comments), closes the
issue, moves the worktree directory into `_archived/`, and prunes dangling
`git worktree` registrations in each upstream repo.

See `specs/4-archive-subcommand/spec.md` for the full specification and
`specs/4-archive-subcommand/research.md` for implementation decisions.
"""
from __future__ import annotations


def cmd_archive(issue_arg: str, force: bool = False, dry_run: bool = False) -> int:
    """Entry point for `devkit archive`. Stub — implementation lands in US1."""
    return 1
