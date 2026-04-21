from __future__ import annotations

import json
import os
import re
import shutil
from pathlib import Path

from .util import (
    E_DEP_MISSING,
    E_ORIGIN_MAIN_UNAVAILABLE,
    E_REPO_NOT_FOUND,
    E_REPOS_MISSING,
    E_USAGE,
    E_WORKTREE_EXISTS,
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

    for var in ("APP_EMPIRE_PROJECTS", "APP_EMPIRE_WORKTREES_HOME"):
        val = os.environ.get(var)
        if not val:
            die(f"${var} not set (run 'devkit doctor')", code=E_DEP_MISSING)
        if not Path(val).is_dir():
            die(f"${var} does not point at a directory: {val}", code=E_DEP_MISSING)


def _parse_issue_ref(issue_arg: str) -> tuple[str, str, int]:
    m = _ISSUE_REF.match(issue_arg)
    if not m:
        die(f"issue must be in form 'owner/repo#number' (got: {issue_arg})", code=E_USAGE)
    owner, repo, num_str = m.group(1), m.group(2), m.group(3)
    return owner, repo, int(num_str)


def _parse_affected_repos_from_body(body: str) -> list[str]:
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


def _resolve_affected_repos(
    issue_home: str,
    body: str,
    repos_override: str,
) -> list[str]:
    owner = issue_home.split("/", 1)[0]
    appire_docs_repo = f"{owner}/appire_docs"

    if repos_override:
        log("using --repos override")
        repos = [r.strip() for r in repos_override.split(",") if r.strip()]
        if issue_home not in repos:
            log(f"adding issue's home repo to set: {issue_home}")
            repos = [issue_home, *repos]
    else:
        from_body = _parse_affected_repos_from_body(body)
        if issue_home not in from_body:
            if from_body:
                log(f"adding issue's home repo to set: {issue_home}")
            from_body = [issue_home, *from_body]
        repos = from_body

    if appire_docs_repo not in repos:
        log("adding appire_docs to set (required for SpecKit)")
        repos.append(appire_docs_repo)

    if not repos:
        die(
            "no affected repos could be determined. Add a '## Affected Repos' section to the "
            "issue body, or re-run with --repos owner/a,owner/b",
            code=E_REPOS_MISSING,
        )
    return repos


def _verify_source_repos(repos: list[str], projects_dir: Path) -> None:
    for full in repos:
        reponame = full.rsplit("/", 1)[-1]
        src = projects_dir / reponame
        if not (src / ".git").exists():
            die(f"source repo not found at {src} (from {full})", code=E_REPO_NOT_FOUND)


def _validate_origin_main(repos: list[str], projects_dir: Path) -> None:
    """Validation phase of the two-phase bootstrap (DevKit#27 FR-001).

    For each affected repo, fetch origin and verify ``origin/main`` exists.
    Fail-fast on first repo that fails: no subsequent repos are fetched, and
    no worktrees or branches are created for any repo. The caller MUST run
    this before any filesystem or worktree mutation so that atomicity is
    preserved (FR-004, FR-005, SC-007).
    """
    for full in repos:
        reponame = full.rsplit("/", 1)[-1]
        src = projects_dir / reponame
        log(f"fetch origin: {full}")
        fetch_res = git("fetch", "origin", cwd=src)
        if fetch_res.code != 0:
            detail = fetch_res.stderr.strip() or fetch_res.stdout.strip() or "(no detail)"
            die(
                f"fetch origin failed for {full}: {detail}",
                code=E_ORIGIN_MAIN_UNAVAILABLE,
            )
        verify_res = git(
            "rev-parse", "--verify", "--quiet", "refs/remotes/origin/main",
            cwd=src,
        )
        if verify_res.code != 0:
            die(
                f"origin/main not found in {full} — is main the trunk? is the remote configured?",
                code=E_ORIGIN_MAIN_UNAVAILABLE,
            )


def _format_ack_comment(workspace: Path, repos: list[str]) -> str:
    repos_line = " ".join(repos)
    return (
        f"Bootstrap started by claude. Worktree: `{workspace}`. "
        f"Affected repos: {repos_line}. (Comment auto-posted by devkit-bootstrap.)"
    )


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

    repos = _resolve_affected_repos(issue_home, body, repos_override)

    projects_dir = Path(os.environ["APP_EMPIRE_PROJECTS"])
    workspaces_home = Path(os.environ["APP_EMPIRE_WORKTREES_HOME"])

    _verify_source_repos(repos, projects_dir)
    _validate_origin_main(repos, projects_dir)

    workspace = workspaces_home / f"{repo}-issue-{num}"
    if workspace.exists():
        die(
            f"worktree dir already exists: {workspace} (archive or remove it first)",
            code=E_WORKTREE_EXISTS,
        )

    branch = f"issue-{repo}-{num}"
    info(f"Worktree: {workspace}")
    info(f"Branch:   {branch}")
    info("Repos:")
    for full in repos:
        info(f"  - {full}")

    if dry_run:
        info("")
        info("[dry-run] would create worktree dir, git init, add worktrees, post ack comment")
        return 0

    workspace.mkdir(parents=True, exist_ok=False)
    try:
        init_res = git("init", "--quiet", cwd=workspace)
        if init_res.code != 0:
            die(f"git init failed: {init_res.stderr.strip()}", code=1)

        for full in repos:
            reponame = full.rsplit("/", 1)[-1]
            src = projects_dir / reponame
            wt_target = workspace / reponame
            info(f"Adding worktree: {reponame}  ({src} -> {wt_target}, {branch})")
            add_res = git(
                "worktree", "add", str(wt_target), "-b", branch, "origin/main",
                cwd=src,
            )
            if add_res.code != 0:
                detail = add_res.stderr.strip() or add_res.stdout.strip()
                die(
                    f"git worktree add failed for {reponame}: {detail}",
                    code=1,
                )
    except Exception:
        shutil.rmtree(workspace, ignore_errors=True)
        raise

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
    info(f"    cd {primary} && claude")
    info("")
    return 0
