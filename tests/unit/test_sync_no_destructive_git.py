"""T010: `aidevkit.sync` source MUST NOT contain destructive git invocations.

Backs FR-013 at the source level. The module's own docstring enumerates the
forbidden tokens — strip it before scanning so the documentation doesn't
trigger its own test.
"""

from __future__ import annotations

import inspect

from aidevkit import sync as _sync

FORBIDDEN = (
    "git push",
    "push --force",
    "reset --hard",
    "git clean",
    "branch -D",
    "reflog expire",
    "--force-with-lease",
    "--force",
)


def test_sync_source_has_no_destructive_git() -> None:
    source = inspect.getsource(_sync)
    docstring = _sync.__doc__ or ""
    scanned = source.replace(docstring, "", 1)
    hits = [token for token in FORBIDDEN if token in scanned]
    assert not hits, f"forbidden destructive-git tokens found in aidevkit.sync: {hits}"
