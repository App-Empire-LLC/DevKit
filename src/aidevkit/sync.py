"""`devkit sync` — fetch and rebase every worktree in the current workspace onto its trunk.

All subprocess calls go through ``aidevkit.util.run``/``git`` — do not import
``subprocess`` directly here.

This module MUST NOT invoke ``git push``, ``git reset --hard``, ``git clean``,
``git branch -D``, ``git reflog expire``, or any ``--force*`` flag (FR-013).
"""
from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Literal, Optional

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


def cmd_sync(json_output: bool, dry_run: bool) -> int:
    raise NotImplementedError
