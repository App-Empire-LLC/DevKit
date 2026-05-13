"""Epic graph: data model, GitHub API walk, and EPIC.md I/O.

Provides EpicNode / EpicGraph dataclasses plus the functions that build,
persist, and restore them.  All shell calls go through aidevkit.util.gh /
aidevkit.util.git — never import subprocess directly.
"""
from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Literal

import yaml

from .util import gh

# ---------------------------------------------------------------------------
# Data model
# ---------------------------------------------------------------------------

NodeStatus = Literal["not_started", "in_progress", "in_review", "merged"]
NodeType = Literal["epic", "issue"]

_VALID_STATUSES = {"not_started", "in_progress", "in_review", "merged"}
_GITHUB_URL_RE = re.compile(
    r"https://github\.com/([^/]+)/([^/]+)/issues/(\d+)"
)


class EpicGraphInvalid(Exception):
    """Raised when EPIC.md cannot be parsed or fails schema validation."""


@dataclass
class EpicNode:
    ref: str                          # canonical: owner/repo#N (short form: repo#N in YAML)
    type: NodeType
    own_repos: list[str]
    effective_repos: list[str]
    branch_name: str
    parent: str | None
    children: list[str]
    status: NodeStatus


@dataclass
class EpicGraph:
    top_epic: str
    current_issue: str
    execution_order: list[str]        # leaves-first post-order DFS; excludes top_epic
    nodes: dict[str, EpicNode] = field(default_factory=dict)


# ---------------------------------------------------------------------------
# GitHub API helpers
# ---------------------------------------------------------------------------

def _repo_slug_from_url(html_url: str) -> str | None:
    """Extract repo slug from a GitHub issue html_url.

    e.g. https://github.com/App-Empire-LLC/appire_docs/issues/8 → 'appire_docs'
    """
    m = _GITHUB_URL_RE.match(html_url)
    return m.group(2) if m else None


def _owner_repo_from_url(html_url: str) -> str | None:
    """Extract 'owner/repo' from a GitHub issue html_url."""
    m = _GITHUB_URL_RE.match(html_url)
    return f"{m.group(1)}/{m.group(2)}" if m else None


def fetch_sub_issues(owner: str, repo: str, num: int) -> list[dict]:
    """Return sub-issues for a GitHub issue as a list of raw API dicts.

    Returns [] on 404, API error, or JSON parse failure so callers can
    degrade to non-epic mode without special-casing.
    """
    res = gh(
        "api",
        f"repos/{owner}/{repo}/issues/{num}/sub_issues",
        "--paginate",
    )
    if res.code != 0:
        return []
    try:
        data = json.loads(res.stdout or "[]")
    except json.JSONDecodeError:
        return []
    if not isinstance(data, list):
        return []
    return data


# ---------------------------------------------------------------------------
# Graph computation
# ---------------------------------------------------------------------------

def _parse_affected_repos_from_body(body: str) -> list[str]:
    """Extract owner/repo entries from the '## Affected Repos' section."""
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


def compute_effective_repos(nodes: dict[str, EpicNode], ref: str) -> list[str]:
    """Return effective_repos(N) = own_repos(N) ∪ ⋃ effective(child), ordered, deduped."""
    node = nodes[ref]
    seen: set[str] = set()
    result: list[str] = []

    def _add(r: str) -> None:
        if r not in seen:
            seen.add(r)
            result.append(r)

    for r in node.own_repos:
        _add(r)
    for child_ref in node.children:
        for r in compute_effective_repos(nodes, child_ref):
            _add(r)
    return result


def compute_execution_order(top_ref: str, nodes: dict[str, EpicNode]) -> list[str]:
    """Return post-order DFS list of node refs (leaves first), excluding top_ref."""
    order: list[str] = []

    def _visit(ref: str) -> None:
        for child_ref in nodes[ref].children:
            _visit(child_ref)
        if ref != top_ref:
            order.append(ref)

    _visit(top_ref)
    return order


def _walk_node(
    owner: str,
    repo: str,
    num: int,
    parent_ref: str | None,
    nodes: dict[str, EpicNode],
    no_recursive: bool,
    depth: int,
) -> str:
    """Recursively walk one node, populating `nodes`. Returns the node's ref."""
    ref = f"{owner}/{repo}#{num}"

    sub_issues_raw = fetch_sub_issues(owner, repo, num) if depth == 0 or not no_recursive else []
    children_refs: list[str] = []

    for sub in sub_issues_raw:
        html_url = sub.get("html_url", "")
        child_owner_repo = _owner_repo_from_url(html_url)
        child_slug = _repo_slug_from_url(html_url)
        child_num = sub.get("number")
        if not child_owner_repo or not child_slug or not child_num:
            continue
        child_owner, child_repo = child_owner_repo.split("/", 1)
        child_body = sub.get("body", "") or ""
        child_own_repos = _parse_affected_repos_from_body(child_body)
        if not child_own_repos:
            child_own_repos = [child_owner_repo]

        child_ref = _walk_node(
            child_owner,
            child_repo,
            int(child_num),
            ref,
            nodes,
            no_recursive,
            depth + 1,
        )
        children_refs.append(child_ref)

    # Fetch own body for own_repos (only needed at depth 0; sub-issues already processed above)
    if depth == 0:
        # own_repos determined by caller (bootstrap.py) for top; here we set placeholder
        own_repos: list[str] = [f"{owner}/{repo}"]
    else:
        own_repos = []  # filled by parent call

    node_type: NodeType = "epic" if children_refs else "issue"
    branch_name = f"issue-{repo}-{num}"

    nodes[ref] = EpicNode(
        ref=ref,
        type=node_type,
        own_repos=own_repos,
        effective_repos=[],       # computed bottom-up after full walk
        branch_name=branch_name,
        parent=parent_ref,
        children=children_refs,
        status="in_progress" if parent_ref is None else "not_started",
    )
    return ref


def walk_graph(
    owner: str,
    repo: str,
    num: int,
    no_recursive: bool,
    issue_body: str = "",
) -> EpicGraph | None:
    """Walk the GitHub sub-issues graph rooted at owner/repo#num.

    Returns None if the issue has no sub-issues (treat as non-epic).
    `issue_body` is the already-fetched body of the top issue so we can
    extract own_repos without an extra API call.
    """
    sub_issues_raw = fetch_sub_issues(owner, repo, num)
    if not sub_issues_raw:
        return None

    top_ref = f"{owner}/{repo}#{num}"
    nodes: dict[str, EpicNode] = {}

    # Parse top-level own_repos from body
    own_repos = _parse_affected_repos_from_body(issue_body)
    if not own_repos:
        own_repos = [f"{owner}/{repo}"]

    # Build child nodes first (depth-first)
    children_refs: list[str] = []
    for sub in sub_issues_raw:
        html_url = sub.get("html_url", "")
        child_owner_repo = _owner_repo_from_url(html_url)
        child_slug = _repo_slug_from_url(html_url)
        child_num = sub.get("number")
        if not child_owner_repo or not child_slug or not child_num:
            continue
        child_owner, child_repo_name = child_owner_repo.split("/", 1)
        child_body = sub.get("body", "") or ""
        child_own_repos = _parse_affected_repos_from_body(child_body)
        if not child_own_repos:
            child_own_repos = [child_owner_repo]

        child_ref = f"{child_owner}/{child_repo_name}#{child_num}"

        if no_recursive:
            # Leaf only — no further recursion
            child_sub = []
        else:
            child_sub = fetch_sub_issues(child_owner, child_repo_name, int(child_num))

        child_children_refs: list[str] = []
        if child_sub and not no_recursive:
            # Recurse into grandchildren
            for gsub in child_sub:
                g_html = gsub.get("html_url", "")
                g_or = _owner_repo_from_url(g_html)
                g_slug = _repo_slug_from_url(g_html)
                g_num = gsub.get("number")
                if not g_or or not g_slug or not g_num:
                    continue
                g_owner, g_repo_name = g_or.split("/", 1)
                g_body = gsub.get("body", "") or ""
                g_own = _parse_affected_repos_from_body(g_body)
                if not g_own:
                    g_own = [g_or]
                g_ref = f"{g_owner}/{g_repo_name}#{g_num}"
                nodes[g_ref] = EpicNode(
                    ref=g_ref,
                    type="issue",
                    own_repos=g_own,
                    effective_repos=[],
                    branch_name=f"issue-{g_repo_name}-{g_num}",
                    parent=child_ref,
                    children=[],
                    status="not_started",
                )
                child_children_refs.append(g_ref)

        child_node_type: NodeType = "epic" if child_children_refs else "issue"
        nodes[child_ref] = EpicNode(
            ref=child_ref,
            type=child_node_type,
            own_repos=child_own_repos,
            effective_repos=[],
            branch_name=f"issue-{child_repo_name}-{child_num}",
            parent=top_ref,
            children=child_children_refs,
            status="not_started",
        )
        children_refs.append(child_ref)

    node_type: NodeType = "epic" if children_refs else "issue"
    nodes[top_ref] = EpicNode(
        ref=top_ref,
        type=node_type,
        own_repos=own_repos,
        effective_repos=[],
        branch_name=f"issue-{repo}-{num}",
        parent=None,
        children=children_refs,
        status="in_progress",
    )

    # Compute effective_repos bottom-up
    for ref in nodes:
        nodes[ref].effective_repos = compute_effective_repos(nodes, ref)

    execution_order = compute_execution_order(top_ref, nodes)
    current_issue = execution_order[0] if execution_order else top_ref

    return EpicGraph(
        top_epic=top_ref,
        current_issue=current_issue,
        execution_order=execution_order,
        nodes=nodes,
    )


# ---------------------------------------------------------------------------
# EPIC.md I/O
# ---------------------------------------------------------------------------

def _graph_to_frontmatter(graph: EpicGraph) -> dict:
    node_dicts: dict[str, dict] = {}
    for ref, node in graph.nodes.items():
        node_dicts[ref] = {
            "type": node.type,
            "own_repos": node.own_repos,
            "effective_repos": node.effective_repos,
            "branch_name": node.branch_name,
            "parent": node.parent,
            "children": node.children,
            "status": node.status,
        }
    return {
        "top_epic": graph.top_epic,
        "current_issue": graph.current_issue,
        "execution_order": graph.execution_order,
        "graph": node_dicts,
    }


def _frontmatter_to_graph(fm: dict) -> EpicGraph:
    required = {"top_epic", "current_issue", "execution_order", "graph"}
    missing = required - fm.keys()
    if missing:
        raise EpicGraphInvalid(f"EPIC.md missing required fields: {missing}")

    nodes: dict[str, EpicNode] = {}
    for ref, nd in fm["graph"].items():
        status = nd.get("status", "")
        if status not in _VALID_STATUSES:
            raise EpicGraphInvalid(
                f"EPIC.md node {ref!r} has invalid status {status!r}"
            )
        nodes[ref] = EpicNode(
            ref=ref,
            type=nd.get("type", "issue"),
            own_repos=nd.get("own_repos", []),
            effective_repos=nd.get("effective_repos", []),
            branch_name=nd.get("branch_name", ""),
            parent=nd.get("parent"),
            children=nd.get("children", []),
            status=status,
        )

    return EpicGraph(
        top_epic=fm["top_epic"],
        current_issue=fm["current_issue"],
        execution_order=fm["execution_order"],
        nodes=nodes,
    )


def read_epic_md(workspace: Path) -> EpicGraph:
    """Parse EPIC.md and return an EpicGraph.

    Raises EpicGraphInvalid on parse failure or schema violation.
    """
    path = workspace / "EPIC.md"
    if not path.exists():
        raise EpicGraphInvalid(f"EPIC.md not found at {path}")
    text = path.read_text()
    parts = text.split("---\n", 2)
    if len(parts) < 3:
        raise EpicGraphInvalid("EPIC.md has no valid frontmatter delimiters")
    try:
        fm = yaml.safe_load(parts[1]) or {}
    except yaml.YAMLError as exc:
        raise EpicGraphInvalid(f"EPIC.md YAML parse error: {exc}") from exc
    return _frontmatter_to_graph(fm)


def _regenerate_body(graph: EpicGraph, title: str = "") -> str:
    """Build the human-readable markdown body for EPIC.md."""
    lines: list[str] = []
    heading = title or graph.top_epic
    lines.append(f"# {heading}")
    lines.append("")
    lines.append("## Graph")
    lines.append("")

    def _tree(ref: str, indent: int) -> None:
        node = graph.nodes[ref]
        prefix = "    " * indent + ("└── " if indent else "")
        lines.append(f"{prefix}{ref}")
        for child in node.children:
            _tree(child, indent + 1)

    _tree(graph.top_epic, 0)
    lines.append("")
    lines.append("## Execution Order")
    lines.append("")
    for i, ref in enumerate(graph.execution_order, 1):
        lines.append(f"{i}. {ref}")
    lines.append("")
    lines.append("## Current")
    lines.append("")
    lines.append(f"Working on: {graph.current_issue}")
    lines.append("")
    return "\n".join(lines)


def write_epic_md(workspace: Path, graph: EpicGraph, title: str = "") -> None:
    """Write EPIC.md with YAML frontmatter and regenerated markdown body."""
    fm = _graph_to_frontmatter(graph)
    body = _regenerate_body(graph, title)
    fm_text = yaml.safe_dump(fm, sort_keys=False, default_flow_style=False)
    content = "---\n" + fm_text + "---\n\n" + body
    (workspace / "EPIC.md").write_text(content)
