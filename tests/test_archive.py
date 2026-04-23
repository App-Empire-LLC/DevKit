"""Tests for the archive subcommand — resolution, PR checks, spec discovery, mv + prune."""
from __future__ import annotations

import datetime
import json
from pathlib import Path

import pytest
from typer.testing import CliRunner

from aidevkit import archive as archive_mod
from aidevkit.cli import app
from aidevkit.util import (
    E_ARCHIVE_COLLISION,
    E_PRS_NOT_MERGED,
    E_USAGE,
    E_WORKSPACE_MISSING,
    RunResult,
)


@pytest.fixture
def runner(monkeypatch: pytest.MonkeyPatch) -> CliRunner:
    monkeypatch.setenv("NO_COLOR", "1")
    return CliRunner()


def _which_git_gh(name: str) -> str | None:
    return "/bin/" + name if name in {"git", "gh"} else None


def _make_workspace(
    tmp_path: Path,
    repo: str,
    num: int,
    upstream_repos: list[tuple[str, str]] | None = None,
    spec_content: str | None = "# Test Spec\n\nHello.\n",
) -> tuple[Path, list[Path]]:
    """Create a mock per-issue workspace dir with optional upstream worktrees + spec.

    Returns (workspace, upstream_roots). Each upstream_root has a fake `.git/`
    dir + a `.git/worktrees/<name>/` dir pointed to by the workspace subdir's
    `.git` file.
    """
    worktrees_home = tmp_path / "worktrees"
    worktrees_home.mkdir(exist_ok=True)
    workspace = worktrees_home / f"{repo}-issue-{num}"
    workspace.mkdir()

    upstream_roots: list[Path] = []
    for upstream_dirname, _owner_repo in (upstream_repos or []):
        upstream_root = tmp_path / "projects" / upstream_dirname
        (upstream_root / ".git" / "worktrees" / upstream_dirname).mkdir(parents=True)
        upstream_roots.append(upstream_root)

        worktree_subdir = workspace / upstream_dirname
        worktree_subdir.mkdir()
        gitdir_target = upstream_root / ".git" / "worktrees" / upstream_dirname
        (worktree_subdir / ".git").write_text(
            f"gitdir: {gitdir_target}\n"
        )

    if spec_content is not None:
        specs_dir = workspace / "specs" / f"{num}-test"
        specs_dir.mkdir(parents=True)
        (specs_dir / "spec.md").write_text(spec_content)

    return workspace, upstream_roots


# --- Parse and inference ------------------------------------------------------


def test_parse_issue_ref_full_form() -> None:
    owner, repo, num = archive_mod._parse_issue_ref("App-Empire-LLC/DevKit#4")
    assert owner == "App-Empire-LLC"
    assert repo == "DevKit"
    assert num == 4


def test_parse_issue_ref_bare_number() -> None:
    owner, repo, num = archive_mod._parse_issue_ref("4")
    assert owner is None
    assert repo is None
    assert num == 4


def test_parse_issue_ref_bare_hash_number() -> None:
    owner, repo, num = archive_mod._parse_issue_ref("#4")
    assert owner is None
    assert repo is None
    assert num == 4


def test_parse_issue_ref_invalid_exits_usage(runner: CliRunner) -> None:
    result = runner.invoke(app, ["archive", "not-a-ref"])
    assert result.exit_code == E_USAGE


# --- Spec discovery + splitting ----------------------------------------------


def test_find_spec_files_single(tmp_path: Path) -> None:
    workspace, _ = _make_workspace(tmp_path, "DevKit", 4)
    result = archive_mod._find_spec_files(workspace)
    assert len(result) == 1
    assert result[0].name == "spec.md"


def test_find_spec_files_missing_dir(tmp_path: Path) -> None:
    workspace, _ = _make_workspace(tmp_path, "DevKit", 4, spec_content=None)
    result = archive_mod._find_spec_files(workspace)
    assert result == []


def test_find_spec_files_multiple(tmp_path: Path) -> None:
    workspace, _ = _make_workspace(tmp_path, "DevKit", 4)
    # Add a second spec
    second_dir = workspace / "specs" / "4-other"
    second_dir.mkdir()
    (second_dir / "spec.md").write_text("# Second\n")
    result = archive_mod._find_spec_files(workspace)
    assert len(result) == 2


def test_split_for_comments_short_returns_single() -> None:
    chunks = archive_mod._split_for_comments("hello world")
    assert chunks == ["hello world"]


def test_split_for_comments_exactly_threshold_no_split() -> None:
    text = "a" * archive_mod.COMMENT_SIZE_THRESHOLD
    chunks = archive_mod._split_for_comments(text)
    assert len(chunks) == 1


def test_split_for_comments_oversized_hard_split() -> None:
    # No newlines — hard split at threshold
    text = "a" * (archive_mod.COMMENT_SIZE_THRESHOLD + 100)
    chunks = archive_mod._split_for_comments(text)
    assert len(chunks) == 2
    assert len(chunks[0]) == archive_mod.COMMENT_SIZE_THRESHOLD
    assert len(chunks[1]) == 100


def test_split_for_comments_oversized_newline_boundary() -> None:
    # Place a newline inside the last-500 window — split should land on it.
    threshold = archive_mod.COMMENT_SIZE_THRESHOLD
    filler = "x" * (threshold - 100)
    text = filler + "\n" + ("y" * 200)
    chunks = archive_mod._split_for_comments(text)
    assert len(chunks) == 2
    assert chunks[0].endswith("\n")
    assert chunks[1].startswith("y")


# --- Upstream discovery ------------------------------------------------------


def test_discover_upstream_repos_finds_worktrees(
    tmp_path: Path,
    subprocess_capture,
) -> None:
    workspace, _ = _make_workspace(
        tmp_path,
        "DevKit",
        4,
        upstream_repos=[("DevKit", "App-Empire-LLC/DevKit"),
                         ("appire_docs", "App-Empire-LLC/appire_docs")],
    )
    subprocess_capture.queue(
        RunResult(code=0, stdout="https://github.com/App-Empire-LLC/DevKit.git\n", stderr="")
    )
    subprocess_capture.queue(
        RunResult(code=0, stdout="git@github.com:App-Empire-LLC/appire_docs.git\n", stderr="")
    )
    result = archive_mod._discover_upstream_repos(workspace)
    assert sorted(owner_repo for owner_repo, _ in result) == [
        "App-Empire-LLC/DevKit",
        "App-Empire-LLC/appire_docs",
    ]


def test_discover_upstream_repos_ignores_non_git_subdirs(
    tmp_path: Path,
) -> None:
    workspace, _ = _make_workspace(tmp_path, "DevKit", 4)
    # `specs/` exists as a plain subdir — must not be probed as an upstream.
    result = archive_mod._discover_upstream_repos(workspace)
    assert result == []


def test_parse_owner_repo_from_url_https() -> None:
    assert (
        archive_mod._parse_owner_repo_from_url("https://github.com/App-Empire-LLC/DevKit.git")
        == "App-Empire-LLC/DevKit"
    )


def test_parse_owner_repo_from_url_ssh() -> None:
    assert (
        archive_mod._parse_owner_repo_from_url("git@github.com:App-Empire-LLC/DevKit.git")
        == "App-Empire-LLC/DevKit"
    )


def test_parse_owner_repo_from_url_no_suffix() -> None:
    assert (
        archive_mod._parse_owner_repo_from_url("https://github.com/foo/bar")
        == "foo/bar"
    )


# --- PR check -----------------------------------------------------------------


def test_check_prs_merged_all_merged(subprocess_capture) -> None:
    subprocess_capture.queue(
        RunResult(
            code=0,
            stdout=json.dumps([{"number": 99, "state": "MERGED", "url": "https://x/99"}]),
            stderr="",
        )
    )
    blockers = archive_mod._check_prs_merged(
        [("App-Empire-LLC/DevKit", Path("/tmp"))],
        "issue-DevKit-4",
    )
    assert blockers == []


def test_check_prs_merged_open_blocks(subprocess_capture) -> None:
    subprocess_capture.queue(
        RunResult(
            code=0,
            stdout=json.dumps([{"number": 99, "state": "OPEN", "url": "https://x/99"}]),
            stderr="",
        )
    )
    blockers = archive_mod._check_prs_merged(
        [("App-Empire-LLC/DevKit", Path("/tmp"))],
        "issue-DevKit-4",
    )
    assert len(blockers) == 1
    assert "OPEN" in blockers[0]
    assert "#99" in blockers[0]


def test_check_prs_merged_closed_unmerged_blocks(subprocess_capture) -> None:
    subprocess_capture.queue(
        RunResult(
            code=0,
            stdout=json.dumps([{"number": 99, "state": "CLOSED", "url": "https://x/99"}]),
            stderr="",
        )
    )
    blockers = archive_mod._check_prs_merged(
        [("App-Empire-LLC/DevKit", Path("/tmp"))],
        "issue-DevKit-4",
    )
    assert len(blockers) == 1
    assert "CLOSED" in blockers[0]


def test_check_prs_merged_zero_prs_is_ok(subprocess_capture) -> None:
    subprocess_capture.queue(RunResult(code=0, stdout="[]", stderr=""))
    blockers = archive_mod._check_prs_merged(
        [("App-Empire-LLC/DevKit", Path("/tmp"))],
        "issue-DevKit-4",
    )
    assert blockers == []


def test_check_prs_merged_query_failure_is_blocker(subprocess_capture) -> None:
    subprocess_capture.queue(RunResult(code=1, stdout="", stderr="network"))
    blockers = archive_mod._check_prs_merged(
        [("App-Empire-LLC/DevKit", Path("/tmp"))],
        "issue-DevKit-4",
    )
    assert len(blockers) == 1
    assert "failed to query" in blockers[0]


# --- Move + prune -------------------------------------------------------------


def test_move_to_archived_creates_archived_root(tmp_path: Path) -> None:
    worktrees = tmp_path / "worktrees"
    worktrees.mkdir()
    workspace = worktrees / "DevKit-issue-4"
    workspace.mkdir()
    (workspace / "marker").write_text("test")

    dest = archive_mod._move_to_archived(workspace)
    assert not workspace.exists()
    assert dest == worktrees / "_archived" / "DevKit-issue-4"
    assert (dest / "marker").read_text() == "test"


def test_move_to_archived_writes_devkit_archived_marker(tmp_path: Path) -> None:
    worktrees = tmp_path / "worktrees"
    worktrees.mkdir()
    workspace = worktrees / "DevKit-issue-4"
    workspace.mkdir()

    dest = archive_mod._move_to_archived(workspace)
    marker = dest / ".devkit-archived"
    assert marker.is_file(), "archive must drop a .devkit-archived marker"
    raw = marker.read_text().strip()
    parsed = datetime.datetime.fromisoformat(raw)
    now = datetime.datetime.now(datetime.UTC)
    # Generous skew window — CI clocks wobble.
    assert abs((now - parsed).total_seconds()) < 60


def test_prune_worktrees_runs_prune_per_upstream(
    tmp_path: Path,
    subprocess_capture,
) -> None:
    upstream_a = tmp_path / "a"
    upstream_b = tmp_path / "b"
    upstream_a.mkdir()
    upstream_b.mkdir()
    # prune calls: empty stdout; then list --porcelain: empty
    for _ in range(4):
        subprocess_capture.queue(RunResult(code=0, stdout="", stderr=""))
    warnings = archive_mod._prune_worktrees(
        [("owner/a", upstream_a), ("owner/b", upstream_b)],
        tmp_path / "original",
    )
    assert warnings == []
    cmds = [call["cmd"] for call in subprocess_capture.calls]
    prune_calls = [c for c in cmds if c[:3] == ["git", "worktree", "prune"]]
    assert len(prune_calls) == 2


def test_prune_worktrees_reports_stale_entry(
    tmp_path: Path,
    subprocess_capture,
) -> None:
    upstream = tmp_path / "u"
    upstream.mkdir()
    original = tmp_path / "worktrees" / "DevKit-issue-4"
    # prune (code 0), list --porcelain (returns a stale reference)
    subprocess_capture.queue(RunResult(code=0, stdout="", stderr=""))
    subprocess_capture.queue(
        RunResult(
            code=0,
            stdout=f"worktree {original}\nHEAD abc\nbranch refs/heads/issue-DevKit-4\n",
            stderr="",
        )
    )
    warnings = archive_mod._prune_worktrees([("owner/u", upstream)], original)
    assert len(warnings) == 1
    assert "stale worktree registration" in warnings[0]


# --- End-to-end happy path via CLI --------------------------------------------


@pytest.fixture
def archive_env(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    subprocess_capture,
) -> dict:
    """Full happy-path environment: workspace + upstream worktrees + gh/git mocks."""
    workspace, upstream_roots = _make_workspace(
        tmp_path,
        "DevKit",
        4,
        upstream_repos=[("DevKit", "App-Empire-LLC/DevKit")],
    )
    monkeypatch.setattr("aidevkit.archive.shutil.which", _which_git_gh)
    monkeypatch.setenv("APP_EMPIRE_WORKTREES_HOME", str(tmp_path / "worktrees"))

    def default_shell(cmd: list[str], **kwargs) -> RunResult:
        if cmd[:3] == ["git", "remote", "get-url"]:
            return RunResult(
                code=0,
                stdout="https://github.com/App-Empire-LLC/DevKit.git\n",
                stderr="",
            )
        if cmd[:3] == ["gh", "pr", "list"]:
            return RunResult(
                code=0,
                stdout=json.dumps([{"number": 31, "state": "MERGED", "url": "https://x/31"}]),
                stderr="",
            )
        if cmd[:4] == ["gh", "issue", "comment", "4"]:
            return RunResult(code=0, stdout="https://github.com/.../comments/1\n", stderr="")
        if cmd[:4] == ["gh", "issue", "view", "4"]:
            return RunResult(code=0, stdout=json.dumps({"state": "OPEN"}), stderr="")
        if cmd[:4] == ["gh", "issue", "close", "4"]:
            return RunResult(code=0, stdout="", stderr="")
        if cmd[:2] == ["git", "worktree"]:
            return RunResult(code=0, stdout="", stderr="")
        return RunResult(code=0, stdout="", stderr="")

    monkeypatch.setattr("aidevkit.util.run", default_shell)

    return {
        "workspace": workspace,
        "upstream_roots": upstream_roots,
    }


def test_happy_path_cli_exits_zero_and_moves_worktree(
    runner: CliRunner,
    archive_env: dict,
) -> None:
    workspace: Path = archive_env["workspace"]
    result = runner.invoke(app, ["archive", "App-Empire-LLC/DevKit#4"])
    assert result.exit_code == 0, result.output
    assert not workspace.exists()
    archived = workspace.parent / "_archived" / "DevKit-issue-4"
    assert archived.is_dir()
    marker = archived / ".devkit-archived"
    assert marker.is_file()
    datetime.datetime.fromisoformat(marker.read_text().strip())


def test_happy_path_dry_run_makes_no_mutations(
    runner: CliRunner,
    archive_env: dict,
) -> None:
    workspace: Path = archive_env["workspace"]
    result = runner.invoke(app, ["archive", "App-Empire-LLC/DevKit#4", "--dry-run"])
    assert result.exit_code == 0, result.output
    assert workspace.exists()  # NOT moved
    archived = workspace.parent / "_archived" / "DevKit-issue-4"
    assert not archived.exists()


def test_workspace_missing_exits_16(
    runner: CliRunner,
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    subprocess_capture,
) -> None:
    monkeypatch.setattr("aidevkit.archive.shutil.which", _which_git_gh)
    monkeypatch.setenv("APP_EMPIRE_WORKTREES_HOME", str(tmp_path))
    result = runner.invoke(app, ["archive", "App-Empire-LLC/DevKit#4"])
    assert result.exit_code == E_WORKSPACE_MISSING


def test_archived_collision_refuses(
    runner: CliRunner,
    archive_env: dict,
) -> None:
    workspace: Path = archive_env["workspace"]
    archived_root = workspace.parent / "_archived"
    archived_root.mkdir()
    (archived_root / "DevKit-issue-4").mkdir()
    result = runner.invoke(app, ["archive", "App-Empire-LLC/DevKit#4"])
    assert result.exit_code == E_ARCHIVE_COLLISION
    assert workspace.exists()  # no mutation


# --- Guardrail (US2) ---------------------------------------------------------


@pytest.fixture
def archive_env_open_pr(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    subprocess_capture,
) -> dict:
    """Same as archive_env but gh reports an open PR."""
    workspace, _ = _make_workspace(
        tmp_path,
        "DevKit",
        4,
        upstream_repos=[("DevKit", "App-Empire-LLC/DevKit")],
    )
    monkeypatch.setattr("aidevkit.archive.shutil.which", _which_git_gh)
    monkeypatch.setenv("APP_EMPIRE_WORKTREES_HOME", str(tmp_path / "worktrees"))

    def shell(cmd: list[str], **kwargs) -> RunResult:
        if cmd[:3] == ["git", "remote", "get-url"]:
            return RunResult(
                code=0,
                stdout="https://github.com/App-Empire-LLC/DevKit.git\n",
                stderr="",
            )
        if cmd[:3] == ["gh", "pr", "list"]:
            return RunResult(
                code=0,
                stdout=json.dumps([{"number": 99, "state": "OPEN", "url": "https://x/99"}]),
                stderr="",
            )
        if cmd[:4] == ["gh", "issue", "comment", "4"]:
            return RunResult(code=0, stdout="", stderr="")
        if cmd[:4] == ["gh", "issue", "view", "4"]:
            return RunResult(code=0, stdout=json.dumps({"state": "OPEN"}), stderr="")
        if cmd[:4] == ["gh", "issue", "close", "4"]:
            return RunResult(code=0, stdout="", stderr="")
        return RunResult(code=0, stdout="", stderr="")

    monkeypatch.setattr("aidevkit.util.run", shell)
    return {"workspace": workspace}


def test_open_pr_blocks_archive(
    runner: CliRunner,
    archive_env_open_pr: dict,
) -> None:
    workspace: Path = archive_env_open_pr["workspace"]
    result = runner.invoke(app, ["archive", "App-Empire-LLC/DevKit#4"])
    assert result.exit_code == E_PRS_NOT_MERGED
    assert workspace.exists()  # zero mutations
    assert not (workspace.parent / "_archived").exists()


def test_force_overrides_open_pr(
    runner: CliRunner,
    archive_env_open_pr: dict,
) -> None:
    workspace: Path = archive_env_open_pr["workspace"]
    result = runner.invoke(app, ["archive", "App-Empire-LLC/DevKit#4", "--force"])
    assert result.exit_code == 0, result.output
    assert not workspace.exists()
    assert (workspace.parent / "_archived" / "DevKit-issue-4").is_dir()


# --- No-spec case (US3) -------------------------------------------------------


@pytest.fixture
def archive_env_no_spec(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    subprocess_capture,
) -> dict:
    workspace, _ = _make_workspace(
        tmp_path,
        "DevKit",
        4,
        upstream_repos=[("DevKit", "App-Empire-LLC/DevKit")],
        spec_content=None,
    )
    monkeypatch.setattr("aidevkit.archive.shutil.which", _which_git_gh)
    monkeypatch.setenv("APP_EMPIRE_WORKTREES_HOME", str(tmp_path / "worktrees"))

    def shell(cmd: list[str], **kwargs) -> RunResult:
        if cmd[:3] == ["git", "remote", "get-url"]:
            return RunResult(
                code=0,
                stdout="https://github.com/App-Empire-LLC/DevKit.git\n",
                stderr="",
            )
        if cmd[:3] == ["gh", "pr", "list"]:
            return RunResult(code=0, stdout=json.dumps([]), stderr="")
        if cmd[:4] == ["gh", "issue", "view", "4"]:
            return RunResult(code=0, stdout=json.dumps({"state": "OPEN"}), stderr="")
        return RunResult(code=0, stdout="", stderr="")

    monkeypatch.setattr("aidevkit.util.run", shell)
    return {"workspace": workspace}


def test_missing_spec_succeeds_and_skips_comment(
    runner: CliRunner,
    archive_env_no_spec: dict,
) -> None:
    workspace: Path = archive_env_no_spec["workspace"]
    result = runner.invoke(app, ["archive", "App-Empire-LLC/DevKit#4"])
    assert result.exit_code == 0, result.output
    assert "no spec artifact found" in result.output.lower() or \
           "Spec comments posted: 0" in result.output
    assert not workspace.exists()


# --- Already-closed issue (edge case, polish T031) ---------------------------


def test_already_closed_issue_succeeds(
    runner: CliRunner,
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    subprocess_capture,
) -> None:
    """If the issue is already closed, archive completes without erroring on the close step."""
    workspace, _ = _make_workspace(
        tmp_path,
        "DevKit",
        4,
        upstream_repos=[("DevKit", "App-Empire-LLC/DevKit")],
    )
    monkeypatch.setattr("aidevkit.archive.shutil.which", _which_git_gh)
    monkeypatch.setenv("APP_EMPIRE_WORKTREES_HOME", str(tmp_path / "worktrees"))

    close_calls: list[list[str]] = []

    def shell(cmd: list[str], **kwargs) -> RunResult:
        if cmd[:3] == ["git", "remote", "get-url"]:
            return RunResult(
                code=0,
                stdout="https://github.com/App-Empire-LLC/DevKit.git\n",
                stderr="",
            )
        if cmd[:3] == ["gh", "pr", "list"]:
            return RunResult(code=0, stdout=json.dumps([]), stderr="")
        if cmd[:4] == ["gh", "issue", "comment", "4"]:
            return RunResult(code=0, stdout="", stderr="")
        if cmd[:4] == ["gh", "issue", "view", "4"]:
            return RunResult(code=0, stdout=json.dumps({"state": "CLOSED"}), stderr="")
        if cmd[:4] == ["gh", "issue", "close", "4"]:
            close_calls.append(list(cmd))
            return RunResult(code=0, stdout="", stderr="")
        return RunResult(code=0, stdout="", stderr="")

    monkeypatch.setattr("aidevkit.util.run", shell)

    result = runner.invoke(app, ["archive", "App-Empire-LLC/DevKit#4"])
    assert result.exit_code == 0, result.output
    assert close_calls == [], (
        "archive must not call `gh issue close` when issue is already closed"
    )
    assert not workspace.exists()


# --- Fail-fast mid-archive (FR-011a, polish T029) -----------------------------


def test_mv_failure_leaves_partial_state_no_rollback(
    runner: CliRunner,
    archive_env: dict,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """If `shutil.move` raises after comments have been posted, no rollback is attempted.

    The command must propagate the exception and leave the posted-comment state
    in place for the user to resolve. Verifies FR-011a ("fail-fast, no auto-rollback").
    """
    workspace: Path = archive_env["workspace"]
    posted_comments: list[list[str]] = []

    # Replace util.run with a version that records gh issue comment calls so we
    # can assert no "unpost" (delete) call happens after the mv failure.
    original_run = __import__("aidevkit.util", fromlist=["run"]).run

    def recording_run(cmd: list[str], **kwargs) -> RunResult:
        if cmd[:3] == ["gh", "issue", "comment"]:
            posted_comments.append(list(cmd))
        if cmd[:2] == ["gh", "api"] and "DELETE" in cmd:
            raise AssertionError(
                "archive must not attempt to delete posted comments on mid-step failure"
            )
        return original_run(cmd, **kwargs)

    monkeypatch.setattr("aidevkit.util.run", recording_run)

    def failing_move(src, dst):
        raise OSError("simulated mv failure")

    monkeypatch.setattr("aidevkit.archive.shutil.move", failing_move)

    result = runner.invoke(app, ["archive", "App-Empire-LLC/DevKit#4"])
    assert result.exit_code != 0
    # Comments were posted BEFORE the mv step — they stay posted (no rollback).
    assert len(posted_comments) >= 1
    # Workspace still exists (mv failed, no re-move attempted).
    assert workspace.exists()
