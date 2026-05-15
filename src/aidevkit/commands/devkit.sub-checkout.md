---
description: Switch all worktrees in an epic workspace to a sub-issue's branch
---

# /devkit.sub-checkout

Switch every worktree in an **epic workspace** to the branch for a specific sub-issue, then update `EPIC.md` so the workspace remembers which sub-issue is active. This is the "I'm about to work on sub-issue N" command in the epic lifecycle.

The epic workspace model is documented in `appire_docs/docs/workflows/devkit-workspaces.md` and `DevKit/docs/epic-workspaces.md`.

## Usage

The user will give you a sub-issue reference. Any of these forms is accepted:

- Bare number: `7`
- Hash form: `#7`
- Fully qualified: `App-Empire-LLC/AuthService#7`

```bash
/devkit.sub-checkout 7
/devkit.sub-checkout #7
/devkit.sub-checkout App-Empire-LLC/AuthService#7
```

## What to do

1. Confirm you are inside an epic workspace (the workspace dir contains `EPIC.md`). If you are not, the command exits with `E_NOT_IN_WORKSPACE` (20) or `E_EPIC_GRAPH_INVALID` (31).

2. Run the command from anywhere inside the workspace:

       devkit sub-checkout <ref>

3. **Common exit codes** (each names the offending input in its message):
   - **20** `E_NOT_IN_WORKSPACE` — CWD is not inside a workspace directory under `workspaces_home`.
   - **31** `E_EPIC_GRAPH_INVALID` — no `EPIC.md` in the workspace, or it failed to parse. Non-epic workspaces don't have one — sub-checkout is epic-only.
   - **33** `E_NODE_NOT_FOUND` — the given number/ref isn't a node in this epic's graph.
   - **32** `E_DIRTY_WORKTREE` — at least one worktree in `effective(N)` has uncommitted changes. Commit or stash, then retry.
   - **2** `E_USAGE` — usually means **serial enforcement** kicked in (see below).

## Serial enforcement (FR-030)

`sub-checkout` only succeeds when the target sub-issue matches `EPIC.md#current_issue`. This is by design: sub-issues are worked one at a time in execution order so the stacked branches don't get tangled.

If the user tries to check out a different node:

- Surface the error verbatim and don't try to work around it.
- The error message names the current pointer. Either `devkit sub-merge <current>` to finish the in-flight one, or — if the user genuinely needs to skip ahead — edit `current_issue` in `EPIC.md` manually. The escape hatch is intentional and human-driven; do not edit `EPIC.md` on the user's behalf without explicit instruction.

If `current_issue` already equals `top_epic`, every sub-issue has been merged. The error will say so; recommend `devkit pr-create` or `devkit sub-merge` on the top epic instead.

## Dirty-check scope

Only worktrees in the sub-issue's **effective repos** are dirty-checked. A workspace can contain worktrees outside the current sub-issue's scope (e.g., from a sibling sub-issue), and those will NOT block checkout. This is the documented clarification (Q2) from issue #42 — preserve it; don't propose a "check all worktrees" workaround.

## Notes

- On success, every effective-repos worktree has been switched to `node.branch_name` and `EPIC.md` records `current_issue = <ref>` and the node's `status = in_progress`.
- `sub-checkout` performs `git checkout <branch>` — it does NOT fetch, rebase, or merge. Use `/devkit.sync` separately if branches are stale.
- The command never mutates `main` or any branch other than the target sub-issue's stacked branch in each worktree.
- Do not try to "help" by running destructive git commands if checkout fails. Stop, surface the error, let the user decide.
