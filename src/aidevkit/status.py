"""`devkit status` — stub; real implementation lands in US1 phase."""
from __future__ import annotations

from .util import log


def cmd_status(json_output: bool) -> int:
    log("status: not yet implemented")
    return 0
