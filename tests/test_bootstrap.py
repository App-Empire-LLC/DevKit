"""Tests for the bootstrap subcommand — parsing, required args, flags, exit codes."""
from __future__ import annotations

import json
from pathlib import Path

import pytest
from typer.testing import CliRunner

from aidevkit.cli import app
from aidevkit.util import (
    E_DEP_MISSING,
    E_ORIGIN_MAIN_UNAVAILABLE,
    E_REPO_NOT_FOUND,
    E_REPOS_MISSING,
    E_USAGE,
    E_WORKSPACE_EXISTS,
    RunResult,
)


@pytest.fixture
def runner(monkeypatch: pytest.MonkeyPatch) -> CliRunner:
    monkeypatch.setenv("NO_COLOR", "1")
    return CliRunner()


def _which_all_present(tmp_path: Path) -> "callable":
    def _which(name: str) -> str | None:
        if name in {"git", "gh", "jq"}:
            return str(tmp_path / "bin" / name)
        return None

    return _which


@pytest.fixture
def bootstrap_env(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    gh_response,
    subprocess_capture,
) -> dict:
    """Set up a full happy-path bootstrap environment.

    Returns a dict with `projects_dir`, `workspaces_dir`, `issue_payload`,
    and the `capture` recorder. Seeds:
    - $PROJECTS_HOME/.devkit/config.yaml  (version, org, workspaces_home)
    - $PROJECTS_HOME/.devkit/PROJECTS.md  (DevKit + appire_docs catalog rows)
    - $PROJECTS_HOME/DevKit/.git/         (source clone sentinel)
    - $PROJECTS_HOME/appire_docs/.git/    (source clone sentinel)
    Sets PROJECTS_HOME, points HOME at an empty dir (no global .devkit/).
    """
    projects = tmp_path / "projects"
    workspaces = tmp_path / "workspaces"
    fake_home = tmp_path / "fake-home"
    projects.mkdir()
    workspaces.mkdir()
    fake_home.mkdir()

    for reponame in ("DevKit", "appire_docs"):
        repo_dir = projects / reponame
        (repo_dir / ".git").mkdir(parents=True)

    devkit_dir = projects / ".devkit"
    devkit_dir.mkdir()
    (devkit_dir / "config.yaml").write_text(
        f"version: 1\norg: App-Empire-LLC\nworkspaces_home: {workspaces}\n"
    )
    (devkit_dir / "PROJECTS.md").write_text(
        "# Projects\n\n"
        "| name | git_url | default_branch | description |\n"
        "|------|---------|----------------|-------------|\n"
        "| DevKit | git@github.com:App-Empire-LLC/DevKit.git | main | DevKit |\n"
        "| appire_docs | git@github.com:App-Empire-LLC/appire_docs.git "
        "| main | Docs |\n"
    )

    monkeypatch.setattr("aidevkit.bootstrap.shutil.which", _which_all_present(tmp_path))
    monkeypatch.setenv("PROJECTS_HOME", str(projects))
    monkeypatch.setattr("pathlib.Path.home", classmethod(lambda cls: fake_home))
    # Reset the cli.py org-shorthand cache between tests.
    from aidevkit import cli as _cli
    if hasattr(_cli._resolve_org_lazy, "_cached"):
        delattr(_cli._resolve_org_lazy, "_cached")
    # Reset the global config path module-level constant for hermetic resolution.
    monkeypatch.setattr(
        "aidevkit.config._GLOBAL_CONFIG_PATH",
        fake_home / ".devkit" / "config.yaml",
    )
    # Drop legacy env vars so nothing accidentally reads them.
    monkeypatch.delenv("APP_EMPIRE_PROJECTS", raising=False)
    monkeypatch.delenv("APP_EMPIRE_WORKTREES_HOME", raising=False)

    payload = gh_response("issue_with_affected_repos")
    subprocess_capture.set_default(
        RunResult(code=0, stdout=json.dumps(payload), stderr="")
    )

    return {
        "projects_dir": projects,
        "workspaces_dir": workspaces,
        "issue_payload": payload,
        "capture": subprocess_capture,
    }


# --- T013: issue-reference parsing ------------------------------------------


@pytest.mark.parametrize(
    "arg,expected_ok",
    [
        ("App-Empire-LLC/DevKit#22", True),
        ("owner/repo-name#1", True),
        ("a/b#12345", True),
        # DevKit#37 FR-005a: bare 'DevKit#22' is valid — expanded via the
        # `org` config field. The bootstrap_env fixture sets org=App-Empire-LLC.
        ("DevKit#22", True),
        ("owner/repo", False),
        ("owner/repo#", False),
        ("", False),
        ("owner/repo#abc", False),
    ],
)
def test_issue_ref_parsing(
    runner: CliRunner,
    bootstrap_env: dict,
    arg: str,
    expected_ok: bool,
) -> None:
    result = runner.invoke(app, ["bootstrap", "--dry-run", arg])
    if expected_ok:
        # Parsing succeeded — the command may still fail downstream because
        # the fake owner/repo#N doesn't match pre-seeded src dirs, but we
        # must NOT see the "issue must be in form" usage error.
        assert result.exit_code != E_USAGE, result.output
        assert "issue must be in form" not in result.output
    else:
        assert result.exit_code == E_USAGE, (
            f"expected usage error for {arg!r}, got {result.exit_code}: {result.output}"
        )
        assert "issue must be in form" in result.output


# --- T014: required positional argument --------------------------------------


def test_missing_required_argument(runner: CliRunner) -> None:
    result = runner.invoke(app, ["bootstrap"])
    assert result.exit_code != 0
    assert "OWNER/REPO#N" in result.output or "Missing argument" in result.output


# --- T015: one dedicated happy-path test per flag ----------------------------


def test_flag_dry_run_skips_mutations(runner: CliRunner, bootstrap_env: dict) -> None:
    result = runner.invoke(
        app, ["bootstrap", "--dry-run", "App-Empire-LLC/DevKit#22"]
    )
    assert result.exit_code == 0, result.output
    assert "[dry-run]" in result.output

    calls = bootstrap_env["capture"].calls
    git_worktree_calls = [c for c in calls if c["cmd"][:2] == ["git", "worktree"]]
    gh_comment_calls = [
        c for c in calls if c["cmd"][:2] == ["gh", "issue"] and "comment" in c["cmd"]
    ]
    assert git_worktree_calls == [], "dry-run must not add worktrees"
    assert gh_comment_calls == [], "dry-run must not post ack comments"

    # The workspace dir should never be created in dry-run.
    assert not (bootstrap_env["workspaces_dir"] / "DevKit-issue-22").exists()


def test_flag_repos_additive(
    runner: CliRunner,
    bootstrap_env: dict,
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    """DevKit#37 FR-018a: --repos is additive, not override.
    Issue body lists DevKit + appire_docs; --repos adds OtherRepo on top."""
    # Add another source repo + catalog row so --repos has somewhere to point.
    (bootstrap_env["projects_dir"] / "OtherRepo" / ".git").mkdir(parents=True)
    catalog_path = bootstrap_env["projects_dir"] / ".devkit" / "PROJECTS.md"
    catalog_path.write_text(
        catalog_path.read_text()
        + "| OtherRepo | git@github.com:App-Empire-LLC/OtherRepo.git "
        "| main | other |\n"
    )

    result = runner.invoke(
        app,
        [
            "bootstrap",
            "--dry-run",
            "--repos",
            "App-Empire-LLC/OtherRepo",
            "App-Empire-LLC/DevKit#22",
        ],
    )

    assert result.exit_code == 0, result.output
    # Both issue-body repos AND the --repos addition are present.
    assert "App-Empire-LLC/DevKit" in result.output
    assert "App-Empire-LLC/appire_docs" in result.output
    assert "App-Empire-LLC/OtherRepo" in result.output


def test_flag_no_ack_skips_comment(runner: CliRunner, bootstrap_env: dict) -> None:
    capture = bootstrap_env["capture"]

    # gh issue view returns the issue payload; every subsequent call (git init,
    # git worktree add, etc.) returns a benign success.
    capture.set_default(RunResult(code=0, stdout="", stderr=""))
    capture.queue(
        RunResult(code=0, stdout=json.dumps(bootstrap_env["issue_payload"]), stderr="")
    )

    result = runner.invoke(
        app,
        ["bootstrap", "--no-ack", "App-Empire-LLC/DevKit#22"],
    )

    assert result.exit_code == 0, result.output
    gh_comment_calls = [
        c for c in capture.calls if c["cmd"][:3] == ["gh", "issue", "comment"]
    ]
    assert gh_comment_calls == [], "--no-ack must not post an ack comment"

    # And an acknowledging call path proves worktree creation did run.
    git_worktree_calls = [c for c in capture.calls if c["cmd"][:2] == ["git", "worktree"]]
    assert git_worktree_calls, "non-dry-run should have issued git worktree add"


# --- T016: exit code paths ---------------------------------------------------


def test_exit_code_13_repo_not_in_catalog(
    runner: CliRunner,
    bootstrap_env: dict,
    gh_response,
) -> None:
    """DevKit#37 FR-010: an issue home repo that's not in PROJECTS.md
    must refuse with E_REPO_NOT_FOUND (formerly tested as the 'no affected
    repos' path under #27)."""
    minimal = gh_response("issue_minimal")
    # Issue home is some-other-owner/UnknownRepo — not in the catalog.
    minimal["url"] = "https://github.com/some-other-owner/UnknownRepo/issues/999"
    bootstrap_env["capture"].set_default(
        RunResult(code=0, stdout=json.dumps(minimal), stderr="")
    )

    result = runner.invoke(
        app, ["bootstrap", "--dry-run", "some-other-owner/UnknownRepo#999"]
    )
    assert result.exit_code == E_REPO_NOT_FOUND, result.output


def test_exit_code_11_workspace_exists(
    runner: CliRunner,
    bootstrap_env: dict,
) -> None:
    workspace = bootstrap_env["workspaces_dir"] / "DevKit-issue-22"
    workspace.mkdir()

    result = runner.invoke(
        app, ["bootstrap", "--dry-run", "App-Empire-LLC/DevKit#22"]
    )
    assert result.exit_code == E_WORKSPACE_EXISTS, result.output


def test_exit_code_12_dep_missing(
    runner: CliRunner,
    bootstrap_env: dict,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def _which_missing_gh(name: str) -> str | None:
        if name == "gh":
            return None
        return "/usr/bin/" + name

    monkeypatch.setattr("aidevkit.bootstrap.shutil.which", _which_missing_gh)

    result = runner.invoke(
        app, ["bootstrap", "--dry-run", "App-Empire-LLC/DevKit#22"]
    )
    assert result.exit_code == E_DEP_MISSING, result.output


def test_exit_code_13_source_repo_not_found(
    runner: CliRunner,
    bootstrap_env: dict,
) -> None:
    # Remove the DevKit src repo so verify_source_repos fails on the home repo.
    import shutil as _sh
    _sh.rmtree(bootstrap_env["projects_dir"] / "DevKit")

    result = runner.invoke(
        app, ["bootstrap", "--dry-run", "App-Empire-LLC/DevKit#22"]
    )
    assert result.exit_code == E_REPO_NOT_FOUND, result.output


# Keep E_REPOS_MISSING referenced so a future contributor who renames it doesn't
# silently break the invariant the module exposes. The spec lists 10/11/12/13
# as the documented exit codes; this import-level symbol makes that explicit.
_EXIT_CODES_UNDER_TEST = (
    E_REPOS_MISSING,
    E_WORKSPACE_EXISTS,
    E_DEP_MISSING,
    E_REPO_NOT_FOUND,
    E_ORIGIN_MAIN_UNAVAILABLE,
)


# --- DevKit#27: bootstrap origin/main semantics -----------------------------
#
# Tests T003–T005 (US1 happy path) and T009–T010 (FR-006 hermeticity +
# SC-006 ref-snapshot) for the two-phase bootstrap that bases new issue
# branches on origin/main instead of the source repo's current HEAD.


def _invoke_happy_bootstrap(
    runner: CliRunner, bootstrap_env: dict, issue_arg: str = "App-Empire-LLC/DevKit#22"
):
    """Run a successful bootstrap with --no-ack. Returns the CliRunner result."""
    capture = bootstrap_env["capture"]
    capture.set_default(RunResult(code=0, stdout="", stderr=""))
    # First shell call is `gh issue view`; queue the issue payload for it.
    capture.queue(
        RunResult(code=0, stdout=json.dumps(bootstrap_env["issue_payload"]), stderr="")
    )
    return runner.invoke(app, ["bootstrap", "--no-ack", issue_arg])


def test_bootstrap_fetches_origin_before_worktree_add(
    runner: CliRunner, bootstrap_env: dict
) -> None:
    """T003 / FR-001: validation phase (fetch + verify) precedes creation phase."""
    result = _invoke_happy_bootstrap(runner, bootstrap_env)
    assert result.exit_code == 0, result.output
    calls = bootstrap_env["capture"].calls

    def _first(pred) -> int:
        for i, c in enumerate(calls):
            if pred(c):
                return i
        return -1

    fetch_idx = _first(lambda c: c["cmd"][:2] == ["git", "fetch"])
    verify_idx = _first(
        lambda c: c["cmd"][:2] == ["git", "rev-parse"]
        and "refs/remotes/origin/main" in c["cmd"]
    )
    init_idx = _first(lambda c: c["cmd"][:2] == ["git", "init"])
    worktree_idx = _first(lambda c: c["cmd"][:3] == ["git", "worktree", "add"])

    assert fetch_idx != -1, f"no git fetch call observed in {calls}"
    assert verify_idx != -1, (
        f"no git rev-parse --verify refs/remotes/origin/main observed in {calls}"
    )
    assert init_idx != -1, "no git init call observed"
    assert worktree_idx != -1, "no git worktree add call observed"
    assert fetch_idx < init_idx, "fetch must precede git init (validation before creation)"
    assert verify_idx < init_idx, "rev-parse --verify must precede git init"
    assert init_idx < worktree_idx, "git init must precede git worktree add"


def test_bootstrap_worktree_add_uses_origin_main(
    runner: CliRunner, bootstrap_env: dict
) -> None:
    """T004 / FR-002: every `git worktree add` passes `origin/main` as start point."""
    result = _invoke_happy_bootstrap(runner, bootstrap_env)
    assert result.exit_code == 0, result.output
    worktree_adds = [
        c for c in bootstrap_env["capture"].calls
        if c["cmd"][:3] == ["git", "worktree", "add"]
    ]
    assert worktree_adds, "expected at least one git worktree add call"
    for c in worktree_adds:
        assert c["cmd"][-1] == "origin/main", (
            f"worktree add must end with origin/main start point, got: {c['cmd']}"
        )


def test_bootstrap_does_not_touch_local_main(
    runner: CliRunner, bootstrap_env: dict
) -> None:
    """T005 / FR-003: no command mutates local main in any source repo."""
    result = _invoke_happy_bootstrap(runner, bootstrap_env)
    assert result.exit_code == 0, result.output
    forbidden_prefixes = (
        ("git", "branch", "-f", "main"),
        ("git", "reset"),
        ("git", "update-ref", "refs/heads/main"),
        ("git", "checkout", "main"),
    )
    for c in bootstrap_env["capture"].calls:
        cmd = tuple(c["cmd"])
        for bad in forbidden_prefixes:
            assert cmd[: len(bad)] != bad, (
                f"forbidden local-main mutation: {' '.join(c['cmd'])}"
            )


def test_bootstrap_leaves_source_repo_working_tree_untouched(
    runner: CliRunner, bootstrap_env: dict
) -> None:
    """T009 / FR-006 (analysis C1): the only git verbs observed against a
    source repo's cwd are fetch, rev-parse (read-only), and worktree add."""
    result = _invoke_happy_bootstrap(runner, bootstrap_env)
    assert result.exit_code == 0, result.output
    projects_dir = bootstrap_env["projects_dir"]
    src_cwds = {projects_dir / name for name in ("DevKit", "appire_docs")}
    allowed = (
        ("git", "fetch"),
        ("git", "rev-parse"),
        ("git", "worktree", "add"),
    )
    for c in bootstrap_env["capture"].calls:
        if c["cwd"] not in src_cwds:
            continue
        cmd = tuple(c["cmd"])
        assert any(cmd[: len(p)] == p for p in allowed), (
            f"unexpected git verb against source repo {c['cwd']}: {' '.join(c['cmd'])}"
        )


def test_bootstrap_ref_snapshot_matches_allowed_delta(
    runner: CliRunner, bootstrap_env: dict
) -> None:
    """T010 / SC-006 (analysis C2): the only ref-mutating verbs observed are
    `git fetch` (updates refs/remotes/origin/*) and `git worktree add -b`
    (creates exactly the new issue branch). Positive assertion — enumerate
    every git call and reject unexpected ref mutators or --force* flags."""
    result = _invoke_happy_bootstrap(runner, bootstrap_env)
    assert result.exit_code == 0, result.output
    ref_mutating_verbs = {"branch", "update-ref", "push", "tag", "reflog"}
    for c in bootstrap_env["capture"].calls:
        if c["cmd"][:1] != ["git"]:
            continue
        cmd = c["cmd"]
        if cmd[:2] == ["git", "fetch"]:
            continue
        if cmd[:3] == ["git", "worktree", "add"]:
            continue
        # Every other git verb must not be in the ref-mutating set.
        assert len(cmd) >= 2, f"malformed git call: {cmd}"
        assert cmd[1] not in ref_mutating_verbs, (
            f"unexpected ref-mutating verb: {' '.join(cmd)}"
        )
        # And no --force* flags anywhere.
        for tok in cmd:
            assert not tok.startswith("--force"), f"forbidden --force flag: {' '.join(cmd)}"


# --- DevKit#27 US3: multi-repo atomicity and clear diagnostics --------------


def test_bootstrap_fetch_failure_creates_nothing(
    runner: CliRunner, bootstrap_env: dict
) -> None:
    """T011 / FR-004, SC-007: if any affected repo's fetch fails, bootstrap
    aborts before any worktree, branch, or workspace dir is created — even
    for repos whose validation would have succeeded."""
    capture = bootstrap_env["capture"]
    payload = bootstrap_env["issue_payload"]
    # Call sequence: gh issue view, DevKit fetch OK, DevKit verify OK,
    # appire_docs fetch FAILS. Queue exactly these four; default covers any
    # unexpected trailing call but none is expected after the failure.
    capture.set_default(RunResult(code=0, stdout="", stderr=""))
    capture.queue(RunResult(code=0, stdout=json.dumps(payload), stderr=""))
    capture.queue(RunResult(code=0, stdout="", stderr=""))  # DevKit git fetch
    capture.queue(RunResult(code=0, stdout="abc123\n", stderr=""))  # DevKit rev-parse --verify
    capture.queue(
        RunResult(code=128, stdout="", stderr="fatal: could not read from remote repository")
    )

    result = runner.invoke(app, ["bootstrap", "--no-ack", "App-Empire-LLC/DevKit#22"])

    assert result.exit_code == E_ORIGIN_MAIN_UNAVAILABLE, result.output
    # No creation-phase calls.
    git_inits = [c for c in capture.calls if c["cmd"][:2] == ["git", "init"]]
    git_worktree_adds = [
        c for c in capture.calls if c["cmd"][:3] == ["git", "worktree", "add"]
    ]
    assert git_inits == [], "git init must not run when validation fails"
    assert git_worktree_adds == [], "git worktree add must not run when validation fails"
    # And no workspace dir on disk.
    assert not (bootstrap_env["workspaces_dir"] / "DevKit-issue-22").exists(), (
        "workspace dir must not exist when validation fails"
    )


def test_bootstrap_missing_origin_main_creates_nothing(
    runner: CliRunner, bootstrap_env: dict
) -> None:
    """T012 / FR-005, SC-007: same atomicity guarantee when rev-parse --verify
    fails (origin/main ref does not exist after fetch)."""
    capture = bootstrap_env["capture"]
    payload = bootstrap_env["issue_payload"]
    capture.set_default(RunResult(code=0, stdout="", stderr=""))
    capture.queue(RunResult(code=0, stdout=json.dumps(payload), stderr=""))
    capture.queue(RunResult(code=0, stdout="", stderr=""))  # DevKit git fetch OK
    capture.queue(RunResult(code=1, stdout="", stderr=""))  # DevKit rev-parse --verify FAILS

    result = runner.invoke(app, ["bootstrap", "--no-ack", "App-Empire-LLC/DevKit#22"])

    assert result.exit_code == E_ORIGIN_MAIN_UNAVAILABLE, result.output
    git_inits = [c for c in capture.calls if c["cmd"][:2] == ["git", "init"]]
    git_worktree_adds = [
        c for c in capture.calls if c["cmd"][:3] == ["git", "worktree", "add"]
    ]
    assert git_inits == []
    assert git_worktree_adds == []
    assert not (bootstrap_env["workspaces_dir"] / "DevKit-issue-22").exists()


def test_bootstrap_fetch_error_message_identifies_repo(
    runner: CliRunner, bootstrap_env: dict
) -> None:
    """T013 / FR-004, FR-013: error message names the failing repo and
    distinguishes fetch-failure from missing-origin/main."""
    capture = bootstrap_env["capture"]
    payload = bootstrap_env["issue_payload"]

    # Case 1: fetch failure — message mentions the failing repo.
    capture.set_default(RunResult(code=0, stdout="", stderr=""))
    capture.queue(RunResult(code=0, stdout=json.dumps(payload), stderr=""))
    capture.queue(RunResult(code=0, stdout="", stderr=""))  # DevKit fetch
    capture.queue(RunResult(code=0, stdout="abc123\n", stderr=""))  # DevKit verify
    capture.queue(
        RunResult(code=128, stdout="", stderr="fatal: could not read Username for 'https://github.com'")
    )
    result = runner.invoke(app, ["bootstrap", "--no-ack", "App-Empire-LLC/DevKit#22"])
    assert result.exit_code == E_ORIGIN_MAIN_UNAVAILABLE, result.output
    assert "App-Empire-LLC/appire_docs" in result.output, (
        f"fetch-failure message must identify the repo: {result.output}"
    )
    assert "fetch origin failed" in result.output, (
        f"message must say 'fetch origin failed' (transient/network class): {result.output}"
    )


def test_bootstrap_missing_origin_message_distinguishes_from_fetch_fail(
    runner: CliRunner, bootstrap_env: dict
) -> None:
    """T013 cont. / FR-005: the 'origin/main not found' diagnostic is
    distinct from the 'fetch origin failed' one — distinguishing transient
    (network / auth) failures from structural (remote misconfigured) ones."""
    capture = bootstrap_env["capture"]
    payload = bootstrap_env["issue_payload"]
    capture.set_default(RunResult(code=0, stdout="", stderr=""))
    capture.queue(RunResult(code=0, stdout=json.dumps(payload), stderr=""))
    capture.queue(RunResult(code=0, stdout="", stderr=""))  # DevKit fetch OK
    capture.queue(RunResult(code=1, stdout="", stderr=""))  # DevKit verify FAILS

    result = runner.invoke(app, ["bootstrap", "--no-ack", "App-Empire-LLC/DevKit#22"])
    assert result.exit_code == E_ORIGIN_MAIN_UNAVAILABLE, result.output
    assert "App-Empire-LLC/DevKit" in result.output, (
        "origin/main-missing message must identify the repo"
    )
    assert "origin/main not found" in result.output, (
        f"message must say 'origin/main not found' (structural class): {result.output}"
    )
    assert "fetch origin failed" not in result.output, (
        "missing-origin must NOT be reported as a fetch failure"
    )
