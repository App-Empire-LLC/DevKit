"""Unit tests for the `review_issue` block in `.devkit/config.yaml`.

Covers spec 001-review-issue-standard-path (DevKit#52) FR-002, FR-004, FR-006:
the new optional ``standard_path`` field, its absence semantics, validation
rules, and the relative-vs-absolute path resolution against ``projects_home``.

Hermetic: writes throwaway YAML into tmp_path and invokes
``load_review_issue_config`` directly. No real `.devkit/` lookup; no real
filesystem state outside tmp_path is touched.
"""
from __future__ import annotations

from pathlib import Path

import pytest
import typer

from aidevkit.config import ReviewIssueConfig, load_review_issue_config


def _write_config(projects_home: Path, body: str) -> Path:
    devkit = projects_home / ".devkit"
    devkit.mkdir(parents=True, exist_ok=True)
    config = devkit / "config.yaml"
    config.write_text(body)
    return config


# --------------------------------------------------------------------------- #
# T015: field absent → standard_path is None
# --------------------------------------------------------------------------- #


def test_standard_path_field_absent_yields_none(tmp_path: Path) -> None:
    """No `standard_path` in YAML → ReviewIssueConfig.standard_path is None."""
    _write_config(
        tmp_path,
        "version: 1\norg: TestOrg\nworkspaces_home: /tmp\nreview_issue:\n  reviewer_id: claude\n",
    )
    cfg = load_review_issue_config(tmp_path)
    assert cfg.standard_path is None


def test_review_issue_block_entirely_absent_yields_defaults(tmp_path: Path) -> None:
    """No `review_issue` block at all → all defaults; no errors."""
    _write_config(
        tmp_path,
        "version: 1\norg: TestOrg\nworkspaces_home: /tmp\n",
    )
    cfg = load_review_issue_config(tmp_path)
    assert cfg == ReviewIssueConfig()


# --------------------------------------------------------------------------- #
# T016: absolute path used as-is
# --------------------------------------------------------------------------- #


def test_standard_path_absolute_used_as_is(tmp_path: Path) -> None:
    target = tmp_path / "abs.md"
    target.write_text("# abs\n")
    _write_config(
        tmp_path,
        "version: 1\norg: TestOrg\nworkspaces_home: /tmp\nreview_issue:\n"
        f"  standard_path: {target}\n",
    )
    cfg = load_review_issue_config(tmp_path)
    assert cfg.standard_path == target


# --------------------------------------------------------------------------- #
# T017: relative path resolved against projects_home
# --------------------------------------------------------------------------- #


def test_standard_path_relative_resolved_against_projects_home(tmp_path: Path) -> None:
    """Relative `standard_path` MUST resolve against projects_home, not cwd."""
    sub = tmp_path / "appire_docs" / "docs" / "engineering" / "standards"
    sub.mkdir(parents=True)
    (sub / "issue_authoring.md").write_text("# rel\n")
    _write_config(
        tmp_path,
        "version: 1\norg: TestOrg\nworkspaces_home: /tmp\nreview_issue:\n"
        "  standard_path: appire_docs/docs/engineering/standards/issue_authoring.md\n",
    )
    cfg = load_review_issue_config(tmp_path)
    assert cfg.standard_path == (sub / "issue_authoring.md").resolve()


# --------------------------------------------------------------------------- #
# T018–T019: invalid values
# --------------------------------------------------------------------------- #


def test_standard_path_non_string_rejected(tmp_path: Path) -> None:
    _write_config(
        tmp_path,
        "version: 1\norg: TestOrg\nworkspaces_home: /tmp\nreview_issue:\n  standard_path: 42\n",
    )
    with pytest.raises(typer.Exit) as excinfo:
        load_review_issue_config(tmp_path)
    assert excinfo.value.exit_code == 70  # E_CONFIG_INVALID


def test_standard_path_empty_string_rejected(tmp_path: Path) -> None:
    _write_config(
        tmp_path,
        "version: 1\norg: TestOrg\nworkspaces_home: /tmp\nreview_issue:\n  standard_path: \"\"\n",
    )
    with pytest.raises(typer.Exit) as excinfo:
        load_review_issue_config(tmp_path)
    assert excinfo.value.exit_code == 70


def test_standard_path_mapping_rejected(tmp_path: Path) -> None:
    """V5: a mapping value is rejected (must be a string)."""
    _write_config(
        tmp_path,
        "version: 1\norg: TestOrg\nworkspaces_home: /tmp\nreview_issue:\n"
        "  standard_path:\n    nested: oops\n",
    )
    with pytest.raises(typer.Exit) as excinfo:
        load_review_issue_config(tmp_path)
    assert excinfo.value.exit_code == 70


# --------------------------------------------------------------------------- #
# Co-existence with sibling fields
# --------------------------------------------------------------------------- #


def test_standard_path_coexists_with_reviewer_id_and_gate(tmp_path: Path) -> None:
    target = tmp_path / "co.md"
    target.write_text("# co\n")
    _write_config(
        tmp_path,
        "version: 1\norg: TestOrg\nworkspaces_home: /tmp\nreview_issue:\n"
        "  reviewer_id: gpt\n"
        f"  standard_path: {target}\n"
        "  gate:\n    project_board_required: false\n",
    )
    cfg = load_review_issue_config(tmp_path)
    assert cfg.reviewer_id == "gpt"
    assert cfg.project_board_required is False
    assert cfg.standard_path == target


def test_source_config_path_populated_when_block_present(tmp_path: Path) -> None:
    """Source path is stamped on the dataclass so the resolver can label errors."""
    cfg_file = _write_config(
        tmp_path,
        "version: 1\norg: TestOrg\nworkspaces_home: /tmp\nreview_issue:\n  reviewer_id: claude\n",
    )
    cfg = load_review_issue_config(tmp_path)
    assert cfg.source_config_path == cfg_file
