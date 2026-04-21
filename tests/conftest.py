"""Shared fixtures for the DevKit test suite.

Hermeticity contract: no test is permitted to invoke real `git` or `gh` against
real repositories or the real GitHub API. The autouse `_fail_on_unmocked_shell`
fixture enforces this by patching `aidevkit.util.subprocess.run` — the single
import site of `subprocess` in DevKit — so any bypass of the `util.run` seam
surfaces as a loud `RuntimeError`.
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
    """A per-test throwaway directory modeled as a per-issue worktree root."""
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


@pytest.fixture(autouse=True)
def _fail_on_unmocked_shell(monkeypatch: pytest.MonkeyPatch) -> None:
    """Hermeticity guard: any real `subprocess.run` call via `util` is a violation.

    Fires when `_CAPTURE_ACTIVE` is False (no `subprocess_capture` in use) —
    this surfaces tests that trigger `util.run` without having installed the
    fixture. When `_CAPTURE_ACTIVE` is True, this still fires if something
    bypassed the `util.run` seam and reached `subprocess.run` directly.
    """
    def guard(*args: Any, **kwargs: Any) -> None:
        if _CAPTURE_ACTIVE:
            raise RuntimeError(
                "hermeticity violation: util.subprocess.run invoked despite "
                "subprocess_capture being active — something bypassed the util.run seam"
            )
        raise RuntimeError(
            "hermeticity violation: util.run called without subprocess_capture "
            "fixture active"
        )

    monkeypatch.setattr("aidevkit.util.subprocess.run", guard)
