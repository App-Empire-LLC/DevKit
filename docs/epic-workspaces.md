# Epic Workspace Model

**Issue**: [App-Empire-LLC/DevKit#13](https://github.com/App-Empire-LLC/DevKit/issues/13)
**Status**: Draft
**Date**: 2026-04-26

This design specifies how DevKit handles GitHub issues that have sub-issues — "epic" issues whose deliverable decomposes into multiple child work items, possibly spanning multiple repositories. It builds on the regular workspace model defined in [DevKit#14](https://github.com/App-Empire-LLC/DevKit/issues/14) and the SpecKit stamping model from [DevKit#36](https://github.com/App-Empire-LLC/DevKit/issues/36).

## Decisions Map

The nine "Decisions Needed" from [issue #13's body](https://github.com/App-Empire-LLC/DevKit/issues/13), each resolved by a section of this design.

| # | Decision (from issue body) | Resolved in |
|---|---|---|
| 1 | Confirm Option A as the model | §3 (Option B selected, not A); §4.1 (A rejected, losing-criteria documented) |
| 2 | TRUNK.md format specification | §10.1 (values at each level; format itself owned by #14 §4.2 per consulted version) |
| 3 | Sub-workspace directory structure (what gets stamped vs. inherited from parent) | §6 (sub-workspace layout with inheritance labels) |
| 4 | How `devkit bootstrap` detects epic vs. regular issue | §12 (algorithm + override flags + API-unavailable fallback); §13.1 (recursive bootstrap behavior) |
| 5 | SpecKit integration: `SPECIFY_FEATURE` or equivalent per sub-workspace | §17.1 (filesystem-path boundary; each sub gets its own `.specify/` and scratch git; `SPECIFY_FEATURE` is process-scoped) |
| 6 | Branch naming convention finalized | §8 (epic, sub-issue, spec branches with patterns + worked examples) |
| 7 | How `devkit archive` handles epic workspaces (atomic vs. incremental) | §14 (single-command atomic at the user-facing level; sequential children-then-parent internally) |
| 8 | Commands needed for epic branch management | §16 (four new subcommands: link-sub, unlink-sub, promote-to-epic, demote-from-epic; implementation deferred to follow-ups) |
| 9 | Do epic-level worktrees serve any purpose, or is the epic workspace just metadata + sub-workspaces? | §7 (yes, epic-level worktrees exist; the epic issue often has its own deliverable PR; "metadata-only epic dir" was Option D's premise, which collapsed — see §4.3) |

All nine decisions resolved with concrete section anchors. SC-003 satisfied.

---

## §1 Consulted Versions

External artifacts this design was drafted against. If any of these change materially, this design is re-opened (not silently amended in implementation).

| Source | Version | Snapshot date | Notes |
|---|---|---|---|
| DevKit#14 design | issue closed 2026-04-27; comment id `IC_kwDOQiNeWM8AAAABAbfdow`, 74,459 bytes | 2026-04-27 | Regular workspace structure + `.devkit/` config. Defines WORKSPACE.md, TRUNK.md, CLAUDE.md, PROJECTS.md, ACTORS.md schemas; bootstrap stamping flow; constitution/template propagation. |
| DevKit#36 issue body | OPEN, body 3,134 bytes, last edited 2026-04-25 | 2026-04-26 | Stamps `.specify/` and `.claude/commands/speckit.*.md` at workspace root. Hard prerequisite for SpecKit FRs in this design. |
| DevKit#37 issue body | OPEN, body 5,370 bytes, last edited 2026-04-25 | 2026-04-26 | Generalizes the hardcoded source path from #36 into three-layer `.devkit/` discovery. Hard prerequisite for §17.4 (template flow into sub-workspaces). |
| DevKit CLI | aidevkit 0.3.0 | 2026-04-26 | Commands present: `bootstrap`, `doctor`, `setup`, `sync`, `archive`, `preflight`, `status`, `add-repo`, `purge`, `uninstall`, `update`, `check-update`, `version`. Spec.md's earlier "v0.3 surface" enumeration omitted `setup`, `preflight`, and the `update`/`check-update`/`uninstall`/`version` family; this doc uses the full set. |
| GitHub sub-issue API | `GET /repos/{owner}/{repo}/issues/{N}/sub_issues` returning JSON array of issue objects | 2026-04-26 | Probed via `gh api repos/APP-EMPIRE-LLC/DevKit/issues/25/sub_issues` — returned 4 sub-issues (#21–#24). Endpoint is available on App Empire's plan. |

---

## §2 Comparative Matrix

Per spec FR-001, three options were evaluated against five weighted criteria. A fourth option (D — metadata-only epic dir + flat sub-workspaces) was surfaced and rejected during scoring; see §4.4.

### §2.1 Criteria

| # | Criterion | Weight | Anchor |
|---|---|---|---|
| 1 | **Branch-conflict risk** | 3 | Spec § Overview: cortex-agent-issue-2 failed on branch conflicts. The most operationally painful failure mode. |
| 2 | **Archive coherence** | 3 | DevKit v0.3 shipped `devkit archive <N>` as a single-command primitive. The epic case must preserve it. |
| 3 | **SpecKit compatibility** | 3 | Hard prerequisite per spec Dependencies. Design must compose with #36's stamping model without rework. |
| 4 | **Cognitive load** | 3 | Constitution Principle I (Single AI-First Operator) and II (Keep It Boring). The operator must hold the model in their head. |
| 5 | **Sandbox-container fitness** | 2 | codegates.ai vision: per-issue dirs are sandbox mount points. Lower weight because the codegates.ai roadmap has no current ETA. |

Total weight: 14.

### §2.2 Options

- **A — Hierarchical**: Epic workspace at `<workspaces_home>/<repo>-issue-<epic_N>/` with a `sub-workspaces/sub-issue-<M>/` subdirectory per sub-issue. Sub-issue branches cut from the epic branch. (Issue body's "preferred direction.")
- **B — Flat siblings**: Each sub-issue gets its own workspace at `<workspaces_home>/<repo>-issue-<M>/`, indistinguishable in directory shape from any other workspace. Linkage to the epic is via the WORKSPACE.md `parent_issue` field (defined by #14 §4.1). Sub-issue branches cut from main; PRs target the parent issue's branch. (Issue body's "Option B".)
- **C — Nested workspaces**: Workspace inside a workspace, sharing `.git/`, `.specify/`, and `CLAUDE.md` across nesting levels. Pre-rejected by the issue body; re-evaluated here per FR-001's "from scratch" mandate.

A fourth option **D — Metadata-only epic dir + flat sub-workspaces** was considered: an epic workspace dir holds only metadata (no worktrees, no specs/), and each sub-issue is a flat sibling per Option B. D collapsed into "B + epic-aware command behavior" once the epic dir's role was traced through (the epic issue itself often has its own deliverable PR — e.g., the design.md for #14 was authored in `DevKit-issue-14/` — so the epic dir cannot be metadata-only without reintroducing a separate "epic-host" workspace, which is just B with a flag). D is captured here for transparency; it is not scored as a separate row.

### §2.3 Scoring

Scale: 1 (poor) — 5 (excellent). Each cell carries a one-sentence justification.

| Criterion (weight) | A: Hierarchical | B: Flat siblings | C: Nested workspaces |
|---|---|---|---|
| Branch-conflict (3) | **2** — sub-issue branches cut from epic branch; when main advances, chained rebases (epic onto main, then each sub onto epic) | **4** — independent rebases; each sub cuts from main, rebases onto main directly, regardless of parent's state | **1** — multiple `.git/` interactions across nesting levels; SpecKit's CWD walk-up resolves ambiguously |
| Archive coherence (3) | **5** — `devkit archive <epic_N>` archives one directory; sub-workspaces inside are swept atomically | **3** — `devkit archive <epic_N>` walks `parent_issue` pointers to find children; multi-directory effect under one command, but more orchestration logic | **2** — multi-level archive: which level is the archive unit? Ambiguous |
| SpecKit compat (3) | **3** — works but requires nested stamping (`.specify/` at epic root AND at each sub-workspace root); #36's stamping flow needs to know about both layers | **5** — each flat sibling IS a regular #14/#36 workspace; zero rework | **1** — `.specify/` shadowing across nesting levels breaks SpecKit's template resolution; the canonical anti-pattern |
| Cognitive load (3) | **3** — hierarchy is intuitive but adds a directory level and a branch tier | **4** — uniform model: every workspace is a workspace; the only distinguishing feature of a sub-workspace is the `parent_issue` pointer in WORKSPACE.md | **1** — multi-level nesting forces the operator to track which `.git/` they're operating against |
| Sandbox fitness (2) | **4** — epic dir is one mount unit for the whole epic; sub-workspaces are sub-mounts of it | **5** — each sub-workspace mounts independently into a future per-issue agent container, matching the codegates.ai per-issue agent vision | **2** — nesting complicates mount boundaries; partial-mount cases (sub but not parent) are awkward |

### §2.4 Weighted Totals

| Option | 3·BC + 3·AC + 3·SC + 3·CL + 2·SF | Total |
|---|---|---|
| **A** | 3·2 + 3·5 + 3·3 + 3·3 + 2·4 = 6 + 15 + 9 + 9 + 8 | **47** |
| **B** | 3·4 + 3·3 + 3·5 + 3·4 + 2·5 = 12 + 9 + 15 + 12 + 10 | **58** |
| **C** | 3·1 + 3·2 + 3·1 + 3·1 + 2·2 = 3 + 6 + 3 + 3 + 4 | **19** |

### §2.5 Sensitivity

The selection is robust to scoring sensitivity. Even allowing A maximum-generous scoring on every criterion (5 across the board: 14·5 = 70), B's actual score (58) is closer to A's hypothetical ceiling than to A's actual score (47), and B retains its 11-point lead on the criteria that decided the matrix (SpecKit compat, branch-conflict, cognitive load, sandbox fitness). A would have to be re-imagined — sub-issue branches cut from main rather than from the epic branch, AND SpecKit stamping pre-flighted to handle two layers cleanly — to come within striking distance, and that re-imagining moves A toward B's topology anyway.

---

## §3 Selected Option

**B — Flat sibling sub-workspaces.**

Each sub-issue gets its own workspace at `<workspaces_home>/<repo>-issue-<M>/`, structurally identical to any regular workspace per #14. The link from a sub-workspace to its epic is the `parent_issue` field in WORKSPACE.md frontmatter (defined by #14 §4.1) and the optional `parent: <owner>/<repo>#<N>` second line in TRUNK.md (defined by #14 §4.2). The epic workspace itself is a regular workspace per #14 — no structural difference; it carries an `is_epic: true` flag in its WORKSPACE.md frontmatter (proposed addition; see §10.2) and may host its own deliverable work like any regular workspace.

Selection rationale, citing §2.4:

- **B beats A by 11 points** (58 vs. 47), driven primarily by SpecKit compatibility (5 vs. 3), branch-conflict risk (4 vs. 2), and cognitive load (4 vs. 3). A's archive-coherence advantage (5 vs. 3) is real but addressable via command-level orchestration rather than directory structure (see §13).
- **Zero SpecKit rework**: B inherits #36's stamping model unchanged for every workspace, sub or not. A would require #36 to stamp at two layers; that complication is not a deal-breaker but is unjustified given B's superior fit.
- **Independent rebases**: Sub-issue branches under B cut from main and rebase onto main when main advances. No chained rebase across an "epic branch tier." This matches the existing per-issue workflow (`workflow-per-issue-specs.md`) verbatim — sub-workspaces are per-issue workspaces.
- **Future sandbox fitness**: codegates.ai's per-issue agent containers map 1:1 onto flat sibling workspaces. Each container mounts one sub-workspace; orchestration across sub-workspaces is the parent agent's concern.

A's archive-coherence advantage is preserved in B by `devkit archive <epic_N>` walking `parent_issue` pointers: a single user-facing command, multi-directory effect. See §13.

---

## §4 Rejected Options

### §4.1 Option A (Hierarchical) — rejected

**Losing criteria**:

- **SpecKit compatibility (weight 3, A:3 vs. B:5)** — A requires #36 to stamp `.specify/` at two distinct roots (the epic workspace root AND each `sub-workspaces/sub-issue-M/` root). #36's current design stamps at one root. Either #36 grows two-layer awareness or A's sub-workspaces have to abandon the per-workspace `.specify/` pattern. Both are unjustified rework.
- **Cognitive load (weight 3, A:3 vs. B:4)** — A introduces a structurally distinct "epic workspace" type (carries sub-workspaces) and a "sub-workspace" type (lives inside an epic). Two concepts vs. B's one. The marginal cost is small per workspace but accumulates: every operator-facing command has to reason about both types.
- **Branch-conflict risk (weight 3, A:2 vs. B:4)** — A's strawman cuts sub-issue branches from the epic branch. When main advances mid-epic, the epic branch must rebase onto main, then in-flight sub-issue branches must rebase onto the new epic branch — a chained rebase. Under B, sub-issue branches cut from main directly and rebase onto main independently. The chained rebase under A has no offsetting benefit.

**Where A still wins**: archive coherence (5 vs. 3) — atomic single-directory archive. This is real but B addresses it at the command layer (§13) without paying A's costs at the topology layer.

**Verdict**: rejected.

### §4.2 Option C (Nested workspaces) — rejected

**Losing criteria**: every criterion (1, 2, 1, 1, 2). C's only conceptual advantage was "fewer top-level entries in `<workspaces_home>/`" which is not a criterion any user actually feels. C reintroduces every problem the per-issue workflow exists to fix (multi-level git surface, SpecKit ambiguity, cognitive overhead) and adds new ones (which `.git/` is the scratch git? which `.specify/` resolves at a given CWD?). Pre-rejection by the issue body was correct; the fresh evaluation confirms it.

**Verdict**: rejected.

### §4.3 Option D (Metadata-only epic + flat subs) — collapsed, not scored

**Why considered**: D appeared to combine A's archive coherence with B's SpecKit compatibility. The epic workspace would hold only metadata (WORKSPACE.md, child pointers, no worktrees, no specs/), and each sub-issue would be a flat sibling per B.

**Why collapsed**: the epic issue itself often has its own deliverable PR. The design.md for #14 was authored in `DevKit-issue-14/`'s DevKit worktree on branch `issue-DevKit-14`. Under D, the epic workspace has no worktrees — so the epic-issue's own work has no home. Three resolutions were considered:

- D1: the epic workspace gains worktrees (just like a regular workspace). Now D = B + an `is_epic` flag, which is exactly the chosen B-with-epic-features model below.
- D2: the epic-issue's work happens in one of the sub-workspaces. Awkward — the epic-issue isn't a sub-issue's concern, and choosing which sub-workspace to use is arbitrary.
- D3: a separate "epic-host" workspace co-located with the metadata workspace. Two epic workspaces per epic. Unjustified complexity.

D collapses into B once D1 is chosen, so D is not scored as a separate matrix row. The B-with-epic-aware-features synthesis (an `is_epic` flag in WORKSPACE.md, plus epic-aware orchestration in `devkit bootstrap`/`archive`/`status`) is the actual selected model — see §3.

---

## §5 Epic Workspace Layout (delta over #14)

**No structural delta.** An epic workspace is a regular workspace per #14 §2. Same root files (CLAUDE.md, WORKSPACE.md, TRUNK.md, PROJECTS.md, ACTORS.md, .gitignore), same `.git/` scratch repo, same `.specify/` and `.claude/commands/` from #36 stamping, same worktree mounts for affected repos, same `specs/` and `transcripts/` directories.

The only differences are in **frontmatter values and aggregation behavior**, not in file layout:

1. WORKSPACE.md frontmatter carries `is_epic: true` (proposed addition to #14's schema — see §10.2).
2. WORKSPACE.md frontmatter optionally carries `child_sub_workspaces: [<owner>/<repo>#<N>, ...]` listing the sub-issues bootstrapped from this epic (§10.3).
3. `devkit status`, `devkit archive`, and `devkit bootstrap` consult these fields to surface epic-aware behavior (§§13, 14, 15).

Worked example — `DevKit-issue-13/` if #13 had sub-issues #88 and #89:

```text
<workspaces_home>/DevKit-issue-13/
├── CLAUDE.md
├── WORKSPACE.md             # is_epic: true; child_sub_workspaces: [#88, #89]
├── TRUNK.md                 # main
├── PROJECTS.md
├── ACTORS.md
├── .git/
├── .gitignore
├── .specify/                # per #36
├── .claude/commands/        # per #36
├── DevKit/                  # worktree on issue-DevKit-13
├── appire_docs/             # worktree on issue-DevKit-13
└── specs/13-epic-workspace-model/
```

#13 itself is not an epic (sub-issue API returned 0 sub-issues at consulted-version time per §1), so the example is hypothetical for illustration. Drafted against #14 design as captured in §1.

**Why no `sub-workspaces/` subdirectory**: per §3 and §4.1, sub-workspaces live as flat siblings under `<workspaces_home>/`, not nested under the epic. The epic's WORKSPACE.md tracks the relationship via `child_sub_workspaces`; the filesystem hierarchy stays flat.

---

## §6 Sub-Workspace Layout

**No structural delta either.** A sub-workspace is a regular workspace per #14 §2, sitting at `<workspaces_home>/<sub_repo>-issue-<sub_M>/` as a flat sibling of every other workspace. Inheritance labels per FR-003:

| File / dir | Inheritance | Source |
|---|---|---|
| `CLAUDE.md` | from #14 (template) | `.devkit/templates/CLAUDE.md.template` interpolated at bootstrap. The template's `{{trunk_branch}}` token resolves to the parent's branch (e.g., `issue-DevKit-13`), not `main`. |
| `WORKSPACE.md` | from #14 (generated) | Generated at bootstrap. `parent_issue` and `parent_workspace_path` fields populated; `is_epic` is `false` (or omitted, treating absence as false). |
| `TRUNK.md` | from #14 (generated) | Two lines per #14 §4.2: parent's branch on line 1, `parent: <owner>/<repo>#<N>` on line 2. |
| `PROJECTS.md` | from #14 (template) | Verbatim copy of `.devkit/templates/PROJECTS.md`, identical to a regular workspace's copy. |
| `ACTORS.md` | from #14 (template) | Verbatim copy. |
| `.gitignore` | from #14 (template) | Verbatim copy. |
| `.git/` | from #14 (scratch) | `git init --quiet` per #14 §5.2. |
| `.specify/` | from #14 (SpecKit snapshot per #36) | Each sub-workspace gets its own snapshot. See §16.1. |
| `.claude/commands/speckit.*.md` | from #14 (SpecKit snapshot per #36) | Each sub-workspace gets its own snapshot. |
| `<repo>/` worktrees | fresh per sub-issue | One per repo in the sub-issue's `## Affected Repos` list (or `--repos` override at bootstrap). |
| `specs/` | fresh per sub-issue | Created lazily by `/speckit.specify`. |
| `transcripts/` | fresh per sub-issue | Optional. |

**No fields are inherited from the parent epic workspace at the file level.** The sub-workspace is structurally autonomous; the parent linkage exists only in `WORKSPACE.md.parent_issue` / `WORKSPACE.md.parent_workspace_path` / `TRUNK.md` line 2. This is what makes each sub-workspace independently sandboxable per Constitution-aligned codegates.ai future-fit.

**Worked example** — sub-issue `App-Empire-LLC/DevKit#88` of epic `DevKit#13`:

```text
<workspaces_home>/DevKit-issue-88/
├── CLAUDE.md                # {{trunk_branch}} = issue-DevKit-13
├── WORKSPACE.md             # parent_issue: App-Empire-LLC/DevKit#13
│                            # parent_workspace_path: ../DevKit-issue-13/
│                            # is_epic: false
├── TRUNK.md                 # line 1: issue-DevKit-13
│                            # line 2: parent: App-Empire-LLC/DevKit#13
├── PROJECTS.md
├── ACTORS.md
├── .git/
├── .gitignore
├── .specify/                # own snapshot per #36
├── .claude/commands/        # own snapshot per #36
└── <affected repos>/        # one worktree per affected repo, on issue-DevKit-88
```

---

## §7 Epic-Level Worktrees

**Yes, the epic workspace has worktrees**, on the same `issue-<repo>-<N>` branch as a regular workspace, mounted exactly the way #14 §5.2 describes. The "epic workspace" is not a metadata-only directory — it carries the parent issue's own deliverable work (PRs against the parent issue's branch).

The role beyond "merge target":

- **The parent issue often has its own deliverable PR.** The design doc this current spec produces lands as a PR on `issue-DevKit-13` from the `DevKit-issue-13/DevKit/` worktree. Without epic-level worktrees, that PR has nowhere to be authored.
- **`devkit add-repo` works the same way.** A maintainer who needs to add a repo's worktree to the epic for cross-cutting work (e.g., updating shared docs that span the whole epic) does so identically to a regular workspace.
- **The epic branch is the merge target for sub-issue PRs.** Per §9, sub-issue PRs target `issue-<repo>-<epic_N>`. That branch needs to exist on every repo affected by the epic — the worktree is what creates it.

This is the practical resolution of the Option D collapse documented in §4.3: "epic = workspace + flag" rather than "epic = metadata-only orchestrator."

---

## §8 Branch Naming

### §8.1 Epic Branch

**Format**: `issue-<IssueHomeRepo>-<N>`. Identical to a regular per-issue branch. The "epic" status of the issue does not change the branch name — naming is a function of the issue's home repo and number, not its sub-issue cardinality.

**Worked example**: `issue-DevKit-13` (epic with home repo DevKit and number 13).

**Where `<IssueHomeRepo>` comes from**: the issue's home repo, not the worktree's host repo. This rule (carried verbatim from per-issue workflow memory and #14 §5.2) prevents collisions when an issue affects multiple repos: every worktree in the epic workspace, regardless of which repo it mounts, lives on the same branch name `issue-<IssueHomeRepo>-<N>`.

**Cut from**: `origin/main`. Per #27, bootstrap bases new branches on `origin/main` (not local `main`).

### §8.2 Sub-Issue Branch

**Format**: `issue-<SubIssueHomeRepo>-<M>`. Same shape as an epic branch — a sub-issue is just an issue, and per the per-issue convention every issue gets a branch named for its home repo and number.

**Worked example**: `issue-DevKit-88` for sub-issue `App-Empire-LLC/DevKit#88` of epic `DevKit#13`.

**Cut from**: `origin/main`, **not from the epic branch**. This is the key topology decision of Option B (§3) — independent rebases. Sub-issue branches advance and rebase against `main` regardless of the parent epic's branch state.

**PR target**: the parent's epic branch (`issue-<EpicHomeRepo>-<EpicN>`), not `main`. The sub-issue's TRUNK.md (line 1) records this target. The PR review happens per sub-issue; the parent issue's PR (when finally cut) carries the aggregated diff.

### §8.3 Spec Branch

**Format**: delegated to SpecKit's `create-new-feature.sh`, which produces `NNN-<short-name>` (e.g., `001-spec-name`). #36's stamping model places `.specify/` at the workspace root, so when SpecKit cuts a new branch via `git checkout -b`, the branch lives in **the workspace's scratch `.git/`**, not in any worktree's git repo.

**Cut from**: whatever HEAD points at in the workspace scratch git at the time `/speckit.specify` runs. In practice this is whatever `create-new-feature.sh` produces; the spec branch is a SpecKit-internal artifact, not a code-bearing branch.

**Lives in**: the workspace's scratch `.git/` only. Never pushed. Never merged. The spec branch's job is solely to satisfy SpecKit's "I'm in a feature branch" expectation; the actual code commits land on `issue-<repo>-<N>` in the worktree, not on the spec branch.

**Per #36's invariant**: the spec branch never touches any per-issue worktree's git repo. The fragmenting-branch failure mode from issue #3 is structurally prevented under #36 + this design.

---

## §9 Merge Flow

The complete flow from spec branch (where SpecKit cut its branch) all the way to `main`. Numbered steps with the actor performing each.

### §9.1 Sub-issue work

For each sub-issue under an epic:

1. **Code commits land on `issue-<SubRepo>-<M>` in the sub-workspace's worktree.** Actor: implementer Claude (or human dev, whichever).
2. **Push `issue-<SubRepo>-<M>` to origin.** Actor: implementer.
3. **Open a PR: `issue-<SubRepo>-<M>` → `issue-<EpicRepo>-<EpicN>`** (the parent epic's branch, recorded as the trunk in the sub-workspace's TRUNK.md line 1). Actor: implementer (`gh pr create --base issue-<EpicRepo>-<EpicN>`).
4. **Review and merge the sub PR.** Actor: Max (review by reading the diff; merge via `gh pr merge` or GitHub UI).
5. **Sub-workspace becomes archive-ready** — the sub-issue is closed by the merged PR; the sub-workspace can be archived next time `devkit archive <epic_N>` runs (§13).

### §9.2 Epic work

Once all sub-issue PRs have merged into `issue-<EpicRepo>-<EpicN>`:

6. **Optional epic-level commits.** If the epic itself has a deliverable that doesn't belong to any sub-issue (e.g., a top-level integration commit, an aggregated CHANGELOG entry, the epic's own design doc), those commits land on `issue-<EpicRepo>-<EpicN>` in the epic workspace's worktree. Actor: implementer in the epic workspace.
7. **Push `issue-<EpicRepo>-<EpicN>` to origin** (already pushed if any sub merged into it; this step is a refresh).
8. **Open a PR: `issue-<EpicRepo>-<EpicN>` → `main`.** Actor: implementer (`gh pr create --base main`).
9. **Review and merge the epic PR.** Per spec Assumption "merges up the branch hierarchy are human-authored pull requests, not automated." Actor: Max. Because every sub-issue has already been reviewed in step 4, this merge is often a fast-forward style review focused on integration, not per-line diff.
10. **Epic workspace becomes archive-ready.** `devkit archive <epic_N>` validates and sweeps everything (§13).

### §9.3 Spec branch (if any)

The spec branch lives only in the workspace scratch `.git/`. It does not participate in the merge flow above. SpecKit may use it internally (e.g., for `find_feature_dir_by_prefix` in `common.sh`); DevKit does not push, merge, or otherwise act on it.

### §9.4 Diagram

```text
spec branch (scratch .git/)        [never pushed, never merged]
    │
    │  (SpecKit-internal; informational only)
    │
issue-<SubRepo>-<M>      ─PR─►   issue-<EpicRepo>-<EpicN>      ─PR─►   main
   (sub-workspace                  (epic workspace                    (origin)
    worktree, cut from               worktree, cut from
    origin/main)                     origin/main; receives
                                     all sub-PR merges)
```

Each arrow is a human-authored PR. Each base is recorded in the source workspace's TRUNK.md.

---

## §10 Metadata File Values

#14 §4 owns the formats of TRUNK.md and WORKSPACE.md. This design specifies the **values** those files take at each level of an epic (epic root, sub-workspace), and proposes one new WORKSPACE.md field for `is_epic`.

### §10.1 TRUNK.md values

Per #14 §4.2 format (one line + optional second line):

| Workspace level | TRUNK.md content |
|---|---|
| Regular workspace (no epic) | `main` |
| Epic workspace | `main` (an epic's own merge target is still `main`; the epic is the top of the sub-issue tier but its own PR base is `main`) |
| Sub-workspace | Line 1: `issue-<EpicRepo>-<EpicN>` (the parent epic's branch). Line 2: `parent: <owner>/<repo>#<EpicN>` |

The rule that determines the value: TRUNK.md line 1 is the branch the workspace's PR targets. Regular and epic workspaces target `main`; sub-workspaces target their parent's branch.

### §10.2 WORKSPACE.md `is_epic` field (proposed addition)

#14 §4.1 lists 14 frontmatter fields. None distinguish an epic workspace from a regular one. This design proposes one new field:

| Field | Type | Req? | Description |
|---|---|---|---|
| `is_epic` | bool | optional (default `false`) | `true` when this workspace's issue has sub-issues at bootstrap time and the design's epic-aware behavior should apply. Set by `devkit bootstrap` when the sub-issue API returns ≥1 sub-issue (§12.1). May be flipped manually by a maintainer if a regular workspace later acquires sub-issues, via a `devkit promote-to-epic` command (§15). |

**Why a separate field rather than inferring from `child_sub_workspaces` length**: the inference works for the fully-bootstrapped case but breaks for the edge case "epic with zero sub-workspaces yet bootstrapped" (e.g., `devkit bootstrap <epic_N> --no-recursive` where the operator wants the epic workspace alone first). Explicit beats implicit.

**Proposal status**: at consulted-version time (§1), #14 was closed without this field. The proposal is recorded here as the canonical addition; a follow-up to #14 (either reopened or as a new amendment issue) can adopt it. Until then, the field is defined and consumed by this design's described commands (§13–§15) only.

### §10.3 WORKSPACE.md `child_sub_workspaces` field (proposed addition)

| Field | Type | Req? | Description |
|---|---|---|---|
| `child_sub_workspaces` | list of strings | optional (only when `is_epic: true`) | Each entry is `<owner>/<repo>#<N>` of a sub-issue whose workspace was bootstrapped from (or linked to) this epic. Maintained by `devkit bootstrap` (when sub-workspaces are auto-created) and `devkit link-sub` (§15). Used by `devkit archive <epic_N>` to find the sub-workspaces to sweep, and by `devkit status` for hierarchy rendering. |

**Why a list of issue refs and not paths**: paths can change (a workspace can be archived). Issue refs are stable. Paths are reconstructible from `parent_workspace_path` in each child's WORKSPACE.md (#14 §4.1).

### §10.4 Cross-section consistency

- WORKSPACE.md.is_epic == true ⟺ this issue has sub-issues recorded in `child_sub_workspaces`.
- For each sub in `child_sub_workspaces`, the sub-workspace at `<workspaces_home>/<sub_repo>-issue-<M>/` exists AND its WORKSPACE.md.parent_issue points back at this epic.
- TRUNK.md line 1 of the epic workspace == `main` (epics target main).
- TRUNK.md line 1 of every sub-workspace listed in `child_sub_workspaces` == `issue-<EpicRepo>-<EpicN>`.

`devkit status` validates these invariants on read; divergence is surfaced as a warning, not silently masked.

### §10.5 Additional metadata files

**No additional files beyond #14's set are stamped into an epic workspace or sub-workspace.** The two proposed fields (§10.2, §10.3) live in the existing WORKSPACE.md, not in a new file. Adding a `SUB_WORKSPACES.md` index file was considered and rejected: the data already exists in `child_sub_workspaces` (machine-parseable) and the per-child `parent_issue` fields (cross-checkable); a separate file would only add a fourth source of truth that can drift.

---

## §11 Note on M4 Guard

Tasks T021–T024 in `tasks.md` carried an "Option-B guard" added during analyze remediation (M4): "if Option B was selected, state explicitly that bootstrap/archive/status/new-subcommands behave identically to the regular case and collapse the section body." The guard assumed a strict interpretation of B where epic = tracking artifact only and DevKit had no epic-specific behavior to add.

Per §3, the actual selection is **B-with-epic-aware-features** — Option B's flat-sibling topology, plus an `is_epic` flag and orchestration commands that consult it. The guard doesn't fire as written: epic-aware behavior IS present and is documented in §§12–15. This is a deliberate design choice (Option D collapse, §4.3) — not a violation of the guard.

The guard's value was as a check against unjustified epic-special-casing: if the matrix had picked a stricter B, sections §§12–15 would collapse. The selection happened to land on B-with-features because the archive-coherence concern (§2.3 row 2) needed command-level resolution rather than topology-level resolution.

---

## §12 Epic Detection

### §12.1 Algorithm

`devkit bootstrap <owner/repo>#<N>` decides whether to apply epic-aware behavior using the following pseudocode:

```text
def is_epic(owner, repo, n, force_epic_flag, no_epic_flag):
    if no_epic_flag:
        return False  # explicit override; treat as regular even if API says otherwise
    if force_epic_flag:
        return True   # explicit override; useful when API is unavailable
    try:
        sub_issues = gh_api("repos/{owner}/{repo}/issues/{n}/sub_issues")
        return len(sub_issues) > 0
    except APIUnavailable:
        return False  # safe default: treat as regular; print a warning
```

Probe verification (§1): the endpoint `GET /repos/{owner}/{repo}/issues/{N}/sub_issues` returned a JSON array on App Empire's plan as of 2026-04-26. The endpoint is stable enough to depend on.

### §12.2 Override flags

| Flag | Effect | Use case |
|---|---|---|
| `--epic` | Force `is_epic = true` regardless of API result | Pre-bootstrap an issue that doesn't yet have sub-issues recorded but will; or work around API unavailability |
| `--no-epic` | Force `is_epic = false` regardless of API result | Bootstrap just the parent issue's workspace without engaging the recursive sub-bootstrap (§13.2); useful for incremental epic setup |
| `--no-recursive` | When `is_epic = true`, do NOT auto-bootstrap sub-workspaces; bootstrap only the epic dir itself | Same as `--no-epic` for this run but preserves the epic flag for later sub-bootstrap |

### §12.3 Fallback when API unavailable

If `gh api` for the sub-issue endpoint fails (network down, plan downgrade, GitHub deprecates the endpoint), bootstrap defaults to **non-epic**, prints a warning to stderr, and continues. The warning text:

```
[devkit] warning: could not query sub-issues for App-Empire-LLC/DevKit#13.
  Reason: <gh error message>
  Treating as a regular (non-epic) issue. If this issue has sub-issues, re-run with
  --epic and use `devkit link-sub` to attach sub-workspaces manually.
```

Bootstrap MUST NOT silently fail or block on API unavailability — the regular workspace path always works.

---

## §13 Bootstrap Behavior

### §13.1 Outputs (epic case, recursive default)

When `is_epic = true` and `--no-recursive` is NOT passed, `devkit bootstrap <owner/repo>#<epic_N>` produces:

1. **The epic workspace** at `<workspaces_home>/<repo>-issue-<epic_N>/` — every artifact #14 §5.2 lists for a regular workspace, with two additions to WORKSPACE.md frontmatter:
   - `is_epic: true`
   - `child_sub_workspaces: [<owner>/<repo>#<sub_M> for each sub-issue returned by the API]`
2. **One sub-workspace per sub-issue** at `<workspaces_home>/<sub_repo>-issue-<sub_M>/` — each is itself a #14 regular workspace, plus:
   - `parent_issue: <owner>/<repo>#<epic_N>` in WORKSPACE.md frontmatter
   - `parent_workspace_path: ../<repo>-issue-<epic_N>/` in WORKSPACE.md frontmatter
   - `is_epic: false` (or omitted)
   - TRUNK.md two-line form per §10.1
3. **An ack comment posted on every issue touched** (the epic + each sub) — see §13.3 for field set.

When `--no-recursive` is passed, only step 1 runs. Sub-workspaces can be added later via `devkit bootstrap <sub_M>` (which infers parent via the sub-issue API, or via explicit `--parent <epic_N>` flag) followed by `devkit link-sub` if auto-link doesn't fire (§15).

### §13.2 Outputs (regular case)

When `is_epic = false`, bootstrap is **identical to today's regular case** per #14 §5.2. No changes. SC-007 (non-regression) hinges on this — see §19.

### §13.3 Ack comment field set

Today's regular bootstrap posts an ack comment on the issue (visible verbatim in this very workspace's issue #13 thread, comment id `IC_kwDOQiNeWM8AAAABALuoyQ` from 2026-04-23). The fields it carries today:

- "Bootstrap started by claude."
- Worktree path: `<workspaces_home>/<repo>-issue-<N>`
- Affected repos list

For an epic bootstrap, the ack comment is extended with **two additional fields**, posted on the epic issue:

- `is_epic: true`
- `Sub-issues bootstrapped: <owner>/<repo>#<sub_M>, ...` (or `Sub-issues bootstrapped: none (--no-recursive passed)`)

For each sub-issue bootstrapped recursively, the ack comment posted on the sub-issue is **identical to today's regular ack comment plus one additional field**:

- `Parent epic: <owner>/<repo>#<epic_N>`

All ack-comment posts are skippable with `--no-ack` (existing flag, preserved verbatim per #14 §5.2's "Side effect" note).

### §13.4 Worked example

Hypothetical: `devkit bootstrap App-Empire-LLC/DevKit#13` if #13 had sub-issues #88, #89 affecting DevKit only.

**Filesystem effects**:
```text
<workspaces_home>/DevKit-issue-13/    # epic; is_epic: true; child_sub_workspaces: [#88, #89]
<workspaces_home>/DevKit-issue-88/    # sub of #13; parent_issue: ...DevKit#13
<workspaces_home>/DevKit-issue-89/    # sub of #13; parent_issue: ...DevKit#13
```

**GitHub effects**:
- Comment on #13: existing fields + `is_epic: true; Sub-issues bootstrapped: ...DevKit#88, ...DevKit#89`
- Comment on #88: existing fields + `Parent epic: ...DevKit#13`
- Comment on #89: existing fields + `Parent epic: ...DevKit#13`

**Branches**:
- `issue-DevKit-13` cut from `origin/main` in DevKit/, appire_docs/ (epic's affected repos)
- `issue-DevKit-88` cut from `origin/main` in DevKit/ (sub #88's affected repo)
- `issue-DevKit-89` cut from `origin/main` in DevKit/

---

## §14 Archive Behavior

### §14.1 Atomicity

**`devkit archive <epic_N>` is atomic at the user-facing-command level**: a single command sweeps the epic workspace and all child sub-workspaces. Internally it is sequential (sub-workspaces archived first, epic last), and it refuses to start unless every sub-workspace is archive-ready.

This preserves the user-facing primitive established by DevKit v0.3 (`devkit archive <N>` archives one issue's workspace) while extending it to the epic case. The matrix (§2.3 row 2) gave Option A 5 vs. B 3 on archive coherence; this §14 design lifts B's effective archive coherence by orchestrating across multiple directories under one command.

### §14.2 Precondition checks

Before any filesystem moves, `devkit archive <epic_N>` validates:

1. **The epic workspace exists** at `<workspaces_home>/<repo>-issue-<epic_N>/` and its WORKSPACE.md has `is_epic: true`.
2. **Every entry in `child_sub_workspaces`** has a corresponding sub-workspace directory at the path computed from `parent_workspace_path` lookup. Missing children: warning, not error (see §14.5).
3. **Every sub-issue's PR has been merged** into `issue-<EpicRepo>-<EpicN>`. Checked via `gh pr list --repo <SubRepo> --base issue-<EpicRepo>-<EpicN> --state merged --search 'head:issue-<SubRepo>-<SubM>'`. Refuses if any sub-PR is still open.
4. **The epic's PR has been merged** into `main`. Checked similarly.
5. **No uncommitted/unpushed work** in any worktree across the epic + sub-workspaces (delegated to the existing per-workspace check `devkit archive` already runs).

If any check fails, archive aborts with a per-failure error message naming the offending workspace and what's missing. No partial moves happen.

### §14.3 GitHub mutations

For each child sub-workspace (in dictionary order of issue number for determinism):
1. Post the sub's spec.md content as a comment on the sub-issue (existing v0.3 behavior of `devkit archive`).
2. (Optional) Mark the sub-issue closed via `gh issue close --reason completed` if not already closed.

For the epic workspace:
3. Post the epic's spec.md content as a comment on the epic issue.
4. (Optional) Close the epic issue.

The "post spec content as comment" step is identical to today's `devkit archive` behavior (#33). The "close issue" step is preserved if it exists today, or skipped if `devkit archive` doesn't currently close (defer to existing v0.3 behavior).

### §14.4 Filesystem moves

For each child (in same order):
1. `mv <workspaces_home>/<sub_repo>-issue-<sub_M>/ <workspaces_home>/_archived/<sub_repo>-issue-<sub_M>-<archive_date>/`
2. Verify the move succeeded (target exists; source gone).

For the epic:
3. `mv <workspaces_home>/<repo>-issue-<epic_N>/ <workspaces_home>/_archived/<repo>-issue-<epic_N>-<archive_date>/`

Order matters: children before parent. If the parent moved first and a child sweep failed mid-flight, the parent's `child_sub_workspaces` would point at children that may no longer match the listed paths (post-move). Children-first preserves the parent's intactness as a recovery anchor.

### §14.5 Edge cases at archive time

- **Missing child sub-workspace** (the child dir doesn't exist; user removed it manually): warning to stderr, continue with remaining children. The epic's `child_sub_workspaces` list is updated to reflect reality (entry removed) before archive of the epic itself.
- **Extra sub-workspace** (a workspace exists with `parent_issue: <epic_N>` but isn't in `child_sub_workspaces`): warning, **do not auto-include**. The mismatch indicates manual link state; require `devkit link-sub` to be run before retrying archive, or `--include-orphans` flag to sweep them anyway.
- **Partial archive recovery**: if `devkit archive` failed mid-sweep (e.g., network down during a `gh issue comment` post), the next run picks up: archived children stay archived; remaining children + epic continue. Idempotent.

### §14.6 Regular case

When `devkit archive <N>` runs against an issue that is NOT an epic (`is_epic: false` or absent), behavior is **identical to today's v0.3 archive**. Zero behavioral change. SC-007.

---

## §15 Status Behavior

### §15.1 Differences for epics

`devkit status` (today: lists every active workspace under `<workspaces_home>/`) gains hierarchy rendering when any active workspace has `is_epic: true`:

- Epics are rendered as headers with their child sub-workspaces indented underneath.
- The header line for an epic includes an aggregate sub-PR-progress indicator (e.g., `2/3 sub-PRs merged`).
- Workspaces with `parent_issue` set are NOT rendered at the top level — they appear under their parent's header.
- Regular workspaces (neither epic nor sub) render at the top level identically to today.

**Rendered example**:
```text
$ devkit status

App-Empire-LLC/DevKit#13 (epic; 2/3 sub-PRs merged)  branch: issue-DevKit-13  trunk: main
  ├─ App-Empire-LLC/DevKit#88                        branch: issue-DevKit-88  trunk: issue-DevKit-13   PR: merged
  ├─ App-Empire-LLC/DevKit#89                        branch: issue-DevKit-89  trunk: issue-DevKit-13   PR: merged
  └─ App-Empire-LLC/DevKit#90                        branch: issue-DevKit-90  trunk: issue-DevKit-13   PR: open

App-Empire-LLC/CallScribe#42                          branch: issue-CallScribe-42  trunk: main          PR: open
```

### §15.2 Non-regression

When no active workspace has `is_epic: true`, `devkit status` output is identical to today's v0.3 output. Workspaces with `parent_issue` set in absence of any epic header (orphaned subs — edge case) render at the top level with a `(orphan: parent <epic_N> not found)` annotation.

---

## §16 New Subcommands

The following subcommands are identified as needed under this design. Each carries a one-line purpose. Implementation is **deferred to follow-up DevKit issues** — this spec only names them per FR-016.

| Command | Purpose |
|---|---|
| `devkit link-sub <sub_workspace> <epic_workspace>` | Manually attach a sub-workspace to an epic by setting `parent_issue` / `parent_workspace_path` on the sub and adding the sub to the epic's `child_sub_workspaces`. Use case: sub-issues created after epic bootstrap. |
| `devkit unlink-sub <sub_workspace>` | Detach a sub-workspace from its epic. Use case: sub-issue cancelled but workspace kept around for reference; or sub-issue reassigned to a different epic. Does not delete files; only mutates frontmatter. |
| `devkit promote-to-epic <issue_ref>` | Flip `is_epic: false → true` on a workspace's WORKSPACE.md. Use case: a regular issue later acquires sub-issues. After running, the operator typically follows with `devkit bootstrap <sub_M>` for each new sub. |
| `devkit demote-from-epic <issue_ref>` | Flip `is_epic: true → false`. Use case: an epic that lost all its sub-issues (closed/cancelled). Refuses if `child_sub_workspaces` is non-empty (run `devkit unlink-sub` for each first). |

These commands modify only WORKSPACE.md frontmatter; no branch operations, no GitHub calls, no filesystem moves. They are deliberately small. Existing `devkit bootstrap` flag overrides (`--epic`, `--no-epic`, `--no-recursive`, §12.2) cover most workflows; the four new commands above handle the post-bootstrap reconfiguration cases.

The `devkit refresh-issue-meta` command from #14 §9 row 2 (capturing issue title freshness in WORKSPACE.md) is orthogonal and not enumerated here.

---

## §17 SpecKit Integration

### §17.1 Isolation across sub-workspaces

**Each sub-workspace gets its own stamped `.specify/` and its own scratch `.git/`.** Sub-workspaces do NOT share the parent epic's stamped speckit; each is a structurally independent #14/#36 workspace.

The isolation mechanism is **filesystem-path boundary**: each workspace has its own `<workspace>/.specify/` directory, its own `<workspace>/.git/` scratch repo, and its own `<workspace>/specs/`. SpecKit's `find_feature_dir_by_prefix` and `get_current_branch` (in `common.sh`) operate against whatever workspace the user `cd`'d into. Concurrent SpecKit invocations across sibling sub-workspaces cannot collide because they touch different filesystem paths and different scratch gits.

The `SPECIFY_FEATURE` environment variable (or its successor) is process-scoped, not workspace-scoped — if the operator launches two Claude sessions in two different sub-workspaces, each session's environment is independent. No cross-session contamination is possible at the env-var level.

This decision is consistent with #36's invariant: SpecKit operates against the workspace's scratch git, never against any per-issue worktree's git. Under Option B, "the workspace" is unambiguously each sub-workspace.

### §17.2 Where SpecKit runs

**SpecKit can run at both the epic level and the sub-workspace level, with distinct meanings:**

- **Sub-workspace level (primary use)**: each sub-issue's implementation work runs through SpecKit normally — `/speckit.specify` → `/plan` → `/tasks` → `/implement` — producing artifacts in `<sub-workspace>/specs/<NN>-<short>/`. This is the scope-of-work spec for that sub-issue.
- **Epic level (secondary use)**: the epic itself may have a spec, addressing concerns that span sub-issues — e.g., the cross-cutting design decision documented in this very file is the spec for issue #13 even though #13 is treated structurally as a regular workspace (with no sub-issues at consulted-version time). For an epic that DOES have sub-issues, an epic-level spec might capture: the sub-issue decomposition rationale, integration test plans, cross-cutting decisions that bind multiple sub-specs.

There is no requirement that an epic have its own spec. Many epics will have sub-issue specs only, with the epic issue serving as a tracking umbrella.

### §17.3 Artifact paths

| Spec scope | Path |
|---|---|
| Epic-level spec | `<workspaces_home>/<repo>-issue-<epic_N>/specs/<NN>-<short>/spec.md` (and `plan.md`, `tasks.md`, etc.) |
| Sub-issue spec | `<workspaces_home>/<sub_repo>-issue-<sub_M>/specs/<NN>-<short>/spec.md` |
| Regular issue spec | `<workspaces_home>/<repo>-issue-<N>/specs/<NN>-<short>/spec.md` (unchanged from #14) |

All paths are workspace-rooted per #36. No spec lives outside its workspace; no spec is shared across workspaces. The `specs/` directory is gitignored at the workspace root (per #14 §5.2 "`.gitignore`") — specs are ephemeral artifacts; the durable record is the issue comment posted at archive time.

### §17.4 `.devkit/` template flow into sub-workspaces

**Each sub-workspace re-resolves `.devkit/` at sub-workspace creation time.** Sub-workspaces do NOT inherit a snapshot from the parent epic.

**Why re-resolve rather than inherit**: re-resolution is the simpler invariant. Every workspace, regardless of whether it's a sub or a regular workspace, runs the same `.devkit/` discovery flow (per #37's three-layer model: walk-up from CWD, `$DEVKIT_CONFIG_DIR`, `~/.config/devkit/`). The outputs of that resolution are stamped into the workspace at bootstrap. There is no "inherited from parent" code path — a sub-workspace is identical to a regular workspace at the bootstrap-flow level.

**Trade-off**: drift safety vs. consistency with parent.

- **Drift safety (re-resolve wins)**: if `.devkit/templates/` was updated between when the epic was bootstrapped and when a new sub-workspace is bootstrapped mid-epic, the sub-workspace gets the newer template. The maintainer's intent (newer templates are the canonical source) is honored.
- **Consistency with parent (inherit wins, but this design rejects it)**: under inheritance, all sub-workspaces of a given epic share the same template snapshot as the epic. The argument: "an epic is a coherent unit; mid-epic template drift is undesirable." This argument is rejected for two reasons:
  1. #14 §6.2 already establishes that template propagation is "frozen at bootstrap, opt-in refresh." A sub-workspace bootstrapped mid-epic *should* get the current `.devkit/templates/` because that IS the maintainer's most recent intent. If the maintainer wants the sub-workspace to match the parent's template, they explicitly run `devkit refresh-templates` on the sub after bootstrap (or downgrade `.devkit/templates/` to the parent's snapshot, which they shouldn't).
  2. Inheritance introduces a "where did this template come from?" question that re-resolution doesn't have. Re-resolution always answers: from the resolved `.devkit/` at the moment this workspace was bootstrapped.

The sub-workspace's `template_stamp_sha` field in WORKSPACE.md (per #14 §4.1) records the SHA of `.devkit/templates/` at sub-bootstrap time, which may differ from the parent's `template_stamp_sha`. `devkit status` should display this delta in the hierarchy rendering when present, so the maintainer knows two workspaces in the same epic have different template snapshots.

### §17.5 SpecKit subset

The SpecKit subset stamped per workspace is unchanged from #14 §5.3 (`.specify/memory/`, `.specify/templates/*.md`, `.specify/scripts/bash/*.sh`, the nine `speckit.*.md` slash commands). No epic-specific SpecKit files exist. Workspace-orchestration commands (`workspace.*`, `branch.*`, `repo.*`) per #14 §5.3 stay outside per-workspace stamping, identically for epic and sub workspaces.

---

## §18 Self-Containment & Idempotence

### §18.1 No host-absolute paths in stamped files

Every stamped file (CLAUDE.md, WORKSPACE.md, TRUNK.md, PROJECTS.md, ACTORS.md) carries only paths that are workspace-relative or repository-relative. The `parent_workspace_path` field in WORKSPACE.md is a relative path (e.g., `../<repo>-issue-<epic_N>/`), not an absolute path — this is critical for sandboxability per #14's invariants.

The only exception: example paths inside Markdown code blocks throughout this design doc carry illustrative absolute paths (e.g., `/Users/maxjonathanspaulding/.app_empire_worktrees/...`) for readability. These are example text, not stamped content. Per FR-021's audit (T042), the design doc is greppable; the only hits are in clearly illustrative blocks.

### §18.2 Idempotence

**`devkit bootstrap`** (epic case):

- First run: creates the epic workspace + each sub-workspace, posts ack comments. Exit 0.
- Re-run on same epic ref: refuses with `E_WORKTREE_EXISTS` for the epic dir. Per #14 §5.2 the epic dir creation fails first; sub-workspaces are not touched. Exit non-zero with explicit message.
- Re-run with `--retry-children` (proposed flag, optional): epic dir untouched (the flag implies "epic dir already exists; only retry the recursive sub-bootstrap"). For each sub in `child_sub_workspaces`: if the sub dir exists, skip; if missing, bootstrap it. Idempotent.

**`devkit archive`** (epic case):

- First run on a fully-archive-ready epic: archives all subs, then epic. Exit 0.
- Re-run after success: epic dir is now under `_archived/`; the issue ref no longer resolves to an active workspace. Exit non-zero with `<repo>#<epic_N> not found in active workspaces; check _archived/`.
- Re-run after a partial-archive failure (e.g., network failure during the third sub's `gh issue comment`): archived children stay archived; remaining children + epic continue. Idempotent because each per-workspace step is itself idempotent (move is idempotent; comment post is detected by checking comment history, skipped if already present).

Both commands satisfy FR-022's "running twice MUST be safe" requirement.

---

## §19 Non-Regression

**Running `devkit bootstrap` on a regular (non-epic) issue continues to work exactly as it does today.** No code paths regress. Specifically:

- For an issue with zero sub-issues, the sub-issue API check returns an empty array. `is_epic = false`. Bootstrap follows the existing #14 §5.2 flow verbatim, including the existing ack comment field set, no `is_epic`/`child_sub_workspaces` frontmatter additions, and no recursive bootstrap.
- `devkit archive <N>` on a regular workspace runs the existing v0.3 archive flow without modification.
- `devkit status` on a workspace tree containing only regular workspaces produces output identical to today's.
- All four new subcommands in §16 are no-ops for regular workspaces (they require `is_epic: true` or `parent_issue` to apply).

The single point where regular-case behavior touches new code is the sub-issue API probe in `devkit bootstrap` (§12.1). The probe is wrapped in a try/except: if it fails, bootstrap proceeds as if the issue were regular. Network down or API removed = regular-case behavior preserved (with a warning).

SC-007 satisfied.

---

## §20 Edge Case Dispositions

Each of the 11 edge cases enumerated in spec § Edge Cases. Disposition is `supported`, `unsupported`, or `supported-with-caveat`, with rationale.

### §20.1 Case 1 — Sub-issue touches a repo the parent epic does not

**Disposition: supported.**

**Rationale**: Each sub-workspace has its own `affected_repos` resolution path (issue body's `## Affected Repos`, or `--repos` CLI override at sub-bootstrap time). The epic's `affected_repos` does not constrain its children. The resulting state: sub-workspace has worktrees for its repos; epic workspace has worktrees for its repos; the sets may be disjoint, overlapping, or identical without any consistency requirement.

**Worked example**: epic `App-Empire-LLC/DevKit#13` affects `DevKit` + `appire_docs`. Sub-issue `App-Empire-LLC/DevKit#88` affects `CallScribe` only. After bootstrap:
- `DevKit-issue-13/` has `DevKit/` + `appire_docs/` worktrees.
- `DevKit-issue-88/` has `CallScribe/` worktree only.

Both are valid. The link is metadata-only (`parent_issue`), not repo-set-based.

### §20.2 Case 2 — Sub-issue touches zero repos (pure docs / design)

**Disposition: supported.**

**Rationale**: A sub-workspace with empty `affected_repos` is bootstrapped with no worktrees. It still has the workspace-root files (CLAUDE.md, WORKSPACE.md, TRUNK.md, PROJECTS.md, ACTORS.md, .git/, .specify/) and can host SpecKit work whose deliverable is the spec.md content itself (posted as an issue comment at archive time per §14.3). This issue (#13) is exactly such a case at the regular-workspace level — the deliverable IS this design doc.

**Caveat (sub-workspaces specifically)**: at `devkit bootstrap <sub_M>` time, if the issue body has no `## Affected Repos` section AND `--repos` is not passed, bootstrap creates the workspace with empty worktree set. No error, no warning required.

### §20.3 Case 3 — Epic itself touches zero repos (tracking umbrella)

**Disposition: supported.**

**Rationale**: Same mechanism as §20.2. The epic workspace can have empty `affected_repos`. WORKSPACE.md still records `is_epic: true` and `child_sub_workspaces`, the epic branch (`issue-<EpicRepo>-<EpicN>`) still exists in name (per §8.1) but is not cut on any repo because there are no affected repos to cut it on. Sub-workspace PRs target... nothing? Edge case: if epic has no repos but subs DO have repos, the sub PRs need a target branch.

**Refinement**: when the epic touches zero repos but its sub-issues touch repos, sub-workspace TRUNK.md line 1 falls back to `main` (because there is no epic branch to target). The sub PRs target `main` directly, and the "epic" exists purely as a tracking artifact in `child_sub_workspaces` and the `parent_issue` linkage. Archive coherence (§14) still applies: `devkit archive <epic_N>` sweeps all subs first then the epic dir.

This case is rare (an epic with sub-issues but no own-repo work) and the behavior degrades gracefully into "subs target main; epic is metadata-only." No new code paths needed beyond §13's existing logic if `affected_repos` is empty.

### §20.4 Case 4 — Sub-issue is closed or cancelled before its work merges

**Disposition: supported-with-caveat.**

**Rationale**: The cancelled sub-issue's workspace is removed manually by the operator (`rm -rf <sub-workspace>` or `devkit archive <sub_M>` if the sub has its own archive-ready state). The link from the parent epic is broken via `devkit unlink-sub <sub_M>` (§16), which removes the entry from the epic's `child_sub_workspaces` and clears `parent_issue` from the sub's WORKSPACE.md (if the sub is being kept around for reference rather than removed).

**Caveat 1**: `devkit archive <epic_N>` will refuse to archive the epic if any entry in `child_sub_workspaces` corresponds to a still-open sub-issue. The operator must run `devkit unlink-sub` (or close the sub-issue and ensure its PR landed) before archiving the epic.

**Caveat 2**: branches on the cancelled sub's repos (`issue-<SubRepo>-<SubM>`) remain on origin until manually deleted by the operator. DevKit does not auto-delete branches.

### §20.5 Case 5 — New sub-issue discovered mid-epic

**Disposition: supported.**

**Rationale**: The operator adds the sub-issue on GitHub (linking it to the parent via GitHub's sub-issue UI), then runs:

```bash
devkit bootstrap App-Empire-LLC/DevKit#<new_M>
```

If the GitHub sub-issue API returns the parent linkage at bootstrap time, the sub-workspace is auto-linked: `parent_issue` is set, and the parent epic's `child_sub_workspaces` is updated. If auto-link doesn't fire (e.g., GitHub UI hasn't propagated the parent link yet, or API returns no parent), the operator runs `devkit link-sub <sub_workspace> <epic_workspace>` (§16) to attach manually.

**No change to the epic workspace's filesystem state** is needed beyond the WORKSPACE.md frontmatter update for `child_sub_workspaces`. The epic branch already exists; the new sub PR will target it.

### §20.6 Case 6 — Epic branch falls behind main while sub-issue work is in-flight

**Disposition: supported (no special handling needed under Option B).**

**Rationale**: This case is a non-issue under the Option B topology selected in §3. Sub-issue branches are cut from `origin/main`, not from the epic branch (§8.2). When `main` advances:

- The epic workspace runs `git pull --rebase origin main` on `issue-<EpicRepo>-<EpicN>` (or `devkit sync` per #30 — actor: implementer in epic workspace).
- Each sub-workspace independently runs `git pull --rebase origin main` on its own `issue-<SubRepo>-<SubM>` (actor: implementer in each sub workspace).
- No chained rebase. The two operations are independent.

The Option-A version of this case ("chained rebase: epic onto main, then subs onto epic") is exactly what Option B's selection (§3) avoids. This is one of the criteria that drove the matrix outcome (§2.3 row 1: B:4 vs. A:2).

### §20.7 Case 7 — Sub-issue branch falls behind epic branch while a spec branch is in-flight

**Disposition: supported (case partially N/A under Option B).**

**Rationale**: Two parts:

- **"Sub-issue branch falls behind epic branch"**: doesn't occur under Option B as framed. Sub branches don't track epic branches; they track main. The sub-PR's *base* is the epic branch (so PR conflict-detection runs against the epic branch's tip), but the sub-branch's *commits* sit on top of `origin/main`. When the epic branch advances (via merges from sibling subs), the sub-PR may show new "base updates" in GitHub's UI — that's normal PR behavior, not a worktree-state concern.
- **"Spec branch in-flight"**: spec branches per §8.3 / §17.1 live only in the workspace's scratch `.git/`. They never touch the per-issue worktree's branch state. Whatever happens to the worktree's branch (rebase, force-push, anything) is invisible to the spec branch.

Neither half of the case introduces new failure modes under Option B. SUPPORTED with the disclaimer that the case description's framing matches Option A's topology, not Option B's.

### §20.8 Case 8 — Workspace collision with `_archived/` directory of the same name

**Disposition: supported (delegated to #14's archive path collision rule).**

**Rationale**: #14 §5.2 specifies that archived workspaces move to `<workspaces_home>/_archived/` with a date suffix (`<repo>-issue-<N>-<archive_date>`). If a freshly bootstrapped workspace collides with an existing `_archived/<repo>-issue-<N>/` (no date suffix; legacy state), `devkit archive` can refuse with `E_ARCHIVE_COLLISION` and require the legacy entry to be renamed manually.

For the epic case, the same rule applies independently to each level: `_archived/<repo>-issue-<epic_N>-<date>/` for the epic; `_archived/<sub_repo>-issue-<sub_M>-<date>/` for each sub. Because sub-workspaces are flat siblings (Option B), there is no nested `_archived/` substructure to worry about — the archived sub is at `_archived/`'s top level alongside the archived epic.

### §20.9 Case 9 — Epic workspace partially archived then reopened

**Disposition: supported (idempotent recovery per §14.5).**

**Rationale**: Per §14.4, `devkit archive <epic_N>` archives children before the parent. If the command failed mid-flight (network error during a sub's `gh issue comment` post; disk full mid-`mv`; user Ctrl-C), the on-disk state is:

- Some children archived (under `_archived/`).
- Remaining children + epic still under `<workspaces_home>/`.
- The epic's `child_sub_workspaces` list still references the now-archived children.

Re-running `devkit archive <epic_N>` picks up where it left off:

- For each entry in `child_sub_workspaces`, check if the sub-workspace exists at the expected path. If not, check `_archived/` for `<sub_repo>-issue-<sub_M>-*`. If found in `_archived/`, mark that sub as already-archived (no-op for it) and update the epic's tracking accordingly. If found nowhere, warn (case 4 territory) and continue.
- For each unarchived sub, retry the per-sub archive (idempotent: comment post checks history first; mv is idempotent).
- Finally archive the epic itself.

Each individual step is idempotent; the orchestration is recovery-friendly. No "reopen the partially archived state" command is needed — the recovery is just "re-run the archive command."

### §20.10 Case 10 — SpecKit isolation across sibling sub-workspaces running concurrently

**Disposition: supported.**

**Rationale**: Per §17.1, isolation is by filesystem-path boundary. Each sub-workspace has its own `<sub-workspace>/.specify/` and its own `<sub-workspace>/.git/`. SpecKit operations (`/speckit.specify`, `/plan`, `/tasks`, `/implement`) consult `git rev-parse --show-toplevel` from CWD, which resolves to the sub-workspace's scratch `.git/` when Claude is launched in that sub-workspace per #14's workspace-root CWD convention.

Two concurrent Claude sessions, one in each of two sibling sub-workspaces, see entirely disjoint SpecKit state: different scratch gits, different `.specify/` instances, different `specs/` directories. The `SPECIFY_FEATURE` env var (or its successor) is process-scoped — each Claude session has its own environment, so no cross-session contamination is possible at the env-var level.

This is FR-017's question answered explicitly: each sub-workspace has its own stamped speckit; no sharing with parent or with siblings.

### §20.11 Case 11 — Sub-workspace started pre-template-stabilization, then parent operation runs post-newer-template

**Disposition: supported-with-caveat.**

**Rationale**: Per §17.4, each workspace's `template_stamp_sha` is independent. A sub-workspace bootstrapped at time T1 with template SHA `abc123` is unaffected when `.devkit/templates/` is updated to `def456` at time T2 and a parent-level operation (e.g., `devkit refresh-templates` on the epic) runs at T3 with the newer SHA. The sub-workspace stays at `abc123` until the operator explicitly runs `devkit refresh-templates` on the sub.

**Caveat (visibility)**: `devkit status` should display each workspace's `template_stamp_sha` in the hierarchy rendering when sub-workspaces' SHAs differ from their parent's. Otherwise the operator may not realize a sub-workspace is lagging the current `.devkit/templates/`. Implementation note: this is a small extension to §15.1's render format — out of scope for this design's required FRs but recommended for follow-up.

**Caveat (re-stamp policy)**: this design **does not auto-re-stamp** sub-workspaces when the parent epic refreshes. Auto-propagation would violate #14 §6.2's "frozen at bootstrap, opt-in refresh" invariant. The operator who wants the sub to match the parent runs `devkit refresh-templates` on the sub explicitly. The decision is consistent with #14.

---



