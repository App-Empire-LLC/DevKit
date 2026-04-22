"""`devkit purge` — stub; real implementation lands in US3 phase."""
from __future__ import annotations

from .util import log


def cmd_purge(days: int, yes: bool) -> int:
    log("purge: not yet implemented")
    return 0
