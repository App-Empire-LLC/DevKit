"""Unit tests for the issue-authoring standard-path resolver.

Covers spec 001-review-issue-standard-path (DevKit#52):
- FR-001: default-location resolution at the new path.
- FR-003: strict env-var / config precedence (no fallback after a higher source is set).
- FR-005: single-resolution invariant per CLI invocation.
- FR-006: relative + absolute override path handling.
- FR-007: failure messages name both the attempted path AND the source.
- SC-005: existing env-var test hook continues to work post-rename.

Hermetic: pytest's `monkeypatch.chdir` / `monkeypatch.setenv` keep these tests
isolated from real filesystem state. The autouse `_clear_resolver_env` fixture
guarantees a clean env-var baseline.
"""
from __future__ import annotations

from pathlib import Path
from typing import Callable

import pytest
import typer

from aidevkit import review_issue
from aidevkit.config import ReviewIssueConfig
from aidevkit.review_issue import (
    StandardPathSource,
    _resolve_issue_authoring_standard_path,
)
from aidevkit.util import E_CONFIG_INVALID

REL = "appire_docs/docs/engineering/standards/issue_authoring.md"


def _make_default_standard(base: Path) -> Path:
    """Materialise the standard at the canonical default sub-path under ``base``."""
    standard = base / REL
    standard.parent.mkdir(parents=True, exist_ok=True)
    standard.write_text("# Issue Authoring (stub)\n")
    return standard


@pytest.fixture(autouse=True)
def _clear_resolver_env(monkeypatch: pytest.MonkeyPatch) -> None:
    """Ensure the resolver's env-var hook is unset by default for each test."""
    monkeypatch.delenv("DEVKIT_REVIEW_ISSUE_STANDARD_PATH", raising=False)


# --------------------------------------------------------------------------- #
# T005–T008: US1 default-search behavior + env-var backward compat
# --------------------------------------------------------------------------- #


def test_default_search_finds_at_cwd_appire_docs(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Default resolver hits ``<cwd>/appire_docs/.../issue_authoring.md`` (FR-001)."""
    standard = _make_default_standard(tmp_path)
    monkeypatch.chdir(tmp_path)
    path, source = _resolve_issue_authoring_standard_path(ReviewIssueConfig())
    assert path == standard.resolve()
    assert source is StandardPathSource.DEFAULT


def test_default_search_falls_back_to_cwd_parent(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """When cwd has no standard, resolver searches ``<cwd>/..`` next."""
    standard = _make_default_standard(tmp_path)
    nested = tmp_path / "subdir"
    nested.mkdir()
    monkeypatch.chdir(nested)
    path, source = _resolve_issue_authoring_standard_path(ReviewIssueConfig())
    assert path == standard.resolve()
    assert source is StandardPathSource.DEFAULT


def test_default_search_both_missing_raises_with_default_source_label(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    """Both default locations absent → typer.Exit + source label + both paths in err."""
    nested = tmp_path / "deep" / "nested"
    nested.mkdir(parents=True)
    monkeypatch.chdir(nested)
    with pytest.raises(typer.Exit) as excinfo:
        _resolve_issue_authoring_standard_path(ReviewIssueConfig())
    assert excinfo.value.exit_code == E_CONFIG_INVALID
    err = capsys.readouterr().err
    assert "Issue-authoring standard not found" in err
    assert StandardPathSource.DEFAULT.value in err
    assert str(nested / REL) in err
    assert str(nested.parent / REL) in err


def test_env_var_hook_still_works_post_rename(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """SC-005: existing env-var test hook continues to work after the rename."""
    standard = tmp_path / "anywhere.md"
    standard.write_text("# Stub\n")
    monkeypatch.setenv("DEVKIT_REVIEW_ISSUE_STANDARD_PATH", str(standard))
    monkeypatch.chdir(tmp_path)
    path, source = _resolve_issue_authoring_standard_path(ReviewIssueConfig())
    assert path == standard.resolve()
    assert source is StandardPathSource.ENV_VAR


# --------------------------------------------------------------------------- #
# T020–T021: US2 config-override happy path + (US3 flips T021 → strict)
# --------------------------------------------------------------------------- #


def test_resolver_uses_config_override_when_set(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """FR-002: config.standard_path is honored when it points at an existing file."""
    override = tmp_path / "custom-standard.md"
    override.write_text("# Custom\n")
    config = ReviewIssueConfig(
        standard_path=override, source_config_path=tmp_path / "config.yaml"
    )
    monkeypatch.chdir(tmp_path)
    path, source = _resolve_issue_authoring_standard_path(config)
    assert path == override.resolve()
    assert source is StandardPathSource.CONFIG


# --------------------------------------------------------------------------- #
# T027–T030: US3 strict precedence + source labels
# --------------------------------------------------------------------------- #


def test_env_var_strict_precedence_missing_file_raises(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    """FR-003: env-var path missing → command fails, does NOT fall back (R1)."""
    # Set up a valid default standard so we can prove it's NOT consulted.
    _make_default_standard(tmp_path)
    monkeypatch.chdir(tmp_path)
    bogus = tmp_path / "does_not_exist.md"
    monkeypatch.setenv("DEVKIT_REVIEW_ISSUE_STANDARD_PATH", str(bogus))
    with pytest.raises(typer.Exit) as excinfo:
        _resolve_issue_authoring_standard_path(ReviewIssueConfig())
    assert excinfo.value.exit_code == E_CONFIG_INVALID
    err = capsys.readouterr().err
    assert str(bogus) in err
    assert StandardPathSource.ENV_VAR.value in err
    # Strict precedence: the default-source label MUST NOT appear (no fallback).
    assert StandardPathSource.DEFAULT.value not in err


def test_config_strict_precedence_missing_file_raises(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    """Config-path missing → command fails with config source label, no fallback."""
    # Default standard exists to prove it's NOT consulted (strict).
    _make_default_standard(tmp_path)
    monkeypatch.chdir(tmp_path)
    bogus = tmp_path / "missing-override.md"
    config_file = tmp_path / "fake-config.yaml"
    config_file.write_text("review_issue:\n  standard_path: missing-override.md\n")
    config = ReviewIssueConfig(standard_path=bogus, source_config_path=config_file)
    with pytest.raises(typer.Exit) as excinfo:
        _resolve_issue_authoring_standard_path(config)
    assert excinfo.value.exit_code == E_CONFIG_INVALID
    err = capsys.readouterr().err
    assert str(bogus) in err
    assert "config field review_issue.standard_path" in err
    assert str(config_file) in err  # source path is named in the label
    assert StandardPathSource.DEFAULT.value not in err  # no fallback


def test_config_strict_precedence_no_fallback_to_default(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    """T030 (replaces the earlier chain-fallback expectation): config-missing must
    NOT silently fall through to the default search, even when default exists."""
    _make_default_standard(tmp_path)  # default IS present
    monkeypatch.chdir(tmp_path)
    config = ReviewIssueConfig(
        standard_path=tmp_path / "nope.md", source_config_path=tmp_path / "c.yaml"
    )
    with pytest.raises(typer.Exit):
        _resolve_issue_authoring_standard_path(config)
    # The command failed at the config-source level — that's the strict-
    # precedence contract. Default was never consulted.
    assert StandardPathSource.DEFAULT.value not in capsys.readouterr().err


def test_default_search_error_includes_source_label(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    """Default-search failure includes the DEFAULT source label."""
    nested = tmp_path / "nowhere" / "deeper"
    nested.mkdir(parents=True)
    monkeypatch.chdir(nested)
    with pytest.raises(typer.Exit):
        _resolve_issue_authoring_standard_path(ReviewIssueConfig())
    err = capsys.readouterr().err
    assert StandardPathSource.DEFAULT.value in err
    # Both attempted paths are listed
    assert str(nested / REL) in err
    assert str(nested.parent / REL) in err


def test_resolver_returns_path_and_source_tuple(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The resolver always returns (Path, StandardPathSource) on success."""
    # Branch A: env var
    env_target = tmp_path / "env.md"
    env_target.write_text("# env\n")
    monkeypatch.setenv("DEVKIT_REVIEW_ISSUE_STANDARD_PATH", str(env_target))
    result = _resolve_issue_authoring_standard_path(ReviewIssueConfig())
    assert isinstance(result, tuple) and len(result) == 2
    assert isinstance(result[0], Path)
    assert isinstance(result[1], StandardPathSource)
    monkeypatch.delenv("DEVKIT_REVIEW_ISSUE_STANDARD_PATH")

    # Branch B: config
    cfg_target = tmp_path / "cfg.md"
    cfg_target.write_text("# cfg\n")
    config = ReviewIssueConfig(
        standard_path=cfg_target, source_config_path=tmp_path / "c.yaml"
    )
    result = _resolve_issue_authoring_standard_path(config)
    assert result == (cfg_target.resolve(), StandardPathSource.CONFIG)

    # Branch C: default
    default_target = _make_default_standard(tmp_path)
    monkeypatch.chdir(tmp_path)
    result = _resolve_issue_authoring_standard_path(ReviewIssueConfig())
    assert result == (default_target.resolve(), StandardPathSource.DEFAULT)


# --------------------------------------------------------------------------- #
# T031b: FR-005 single-resolution invariant per CLI invocation
# --------------------------------------------------------------------------- #


def _patched_resolver_counter(
    monkeypatch: pytest.MonkeyPatch,
) -> Callable[[], int]:
    """Wrap _resolve_issue_authoring_standard_path with a call counter."""
    original = review_issue._resolve_issue_authoring_standard_path
    call_count = {"n": 0}

    def _wrapper(config: ReviewIssueConfig):
        call_count["n"] += 1
        return original(config)

    monkeypatch.setattr(
        review_issue,
        "_resolve_issue_authoring_standard_path",
        _wrapper,
    )
    return lambda: call_count["n"]


def test_resolver_invoked_exactly_once_per_inspect_run(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    subprocess_capture,  # noqa: ANN001 — fixture from top-level conftest
) -> None:
    """FR-005: a single `inspect` invocation MUST resolve the standard exactly once."""
    # Stub the standard via env var (cheap, hermetic).
    standard = tmp_path / "issue_authoring.md"
    standard.write_text("# stub\n")
    monkeypatch.setenv("DEVKIT_REVIEW_ISSUE_STANDARD_PATH", str(standard))

    # Mock gh issue view to return a minimal valid envelope.
    import json as _json

    from aidevkit.util import RunResult

    issue = {
        "number": 1,
        "url": "https://github.com/o/r/issues/1",
        "title": "T",
        "body": "## Summary\nx\n",
        "labels": [],
        "assignees": [],
        "milestone": None,
        "projectItems": [],
        "comments": [],
    }
    subprocess_capture.set_default(
        RunResult(code=0, stdout=_json.dumps(issue), stderr="")
    )

    get_count = _patched_resolver_counter(monkeypatch)
    review_issue.cmd_review_issue_inspect("o/r#1", reviewer_id=None)
    assert get_count() == 1


def test_resolver_invoked_exactly_once_per_post_run(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    subprocess_capture,  # noqa: ANN001
) -> None:
    """FR-005: a single `post` invocation MUST resolve the standard exactly once."""
    import io
    import json as _json

    from aidevkit.util import RunResult

    standard = tmp_path / "issue_authoring.md"
    standard.write_text("# stub\n")
    monkeypatch.setenv("DEVKIT_REVIEW_ISSUE_STANDARD_PATH", str(standard))

    issue = {
        "number": 1,
        "url": "https://github.com/o/r/issues/1",
        "title": "T",
        "body": "## Summary\nx\n",
        "labels": [],
        "assignees": [],
        "milestone": None,
        "projectItems": [],
        "comments": [],
    }
    subprocess_capture.set_default(
        RunResult(code=0, stdout=_json.dumps(issue), stderr="")
    )
    monkeypatch.setattr(
        "sys.stdin",
        io.StringIO(_json.dumps({"schema_version": "1", "findings": []})),
    )

    get_count = _patched_resolver_counter(monkeypatch)
    review_issue.cmd_review_issue_post(
        "o/r#1",
        reviewer_id=None,
        dry_run=True,
        json_output=False,
        verbose=False,
        min_severity="warning",
    )
    assert get_count() == 1
