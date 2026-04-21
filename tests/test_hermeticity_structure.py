"""Structural backup detector for FR-005 / DevKit#29.

Walks every `src/aidevkit/**/*.py` file, collects all top-level and nested
`import subprocess` / `from subprocess import ...` statements, and fails if
any live outside the designated seam (`src/aidevkit/util.py`).

This is a belt-and-suspenders check complementing the ruff TID251 rule
configured in `pyproject.toml`. If the lint rule ever gets disabled or
misconfigured, this test still fails on a direct-subprocess bypass.
"""
from __future__ import annotations

import ast
from pathlib import Path

SRC_ROOT = Path(__file__).resolve().parent.parent / "src" / "aidevkit"
SEAM = SRC_ROOT / "util.py"


def _uses_subprocess(node: ast.AST) -> bool:
    if isinstance(node, ast.Import):
        return any(
            alias.name == "subprocess" or alias.name.startswith("subprocess.")
            for alias in node.names
        )
    if isinstance(node, ast.ImportFrom):
        mod = node.module or ""
        return mod == "subprocess" or mod.startswith("subprocess.")
    return False


def test_no_subprocess_imports_outside_seam() -> None:
    violations: list[tuple[str, int]] = []
    for py_file in SRC_ROOT.rglob("*.py"):
        if py_file.resolve() == SEAM.resolve():
            continue
        tree = ast.parse(py_file.read_text(), filename=str(py_file))
        for node in ast.walk(tree):
            if _uses_subprocess(node):
                rel = py_file.relative_to(SRC_ROOT.parent.parent)
                violations.append((str(rel), node.lineno))
    assert not violations, (
        f"Hermeticity violation: {len(violations)} file(s) import `subprocess` outside the seam "
        f"({SEAM.relative_to(SRC_ROOT.parent.parent)}). Use aidevkit.util.run instead.\n"
        f"Violations: {violations}"
    )
