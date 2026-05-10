"""DevKit `.devkit/` configuration: resolution + schema + merge.

The two-tier configuration model (global + projects-home; per-repo has no
config.yaml) is documented in
``appire_docs/docs/workflows/devkit-workspaces.md``. This module implements
projects-home resolution and the merged-config schema for DevKit#37.
"""
from __future__ import annotations

import os
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import yaml

from .util import E_CONFIG_INVALID, E_DEP_MISSING, die

CONFIG_FILENAME = "config.yaml"
DEVKIT_DIRNAME = ".devkit"
SCHEMA_VERSION = 1

_GLOBAL_CONFIG_PATH = Path.home() / DEVKIT_DIRNAME / CONFIG_FILENAME

_OWNER_REPO_RE = re.compile(r"^[^/\s]+/[^/\s]+$")
_ORG_RE = re.compile(r"^[^/\s]+$")


@dataclass(frozen=True)
class Config:
    """Merged DevKit configuration consumed by bootstrap and friends.

    All paths are absolute. ``always_include_repos`` is a tuple for hashability
    on this frozen dataclass.
    """

    version: int
    org: str
    workspaces_home: Path
    always_include_repos: tuple[str, ...] = field(default=())
    projects_home: Path = field(default=Path("/"))
    source_global_path: Path | None = field(default=None)
    source_projects_home_path: Path = field(default=Path("/"))

    def __post_init__(self) -> None:
        if self.version != SCHEMA_VERSION:
            _config_error(
                "version",
                self._effective_source_for("version"),
                f"unknown schema version: {self.version!r}",
                f"set 'version: {SCHEMA_VERSION}' (the current schema)",
            )

        if not isinstance(self.org, str) or not _ORG_RE.match(self.org):
            _config_error(
                "org",
                self._effective_source_for("org"),
                f"value must be a GitHub org/user name (no slashes/whitespace), got {self.org!r}",
                "set 'org' to your default GitHub owner — e.g. 'org: App-Empire-LLC'",
            )

        if not isinstance(self.workspaces_home, Path) or not self.workspaces_home.is_dir():
            _config_error(
                "workspaces_home",
                self._effective_source_for("workspaces_home"),
                f"path does not exist on disk: {self.workspaces_home}",
                f"mkdir -p {self.workspaces_home}, or point the field at an existing dir",
            )

        for i, entry in enumerate(self.always_include_repos):
            if not isinstance(entry, str) or not _OWNER_REPO_RE.match(entry):
                _config_error(
                    f"always_include_repos[{i}]",
                    self._effective_source_for("always_include_repos"),
                    f"entry must be 'owner/repo' (got {entry!r})",
                    "use fully qualified 'owner/repo' — bare names not expanded via 'org' here",
                )

    def _effective_source_for(self, field_name: str) -> Path:
        # projects-home wins on overlap; only `projects_home` itself comes
        # from the global tier.
        if field_name == "projects_home":
            return self.source_global_path or self.source_projects_home_path
        return self.source_projects_home_path


def _config_error(field_name: str, source: Path, problem: str, fix: str) -> None:
    die(
        f".devkit/config.yaml is invalid.\n"
        f"  File: {source}\n"
        f"  Field: {field_name}\n"
        f"  Problem: {problem}\n"
        f"  Fix: {fix}",
        code=E_CONFIG_INVALID,
    )


def resolve_projects_home() -> Path:
    """Resolve the projects-home directory, first hit wins.

    1. ``$PROJECTS_HOME`` env var, if it points at a directory containing
       ``.devkit/config.yaml``.
    2. ``projects_home`` field in ``~/.devkit/config.yaml``, same check.
    3. Failure (``E_DEP_MISSING``).
    """
    env_value = os.environ.get("PROJECTS_HOME")
    env_status = "unset"
    if env_value:
        env_path = Path(env_value)
        if (env_path / DEVKIT_DIRNAME / CONFIG_FILENAME).is_file():
            return env_path.resolve()
        env_status = f"set to {env_value!r} but no {DEVKIT_DIRNAME}/{CONFIG_FILENAME} found there"

    global_status = "unset"
    if _GLOBAL_CONFIG_PATH.is_file():
        try:
            with _GLOBAL_CONFIG_PATH.open() as f:
                global_data = yaml.safe_load(f) or {}
        except yaml.YAMLError as exc:
            _config_error(
                "(file)",
                _GLOBAL_CONFIG_PATH,
                f"YAML parse error: {exc}",
                "fix the YAML syntax in ~/.devkit/config.yaml",
            )
            global_data = {}  # unreachable, satisfies type checker
        if "projects_home" in global_data:
            ph_value = global_data["projects_home"]
            if isinstance(ph_value, str):
                ph_path = Path(ph_value)
                if (ph_path / DEVKIT_DIRNAME / CONFIG_FILENAME).is_file():
                    return ph_path.resolve()
                global_status = (
                    f"~/.devkit/config.yaml#projects_home={ph_value!r} but no "
                    f"{DEVKIT_DIRNAME}/{CONFIG_FILENAME} found there"
                )
            else:
                global_status = (
                    "~/.devkit/config.yaml#projects_home is not a string "
                    f"({type(ph_value).__name__})"
                )

    die(
        f"cannot locate projects-home.\n"
        f"  Searched:\n"
        f"    - $PROJECTS_HOME ({env_status})\n"
        f"    - ~/.devkit/config.yaml#projects_home ({global_status})\n"
        f"  Fix: either `export PROJECTS_HOME=/path/to/your/projects`, or add\n"
        f"       `projects_home: /path/to/your/projects` to ~/.devkit/config.yaml.",
        code=E_DEP_MISSING,
    )
    raise AssertionError("die() should have exited")  # pragma: no cover


def _load_yaml(path: Path) -> dict[str, Any]:
    try:
        with path.open() as f:
            data = yaml.safe_load(f) or {}
    except yaml.YAMLError as exc:
        _config_error(
            "(file)",
            path,
            f"YAML parse error: {exc}",
            f"fix the YAML syntax in {path}",
        )
        return {}  # unreachable
    if not isinstance(data, dict):
        _config_error(
            "(file)",
            path,
            f"top-level value must be a mapping (got {type(data).__name__})",
            "the file must look like 'version: 1\\norg: ...\\n' — a YAML mapping at the top level",
        )
    return data


_ALLOWED_GLOBAL_FIELDS = {
    "version", "org", "workspaces_home", "always_include_repos", "projects_home",
    "review_issue",
}
_ALLOWED_PROJECTS_HOME_FIELDS = {
    "version", "org", "workspaces_home", "always_include_repos",
    "review_issue",
}

_REVIEWER_ID_RE = re.compile(r"^[a-z][a-z0-9-]{0,30}$")


@dataclass(frozen=True)
class ReviewIssueConfig:
    """Optional `review_issue` block from `.devkit/config.yaml`.

    Two fields per spec/research R5 (creep K3/K4 cut the rest):
    - reviewer_id: identity for run-marker grouping (default "claude")
    - project_board_required: whether absence of a project board is blocker (default True)
    """

    reviewer_id: str = "claude"
    project_board_required: bool = True


def _validate_review_issue_block(raw: Any, source: Path) -> ReviewIssueConfig:
    """Parse and validate the review_issue config block. Returns defaults if raw is None."""
    if raw is None:
        return ReviewIssueConfig()
    if not isinstance(raw, dict):
        _config_error(
            "review_issue",
            source,
            f"value must be a mapping (got {type(raw).__name__})",
            "use YAML mapping syntax, e.g.\n    review_issue:\n      reviewer_id: claude",
        )
    allowed = {"reviewer_id", "gate"}
    for key in raw:
        if key not in allowed:
            _config_error(
                f"review_issue.{key}",
                source,
                f"unknown field: {key!r}",
                f"remove the field. Allowed: {sorted(allowed)} "
                "(see research.md R5 / creep.md K3/K4)",
            )
    reviewer_id = raw.get("reviewer_id", "claude")
    if not isinstance(reviewer_id, str) or not _REVIEWER_ID_RE.match(reviewer_id):
        _config_error(
            "review_issue.reviewer_id",
            source,
            f"value must match {_REVIEWER_ID_RE.pattern} (got {reviewer_id!r})",
            "use lowercase letters, digits, and hyphens only — e.g. 'claude' or 'gpt'",
        )
    gate = raw.get("gate", {})
    if not isinstance(gate, dict):
        _config_error(
            "review_issue.gate",
            source,
            f"value must be a mapping (got {type(gate).__name__})",
            "use YAML mapping syntax, e.g.\n    review_issue:\n"
            "      gate:\n        project_board_required: true",
        )
    gate_allowed = {"project_board_required"}
    for key in gate:
        if key not in gate_allowed:
            _config_error(
                f"review_issue.gate.{key}",
                source,
                f"unknown field: {key!r}",
                f"remove the field. Allowed: {sorted(gate_allowed)}",
            )
    project_board_required = gate.get("project_board_required", True)
    if not isinstance(project_board_required, bool):
        _config_error(
            "review_issue.gate.project_board_required",
            source,
            f"value must be a boolean (got {type(project_board_required).__name__})",
            "use 'true' or 'false'",
        )
    return ReviewIssueConfig(
        reviewer_id=reviewer_id,
        project_board_required=project_board_required,
    )


def load_review_issue_config(projects_home: Path) -> ReviewIssueConfig:
    """Load the optional `review_issue` block from the projects-home config.

    Reads only the projects-home tier (matches `load_merged_config`'s primary
    source). Returns defaults if the block is absent. Raises `typer.Exit(70)`
    via `_config_error` on schema failure.
    """
    projects_home_config = projects_home / DEVKIT_DIRNAME / CONFIG_FILENAME
    if not projects_home_config.is_file():
        return ReviewIssueConfig()
    data = _load_yaml(projects_home_config)
    return _validate_review_issue_block(data.get("review_issue"), projects_home_config)


def _check_unknown_fields(data: dict[str, Any], allowed: set[str], source: Path) -> None:
    for key in data:
        if key not in allowed:
            _config_error(
                key,
                source,
                f"unknown field: {key!r}",
                f"remove the field. Allowed at this tier: {sorted(allowed)}",
            )


def load_merged_config(projects_home: Path) -> Config:
    """Read both tiers, merge them (projects-home wins), validate, return."""
    projects_home_config = projects_home / DEVKIT_DIRNAME / CONFIG_FILENAME
    if not projects_home_config.is_file():
        die(
            f"projects-home config not found: {projects_home_config}\n"
            f"  Fix: create {projects_home_config} with at minimum:\n"
            f"       version: 1\n"
            f"       org: <your-org>\n"
            f"       workspaces_home: <path>",
            code=E_DEP_MISSING,
        )

    global_data: dict[str, Any] = {}
    global_path: Path | None = None
    if _GLOBAL_CONFIG_PATH.is_file():
        global_path = _GLOBAL_CONFIG_PATH
        global_data = _load_yaml(_GLOBAL_CONFIG_PATH)
        _check_unknown_fields(global_data, _ALLOWED_GLOBAL_FIELDS, _GLOBAL_CONFIG_PATH)

    projects_home_data = _load_yaml(projects_home_config)
    _check_unknown_fields(projects_home_data, _ALLOWED_PROJECTS_HOME_FIELDS, projects_home_config)

    # Field-by-field merge, projects-home wins. List-typed fields follow
    # replace semantics (FR-004 clarification): projects-home value replaces
    # global outright; absent/empty falls back to global.
    merged: dict[str, Any] = dict(global_data)
    for key, value in projects_home_data.items():
        if key == "always_include_repos" and not value:
            # empty list → fall back to global
            continue
        merged[key] = value

    # `projects_home` is global-only by schema; if it leaked into projects-home
    # config it's already caught by _check_unknown_fields above. Drop it from
    # the merged dict — the resolved Path is passed in separately.
    merged.pop("projects_home", None)

    # Construct Config (validation runs in __post_init__)
    if "version" not in merged:
        _config_error(
            "version",
            projects_home_config,
            "required — must be set at the global tier, projects-home tier, or both",
            "add 'version: 1' to .devkit/config.yaml",
        )
    if "org" not in merged:
        _config_error(
            "org",
            projects_home_config,
            "required — must be set at the global tier, projects-home tier, or both",
            "add 'org: <your-github-org>' to .devkit/config.yaml",
        )
    if "workspaces_home" not in merged:
        _config_error(
            "workspaces_home",
            projects_home_config,
            "required — must be set at the global tier, projects-home tier, or both",
            "add 'workspaces_home: /abs/path' to .devkit/config.yaml",
        )

    workspaces_home_raw = merged["workspaces_home"]
    if not isinstance(workspaces_home_raw, str):
        _config_error(
            "workspaces_home",
            projects_home_config,
            f"value must be a string (got {type(workspaces_home_raw).__name__})",
            "use a quoted string path, e.g. 'workspaces_home: /Users/you/.app_empire_worktrees'",
        )

    always_include_raw = merged.get("always_include_repos", [])
    if not isinstance(always_include_raw, list):
        _config_error(
            "always_include_repos",
            projects_home_config,
            f"value must be a list (got {type(always_include_raw).__name__})",
            "use YAML list syntax, e.g.\n    always_include_repos:\n      - owner/repo",
        )

    return Config(
        version=merged["version"],
        org=merged["org"],
        workspaces_home=Path(workspaces_home_raw),
        always_include_repos=tuple(always_include_raw),
        projects_home=projects_home,
        source_global_path=global_path,
        source_projects_home_path=projects_home_config,
    )
