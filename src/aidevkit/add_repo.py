"""`devkit add-repo` — add a sibling repo's worktree to the current per-issue workspace.

Invoked from anywhere inside `$APP_EMPIRE_WORKTREES_HOME/<Repo>-issue-<N>/`.
Walks the CWD's ancestors to find the per-issue workspace, resolves the named
sibling repo under `$APP_EMPIRE_PROJECTS/<name>`, and adds a `git worktree` on
the issue's branch (creating the branch if absent). Idempotent — if the
target subdir already contains a valid worktree, the command logs a skip and
exits 0.
"""
from __future__ import annotations

import os
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Optional

from .util import (
    E_NOT_IN_PER_ISSUE_WORKSPACE,
    E_REPO_NOT_FOUND,
    E_WORKSPACE_MISSING,
    die,
    git,
    info,
    log,
)

_WS_NAME_RE = re.compile(r"^(?P<repo>[A-Za-z0-9_.-]+)-issue-(?P<n>\d+)$")


@dataclass
class PerIssueContext:
    workspace_dir: Path
    home_repo_name: str
    issue_number: int
    branch: str


def _detect_per_issue_context(cwd: Path, home: Path) -> PerIssueContext:
    """Walk ancestors; first ancestor directly under `home` that matches the
    `<Repo>-issue-<N>` pattern wins.
    """
    cwd_resolved = cwd.resolve()
    home_resolved = home.resolve()
    current: Optional[Path] = cwd_resolved
    while current is not None:
        parent = current.parent
        if parent == home_resolved:
            if current.name.startswith("_"):
                break
            m = _WS_NAME_RE.match(current.name)
            if m:
                return PerIssueContext(
                    workspace_dir=current,
                    home_repo_name=m.group("repo"),
                    issue_number=int(m.group("n")),
                    branch=f"issue-{m.group('repo')}-{m.group('n')}",
                )
            break
        if parent == current:
            break
        current = parent
    die(
        f"not inside a per-issue workspace (cwd={cwd_resolved}). "
        f"cd into $APP_EMPIRE_WORKTREES_HOME/<Repo>-issue-<N>/ first.",
        code=E_NOT_IN_PER_ISSUE_WORKSPACE,
    )
    # unreachable
    raise SystemExit(E_NOT_IN_PER_ISSUE_WORKSPACE)


def _resolve_source_repo(name: str, projects: Path) -> Path:
    source = projects / name
    if not source.is_dir():
        die(
            f"source repo not found at {source}. "
            f"Clone it first: git clone <url> {source}",
            code=E_REPO_NOT_FOUND,
        )
    return source


def _target_points_into(source_repo: Path, target_path: Path) -> bool:
    """True if `target_path/.git` is a worktree file pointing inside `source_repo`."""
    dotgit = target_path / ".git"
    if not dotgit.is_file():
        return False
    try:
        content = dotgit.read_text(errors="replace").strip()
    except OSError:
        return False
    m = re.match(r"gitdir:\s*(.+)$", content)
    if not m:
        return False
    try:
        worktree_gitdir = Path(m.group(1)).resolve()
        source_resolved = source_repo.resolve()
    except Exception:
        return False
    try:
        worktree_gitdir.relative_to(source_resolved)
        return True
    except ValueError:
        return False


def _branch_exists(source_repo: Path, branch: str) -> bool:
    res = git("show-ref", "--verify", f"refs/heads/{branch}", cwd=source_repo)
    return res.code == 0


def _ensure_worktree(source_repo: Path, target_path: Path, branch: str) -> bool:
    """Return True when a new worktree was created, False on idempotent skip."""
    if target_path.exists():
        if _target_points_into(source_repo, target_path):
            info(f"worktree already present at {target_path} — skipping")
            return False
        die(
            f"target path {target_path} exists but is not a git worktree of "
            f"{source_repo}. Resolve the conflict before retrying.",
            code=E_REPO_NOT_FOUND,
        )

    target_path.parent.mkdir(parents=True, exist_ok=True)

    if _branch_exists(source_repo, branch):
        res = git("worktree", "add", str(target_path), branch, cwd=source_repo)
    else:
        res = git(
            "worktree", "add", "-b", branch, str(target_path),
            cwd=source_repo,
        )
    if res.code != 0:
        die(
            f"git worktree add failed: "
            f"{res.stderr.strip() or res.stdout.strip() or 'unknown error'}",
        )
    return True


def cmd_add_repo(repo_name: str) -> int:
    home_env = os.environ.get("APP_EMPIRE_WORKTREES_HOME")
    projects_env = os.environ.get("APP_EMPIRE_PROJECTS")
    if not home_env or not projects_env:
        die(
            "$APP_EMPIRE_WORKTREES_HOME and $APP_EMPIRE_PROJECTS must both "
            "be set (run 'devkit doctor')",
            code=E_WORKSPACE_MISSING,
        )
    home = Path(home_env)
    projects = Path(projects_env)
    if not home.is_dir():
        die(f"$APP_EMPIRE_WORKTREES_HOME is not a directory: {home_env}",
            code=E_WORKSPACE_MISSING)
    if not projects.is_dir():
        die(f"$APP_EMPIRE_PROJECTS is not a directory: {projects_env}",
            code=E_WORKSPACE_MISSING)

    ctx = _detect_per_issue_context(Path.cwd(), home)
    source = _resolve_source_repo(repo_name, projects)
    target = ctx.workspace_dir / repo_name

    info(f"[devkit] Adding worktree: {repo_name} → {target}")
    info(f"  source:  {source}")
    info(f"  branch:  {ctx.branch}")

    created = _ensure_worktree(source, target, ctx.branch)
    if created:
        info(f"worktree created at {target} on {ctx.branch}")
    else:
        log("no changes (idempotent skip)")
    return 0
