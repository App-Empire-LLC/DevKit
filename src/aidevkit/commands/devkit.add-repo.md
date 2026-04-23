---
description: Add a sibling repo's worktree to the current per-issue workspace
---

# /devkit.add-repo

From anywhere inside `$APP_EMPIRE_WORKTREES_HOME/<Repo>-issue-<N>/`, add a
sibling repo's git worktree on the current issue branch. The command infers
the workspace, branch, and source path from CWD — the user only supplies the
sibling repo's directory name.

## Usage

The user gives you a sibling repo name (e.g., `AuthService`):

    /devkit.add-repo AuthService

## What to do

1. Run the command:

       devkit add-repo <name>

2. On success, the worktree lives at `<workspace>/<name>/` on the workspace's
   `issue-<HomeRepo>-<N>` branch. Re-running is a safe no-op.

3. Exit-code handling:
   - `13` (source repo not found) — the sibling isn't cloned under
     `$APP_EMPIRE_PROJECTS`. Tell the user to clone it first. Do NOT clone
     on their behalf.
   - `24` (not in per-issue workspace) — the user is running this from
     outside a `<Repo>-issue-<N>` tree. Tell them to `cd` into the workspace.
   - `16` (env missing) — `$APP_EMPIRE_WORKTREES_HOME` or
     `$APP_EMPIRE_PROJECTS` is unset or not a directory. Run
     `devkit doctor`.
   - Any other non-zero — surface the message; don't retry.

## Notes

- Idempotent: if `<workspace>/<name>/` already has a valid worktree pointing
  into the source repo, the command logs a skip and exits 0.
- If the `issue-<HomeRepo>-<N>` branch does not yet exist in the source repo,
  it is created at HEAD (default: `git worktree add -b`).
- Never mutates the source repo beyond the worktree registration; never
  runs destructive git commands.
