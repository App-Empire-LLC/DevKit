"""Shared fixtures for the DevKit test suite.

Hermeticity contract: no test is permitted to invoke real `git` or `gh` against
real repositories or the real GitHub API. The autouse `_fail_on_unmocked_shell`
fixture enforces this by patching `aidevkit.util._runner.run` — the
instance-scoped shell seam introduced for DevKit#29 — so any bypass of the
`util.run` wrapper surfaces as a loud `RuntimeError`. Patching the instance
(rather than a module-level `subprocess.run` reference) keeps the guard
isolated from the global `subprocess` module; integration-test fixtures that
call `subprocess.run` directly are unaffected.
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Callable

import pytest

from aidevkit.util import RunResult

_CAPTURE_ACTIVE: bool = False


class SubprocessRecorder:
    """Records calls routed through `aidevkit.util.run` during a test.

    Configure responses via `set_default` (one fallback) or `queue`
    (FIFO queue, consumed one per call; falls back to the default when empty).
    Inspect recorded invocations via `.calls` — each entry is a dict with
    keys `cmd`, `cwd`, `check`.
    """

    def __init__(self) -> None:
        self.calls: list[dict[str, Any]] = []
        self._queue: list[RunResult] = []
        self._default: RunResult = RunResult(code=0, stdout="", stderr="")

    def set_default(self, result: RunResult) -> None:
        self._default = result

    def queue(self, result: RunResult) -> None:
        self._queue.append(result)

    def __call__(
        self,
        cmd: list[str],
        *,
        check: bool = False,
        cwd: Path | None = None,
    ) -> RunResult:
        self.calls.append({"cmd": list(cmd), "cwd": cwd, "check": check})
        if self._queue:
            return self._queue.pop(0)
        return self._default


@pytest.fixture
def subprocess_capture(monkeypatch: pytest.MonkeyPatch) -> Any:
    """Replace `aidevkit.util.run` with a recorder for the duration of the test.

    Since `util.git` and `util.gh` delegate to `util.run`, patching at this
    single seam captures all intended shell invocations without needing to
    patch each wrapper separately.
    """
    global _CAPTURE_ACTIVE
    recorder = SubprocessRecorder()
    monkeypatch.setattr("aidevkit.util.run", recorder)
    _CAPTURE_ACTIVE = True
    try:
        yield recorder
    finally:
        _CAPTURE_ACTIVE = False


@pytest.fixture
def tmp_workspace(tmp_path: Path) -> Path:
    """A per-test throwaway directory modeled as a per-issue workspace root."""
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    return workspace


@pytest.fixture
def gh_response() -> Callable[[str], dict[str, Any]]:
    """Factory that loads a canned `gh` response payload by filename stem.

    Example: `gh_response("issue_with_affected_repos")` returns the parsed
    dict from `tests/fixtures/issue_with_affected_repos.json`.
    """
    fixtures_dir = Path(__file__).parent / "fixtures"

    def _load(name: str) -> dict[str, Any]:
        path = fixtures_dir / f"{name}.json"
        with path.open() as f:
            return json.load(f)

    return _load


@pytest.fixture
def devkit_setup(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> Callable[[Path], None]:
    """Configure $PROJECTS_HOME → tmp_path/.devkit/{config.yaml,PROJECTS.md}
    and a fake HOME with no global .devkit/. Pass an existing workspaces_home
    Path; the helper writes a minimal valid config that points at it.

    DevKit#37: replaces the legacy ``APP_EMPIRE_WORKTREES_HOME`` /
    ``APP_EMPIRE_PROJECTS`` env-var setup used by pre-#37 tests.
    """
    def _setup(workspaces_home: Path, projects_home: Path | None = None) -> None:
        ph = projects_home or (tmp_path / "_devkit_projects")
        ph.mkdir(parents=True, exist_ok=True)
        fake_home = tmp_path / "_devkit_fake_home"
        fake_home.mkdir(exist_ok=True)
        devkit_dir = ph / ".devkit"
        devkit_dir.mkdir(exist_ok=True)
        (devkit_dir / "config.yaml").write_text(
            f"version: 1\norg: TestOrg\nworkspaces_home: {workspaces_home}\n"
        )
        (devkit_dir / "PROJECTS.md").write_text(
            "# Projects\n\n"
            "| name | git_url | description |\n|------|---------|-------------|\n"
            "| placeholder | git@github.com:TestOrg/placeholder.git | x |\n"
        )
        monkeypatch.setenv("PROJECTS_HOME", str(ph))
        monkeypatch.setattr("pathlib.Path.home", classmethod(lambda cls: fake_home))
        monkeypatch.setattr(
            "aidevkit.config._GLOBAL_CONFIG_PATH",
            fake_home / ".devkit" / "config.yaml",
        )
        monkeypatch.delenv("APP_EMPIRE_WORKTREES_HOME", raising=False)
        monkeypatch.delenv("APP_EMPIRE_PROJECTS", raising=False)
        # Reset cli.py org-cache between tests
        from aidevkit import cli as _cli
        if hasattr(_cli._resolve_org_lazy, "_cached"):
            delattr(_cli._resolve_org_lazy, "_cached")

    return _setup


@pytest.fixture(autouse=True)
def _legacy_env_compat(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path_factory: pytest.TempPathFactory,
    request: pytest.FixtureRequest,
) -> None:
    """DevKit#37 test-compat shim.

    Pre-#37 tests set ``APP_EMPIRE_WORKTREES_HOME`` to point at a fake
    workspaces dir. The new code reads ``workspaces_home`` from
    ``$PROJECTS_HOME/.devkit/config.yaml`` and never consults the legacy
    env var. Rather than touch every old test, this autouse fixture
    intercepts ``setenv``: when a test sets ``APP_EMPIRE_WORKTREES_HOME``,
    we also seed a fresh ``.devkit/`` whose ``workspaces_home`` field
    points at the same dir.

    Integration tests under ``tests/integration/`` opt out — they manage
    ``$PROJECTS_HOME`` themselves.
    """
    if any(part == "integration" for part in request.node.path.parts):
        return

    real_setenv = monkeypatch.setenv

    seed_dir = tmp_path_factory.mktemp("_legacy_compat_devkit", numbered=True)
    fake_home = tmp_path_factory.mktemp("_legacy_compat_home", numbered=True)
    devkit_dir = seed_dir / ".devkit"
    devkit_dir.mkdir()
    (devkit_dir / "PROJECTS.md").write_text(
        "# Projects\n\n"
        "| name | git_url | description |\n|------|---------|-------------|\n"
        "| placeholder | git@github.com:TestOrg/placeholder.git | x |\n"
    )

    state: dict[str, str] = {}

    def _rewrite_devkit() -> None:
        if "APP_EMPIRE_WORKTREES_HOME" not in state:
            return
        target_dir = Path(state.get("APP_EMPIRE_PROJECTS", str(seed_dir)))
        target_devkit = target_dir / ".devkit"
        target_devkit.mkdir(parents=True, exist_ok=True)
        (target_devkit / "config.yaml").write_text(
            f"version: 1\norg: TestOrg\n"
            f"workspaces_home: {state['APP_EMPIRE_WORKTREES_HOME']}\n"
        )
        if not (target_devkit / "PROJECTS.md").exists():
            (target_devkit / "PROJECTS.md").write_text(
                "# Projects\n\n"
                "| name | git_url | description |\n|------|---------|-------------|\n"
                "| placeholder | git@github.com:TestOrg/placeholder.git | x |\n"
            )
        real_setenv("PROJECTS_HOME", str(target_dir))
        from aidevkit import cli as _cli
        if hasattr(_cli._resolve_org_lazy, "_cached"):
            delattr(_cli._resolve_org_lazy, "_cached")

    def patched_setenv(name: str, value: str, *args: object, **kwargs: object) -> None:
        real_setenv(name, value, *args, **kwargs)
        if name in ("APP_EMPIRE_WORKTREES_HOME", "APP_EMPIRE_PROJECTS"):
            state[name] = value
            _rewrite_devkit()

    monkeypatch.setattr(monkeypatch, "setenv", patched_setenv)

    # Only redirect Path.home() when the test hasn't set $HOME itself —
    # tests like test_setup deliberately set HOME and expect that to flow
    # through.
    import os as _os

    def _home_resolver(cls):
        env_home = _os.environ.get("HOME")
        if env_home:
            return Path(env_home)
        return fake_home

    monkeypatch.setattr("pathlib.Path.home", classmethod(_home_resolver))
    monkeypatch.setattr(
        "aidevkit.config._GLOBAL_CONFIG_PATH",
        fake_home / ".devkit" / "config.yaml",
    )


@pytest.fixture(autouse=True)
def _fail_on_unmocked_shell(
    request: pytest.FixtureRequest,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Hermeticity guard: any real shell call via `util` is a violation.

    Fires when `_CAPTURE_ACTIVE` is False (no `subprocess_capture` in use) —
    this surfaces tests that trigger `util.run` without having installed the
    fixture. When `_CAPTURE_ACTIVE` is True, this still fires if something
    bypassed the `util.run` seam and reached the runner directly.

    Scope: unit tests only. Integration tests under `tests/integration/` drive
    the real `git` binary against tempdir fixtures and legitimately route
    through `util.run`, so the guard is not installed there. (Per DevKit#29,
    this replaces the tree-wide no-op override that previously lived in
    `tests/integration/conftest.py`.)

    Patches `aidevkit.util._runner.run` (instance attribute) rather than the
    global `subprocess.run` — see module docstring.
    """
    if any(part == "integration" for part in request.node.path.parts):
        return

    def guard(*args: Any, **kwargs: Any) -> None:
        if _CAPTURE_ACTIVE:
            raise RuntimeError(
                "hermeticity violation: util._runner.run invoked despite "
                "subprocess_capture being active — something bypassed the util.run seam"
            )
        raise RuntimeError(
            "hermeticity violation: util.run called without subprocess_capture "
            "fixture active"
        )

    monkeypatch.setattr("aidevkit.util._runner.run", guard)
