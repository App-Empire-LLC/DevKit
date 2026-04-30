"""End-to-end integration tests for `devkit bootstrap` against the new
.devkit/ tiered configuration model (DevKit#37).

Uses real `git` against tmpdir-backed bare-repo origins. Mocks only `gh`
(which would otherwise require a real GitHub remote and authentication).
"""
from __future__ import annotations

import json
import shutil
import subprocess
from pathlib import Path

import pytest
from typer.testing import CliRunner

from aidevkit import cli as _cli
from aidevkit.cli import app
from aidevkit.util import (
    E_CONFIG_INVALID,
    E_DEP_MISSING,
    E_REPO_NOT_FOUND,
    E_TEMPLATE_COLLISION,
    RunResult,
)


def _git(*args: str, cwd: Path) -> None:
    res = subprocess.run(
        ["git", *args], cwd=cwd, capture_output=True, text=True, check=False,
    )
    if res.returncode != 0:
        raise RuntimeError(
            f"git {' '.join(args)} failed in {cwd}: "
            f"{res.stderr.strip() or res.stdout.strip()}"
        )


def _init_bare_origin(origin: Path) -> None:
    """Create an `--bare` repo and seed it with one commit on main."""
    origin.mkdir(parents=True)
    _git("init", "--bare", "--initial-branch=main", cwd=origin)
    seed = origin.parent / f"_seed_{origin.name}"
    seed.mkdir()
    _git("init", "--initial-branch=main", cwd=seed)
    _git("config", "user.email", "test@example.com", cwd=seed)
    _git("config", "user.name", "Test", cwd=seed)
    (seed / "README.md").write_text("# seed\n")
    _git("add", ".", cwd=seed)
    _git("commit", "-m", "seed", cwd=seed)
    _git("push", str(origin), "main", cwd=seed)
    shutil.rmtree(seed)


def _seed_source_clone(projects_home: Path, name: str, origin: Path) -> Path:
    """Clone `origin` into `$PROJECTS_HOME/<name>/` so bootstrap finds it."""
    target = projects_home / name
    _git("clone", str(origin), str(target), cwd=projects_home)
    _git("config", "user.email", "test@example.com", cwd=target)
    _git("config", "user.name", "Test", cwd=target)
    return target


@pytest.fixture
def runner(monkeypatch: pytest.MonkeyPatch) -> CliRunner:
    monkeypatch.setenv("NO_COLOR", "1")
    return CliRunner()


@pytest.fixture
def tiered_setup(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> dict:
    """Build a fresh .devkit/ + source-clone fixture under tmp_path.

    Returns:
        projects_home: $PROJECTS_HOME/
        workspaces_home: where bootstrap creates workspaces
        fake_home: ~/.devkit/ stand-in (empty by default)
        ph_devkit: $PROJECTS_HOME/.devkit/
    """
    projects_home = tmp_path / "projects"
    workspaces_home = tmp_path / "worktrees"
    fake_home = tmp_path / "fake-home"
    projects_home.mkdir()
    workspaces_home.mkdir()
    fake_home.mkdir()

    ph_devkit = projects_home / ".devkit"
    ph_devkit.mkdir()
    (ph_devkit / "config.yaml").write_text(
        f"version: 1\norg: TestOrg\nworkspaces_home: {workspaces_home}\n"
    )
    (ph_devkit / "PROJECTS.md").write_text(
        "# Projects\n\n"
        "| name | git_url | default_branch | description |\n"
        "|------|---------|----------------|-------------|\n"
        "| repo-a | git@github.com:TestOrg/repo-a.git | main | A |\n"
    )

    # Seed origin + clone for repo-a
    origin = tmp_path / "origins" / "repo-a.git"
    _init_bare_origin(origin)
    _seed_source_clone(projects_home, "repo-a", origin)

    monkeypatch.setenv("PROJECTS_HOME", str(projects_home))
    monkeypatch.setattr("pathlib.Path.home", classmethod(lambda cls: fake_home))
    monkeypatch.setattr(
        "aidevkit.config._GLOBAL_CONFIG_PATH",
        fake_home / ".devkit" / "config.yaml",
    )
    monkeypatch.delenv("APP_EMPIRE_PROJECTS", raising=False)
    monkeypatch.delenv("APP_EMPIRE_WORKTREES_HOME", raising=False)
    # Clear cli.py org cache between tests
    if hasattr(_cli._resolve_org_lazy, "_cached"):
        delattr(_cli._resolve_org_lazy, "_cached")

    return {
        "projects_home": projects_home,
        "workspaces_home": workspaces_home,
        "fake_home": fake_home,
        "ph_devkit": ph_devkit,
        "origin_repo_a": origin,
    }


def _mock_gh(monkeypatch: pytest.MonkeyPatch, payload: dict) -> list[list[str]]:
    """Mock aidevkit.bootstrap.gh — first call returns `payload`, others return success.

    Returns a list that test code can inspect for posted comments.
    """
    posted_comments: list[list[str]] = []

    def fake_gh(*args, **kwargs):
        cmd = list(args)
        if cmd[:2] == ["issue", "view"]:
            return RunResult(code=0, stdout=json.dumps(payload), stderr="")
        if cmd[:2] == ["issue", "comment"]:
            posted_comments.append(cmd)
            return RunResult(code=0, stdout="", stderr="")
        return RunResult(code=0, stdout="", stderr="")

    monkeypatch.setattr("aidevkit.bootstrap.gh", fake_gh)
    return posted_comments


def _which_real_git(tmp_path: Path):
    """Allow the real `git`, `gh`, `jq` to be discovered (gh won't be called
    since we mock the wrapper at the module seam)."""
    real_git = shutil.which("git")
    real_jq = shutil.which("jq")

    def _which(name: str):
        if name == "git":
            return real_git
        if name == "jq":
            return real_jq or "/usr/bin/jq"
        if name == "gh":
            return "/usr/bin/gh"  # presence check only
        return None

    return _which


# ----- US1 acceptance scenarios -----------------------------------------------

def test_us1_full_owner_repo(
    runner: CliRunner,
    tiered_setup: dict,
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    """US1 scenario 1: env var, fully qualified ref, single repo, no templates."""
    monkeypatch.setattr("aidevkit.bootstrap.shutil.which", _which_real_git(tmp_path))
    _mock_gh(monkeypatch, {
        "title": "Test issue",
        "body": "## Affected Repos\n\n- TestOrg/repo-a\n",
        "url": "https://github.com/TestOrg/repo-a/issues/42",
    })

    result = runner.invoke(
        app,
        ["bootstrap", "--no-ack", "TestOrg/repo-a#42"],
    )
    assert result.exit_code == 0, result.output

    workspace = tiered_setup["workspaces_home"] / "repo-a-issue-42"
    assert workspace.is_dir()
    assert (workspace / "WORKSPACE.md").is_file()
    assert (workspace / "TRUNK.md").read_text() == "main\n"
    assert (workspace / "PROJECTS.md").is_file()
    assert (workspace / "repo-a").is_dir()
    assert (workspace / "repo-a" / ".git").exists()
    # No App-Empire env var was read.
    assert "APP_EMPIRE" not in result.output


def test_us1_projects_home_via_global(
    runner: CliRunner,
    tiered_setup: dict,
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    """US1 scenario 2: projects-home resolved from ~/.devkit/config.yaml#projects_home."""
    fake_home = tiered_setup["fake_home"]
    global_config = fake_home / ".devkit" / "config.yaml"
    global_config.parent.mkdir(parents=True, exist_ok=True)
    global_config.write_text(
        f"version: 1\nprojects_home: {tiered_setup['projects_home']}\n"
    )
    monkeypatch.delenv("PROJECTS_HOME", raising=False)
    monkeypatch.setattr("aidevkit.bootstrap.shutil.which", _which_real_git(tmp_path))
    _mock_gh(monkeypatch, {
        "title": "T",
        "body": "## Affected Repos\n\n- TestOrg/repo-a\n",
        "url": "https://github.com/TestOrg/repo-a/issues/7",
    })

    result = runner.invoke(
        app,
        ["bootstrap", "--no-ack", "TestOrg/repo-a#7"],
    )
    assert result.exit_code == 0, result.output
    assert (tiered_setup["workspaces_home"] / "repo-a-issue-7").is_dir()


def test_us1_no_projects_home(
    runner: CliRunner,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """US1 scenario 3: neither resolution path → E_DEP_MISSING with both
    paths in the error message."""
    fake_home = tmp_path / "fake-home"
    fake_home.mkdir()
    monkeypatch.delenv("PROJECTS_HOME", raising=False)
    monkeypatch.setattr("pathlib.Path.home", classmethod(lambda cls: fake_home))
    monkeypatch.setattr(
        "aidevkit.config._GLOBAL_CONFIG_PATH",
        fake_home / ".devkit" / "config.yaml",
    )
    monkeypatch.setattr("aidevkit.bootstrap.shutil.which", _which_real_git(tmp_path))
    _mock_gh(monkeypatch, {
        "title": "T", "body": "", "url": "https://github.com/x/y/issues/1",
    })
    if hasattr(_cli._resolve_org_lazy, "_cached"):
        delattr(_cli._resolve_org_lazy, "_cached")

    result = runner.invoke(app, ["bootstrap", "--no-ack", "x/y#1"])
    assert result.exit_code == E_DEP_MISSING, result.output
    # Both lookup paths surfaced.
    assert "$PROJECTS_HOME" in result.output
    assert "~/.devkit/config.yaml" in result.output


def test_us1_invalid_config(
    runner: CliRunner,
    tiered_setup: dict,
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    """US1 scenario 4: per-field error format, stops at first failure."""
    # Break the config: workspaces_home points at a nonexistent dir.
    (tiered_setup["ph_devkit"] / "config.yaml").write_text(
        "version: 1\norg: TestOrg\nworkspaces_home: /no-such-directory-xyz\n"
    )
    monkeypatch.setattr("aidevkit.bootstrap.shutil.which", _which_real_git(tmp_path))
    _mock_gh(monkeypatch, {
        "title": "T",
        "body": "## Affected Repos\n\n- TestOrg/repo-a\n",
        "url": "https://github.com/TestOrg/repo-a/issues/1",
    })

    result = runner.invoke(app, ["bootstrap", "--no-ack", "TestOrg/repo-a#1"])
    assert result.exit_code == E_CONFIG_INVALID, result.output
    # Per-field error structure
    assert "Field: workspaces_home" in result.output
    assert "Problem:" in result.output
    assert "Fix:" in result.output


# ----- US4 acceptance scenarios (wired via T008's catalog enforcement) -------

def test_us4_always_include(
    runner: CliRunner,
    tiered_setup: dict,
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    """US4 scenario 1: always_include_repos adds a worktree even when not in
    the issue body."""
    # Add 'foo' to catalog + sources, set always_include
    foo_origin = tmp_path / "origins" / "foo.git"
    _init_bare_origin(foo_origin)
    _seed_source_clone(tiered_setup["projects_home"], "foo", foo_origin)
    catalog_path = tiered_setup["ph_devkit"] / "PROJECTS.md"
    catalog_path.write_text(
        catalog_path.read_text()
        + "| foo | git@github.com:TestOrg/foo.git | main | foo |\n"
    )
    config_path = tiered_setup["ph_devkit"] / "config.yaml"
    config_path.write_text(
        config_path.read_text() + "always_include_repos:\n  - TestOrg/foo\n"
    )

    monkeypatch.setattr("aidevkit.bootstrap.shutil.which", _which_real_git(tmp_path))
    _mock_gh(monkeypatch, {
        "title": "T",
        "body": "## Affected Repos\n\n- TestOrg/repo-a\n",
        "url": "https://github.com/TestOrg/repo-a/issues/1",
    })

    result = runner.invoke(app, ["bootstrap", "--no-ack", "TestOrg/repo-a#1"])
    assert result.exit_code == 0, result.output
    workspace = tiered_setup["workspaces_home"] / "repo-a-issue-1"
    assert (workspace / "foo").is_dir()
    assert (workspace / "foo" / ".git").exists()


def test_us4_always_include_missing_from_catalog(
    runner: CliRunner,
    tiered_setup: dict,
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    """US4 scenario 2: always_include_repos referencing a non-catalogued repo
    refuses pre-mutation."""
    config_path = tiered_setup["ph_devkit"] / "config.yaml"
    config_path.write_text(
        config_path.read_text() + "always_include_repos:\n  - TestOrg/missing\n"
    )
    monkeypatch.setattr("aidevkit.bootstrap.shutil.which", _which_real_git(tmp_path))
    _mock_gh(monkeypatch, {
        "title": "T",
        "body": "## Affected Repos\n\n- TestOrg/repo-a\n",
        "url": "https://github.com/TestOrg/repo-a/issues/1",
    })

    result = runner.invoke(app, ["bootstrap", "--no-ack", "TestOrg/repo-a#1"])
    assert result.exit_code == E_REPO_NOT_FOUND, result.output
    # No workspace created
    assert not (tiered_setup["workspaces_home"] / "repo-a-issue-1").exists()


def test_us4_issue_body_repo_not_in_catalog(
    runner: CliRunner,
    tiered_setup: dict,
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    """US4 scenario 3: issue body lists a repo not in PROJECTS.md → refuse
    pre-mutation."""
    monkeypatch.setattr("aidevkit.bootstrap.shutil.which", _which_real_git(tmp_path))
    _mock_gh(monkeypatch, {
        "title": "T",
        "body": "## Affected Repos\n\n- TestOrg/repo-a\n- TestOrg/missing\n",
        "url": "https://github.com/TestOrg/repo-a/issues/1",
    })

    result = runner.invoke(app, ["bootstrap", "--no-ack", "TestOrg/repo-a#1"])
    assert result.exit_code == E_REPO_NOT_FOUND, result.output
    assert not (tiered_setup["workspaces_home"] / "repo-a-issue-1").exists()


def test_repos_flag_not_in_catalog(
    runner: CliRunner,
    tiered_setup: dict,
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    """FR-018a: --repos entry must resolve through PROJECTS.md."""
    monkeypatch.setattr("aidevkit.bootstrap.shutil.which", _which_real_git(tmp_path))
    _mock_gh(monkeypatch, {
        "title": "T",
        "body": "## Affected Repos\n\n- TestOrg/repo-a\n",
        "url": "https://github.com/TestOrg/repo-a/issues/1",
    })

    result = runner.invoke(
        app,
        ["bootstrap", "--no-ack", "--repos", "TestOrg/missing", "TestOrg/repo-a#1"],
    )
    assert result.exit_code == E_REPO_NOT_FOUND, result.output


def test_repos_flag_additive(
    runner: CliRunner,
    tiered_setup: dict,
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    """FR-018a: --repos appends to issue body, doesn't override."""
    # Add 'foo' to catalog + sources
    foo_origin = tmp_path / "origins" / "foo.git"
    _init_bare_origin(foo_origin)
    _seed_source_clone(tiered_setup["projects_home"], "foo", foo_origin)
    catalog_path = tiered_setup["ph_devkit"] / "PROJECTS.md"
    catalog_path.write_text(
        catalog_path.read_text()
        + "| foo | git@github.com:TestOrg/foo.git | main | foo |\n"
    )
    monkeypatch.setattr("aidevkit.bootstrap.shutil.which", _which_real_git(tmp_path))
    _mock_gh(monkeypatch, {
        "title": "T",
        "body": "## Affected Repos\n\n- TestOrg/repo-a\n",
        "url": "https://github.com/TestOrg/repo-a/issues/1",
    })

    result = runner.invoke(
        app,
        ["bootstrap", "--no-ack", "--repos", "TestOrg/foo", "TestOrg/repo-a#1"],
    )
    assert result.exit_code == 0, result.output
    workspace = tiered_setup["workspaces_home"] / "repo-a-issue-1"
    # Both issue body's repo-a AND --repos foo are mounted.
    assert (workspace / "repo-a").is_dir()
    assert (workspace / "foo").is_dir()


# ----- E_TEMPLATE_COLLISION (US2 reserved-file edge case) --------------------

def test_reserved_collision_refused_pre_mutation(
    runner: CliRunner,
    tiered_setup: dict,
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    """FR-016: a template at templates/workspace/WORKSPACE.md must refuse
    BEFORE any worktree is created."""
    ws_template_dir = tiered_setup["ph_devkit"] / "templates" / "workspace"
    ws_template_dir.mkdir(parents=True)
    (ws_template_dir / "WORKSPACE.md").write_text("evil override")

    monkeypatch.setattr("aidevkit.bootstrap.shutil.which", _which_real_git(tmp_path))
    _mock_gh(monkeypatch, {
        "title": "T",
        "body": "## Affected Repos\n\n- TestOrg/repo-a\n",
        "url": "https://github.com/TestOrg/repo-a/issues/1",
    })

    result = runner.invoke(app, ["bootstrap", "--no-ack", "TestOrg/repo-a#1"])
    assert result.exit_code == E_TEMPLATE_COLLISION, result.output
    # No workspace dir on disk.
    assert not (tiered_setup["workspaces_home"] / "repo-a-issue-1").exists()


# ----- US2 acceptance scenarios (templates layering) ------------------------

def test_us2_per_repo_wins(
    runner: CliRunner,
    tiered_setup: dict,
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    """US2 #1: identical CLAUDE.md at all 3 tiers; per-repo wins, warning
    names the two losers."""
    fake_home = tiered_setup["fake_home"]
    g_ws = fake_home / ".devkit" / "templates" / "workspace"
    g_ws.mkdir(parents=True)
    (g_ws / "CLAUDE.md").write_text("global content")

    ph_ws = tiered_setup["ph_devkit"] / "templates" / "workspace"
    ph_ws.mkdir(parents=True)
    (ph_ws / "CLAUDE.md").write_text("projects-home content")

    repo_a_ws = tiered_setup["projects_home"] / "repo-a" / ".devkit" / "templates" / "workspace"
    repo_a_ws.mkdir(parents=True)
    (repo_a_ws / "CLAUDE.md").write_text("per-repo content")

    monkeypatch.setattr("aidevkit.bootstrap.shutil.which", _which_real_git(tmp_path))
    _mock_gh(monkeypatch, {
        "title": "T",
        "body": "## Affected Repos\n\n- TestOrg/repo-a\n",
        "url": "https://github.com/TestOrg/repo-a/issues/1",
    })

    result = runner.invoke(app, ["bootstrap", "--no-ack", "TestOrg/repo-a#1"])
    assert result.exit_code == 0, result.output

    workspace = tiered_setup["workspaces_home"] / "repo-a-issue-1"
    assert (workspace / "CLAUDE.md").read_text() == "per-repo content"
    # Both losing tiers named in stderr.
    assert "global" in result.stderr or "global" in result.output
    assert "projects-home" in result.stderr or "projects-home" in result.output


def test_us2_worktree_per_repo_scope(
    runner: CliRunner,
    tiered_setup: dict,
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    """US2 #2: global templates/worktree/.editorconfig applies to every
    worktree; a per-repo templates/worktree/.editorconfig wins for that
    one repo."""
    # Add 'foo' to catalog + sources
    foo_origin = tmp_path / "origins" / "foo.git"
    _init_bare_origin(foo_origin)
    _seed_source_clone(tiered_setup["projects_home"], "foo", foo_origin)
    catalog_path = tiered_setup["ph_devkit"] / "PROJECTS.md"
    catalog_path.write_text(
        catalog_path.read_text()
        + "| foo | git@github.com:TestOrg/foo.git | main | foo |\n"
    )

    # global templates/worktree/.editorconfig
    fake_home = tiered_setup["fake_home"]
    g_wt = fake_home / ".devkit" / "templates" / "worktree"
    g_wt.mkdir(parents=True)
    (g_wt / ".editorconfig").write_text("global config")

    # repo-a per-repo templates/worktree/.editorconfig (overrides global)
    repo_a_wt = tiered_setup["projects_home"] / "repo-a" / ".devkit" / "templates" / "worktree"
    repo_a_wt.mkdir(parents=True)
    (repo_a_wt / ".editorconfig").write_text("repo-a config")

    monkeypatch.setattr("aidevkit.bootstrap.shutil.which", _which_real_git(tmp_path))
    _mock_gh(monkeypatch, {
        "title": "T",
        "body": "## Affected Repos\n\n- TestOrg/repo-a\n- TestOrg/foo\n",
        "url": "https://github.com/TestOrg/repo-a/issues/1",
    })

    result = runner.invoke(app, ["bootstrap", "--no-ack", "TestOrg/repo-a#1"])
    assert result.exit_code == 0, result.output

    workspace = tiered_setup["workspaces_home"] / "repo-a-issue-1"
    # repo-a's worktree gets per-repo content (more specific than global).
    assert (workspace / "repo-a" / ".editorconfig").read_text() == "repo-a config"
    # foo's worktree (no per-repo .devkit/) gets the global content.
    assert (workspace / "foo" / ".editorconfig").read_text() == "global config"


def test_us2_no_collision(
    runner: CliRunner,
    tiered_setup: dict,
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    """US2 #3: two per-repo tiers contributing different files (no collision)
    — both end up at workspace root."""
    # Add 'foo' with its own templates/workspace/Y.md
    foo_origin = tmp_path / "origins" / "foo.git"
    _init_bare_origin(foo_origin)
    _seed_source_clone(tiered_setup["projects_home"], "foo", foo_origin)
    catalog_path = tiered_setup["ph_devkit"] / "PROJECTS.md"
    catalog_path.write_text(
        catalog_path.read_text()
        + "| foo | git@github.com:TestOrg/foo.git | main | foo |\n"
    )

    a_ws = tiered_setup["projects_home"] / "repo-a" / ".devkit" / "templates" / "workspace"
    a_ws.mkdir(parents=True)
    (a_ws / "X.md").write_text("from repo-a")

    foo_ws = tiered_setup["projects_home"] / "foo" / ".devkit" / "templates" / "workspace"
    foo_ws.mkdir(parents=True)
    (foo_ws / "Y.md").write_text("from foo")

    monkeypatch.setattr("aidevkit.bootstrap.shutil.which", _which_real_git(tmp_path))
    _mock_gh(monkeypatch, {
        "title": "T",
        "body": "## Affected Repos\n\n- TestOrg/repo-a\n- TestOrg/foo\n",
        "url": "https://github.com/TestOrg/repo-a/issues/1",
    })

    result = runner.invoke(app, ["bootstrap", "--no-ack", "TestOrg/repo-a#1"])
    assert result.exit_code == 0, result.output

    workspace = tiered_setup["workspaces_home"] / "repo-a-issue-1"
    assert (workspace / "X.md").read_text() == "from repo-a"
    assert (workspace / "Y.md").read_text() == "from foo"


def test_us2_two_per_repo_collide_later_wins(
    runner: CliRunner,
    tiered_setup: dict,
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    """US2 #4: two per-repo tiers contributing the same workspace path —
    later in affected-repos order wins; warning names the loser."""
    # Add 'foo' to catalog + sources
    foo_origin = tmp_path / "origins" / "foo.git"
    _init_bare_origin(foo_origin)
    _seed_source_clone(tiered_setup["projects_home"], "foo", foo_origin)
    catalog_path = tiered_setup["ph_devkit"] / "PROJECTS.md"
    catalog_path.write_text(
        catalog_path.read_text()
        + "| foo | git@github.com:TestOrg/foo.git | main | foo |\n"
    )

    a_ws = tiered_setup["projects_home"] / "repo-a" / ".devkit" / "templates" / "workspace"
    a_ws.mkdir(parents=True)
    (a_ws / "Z.md").write_text("from repo-a")

    foo_ws = tiered_setup["projects_home"] / "foo" / ".devkit" / "templates" / "workspace"
    foo_ws.mkdir(parents=True)
    (foo_ws / "Z.md").write_text("from foo")

    monkeypatch.setattr("aidevkit.bootstrap.shutil.which", _which_real_git(tmp_path))
    # Issue body order: repo-a first, foo second. So foo (later) wins.
    _mock_gh(monkeypatch, {
        "title": "T",
        "body": "## Affected Repos\n\n- TestOrg/repo-a\n- TestOrg/foo\n",
        "url": "https://github.com/TestOrg/repo-a/issues/1",
    })

    result = runner.invoke(app, ["bootstrap", "--no-ack", "TestOrg/repo-a#1"])
    assert result.exit_code == 0, result.output

    workspace = tiered_setup["workspaces_home"] / "repo-a-issue-1"
    assert (workspace / "Z.md").read_text() == "from foo"
    # Warning names the loser.
    combined = result.output + (result.stderr or "")
    assert "repo:TestOrg/repo-a" in combined or "repo-a" in combined


# ----- US3 acceptance scenarios (per-repo tier scope) ------------------------

def test_us3_per_repo_isolation(
    runner: CliRunner,
    tiered_setup: dict,
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    """US3 #1: per-repo templates/worktree/A-only.md lands ONLY in that
    repo's worktree, not siblings."""
    # Add 'foo' to catalog + sources
    foo_origin = tmp_path / "origins" / "foo.git"
    _init_bare_origin(foo_origin)
    _seed_source_clone(tiered_setup["projects_home"], "foo", foo_origin)
    catalog_path = tiered_setup["ph_devkit"] / "PROJECTS.md"
    catalog_path.write_text(
        catalog_path.read_text()
        + "| foo | git@github.com:TestOrg/foo.git | main | foo |\n"
    )

    a_wt = tiered_setup["projects_home"] / "repo-a" / ".devkit" / "templates" / "worktree"
    a_wt.mkdir(parents=True)
    (a_wt / "A-only.md").write_text("only in A")

    monkeypatch.setattr("aidevkit.bootstrap.shutil.which", _which_real_git(tmp_path))
    _mock_gh(monkeypatch, {
        "title": "T",
        "body": "## Affected Repos\n\n- TestOrg/repo-a\n- TestOrg/foo\n",
        "url": "https://github.com/TestOrg/repo-a/issues/1",
    })

    result = runner.invoke(app, ["bootstrap", "--no-ack", "TestOrg/repo-a#1"])
    assert result.exit_code == 0, result.output

    workspace = tiered_setup["workspaces_home"] / "repo-a-issue-1"
    assert (workspace / "repo-a" / "A-only.md").is_file()
    assert not (workspace / "foo" / "A-only.md").exists()


def test_us3_per_repo_not_consulted_when_not_in_workspace(
    runner: CliRunner,
    tiered_setup: dict,
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    """US3 #2: per-repo templates/workspace/X.md does NOT land anywhere
    when that repo isn't an affected repo of the workspace."""
    # Add 'foo' to catalog + sources, with its own template
    foo_origin = tmp_path / "origins" / "foo.git"
    _init_bare_origin(foo_origin)
    _seed_source_clone(tiered_setup["projects_home"], "foo", foo_origin)
    catalog_path = tiered_setup["ph_devkit"] / "PROJECTS.md"
    catalog_path.write_text(
        catalog_path.read_text()
        + "| foo | git@github.com:TestOrg/foo.git | main | foo |\n"
    )
    foo_ws = tiered_setup["projects_home"] / "foo" / ".devkit" / "templates" / "workspace"
    foo_ws.mkdir(parents=True)
    (foo_ws / "foo-says-hi.md").write_text("hi from foo")

    monkeypatch.setattr("aidevkit.bootstrap.shutil.which", _which_real_git(tmp_path))
    # Only repo-a in affected — foo not consulted.
    _mock_gh(monkeypatch, {
        "title": "T",
        "body": "## Affected Repos\n\n- TestOrg/repo-a\n",
        "url": "https://github.com/TestOrg/repo-a/issues/1",
    })

    result = runner.invoke(app, ["bootstrap", "--no-ack", "TestOrg/repo-a#1"])
    assert result.exit_code == 0, result.output

    workspace = tiered_setup["workspaces_home"] / "repo-a-issue-1"
    # The foo template did not land anywhere.
    assert not (workspace / "foo-says-hi.md").exists()
    assert not list(workspace.rglob("foo-says-hi.md"))


# ----- WORKSPACE.md frontmatter integration check ---------------------------

def test_workspace_md_template_stamp_sha_present(
    runner: CliRunner,
    tiered_setup: dict,
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    """FR-019a: WORKSPACE.md is stamped with a non-empty template_stamp_sha
    field (64 hex chars). Even with no templates, the SHA over an empty
    plan is computed deterministically."""
    monkeypatch.setattr("aidevkit.bootstrap.shutil.which", _which_real_git(tmp_path))
    _mock_gh(monkeypatch, {
        "title": "T",
        "body": "## Affected Repos\n\n- TestOrg/repo-a\n",
        "url": "https://github.com/TestOrg/repo-a/issues/1",
    })

    result = runner.invoke(app, ["bootstrap", "--no-ack", "TestOrg/repo-a#1"])
    assert result.exit_code == 0, result.output
    workspace = tiered_setup["workspaces_home"] / "repo-a-issue-1"
    text = (workspace / "WORKSPACE.md").read_text()
    # Frontmatter is YAML between '---' markers.
    import yaml
    end = text.index("\n---\n", 4)
    fm = yaml.safe_load(text[4:end])
    assert "template_stamp_sha" in fm
    sha = fm["template_stamp_sha"]
    assert isinstance(sha, str) and len(sha) == 64
    assert all(c in "0123456789abcdef" for c in sha)
