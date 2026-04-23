---
description: Summarize every active per-issue workspace at a glance
---

# /devkit.status

Print one entry per active workspace under `$APP_EMPIRE_WORKTREES_HOME`:
issue state, per-repo branch state (ahead/behind/dirty), PRs associated with
each branch, and a workspace-level `archivable` flag (issue closed AND every
repo has at least one merged PR — shares signal with `devkit archive`).

`_archived/` is excluded. Missing or externally-deleted worktrees are reported
without crashing.

## Usage

    /devkit.status

Takes no arguments.

## What to do

1. Run with JSON so the output is parseable:

       devkit status --json

2. Parse stdout as a single JSON document. Schema:
   `importlib.resources.files("aidevkit.schemas") / "status.schema.json"`.
   Top-level fields: `version` (currently `1`), `workspaces[]`. Each workspace
   has `dir_name`, `issue {owner_repo, number, title, state}`, `branch`,
   `archivable`, and `repos[]`. Each repo has `name`, `worktree_present`,
   `branch_state {ahead, behind, dirty, missing}`, and `prs[]`.

3. For each workspace summarize for the user:
   - Issue line: `<dir_name>  <owner>/<repo>#<N>  (<state>)` + `[archivable]`
     when applicable.
   - Per-repo line: `<name>  ahead N  behind M  [dirty]  [branch-missing]`
     (or `worktree: MISSING` if externally deleted).
   - PR lines: `PR #<n> <state> <url>` — one per PR.

4. If `issue.state == "unknown"` anywhere, GitHub was unreachable for that
   workspace — surface that, don't guess.

## Example JSON

```json
{
  "version": 1,
  "workspaces": [
    {
      "dir_name": "DevKit-issue-20",
      "issue": {"owner_repo": "App-Empire-LLC/DevKit", "number": 20,
                "title": "Lifecycle commands", "state": "open"},
      "branch": "issue-DevKit-20",
      "archivable": false,
      "repos": [
        {
          "name": "DevKit",
          "worktree_present": true,
          "branch_state": {"ahead": 2, "behind": 0, "dirty": false, "missing": false},
          "prs": []
        }
      ]
    }
  ]
}
```

## Notes

- Read-only. Never mutates filesystem or git state.
- GH unreachability (auth, rate limit, offline) degrades the issue/PR fields
  to `"unknown"` / empty; local git state is still reported. The command
  always exits 0 for reachability issues — not a failure.
- Exit code `16` means `$APP_EMPIRE_WORKTREES_HOME` is unset or not a
  directory (run `devkit doctor`).
