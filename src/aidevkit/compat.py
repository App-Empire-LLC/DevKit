"""Reader-command helper: resolve workspaces_home from .devkit/ config.

Used by ``status``, ``sync``, ``archive``, ``preflight``, ``purge``, and
``add_repo`` after DevKit#37 replaced ``$APP_EMPIRE_WORKTREES_HOME`` /
``$APP_EMPIRE_PROJECTS`` env-var reads with config-driven resolution.

The functions here also tolerate pre-#37 workspaces (workspaces created
before this issue shipped). Those workspaces don't have ``WORKSPACE.md``
or ``TRUNK.md`` at their root; reader commands should fall back to
filesystem-based inference (read branch from git, read issue ref from
directory name).
"""
from __future__ import annotations

from pathlib import Path

from . import config as _config


def get_workspaces_home() -> Path:
    """Resolve the workspaces-home directory via .devkit/config.yaml.

    Replaces ``Path(os.environ["APP_EMPIRE_WORKTREES_HOME"])`` reads
    in pre-#37 reader commands.
    """
    projects_home = _config.resolve_projects_home()
    cfg = _config.load_merged_config(projects_home)
    return cfg.workspaces_home


def get_projects_and_workspaces_homes() -> tuple[Path, Path]:
    """Return ``(projects_home, workspaces_home)`` — used by ``add_repo``."""
    projects_home = _config.resolve_projects_home()
    cfg = _config.load_merged_config(projects_home)
    return projects_home, cfg.workspaces_home
