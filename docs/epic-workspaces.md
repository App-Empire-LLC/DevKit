# Epic Workspaces

**Issue**: [App-Empire-LLC/DevKit#42](https://github.com/App-Empire-LLC/DevKit/issues/42)  
**Supersedes**: DevKit#13 (Option B flat-sibling design — never shipped)  
**Status**: Current  

A single workspace, one worktree per affected repo, stacked branches that mirror the epic graph. One command bootstraps everything; subsequent commands navigate the lifecycle.

## Conceptual Model

### Effective Repos

For every node N in the epic graph:

> `effective(N) = own_repos(N) ∪ ⋃ effective(child) for child in children(N)`

Computed bottom-up at bootstrap time. Every repo touched anywhere in the graph ends up with a worktree in the workspace.

### Per-Repo Branch Graph

For every repo R: a branch exists for every node whose `effective_repos` contains R. The per-repo merge graph is a strict sub-tree of the epic graph.

### Merge Target Rule

For node N in repo R: merge target = `N.parent.branch_name` in R if N has a parent; else `origin/<default_branch>`.

### Worked Example

```
top_epic#1     own: repoA, repoB
└── sub_epic#2   own: repoA
    ├── issue#7   own: repoA, repoB
    └── issue#8   own: repoB
```

Effective repos (bottom-up):

| Node | Effective repos |
|------|----------------|
| issue#7 | {A, B} |
| issue#8 | {B} |
| sub_epic#2 | {A} ∪ {A, B} ∪ {B} = {A, B} |
| top_epic#1 | {A, B} ∪ {A, B} = {A, B} |

Branches per repo:

```
repoA:  main ← top_epic#1 ← sub_epic#2 ← issue#7
repoB:  main ← top_epic#1 ← sub_epic#2 ← issue#7
                                       ← issue#8
```

`sub_epic#2` exists as a branch in repoB even though its own repos didn't include B — because `effective(sub_epic#2) = {A, B}`.

---

## Workspace Structure

```
<workspaces_home>/<top_epic_repo>-issue-<N>/
├── EPIC.md          # graph + execution order + current pointer
├── WORKSPACE.md     # workspace metadata + is_epic: true
├── PROJECTS.md      # catalog snapshot
├── TRUNK.md
├── .specify/
├── .claude/
├── <repoA>/         # worktree on top_epic branch at bootstrap
├── <repoB>/         # worktree on top_epic branch at bootstrap
└── ...
```

### EPIC.md Schema

YAML frontmatter (machine-read by DevKit) + markdown body (human-read).

```yaml
---
top_epic: App-Empire-LLC/DevKit#1
current_issue: App-Empire-LLC/DevKit#7
execution_order:
  - App-Empire-LLC/DevKit#7
  - App-Empire-LLC/appire_docs#8
  - App-Empire-LLC/DevKit#2
graph:
  App-Empire-LLC/DevKit#1:
    type: epic
    own_repos: [App-Empire-LLC/DevKit]
    effective_repos: [App-Empire-LLC/DevKit, App-Empire-LLC/appire_docs]
    branch_name: issue-DevKit-1
    parent: null
    children: [App-Empire-LLC/DevKit#2]
    status: in_progress
  App-Empire-LLC/DevKit#2:
    type: epic
    own_repos: [App-Empire-LLC/DevKit]
    effective_repos: [App-Empire-LLC/DevKit, App-Empire-LLC/appire_docs]
    branch_name: issue-DevKit-2
    parent: App-Empire-LLC/DevKit#1
    children: [App-Empire-LLC/DevKit#7, App-Empire-LLC/appire_docs#8]
    status: not_started
  App-Empire-LLC/DevKit#7:
    type: issue
    own_repos: [App-Empire-LLC/DevKit, App-Empire-LLC/appire_docs]
    effective_repos: [App-Empire-LLC/DevKit, App-Empire-LLC/appire_docs]
    branch_name: issue-DevKit-7
    parent: App-Empire-LLC/DevKit#2
    children: []
    status: not_started
  App-Empire-LLC/appire_docs#8:
    type: issue
    own_repos: [App-Empire-LLC/appire_docs]
    effective_repos: [App-Empire-LLC/appire_docs]
    branch_name: issue-appire_docs-8
    parent: App-Empire-LLC/DevKit#2
    children: []
    status: not_started
---
```

**Status enum**: `not_started` → `in_progress` → `in_review` → `merged`  
**Reordering**: edit `execution_order` directly in EPIC.md — DevKit reads it fresh on every invocation (no caching).

### WORKSPACE.md Additions

```yaml
is_epic: true
epic_top_issue: App-Empire-LLC/DevKit#42
```

---

## Commands

### Bootstrap

```bash
devkit bootstrap App-Empire-LLC/DevKit#42
```

- Detects sub-issues via GitHub API
- Computes effective_repos bottom-up for every graph node
- Creates workspace, one worktree per effective repo
- Creates all stacked branches (depth-first, parent before child)
- Writes EPIC.md and WORKSPACE.md
- Posts ack comments to every issue in the graph

**Flags**:
```bash
--no-epic        # treat as regular non-epic workspace
--no-recursive   # only direct children, skip nested epics
--no-ack         # skip GitHub comments
--dry-run        # print plan, no changes
```

### Sub-Checkout

```bash
devkit sub-checkout 7       # bare number
devkit sub-checkout #7      # with hash
devkit sub-checkout App-Empire-LLC/DevKit#7   # full ref
```

Switches all worktrees for repos in `effective(#7)` to `#7`'s branch in one command. Only checks dirty state in repos that will actually be modified. Only allowed for `current_issue` — serial enforcement ensures work proceeds in order.

### PR Create

```bash
devkit pr-create
devkit pr-create --dry-run
```

Opens one PR per repo in `effective(current_issue)`. Each PR targets the parent node's branch (never `main`, unless `current_issue` is the top epic). Sibling PRs across repos are cross-linked in their bodies.

### Sub-Merge

```bash
devkit sub-merge 7
```

Verifies all PRs for node #7 are merged on GitHub, marks #7 merged, advances `current_issue`. If all siblings of #7's parent are now merged, automatically opens PRs for the parent (cascade-up). Each level must be explicitly `sub-merge`d after its PRs are merged — cascade-up stops after one level.

When `execution_order` is exhausted, `current_issue` points to the top epic.

### Archive

```bash
devkit archive App-Empire-LLC/DevKit#42
```

Verifies all nodes in the epic graph have status `merged`, then moves the workspace to `_archived/`. `git worktree prune` runs in each upstream repo.

---

## Manual Rebase Recipe

Until `devkit epic-sync` ships (DevKit#47), use this recipe when `origin/main` advances and stacked branches need updating:

```bash
# For each affected repo, from inside its worktree:
cd <workspace>/<repo>

# 1. Fetch origin
git fetch origin

# 2. Rebase top epic branch onto origin/main
git checkout issue-<repo>-<top_N>
git rebase origin/main

# 3. Rebase sub-epic branch onto updated top epic branch
git checkout issue-<repo>-<sub_N>
git rebase issue-<repo>-<top_N>

# 4. Rebase active sub-issue branch onto updated parent
git checkout issue-<repo>-<issue_N>
git rebase issue-<repo>-<sub_N>
```

Repeat for each repo in the workspace. Force-push your branches (not main) after rebasing.

---

## References

- DevKit#14 — regular workspace structure (non-epic path, unchanged)
- DevKit#36 — workspace template stamping (used for epic workspaces too)
- DevKit#46 — case-insensitive owner/repo matching
- DevKit#47 — `devkit epic-sync` (automated stacked-rebase, deferred follow-up)
