"""Shared PR-merge helpers.

`archive` uses ``check_prs_merged`` as a precondition check; `status` uses
``prs_for_branch`` to render per-repo PR lists and derive the `archivable`
flag. Extracting these keeps the PR-state signal consistent across the two
commands (FR-STAT-004b).
"""
from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Literal

from .util import gh


@dataclass
class PR:
    number: int
    state: Literal["open", "merged", "closed"]
    url: str


def check_prs_merged(
    repos: list[tuple[str, Path]],
    branch: str,
) -> list[str]:
    """Return list of blocker descriptions (empty list == all merged).

    A "blocker" is any PR on `branch` in any repo with state != 'MERGED'.
    """
    blockers: list[str] = []
    for owner_repo, _path in repos:
        res = gh(
            "pr", "list",
            "--repo", owner_repo,
            "--head", branch,
            "--state", "all",
            "--json", "number,state,url",
        )
        if res.code != 0:
            blockers.append(
                f"{owner_repo} — failed to query PRs: "
                f"{res.stderr.strip() or res.stdout.strip()}"
            )
            continue
        try:
            prs = json.loads(res.stdout or "[]")
        except json.JSONDecodeError:
            blockers.append(f"{owner_repo} — unparseable PR list")
            continue
        for pr in prs:
            if pr.get("state") != "MERGED":
                blockers.append(
                    f"{owner_repo}#{pr.get('number')} ({pr.get('state')}) — "
                    f"{pr.get('url')}"
                )
    return blockers


def prs_for_branch(
    repos: list[tuple[str, Path]],
    branch: str,
) -> dict[str, list[PR]]:
    """Return per-repo PR lists keyed by owner/repo slug.

    On query failure or parse failure for a given repo, the value is an empty
    list (caller decides how to surface the degraded signal — `status`
    degrades the whole workspace via `issue.state = "unknown"` when
    GitHub-reachability is suspect).
    """
    result: dict[str, list[PR]] = {}
    for owner_repo, _path in repos:
        res = gh(
            "pr", "list",
            "--repo", owner_repo,
            "--head", branch,
            "--state", "all",
            "--json", "number,state,url",
        )
        if res.code != 0:
            result[owner_repo] = []
            continue
        try:
            raw = json.loads(res.stdout or "[]")
        except json.JSONDecodeError:
            result[owner_repo] = []
            continue
        prs: list[PR] = []
        for pr in raw:
            gh_state = (pr.get("state") or "").upper()
            if gh_state == "MERGED":
                state: Literal["open", "merged", "closed"] = "merged"
            elif gh_state == "OPEN":
                state = "open"
            else:
                state = "closed"
            prs.append(
                PR(
                    number=int(pr.get("number") or 0),
                    state=state,
                    url=str(pr.get("url") or ""),
                )
            )
        result[owner_repo] = prs
    return result
