---
description: Open stacked PRs for the current sub-issue in an epic workspace
---

# /devkit.pr-create

Open one PR per effective repo for the **current sub-issue** in an epic workspace, with each PR's base branch wired to the parent sub-issue's branch (or `origin/<default_branch>` if this is the top epic). Cross-links sibling PRs in each body and marks the sub-issue `in_review` in `EPIC.md`.

The epic workspace model is documented in `appire_docs/docs/workflows/devkit-workspaces.md` and `DevKit/docs/epic-workspaces.md`.

## Usage

```bash
/devkit.pr-create
/devkit.pr-create --dry-run
```

There are no positional arguments — the target is whatever `EPIC.md#current_issue` points at. To open PRs for a different sub-issue, first `/devkit.sub-checkout <N>` (which enforces serial order) or — only if the user explicitly directs — edit `current_issue` in `EPIC.md` manually.

## What to do

1. Confirm you are inside an epic workspace (the workspace dir contains `EPIC.md`). Run the command from anywhere inside the workspace:

       devkit pr-create
       devkit pr-create --dry-run

2. `--dry-run` skips both the PR-create and PR-edit calls, but still walks the graph and reports the base branch and effective repos that *would* be targeted. It does NOT update `EPIC.md`.

3. **Common exit codes** (each names the offending input in its message):
   - **20** `E_NOT_IN_WORKSPACE` — CWD is not inside a workspace directory under `workspaces_home`.
   - **31** `E_EPIC_GRAPH_INVALID` — no `EPIC.md` in the workspace, or it failed to parse. Non-epic workspaces don't have one — pr-create is epic-only.

## How base branches are computed

For the current sub-issue `N`:

- If `N` has a **parent** in the epic graph, each PR's `--base` is the **parent's** stacked branch (`issue-<repo>-<parent_num>`). This is the stacking — child PRs target parent branches, not `main`.
- If `N` is the **top epic** (no parent), each PR's `--base` is `origin/<default_branch>` of that repo (typically `origin/main`). The top epic's PRs are the only ones that ever target `main`.

Do not propose flattening this to "everything targets main" — the stacked-base model is what makes the cascade-up review flow work.

## Two-pass PR body editing

`pr-create` runs two passes:

1. **Pass 1**: create each PR with a minimal body that names the sub-issue.
2. **Pass 2**: edit each PR's body to add a `## Sibling PRs` section cross-linking the other PRs opened in the same run. This only happens when more than one PR was opened.

If pass-2 fails for any single PR, the command logs a WARN and continues — the PR itself still exists, just without cross-links. Don't retry the whole command on a pass-2 WARN; surface it and let the user decide whether to edit by hand.

## Status transition

On success, the sub-issue's node in `EPIC.md` flips from `in_progress` → `in_review`. The `current_issue` pointer does **not** advance — only `/devkit.sub-merge` advances it.

## Cascade-up note

`pr-create` is also called automatically by `/devkit.sub-merge` when all of a parent's children become merged (the cascade-up step). You normally only run `pr-create` directly for the *current* sub-issue; the parent's PRs open themselves via cascade.

## Notes

- Each PR title defaults to the sub-issue's GitHub title, prefixed with `[epic]`. If the `gh issue view` call fails, the title falls back to `[epic] <owner/repo#N>` — surface this rather than retrying.
- `pr-create` requires that the sub-issue's branch has been pushed to `origin` in every effective repo. If a `gh pr create` call fails because the branch doesn't exist on the remote, push first and re-run.
- Do not try to "help" by force-pushing or rebasing if PR creation fails. Stop, surface the error, let the user decide.
