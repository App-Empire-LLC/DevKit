---
description: Fetch and rebase every worktree in the current workspace onto its trunk
---

# /devkit.sync

Catch every per-repo worktree up with its trunk in one pass: fetch `origin`,
rebase the issue branch onto `origin/<trunk>`, surface conflicts, keep going
across remaining worktrees. Never auto-resolves anything.

## Usage

    /devkit.sync

The command takes no arguments. It discovers the workspace by walking the
CWD's ancestors, so run it from anywhere inside a `<repo>-issue-<N>/` tree
(or one of its worktrees).

## What to do

1. Run the sync with JSON output so you can parse the result:

       devkit sync --json

2. Parse stdout as a single JSON document. Schema:
   `importlib.resources.files("aidevkit.schemas") / "sync-output.schema.json"`.
   The top-level fields are `workspace_root`, `overall_status`, `exit_code`,
   and `worktrees[]`. Each worktree record has `repo`, `path`, `branch`,
   `trunk`, `outcome`, and `behind_count` (plus `message` for non-clean
   outcomes and `commits_replayed` when `outcome == "rebased"`).

3. Summarize the per-worktree outcomes to the user:
   - `rebased` → mention the commit count from `commits_replayed`.
   - `up-to-date` / `fast-forwarded` → one-liner noting no change.
   - `skipped-dirty` → surface `message` (describes the dirty files).
   - `fetch-failed` / `trunk-missing` / `rebase-error` → surface `message`;
     treat as an error the user must unblock.
   - `conflict` → surface `message` verbatim; it names the worktree path
     and the `git rebase --continue` / `git rebase --abort` choices.

4. If `overall_status != "ok"`, **stop**. Do not attempt to:
   - run `git rebase --continue`, `git rebase --abort`, or any other rebase
     state-mutating command on the user's behalf,
   - delete conflicting files or revert them,
   - push branches or force-push to resolve things "faster."
   The user decides the next move.

5. If `exit_code == 20` (`not in workspace`), tell the user to `cd` into a
   workspace first. Do not try to infer a workspace path.

## Notes

- Do not run destructive git commands regardless of outcome (FR-017).
  No `git push`, `git reset --hard`, `git clean`, `git branch -D`,
  `git reflog expire`, or any `--force*` flag — ever.
- Worktrees are processed alphabetically and sequentially, so the slash
  command's summary should reflect that same order.
- `devkit sync --dry-run --json` gives you a parseable plan without
  touching git.
- `behind_count` on each worktree record is informational — it's the
  count *before* sync ran. For a fresh "how behind am I right now?" read
  after sync, re-run with `--dry-run`.
