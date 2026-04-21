---
description: Archive a completed per-issue workspace after PRs are merged
---

# /devkit.archive

Finalize a per-issue workspace whose PRs have merged: post the spec.md as a durable comment on the issue, close the issue, move the workspace directory into `_archived/`, and prune dangling `git worktree` registrations from the upstream repos.

## Usage

The user will give you an issue reference in the form `owner/repo#number`, or (if they are working inside the per-issue worktree) a bare `#N` that can be inferred from the CWD:

    /devkit.archive App-Empire-LLC/DevKit#4
    /devkit.archive #4

## What to do

1. Run the archive command:

       devkit archive <owner/repo#number>

2. If the command exits with **code 14** (`PRs not merged`), surface the open-PR URLs to the user. Do NOT pass `--force` on the user's behalf — force is a deliberate override that the user must choose. Tell them either to merge the PRs first or to re-invoke with `--force` themselves:

       /devkit.archive <owner/repo#number> --force

3. If the command exits with **code 15** (`_archived/ collision`), a prior archive directory with the same name already exists. Surface the error. Do NOT delete or rename the existing archive automatically — the user decides whether to remove it or to rename the new one.

4. If the command exits with **code 16** (`workspace missing`), the per-issue directory doesn't exist at `$APP_EMPIRE_WORKTREES_HOME/<Repo>-issue-<N>`. Either it was already archived or the issue never had one. Surface the error.

5. For intermediate failures (mid-archive: a step failed after another already succeeded), the command prints which steps completed and which remain. Do NOT attempt auto-recovery — surface the message so the user can resolve the partial state manually.

6. On success, surface the summary (comments posted, issue state, move destination, prune results).

## Flags

- `--dry-run` — print planned actions without making changes. Read-only PR queries and spec introspection still run so the user can see what *would* happen.
- `--force` — override the PR-merged guardrail (exit code 14). Does NOT override the `_archived/` collision check (exit 15) — that remains a hard refusal.

## Notes

- Archive is **never automatic**. It only runs when the user explicitly invokes this command.
- The worktree is **moved**, not deleted. The user prunes `_archived/` manually on their own schedule.
- Local `issue-<repo>-<N>` branches in the upstream repos are **left alone**. Branch cleanup is out of scope.
- If the workspace's `specs/` directory is missing or empty, archive skips the comment step with a note and continues with the remaining cleanup — this is expected for trivial issues that skipped `/speckit.specify`.
