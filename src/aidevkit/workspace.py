"""DevKit workspace stamping: WORKSPACE.md, TRUNK.md, PROJECTS.md.

Schemas documented in
``appire_docs/docs/workflows/devkit-workspaces.md`` § File Schemas.

This module owns writing the three reserved files at the workspace root.
``parent_issue`` and ``children`` frontmatter fields are out of scope for
DevKit#37; the schema reserves those slots but bootstrap does not stamp
them in this issue.
"""
from __future__ import annotations

import datetime
from pathlib import Path

import yaml


def stamp_workspace_md(
    workspace: Path,
    *,
    issue_url: str,
    issue_owner_repo: str,
    issue_number: int,
    issue_title: str,
    affected_repos: list[str],
    trunk_branch: str,
    stamp_devkit_version: str,
    stamp_config_sha: str,
    template_stamp_sha: str,
    stamp_date: str | None = None,
) -> None:
    """Write ``<workspace>/WORKSPACE.md`` with the stamped frontmatter."""
    if stamp_date is None:
        stamp_date = datetime.date.today().isoformat()

    frontmatter: dict[str, object] = {
        "issue_url": issue_url,
        "issue_owner_repo": issue_owner_repo,
        "issue_number": int(issue_number),
        "issue_title": issue_title,
        "affected_repos": list(affected_repos),
        "trunk_branch": trunk_branch,
        "stamp_date": stamp_date,
        "stamp_devkit_version": stamp_devkit_version,
        "stamp_config_sha": stamp_config_sha,
        "template_stamp_sha": template_stamp_sha,
        "status": "active",
    }

    body = (
        "---\n"
        + yaml.safe_dump(frontmatter, sort_keys=False, default_flow_style=False)
        + "---\n\n"
        + "## Notes\n"
    )
    (workspace / "WORKSPACE.md").write_text(body)


def stamp_trunk_md(workspace: Path, trunk_branch: str) -> None:
    """Write ``<workspace>/TRUNK.md`` — one line, the trunk branch name.

    Two-line form (with a `parent: ...` second line) is reserved for the
    parent/children follow-up issue.
    """
    (workspace / "TRUNK.md").write_text(f"{trunk_branch}\n")


def stamp_projects_md(workspace: Path, raw_catalog_text: str) -> None:
    """Write ``<workspace>/PROJECTS.md`` as a verbatim copy of the projects-home
    catalog. Same bytes — diffable, idempotent, FR-011 verbatim guarantee."""
    (workspace / "PROJECTS.md").write_text(raw_catalog_text)
