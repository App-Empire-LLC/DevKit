"""Regression guard for SC-005 / FR-001: runner-scope isolation.

Patching `aidevkit.util._runner.run` must affect `util.run` callers but MUST
NOT leak into the global `subprocess` module. If a future refactor ever
reverts to patching `aidevkit.util.subprocess.run` (module-global), direct
`subprocess.run` callers would start failing — and this test would catch it.
"""
from __future__ import annotations

import subprocess

import pytest

from aidevkit import util


def test_runner_scope_is_isolated_from_global_subprocess(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def fail(*args, **kwargs):
        raise RuntimeError("runner-scoped stub fired")

    monkeypatch.setattr("aidevkit.util._runner.run", fail)

    with pytest.raises(RuntimeError, match="runner-scoped stub fired"):
        util.run(["echo", "hi"])

    proc = subprocess.run(["echo", "direct-ok"], capture_output=True, text=True)
    assert proc.returncode == 0
    assert proc.stdout.strip() == "direct-ok"
