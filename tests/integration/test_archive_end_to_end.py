"""End-to-end integration test for `devkit archive`.

Exercises the real filesystem + real `git worktree` machinery. `gh` is stubbed
out by PATH-prefixing a fake executable so we don't hit the live GitHub API;
the parts we verify are the filesystem and git-registration post-conditions.
"""
from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

import pytest

from aidevkit import archive as archive_mod
from aidevkit.util import RunResult


def _real_run(cmd: list[str], *, check: bool = False, cwd: Path | None = None) -> RunResult:
    """Re-implementation of util.run against the real subprocess module.

    The hermeticity guard patches util.run at the module level for unit tests;
    for integration tests we install this pass-through so the real git binary
    is driven against the tempdir-backed fixture.
    """
    proc = subprocess.run(
        cmd,
        cwd=cwd,
        capture_output=True,
        text=True,
        check=check,
    )
    return RunResult(code=proc.returncode, stdout=proc.stdout, stderr=proc.stderr)


@pytest.fixture
def fake_gh_on_path(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """Install a fake `gh` script on PATH that canned-responds per argv."""
    bin_dir = tmp_path / "fakebin"
    bin_dir.mkdir()
    fake_gh = bin_dir / "gh"
    fake_gh.write_text(
        f"""#!{sys.executable}
import json, sys
args = sys.argv[1:]
if args[:2] == ["pr", "list"]:
    print(json.dumps([{{"number": 99, "state": "MERGED", "url": "https://x/99"}}]))
    sys.exit(0)
if args[:2] == ["issue", "comment"]:
    print("https://fake.example/comments/1")
    sys.exit(0)
if args[:2] == ["issue", "view"]:
    print(json.dumps({{"state": "OPEN"}}))
    sys.exit(0)
if args[:2] == ["issue", "close"]:
    sys.exit(0)
sys.stderr.write(f"fake gh: unexpected args {{args}}\\n")
sys.exit(1)
"""
    )
    fake_gh.chmod(0o755)
    monkeypatch.setenv("PATH", f"{bin_dir}{os.pathsep}{os.environ.get('PATH', '')}")
    return bin_dir


def test_archive_happy_path_real_git(
    tmp_path: Path,
    fake_gh_on_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Full archive: bare-init origin, worktree, archive → verify mv + prune."""
    # Set up a real upstream repo with a remote pointing at "github.com/owner/Upstream"
    origin = tmp_path / "origin.git"
    subprocess.run(
        ["git", "init", "--bare", "--initial-branch=main", str(origin)],
        check=True, capture_output=True,
    )
    seed = tmp_path / "_seed"
    seed.mkdir()
    for cmd in (
        ["git", "init", "--initial-branch=main"],
        ["git", "config", "user.email", "t@t.t"],
        ["git", "config", "user.name", "T"],
    ):
        subprocess.run(cmd, cwd=seed, check=True, capture_output=True)
    (seed / "README.md").write_text("seed\n")
    subprocess.run(["git", "add", "."], cwd=seed, check=True, capture_output=True)
    subprocess.run(
        ["git", "commit", "-m", "initial"],
        cwd=seed, check=True, capture_output=True,
    )
    subprocess.run(
        ["git", "remote", "add", "origin", str(origin)],
        cwd=seed, check=True, capture_output=True,
    )
    subprocess.run(
        ["git", "push", "origin", "main"],
        cwd=seed, check=True, capture_output=True,
    )

    upstream = tmp_path / "Upstream"
    subprocess.run(
        ["git", "clone", str(origin), str(upstream)],
        check=True, capture_output=True,
    )
    # Rewrite origin URL so _parse_owner_repo_from_url sees github.com/.../Upstream
    subprocess.run(
        ["git", "remote", "set-url", "origin", "https://github.com/App-Empire-LLC/Upstream.git"],
        cwd=upstream, check=True, capture_output=True,
    )

    # Build workspace
    workspaces_home = tmp_path / "worktrees"
    workspaces_home.mkdir()
    workspace = workspaces_home / "Upstream-issue-77"
    workspace.mkdir()

    # Add a worktree from upstream into workspace on branch issue-Upstream-77
    wt_path = workspace / "Upstream"
    subprocess.run(
        ["git", "worktree", "add", "-b", "issue-Upstream-77", str(wt_path)],
        cwd=upstream, check=True, capture_output=True,
    )

    # Drop a spec.md into the workspace
    specs_dir = workspace / "specs" / "77-test"
    specs_dir.mkdir(parents=True)
    (specs_dir / "spec.md").write_text("# Integration Spec\n\nHello from integration test.\n")

    # DevKit#37: seed .devkit/ for the new workspaces_home resolver.
    ph = tmp_path / "projects_home"
    ph.mkdir()
    devkit_dir = ph / ".devkit"
    devkit_dir.mkdir()
    (devkit_dir / "config.yaml").write_text(
        f"version: 1\norg: App-Empire-LLC\nworkspaces_home: {workspaces_home}\n"
    )
    (devkit_dir / "PROJECTS.md").write_text(
        "# Projects\n\n| name | git_url | description |\n|------|---------|-------------|\n"
        "| Upstream | git@github.com:App-Empire-LLC/Upstream.git | x |\n"
    )
    fake_home = tmp_path / "_fake_home"
    fake_home.mkdir()
    monkeypatch.setenv("PROJECTS_HOME", str(ph))
    monkeypatch.setattr("pathlib.Path.home", classmethod(lambda cls: fake_home))
    monkeypatch.setattr(
        "aidevkit.config._GLOBAL_CONFIG_PATH",
        fake_home / ".devkit" / "config.yaml",
    )
    monkeypatch.setattr("aidevkit.util.run", _real_run)

    # Precondition: worktree registered in upstream
    list_res = subprocess.run(
        ["git", "worktree", "list"],
        cwd=upstream, check=True, capture_output=True, text=True,
    )
    assert str(wt_path) in list_res.stdout

    # Run archive
    exit_code = archive_mod.cmd_archive("App-Empire-LLC/Upstream#77", force=False, dry_run=False)
    assert exit_code == 0

    # Post-conditions
    assert not workspace.exists(), "workspace should have been moved"
    archived = workspaces_home / "_archived" / "Upstream-issue-77"
    assert archived.is_dir(), "archived dir should exist"
    assert (archived / "specs" / "77-test" / "spec.md").is_file()
    assert (archived / "Upstream").is_dir()
    marker = archived / ".devkit-archived"
    assert marker.is_file(), "archive must drop a .devkit-archived marker"
    import datetime as _dt
    _dt.datetime.fromisoformat(marker.read_text().strip())

    # Prune should have cleaned the stale registration
    list_after = subprocess.run(
        ["git", "worktree", "list"],
        cwd=upstream, check=True, capture_output=True, text=True,
    )
    assert str(wt_path) not in list_after.stdout, (
        f"stale worktree registration should have been pruned; got:\n{list_after.stdout}"
    )
