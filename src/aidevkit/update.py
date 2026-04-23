"""`devkit update` — `uv tool upgrade aidevkit`, then run `devkit doctor`.

No rollback on doctor failure (FR-SELF-005 / R-12). The upgrade succeeded;
doctor's findings are surfaced verbatim and the command exits with doctor's
exit code so the failure is loud.
"""
from __future__ import annotations

from . import doctor as doctor_mod
from . import util
from ._install import detect_install_info
from .util import (
    E_INSTALL_NOT_UV_TOOL,
    die,
    info,
    log,
)


def cmd_update() -> int:
    before = detect_install_info()
    if not before.manageable:
        die(
            f"install method is '{before.method}', which devkit cannot manage. "
            f"Upgrade manually: for pip use `pip install --upgrade aidevkit`; "
            f"for a source checkout pull + reinstall from the repo.",
            code=E_INSTALL_NOT_UV_TOOL,
        )

    info(f"Current version: aidevkit {before.installed_version or 'unknown'}")
    upgrade = util.run(["uv", "tool", "upgrade", "aidevkit"])
    if upgrade.code != 0:
        log(
            "uv tool upgrade failed: "
            + (upgrade.stderr.strip() or upgrade.stdout.strip() or "unknown error")
        )
        return upgrade.code
    if upgrade.stdout:
        info(upgrade.stdout.strip())

    after = detect_install_info()
    before_v = before.installed_version or "unknown"
    after_v = after.installed_version or "unknown"
    if before_v != after_v:
        info(f"[devkit] aidevkit {before_v} → {after_v}")
    else:
        info(f"[devkit] aidevkit already at {after_v}")

    info("Running devkit doctor…")
    return doctor_mod.cmd_doctor()
