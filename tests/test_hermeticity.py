"""Meta-tests that validate the hermeticity guard itself."""
from __future__ import annotations

import pytest

import aidevkit.util as util


def test_guard_fires_when_util_run_called_without_capture() -> None:
    """Without `subprocess_capture`, any util.run call must raise from the guard.

    This proves SC-005 / FR-012 / FR-014 at the structural level: a test that
    forgets to install `subprocess_capture` can't accidentally reach the
    network or shell.
    """
    with pytest.raises(RuntimeError, match="hermeticity violation"):
        util.run(["echo", "this-should-never-execute"])


def test_guard_passes_through_when_capture_active(subprocess_capture) -> None:
    """With `subprocess_capture`, util.run is replaced and the guard stays silent."""
    result = util.run(["git", "status"])
    assert result.code == 0
    assert subprocess_capture.calls[-1]["cmd"] == ["git", "status"]
