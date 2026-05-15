---
description: Mark a sub-issue's PRs merged, advance the epic pointer, and cascade-up
---

# /devkit.sub-merge

Verify that every PR for a sub-issue is merged on GitHub, mark the node `merged` in `EPIC.md`, advance `current_issue` to the next sub-issue in execution order, and — if this completes a parent's children — cascade-up by opening the parent's PRs.

The epic workspace model is documented in `appire_docs/docs/workflows/devkit-workspaces.md` and `DevKit/docs/epic-workspaces.md`.

## Usage

The user will give you a sub-issue reference. Any of these forms is accepted:

- Bare number: `7`
- Hash form: `#7`
- Fully qualified: `App-Empire-LLC/AuthService#7`

```bash
/devkit.sub-merge 7
/devkit.sub-merge #7
/devkit.sub-merge App-Empire-LLC/AuthService#7
```

The sub-issue must be a node in the current workspace's `EPIC.md` graph.

## What to do

1. Confirm you are inside an epic workspace (the workspace dir contains `EPIC.md`). Run the command from anywhere inside the workspace:

       devkit sub-merge <ref>

2. **Common exit codes** (each names the offending input in its message):
   - **20** `E_NOT_IN_WORKSPACE` — CWD is not inside a workspace directory under `workspaces_home`.
   - **31** `E_EPIC_GRAPH_INVALID` — no `EPIC.md`, or it failed to parse.
   - **33** `E_NODE_NOT_FOUND` — the given number/ref isn't a node in this epic's graph.
   - **34** `E_PRS_NOT_MERGED` — at least one PR for the sub-issue's branch is still open. The error message lists the blockers; surface them and stop. Do NOT try to merge them via `gh pr merge` — merges are human-driven.

## PR verification

`sub-merge` checks each effective repo's clone for a PR whose head matches the sub-issue's branch (`issue-<repo>-<N>`) and confirms its state is `merged`. If any are not merged, the command exits cleanly with `E_PRS_NOT_MERGED` and does **not** mutate `EPIC.md`.

## Pointer advance

On success the node's `status` flips to `merged`. `current_issue` advances to the next node in `execution_order`. When `execution_order` is exhausted, `current_issue` points at `top_epic` (clarification Q5) — this is the signal that the whole epic is ready for its own PRs.

## Cascade-up (one level only)

After advancing the pointer, `sub-merge` checks the merged node's **parent**:

- If **all** of the parent's children are now `merged`, `sub-merge` calls `pr-create` for the parent, flips the parent's status to `in_review`, and stops.
- The parent is NOT auto-marked `merged`. The user must still run `/devkit.sub-merge <parent>` once its PRs land — that's the explicit human gate from FR-024.

Cascade-up is exactly one level deep per call. If a chain of parents all complete at once, each level requires its own `sub-merge` invocation.

## Notes

- `sub-merge` never closes or merges PRs; it only verifies state and mutates `EPIC.md`. If PRs are open, point the user at `/devkit.pr-create` (to open) or the GitHub UI (to merge).
- After `sub-merge`, the next `/devkit.sub-checkout` should target the new `current_issue`. Re-read `EPIC.md` if you need to confirm what that is.
- The `archive` command refuses to run on an epic workspace unless every node is `merged` (use `--force` only at the user's explicit direction).
- Do not try to "help" by running destructive git or `gh` commands if verification fails. Stop, surface the error, let the user decide.
