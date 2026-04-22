"""`devkit add-repo` — stub; real implementation lands in US2 phase."""
from __future__ import annotations

from .util import log


def cmd_add_repo(repo_name: str) -> int:
    log(f"add-repo: not yet implemented ({repo_name})")
    return 0
