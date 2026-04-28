---
description: Check whether the current issue branch is behind origin/main (detect-only)
---

# /devkit.preflight

Run `devkit preflight` from the current issue workspace to find out whether the current branch is behind `origin/main` before pushing. The command fetches `origin` and computes the behind-count, then exits. It **never** rebases, merges, resets, pushes, or mutates the working tree.

## When to run

- Right before `git push` from any issue workspace, especially if the branch has been in flight for more than a few hours.
- When resuming work on a branch after time away — quickly confirms whether `origin/main` has advanced.
- Before opening a PR, to avoid PRs that silently include stale history.

## What to do

1. Change to any directory inside the issue workspace (e.g. one of its repo worktrees).
2. Run:

       devkit preflight

3. Interpret the exit code and surface the result to the user:

| Exit code | Symbol | Meaning | What to say |
|---|---|---|---|
| `0` | — | Branch contains every commit in `origin/main` | "Safe to push." |
| `22` | `E_BEHIND_ORIGIN` | Branch is behind `origin/main` | Surface the message verbatim — it names the behind-count. Let the user decide how to rebase or merge. Do NOT auto-rebase. |
| `23` | `E_PREFLIGHT_FAILED` | Not in a git worktree, `origin` missing, `origin/main` missing, or fetch failed | Surface the error. Do not attempt destructive recovery — the user must diagnose. |

## Invariants

- Preflight is **detect-only**. It runs exactly three mutating operations: `git rev-parse --is-inside-work-tree`, `git fetch origin` (only mutates `refs/remotes/origin/*`), and `git rev-parse --verify` (read-only). Nothing else.
- If preflight reports "behind", do not try to "fix" it by running `git pull`, `git merge`, or `git reset` on behalf of the user. The whole point is to make the user decide.
- If preflight exits `23`, do not retry in a loop or attempt to bypass by running git commands directly. Surface the error.

## Notes

- The trunk is hardcoded to `main` in v1. Repos that use a different default branch name will exit `23`.
- Wiring preflight into a git pre-push hook is a potential follow-up but is out of scope — preflight is intentionally user-invoked.
- Implementation: see `src/aidevkit/preflight.py`. Behind-count computation delegates to `aidevkit.sync.behind_count` (landed in DevKit#30).
