---
description: Bootstrap a per-issue worktree directory for a GitHub issue
---

# /devkit.bootstrap

Create a per-issue worktree for a GitHub issue: set up the directory, git-init it, add worktrees for each affected repo on a shared branch, and post an ack comment on the issue.

## Usage

The user will give you an issue reference in the form `owner/repo#number`, e.g.:

    /devkit.bootstrap App-Empire-LLC/AuthService#5

If the user gives you a bare number or a URL, ask them to confirm the `owner/repo` before running.

## What to do

1. Run the bootstrap script with the issue reference:

       devkit bootstrap <owner/repo#number>

2. If the script exits with **code 10** (`no affected repos could be determined` — typically a draft issue with no `## Affected Repos` section), ask the user which repos should be included, then re-run with `--repos`:

       devkit bootstrap <owner/repo#number> --repos owner/repo-a,owner/repo-b

3. If the script exits with **code 11** (`worktree dir already exists`), do not attempt to delete or overwrite it. Surface the error to the user — they must decide whether to archive the existing worktree or remove it manually.

4. If the script exits with **code 13** (`source repo not found`), surface the error — the user may need to clone the missing repo into `$APP_EMPIRE_PROJECTS` first.

5. On success, surface the `cd ... && claude` command the script prints at the end, so the user can start a fresh implementation session in the worktree directory.

## Notes

- The worktree directory is created at `$APP_EMPIRE_WORKTREES_HOME/<repo>-issue-<N>/`
- Each affected repo gets a git worktree at `<wt_dir>/<reponame>` on branch `issue-<repo>-<N>`
- The issue's home repo is always included in the worktree set (unless it's a GH draft issue with no repo at all)
- An ack comment is auto-posted to the issue — pass `--no-ack` if testing and you want to skip it
- Do not try to "help" by running destructive commands if bootstrap fails. Stop, surface the error, let the user decide.
