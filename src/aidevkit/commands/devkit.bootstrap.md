---
description: Bootstrap a per-issue workspace directory for a GitHub issue
---

# /devkit.bootstrap

Create a per-issue workspace for a GitHub issue: set up the directory, git-init it, stamp the three reserved files (`WORKSPACE.md`, `TRUNK.md`, `PROJECTS.md`) and any templates from `.devkit/templates/`, add worktrees for each affected repo on a shared branch, and post an ack comment on the issue.

The schema for `.devkit/config.yaml`, `PROJECTS.md`, and templates is documented in `appire_docs/docs/workflows/devkit-workspaces.md` (the canonical operating reference).

## Usage

The user will give you an issue reference. Either form is accepted:

- Fully qualified: `App-Empire-LLC/AuthService#5`
- Bare (expanded via `org` config field): `AuthService#5`

```bash
/devkit.bootstrap App-Empire-LLC/AuthService#5
/devkit.bootstrap AuthService#5
```

If the user gives you a bare number with no repo (e.g. `#5`), ask them to confirm the `owner/repo` before running.

## What to do

1. Run the bootstrap script with the issue reference:

       devkit bootstrap <ref>

2. **--repos is additive** (DevKit#37 change). If the user wants extra repos beyond the issue body's `## Affected Repos`, append them:

       devkit bootstrap <ref> --repos owner/extra-a,owner/extra-b

   Every entry in `--repos` must already exist in the projects-home `PROJECTS.md` catalog. Bootstrap refuses with exit code 13 if not.

3. **Common exit codes** (each names the offending input in its message):
   - **12** `E_DEP_MISSING` — projects-home not resolvable. Check `$PROJECTS_HOME` or `~/.devkit/config.yaml#projects_home`.
   - **13** `E_REPO_NOT_FOUND` — a repo (issue body, `--repos`, `always_include_repos`) is not in `PROJECTS.md`, or the source clone is missing. Surface the error.
   - **11** `E_WORKSPACE_EXISTS` — workspace dir already exists. Don't delete; surface to the user.
   - **17** `E_ORIGIN_MAIN_UNAVAILABLE` — fetch failed or `origin/<default_branch>` doesn't exist. Surface; do NOT hand-create from local main.
   - **70** `E_CONFIG_INVALID` — `.devkit/config.yaml` schema failure. The error message names the field, problem, and fix.
   - **71** `E_CATALOG_INVALID` — `PROJECTS.md` parse failure or duplicate `name`.
   - **72** `E_TEMPLATE_COLLISION` — a template tries to overwrite a reserved file (`WORKSPACE.md`, `TRUNK.md`, `PROJECTS.md`). Refused before any worktree is created.

4. On success, surface the `cd ... && claude` command the script prints at the end, so the user can start a fresh implementation session in the workspace directory.

## Validation phase

Before any worktree is created, bootstrap runs a two-phase sequence:

1. **Validation phase**: resolve `.devkit/` config + catalog, validate every affected repo against `PROJECTS.md`, plan template stamping (including reserved-file collision detection), `git fetch origin` for each repo, verify `origin/<default_branch>`. Fail-fast — the first failure causes bootstrap to exit before creating any workspace dir, worktree, or branch.
2. **Creation phase**: workspace dir, `git init`, stamp `WORKSPACE.md` / `TRUNK.md` / `PROJECTS.md`, apply workspace-root templates, `git worktree add ... -b <branch> origin/<default_branch>` per repo, apply per-worktree templates.

This means: if bootstrap exits with a validation error for a multi-repo issue, **no worktrees exist for any of the affected repos** — not even the ones whose validation would have succeeded.

## Notes

- The workspace directory is created at `<workspaces_home>/<repo>-issue-<N>/`, where `<workspaces_home>` comes from the merged `.devkit/config.yaml`.
- Each affected repo gets a git worktree at `<workspace>/<name>` on branch `issue-<IssueHomeRepo>-<N>`, based on `origin/<default_branch>` at fetch time.
- The issue's home repo is always included in the workspace's worktree set.
- `always_include_repos` in `.devkit/config.yaml` adds repos to every workspace (each entry must be in `PROJECTS.md`).
- An ack comment is auto-posted to the issue — pass `--no-ack` if testing and you want to skip it.
- Local `main` in each source repo is never read or mutated — bootstrap uses the remote-tracking `origin/<default_branch>` directly.
- Do not try to "help" by running destructive commands if bootstrap fails. Stop, surface the error, let the user decide.
