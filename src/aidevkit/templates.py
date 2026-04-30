"""DevKit template stamping: discover, plan, hash, apply.

Templates layer across three tiers in order of increasing specificity:
global (~/.devkit/templates/), projects-home ($PROJECTS_HOME/.devkit/templates/),
and per-repo ($PROJECTS_HOME/<repo>/.devkit/templates/, consulted only when
that repo contributes a worktree to the workspace).

Each tier may have ``templates/workspace/`` (→ workspace root) and
``templates/worktree/`` (→ worktree roots). Per-repo ``templates/worktree/``
applies only to that repo's own worktree; global+projects-home worktree
templates apply to every worktree.

Most-specific wins on collision: per-repo > projects-home > global. Within
the per-repo tier, later in affected-repos order wins. DevKit warns on
override.

Reserved-file collisions (templates/workspace/{WORKSPACE,TRUNK,PROJECTS}.md)
do NOT silently override — they are flagged in StampPlan.collisions_with_reserved
so bootstrap can refuse with E_TEMPLATE_COLLISION before any worktree is
created.

Schema reference: appire_docs/docs/workflows/devkit-workspaces.md § Templates.
"""
from __future__ import annotations

import hashlib
import shutil
from dataclasses import dataclass, field
from pathlib import Path, PurePosixPath

from .util import log

DEVKIT_DIRNAME = ".devkit"
TEMPLATES_DIRNAME = "templates"
WORKSPACE_SUBDIR = "workspace"
WORKTREE_SUBDIR = "worktree"

RESERVED_WORKSPACE_FILES = frozenset({"WORKSPACE.md", "TRUNK.md", "PROJECTS.md"})

GLOBAL_TIER_LABEL = "global"
PROJECTS_HOME_TIER_LABEL = "projects-home"


@dataclass(frozen=True)
class TemplateTier:
    """One tier's contribution to the template stamping plan."""

    label: str  # "global" | "projects-home" | f"repo:{owner}/{repo}"
    workspace_root: Path | None  # tier's templates/workspace/ (or None if absent)
    worktree_root: Path | None  # tier's templates/worktree/ (or None if absent)
    repo_owner_repo: str | None = None  # set for per-repo tiers; controls worktree scope
    repo_name: str | None = None  # set for per-repo tiers; the catalog `name` slug


@dataclass(frozen=True)
class PlannedCopy:
    source: Path
    destination: Path
    tier_label: str
    relpath: PurePosixPath  # for collision detection + SHA
    overrides: tuple[str, ...] = field(default=())  # tier_labels overridden


@dataclass(frozen=True)
class StampPlan:
    copies: tuple[PlannedCopy, ...]
    collisions_with_reserved: tuple[PlannedCopy, ...]
    overrides_log: tuple[tuple[str, str, str], ...]  # (relpath, winner_tier, loser_tier)
    template_stamp_sha: str


def _has_templates(devkit_dir: Path, subdir: str) -> Path | None:
    candidate = devkit_dir / TEMPLATES_DIRNAME / subdir
    if candidate.is_dir():
        return candidate
    return None


def discover_tiers(
    *,
    home_dir: Path,
    projects_home: Path,
    affected_repo_source_paths: list[tuple[str, str, Path]],
) -> list[TemplateTier]:
    """Discover the three tiers' template directories.

    ``affected_repo_source_paths`` is a list of
    ``(repo_name, owner_repo, source_clone_path)`` tuples in affected-repos
    order — controls which per-repo tiers are consulted and the within-tier
    collision tie-break order.
    """
    tiers: list[TemplateTier] = []

    # Global
    global_devkit = home_dir / DEVKIT_DIRNAME
    if global_devkit.is_dir():
        tiers.append(
            TemplateTier(
                label=GLOBAL_TIER_LABEL,
                workspace_root=_has_templates(global_devkit, WORKSPACE_SUBDIR),
                worktree_root=_has_templates(global_devkit, WORKTREE_SUBDIR),
            )
        )

    # Projects-home
    ph_devkit = projects_home / DEVKIT_DIRNAME
    if ph_devkit.is_dir():
        tiers.append(
            TemplateTier(
                label=PROJECTS_HOME_TIER_LABEL,
                workspace_root=_has_templates(ph_devkit, WORKSPACE_SUBDIR),
                worktree_root=_has_templates(ph_devkit, WORKTREE_SUBDIR),
            )
        )

    # Per-repo (in affected-repos order — later wins on within-tier collision)
    for repo_name, owner_repo, source_path in affected_repo_source_paths:
        repo_devkit = source_path / DEVKIT_DIRNAME
        if repo_devkit.is_dir():
            tiers.append(
                TemplateTier(
                    label=f"repo:{owner_repo}",
                    workspace_root=_has_templates(repo_devkit, WORKSPACE_SUBDIR),
                    worktree_root=_has_templates(repo_devkit, WORKTREE_SUBDIR),
                    repo_owner_repo=owner_repo,
                    repo_name=repo_name,
                )
            )

    return tiers


def _walk_tier_files(root: Path) -> list[tuple[PurePosixPath, Path]]:
    """Walk a templates/workspace/ or templates/worktree/ tree.

    Returns (relpath, abs_source_path) tuples sorted lexicographically.
    Skips directories (only files contribute).
    """
    if root is None or not root.is_dir():
        return []
    entries: list[tuple[PurePosixPath, Path]] = []
    for path in sorted(root.rglob("*")):
        if path.is_file() or path.is_symlink():
            relpath = PurePosixPath(path.relative_to(root).as_posix())
            entries.append((relpath, path))
    entries.sort(key=lambda e: e[0].as_posix())
    return entries


def plan_stamp(
    tiers: list[TemplateTier],
    *,
    affected_repo_names: list[str],
) -> StampPlan:
    """Build a StampPlan from the discovered tiers.

    ``affected_repo_names`` is the ordered list of repo `name` slugs the
    workspace mounts — used as worktree subdirectory names for
    ``templates/worktree/``.
    """
    # Build {(destination_relpath_within_workspace) -> [(tier_label, source)]}
    # tracking the tier-and-source for collision resolution.
    workspace_candidates: dict[PurePosixPath, list[tuple[str, Path]]] = {}
    worktree_candidates: dict[PurePosixPath, list[tuple[str, Path]]] = {}

    for tier in tiers:
        # workspace files — destination is <workspace>/<relpath>
        if tier.workspace_root is not None:
            for relpath, source in _walk_tier_files(tier.workspace_root):
                workspace_candidates.setdefault(relpath, []).append(
                    (tier.label, source)
                )

        # worktree files — destination scope depends on tier kind
        if tier.worktree_root is not None:
            files = _walk_tier_files(tier.worktree_root)
            if tier.repo_name is None:
                # Global or projects-home: applies to every worktree
                for repo_name in affected_repo_names:
                    for relpath, source in files:
                        scoped = PurePosixPath(repo_name) / relpath
                        worktree_candidates.setdefault(scoped, []).append(
                            (tier.label, source)
                        )
            else:
                # Per-repo: applies only to that repo's worktree
                for relpath, source in files:
                    scoped = PurePosixPath(tier.repo_name) / relpath
                    worktree_candidates.setdefault(scoped, []).append(
                        (tier.label, source)
                    )

    copies: list[PlannedCopy] = []
    overrides_log: list[tuple[str, str, str]] = []
    collisions_with_reserved: list[PlannedCopy] = []

    for source_map, prefix in (
        (workspace_candidates, ""),
        (worktree_candidates, ""),
    ):
        for relpath in sorted(source_map.keys(), key=lambda p: p.as_posix()):
            candidates = source_map[relpath]
            # Last entry wins. Tiers were appended in
            # global → projects-home → per-repo (in affected order),
            # so the last appended is the most-specific.
            winner_label, winner_source = candidates[-1]
            losers = [c[0] for c in candidates[:-1]]
            for loser_label in losers:
                overrides_log.append((relpath.as_posix(), winner_label, loser_label))

            # Note: prefix is unused but kept for symmetry; both maps already have
            # full destination relpaths (workspace map has "<file>", worktree map
            # has "<repo>/<file>").
            assert prefix == ""

            planned = PlannedCopy(
                source=winner_source,
                destination=PurePosixPath(relpath),  # workspace-relative
                tier_label=winner_label,
                relpath=relpath,
                overrides=tuple(losers),
            )

            # Reserved-file collision check (workspace tier only — reserved
            # files live at workspace root, not inside worktrees).
            if (
                source_map is workspace_candidates
                and relpath.as_posix() in RESERVED_WORKSPACE_FILES
            ):
                collisions_with_reserved.append(planned)
            else:
                copies.append(planned)

    template_stamp_sha = _compute_template_stamp_sha(copies, collisions_with_reserved)

    return StampPlan(
        copies=tuple(copies),
        collisions_with_reserved=tuple(collisions_with_reserved),
        overrides_log=tuple(overrides_log),
        template_stamp_sha=template_stamp_sha,
    )


def _compute_template_stamp_sha(
    copies: list[PlannedCopy],
    reserved_collisions: list[PlannedCopy],
) -> str:
    """Compute a deterministic SHA over all plan inputs.

    Hash format per data-model.md:
        <tier_label>\\0<posix_relpath>\\0<mode_octal>\\0<content_sha256_hex>\\n
    Records are sorted lexicographically by (tier_label, relpath) so the
    same template state produces the same SHA across machines.
    """
    records: list[bytes] = []
    for plan_item in list(copies) + list(reserved_collisions):
        try:
            mode = oct(plan_item.source.stat().st_mode & 0o777)[2:]
        except OSError:
            mode = "000"
        try:
            content = plan_item.source.read_bytes()
        except OSError:
            content = b""
        content_sha = hashlib.sha256(content).hexdigest()
        record = (
            f"{plan_item.tier_label}\0"
            f"{plan_item.relpath.as_posix()}\0"
            f"{mode}\0"
            f"{content_sha}\n"
        ).encode()
        records.append(record)
    records.sort()
    h = hashlib.sha256()
    for record in records:
        h.update(record)
    return h.hexdigest()


def log_overrides(plan: StampPlan) -> None:
    """Emit one ``[devkit] warn:`` line per resolved-by-override entry."""
    for relpath, winner, loser in plan.overrides_log:
        log(f"warn: template {relpath} from {winner} overrides {loser}")


def apply_stamp_plan(
    plan: StampPlan,
    workspace: Path,
    *,
    affected_repo_names: list[str] | None = None,
    phase: str = "all",
) -> None:
    """Copy plan items to their destinations.

    The ``phase`` parameter controls which items are copied:

    - ``"workspace"``: only workspace-root targets (no <repo>/ prefix).
      Run BEFORE ``git worktree add`` so workspace-root templates are
      in place when the workspace is first inspected.
    - ``"worktree"``: only items targeted at a worktree subdirectory.
      Run AFTER ``git worktree add`` so the worktree dir exists.
    - ``"all"``: both, in one pass. Suitable when worktrees already
      exist (e.g., idempotent re-stamping).

    The function does NOT log override warnings — call
    :func:`log_overrides` separately, once.

    Caller must check ``plan.collisions_with_reserved`` separately and
    fail before invoking this function.
    """
    repo_set = set(affected_repo_names or [])

    for copy in plan.copies:
        first_segment = copy.destination.parts[0] if copy.destination.parts else ""
        is_worktree_target = first_segment in repo_set
        if phase == "workspace" and is_worktree_target:
            continue
        if phase == "worktree" and not is_worktree_target:
            continue

        dest = workspace / copy.destination
        dest.parent.mkdir(parents=True, exist_ok=True)
        # Use copy2 to preserve mode bits.
        shutil.copy2(copy.source, dest, follow_symlinks=False)
