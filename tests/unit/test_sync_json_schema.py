"""T015 [US1]: SyncReport.to_dict() conforms to shipped JSON schema."""
from __future__ import annotations

import json
from importlib.resources import files
from pathlib import Path

import jsonschema

from aidevkit import sync as _sync


def _schema():
    raw = (files("aidevkit.schemas") / "sync-output.schema.json").read_text()
    return json.loads(raw)


def test_all_clean_report_conforms():
    schema = _schema()
    report = _sync.SyncReport(
        workspace_root=Path("/fake/ws"),
        overall_status="ok",
        exit_code=0,
        worktrees=[
            _sync.WorktreeResult(
                repo="DevKit",
                path=Path("/fake/ws/DevKit"),
                branch="issue-DevKit-11",
                trunk="main",
                outcome="rebased",
                behind_count=3,
                commits_replayed=3,
            ),
            _sync.WorktreeResult(
                repo="appire_docs",
                path=Path("/fake/ws/appire_docs"),
                branch="issue-DevKit-11",
                trunk="main",
                outcome="up-to-date",
                behind_count=0,
            ),
        ],
    )
    jsonschema.validate(_sync.report_to_dict(report), schema)


def test_mixed_report_with_skipped_dirty_conforms():
    schema = _schema()
    report = _sync.SyncReport(
        workspace_root=Path("/fake/ws"),
        overall_status="partial",
        exit_code=21,
        worktrees=[
            _sync.WorktreeResult(
                repo="DevKit",
                path=Path("/fake/ws/DevKit"),
                branch="issue-DevKit-11",
                trunk="main",
                outcome="skipped-dirty",
                behind_count=0,
                message="2 modified files — commit or stash and re-run.",
            ),
        ],
    )
    jsonschema.validate(_sync.report_to_dict(report), schema)


def test_dry_run_report_conforms():
    schema = _schema()
    report = _sync.SyncReport(
        workspace_root=Path("/fake/ws"),
        overall_status="dry-run",
        exit_code=0,
        worktrees=[
            _sync.WorktreeResult(
                repo="DevKit",
                path=Path("/fake/ws/DevKit"),
                branch="issue-DevKit-11",
                trunk="main",
                outcome="dry-run-plan",
                behind_count=0,
                message="would fetch origin then rebase onto origin/main",
            ),
        ],
    )
    jsonschema.validate(_sync.report_to_dict(report), schema)
