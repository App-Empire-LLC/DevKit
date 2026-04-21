"""T009: `aidevkit.sync` must not import `subprocess` directly.

All subprocess work goes through `aidevkit.util.run`/`git` so tests have a
single monkeypatch target.
"""
from __future__ import annotations

import inspect

from aidevkit import sync as _sync


def test_sync_does_not_import_subprocess() -> None:
    source = inspect.getsource(_sync)
    assert "import subprocess" not in source
    assert "from subprocess" not in source
