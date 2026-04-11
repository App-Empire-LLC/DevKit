# DevKit

Companion tooling for [GitHub Spec-Kit](https://github.com/github/spec-kit).
Per-issue git worktrees, Claude Code slash commands, and workflow helpers built on `gh` and `git worktree`.

**Status:** v0.1 — internal use. Not yet published; expect rough edges.

## What it does

DevKit takes a GitHub issue and produces a clean per-issue workspace:

- A dedicated directory at `$APP_EMPIRE_WORKTREES_HOME/<repo>-issue-<N>/`
- `git init` inside it (so Spec-Kit has a repo to write artifacts into)
- One `git worktree` per affected repo, all on a shared branch `issue-<repo>-<N>`
- An auto-posted ack comment on the GH issue

The per-issue directory is the canonical place to run `claude` for an implementation session. Spec-Kit artifacts, multiple repo worktrees, and any scratch files live side-by-side — when the work is done, archive the whole directory.

## Requirements

- `bash`, `git`, `gh`, `jq`
- `gh auth login` completed
- `~/.local/bin` on `$PATH`
- Two environment variables:
  - `APP_EMPIRE_PROJECTS` — directory containing the source repos (DevKit adds worktrees *from* these)
  - `APP_EMPIRE_WORKTREES_HOME` — directory where per-issue worktrees will be created

## Install

```bash
git clone git@github.com:App-Empire-LLC/DevKit.git
cd DevKit
./bin/devkit install
```

`devkit install` runs `devkit doctor` first, then symlinks:

- `bin/devkit` → `~/.local/bin/devkit`
- `.claude/commands/devkit.*.md` → `~/.claude/commands/`

After install, `devkit` is callable from anywhere and the `/devkit.bootstrap` slash command is available inside Claude Code.

## Subcommands

| Command                             | Description                                             |
| ----------------------------------- | ------------------------------------------------------- |
| `devkit bootstrap <owner/repo#N>`   | create a per-issue worktree directory                   |
| `devkit doctor`                     | check dependencies and environment                      |
| `devkit install`                    | run doctor, then symlink devkit + slash commands        |
| `devkit version`                    | show version                                            |
| `devkit help`                       | show top-level help                                     |

## `devkit bootstrap`

```
devkit bootstrap <owner/repo#N> [--repos owner/a,owner/b] [--dry-run] [--no-ack]
```

### Affected repos resolution

DevKit determines which repos to add worktrees for, in this priority order:

1. **`--repos` flag** — if provided, its comma-separated list wins.
2. **`## Affected Repos` section in the issue body** — a markdown heading followed by a bulleted list of `owner/repo`:

       ## Affected Repos

       - App-Empire-LLC/AuthService
       - App-Empire-LLC/AppEmpireAdmin

3. **The issue's home repo** — always added to the set unless the issue is a draft without a home. Listing it explicitly is optional; DevKit adds it silently if it's missing.

If DevKit can't determine any affected repos (draft issue with no `## Affected Repos` section and no `--repos`), it exits with code **10** so the caller can prompt the user and retry with `--repos`.

### Exit codes

| Code | Meaning                                                                |
| ---: | ---------------------------------------------------------------------- |
|    0 | success                                                                |
|    2 | usage error                                                            |
|   10 | no affected repos could be determined (draft issue, no list)           |
|   11 | worktree directory already exists                                      |
|   12 | dependency missing (bash/git/gh/jq, or a required env var)             |
|   13 | source repo not found at `$APP_EMPIRE_PROJECTS`                        |

### Examples

Bootstrap a non-draft issue — no `## Affected Repos` section needed; home repo is auto-included:

```
devkit bootstrap App-Empire-LLC/AuthService#5
```

Bootstrap with an explicit repo list (overrides body parsing):

```
devkit bootstrap App-Empire-LLC/appire_docs#42 \
  --repos App-Empire-LLC/AuthService,App-Empire-LLC/AppEmpireAdmin
```

Show what would happen without touching anything:

```
devkit bootstrap App-Empire-LLC/AuthService#5 --dry-run --no-ack
```

## Conventions

- **Worktree dir name:** `<repo>-issue-<N>` — `<repo>` is the short name of the issue's home repo (e.g. `AuthService-issue-5`). Flat naming sorts well in `ls` and disambiguates across repos that all start numbering at 1.
- **Branch name:** `issue-<repo>-<N>` — `<repo>` is always the issue's home repo, not the worktree's host repo. This prevents cross-repo branch collisions when two issues in different home repos both touch the same shared repo.
- **Ack comment:** auto-posted to the issue on bootstrap. Pass `--no-ack` to skip.

## Next session handoff

When `devkit bootstrap` succeeds, it prints a `cd ... && claude` command. Running it starts a fresh Claude Code session inside the per-issue worktree — that's where Spec-Kit (`/speckit.specify`, `/speckit.plan`, etc.) should run for this issue's implementation work.

## License

See [LICENSE](LICENSE).
