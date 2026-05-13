"""devkit sub-checkout: switch worktrees to a sub-issue's branch."""
from __future__ import annotations

import re
from pathlib import Path
from typing import Optional

from . import config as _config
from . import epic as _epic
from . import projects as _projects
from .util import (
    E_DIRTY_WORKTREE,
    E_EPIC_GRAPH_INVALID,
    E_NODE_NOT_FOUND,
    E_NOT_IN_WORKSPACE,
    E_USAGE,
    die,
    git,
    info,
    log,
)

_ISSUE_REF_RE = re.compile(r"^([^/]+)/([^#]+)#(\d+)$")
_BARE_NUM_RE = re.compile(r"^#?(\d+)$")


def _infer_workspace(num: Optional[int] = None) -> Optional[Path]:
    """Walk CWD upward looking for a workspace root containing EPIC.md."""
    try:
        cfg = _config.load_merged_config(_config.resolve_projects_home())
        home = cfg.workspaces_home.resolve()
    except Exception:
        return None

    cwd = Path.cwd().resolve()
    current = cwd
    while current != current.parent:
        if current.parent == home:
            return current
        current = current.parent
    return None


def _resolve_node_ref(issue_arg: str, graph: _epic.EpicGraph) -> str:
    """Resolve a bare number, #N, or owner/repo#N to a node ref in the graph."""
    bare = _BARE_NUM_RE.match(issue_arg)
    if bare:
        num = int(bare.group(1))
        for ref in graph.nodes:
            if ref.split("#")[-1] == str(num):
                return ref
        die(f"node #{num} not found in EPIC.md graph", code=E_NODE_NOT_FOUND)

    full = _ISSUE_REF_RE.match(issue_arg)
    if full:
        ref = f"{full.group(1)}/{full.group(2)}#{full.group(3)}"
        if ref in graph.nodes:
            return ref
        die(f"node {ref!r} not found in EPIC.md graph", code=E_NODE_NOT_FOUND)

    die(
        f"issue argument must be a number, #N, or owner/repo#N (got: {issue_arg!r})",
        code=E_USAGE,
    )
    return ""  # unreachable


def cmd_sub_checkout(issue_arg: str) -> int:
    workspace = _infer_workspace()
    if workspace is None:
        die(
            "not inside a DevKit workspace — run this command from within a workspace directory",
            code=E_NOT_IN_WORKSPACE,
        )

    epic_md = workspace / "EPIC.md"
    if not epic_md.exists():
        die(
            "no EPIC.md found — this command requires an epic workspace",
            code=E_EPIC_GRAPH_INVALID,
        )

    try:
        graph = _epic.read_epic_md(workspace)
    except _epic.EpicGraphInvalid as exc:
        die(str(exc), code=E_EPIC_GRAPH_INVALID)

    node_ref = _resolve_node_ref(issue_arg, graph)
    node = graph.nodes[node_ref]

    # FR-030: serial enforcement — must check out current_issue only
    if node_ref != graph.current_issue:
        if graph.current_issue == graph.top_epic:
            die(
                f"all sub-issues are done — current pointer is the top epic "
                f"({graph.top_epic}). Run `devkit pr-create` or `devkit sub-merge` "
                f"on the top epic instead.",
                code=E_USAGE,
            )
        die(
            f"cannot check out {node_ref!r} — current issue is {graph.current_issue!r}. "
            f"Merge it first, or update `current_issue` in EPIC.md manually.",
            code=E_USAGE,
        )

    # Load catalog to map owner/repo → worktree directory name
    try:
        projects_home = _config.resolve_projects_home()
        catalog = _projects.parse_projects_md(projects_home / ".devkit" / "PROJECTS.md")
    except Exception as exc:
        die(f"could not load catalog: {exc}", code=1)

    # FR-017: dirty check — only repos in effective(N) (clarification Q2)
    dirty: list[str] = []
    for er in node.effective_repos:
        if not catalog.has_owner_repo(er):
            continue
        entry = catalog.resolve_owner_repo(er)
        wt_path = workspace / entry.name
        if not wt_path.exists():
            continue
        res = git("status", "--porcelain", cwd=wt_path)
        if res.stdout.strip():
            dirty.append(str(wt_path))

    if dirty:
        die(
            "dirty worktree(s) in effective repos — commit or stash changes first:\n"
            + "\n".join(f"  {p}" for p in dirty),
            code=E_DIRTY_WORKTREE,
        )

    # Switch all effective(N) worktrees to N's branch
    for er in node.effective_repos:
        if not catalog.has_owner_repo(er):
            log(f"WARN: {er!r} not in catalog — skipping worktree switch")
            continue
        entry = catalog.resolve_owner_repo(er)
        wt_path = workspace / entry.name
        if not wt_path.exists():
            log(f"WARN: worktree {wt_path} not found — skipping")
            continue
        res = git("checkout", node.branch_name, cwd=wt_path)
        if res.code != 0:
            die(
                f"git checkout {node.branch_name!r} failed in {er}: "
                f"{res.stderr.strip() or res.stdout.strip()}",
                code=1,
            )
        info(f"Switched {entry.name} → {node.branch_name}")

    # FR-018: update EPIC.md
    graph.current_issue = node_ref
    graph.nodes[node_ref].status = "in_progress"
    _epic.write_epic_md(workspace, graph)
    info(f"EPIC.md updated: current_issue = {node_ref}")
    return 0
