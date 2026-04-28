---
description: Bootstrap a per-issue workspace directory for a GitHub issue
---

# /devkit.bootstrap

Create a per-issue workspace for a GitHub issue: set up the directory, git-init it, add worktrees for each affected repo on a shared branch, and post an ack comment on the issue.

## Usage

The user will give you an issue reference in the form `owner/repo#number`, e.g.:

    /devkit.bootstrap App-Empire-LLC/AuthService#5

If the user gives you a bare number or a URL, ask them to confirm the `owner/repo` before running.

## What to do

1. Run the bootstrap script with the issue reference:

       devkit bootstrap <owner/repo#number>

2. If the script exits with **code 10** (`no affected repos could be determined` — typically a draft issue with no `## Affected Repos` section), ask the user which repos should be included, then re-run with `--repos`:

       devkit bootstrap <owner/repo#number> --repos owner/repo-a,owner/repo-b

3. If the script exits with **code 11** (`workspace dir already exists`), do not attempt to delete or overwrite it. Surface the error to the user — they must decide whether to archive the existing workspace or remove it manually.

4. If the script exits with **code 13** (`source repo not found`), surface the error — the user may need to clone the missing repo into `$APP_EMPIRE_PROJECTS` first.

5. If the script exits with **code 17** (`origin/main unavailable` — either the `git fetch origin` failed or `origin/main` does not exist after fetch), surface the error. The message names the affected repo. Common causes: network failure, missing/misconfigured `origin` remote, repo has been renamed, or trunk is not called `main`. Do NOT attempt to bypass by hand-creating the branch from local `main` — that reintroduces the exact stale-main bug this check exists to prevent. (Note: code 14 is `E_PRS_NOT_MERGED` used by `devkit archive`, not bootstrap.)

6. On success, surface the `cd ... && claude` command the script prints at the end, so the user can start a fresh implementation session in the workspace directory.

## Validation phase

Before any worktree is created, bootstrap runs a two-phase sequence:

1. **Validation phase**: for every affected repo, `git fetch origin` and verify `refs/remotes/origin/main` exists. Fail-fast — the first failing repo causes bootstrap to exit `14` without creating any workspace dir, worktree, or branch anywhere.
2. **Creation phase**: workspace dir, `git init`, then `git worktree add ... -b <branch> origin/main` per repo. Only runs if every repo passed validation.

This means: if bootstrap exits `14` for a multi-repo issue, **no worktrees exist for any of the affected repos** — not even the ones whose validation would have succeeded. Re-runs are idempotent: fix the failing repo, re-run, and bootstrap picks up validation from scratch.

## Notes

- The workspace directory is created at `$APP_EMPIRE_WORKTREES_HOME/<repo>-issue-<N>/`
- Each affected repo gets a git worktree at `<wt_dir>/<reponame>` on branch `issue-<repo>-<N>`, based on `origin/main` at fetch time
- The issue's home repo is always included in the workspace's worktree set (unless it's a GH draft issue with no repo at all)
- An ack comment is auto-posted to the issue — pass `--no-ack` if testing and you want to skip it
- Local `main` in each source repo is never read or mutated — bootstrap uses the remote-tracking `origin/main` directly
- Do not try to "help" by running destructive commands if bootstrap fails. Stop, surface the error, let the user decide.
