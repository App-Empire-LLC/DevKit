"""Tests for the install-method detector (`_install.detect_install_info`)."""
from __future__ import annotations

from aidevkit import _install
from aidevkit.util import RunResult


def test_detects_uv_tool(subprocess_capture) -> None:
    subprocess_capture.queue(
        RunResult(code=0, stdout="aidevkit v0.3.0\n- devkit\n", stderr="")
    )
    info = _install.detect_install_info()
    assert info.method == "uv-tool"
    assert info.installed_version == "0.3.0"
    assert info.manageable is True


def test_detects_pip(subprocess_capture) -> None:
    # uv tool list returns nothing matching
    subprocess_capture.queue(RunResult(code=0, stdout="othertool v1.0\n", stderr=""))
    subprocess_capture.queue(
        RunResult(
            code=0,
            stdout=(
                "Name: aidevkit\n"
                "Version: 0.2.0\n"
                "Location: /Users/x/.venv/lib/python3.11/site-packages\n"
            ),
            stderr="",
        )
    )
    info = _install.detect_install_info()
    assert info.method == "pip"
    assert info.installed_version == "0.2.0"
    assert info.manageable is False


def test_detects_source_when_location_not_sitepackages(subprocess_capture) -> None:
    subprocess_capture.queue(RunResult(code=0, stdout="", stderr=""))
    subprocess_capture.queue(
        RunResult(
            code=0,
            stdout=(
                "Name: aidevkit\n"
                "Version: 0.0.0+unknown\n"
                "Location: /Users/x/code/DevKit/src\n"
            ),
            stderr="",
        )
    )
    info = _install.detect_install_info()
    assert info.method == "source"
    assert info.manageable is False


def test_detects_unknown_when_neither(subprocess_capture) -> None:
    subprocess_capture.queue(RunResult(code=0, stdout="", stderr=""))
    subprocess_capture.queue(RunResult(code=1, stdout="", stderr="not found"))
    info = _install.detect_install_info()
    assert info.method == "unknown"
    assert info.installed_version is None
    assert info.manageable is False
