"""DevKit `PROJECTS.md` catalog: parser + lookup helpers.

Catalog schema is documented in
``appire_docs/docs/workflows/devkit-workspaces.md`` § PROJECTS.md.

This module implements the subset required for DevKit#37: columns
``name``, ``git_url``, ``default_branch`` (optional, default ``main``),
``description``. Unknown columns are ignored (forward-compat with the
``path`` column that lands in a follow-up issue).
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path

from .util import E_CATALOG_AMBIGUOUS, E_CATALOG_INVALID, E_REPO_NOT_FOUND, die

REQUIRED_COLUMNS = ("name", "git_url", "description")
OPTIONAL_COLUMNS = ("default_branch",)
DEFAULT_BRANCH = "main"

_TABLE_ROW_RE = re.compile(r"^\s*\|.*\|\s*$")
_SEPARATOR_RE = re.compile(r"^\s*\|(\s*[-:]+\s*\|)+\s*$")
# git URLs we recognize for owner/repo extraction. We don't validate URLs
# strictly — the catalog author owns correctness; we just need owner/repo
# pairs for issue-body matching.
_GIT_URL_RE = re.compile(
    r"(?:git@github\.com:|https?://github\.com/)([^/\s]+)/([^/\s]+?)(?:\.git)?/?$"
)


@dataclass(frozen=True)
class CatalogEntry:
    name: str
    git_url: str
    default_branch: str
    description: str

    @property
    def owner_repo(self) -> str | None:
        """Extract ``owner/repo`` from ``git_url``, or None if not GitHub."""
        m = _GIT_URL_RE.search(self.git_url)
        if not m:
            return None
        return f"{m.group(1)}/{m.group(2)}"


@dataclass(frozen=True)
class Catalog:
    entries: tuple[CatalogEntry, ...]
    source_path: Path
    raw_text: str = field(repr=False)

    def resolve(self, name: str) -> CatalogEntry:
        for entry in self.entries:
            if entry.name == name:
                return entry
        die(
            f"repo {name!r} not found in {self.source_path}.\n"
            f"  Fix: add a row for {name!r} to the catalog, or correct the spelling.",
            code=E_REPO_NOT_FOUND,
        )
        raise AssertionError("unreachable")  # pragma: no cover

    def resolve_owner_repo(self, owner_repo: str) -> CatalogEntry:
        # DevKit#46: GitHub treats owner/repo as case-insensitive, so the
        # matcher does too. The catalog's stored casing remains authoritative
        # for branch names, worktree paths, and generated metadata — only the
        # comparison is case-folded.
        needle = owner_repo.lower()
        matches = [
            e for e in self.entries
            if e.owner_repo is not None and e.owner_repo.lower() == needle
        ]
        if len(matches) == 1:
            return matches[0]
        if not matches:
            die(
                f"repo {owner_repo!r} not found in {self.source_path}.\n"
                f"  Fix: add a row whose git_url resolves to {owner_repo!r}, "
                f"or correct the reference.",
                code=E_REPO_NOT_FOUND,
            )
            raise AssertionError("unreachable")  # pragma: no cover
        # len(matches) >= 2 — catalog-authoring bug; refuse to pick a winner.
        rows = "\n".join(
            f"    - {e.name} (git_url: {e.git_url})" for e in matches
        )
        die(
            f"catalog has ambiguous entries for {owner_repo!r} in "
            f"{self.source_path}.\n"
            f"  Conflicting rows:\n{rows}\n"
            f"  Fix: remove or rename the duplicate row(s) so only one entry "
            f"resolves to {owner_repo!r} under case-insensitive comparison.",
            code=E_CATALOG_AMBIGUOUS,
        )
        raise AssertionError("unreachable")  # pragma: no cover

    def has_owner_repo(self, owner_repo: str) -> bool:
        needle = owner_repo.lower()
        return any(
            e.owner_repo is not None and e.owner_repo.lower() == needle
            for e in self.entries
        )


def _split_row(line: str) -> list[str]:
    # Drop leading/trailing pipes, split on pipes, trim cells.
    inner = line.strip()
    if inner.startswith("|"):
        inner = inner[1:]
    if inner.endswith("|"):
        inner = inner[:-1]
    return [cell.strip() for cell in inner.split("|")]


def _catalog_error(source: Path, problem: str, fix: str) -> None:
    die(
        f"{source} catalog is invalid.\n"
        f"  Problem: {problem}\n"
        f"  Fix: {fix}",
        code=E_CATALOG_INVALID,
    )


def parse_projects_md(path: Path) -> Catalog:
    """Parse a PROJECTS.md file. Returns a frozen Catalog.

    Locates the first markdown table containing the ``name`` header, then
    parses each subsequent row until a blank line or non-table line.
    """
    if not path.is_file():
        _catalog_error(
            path,
            "file does not exist",
            f"create {path} with at least one row — see "
            "appire_docs/docs/workflows/devkit-workspaces.md § PROJECTS.md",
        )

    text = path.read_text()
    lines = text.splitlines()

    header_idx = -1
    headers: list[str] = []
    for i, line in enumerate(lines):
        if not _TABLE_ROW_RE.match(line):
            continue
        cells = _split_row(line)
        if "name" in cells and "git_url" in cells:
            header_idx = i
            headers = cells
            break

    if header_idx == -1:
        _catalog_error(
            path,
            "no markdown table with 'name' and 'git_url' columns found",
            "add a markdown table — see "
            "appire_docs/docs/workflows/devkit-workspaces.md § PROJECTS.md",
        )

    # Validate required columns present
    missing = [c for c in REQUIRED_COLUMNS if c not in headers]
    if missing:
        _catalog_error(
            path,
            f"missing required column(s): {missing}",
            f"the table header must include {list(REQUIRED_COLUMNS)}",
        )

    # Skip the separator row if present
    cursor = header_idx + 1
    if cursor < len(lines) and _SEPARATOR_RE.match(lines[cursor]):
        cursor += 1

    entries: list[CatalogEntry] = []
    seen_names: set[str] = set()
    while cursor < len(lines):
        line = lines[cursor]
        cursor += 1
        if not line.strip():
            break
        if not _TABLE_ROW_RE.match(line):
            break
        cells = _split_row(line)
        if len(cells) != len(headers):
            _catalog_error(
                path,
                f"row {cursor} has {len(cells)} cells; header has {len(headers)}",
                "make sure every row has the same number of pipe-separated cells",
            )
        row = dict(zip(headers, cells))
        name = row["name"]
        if not name:
            _catalog_error(
                path,
                f"row {cursor} has empty 'name'",
                "every row must have a non-empty name",
            )
        if name in seen_names:
            _catalog_error(
                path,
                f"duplicate name {name!r}",
                f"every row's 'name' must be unique within {path}",
            )
        seen_names.add(name)

        git_url = row["git_url"]
        if not git_url:
            _catalog_error(
                path,
                f"row {name!r} has empty 'git_url'",
                "every row must have a non-empty git_url",
            )

        description = row["description"]
        if not description:
            _catalog_error(
                path,
                f"row {name!r} has empty 'description'",
                "every row must have a non-empty description",
            )

        default_branch = row.get("default_branch") or DEFAULT_BRANCH

        entries.append(
            CatalogEntry(
                name=name,
                git_url=git_url,
                default_branch=default_branch,
                description=description,
            )
        )

    if not entries:
        _catalog_error(
            path,
            "catalog table has no rows",
            "add at least one row for a repo you want to mount as a worktree",
        )

    return Catalog(entries=tuple(entries), source_path=path, raw_text=text)
