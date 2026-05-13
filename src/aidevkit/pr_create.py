"""devkit pr-create: open PRs for the current sub-issue with correct base branches."""
from __future__ import annotations

from pathlib import Path

from . import config as _config
from . import epic as _epic
from . import projects as _projects
from .util import (
    E_EPIC_GRAPH_INVALID,
    E_NOT_IN_WORKSPACE,
    die,
    gh,
    info,
    log,
)


def _infer_workspace() -> Path | None:
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


def _open_prs_for(
    workspace: Path,
    graph: _epic.EpicGraph,
    node_ref: str,
    dry_run: bool = False,
) -> dict[str, str]:
    """Open PRs for a given node; return {owner_repo: pr_url}.

    Exposed as a module-level helper for use by sub_merge cascade-up (T043).
    """
    node = graph.nodes[node_ref]
    parent = graph.nodes.get(node.parent) if node.parent else None

    try:
        projects_home = _config.resolve_projects_home()
        catalog = _projects.parse_projects_md(projects_home / ".devkit" / "PROJECTS.md")
    except Exception as exc:
        die(f"could not load catalog: {exc}", code=1)

    # Determine base branch
    if parent is not None:
        base_branch = parent.branch_name
    else:
        # top epic — target default branch
        # Peek at the first effective repo's default branch from catalog
        base_branch = "main"
        for er in node.effective_repos:
            if catalog.has_owner_repo(er):
                entry = catalog.resolve_owner_repo(er)
                base_branch = f"origin/{entry.default_branch}"
                break

    # Fetch issue title for PR title
    node_owner_repo, node_num_str = node_ref.rsplit("#", 1)
    title_res = gh(
        "issue", "view", node_num_str,
        "--repo", node_owner_repo,
        "--json", "title",
    )
    pr_title = f"[epic] {node_ref}"
    if title_res.code == 0:
        import json
        try:
            pr_title = json.loads(title_res.stdout).get("title", pr_title)
        except Exception:
            pass

    pr_urls: dict[str, str] = {}

    if not dry_run:
        # Pass 1: create PRs
        for er in node.effective_repos:
            if not catalog.has_owner_repo(er):
                log(f"WARN: {er!r} not in catalog — skipping PR creation")
                continue
            draft_body = (
                f"Part of epic sub-issue {node_ref}\n\n"
                f"*Auto-created by `devkit pr-create`*"
            )
            res = gh(
                "pr", "create",
                "--repo", er,
                "--head", node.branch_name,
                "--base", base_branch,
                "--title", pr_title,
                "--body", draft_body,
            )
            if res.code != 0:
                log(f"WARN: pr create failed for {er}: {res.stderr.strip() or res.stdout.strip()}")
                continue
            url = res.stdout.strip()
            pr_urls[er] = url
            info(f"PR opened: {url}")

        # Pass 2: cross-link sibling PRs
        if len(pr_urls) > 1:
            for er, pr_url in pr_urls.items():
                siblings = {k: v for k, v in pr_urls.items() if k != er}
                sibling_section = "\n\n## Sibling PRs\n" + "\n".join(
                    f"- {repo}: {url}" for repo, url in siblings.items()
                )
                body_with_links = (
                    f"Part of epic sub-issue {node_ref}{sibling_section}\n\n"
                    f"*Auto-created by `devkit pr-create`*"
                )
                edit_res = gh(
                    "pr", "edit", pr_url,
                    "--repo", er,
                    "--body", body_with_links,
                )
                if edit_res.code != 0:
                    log(f"WARN: could not update PR body for {er} (cross-links not added)")

    return pr_urls


def cmd_pr_create(dry_run: bool = False) -> int:
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

    node_ref = graph.current_issue
    node = graph.nodes[node_ref]

    info(f"Opening PRs for {node_ref} (branch: {node.branch_name})")

    _open_prs_for(workspace, graph, node_ref, dry_run=dry_run)

    # FR-021: update EPIC.md status → in_review
    graph.nodes[node_ref].status = "in_review"
    _epic.write_epic_md(workspace, graph)
    info(f"EPIC.md updated: {node_ref} → in_review")
    return 0
