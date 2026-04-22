---
description: Remove archived workspaces older than the retention threshold
---

# /devkit.purge

Delete directories under `$APP_EMPIRE_WORKTREES_HOME/_archived/` whose
`.devkit-archived` marker timestamp is older than the retention threshold
(default 30 days). **Dry-run by default** — the user must pass `--yes` to
actually delete.

Directories without a valid marker are never deleted — only `devkit archive`
writes markers, so a missing/unparseable marker is evidence that the dir
wasn't created by `devkit archive` and the user owns it.

## Usage

    /devkit.purge
    /devkit.purge --days 7
    /devkit.purge --yes
    /devkit.purge --days 60 --yes

## What to do

1. Run the command:

       devkit purge [--days N] [--yes]

2. The command prints:
   - `would purge <dir>` — dry-run candidate.
   - `purged <dir>` — actually deleted (only with `--yes`).
   - `keep <dir>: age N days < threshold T` — within the retention window.
   - `SKIP <dir>: <reason>` — marker missing/empty/unparseable/future.
     These are never deleted, regardless of flags.

3. If a deletion fails (permission, race), the command reports the failed
   path and exits non-zero. Other eligible deletions in the same run still
   happen — the command does not roll back successful deletions.

4. Active (non-archived) workspaces sit at the root of
   `$APP_EMPIRE_WORKTREES_HOME`, not under `_archived/` — purge never
   enumerates them. Tell the user this explicitly if they worry about data loss.

## Flags

- `--days N` — override the retention threshold (default 30).
- `--yes` — perform deletions. Without this, the command is strictly a
  dry-run report.

## Notes

- `purge` is never automatic. No cron, no archive-time deletion.
- The marker file is one line of ISO 8601 UTC (e.g.,
  `2026-04-22T14:37:22Z`). Date-only strings and timezone-offset variants
  are accepted on read. See `specs/20-lifecycle-and-self-mgmt/contracts/marker-file.md`.
- Exit code `16` means `$APP_EMPIRE_WORKTREES_HOME` is unset or not a
  directory (run `devkit doctor`).
