"""DevKit bootstrap: per-issue workspace orchestration.

Composes config + projects + templates + workspace modules. The hardcoded
``$APP_EMPIRE_PROJECTS`` / ``$APP_EMPIRE_WORKTREES_HOME`` reads and the
hardcoded ``appire_docs`` always-include were both removed in DevKit#37 in
favor of operator-configurable ``.devkit/config.yaml`` + ``PROJECTS.md``.
"""
from __future__ import annotations

import json
import re
import shutil
from pathlib import Path

from . import __version__
from . import config as _config
from . import projects as _projects
from . import templates as _templates
from . import workspace as _workspace
from .util import (
    E_DEP_MISSING,
    E_ORIGIN_MAIN_UNAVAILABLE,
    E_REPO_NOT_FOUND,
    E_TEMPLATE_COLLISION,
    E_USAGE,
    E_WORKSPACE_EXISTS,
    die,
    gh,
    git,
    info,
    log,
)

_ISSUE_REF = re.compile(r"^([^/]+)/([^#]+)#(\d+)$")


def _check_deps() -> None:
    for binary in ("git", "gh", "jq"):
        if shutil.which(binary) is None:
            die(f"{binary} not found in PATH (run 'devkit doctor')", code=E_DEP_MISSING)


def _parse_issue_ref(issue_arg: str) -> tuple[str, str, int]:
    m = _ISSUE_REF.match(issue_arg)
    if not m:
        die(f"issue must be in form 'owner/repo#number' (got: {issue_arg})", code=E_USAGE)
    owner, repo, num_str = m.group(1), m.group(2), m.group(3)
    return owner, repo, int(num_str)


def _parse_affected_repos_from_body(body: str) -> list[str]:
    """Extract owner/repo entries from the issue body's `## Affected Repos`."""
    repos: list[str] = []
    in_section = False
    heading_re = re.compile(r"^##\s+Affected\s+Repos\s*$", re.IGNORECASE)
    next_heading_re = re.compile(r"^##\s+")
    item_re = re.compile(r"^-\s*([^\s/]+/[^\s]+)")
    for line in body.splitlines():
        if heading_re.match(line):
            in_section = True
            continue
        if in_section and next_heading_re.match(line):
            break
        if in_section:
            m = item_re.match(line)
            if m:
                repos.append(m.group(1))
    return repos


def _resolve_affected_owner_repos(
    issue_home_owner_repo: str,
    body: str,
    repos_override: str,
    catalog: _projects.Catalog,
    always_include: tuple[str, ...],
) -> list[_projects.CatalogEntry]:
    """Build the ordered list of CatalogEntry for affected repos.

    Order:
    1. Issue home repo (always first in the workspace tree).
    2. Issue body's ``## Affected Repos`` entries (in body order).
    3. ``always_include_repos`` config entries (in config order).
    4. ``--repos`` flag entries (additive — DevKit#37 FR-018a).

    Duplicates collapse. Each entry must resolve through the catalog;
    misses raise ``E_REPO_NOT_FOUND`` before any filesystem mutation.
    """
    seen_owner_repos: set[str] = set()
    ordered: list[_projects.CatalogEntry] = []

    def _add_owner_repo(owner_repo: str, source: str) -> None:
        if owner_repo in seen_owner_repos:
            return
        if not catalog.has_owner_repo(owner_repo):
            die(
                f"affected repo {owner_repo!r} (from {source}) is not in "
                f"{catalog.source_path}.\n"
                f"  Fix: add a row to PROJECTS.md whose git_url maps to "
                f"{owner_repo!r}, or remove the reference.",
                code=E_REPO_NOT_FOUND,
            )
        seen_owner_repos.add(owner_repo)
        ordered.append(catalog.resolve_owner_repo(owner_repo))

    _add_owner_repo(issue_home_owner_repo, source="issue ref")

    for ref in _parse_affected_repos_from_body(body):
        _add_owner_repo(ref, source="issue body '## Affected Repos'")

    # always_include_repos uses the same owner/repo form (FR-005a forbids
    # bare names there).
    for ref in always_include:
        _add_owner_repo(ref, source="always_include_repos config")

    if repos_override:
        for raw in repos_override.split(","):
            ref = raw.strip()
            if not ref:
                continue
            _add_owner_repo(ref, source="--repos flag")

    return ordered


def _verify_source_repos(
    repos: list[_projects.CatalogEntry], projects_home: Path
) -> None:
    for entry in repos:
        # Forward-compat: ignore the future `path` column. For #37, the
        # source clone is at $PROJECTS_HOME/<name>/.
        src = projects_home / entry.name
        if not (src / ".git").exists():
            die(
                f"source repo not found at {src} (catalog name: {entry.name}, "
                f"git_url: {entry.git_url})",
                code=E_REPO_NOT_FOUND,
            )


def _validate_origin_main(
    repos: list[_projects.CatalogEntry], projects_home: Path
) -> None:
    """Per DevKit#27: fail-fast fetch + verify before any mutation."""
    for entry in repos:
        src = projects_home / entry.name
        owner_repo = entry.owner_repo or entry.name
        log(f"fetch origin: {owner_repo}")
        fetch_res = git("fetch", "origin", cwd=src)
        if fetch_res.code != 0:
            detail = fetch_res.stderr.strip() or fetch_res.stdout.strip() or "(no detail)"
            die(
                f"fetch origin failed for {owner_repo}: {detail}",
                code=E_ORIGIN_MAIN_UNAVAILABLE,
            )
        ref = f"refs/remotes/origin/{entry.default_branch}"
        verify_res = git(
            "rev-parse", "--verify", "--quiet", ref,
            cwd=src,
        )
        if verify_res.code != 0:
            die(
                f"origin/{entry.default_branch} not found in {owner_repo} — "
                f"is {entry.default_branch!r} the trunk? is the remote configured?",
                code=E_ORIGIN_MAIN_UNAVAILABLE,
            )


def _format_ack_comment(workspace: Path, repos: list[_projects.CatalogEntry]) -> str:
    repos_line = " ".join(e.owner_repo or e.name for e in repos)
    return (
        f"Bootstrap started by claude. Worktree: `{workspace}`. "
        f"Affected repos: {repos_line}. (Comment auto-posted by devkit-bootstrap.)"
    )


def _config_sha_for(projects_home: Path) -> str:
    """Return git SHA of the projects-home `.devkit/` if tracked, else 'unversioned'."""
    devkit_dir = projects_home / ".devkit"
    sha = git("rev-parse", "HEAD", cwd=devkit_dir)
    if sha.code == 0 and sha.stdout.strip():
        return sha.stdout.strip()[:7]
    return "unversioned"


def cmd_bootstrap(
    issue_arg: str,
    repos_override: str = "",
    dry_run: bool = False,
    no_ack: bool = False,
) -> int:
    _check_deps()

    owner, repo, num = _parse_issue_ref(issue_arg)
    issue_home = f"{owner}/{repo}"

    info(f"Bootstrapping {issue_home}#{num}")

    # Phase 1a: gh issue view
    res = gh(
        "issue", "view", str(num),
        "--repo", issue_home,
        "--json", "title,body,url",
    )
    if res.code != 0:
        detail = res.stderr.strip() or res.stdout.strip()
        die(f"failed to fetch {issue_home}#{num}: {detail}", code=1)

    try:
        payload = json.loads(res.stdout)
    except json.JSONDecodeError as exc:
        die(f"gh returned invalid JSON: {exc}", code=1)

    title = payload.get("title", "")
    body = payload.get("body", "") or ""
    url = payload.get("url", "")
    info(f"Issue: {title}")
    info(f"URL:   {url}")

    # Phase 1b: load .devkit/ config + catalog
    projects_home = _config.resolve_projects_home()
    cfg = _config.load_merged_config(projects_home)
    catalog_path = projects_home / ".devkit" / "PROJECTS.md"
    catalog = _projects.parse_projects_md(catalog_path)

    # Phase 1c: resolve affected repos
    repos = _resolve_affected_owner_repos(
        issue_home_owner_repo=issue_home,
        body=body,
        repos_override=repos_override,
        catalog=catalog,
        always_include=cfg.always_include_repos,
    )

    # Phase 1d: verify source clones and origin/main
    _verify_source_repos(repos, projects_home)
    _validate_origin_main(repos, projects_home)

    # Phase 1e: workspace path + collision check
    workspace = cfg.workspaces_home / f"{repo}-issue-{num}"
    if workspace.exists():
        die(
            f"workspace dir already exists: {workspace} (archive or remove it first)",
            code=E_WORKSPACE_EXISTS,
        )

    # Phase 1f: plan template stamping (validation phase — no mutation)
    home_dir = Path.home()
    affected_repo_source_paths: list[tuple[str, str, Path]] = []
    affected_repo_names: list[str] = []
    for entry in repos:
        owner_repo = entry.owner_repo
        if owner_repo is None:
            # git_url didn't yield owner/repo; fall back to name.
            owner_repo = f"{cfg.org}/{entry.name}"
        affected_repo_source_paths.append(
            (entry.name, owner_repo, projects_home / entry.name)
        )
        affected_repo_names.append(entry.name)

    tiers = _templates.discover_tiers(
        home_dir=home_dir,
        projects_home=projects_home,
        affected_repo_source_paths=affected_repo_source_paths,
    )
    plan = _templates.plan_stamp(
        tiers,
        affected_repo_names=affected_repo_names,
    )
    if plan.collisions_with_reserved:
        details = "\n".join(
            f"  - {c.relpath.as_posix()} from tier {c.tier_label}"
            for c in plan.collisions_with_reserved
        )
        die(
            f"template would overwrite a reserved workspace file. "
            f"Reserved files (WORKSPACE.md, TRUNK.md, PROJECTS.md) "
            f"cannot come from templates.\n"
            f"  Collisions:\n{details}\n"
            f"  Fix: rename or remove the offending template file(s).",
            code=E_TEMPLATE_COLLISION,
        )

    branch = f"issue-{repo}-{num}"
    info(f"Workspace: {workspace}")
    info(f"Branch:    {branch}")
    info("Repos:")
    for entry in repos:
        info(f"  - {entry.owner_repo or entry.name}")

    if dry_run:
        info("")
        info("[dry-run] would create workspace dir, git init, stamp reserved + "
             "template files, add worktrees, post ack comment")
        return 0

    # Phase 2a: mkdir workspace + git init (preserved per spec Assumptions —
    # `workspace_scratch_git` opt-out is OOS for #37).
    workspace.mkdir(parents=True, exist_ok=False)
    try:
        init_res = git("init", "--quiet", cwd=workspace)
        if init_res.code != 0:
            die(f"git init failed: {init_res.stderr.strip()}", code=1)

        # Phase 2b: stamp the three reserved files FIRST (FR-019).
        # Trunk branch is 'main' for #37 (parent/children OOS).
        trunk_branch = "main"
        config_sha = _config_sha_for(projects_home)
        affected_owner_repos = [
            e.owner_repo or f"{cfg.org}/{e.name}" for e in repos
        ]
        _workspace.stamp_workspace_md(
            workspace,
            issue_url=url,
            issue_owner_repo=issue_home,
            issue_number=num,
            issue_title=title,
            affected_repos=affected_owner_repos,
            trunk_branch=trunk_branch,
            stamp_devkit_version=__version__,
            stamp_config_sha=config_sha,
            template_stamp_sha=plan.template_stamp_sha,
        )
        _workspace.stamp_trunk_md(workspace, trunk_branch)
        _workspace.stamp_projects_md(workspace, catalog.raw_text)

        # Phase 2c: stamp workspace-root templates (before worktrees, so the
        # workspace root is fully populated when first inspected).
        _templates.log_overrides(plan)
        _templates.apply_stamp_plan(
            plan,
            workspace,
            affected_repo_names=affected_repo_names,
            phase="workspace",
        )

        # Phase 2d: add worktrees (must happen before worktree-template apply
        # since `git worktree add` requires the destination dir not to exist).
        for entry in repos:
            src = projects_home / entry.name
            wt_target = workspace / entry.name
            owner_repo = entry.owner_repo or entry.name
            info(f"Adding worktree: {entry.name}  ({src} -> {wt_target}, {branch})")
            origin_ref = f"origin/{entry.default_branch}"
            add_res = git(
                "worktree", "add", str(wt_target), "-b", branch, origin_ref,
                cwd=src,
            )
            if add_res.code != 0:
                detail = add_res.stderr.strip() or add_res.stdout.strip()
                die(
                    f"git worktree add failed for {owner_repo}: {detail}",
                    code=1,
                )

        # Phase 2e: stamp worktree templates (now that worktree dirs exist).
        _templates.apply_stamp_plan(
            plan,
            workspace,
            affected_repo_names=affected_repo_names,
            phase="worktree",
        )
    except Exception:
        shutil.rmtree(workspace, ignore_errors=True)
        raise

    # Phase 2e: ack comment
    if not no_ack:
        comment = _format_ack_comment(workspace, repos)
        ack_res = gh(
            "issue", "comment", str(num),
            "--repo", issue_home,
            "--body", comment,
        )
        if ack_res.code == 0:
            info(f"Posted ack comment on {issue_home}#{num}")
        else:
            log("WARN: failed to post ack comment (continuing)")

    primary = workspace / repo
    info("")
    info("Ready. Start an implementation session with:")
    info("")
    info(f"    cd {workspace} && claude")
    info("")
    info(f"(Or for the primary worktree: cd {primary} && claude)")
    info("")
    return 0
