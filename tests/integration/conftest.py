"""Integration test fixtures for `devkit sync`.

Builds a self-contained fake workspace with real `git init` origins and
worktrees, so tests can exercise the end-to-end command against the real
`git` binary.
"""
from __future__ import annotations

import shutil
import subprocess
from dataclasses import dataclass, field
from pathlib import Path
from typing import Iterable

import pytest


def _git(*args: str, cwd: Path) -> subprocess.CompletedProcess[str]:
    proc = subprocess.run(
        ["git", *args],
        cwd=cwd,
        capture_output=True,
        text=True,
        check=False,
    )
    if proc.returncode != 0:
        raise RuntimeError(
            f"git {' '.join(args)} failed in {cwd}: {proc.stderr.strip() or proc.stdout.strip()}"
        )
    return proc


def _init_origin(origin: Path, trunks: Iterable[str]) -> None:
    origin.mkdir(parents=True)
    _git("init", "--bare", "--initial-branch=main", cwd=origin)
    work = origin.parent / f"_seed_{origin.name}"
    work.mkdir()
    _git("init", "--initial-branch=main", cwd=work)
    _git("config", "user.email", "test@example.com", cwd=work)
    _git("config", "user.name", "Test", cwd=work)
    (work / "README.md").write_text("seed\n")
    _git("add", ".", cwd=work)
    _git("commit", "-m", "initial", cwd=work)
    _git("remote", "add", "origin", str(origin), cwd=work)
    _git("push", "origin", "main", cwd=work)
    for trunk in trunks:
        if trunk == "main":
            continue
        _git("checkout", "-b", trunk, cwd=work)
        (work / f"{trunk}.md").write_text(f"{trunk} branch\n")
        _git("add", ".", cwd=work)
        _git("commit", "-m", f"seed {trunk}", cwd=work)
        _git("push", "origin", trunk, cwd=work)
        _git("checkout", "main", cwd=work)
    shutil.rmtree(work)


@dataclass
class FakeWorkspace:
    workspace_root: Path
    worktrees: list[Path] = field(default_factory=list)
    origins: dict[str, Path] = field(default_factory=dict)

    def advance_trunk(self, repo: str, n: int = 1, trunk: str = "main") -> None:
        """Push `n` new commits onto `origin/<trunk>` for `repo`."""
        origin = self.origins[repo]
        scratch = self.workspace_root.parent / f"_advance_{repo}_{trunk}"
        if scratch.exists():
            shutil.rmtree(scratch)
        _git("clone", "--branch", trunk, str(origin), str(scratch), cwd=self.workspace_root.parent)
        _git("config", "user.email", "test@example.com", cwd=scratch)
        _git("config", "user.name", "Test", cwd=scratch)
        for i in range(n):
            (scratch / f"trunk_{trunk}_{i}.txt").write_text("x\n")
            _git("add", ".", cwd=scratch)
            _git("commit", "-m", f"trunk {trunk} advance {i}", cwd=scratch)
        _git("push", "origin", trunk, cwd=scratch)
        shutil.rmtree(scratch)

    def make_conflicting_commit(self, repo: str, trunk: str = "main") -> None:
        """Push a commit to trunk that will conflict with the worktree's issue branch.

        The companion conflict-producing commit on the issue branch must be added
        by the test (use ``commit_on_worktree`` for that).
        """
        origin = self.origins[repo]
        scratch = self.workspace_root.parent / f"_conflict_{repo}"
        if scratch.exists():
            shutil.rmtree(scratch)
        _git("clone", "--branch", trunk, str(origin), str(scratch), cwd=self.workspace_root.parent)
        _git("config", "user.email", "test@example.com", cwd=scratch)
        _git("config", "user.name", "Test", cwd=scratch)
        (scratch / "CONFLICT.txt").write_text("trunk side\n")
        _git("add", ".", cwd=scratch)
        _git("commit", "-m", "trunk side of conflict", cwd=scratch)
        _git("push", "origin", trunk, cwd=scratch)
        shutil.rmtree(scratch)

    def commit_on_worktree(self, repo: str, file: str, content: str, message: str) -> None:
        worktree = self.workspace_root / repo
        (worktree / file).write_text(content)
        _git("config", "user.email", "test@example.com", cwd=worktree)
        _git("config", "user.name", "Test", cwd=worktree)
        _git("add", ".", cwd=worktree)
        _git("commit", "-m", message, cwd=worktree)

    def write_trunk_md(self, scope: str, value: str) -> None:
        """scope ∈ {"workspace", <repo_name>}."""
        if scope == "workspace":
            (self.workspace_root / "TRUNK.md").write_text(f"{value}\n")
        else:
            (self.workspace_root / scope / "TRUNK.md").write_text(f"{value}\n")


@pytest.fixture
def fake_workspace(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> FakeWorkspace:
    """Two repos, two origins, one workspace with two worktrees on `issue-<repo>-42`."""
    origins_dir = tmp_path / "origins"
    origins_dir.mkdir()
    repo_names = ["RepoA", "RepoB"]
    origins: dict[str, Path] = {}
    for repo in repo_names:
        origin = origins_dir / f"{repo}.git"
        _init_origin(origin, trunks=["main", "develop", "master"])
        origins[repo] = origin

    worktrees_home = tmp_path / "worktrees"
    worktrees_home.mkdir()
    workspace_root = worktrees_home / "RepoA-issue-42"
    workspace_root.mkdir()
    _git("init", "--initial-branch=main", cwd=workspace_root)

    worktree_paths: list[Path] = []
    for repo in repo_names:
        clone = tmp_path / f"_clone_{repo}"
        _git("clone", str(origins[repo]), str(clone), cwd=tmp_path)
        _git("config", "user.email", "test@example.com", cwd=clone)
        _git("config", "user.name", "Test", cwd=clone)
        wt_target = workspace_root / repo
        _git(
            "worktree", "add", str(wt_target),
            "-b", f"issue-{repo}-42",
            cwd=clone,
        )
        worktree_paths.append(wt_target)

    monkeypatch.setenv("APP_EMPIRE_WORKTREES_HOME", str(worktrees_home))

    return FakeWorkspace(
        workspace_root=workspace_root,
        worktrees=worktree_paths,
        origins=origins,
    )
