"""`devkit purge` — delete old archived workspaces after a retention window.

Scans `$APP_EMPIRE_WORKTREES_HOME/_archived/`, reads the `.devkit-archived`
marker inside each directory, and deletes dirs older than the threshold
(default 30 days). Dry-run by default; requires `--yes` to mutate the
filesystem. Dirs without a valid marker are skipped with a warning — never
deleted (FR-PURGE-004a).
"""
from __future__ import annotations

import datetime
import shutil
from dataclasses import dataclass
from pathlib import Path
from typing import Optional

from .util import (
    info,
    log,
)

_MARKER_NAME = ".devkit-archived"
_FUTURE_SKEW_SECONDS = 60


@dataclass
class ArchivedEntry:
    path: Path
    archived_at: Optional[datetime.datetime]
    marker_error: Optional[str]
    age_days: Optional[int]


def _parse_marker(marker: Path, now: datetime.datetime) -> ArchivedEntry:
    if not marker.is_file():
        return ArchivedEntry(
            path=marker.parent,
            archived_at=None,
            marker_error="marker file missing",
            age_days=None,
        )
    try:
        text = marker.read_text().strip()
    except OSError as exc:
        return ArchivedEntry(
            path=marker.parent,
            archived_at=None,
            marker_error=f"could not read marker: {exc}",
            age_days=None,
        )
    if not text:
        return ArchivedEntry(
            path=marker.parent,
            archived_at=None,
            marker_error="marker file empty",
            age_days=None,
        )
    first_line = text.splitlines()[0].strip()
    raw = first_line
    if raw.endswith("Z"):
        raw = raw[:-1] + "+00:00"
    try:
        parsed = datetime.datetime.fromisoformat(raw)
    except ValueError as exc:
        return ArchivedEntry(
            path=marker.parent,
            archived_at=None,
            marker_error=f"unparseable timestamp '{first_line}': {exc}",
            age_days=None,
        )
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=datetime.UTC)
    if parsed > now + datetime.timedelta(seconds=_FUTURE_SKEW_SECONDS):
        return ArchivedEntry(
            path=marker.parent,
            archived_at=parsed,
            marker_error=f"marker timestamp is in the future: {first_line}",
            age_days=None,
        )
    age = now - parsed
    return ArchivedEntry(
        path=marker.parent,
        archived_at=parsed,
        marker_error=None,
        age_days=age.days,
    )


def _enumerate_archived(home: Path) -> list[ArchivedEntry]:
    archived_root = home / "_archived"
    if not archived_root.is_dir():
        return []
    now = datetime.datetime.now(datetime.UTC)
    entries: list[ArchivedEntry] = []
    for child in sorted(archived_root.iterdir()):
        if not child.is_dir():
            continue
        entries.append(_parse_marker(child / _MARKER_NAME, now))
    return entries


def _eligible(entry: ArchivedEntry, threshold_days: int) -> bool:
    if entry.marker_error is not None:
        return False
    if entry.age_days is None:
        return False
    return entry.age_days >= threshold_days


def cmd_purge(days: int, yes: bool) -> int:
    from . import compat
    home = compat.get_workspaces_home()

    archived_root = home / "_archived"
    if not archived_root.is_dir():
        info("nothing to purge — no _archived/ directory")
        return 0

    entries = _enumerate_archived(home)
    if not entries:
        info("nothing to purge — _archived/ is empty")
        return 0

    mode = "DELETE" if yes else "DRY RUN"
    info(f"purge [{mode}] — threshold: {days} days; scanning {archived_root}")

    purged: list[Path] = []
    skipped_marker: list[tuple[Path, str]] = []
    too_new: list[tuple[Path, int]] = []
    deletion_failures: list[tuple[Path, str]] = []

    for entry in entries:
        if entry.marker_error is not None:
            skipped_marker.append((entry.path, entry.marker_error))
            log(
                f"SKIP {entry.path.name}: {entry.marker_error} "
                f"(refusing to delete without a valid marker)"
            )
            continue
        if not _eligible(entry, days):
            too_new.append((entry.path, entry.age_days or 0))
            info(
                f"keep {entry.path.name}: age {entry.age_days} days "
                f"< threshold {days}"
            )
            continue
        if not yes:
            info(f"would purge {entry.path.name} (age {entry.age_days} days)")
            continue
        try:
            shutil.rmtree(entry.path)
            purged.append(entry.path)
            info(f"purged {entry.path.name} (age {entry.age_days} days)")
        except OSError as exc:
            deletion_failures.append((entry.path, str(exc)))
            log(f"FAILED to delete {entry.path}: {exc}")

    info("")
    if yes:
        info(f"Purged {len(purged)} director{'y' if len(purged) == 1 else 'ies'}.")
    else:
        would = [e for e in entries if _eligible(e, days)]
        info(
            f"Dry run: {len(would)} director{'y' if len(would) == 1 else 'ies'} "
            f"would be purged. Re-run with --yes to delete."
        )
    if skipped_marker:
        info(f"Skipped (missing/invalid marker): {len(skipped_marker)}")
    if too_new:
        info(f"Within retention window: {len(too_new)}")
    if deletion_failures:
        return 1
    return 0
