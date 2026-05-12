"""Unit tests for `aidevkit.projects` — PROJECTS.md catalog parsing."""
from __future__ import annotations

from pathlib import Path

import pytest
import typer

from aidevkit.projects import Catalog, parse_projects_md


def _write(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text)


def _minimal_table(rows: list[str]) -> str:
    return (
        "# Projects\n\n"
        "| name | git_url | default_branch | description |\n"
        "|------|---------|----------------|-------------|\n"
        + "\n".join(rows)
        + "\n"
    )


# ----- happy path -------------------------------------------------------------

def test_minimal_valid_table(tmp_path: Path) -> None:
    p = tmp_path / "PROJECTS.md"
    _write(
        p,
        _minimal_table(
            [
                "| repo-a | git@github.com:org/repo-a.git | main | First repo |",
                "| repo-b | git@github.com:org/repo-b.git | dev | Second repo |",
            ]
        ),
    )
    cat = parse_projects_md(p)
    assert isinstance(cat, Catalog)
    assert len(cat.entries) == 2
    assert cat.entries[0].name == "repo-a"
    assert cat.entries[0].git_url == "git@github.com:org/repo-a.git"
    assert cat.entries[0].default_branch == "main"
    assert cat.entries[1].default_branch == "dev"


def test_default_branch_column_optional(tmp_path: Path) -> None:
    p = tmp_path / "PROJECTS.md"
    _write(
        p,
        "| name | git_url | description |\n"
        "|------|---------|-------------|\n"
        "| repo-a | git@github.com:org/repo-a.git | desc |\n",
    )
    cat = parse_projects_md(p)
    assert cat.entries[0].default_branch == "main"


def test_unknown_columns_ignored(tmp_path: Path) -> None:
    """Forward-compat: future `path` column is ignored by current parser."""
    p = tmp_path / "PROJECTS.md"
    _write(
        p,
        "| name | git_url | path | default_branch | description |\n"
        "|------|---------|------|----------------|-------------|\n"
        "| repo-a | git@github.com:org/repo-a.git | sub/repo-a | main | desc |\n",
    )
    cat = parse_projects_md(p)
    assert len(cat.entries) == 1
    assert cat.entries[0].name == "repo-a"


def test_resolve_by_name(tmp_path: Path) -> None:
    p = tmp_path / "PROJECTS.md"
    _write(
        p,
        _minimal_table(["| repo-a | git@github.com:org/repo-a.git | main | desc |"]),
    )
    cat = parse_projects_md(p)
    entry = cat.resolve("repo-a")
    assert entry.name == "repo-a"


def test_resolve_unknown_name(tmp_path: Path) -> None:
    p = tmp_path / "PROJECTS.md"
    _write(
        p,
        _minimal_table(["| repo-a | git@github.com:org/repo-a.git | main | desc |"]),
    )
    cat = parse_projects_md(p)
    with pytest.raises(typer.Exit) as exc_info:
        cat.resolve("missing")
    assert exc_info.value.exit_code == 13  # E_REPO_NOT_FOUND


def test_resolve_owner_repo(tmp_path: Path) -> None:
    p = tmp_path / "PROJECTS.md"
    _write(
        p,
        _minimal_table(["| repo-a | git@github.com:org/repo-a.git | main | desc |"]),
    )
    cat = parse_projects_md(p)
    entry = cat.resolve_owner_repo("org/repo-a")
    assert entry.name == "repo-a"


def test_resolve_owner_repo_https_url(tmp_path: Path) -> None:
    p = tmp_path / "PROJECTS.md"
    _write(
        p,
        _minimal_table(
            ["| repo-a | https://github.com/org/repo-a.git | main | desc |"]
        ),
    )
    cat = parse_projects_md(p)
    assert cat.resolve_owner_repo("org/repo-a").name == "repo-a"


def test_has_owner_repo(tmp_path: Path) -> None:
    p = tmp_path / "PROJECTS.md"
    _write(
        p,
        _minimal_table(["| repo-a | git@github.com:org/repo-a.git | main | desc |"]),
    )
    cat = parse_projects_md(p)
    assert cat.has_owner_repo("org/repo-a") is True
    assert cat.has_owner_repo("org/missing") is False


# ----- DevKit#46: case-insensitive owner/repo matching -----------------------

@pytest.mark.parametrize(
    "supplied",
    ["APP-EMPIRE-LLC/foo", "app-empire-llc/foo", "App-Empire-LLC/FOO"],
)
def test_has_owner_repo_is_case_insensitive(tmp_path: Path, supplied: str) -> None:
    """FR-006: has_owner_repo treats owner/repo as case-insensitive."""
    p = tmp_path / "PROJECTS.md"
    _write(
        p,
        _minimal_table(
            ["| foo | git@github.com:App-Empire-LLC/foo.git | main | desc |"]
        ),
    )
    cat = parse_projects_md(p)
    assert cat.has_owner_repo(supplied) is True


@pytest.mark.parametrize(
    "supplied",
    ["APP-EMPIRE-LLC/foo", "app-empire-llc/foo", "App-Empire-LLC/FOO"],
)
def test_resolve_owner_repo_case_insensitive_preserves_stored_casing(
    tmp_path: Path, supplied: str
) -> None:
    """FR-002 + FR-006: case-insensitive lookup returns the catalog entry
    whose stored owner_repo casing is authoritative for downstream artifacts.
    """
    p = tmp_path / "PROJECTS.md"
    _write(
        p,
        _minimal_table(
            ["| foo | git@github.com:App-Empire-LLC/foo.git | main | desc |"]
        ),
    )
    cat = parse_projects_md(p)
    entry = cat.resolve_owner_repo(supplied)
    assert entry.name == "foo"
    assert entry.owner_repo == "App-Empire-LLC/foo"


def test_resolve_owner_repo_unknown_echoes_input_verbatim(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """FR-004: the not-found error path is unchanged and echoes the user's
    typed casing verbatim in the message.
    """
    p = tmp_path / "PROJECTS.md"
    _write(
        p,
        _minimal_table(
            ["| foo | git@github.com:App-Empire-LLC/foo.git | main | desc |"]
        ),
    )
    cat = parse_projects_md(p)
    with pytest.raises(typer.Exit) as exc_info:
        cat.resolve_owner_repo("NotInCatalog/whatever")
    assert exc_info.value.exit_code == 13  # E_REPO_NOT_FOUND
    captured = capsys.readouterr()
    assert "NotInCatalog/whatever" in captured.err


def test_resolve_owner_repo_ambiguous_catalog_raises_e_catalog_ambiguous(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """FR-007 + FR-008: a catalog with two rows equal under case-insensitive
    comparison must raise E_CATALOG_AMBIGUOUS on resolve, and the error
    payload must list every conflicting row's name and git_url.
    """
    p = tmp_path / "PROJECTS.md"
    _write(
        p,
        _minimal_table(
            [
                "| foo-lower | git@github.com:app-empire-llc/foo.git | main | lower |",
                "| foo-upper | git@github.com:App-Empire-LLC/foo.git | main | upper |",
            ]
        ),
    )
    cat = parse_projects_md(p)
    # has_owner_repo returns True for any ambiguous lookup (no raise).
    assert cat.has_owner_repo("app-empire-llc/foo") is True
    assert cat.has_owner_repo("APP-EMPIRE-LLC/foo") is True
    # resolve_owner_repo raises E_CATALOG_AMBIGUOUS and lists both rows.
    with pytest.raises(typer.Exit) as exc_info:
        cat.resolve_owner_repo("app-empire-llc/foo")
    assert exc_info.value.exit_code == 73  # E_CATALOG_AMBIGUOUS
    captured = capsys.readouterr()
    assert "foo-lower" in captured.err
    assert "foo-upper" in captured.err
    assert "app-empire-llc/foo" in captured.err  # input echoed verbatim
    assert "git@github.com:app-empire-llc/foo.git" in captured.err
    assert "git@github.com:App-Empire-LLC/foo.git" in captured.err


def test_lookup_tolerates_non_github_rows(tmp_path: Path) -> None:
    """A row whose git_url isn't a recognized GitHub remote returns
    owner_repo=None; the case-insensitive comparison must skip those rows
    without raising AttributeError.
    """
    p = tmp_path / "PROJECTS.md"
    _write(
        p,
        _minimal_table(
            [
                "| internal | https://gitlab.example/team/internal | main | non-github |",
                "| foo | git@github.com:App-Empire-LLC/foo.git | main | desc |",
            ]
        ),
    )
    cat = parse_projects_md(p)
    assert cat.has_owner_repo("APP-EMPIRE-LLC/foo") is True
    entry = cat.resolve_owner_repo("app-empire-llc/foo")
    assert entry.name == "foo"


# ----- error cases ------------------------------------------------------------

def test_missing_file(tmp_path: Path) -> None:
    with pytest.raises(typer.Exit) as exc_info:
        parse_projects_md(tmp_path / "nope.md")
    assert exc_info.value.exit_code == 71  # E_CATALOG_INVALID


def test_no_table_in_file(tmp_path: Path) -> None:
    p = tmp_path / "PROJECTS.md"
    _write(p, "# Projects\n\nNo table here.\n")
    with pytest.raises(typer.Exit) as exc_info:
        parse_projects_md(p)
    assert exc_info.value.exit_code == 71


def test_missing_required_column(tmp_path: Path) -> None:
    p = tmp_path / "PROJECTS.md"
    _write(
        p,
        "| name | git_url |\n|------|---------|\n"
        "| repo-a | git@github.com:org/repo-a.git |\n",
    )
    with pytest.raises(typer.Exit, match=None) as exc_info:
        parse_projects_md(p)
    assert exc_info.value.exit_code == 71


def test_duplicate_name_refused(tmp_path: Path) -> None:
    p = tmp_path / "PROJECTS.md"
    _write(
        p,
        _minimal_table(
            [
                "| repo-a | git@github.com:org/repo-a.git | main | first |",
                "| repo-a | git@github.com:org/other.git | main | dup |",
            ]
        ),
    )
    with pytest.raises(typer.Exit) as exc_info:
        parse_projects_md(p)
    assert exc_info.value.exit_code == 71


def test_empty_name_refused(tmp_path: Path) -> None:
    p = tmp_path / "PROJECTS.md"
    _write(
        p,
        _minimal_table(["|  | git@github.com:org/repo-a.git | main | desc |"]),
    )
    with pytest.raises(typer.Exit):
        parse_projects_md(p)


def test_empty_git_url_refused(tmp_path: Path) -> None:
    p = tmp_path / "PROJECTS.md"
    _write(
        p,
        _minimal_table(["| repo-a |  | main | desc |"]),
    )
    with pytest.raises(typer.Exit):
        parse_projects_md(p)


def test_empty_description_refused(tmp_path: Path) -> None:
    p = tmp_path / "PROJECTS.md"
    _write(
        p,
        _minimal_table(["| repo-a | git@github.com:org/repo-a.git | main |  |"]),
    )
    with pytest.raises(typer.Exit):
        parse_projects_md(p)


def test_no_rows_refused(tmp_path: Path) -> None:
    p = tmp_path / "PROJECTS.md"
    _write(
        p,
        "| name | git_url | description |\n|------|---------|-------------|\n",
    )
    with pytest.raises(typer.Exit):
        parse_projects_md(p)


def test_row_cell_count_mismatch(tmp_path: Path) -> None:
    p = tmp_path / "PROJECTS.md"
    _write(
        p,
        _minimal_table(["| repo-a | git@github.com:org/repo-a.git |"]),
    )
    with pytest.raises(typer.Exit):
        parse_projects_md(p)


# ----- whitespace + edge cases -----------------------------------------------

def test_whitespace_in_cells_trimmed(tmp_path: Path) -> None:
    p = tmp_path / "PROJECTS.md"
    _write(
        p,
        _minimal_table(
            ["|   repo-a   |   git@github.com:org/repo-a.git   |   main   |   desc   |"]
        ),
    )
    cat = parse_projects_md(p)
    assert cat.entries[0].name == "repo-a"
    assert cat.entries[0].description == "desc"


def test_blank_line_terminates_table(tmp_path: Path) -> None:
    p = tmp_path / "PROJECTS.md"
    _write(
        p,
        _minimal_table(["| repo-a | git@github.com:org/repo-a.git | main | first |"])
        + "\n"
        + _minimal_table(
            ["| repo-b | git@github.com:org/repo-b.git | main | second |"]
        ),
    )
    # Only the first table is consumed; second table's "name" header isn't
    # discovered after the blank-line break.
    cat = parse_projects_md(p)
    assert len(cat.entries) == 1


def test_raw_text_preserved_for_verbatim_stamping(tmp_path: Path) -> None:
    p = tmp_path / "PROJECTS.md"
    raw = _minimal_table(
        ["| repo-a | git@github.com:org/repo-a.git | main | desc |"]
    )
    _write(p, raw)
    cat = parse_projects_md(p)
    assert cat.raw_text == raw
