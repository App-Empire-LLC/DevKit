"""DevKit ``refresh-issue-meta`` subcommand.

Refresh ``issue_title`` / ``issue_url`` in a per-issue workspace's
``WORKSPACE.md`` from the current state of the GitHub issue. Opt-in,
scoped, diff-on-change, no-op-on-unchanged — same shape as the rest of
the ``refresh-*`` family (DevKit#37).

Spec: ``specs/001-refresh-issue-meta/spec.md`` (DevKit#39).
"""
from __future__ import annotations

import json
import os
import re
import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import Final

import typer
import yaml

from .util import (
    E_DEP_MISSING,
    E_NOT_IN_WORKSPACE,
    E_REPO_NOT_FOUND,
    E_WORKSPACE_MISSING,
    die,
    gh,
    info,
)

WORKSPACE_FILENAME: Final = "WORKSPACE.md"
_FRONTMATTER_DELIM = "---\n"


class NotInWorkspaceError(Exception):
    """``WORKSPACE.md`` is not present in the target directory."""


class WorkspaceMalformedError(Exception):
    """``WORKSPACE.md`` exists but its frontmatter is missing/unparseable/incomplete."""


class GhMissingError(Exception):
    """The ``gh`` CLI is absent or unauthenticated."""


class IssueFetchError(Exception):
    """``gh issue view`` returned a non-zero exit or unexpected JSON."""


class ConcurrentModificationError(Exception):
    """``WORKSPACE.md`` was modified by another writer between our read and write."""


@dataclass
class RefreshResult:
    """Outcome of a single ``refresh()`` invocation.

    ``title_changed`` / ``url_changed`` indicate which fields the on-disk
    file required updating. The ``old_*`` values are what was on disk
    before the refresh; ``new_*`` are what is on disk after (== ``old_*``
    when that field did not change).
    """

    title_changed: bool
    url_changed: bool
    old_title: str
    new_title: str
    old_url: str
    new_url: str

    @property
    def any_changed(self) -> bool:
        return self.title_changed or self.url_changed


def _find_frontmatter_slice(text: str) -> tuple[str, str, str]:
    """Locate the YAML frontmatter block.

    Returns ``(prefix, frontmatter_body, suffix)`` where
    ``prefix + frontmatter_body + suffix == text`` exactly and
    ``frontmatter_body`` contains the lines between (and excluding) the
    opening ``---`` and closing ``---`` delimiters.

    Raises ``WorkspaceMalformedError`` if either delimiter is missing.
    """
    if not text.startswith(_FRONTMATTER_DELIM):
        raise WorkspaceMalformedError(
            "WORKSPACE.md is malformed: missing opening '---' frontmatter delimiter"
        )

    # Find the closing delimiter. Search starts after the first delimiter.
    after_open = len(_FRONTMATTER_DELIM)
    close_idx = text.find("\n" + _FRONTMATTER_DELIM, after_open - 1)
    if close_idx == -1:
        # Also accept an EOF-anchored closing form for the (unusual) bodyless case.
        if text.endswith("\n" + _FRONTMATTER_DELIM.rstrip()):
            close_idx = len(text) - len(_FRONTMATTER_DELIM.rstrip()) - 1
        else:
            raise WorkspaceMalformedError(
                "WORKSPACE.md is malformed: missing closing '---' frontmatter delimiter"
            )

    prefix = text[:after_open]
    frontmatter_body = text[after_open : close_idx + 1]
    suffix = text[close_idx + 1 :]
    return prefix, frontmatter_body, suffix


def _parse_workspace_md(workspace_md_text: str) -> tuple[str, int, str, str]:
    """Read the four fields this command cares about.

    Returns ``(issue_owner_repo, issue_number, issue_title, issue_url)``.
    Raises ``WorkspaceMalformedError`` with a message naming the specific
    issue if any field is missing, wrong-typed, or unparseable.
    """
    _, frontmatter_body, _ = _find_frontmatter_slice(workspace_md_text)
    try:
        data = yaml.safe_load(frontmatter_body)
    except yaml.YAMLError as exc:
        raise WorkspaceMalformedError(
            f"WORKSPACE.md frontmatter does not parse as YAML: {exc}"
        ) from exc

    if not isinstance(data, dict):
        raise WorkspaceMalformedError(
            "WORKSPACE.md frontmatter does not parse as a YAML mapping"
        )

    owner_repo = data.get("issue_owner_repo")
    if not isinstance(owner_repo, str) or not re.fullmatch(r"[^/\s]+/[^/\s]+", owner_repo):
        raise WorkspaceMalformedError(
            "WORKSPACE.md frontmatter field 'issue_owner_repo' is missing "
            "or not in 'owner/repo' form"
        )

    number_raw = data.get("issue_number")
    if isinstance(number_raw, bool) or not isinstance(number_raw, int) or number_raw <= 0:
        raise WorkspaceMalformedError(
            "WORKSPACE.md frontmatter field 'issue_number' is missing or not a positive integer"
        )

    title = data.get("issue_title")
    if not isinstance(title, str):
        raise WorkspaceMalformedError(
            "WORKSPACE.md frontmatter field 'issue_title' is missing or not a string"
        )

    url = data.get("issue_url")
    if not isinstance(url, str):
        raise WorkspaceMalformedError(
            "WORKSPACE.md frontmatter field 'issue_url' is missing or not a string"
        )

    return owner_repo, number_raw, title, url


def _fetch_issue_meta(owner_repo: str, number: int) -> tuple[str, str]:
    """Fetch the current title and canonical URL via ``gh issue view``.

    Returns ``(title, url)``. Raises ``GhMissingError`` if the ``gh`` binary
    is absent / unauthenticated, ``IssueFetchError`` for any other failure.
    """
    try:
        result = gh(
            "issue", "view", str(number),
            "--repo", owner_repo,
            "--json", "title,url",
        )
    except FileNotFoundError as exc:
        raise GhMissingError(
            "gh CLI not found on PATH — install GitHub CLI and run `gh auth login`"
        ) from exc

    if result.code != 0:
        stderr_lower = (result.stderr or "").lower()
        if (
            "not logged" in stderr_lower
            or "not authenticated" in stderr_lower
            or "authentication" in stderr_lower
            or "gh auth login" in stderr_lower
            or "ghp_" in stderr_lower
        ):
            raise GhMissingError(
                f"gh CLI is not authenticated for {owner_repo} — run `gh auth login`\n"
                f"  {result.stderr.strip()}"
            )
        raise IssueFetchError(
            f"gh issue view failed for {owner_repo}#{number} (exit {result.code})\n"
            f"  {result.stderr.strip()}"
        )

    try:
        payload = json.loads(result.stdout)
    except json.JSONDecodeError as exc:
        raise IssueFetchError(
            f"gh issue view returned unparseable JSON for {owner_repo}#{number}: {exc}"
        ) from exc

    title = payload.get("title")
    url = payload.get("url")
    if not isinstance(title, str) or not isinstance(url, str):
        raise IssueFetchError(
            f"gh issue view JSON missing expected fields for {owner_repo}#{number}: {payload!r}"
        )
    return title, url


def _encode_field_value(field: str, value: str) -> str:
    """Render a single ``key: value`` line in the canonical on-disk form.

    Uses the same ``yaml.safe_dump`` settings as bootstrap stamping (no
    flow style, no unicode passthrough) so values round-trip stably.
    The trailing newline is stripped.
    """
    encoded = yaml.safe_dump(
        {field: value},
        default_flow_style=False,
        sort_keys=False,
        allow_unicode=False,
    )
    return encoded.rstrip("\n")


def _substitute_field_line(frontmatter_body: str, field: str, new_value: str) -> str:
    """Replace the line ``{field}: ...`` inside the frontmatter body.

    Anchored to start-of-line; matches exactly the field's existing line.
    Raises ``RuntimeError`` if zero matches found (caller should have
    validated the field exists via ``_parse_workspace_md`` first).
    """
    new_line = _encode_field_value(field, new_value)
    pattern = re.compile(rf"^{re.escape(field)}:.*$", re.MULTILINE)
    updated, count = pattern.subn(new_line, frontmatter_body, count=1)
    if count == 0:
        raise RuntimeError(
            f"internal: field {field!r} not found in frontmatter body during substitution"
        )
    return updated


def _atomic_write_text(path: Path, content: str) -> None:
    """Write ``content`` to ``path`` atomically (tempfile in same dir + rename)."""
    fd, tmp_path_str = tempfile.mkstemp(
        prefix=f".{path.name}.", suffix=".tmp", dir=str(path.parent)
    )
    tmp_path = Path(tmp_path_str)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as fh:
            fh.write(content)
        os.replace(tmp_path, path)
    except Exception:
        # Best-effort cleanup; ignore failures.
        try:
            tmp_path.unlink()
        except OSError:
            pass
        raise


def refresh(workspace_root: Path) -> RefreshResult:
    """Refresh ``issue_title`` / ``issue_url`` in ``<workspace_root>/WORKSPACE.md``.

    Returns a ``RefreshResult`` describing what (if anything) changed.
    Raises ``NotInWorkspaceError``, ``WorkspaceMalformedError``,
    ``GhMissingError``, ``IssueFetchError``, or
    ``ConcurrentModificationError`` on the respective failure modes.

    Does NOT print to stdout; the Typer wrapper ``run_command`` owns
    user-facing output.
    """
    workspace_md = workspace_root / WORKSPACE_FILENAME
    if not workspace_md.is_file():
        raise NotInWorkspaceError(
            f"WORKSPACE.md not found in {workspace_root} — run from a per-issue workspace root"
        )

    initial_mtime_ns = workspace_md.stat().st_mtime_ns
    original_text = workspace_md.read_text(encoding="utf-8")
    owner_repo, number, disk_title, disk_url = _parse_workspace_md(original_text)

    fetched_title, fetched_url = _fetch_issue_meta(owner_repo, number)

    title_changed = disk_title != fetched_title
    url_changed = disk_url != fetched_url

    if not title_changed and not url_changed:
        return RefreshResult(
            title_changed=False,
            url_changed=False,
            old_title=disk_title,
            new_title=disk_title,
            old_url=disk_url,
            new_url=disk_url,
        )

    prefix, frontmatter_body, suffix = _find_frontmatter_slice(original_text)
    if title_changed:
        frontmatter_body = _substitute_field_line(
            frontmatter_body, "issue_title", fetched_title
        )
    if url_changed:
        frontmatter_body = _substitute_field_line(
            frontmatter_body, "issue_url", fetched_url
        )
    new_text = prefix + frontmatter_body + suffix

    # Concurrent-modification guard (research §R6): mtime must not have
    # advanced between our read and our write. Belt-and-suspenders for the
    # rare developer-editor-vs-CLI race.
    current_mtime_ns = workspace_md.stat().st_mtime_ns
    if current_mtime_ns != initial_mtime_ns:
        raise ConcurrentModificationError(
            "WORKSPACE.md was changed during refresh (mtime moved) — re-run"
        )

    _atomic_write_text(workspace_md, new_text)

    return RefreshResult(
        title_changed=title_changed,
        url_changed=url_changed,
        old_title=disk_title,
        new_title=fetched_title if title_changed else disk_title,
        old_url=disk_url,
        new_url=fetched_url if url_changed else disk_url,
    )


def _diff_line(field: str, old: str, new: str, *, max_cols: int = 120) -> str:
    """Format a single diff line, eliding long values to fit ``max_cols`` columns.

    Layout: ``refresh-issue-meta: {field} {old!r} → {new!r}``. After
    ``info()`` prefixes ``[devkit] ``, the total target width is
    ``max_cols``. If either repr is long enough to overflow, the value is
    middle-elided with ``…``.
    """
    prefix_overhead = len("[devkit] refresh-issue-meta: ")
    field_part = f"{field} "
    arrow = " → "
    fixed_overhead = prefix_overhead + len(field_part) + len(arrow)

    budget_for_values = max_cols - fixed_overhead
    if budget_for_values < 8:
        # Pathological narrow terminal — give up on elision; let it wrap.
        return f"refresh-issue-meta: {field} {old!r}{arrow}{new!r}"

    old_repr = repr(old)
    new_repr = repr(new)
    half = budget_for_values // 2

    def _elide(s: str, budget: int) -> str:
        if len(s) <= budget:
            return s
        # Keep the opening and closing quote, elide the middle.
        if budget < 5:
            return s[:budget]
        keep = budget - 1  # one char for the ellipsis
        head = keep // 2
        tail = keep - head
        return s[:head] + "…" + s[-tail:]

    old_disp = _elide(old_repr, half)
    new_disp = _elide(new_repr, budget_for_values - len(old_disp))
    return f"refresh-issue-meta: {field} {old_disp}{arrow}{new_disp}"


def run_command() -> None:
    """Typer-facing entry point. Translates exceptions to ``E_*`` exit codes
    and emits the FR-008 diff line(s) on stdout.
    """
    try:
        result = refresh(Path.cwd())
    except NotInWorkspaceError as exc:
        die(str(exc), code=E_NOT_IN_WORKSPACE)
    except WorkspaceMalformedError as exc:
        die(str(exc), code=E_WORKSPACE_MISSING)
    except GhMissingError as exc:
        die(str(exc), code=E_DEP_MISSING)
    except IssueFetchError as exc:
        die(str(exc), code=E_REPO_NOT_FOUND)
    except ConcurrentModificationError as exc:
        die(str(exc), code=1)
    else:
        if result.title_changed:
            info(_diff_line("issue_title", result.old_title, result.new_title))
        if result.url_changed:
            info(_diff_line("issue_url", result.old_url, result.new_url))


def cmd_refresh_issue_meta() -> None:
    """Typer command body. Thin wrapper around ``run_command()`` for parallel
    naming with the other ``cmd_*`` Typer entries in this package.
    """
    run_command()
    raise typer.Exit(code=0)
