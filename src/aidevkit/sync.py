"""`devkit sync` — fetch and rebase every worktree in the current workspace onto its trunk.

All subprocess calls go through ``aidevkit.util.run``/``git`` — do not import
``subprocess`` directly here.

This module MUST NOT invoke ``git push``, ``git reset --hard``, ``git clean``,
``git branch -D``, ``git reflog expire``, or any ``--force*`` flag (FR-013).
"""

from __future__ import annotations

import json
import os
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Literal, Optional

import typer

from . import util
from .util import (
    E_NOT_IN_WORKSPACE,
    E_SYNC_PARTIAL,
    RunResult,
    info,
    log,
    out,
)

Outcome = Literal[
    "rebased",
    "fast-forwarded",
    "up-to-date",
    "skipped-dirty",
    "fetch-failed",
    "trunk-missing",
    "conflict",
    "rebase-error",
    "dry-run-plan",
]

_CLEAN_OUTCOMES: frozenset[Outcome] = frozenset({"rebased", "fast-forwarded", "up-to-date"})
_ERROR_OUTCOMES: frozenset[Outcome] = frozenset({"fetch-failed", "trunk-missing", "rebase-error"})

_WS_NAME_RE = re.compile(r"^.+-issue-\d+$")


@dataclass(frozen=True)
class Workspace:
    root: Path
    name: str
    default_trunk: Optional[str]


@dataclass(frozen=True)
class Worktree:
    path: Path
    repo: str
    branch: str
    trunk: str


@dataclass(frozen=True)
class WorktreeResult:
    repo: str
    path: Path
    branch: str
    trunk: str
    outcome: Outcome
    behind_count: int
    message: Optional[str] = None
    commits_replayed: Optional[int] = None


@dataclass
class SyncReport:
    workspace_root: Path
    overall_status: Literal["ok", "partial", "error", "dry-run"]
    exit_code: int
    worktrees: list[WorktreeResult] = field(default_factory=list)


# ---------------------------------------------------------------------------
# Thin wrappers over the canonical shell seam. Keeping them here lets tests
# monkeypatch a single target (``aidevkit.util.run``).


def _run(cmd: list[str], *, cwd: Optional[Path] = None) -> RunResult:
    return util.run(cmd, cwd=cwd)


def _git(*args: str, cwd: Optional[Path] = None) -> RunResult:
    return _run(["git", *args], cwd=cwd)


# ---------------------------------------------------------------------------
# Workspace discovery (R3)


def find_workspace_root(cwd: Path) -> Path:
    home_env = os.environ.get("APP_EMPIRE_WORKTREES_HOME")
    home = Path(home_env).resolve() if home_env else None

    cwd = cwd.resolve()
    candidate: Optional[Path] = cwd
    while candidate is not None:
        if _WS_NAME_RE.match(candidate.name) and _has_worktree_child(candidate):
            return candidate
        if home is not None and candidate == home:
            break
        parent = candidate.parent
        if parent == candidate:
            break
        candidate = parent

    util.die(
        f"not inside a recognized workspace (cwd={cwd}). "
        f"cd into $APP_EMPIRE_WORKTREES_HOME/<repo>-issue-<N>/ first.",
        code=E_NOT_IN_WORKSPACE,
    )
    # die() raises typer.Exit; this is unreachable.
    raise typer.Exit(code=E_NOT_IN_WORKSPACE)


def _has_worktree_child(path: Path) -> bool:
    if not path.is_dir():
        return False
    try:
        children = list(path.iterdir())
    except OSError:
        return False
    for child in children:
        if not child.is_dir():
            continue
        if (child / ".git").exists():
            return True
    return False


# ---------------------------------------------------------------------------
# Worktree enumeration


def list_worktrees(workspace: Workspace) -> list[Worktree]:
    results: list[Worktree] = []
    for child in sorted(workspace.root.iterdir(), key=lambda p: p.name):
        if not child.is_dir():
            continue
        if not (child / ".git").exists():
            continue
        branch = _current_branch(child)
        # trunk resolved lazily by the orchestrator; placeholder here.
        results.append(Worktree(path=child, repo=child.name, branch=branch, trunk="main"))
    return results


def _current_branch(worktree: Path) -> str:
    res = _git("rev-parse", "--abbrev-ref", "HEAD", cwd=worktree)
    return res.stdout.strip() if res.code == 0 else "HEAD"


# ---------------------------------------------------------------------------
# TRUNK.md parsing (R6)

_MAX_BRANCH_LEN = 255


def parse_trunk_file(path: Path) -> Optional[str]:
    if not path.exists():
        return None
    try:
        text = path.read_text(encoding="utf-8")
    except UnicodeDecodeError:
        return None
    for raw in text.splitlines():
        stripped = raw.strip()
        if not stripped:
            continue
        if stripped.startswith("#"):
            continue
        # Value must not contain internal whitespace.
        if any(ch.isspace() for ch in stripped):
            return None
        if len(stripped) > _MAX_BRANCH_LEN:
            return None
        return stripped
    return None


def resolve_trunk(worktree: Path, workspace_default: Optional[str]) -> str:
    per_worktree = parse_trunk_file(worktree / "TRUNK.md")
    if per_worktree is not None:
        return per_worktree
    if workspace_default is not None:
        return workspace_default
    return "main"


# ---------------------------------------------------------------------------
# Dirty detection (R1) and behind-count (R7)


def is_dirty(worktree: Path) -> bool:
    res = _git("diff", "--quiet", "HEAD", cwd=worktree)
    if res.code == 0:
        return False
    if res.code == 1:
        return True
    raise RuntimeError(
        f"git diff --quiet HEAD returned unexpected code {res.code} in {worktree}: "
        f"{res.stderr.strip()}"
    )


def behind_count(worktree: Path, trunk: str) -> int:
    """Commits on ``origin/<trunk>`` not reachable from ``HEAD`` in ``worktree``.

    Assumes the caller has already run ``git fetch origin``. Does not fetch.
    Coerces any git error to ``0`` — behind count is advisory, never
    load-bearing for safety decisions. DevKit#27 is the primary consumer
    (pre-push freshness check).
    """
    res = _git("rev-list", "--count", f"HEAD..origin/{trunk}", cwd=worktree)
    if res.code != 0:
        log(
            f"behind_count: git rev-list failed in {worktree} ({res.stderr.strip()}); coercing to 0"
        )
        return 0
    try:
        return int(res.stdout.strip() or "0")
    except ValueError:
        return 0


# ---------------------------------------------------------------------------
# Clean-outcome classification (R4)


def classify_clean_outcome(
    before_sha: str,
    after_sha: str,
    trunk_sha: str,
    worktree: Path,
) -> tuple[Outcome, Optional[int]]:
    if before_sha == after_sha:
        return "up-to-date", None
    replayed = _count_commits(worktree, before_sha, after_sha)
    return "rebased", replayed


def _count_commits(worktree: Path, low: str, high: str) -> int:
    res = _git("rev-list", "--count", f"{low}..{high}", cwd=worktree)
    if res.code != 0:
        return 0
    try:
        return int(res.stdout.strip() or "0")
    except ValueError:
        return 0


# ---------------------------------------------------------------------------
# Rebase-state detection (R2) — used by US3


def detect_rebase_state(worktree: Path) -> Literal["none", "merge", "apply"]:
    for kind in ("rebase-merge", "rebase-apply"):
        res = _git("rev-parse", "--git-path", kind, cwd=worktree)
        if res.code != 0:
            continue
        candidate = res.stdout.strip()
        if not candidate:
            continue
        p = Path(candidate)
        if not p.is_absolute():
            p = worktree / p
        if p.exists():
            return "merge" if kind == "rebase-merge" else "apply"
    return "none"


# ---------------------------------------------------------------------------
# Per-worktree processor


def _process_worktree(
    worktree: Worktree,
    workspace_default_trunk: Optional[str],
    *,
    dry_run: bool,
) -> WorktreeResult:
    wt = worktree.path

    # Trunk resolution — may mark this worktree trunk-missing if TRUNK.md is malformed.
    trunk_md_path = wt / "TRUNK.md"
    if trunk_md_path.exists():
        parsed = parse_trunk_file(trunk_md_path)
        if parsed is None:
            return WorktreeResult(
                repo=worktree.repo,
                path=wt,
                branch=worktree.branch,
                trunk="?",
                outcome="trunk-missing",
                behind_count=0,
                message=f"malformed TRUNK.md at {trunk_md_path}",
            )
        trunk = parsed
    else:
        trunk = workspace_default_trunk or "main"

    if dry_run:
        return WorktreeResult(
            repo=worktree.repo,
            path=wt,
            branch=worktree.branch,
            trunk=trunk,
            outcome="dry-run-plan",
            behind_count=0,
            message=f"would fetch origin then rebase {worktree.branch} onto origin/{trunk}",
        )

    if is_dirty(wt):
        return WorktreeResult(
            repo=worktree.repo,
            path=wt,
            branch=worktree.branch,
            trunk=trunk,
            outcome="skipped-dirty",
            behind_count=0,
            message="tracked-file changes present — commit or stash, then re-run.",
        )

    fetch = _git("fetch", "origin", cwd=wt)
    if fetch.code != 0:
        return WorktreeResult(
            repo=worktree.repo,
            path=wt,
            branch=worktree.branch,
            trunk=trunk,
            outcome="fetch-failed",
            behind_count=0,
            message=(fetch.stderr.strip() or fetch.stdout.strip() or "git fetch failed")[:500],
        )

    trunk_ref = _git("rev-parse", f"origin/{trunk}", cwd=wt)
    if trunk_ref.code != 0:
        return WorktreeResult(
            repo=worktree.repo,
            path=wt,
            branch=worktree.branch,
            trunk=trunk,
            outcome="trunk-missing",
            behind_count=0,
            message=f"origin/{trunk} does not exist on remote",
        )
    trunk_sha = trunk_ref.stdout.strip()

    before = _git("rev-parse", "HEAD", cwd=wt)
    before_sha = before.stdout.strip() if before.code == 0 else ""

    bc = behind_count(wt, trunk)

    # Ancestry shortcut: branch already contains every trunk commit → up-to-date.
    anc = _git("merge-base", "--is-ancestor", trunk_sha, before_sha, cwd=wt)
    if anc.code == 0:
        return WorktreeResult(
            repo=worktree.repo,
            path=wt,
            branch=worktree.branch,
            trunk=trunk,
            outcome="up-to-date",
            behind_count=bc,
        )

    # Fast-forward path: worktree's current branch is trunk itself.
    if worktree.branch == trunk:
        ff = _git("merge", "--ff-only", f"origin/{trunk}", cwd=wt)
        if ff.code == 0:
            return WorktreeResult(
                repo=worktree.repo,
                path=wt,
                branch=worktree.branch,
                trunk=trunk,
                outcome="fast-forwarded",
                behind_count=bc,
            )
        # ff-only refused → classify as rebase-error (rare; divergent history on trunk).
        return WorktreeResult(
            repo=worktree.repo,
            path=wt,
            branch=worktree.branch,
            trunk=trunk,
            outcome="rebase-error",
            behind_count=bc,
            message=(ff.stderr.strip() or "fast-forward refused")[:500],
        )

    # Rebase path.
    rebase = _git("rebase", f"origin/{trunk}", cwd=wt)
    if rebase.code == 0:
        after = _git("rev-parse", "HEAD", cwd=wt)
        after_sha = after.stdout.strip() if after.code == 0 else before_sha
        outcome, replayed = classify_clean_outcome(before_sha, after_sha, trunk_sha, wt)
        return WorktreeResult(
            repo=worktree.repo,
            path=wt,
            branch=worktree.branch,
            trunk=trunk,
            outcome=outcome,
            behind_count=bc,
            commits_replayed=replayed,
        )

    # Non-zero rebase — distinguish conflict from other error via rebase-state.
    state = detect_rebase_state(wt)
    if state in ("merge", "apply"):
        return WorktreeResult(
            repo=worktree.repo,
            path=wt,
            branch=worktree.branch,
            trunk=trunk,
            outcome="conflict",
            behind_count=bc,
            message=(
                f"rebase left {wt} in rebase-in-progress state. "
                f"Resolve conflicts and run `git rebase --continue`, "
                f"or `git rebase --abort` to back out."
            ),
        )
    return WorktreeResult(
        repo=worktree.repo,
        path=wt,
        branch=worktree.branch,
        trunk=trunk,
        outcome="rebase-error",
        behind_count=bc,
        message=(rebase.stderr.strip() or rebase.stdout.strip() or "rebase failed")[:500],
    )


# ---------------------------------------------------------------------------
# Aggregation


def _aggregate_status(
    results: list[WorktreeResult],
) -> tuple[Literal["ok", "partial", "error"], int]:
    has_error = any(r.outcome in _ERROR_OUTCOMES for r in results)
    has_partial = any(r.outcome not in _CLEAN_OUTCOMES for r in results)
    if has_error:
        return "error", E_SYNC_PARTIAL
    if has_partial:
        return "partial", E_SYNC_PARTIAL
    return "ok", 0


# ---------------------------------------------------------------------------
# Rendering


def report_to_dict(report: SyncReport) -> dict:
    return {
        "workspace_root": str(report.workspace_root),
        "overall_status": report.overall_status,
        "exit_code": report.exit_code,
        "worktrees": [_worktree_to_dict(w) for w in report.worktrees],
    }


def _worktree_to_dict(r: WorktreeResult) -> dict:
    d: dict = {
        "repo": r.repo,
        "path": str(r.path),
        "branch": r.branch,
        "trunk": r.trunk,
        "outcome": r.outcome,
        "behind_count": r.behind_count,
    }
    if r.commits_replayed is not None:
        d["commits_replayed"] = r.commits_replayed
    if r.message is not None:
        d["message"] = r.message
    return d


def _render_human(report: SyncReport) -> None:
    info(f"sync: workspace {report.workspace_root}")
    for r in report.worktrees:
        detail = _outcome_detail(r)
        info(f"sync: {r.repo:<16} {r.trunk:<12} {detail}")
        if r.outcome == "conflict" and r.message:
            for line in _format_conflict_remediation(r).splitlines():
                info(f"sync:                 {line}")
        elif r.message and r.outcome not in _CLEAN_OUTCOMES:
            info(f"sync:                 {r.message}")
    if report.overall_status == "ok":
        info("sync: all worktrees clean.")
    elif report.overall_status == "dry-run":
        info("sync: dry-run — no changes applied.")
    else:
        needing = sum(1 for r in report.worktrees if r.outcome not in _CLEAN_OUTCOMES)
        info(f"sync: {needing} worktree{'s' if needing != 1 else ''} needs attention.")


def _outcome_detail(r: WorktreeResult) -> str:
    if r.outcome == "rebased":
        count = r.commits_replayed if r.commits_replayed is not None else 0
        plural = "s" if count != 1 else ""
        return f"rebased ({count} commit{plural} replayed)"
    if r.outcome == "skipped-dirty":
        return "skipped (dirty)"
    return r.outcome


def _format_conflict_remediation(r: WorktreeResult) -> str:
    return (
        f"remediation: cd {r.path}\n"
        f"             resolve conflicts, then `git rebase --continue`\n"
        f"             or `git rebase --abort` to back out"
    )


def _render_json(report: SyncReport) -> None:
    out.print(json.dumps(report_to_dict(report), indent=2))


# ---------------------------------------------------------------------------
# Orchestrator


def cmd_sync(json_output: bool, dry_run: bool) -> int:
    cwd = Path.cwd()
    workspace_root = find_workspace_root(cwd)
    workspace_default = parse_trunk_file(workspace_root / "TRUNK.md")
    workspace = Workspace(
        root=workspace_root,
        name=workspace_root.name,
        default_trunk=workspace_default,
    )

    worktrees = list_worktrees(workspace)
    if not worktrees:
        log(f"no worktrees found under {workspace_root} — nothing to sync")
        report = SyncReport(
            workspace_root=workspace_root,
            overall_status="ok",
            exit_code=0,
            worktrees=[],
        )
        if json_output:
            _render_json(report)
        else:
            _render_human(report)
        return 0

    if not json_output and not dry_run:
        log(f"sync: workspace {workspace_root}")

    results: list[WorktreeResult] = []
    for wt in worktrees:
        if not json_output and not dry_run:
            log(f"sync: {wt.repo} …")
        result = _process_worktree(wt, workspace.default_trunk, dry_run=dry_run)
        results.append(result)

    if dry_run:
        overall = "dry-run"
        exit_code = 0
    else:
        overall, exit_code = _aggregate_status(results)

    report = SyncReport(
        workspace_root=workspace_root,
        overall_status=overall,
        exit_code=exit_code,
        worktrees=results,
    )

    if json_output:
        _render_json(report)
    else:
        _render_human(report)

    return exit_code
