"""Unit tests for `aidevkit.workspace` — reserved-file stamping."""
from __future__ import annotations

from pathlib import Path

import yaml

from aidevkit.workspace import (
    stamp_projects_md,
    stamp_trunk_md,
    stamp_workspace_md,
)


def _split_frontmatter(text: str) -> tuple[dict, str]:
    assert text.startswith("---\n")
    end = text.index("\n---\n", 4)
    fm = yaml.safe_load(text[4:end])
    body = text[end + 5:]
    return fm, body


# ----- stamp_workspace_md -----------------------------------------------------

def test_workspace_md_required_fields(tmp_path: Path) -> None:
    stamp_workspace_md(
        tmp_path,
        issue_url="https://github.com/org/repo/issues/42",
        issue_owner_repo="org/repo",
        issue_number=42,
        issue_title="Some title",
        affected_repos=["org/repo"],
        trunk_branch="main",
        stamp_devkit_version="0.4.0",
        stamp_config_sha="abc1234",
        template_stamp_sha="0" * 64,
        stamp_date="2026-04-29",
    )
    text = (tmp_path / "WORKSPACE.md").read_text()
    fm, body = _split_frontmatter(text)
    assert fm["issue_url"] == "https://github.com/org/repo/issues/42"
    assert fm["issue_owner_repo"] == "org/repo"
    assert fm["issue_number"] == 42
    assert fm["issue_title"] == "Some title"
    assert fm["affected_repos"] == ["org/repo"]
    assert fm["trunk_branch"] == "main"
    assert fm["stamp_date"] == "2026-04-29"
    assert fm["stamp_devkit_version"] == "0.4.0"
    assert fm["stamp_config_sha"] == "abc1234"
    assert fm["template_stamp_sha"] == "0" * 64
    assert fm["status"] == "active"
    assert "## Notes" in body


def test_workspace_md_no_parent_or_children_in_this_issue(tmp_path: Path) -> None:
    """parent_issue/children are out of scope per spec Assumptions; verify
    bootstrap-stamp does NOT include them."""
    stamp_workspace_md(
        tmp_path,
        issue_url="https://github.com/org/repo/issues/42",
        issue_owner_repo="org/repo",
        issue_number=42,
        issue_title="t",
        affected_repos=["org/repo"],
        trunk_branch="main",
        stamp_devkit_version="0.4.0",
        stamp_config_sha="abc",
        template_stamp_sha="0" * 64,
    )
    fm, _ = _split_frontmatter((tmp_path / "WORKSPACE.md").read_text())
    assert "parent_issue" not in fm
    assert "children" not in fm


def test_workspace_md_yaml_round_trips(tmp_path: Path) -> None:
    stamp_workspace_md(
        tmp_path,
        issue_url="https://github.com/o/r/issues/1",
        issue_owner_repo="o/r",
        issue_number=1,
        issue_title="contains: colons and 'quotes'",
        affected_repos=["o/r", "o/s"],
        trunk_branch="main",
        stamp_devkit_version="0.4.0",
        stamp_config_sha="abc",
        template_stamp_sha="0" * 64,
    )
    fm, _ = _split_frontmatter((tmp_path / "WORKSPACE.md").read_text())
    # Verify safe_dump escaped the title properly.
    assert fm["issue_title"] == "contains: colons and 'quotes'"


def test_workspace_md_default_stamp_date_is_today(tmp_path: Path) -> None:
    import datetime
    stamp_workspace_md(
        tmp_path,
        issue_url="https://github.com/o/r/issues/1",
        issue_owner_repo="o/r",
        issue_number=1,
        issue_title="t",
        affected_repos=["o/r"],
        trunk_branch="main",
        stamp_devkit_version="0.4.0",
        stamp_config_sha="abc",
        template_stamp_sha="0" * 64,
    )
    fm, _ = _split_frontmatter((tmp_path / "WORKSPACE.md").read_text())
    assert fm["stamp_date"] == datetime.date.today().isoformat()


# ----- stamp_trunk_md ---------------------------------------------------------

def test_trunk_md_single_line(tmp_path: Path) -> None:
    stamp_trunk_md(tmp_path, "main")
    assert (tmp_path / "TRUNK.md").read_text() == "main\n"


def test_trunk_md_custom_branch(tmp_path: Path) -> None:
    stamp_trunk_md(tmp_path, "develop")
    assert (tmp_path / "TRUNK.md").read_text() == "develop\n"


# ----- stamp_projects_md ------------------------------------------------------

def test_projects_md_verbatim_copy(tmp_path: Path) -> None:
    raw = (
        "# Projects\n\n"
        "| name | git_url | description |\n"
        "|------|---------|-------------|\n"
        "| repo-a | git@github.com:org/repo-a.git | desc |\n"
    )
    stamp_projects_md(tmp_path, raw)
    assert (tmp_path / "PROJECTS.md").read_text() == raw


def test_projects_md_preserves_byte_for_byte(tmp_path: Path) -> None:
    """FR-011 says 'verbatim' — including trailing whitespace, blank lines, etc."""
    raw = "  weird whitespace  \n\n\nblank lines\n"
    stamp_projects_md(tmp_path, raw)
    assert (tmp_path / "PROJECTS.md").read_text() == raw
