"""`devkit check-update` — non-destructive "is there an update?" oracle.

Uses `uv tool upgrade --dry-run aidevkit` as the source of truth: whatever
`devkit update` would actually install is by definition the "latest" we
report. No hardcoded index URL; no parsing of `~/.local/share/uv/tools/`
metadata. If the dry-run can't resolve an index (e.g., source-checkout
install), exit 27 per FR-SELF-011.
"""
from __future__ import annotations

import json
import re
from dataclasses import dataclass
from typing import Optional

from . import util
from ._install import detect_install_info
from .util import (
    E_CHECK_UPDATE_INDEX_UNAVAILABLE,
    die,
    info,
    out,
)

_WOULD_INSTALL_RE = re.compile(
    r"(?:Would install|install|Updated)\s+aidevkit\s*(?:==|=|@)?\s*v?([0-9][^\s]*)",
    re.IGNORECASE,
)
_UP_TO_DATE_RE = re.compile(r"up\s*to\s*date|no\s+updates?\s+available", re.IGNORECASE)


@dataclass
class UpdateCheckResult:
    installed: str
    latest: Optional[str]
    update_available: bool
    unresolvable_reason: Optional[str]


def _parse_dry_run_output(text: str) -> tuple[Optional[str], bool]:
    """Return (latest_version, is_up_to_date). (None, False) means unresolvable."""
    if _UP_TO_DATE_RE.search(text):
        return None, True
    m = _WOULD_INSTALL_RE.search(text)
    if m:
        return m.group(1), False
    return None, False


def cmd_check_update(json_output: bool) -> int:
    install = detect_install_info()
    installed = install.installed_version or "unknown"

    dry = util.run(["uv", "tool", "upgrade", "--dry-run", "aidevkit"])
    if dry.code != 0 and not dry.stdout and not dry.stderr:
        die(
            "uv tool upgrade --dry-run aidevkit returned no output — "
            "cannot determine latest version. Is `uv` installed and is "
            "aidevkit reachable via your configured index?",
            code=E_CHECK_UPDATE_INDEX_UNAVAILABLE,
        )

    combined = (dry.stdout or "") + "\n" + (dry.stderr or "")
    latest, up_to_date = _parse_dry_run_output(combined)

    if up_to_date:
        result = UpdateCheckResult(
            installed=installed,
            latest=installed if installed != "unknown" else None,
            update_available=False,
            unresolvable_reason=None,
        )
    elif latest is not None:
        update_available = installed != "unknown" and latest != installed
        result = UpdateCheckResult(
            installed=installed,
            latest=latest,
            update_available=update_available,
            unresolvable_reason=None,
        )
    else:
        reason = (
            "could not parse `uv tool upgrade --dry-run aidevkit` output; "
            "the configured index may be unavailable or aidevkit may be "
            "installed from a local source checkout."
        )
        if json_output:
            payload = {
                "installed": installed,
                "latest": None,
                "update_available": False,
                "unresolvable_reason": reason,
            }
            out.print(json.dumps(payload, indent=2))
        die(reason, code=E_CHECK_UPDATE_INDEX_UNAVAILABLE)
        return E_CHECK_UPDATE_INDEX_UNAVAILABLE  # unreachable

    if json_output:
        out.print(
            json.dumps(
                {
                    "installed": result.installed,
                    "latest": result.latest,
                    "update_available": result.update_available,
                    "unresolvable_reason": result.unresolvable_reason,
                },
                indent=2,
            )
        )
    else:
        if result.update_available:
            info(
                f"update available: {result.installed} → {result.latest}. "
                f"Run `devkit update`."
            )
        else:
            info(f"aidevkit is up to date ({result.installed}).")
    return 0
