# DevKit

Companion tooling for GitHub Spec-Kit and the App Empire per-issue worktree workflow.

> A fuller project guide is tracked in [App-Empire-LLC/DevKit#15](https://github.com/App-Empire-LLC/DevKit/issues/15). This file is a minimal pointer until that lands.

## Stack

- Python 3.11+ (matches SpecKit's baseline, per closed design decision in #19 — documented deviation from the constitution's 3.12+ default)
- [Typer](https://typer.tiangolo.com/) for subcommand dispatch and auto-generated `--help`
- [Rich](https://rich.readthedocs.io/) for console output (markup disabled; we use plain-text prefixes like `[ok]` / `[FAIL]` that would otherwise be parsed as style tags)
- [Hatchling](https://hatch.pypa.io/latest/) as the build backend
- Distributed via `uv tool install` — see README

## Layout

- `src/aidevkit/` — the Python package
  - `cli.py` — Typer app + subcommand wiring
  - `bootstrap.py` / `doctor.py` / `setup.py` / `sync.py` — one module per subcommand
  - `util.py` — exit-code constants, Rich consoles, `log`/`info`/`die`, subprocess helpers (`run`/`git`/`gh`)
  - `commands/` — bundled Claude Code slash-command markdown, symlinked into `~/.claude/commands/` by `devkit setup`
  - `schemas/` — JSON Schemas shipped as package resources (load via `importlib.resources.files("aidevkit.schemas")`)
- `legacy/devkit.sh` — the original bash CLI, retained for reference; no longer on PATH
- `tests/` — pytest suites; hermetic unit tests monkeypatch `aidevkit.util.run`, integration tests drive the real `git` binary against tempdir origins

### Importable seams

- `aidevkit.sync.behind_count(worktree: Path, trunk: str) -> int` — count of commits on `origin/<trunk>` not reachable from `HEAD`. Assumes caller has already fetched. This is the primitive **DevKit#27's pre-push freshness check** consumes; keep the signature stable.

## Conventions

- All `git` / `gh` calls go through `aidevkit.util.run` (one subprocess seam, `shell=False`). Tests in #22 can mock at this one point.
- Exit codes are preserved from the bash-era: `0` success, `2` usage, `10` repos-missing, `11` workspace-exists, `12` dep-missing, `13` repo-not-found. `sync` adds: `20` not-in-workspace, `21` sync-partial.
- `sync.py` must never issue destructive git commands. A source-level unit test (`tests/unit/test_sync_no_destructive_git.py`) backs this — do not paper over a future violation by editing the allow-list.
- The project is a Python CLI tool, not a service — constitution principles V–IX are N/A.
