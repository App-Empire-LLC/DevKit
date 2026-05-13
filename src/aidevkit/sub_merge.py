"""devkit sub-merge: verify PRs merged, advance epic pointer, cascade-up."""
from __future__ import annotations

import re
from pathlib import Path
from typing import Optional

from . import config as _config
from . import epic as _epic
from . import projects as _projects
from ._prs import check_prs_merged
from .pr_create import _open_prs_for
from .util import (
    E_EPIC_GRAPH_INVALID,
    E_NODE_NOT_FOUND,
    E_NOT_IN_WORKSPACE,
    E_PRS_NOT_MERGED,
    E_USAGE,
    die,
    info,
    log,
)

_ISSUE_REF_RE = re.compile(r"^([^/]+)/([^#]+)#(\d+)$")
_BARE_NUM_RE = re.compile(r"^#?(\d+)$")


def _infer_workspace() -> Optional[Path]:
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
    bare = _BARE_NUM_RE.match(issue_arg)
    if bare:
        num = bare.group(1)
        for ref in graph.nodes:
            if ref.split("#")[-1] == num:
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


def _cascade_up(
    workspace: Path,
    graph: _epic.EpicGraph,
    parent_ref: Optional[str],
) -> None:
    """Open PRs for parent if all its children are merged (one level only, FR-024)."""
    if parent_ref is None:
        return
    parent = graph.nodes[parent_ref]
    all_merged = all(
        graph.nodes[c].status == "merged" for c in parent.children
    )
    if not all_merged:
        return

    info(f"All children of {parent_ref} merged — opening PRs via cascade-up")
    _open_prs_for(workspace, graph, parent_ref, dry_run=False)
    parent.status = "in_review"
    _epic.write_epic_md(workspace, graph)
    info(f"Cascade-up: {parent_ref} → in_review")
    # Stop here — parent must be explicitly sub-merged (FR-024 clarification)


def cmd_sub_merge(issue_arg: str) -> int:
    workspace = _infer_workspace()
    if workspace is None:
        die(
            "not inside a DevKit workspace — run this command from within a workspace directory",
            code=E_NOT_IN_WORKSPACE,
        )

    if not (workspace / "EPIC.md").exists():
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

    # T040: verify all PRs for this node are merged
    try:
        projects_home = _config.resolve_projects_home()
        catalog = _projects.parse_projects_md(projects_home / ".devkit" / "PROJECTS.md")
    except Exception as exc:
        die(f"could not load catalog: {exc}", code=1)

    upstream_paths: list[tuple[str, Path]] = []
    for er in node.effective_repos:
        if catalog.has_owner_repo(er):
            entry = catalog.resolve_owner_repo(er)
            upstream_paths.append((er, projects_home / entry.name))

    blockers = check_prs_merged(upstream_paths, node.branch_name)
    if blockers:
        log(f"ERROR: {len(blockers)} PR(s) not merged for {node_ref}:")
        for b in blockers:
            log(f"  - {b}")
        return E_PRS_NOT_MERGED

    # T041: mark merged + advance current_issue
    node.status = "merged"
    if node_ref in graph.execution_order:
        idx = graph.execution_order.index(node_ref)
        if idx + 1 < len(graph.execution_order):
            graph.current_issue = graph.execution_order[idx + 1]
        else:
            # execution_order exhausted → point at top_epic (clarification Q5)
            graph.current_issue = graph.top_epic
    else:
        # node not in execution_order (e.g., it's the top epic itself)
        graph.current_issue = graph.top_epic

    _epic.write_epic_md(workspace, graph)
    info(f"{node_ref} marked merged. current_issue → {graph.current_issue}")

    # T042–T043: cascade-up
    _cascade_up(workspace, graph, node.parent)

    return 0
