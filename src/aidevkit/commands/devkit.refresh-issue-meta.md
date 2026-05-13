---
description: Refresh issue_title / issue_url in WORKSPACE.md from the current GitHub issue state
---

# /devkit.refresh-issue-meta

Re-fetch the GitHub issue's title and canonical URL and update `WORKSPACE.md` accordingly. Opt-in, scoped, diff-on-change, no-op-on-unchanged. Only `issue_title` and `issue_url` are ever touched — no other frontmatter field, no other file.

## Usage

Run from the per-issue workspace root (the directory containing `WORKSPACE.md`):

    /devkit.refresh-issue-meta

No arguments. The workspace's owning issue is read from `WORKSPACE.md` frontmatter (`issue_owner_repo` + `issue_number`).

## What to do

1. Confirm the current working directory is a per-issue workspace root (contains `WORKSPACE.md`). If not, surface the missing-precondition error to the user — do NOT attempt to walk upward or guess.

2. Run the refresh command:

       devkit refresh-issue-meta

3. Interpret the outcome:
   - **Exit 0, empty stdout**: workspace was already in sync. Tell the user nothing changed.
   - **Exit 0, one or two `[devkit] refresh-issue-meta: ...` lines on stdout**: surface those diff lines verbatim. They describe exactly which field(s) updated.
   - **Exit 20** (`WORKSPACE.md not found`): surface the error. The user is not in a workspace root.
   - **Exit 16** (`WORKSPACE.md malformed`): surface the error including the named precondition (missing delimiter, missing field, etc.). Do NOT attempt to repair the file automatically.
   - **Exit 12** (`gh CLI missing or unauthenticated`): surface the error. The user needs to install `gh` or run `gh auth login` — do not run those for them.
   - **Exit 13** (`gh issue view failed`): surface the upstream `gh` stderr. The issue may have been deleted, made private, or the network is unreachable.
   - **Exit 1** (concurrent modification): rare race where `WORKSPACE.md` was edited between read and write. Tell the user to re-run.

## Notes

- This command never modifies anything outside `WORKSPACE.md`. If a diff appears in any other file under the workspace after running it, that is a bug — surface it to the user.
- This is **strictly opt-in**. Do not invoke it as part of any other slash command's workflow. It costs one GitHub API call per invocation.
- `issue_owner_repo` and `issue_number` are authoritative for the lifetime of the workspace; this command never changes them, even if the issue was transferred between repos.
