"""Unit tests for `aidevkit.templates` — discovery, planning, SHA, apply."""
from __future__ import annotations

import os
from pathlib import Path

from aidevkit.templates import (
    GLOBAL_TIER_LABEL,
    PROJECTS_HOME_TIER_LABEL,
    TemplateTier,
    apply_stamp_plan,
    discover_tiers,
    plan_stamp,
)


def _seed_tier(devkit_root: Path, files: dict[str, str]) -> None:
    """Drop files into a `.devkit/templates/` tree.

    Keys are `workspace/<rel>` or `worktree/<rel>` paths; values are file content.
    """
    for relpath, content in files.items():
        full = devkit_root / "templates" / relpath
        full.parent.mkdir(parents=True, exist_ok=True)
        full.write_text(content)


# ----- discover_tiers ---------------------------------------------------------

def test_discover_no_tiers_present(tmp_path: Path) -> None:
    home = tmp_path / "home"
    home.mkdir()
    ph = tmp_path / "projects"
    ph.mkdir()
    tiers = discover_tiers(
        home_dir=home,
        projects_home=ph,
        affected_repo_source_paths=[],
    )
    assert tiers == []


def test_discover_global_only(tmp_path: Path) -> None:
    home = tmp_path / "home"
    _seed_tier(home / ".devkit", {"workspace/X.md": "hi"})
    ph = tmp_path / "projects"
    ph.mkdir()
    tiers = discover_tiers(
        home_dir=home,
        projects_home=ph,
        affected_repo_source_paths=[],
    )
    assert len(tiers) == 1
    assert tiers[0].label == GLOBAL_TIER_LABEL
    assert tiers[0].workspace_root is not None
    assert tiers[0].worktree_root is None


def test_discover_three_tiers(tmp_path: Path) -> None:
    home = tmp_path / "home"
    _seed_tier(home / ".devkit", {"workspace/A.md": "global"})
    ph = tmp_path / "projects"
    _seed_tier(ph / ".devkit", {"workspace/B.md": "ph"})
    repo_a = ph / "repo-a"
    _seed_tier(repo_a / ".devkit", {"worktree/C.md": "repo"})

    tiers = discover_tiers(
        home_dir=home,
        projects_home=ph,
        affected_repo_source_paths=[("repo-a", "org/repo-a", repo_a)],
    )
    assert [t.label for t in tiers] == [
        GLOBAL_TIER_LABEL,
        PROJECTS_HOME_TIER_LABEL,
        "repo:org/repo-a",
    ]
    assert tiers[2].repo_name == "repo-a"
    assert tiers[2].repo_owner_repo == "org/repo-a"


def test_discover_per_repo_only_when_devkit_present(tmp_path: Path) -> None:
    """Per-repo tier is consulted only if that repo has a `.devkit/`."""
    home = tmp_path / "home"
    home.mkdir()
    ph = tmp_path / "projects"
    ph.mkdir()
    repo_a = ph / "repo-a"
    repo_a.mkdir()
    repo_b = ph / "repo-b"
    _seed_tier(repo_b / ".devkit", {"workspace/B.md": "from-b"})
    tiers = discover_tiers(
        home_dir=home,
        projects_home=ph,
        affected_repo_source_paths=[
            ("repo-a", "org/repo-a", repo_a),
            ("repo-b", "org/repo-b", repo_b),
        ],
    )
    assert len(tiers) == 1
    assert tiers[0].repo_name == "repo-b"


# ----- plan_stamp -------------------------------------------------------------

def _tier(label: str, ws_root: Path | None = None, wt_root: Path | None = None,
          repo_name: str | None = None, owner_repo: str | None = None) -> TemplateTier:
    return TemplateTier(
        label=label,
        workspace_root=ws_root,
        worktree_root=wt_root,
        repo_owner_repo=owner_repo,
        repo_name=repo_name,
    )


def _seed(root: Path, files: dict[str, str]) -> Path:
    root.mkdir(parents=True, exist_ok=True)
    for rel, content in files.items():
        full = root / rel
        full.parent.mkdir(parents=True, exist_ok=True)
        full.write_text(content)
    return root


def test_plan_no_collisions(tmp_path: Path) -> None:
    ws_global = _seed(tmp_path / "g_ws", {"X.md": "from-global"})
    plan = plan_stamp(
        [_tier(GLOBAL_TIER_LABEL, ws_root=ws_global)],
        affected_repo_names=["repo-a"],
    )
    assert len(plan.copies) == 1
    assert plan.copies[0].destination.as_posix() == "X.md"
    assert plan.copies[0].tier_label == GLOBAL_TIER_LABEL
    assert plan.overrides_log == ()


def test_plan_per_repo_wins(tmp_path: Path) -> None:
    ws_g = _seed(tmp_path / "g", {"CLAUDE.md": "global"})
    ws_ph = _seed(tmp_path / "ph", {"CLAUDE.md": "ph"})
    ws_r = _seed(tmp_path / "r", {"CLAUDE.md": "repo"})
    plan = plan_stamp(
        [
            _tier(GLOBAL_TIER_LABEL, ws_root=ws_g),
            _tier(PROJECTS_HOME_TIER_LABEL, ws_root=ws_ph),
            _tier("repo:org/a", ws_root=ws_r, repo_name="a", owner_repo="org/a"),
        ],
        affected_repo_names=["a"],
    )
    assert len(plan.copies) == 1
    winner = plan.copies[0]
    assert winner.tier_label == "repo:org/a"
    overridden_labels = {entry[2] for entry in plan.overrides_log}
    assert overridden_labels == {GLOBAL_TIER_LABEL, PROJECTS_HOME_TIER_LABEL}


def test_plan_two_per_repo_collide_later_wins(tmp_path: Path) -> None:
    ws_a = _seed(tmp_path / "a", {"X.md": "from-a"})
    ws_b = _seed(tmp_path / "b", {"X.md": "from-b"})
    plan = plan_stamp(
        [
            _tier("repo:org/a", ws_root=ws_a, repo_name="a", owner_repo="org/a"),
            _tier("repo:org/b", ws_root=ws_b, repo_name="b", owner_repo="org/b"),
        ],
        affected_repo_names=["a", "b"],
    )
    assert plan.copies[0].tier_label == "repo:org/b"
    overridden = [e for e in plan.overrides_log if e[0] == "X.md"]
    assert len(overridden) == 1
    assert overridden[0][2] == "repo:org/a"


def test_plan_worktree_global_applied_to_every_worktree(tmp_path: Path) -> None:
    wt_g = _seed(tmp_path / "wt_g", {"editorconfig": "[*]\n"})
    plan = plan_stamp(
        [_tier(GLOBAL_TIER_LABEL, wt_root=wt_g)],
        affected_repo_names=["a", "b"],
    )
    dests = sorted(p.destination.as_posix() for p in plan.copies)
    assert dests == ["a/editorconfig", "b/editorconfig"]


def test_plan_worktree_per_repo_scoped_to_one(tmp_path: Path) -> None:
    wt_a = _seed(tmp_path / "wt_a", {"CONVENTIONS.md": "for a"})
    plan = plan_stamp(
        [_tier("repo:org/a", wt_root=wt_a, repo_name="a", owner_repo="org/a")],
        affected_repo_names=["a", "b"],
    )
    dests = [p.destination.as_posix() for p in plan.copies]
    assert dests == ["a/CONVENTIONS.md"]


def test_plan_reserved_collision_flagged(tmp_path: Path) -> None:
    ws_g = _seed(tmp_path / "g", {"WORKSPACE.md": "evil override"})
    plan = plan_stamp(
        [_tier(GLOBAL_TIER_LABEL, ws_root=ws_g)],
        affected_repo_names=["a"],
    )
    assert len(plan.collisions_with_reserved) == 1
    assert plan.collisions_with_reserved[0].relpath.as_posix() == "WORKSPACE.md"
    assert plan.copies == ()


def test_plan_reserved_collision_for_each_reserved_file(tmp_path: Path) -> None:
    ws_g = _seed(
        tmp_path / "g",
        {
            "WORKSPACE.md": "x",
            "TRUNK.md": "x",
            "PROJECTS.md": "x",
            "Other.md": "ok",
        },
    )
    plan = plan_stamp(
        [_tier(GLOBAL_TIER_LABEL, ws_root=ws_g)],
        affected_repo_names=["a"],
    )
    reserved_paths = sorted(c.relpath.as_posix() for c in plan.collisions_with_reserved)
    assert reserved_paths == ["PROJECTS.md", "TRUNK.md", "WORKSPACE.md"]
    assert [c.destination.as_posix() for c in plan.copies] == ["Other.md"]


def test_plan_nested_paths_preserved(tmp_path: Path) -> None:
    ws_g = _seed(tmp_path / "g", {"sub/dir/file.txt": "deep"})
    plan = plan_stamp(
        [_tier(GLOBAL_TIER_LABEL, ws_root=ws_g)],
        affected_repo_names=["a"],
    )
    assert plan.copies[0].destination.as_posix() == "sub/dir/file.txt"


# ----- SHA determinism --------------------------------------------------------

def test_sha_deterministic_on_same_inputs(tmp_path: Path) -> None:
    ws_g = _seed(tmp_path / "g", {"X.md": "hello"})
    plan_a = plan_stamp(
        [_tier(GLOBAL_TIER_LABEL, ws_root=ws_g)],
        affected_repo_names=["a"],
    )
    plan_b = plan_stamp(
        [_tier(GLOBAL_TIER_LABEL, ws_root=ws_g)],
        affected_repo_names=["a"],
    )
    assert plan_a.template_stamp_sha == plan_b.template_stamp_sha
    assert len(plan_a.template_stamp_sha) == 64


def test_sha_changes_on_content_change(tmp_path: Path) -> None:
    ws_g = _seed(tmp_path / "g", {"X.md": "v1"})
    sha_v1 = plan_stamp(
        [_tier(GLOBAL_TIER_LABEL, ws_root=ws_g)],
        affected_repo_names=["a"],
    ).template_stamp_sha
    (ws_g / "X.md").write_text("v2")
    sha_v2 = plan_stamp(
        [_tier(GLOBAL_TIER_LABEL, ws_root=ws_g)],
        affected_repo_names=["a"],
    ).template_stamp_sha
    assert sha_v1 != sha_v2


def test_sha_changes_on_mode_change(tmp_path: Path) -> None:
    ws_g = _seed(tmp_path / "g", {"runme.sh": "#!/bin/sh\n"})
    target = ws_g / "runme.sh"
    os.chmod(target, 0o644)
    sha_644 = plan_stamp(
        [_tier(GLOBAL_TIER_LABEL, ws_root=ws_g)],
        affected_repo_names=["a"],
    ).template_stamp_sha
    os.chmod(target, 0o755)
    sha_755 = plan_stamp(
        [_tier(GLOBAL_TIER_LABEL, ws_root=ws_g)],
        affected_repo_names=["a"],
    ).template_stamp_sha
    assert sha_644 != sha_755


def test_sha_changes_when_a_tier_is_added(tmp_path: Path) -> None:
    ws_g = _seed(tmp_path / "g", {"X.md": "x"})
    sha_one = plan_stamp(
        [_tier(GLOBAL_TIER_LABEL, ws_root=ws_g)],
        affected_repo_names=["a"],
    ).template_stamp_sha
    ws_ph = _seed(tmp_path / "ph", {"Y.md": "y"})
    sha_two = plan_stamp(
        [
            _tier(GLOBAL_TIER_LABEL, ws_root=ws_g),
            _tier(PROJECTS_HOME_TIER_LABEL, ws_root=ws_ph),
        ],
        affected_repo_names=["a"],
    ).template_stamp_sha
    assert sha_one != sha_two


def test_sha_includes_reserved_collisions(tmp_path: Path) -> None:
    """Reserved-file collisions still affect the SHA; otherwise an evil
    template could change SHA-equivalent state by hiding behind a reserved
    name."""
    ws_a = _seed(tmp_path / "a", {"WORKSPACE.md": "evil"})
    ws_b = _seed(tmp_path / "b", {"WORKSPACE.md": "more evil"})
    sha_a = plan_stamp(
        [_tier(GLOBAL_TIER_LABEL, ws_root=ws_a)],
        affected_repo_names=["a"],
    ).template_stamp_sha
    sha_b = plan_stamp(
        [_tier(GLOBAL_TIER_LABEL, ws_root=ws_b)],
        affected_repo_names=["a"],
    ).template_stamp_sha
    assert sha_a != sha_b


# ----- apply_stamp_plan -------------------------------------------------------

def test_apply_creates_workspace_files(tmp_path: Path) -> None:
    ws_g = _seed(tmp_path / "g", {"hello.md": "world"})
    plan = plan_stamp(
        [_tier(GLOBAL_TIER_LABEL, ws_root=ws_g)],
        affected_repo_names=["a"],
    )
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    apply_stamp_plan(plan, workspace)
    assert (workspace / "hello.md").read_text() == "world"


def test_apply_creates_worktree_files(tmp_path: Path) -> None:
    wt_g = _seed(tmp_path / "wt_g", {"editorconfig": "x"})
    plan = plan_stamp(
        [_tier(GLOBAL_TIER_LABEL, wt_root=wt_g)],
        affected_repo_names=["repo-a"],
    )
    workspace = tmp_path / "workspace"
    (workspace / "repo-a").mkdir(parents=True)
    apply_stamp_plan(plan, workspace)
    assert (workspace / "repo-a" / "editorconfig").read_text() == "x"


def test_apply_creates_nested_dirs(tmp_path: Path) -> None:
    ws_g = _seed(tmp_path / "g", {"sub/deep/file.txt": "ok"})
    plan = plan_stamp(
        [_tier(GLOBAL_TIER_LABEL, ws_root=ws_g)],
        affected_repo_names=["a"],
    )
    workspace = tmp_path / "ws"
    workspace.mkdir()
    apply_stamp_plan(plan, workspace)
    assert (workspace / "sub" / "deep" / "file.txt").read_text() == "ok"


def test_apply_preserves_executable_bit(tmp_path: Path) -> None:
    ws_g = _seed(tmp_path / "g", {"runme.sh": "#!/bin/sh\n"})
    os.chmod(ws_g / "runme.sh", 0o755)
    plan = plan_stamp(
        [_tier(GLOBAL_TIER_LABEL, ws_root=ws_g)],
        affected_repo_names=["a"],
    )
    workspace = tmp_path / "ws"
    workspace.mkdir()
    apply_stamp_plan(plan, workspace)
    mode = (workspace / "runme.sh").stat().st_mode & 0o755
    assert mode == 0o755


def test_apply_emits_override_warning(
    tmp_path: Path, capsys: __import__("pytest").CaptureFixture
) -> None:
    ws_g = _seed(tmp_path / "g", {"X.md": "global"})
    ws_ph = _seed(tmp_path / "ph", {"X.md": "ph"})
    plan = plan_stamp(
        [
            _tier(GLOBAL_TIER_LABEL, ws_root=ws_g),
            _tier(PROJECTS_HOME_TIER_LABEL, ws_root=ws_ph),
        ],
        affected_repo_names=["a"],
    )
    workspace = tmp_path / "ws"
    workspace.mkdir()
    apply_stamp_plan(plan, workspace)
    captured = capsys.readouterr()
    assert "warn" in captured.err.lower()
    assert "X.md" in captured.err
    assert GLOBAL_TIER_LABEL in captured.err
    assert PROJECTS_HOME_TIER_LABEL in captured.err
