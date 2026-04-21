"""Unit test fixtures — hermetic monkeypatch of the canonical shell seam."""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable, Optional, Union

import pytest

from aidevkit import util as _util
from aidevkit.util import RunResult

Cmd = tuple[str, ...]
# Either a static RunResult, a factory that returns one, or a sequence consumed
# in FIFO order for multiple calls with the same (cmd, cwd).
ScriptedValue = Union[RunResult, Callable[[Cmd, Optional[Path]], RunResult], list]


@dataclass
class FakeRun:
    scripts: dict[tuple[Cmd, Optional[Path]], ScriptedValue] = field(default_factory=dict)
    calls: list[tuple[Cmd, Optional[Path]]] = field(default_factory=list)
    default_factory: Optional[Callable[[Cmd, Optional[Path]], RunResult]] = None

    def script(
        self,
        cmd: Cmd,
        cwd: Optional[Path],
        result: Union[RunResult, list[RunResult]],
    ) -> None:
        self.scripts[(cmd, cwd)] = result

    def script_any_cwd(self, cmd: Cmd, result: RunResult) -> None:
        self.scripts[(cmd, None)] = result

    def __call__(
        self,
        cmd: list[str],
        *,
        check: bool = False,
        cwd: Optional[Path] = None,
    ) -> RunResult:
        key = (tuple(cmd), cwd)
        self.calls.append(key)
        if key in self.scripts:
            value = self.scripts[key]
        elif (tuple(cmd), None) in self.scripts:
            value = self.scripts[(tuple(cmd), None)]
        elif self.default_factory is not None:
            return self.default_factory(tuple(cmd), cwd)
        else:
            raise AssertionError(
                f"fake_run: unscripted call {cmd!r} in cwd={cwd!r}. "
                f"Script it via fake_run.script(...)"
            )
        if callable(value):
            return value(tuple(cmd), cwd)
        if isinstance(value, list):
            if not value:
                raise AssertionError(f"fake_run: script queue exhausted for {cmd!r}")
            return value.pop(0)
        return value


@pytest.fixture
def fake_run(monkeypatch: pytest.MonkeyPatch) -> FakeRun:
    """Monkeypatches `aidevkit.util.run` with a programmable dispatch table.

    Unmatched calls raise AssertionError — fail-loud default.
    """
    fr = FakeRun()
    monkeypatch.setattr(_util, "run", fr)
    return fr
