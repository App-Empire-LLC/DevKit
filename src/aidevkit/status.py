"""`devkit status` — summarize every active per-issue workspace.

Scans `$APP_EMPIRE_WORKTREES_HOME`, enumerates `<Repo>-issue-<N>` dirs
(excluding `_archived/`), and for each workspace collects issue state,
per-repo branch state, and per-branch PR lists. A workspace-level
`archivable` flag is derived from the PR-merged signal (shared with
`devkit archive` via `_prs.py`).

Output modes: human-readable text (default) and JSON (`--json`, conforms to
`aidevkit/schemas/status.schema.json`).
"""
from __future__ import annotations

import concurrent.futures
import dataclasses
import json
import os
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Literal, Optional

from ._prs import PR, prs_for_branch
from .util import (
    E_WORKSPACE_MISSING,
    die,
    gh,
    git,
    info,
    out,
)

_WS_NAME_RE = re.compile(r"^(?P<repo>[A-Za-z0-9_.-]+)-issue-(?P<n>\d+)$")
_REMOTE_GITHUB = re.compile(
    r"^(?:https://github\.com/|git@github\.com:)([^/]+)/([^/]+?)(?:\.git)?$"
)


@dataclass
class Issue:
    owner_repo: str
    number: int
    title: str
    state: Literal["open", "closed", "unknown"]


@dataclass
class BranchState:
    ahead: int
    behind: int
    dirty: bool
    missing: bool


@dataclass
class RepoStatus:
    name: str
    worktree_present: bool
    branch_state: Optional[BranchState]
    prs: list[PR] = field(default_factory=list)


@dataclass
class Workspace:
    dir_name: str
    issue: Issue
    branch: str
    archivable: bool
    repos: list[RepoStatus] = field(default_factory=list)


def _home() -> Path:
    home = os.environ.get("APP_EMPIRE_WORKTREES_HOME")
    if not home:
        die("$APP_EMPIRE_WORKTREES_HOME not set (run 'devkit doctor')",
            code=E_WORKSPACE_MISSING)
    home_path = Path(home)
    if not home_path.is_dir():
        die(f"$APP_EMPIRE_WORKTREES_HOME is not a directory: {home}",
            code=E_WORKSPACE_MISSING)
    return home_path.resolve()


def _enumerate_workspaces(home: Path) -> list[Path]:
    entries: list[Path] = []
    for child in sorted(home.iterdir()):
        if not child.is_dir():
            continue
        if child.name.startswith("_"):
            continue
        if _WS_NAME_RE.match(child.name):
            entries.append(child)
    return entries


def _parse_dir_name(dir_name: str) -> Optional[tuple[str, int]]:
    m = _WS_NAME_RE.match(dir_name)
    if not m:
        return None
    return m.group("repo"), int(m.group("n"))


def _parse_owner_repo_from_url(url: str) -> Optional[str]:
    m = _REMOTE_GITHUB.match(url)
    if not m:
        return None
    return f"{m.group(1)}/{m.group(2)}"


def _discover_repo_worktrees(workspace: Path) -> list[tuple[str, Path, Path]]:
    """Return list of (subdir_name, worktree_path, upstream_root) for each repo.

    `upstream_root` may not exist on disk if the user deleted it externally;
    the caller signals `worktree_present=False` in that case.
    """
    found: list[tuple[str, Path, Path]] = []
    if not workspace.is_dir():
        return found
    for subdir in sorted(workspace.iterdir()):
        if not subdir.is_dir():
            continue
        if subdir.name in ("specs", ".git"):
            continue
        dotgit = subdir / ".git"
        if not dotgit.is_file():
            continue
        content = dotgit.read_text(errors="replace").strip()
        m = re.match(r"gitdir:\s*(.+)$", content)
        if not m:
            continue
        try:
            worktree_gitdir = Path(m.group(1)).resolve()
            upstream_root = worktree_gitdir.parent.parent.parent
        except Exception:
            continue
        found.append((subdir.name, subdir, upstream_root))
    return found


def _resolve_owner_repo(upstream_root: Path) -> Optional[str]:
    if not upstream_root.is_dir():
        return None
    res = git("remote", "get-url", "origin", cwd=upstream_root)
    if res.code != 0:
        return None
    return _parse_owner_repo_from_url(res.stdout.strip())


def _collect_branch_state(worktree: Path, branch: str) -> Optional[BranchState]:
    """Collect BranchState via git. Returns None if the worktree is unusable."""
    if not worktree.is_dir():
        return None
    dotgit = worktree / ".git"
    if not dotgit.exists():
        return None

    status_res = git("status", "--porcelain", cwd=worktree)
    if status_res.code != 0:
        return BranchState(ahead=0, behind=0, dirty=False, missing=True)
    dirty = bool(status_res.stdout.strip())

    branch_res = git("rev-parse", "--abbrev-ref", "HEAD", cwd=worktree)
    current_branch = branch_res.stdout.strip() if branch_res.code == 0 else ""
    missing = current_branch in ("", "HEAD")

    upstream_ref = f"origin/{branch}"
    rev_res = git(
        "rev-list", "--left-right", "--count", f"{upstream_ref}...HEAD",
        cwd=worktree,
    )
    ahead = 0
    behind = 0
    if rev_res.code == 0:
        parts = rev_res.stdout.strip().split()
        if len(parts) == 2:
            try:
                behind = int(parts[0])
                ahead = int(parts[1])
            except ValueError:
                pass
    else:
        missing = True

    return BranchState(ahead=ahead, behind=behind, dirty=dirty, missing=missing)


def _collect_issue(owner_repo: str, number: int) -> Issue:
    res = gh(
        "issue", "view", str(number),
        "--repo", owner_repo,
        "--json", "state,title",
    )
    if res.code != 0:
        return Issue(owner_repo=owner_repo, number=number, title="", state="unknown")
    try:
        payload = json.loads(res.stdout or "{}")
    except json.JSONDecodeError:
        return Issue(owner_repo=owner_repo, number=number, title="", state="unknown")
    raw_state = (payload.get("state") or "").upper()
    if raw_state == "OPEN":
        state: Literal["open", "closed", "unknown"] = "open"
    elif raw_state == "CLOSED":
        state = "closed"
    else:
        state = "unknown"
    return Issue(
        owner_repo=owner_repo,
        number=number,
        title=str(payload.get("title") or ""),
        state=state,
    )


def _derive_archivable(workspace: Workspace) -> bool:
    if workspace.issue.state != "closed":
        return False
    if not workspace.repos:
        return False
    for repo in workspace.repos:
        if not any(pr.state == "merged" for pr in repo.prs):
            return False
    return True


def _build_workspace(workspace_dir: Path) -> Optional[Workspace]:
    parsed = _parse_dir_name(workspace_dir.name)
    if parsed is None:
        return None
    home_repo, issue_num = parsed
    branch = f"issue-{home_repo}-{issue_num}"

    worktrees = _discover_repo_worktrees(workspace_dir)

    owner_for_home: Optional[str] = None
    resolved: list[tuple[str, Path, Optional[str]]] = []
    for subdir_name, wt_path, upstream_root in worktrees:
        owner_repo = _resolve_owner_repo(upstream_root)
        resolved.append((subdir_name, wt_path, owner_repo))
        if owner_for_home is None and owner_repo is not None:
            candidate_owner, candidate_repo = owner_repo.split("/", 1)
            if candidate_repo == home_repo:
                owner_for_home = candidate_owner

    if owner_for_home is None:
        for _, _, owner_repo in resolved:
            if owner_repo is not None:
                owner_for_home = owner_repo.split("/", 1)[0]
                break

    if owner_for_home is None:
        issue = Issue(
            owner_repo=f"?/{home_repo}",
            number=issue_num,
            title="",
            state="unknown",
        )
    else:
        issue = _collect_issue(f"{owner_for_home}/{home_repo}", issue_num)

    repos_with_owner: list[tuple[str, Path]] = [
        (owner_repo, wt_path)
        for _, wt_path, owner_repo in resolved
        if owner_repo is not None
    ]
    if repos_with_owner and issue.state != "unknown":
        per_repo_prs = prs_for_branch(repos_with_owner, branch)
    else:
        per_repo_prs = {owner_repo: [] for owner_repo, _ in repos_with_owner}

    repo_statuses: list[RepoStatus] = []
    for subdir_name, wt_path, owner_repo in resolved:
        branch_state = _collect_branch_state(wt_path, branch)
        worktree_present = branch_state is not None
        prs = per_repo_prs.get(owner_repo, []) if owner_repo else []
        repo_statuses.append(
            RepoStatus(
                name=subdir_name,
                worktree_present=worktree_present,
                branch_state=branch_state,
                prs=prs,
            )
        )

    ws = Workspace(
        dir_name=workspace_dir.name,
        issue=issue,
        branch=branch,
        archivable=False,
        repos=repo_statuses,
    )
    ws.archivable = _derive_archivable(ws)
    return ws


def _build_workspaces(home: Path) -> list[Workspace]:
    dirs = _enumerate_workspaces(home)
    if not dirs:
        return []
    results: list[Workspace] = []
    with concurrent.futures.ThreadPoolExecutor(max_workers=8) as pool:
        futures = {pool.submit(_build_workspace, d): d for d in dirs}
        for fut in concurrent.futures.as_completed(futures):
            ws = fut.result()
            if ws is not None:
                results.append(ws)
    results.sort(key=lambda w: w.dir_name)
    return results


def _render_json(workspaces: list[Workspace]) -> None:
    payload = {
        "version": 1,
        "workspaces": [_workspace_to_dict(w) for w in workspaces],
    }
    out.print(json.dumps(payload, indent=2))


def _workspace_to_dict(w: Workspace) -> dict:
    return {
        "dir_name": w.dir_name,
        "issue": dataclasses.asdict(w.issue),
        "branch": w.branch,
        "archivable": w.archivable,
        "repos": [_repo_to_dict(r) for r in w.repos],
    }


def _repo_to_dict(r: RepoStatus) -> dict:
    return {
        "name": r.name,
        "worktree_present": r.worktree_present,
        "branch_state": dataclasses.asdict(r.branch_state) if r.branch_state else None,
        "prs": [dataclasses.asdict(pr) for pr in r.prs],
    }


def _render_text(workspaces: list[Workspace]) -> None:
    if not workspaces:
        info("no active workspaces found under $APP_EMPIRE_WORKTREES_HOME")
        return
    for w in workspaces:
        archivable_tag = " [archivable]" if w.archivable else ""
        out.print(
            f"{w.dir_name}  {w.issue.owner_repo}#{w.issue.number} "
            f"({w.issue.state}){archivable_tag}"
        )
        if w.issue.title:
            out.print(f"  title: {w.issue.title}")
        for r in w.repos:
            if not r.worktree_present or r.branch_state is None:
                out.print(f"  {r.name:<16} worktree: MISSING")
            else:
                bs = r.branch_state
                parts = [f"ahead {bs.ahead}", f"behind {bs.behind}"]
                if bs.dirty:
                    parts.append("dirty")
                if bs.missing:
                    parts.append("branch-missing")
                out.print(f"  {r.name:<16} " + "  ".join(parts))
            if r.prs:
                for pr in r.prs:
                    out.print(f"    PR #{pr.number:<6} {pr.state:<8} {pr.url}")


def cmd_status(json_output: bool) -> int:
    home = _home()
    workspaces = _build_workspaces(home)
    if json_output:
        _render_json(workspaces)
    else:
        _render_text(workspaces)
    return 0
