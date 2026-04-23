"""`devkit uninstall` — remove DevKit: unlink slash commands, then `uv tool uninstall`.

Never touches user data (active workspaces, `_archived/`, `.devkit/` dirs).
Detects DevKit-installed slash commands by resolving each `~/.claude/commands/*.md`
symlink and filtering by target containing `/aidevkit/commands/`. Non-`uv-tool`
installs exit with a clear guidance message rather than running a `uv` command
that would fail.
"""
from __future__ import annotations

from pathlib import Path

from . import util
from ._install import detect_install_info
from .util import (
    E_INSTALL_NOT_UV_TOOL,
    die,
    info,
    log,
)

_MARKER_PATH_FRAGMENT = "/aidevkit/commands/"


def _cmd_dir() -> Path:
    return Path.home() / ".claude" / "commands"


def _devkit_symlinks(cmd_dir: Path) -> list[Path]:
    """Return `~/.claude/commands/*.md` entries whose resolved target is inside
    an `aidevkit/commands/` directory (i.e., installed by `devkit setup`).
    """
    if not cmd_dir.is_dir():
        return []
    found: list[Path] = []
    for entry in sorted(cmd_dir.iterdir()):
        if not entry.is_symlink():
            continue
        if not entry.name.endswith(".md"):
            continue
        try:
            target = entry.resolve()
        except (OSError, RuntimeError):
            continue
        if _MARKER_PATH_FRAGMENT in str(target):
            found.append(entry)
    return found


def cmd_uninstall() -> int:
    info_ = detect_install_info()
    if not info_.manageable:
        die(
            f"install method is '{info_.method}', which devkit cannot manage. "
            f"Uninstall manually: for pip use `pip uninstall aidevkit`; for a "
            f"source checkout just delete the repo and remove the devkit "
            f"symlinks under ~/.claude/commands/.",
            code=E_INSTALL_NOT_UV_TOOL,
        )

    cmd_dir = _cmd_dir()
    links = _devkit_symlinks(cmd_dir)
    removed = 0
    for link in links:
        try:
            link.unlink()
            removed += 1
        except OSError as exc:
            log(f"WARN: could not unlink {link}: {exc}")

    result = util.run(["uv", "tool", "uninstall", "aidevkit"])
    if result.code != 0:
        # `uv tool uninstall` of an already-gone package is the idempotent path
        # (FR-SELF "nothing to do"). Treat non-zero exit as a soft signal and
        # surface the stderr but still return 0 if the message looks like
        # already-absent. Otherwise propagate.
        stderr = (result.stderr or result.stdout or "").lower()
        if "not installed" in stderr or "no such tool" in stderr:
            info("aidevkit was already uninstalled.")
            info(f"Removed {removed} DevKit slash command symlink(s) from {cmd_dir}.")
            return 0
        log(result.stderr.strip() or result.stdout.strip())
        return result.code

    info(
        f"Uninstalled aidevkit {info_.installed_version or ''}"
        f" and removed {removed} slash command symlink(s) from {cmd_dir}."
    )
    info("User data under $APP_EMPIRE_WORKTREES_HOME was not touched.")
    return 0
