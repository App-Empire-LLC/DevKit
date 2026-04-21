# DevKit

Companion tooling for [GitHub Spec-Kit](https://github.com/github/spec-kit).
Per-issue git worktrees, Claude Code slash commands, and workflow helpers built on `gh` and `git worktree`.

**Status:** v0.2 — Python port (Typer + Rich). Internal use. Not yet on PyPI (tracked in #23); install via `uv tool install --from .` from a local checkout.

## What it does

DevKit takes a GitHub issue and produces a clean per-issue workspace:

- A dedicated directory at `$APP_EMPIRE_WORKTREES_HOME/<repo>-issue-<N>/`
- `git init` inside it (so Spec-Kit has a repo to write artifacts into)
- One `git worktree` per affected repo, all on a shared branch `issue-<repo>-<N>`
- An auto-posted ack comment on the GH issue

The per-issue directory is the canonical place to run `claude` for an implementation session. Spec-Kit artifacts, multiple repo worktrees, and any scratch files live side-by-side — when the work is done, archive the whole directory.

## Requirements

- `uv` (`brew install uv` or https://github.com/astral-sh/uv)
- Python 3.11+ (`uv` will provision this as needed)
- `bash`, `git`, `gh`, `jq` on PATH
- `gh auth login` completed
- `~/.local/bin` on `$PATH`
- Two environment variables:
  - `APP_EMPIRE_PROJECTS` — directory containing the source repos (DevKit adds worktrees *from* these)
  - `APP_EMPIRE_WORKTREES_HOME` — directory where per-issue worktrees will be created

## Install

Two distinct steps — system install and user setup:

### 1. System install (one-time per machine)

```bash
git clone git@github.com:App-Empire-LLC/DevKit.git
cd DevKit
uv tool install --from . aidevkit
```

`uv tool install` places `devkit` on your PATH via its own shim at `~/.local/bin/devkit`. Once #23 publishes to PyPI, `uv tool install aidevkit` (without `--from .`) will work from anywhere.

If you had the bash-era install, remove its symlink after uv installs the Python version:

```bash
# Only if this points at the DevKit git checkout (not uv's shim):
rm -f ~/.local/bin/devkit
uv tool install --reinstall --from . aidevkit
```

### 2. User setup (one-time per user)

```bash
devkit setup
```

Runs `devkit doctor` first, then symlinks `~/.claude/commands/devkit.*.md` → the slash-command files bundled inside the uv-installed package. After `devkit setup`, the `/devkit.bootstrap` slash command is available inside Claude Code in any project. Re-run `devkit setup` after any `uv tool upgrade` to refresh symlinks.

## Subcommands

| Command                             | Description                                             |
| ----------------------------------- | ------------------------------------------------------- |
| `devkit bootstrap <owner/repo#N>`   | create a per-issue worktree directory                   |
| `devkit sync`                       | fetch and rebase every worktree in the current workspace onto its trunk |
| `devkit doctor`                     | check dependencies and environment                      |
| `devkit setup`                      | link slash commands into `~/.claude/commands/` (runs doctor first) |
| `devkit version`                    | show version                                            |
| `devkit --help`                     | show top-level help (Typer auto-generated)              |

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

## `devkit sync`

```
devkit sync [--json] [--dry-run]
```

Run from anywhere inside a `<repo>-issue-<N>/` workspace. For each worktree
inside the workspace (alphabetical order), sync:

1. `git fetch origin`
2. Resolve the trunk: per-worktree `TRUNK.md` > workspace `TRUNK.md` > `main`
3. `git rebase origin/<trunk>` — on conflict, leave the worktree in
   `rebase-in-progress` state and continue with the next worktree

Conflicts are never auto-resolved. Dirty worktrees (tracked-file changes)
are skipped with a reason — never stashed. No `git push`, no `--force*`,
no `reset --hard` — ever.

### Flags

| Flag         | Effect                                                                 |
| ------------ | ---------------------------------------------------------------------- |
| `--json`     | Emit a single JSON document on stdout. Diagnostics remain on stderr. Schema: `importlib.resources.files("aidevkit.schemas") / "sync-output.schema.json"`. |
| `--dry-run`  | Print the planned actions per worktree. No `git fetch`, no `git rebase`. |

### Exit codes

| Code | Meaning                                                            |
| ---: | ------------------------------------------------------------------ |
|    0 | every worktree clean (`rebased` / `fast-forwarded` / `up-to-date`) |
|    2 | usage error                                                        |
|   12 | dependency missing (`git` not on PATH)                             |
|   20 | not invoked inside a workspace                                     |
|   21 | sync completed but ≥1 worktree needs user attention                |

### Example

```text
$ devkit sync
[devkit] sync: workspace /Users/you/.app_empire_worktrees/DevKit-issue-11
[devkit] sync: DevKit           main         rebased (3 commits replayed)
[devkit] sync: appire_docs      main         up-to-date
[devkit] sync: all worktrees clean.
```

### `TRUNK.md`

Plain-text file containing just the trunk branch name on its own line.
Optional `#`-prefixed comments and blank lines above are allowed. Place
inside a single worktree to apply only to that worktree, or at the
workspace root to apply to every worktree without its own `TRUNK.md`.

```text
# Use develop instead of main for this worktree — see ADR-042.
develop
```

## Conventions

- **Worktree dir name:** `<repo>-issue-<N>` — `<repo>` is the short name of the issue's home repo (e.g. `AuthService-issue-5`). Flat naming sorts well in `ls` and disambiguates across repos that all start numbering at 1.
- **Branch name:** `issue-<repo>-<N>` — `<repo>` is always the issue's home repo, not the worktree's host repo. This prevents cross-repo branch collisions when two issues in different home repos both touch the same shared repo.
- **Ack comment:** auto-posted to the issue on bootstrap. Pass `--no-ack` to skip.

## Next session handoff

When `devkit bootstrap` succeeds, it prints a `cd ... && claude` command. Running it starts a fresh Claude Code session inside the per-issue worktree — that's where Spec-Kit (`/speckit.specify`, `/speckit.plan`, etc.) should run for this issue's implementation work.

### Claude context in per-issue worktrees (current quirk)

Claude Code loads `CLAUDE.md` by walking **ancestors** of the cwd up to `$HOME` at session start (eager), and **lazy-loads** subdirectory `CLAUDE.md` files only when a tool first reads a file inside that subdir. See [appire_docs/tools/claude-code.md](../appire_docs/tools/claude-code.md) for the full behavior.

Because DevKit places per-issue worktrees at `$APP_EMPIRE_WORKTREES_HOME/...`, which sits **outside** `$APP_EMPIRE_PROJECTS`, the ancestor walk from a worktree session never reaches `$APP_EMPIRE_PROJECTS/CLAUDE.md`. The meta-root context is not loaded at session start.

**Workaround until [#2](https://github.com/App-Empire-LLC/DevKit/issues/2) lands:** launch Claude from the project subdirectory inside the worktree rather than the worktree root. That at least picks up the project's own `CLAUDE.md` eagerly via the ancestor walk:

```bash
cd $APP_EMPIRE_WORKTREES_HOME/<repo>-issue-<N>/<repo> && claude
```

This does not restore the AppEmpire meta-root CLAUDE.md — that's what #2 fixes, by seeding a root CLAUDE.md at the worktree top so the ancestor walk can find it.

## Development

These commands are for DevKit maintainers working on the tool itself — not for installing it.

```bash
# From a DevKit clone
uv sync --extra test        # editable install + pytest, pytest-cov, ruff
pytest                       # run the test suite (under 10s, fully offline)
pytest --cov                 # include a terminal coverage report
ruff check .                 # lint the tree
ruff check --fix .           # auto-apply fixable suggestions
```

Tests are hermetic: the autouse `_fail_on_unmocked_shell` fixture in
`tests/conftest.py` raises on any real `subprocess.run` call routed through
`aidevkit.util`. All `git`/`gh` work in tests goes through the
`subprocess_capture` fixture. Coverage is report-only — no threshold gate.

## License

See [LICENSE](LICENSE).
