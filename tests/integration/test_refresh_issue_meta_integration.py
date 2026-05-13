"""End-to-end integration tests for ``devkit refresh-issue-meta`` (DevKit#39).

Drives the real installed ``devkit`` binary via subprocess against a tempdir
workspace. ``gh`` is stubbed by PATH-prefixing a fake executable so we never
hit the live GitHub API — the stub honors a JSON-payload file written by each
test (and an "auth-fail" / "not-found" mode controlled by env vars).

This complements the in-process unit tests in
``tests/test_refresh_issue_meta.py`` by validating the actual Typer
exception→exit-code translation and the on-disk write path.
"""
from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

_REPO_ROOT = Path(__file__).resolve().parents[2]
_VALID_FIXTURE = _REPO_ROOT / "tests" / "fixtures" / "workspace_md" / "valid.md"

# These constants mirror the fixture; keep them in sync if the fixture moves.
_FIXTURE_TITLE = (
    "devkit refresh-issue-meta — re-fetch issue title into WORKSPACE.md"
)
_FIXTURE_URL = "https://github.com/App-Empire-LLC/DevKit/issues/39"


def _devkit_cmd() -> list[str]:
    """Build the argv prefix for invoking ``devkit`` in this checkout.

    Uses ``python -m aidevkit.cli`` when the entry point isn't on PATH;
    falls back to bare ``devkit`` when it is. Either way we end up
    exercising the same Typer app.
    """
    devkit = shutil.which("devkit")
    if devkit:
        return [devkit]
    return [sys.executable, "-m", "aidevkit.cli"]


@pytest.fixture
def fake_gh_dir(tmp_path: Path) -> Path:
    """Create a directory holding a fake ``gh`` script and its config file.

    The fake reads ``<dir>/gh_response.json`` for a canned issue-view payload,
    or honors mode files ``gh_auth_fail`` / ``gh_repo_not_found`` /
    ``gh_missing`` to simulate the various failure modes from the spec.
    """
    bin_dir = tmp_path / "fakebin"
    bin_dir.mkdir()
    config_dir = tmp_path / "fakegh_config"
    config_dir.mkdir()
    fake_gh = bin_dir / "gh"
    fake_gh.write_text(
        f"""#!{sys.executable}
import json, os, sys

CONFIG_DIR = {str(config_dir)!r}
args = sys.argv[1:]

if args[:2] != ["issue", "view"]:
    sys.stderr.write(f"fake gh: unexpected args {{args!r}}\\n")
    sys.exit(2)

if os.path.exists(os.path.join(CONFIG_DIR, "gh_auth_fail")):
    sys.stderr.write("error: not logged into any GitHub hosts. Run `gh auth login`\\n")
    sys.exit(1)

if os.path.exists(os.path.join(CONFIG_DIR, "gh_repo_not_found")):
    sys.stderr.write("GraphQL: Could not resolve to an Issue (issue: 99999)\\n")
    sys.exit(1)

response_path = os.path.join(CONFIG_DIR, "gh_response.json")
with open(response_path) as f:
    print(f.read(), end="")
"""
    )
    fake_gh.chmod(0o755)
    # Stash the config dir alongside the fake-bin dir for tests to write into.
    (bin_dir / ".config_dir").write_text(str(config_dir))
    return bin_dir


def _write_gh_response(fake_gh_dir: Path, *, title: str, url: str) -> None:
    config_dir = Path((fake_gh_dir / ".config_dir").read_text())
    (config_dir / "gh_response.json").write_text(
        json.dumps({"title": title, "url": url})
    )


def _set_gh_mode(fake_gh_dir: Path, mode: str) -> None:
    """``mode`` ∈ {"auth_fail", "repo_not_found"}."""
    config_dir = Path((fake_gh_dir / ".config_dir").read_text())
    (config_dir / f"gh_{mode}").write_text("")


def _stage_workspace(tmp_path: Path, fixture: Path = _VALID_FIXTURE) -> Path:
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    shutil.copy(fixture, workspace / "WORKSPACE.md")
    return workspace


def _run_devkit(
    args: list[str],
    *,
    cwd: Path,
    fake_gh_dir: Path | None = None,
    drop_gh_from_path: bool = False,
) -> subprocess.CompletedProcess[str]:
    env = os.environ.copy()
    if fake_gh_dir is not None:
        env["PATH"] = f"{fake_gh_dir}{os.pathsep}{env['PATH']}"
    if drop_gh_from_path:
        # Build a minimal PATH that excludes any directory containing `gh`.
        clean_dirs = []
        for d in env.get("PATH", "").split(os.pathsep):
            if not d:
                continue
            if (Path(d) / "gh").exists():
                continue
            clean_dirs.append(d)
        env["PATH"] = os.pathsep.join(clean_dirs)
    return subprocess.run(
        [*_devkit_cmd(), *args],
        cwd=cwd,
        capture_output=True,
        text=True,
        env=env,
    )


# ---------------------------------------------------------------------------
# T019 (Phase 4) — in-sync no-op smoke
# ---------------------------------------------------------------------------


def test_runs_silently_when_in_sync(tmp_path: Path, fake_gh_dir: Path) -> None:
    workspace = _stage_workspace(tmp_path)
    _write_gh_response(fake_gh_dir, title=_FIXTURE_TITLE, url=_FIXTURE_URL)

    before = (workspace / "WORKSPACE.md").read_bytes()
    proc = _run_devkit(["refresh-issue-meta"], cwd=workspace, fake_gh_dir=fake_gh_dir)
    after = (workspace / "WORKSPACE.md").read_bytes()

    assert proc.returncode == 0, proc.stderr
    assert proc.stdout == "", f"expected empty stdout, got: {proc.stdout!r}"
    assert after == before, "file must be byte-identical on no-op (SC-002)"


# ---------------------------------------------------------------------------
# T024 (Phase 6) — exit-code matrix
# ---------------------------------------------------------------------------


def test_exit_code_change_applied(tmp_path: Path, fake_gh_dir: Path) -> None:
    workspace = _stage_workspace(tmp_path)
    _write_gh_response(fake_gh_dir, title="NEW TITLE", url=_FIXTURE_URL)

    proc = _run_devkit(["refresh-issue-meta"], cwd=workspace, fake_gh_dir=fake_gh_dir)

    assert proc.returncode == 0, proc.stderr
    # FR-008: one diff line on stdout per changed field.
    assert "refresh-issue-meta" in proc.stdout
    assert "issue_title" in proc.stdout
    # The new title should now be in the file (sanity).
    assert "NEW TITLE" in (workspace / "WORKSPACE.md").read_text()


def test_exit_code_not_in_workspace(tmp_path: Path, fake_gh_dir: Path) -> None:
    # tmp_path itself has no WORKSPACE.md.
    proc = _run_devkit(["refresh-issue-meta"], cwd=tmp_path, fake_gh_dir=fake_gh_dir)

    assert proc.returncode == 20, (proc.stdout, proc.stderr)
    assert "WORKSPACE.md" in proc.stderr


def test_exit_code_malformed_workspace(tmp_path: Path, fake_gh_dir: Path) -> None:
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    (workspace / "WORKSPACE.md").write_text("not yaml\nno frontmatter\n")

    proc = _run_devkit(["refresh-issue-meta"], cwd=workspace, fake_gh_dir=fake_gh_dir)

    assert proc.returncode == 16, (proc.stdout, proc.stderr)
    assert "frontmatter" in proc.stderr.lower() or "delimiter" in proc.stderr.lower()


def test_exit_code_gh_auth_fail(tmp_path: Path, fake_gh_dir: Path) -> None:
    workspace = _stage_workspace(tmp_path)
    _set_gh_mode(fake_gh_dir, "auth_fail")

    proc = _run_devkit(["refresh-issue-meta"], cwd=workspace, fake_gh_dir=fake_gh_dir)

    # Auth-shaped failures map to E_DEP_MISSING (12) per the contract.
    assert proc.returncode == 12, (proc.stdout, proc.stderr)


def test_exit_code_gh_repo_not_found(tmp_path: Path, fake_gh_dir: Path) -> None:
    workspace = _stage_workspace(tmp_path)
    _set_gh_mode(fake_gh_dir, "repo_not_found")

    proc = _run_devkit(["refresh-issue-meta"], cwd=workspace, fake_gh_dir=fake_gh_dir)

    # Other gh failures map to E_REPO_NOT_FOUND (13) per the contract.
    assert proc.returncode == 13, (proc.stdout, proc.stderr)
