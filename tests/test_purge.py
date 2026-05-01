"""Tests for `devkit purge`."""
from __future__ import annotations

import datetime
from pathlib import Path

import pytest
from typer.testing import CliRunner

from aidevkit import purge as purge_mod
from aidevkit.cli import app
from aidevkit.util import E_DEP_MISSING


@pytest.fixture
def runner(monkeypatch: pytest.MonkeyPatch) -> CliRunner:
    monkeypatch.setenv("NO_COLOR", "1")
    return CliRunner()


def _make_archived(
    home: Path,
    name: str,
    *,
    marker_text: str | None,
) -> Path:
    archived_root = home / "_archived"
    archived_root.mkdir(exist_ok=True)
    path = archived_root / name
    path.mkdir()
    if marker_text is not None:
        (path / ".devkit-archived").write_text(marker_text)
    return path


def _iso(days_ago: int) -> str:
    now = datetime.datetime.now(datetime.UTC) - datetime.timedelta(days=days_ago)
    return now.strftime("%Y-%m-%dT%H:%M:%SZ")


# --- Marker parsing -----------------------------------------------------------


def test_parse_marker_valid_timestamp(tmp_path: Path) -> None:
    marker = tmp_path / ".devkit-archived"
    marker.write_text("2026-04-22T00:00:00Z\n")
    now = datetime.datetime(2026, 5, 22, 0, 0, 0, tzinfo=datetime.UTC)
    entry = purge_mod._parse_marker(marker, now)
    assert entry.marker_error is None
    assert entry.archived_at is not None
    assert entry.age_days == 30


def test_parse_marker_date_only_accepted(tmp_path: Path) -> None:
    marker = tmp_path / ".devkit-archived"
    marker.write_text("2026-04-22\n")
    now = datetime.datetime(2026, 5, 22, tzinfo=datetime.UTC)
    entry = purge_mod._parse_marker(marker, now)
    assert entry.marker_error is None


def test_parse_marker_missing(tmp_path: Path) -> None:
    marker = tmp_path / ".devkit-archived"
    now = datetime.datetime.now(datetime.UTC)
    entry = purge_mod._parse_marker(marker, now)
    assert entry.marker_error is not None
    assert "missing" in entry.marker_error


def test_parse_marker_empty(tmp_path: Path) -> None:
    marker = tmp_path / ".devkit-archived"
    marker.write_text("")
    entry = purge_mod._parse_marker(marker, datetime.datetime.now(datetime.UTC))
    assert entry.marker_error == "marker file empty"


def test_parse_marker_unparseable(tmp_path: Path) -> None:
    marker = tmp_path / ".devkit-archived"
    marker.write_text("garbage\n")
    entry = purge_mod._parse_marker(marker, datetime.datetime.now(datetime.UTC))
    assert entry.marker_error is not None
    assert "unparseable" in entry.marker_error


def test_parse_marker_future_skew(tmp_path: Path) -> None:
    marker = tmp_path / ".devkit-archived"
    future = datetime.datetime.now(datetime.UTC) + datetime.timedelta(hours=1)
    marker.write_text(future.strftime("%Y-%m-%dT%H:%M:%SZ"))
    entry = purge_mod._parse_marker(marker, datetime.datetime.now(datetime.UTC))
    assert entry.marker_error is not None
    assert "future" in entry.marker_error


# --- CLI behavior -------------------------------------------------------------


def test_purge_dry_run_default_no_deletion(
    runner: CliRunner,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    home = tmp_path / "home"
    home.mkdir()
    old = _make_archived(home, "Old-issue-1", marker_text=_iso(40))
    young = _make_archived(home, "Young-issue-2", marker_text=_iso(5))
    monkeypatch.setenv("APP_EMPIRE_WORKTREES_HOME", str(home))

    result = runner.invoke(app, ["purge"])
    assert result.exit_code == 0, result.output
    assert old.exists()
    assert young.exists()
    assert "would purge Old-issue-1" in result.output
    assert "would purge Young-issue-2" not in result.output


def test_purge_with_yes_deletes_eligible(
    runner: CliRunner,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    home = tmp_path / "home"
    home.mkdir()
    old = _make_archived(home, "Old-issue-1", marker_text=_iso(40))
    young = _make_archived(home, "Young-issue-2", marker_text=_iso(5))
    monkeypatch.setenv("APP_EMPIRE_WORKTREES_HOME", str(home))

    result = runner.invoke(app, ["purge", "--yes"])
    assert result.exit_code == 0, result.output
    assert not old.exists()
    assert young.exists()


def test_purge_days_override(
    runner: CliRunner,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    home = tmp_path / "home"
    home.mkdir()
    week_old = _make_archived(home, "Week-issue-1", marker_text=_iso(10))
    monkeypatch.setenv("APP_EMPIRE_WORKTREES_HOME", str(home))

    result = runner.invoke(app, ["purge", "--days", "7", "--yes"])
    assert result.exit_code == 0, result.output
    assert not week_old.exists()


def test_purge_missing_marker_skipped(
    runner: CliRunner,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    home = tmp_path / "home"
    home.mkdir()
    # Very old dir, but no marker → never touched
    no_marker = _make_archived(home, "NoMarker-issue-9", marker_text=None)
    monkeypatch.setenv("APP_EMPIRE_WORKTREES_HOME", str(home))

    result = runner.invoke(app, ["purge", "--days", "0", "--yes"])
    assert result.exit_code == 0, result.output
    assert no_marker.exists()
    assert "SKIP NoMarker-issue-9" in result.output


def test_purge_unparseable_marker_skipped(
    runner: CliRunner,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    home = tmp_path / "home"
    home.mkdir()
    bad = _make_archived(home, "Bad-issue-1", marker_text="not a timestamp\n")
    monkeypatch.setenv("APP_EMPIRE_WORKTREES_HOME", str(home))

    result = runner.invoke(app, ["purge", "--days", "0", "--yes"])
    assert result.exit_code == 0, result.output
    assert bad.exists()
    assert "SKIP Bad-issue-1" in result.output


def test_purge_empty_archived_ok(
    runner: CliRunner,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    home = tmp_path / "home"
    home.mkdir()
    (home / "_archived").mkdir()
    monkeypatch.setenv("APP_EMPIRE_WORKTREES_HOME", str(home))

    result = runner.invoke(app, ["purge"])
    assert result.exit_code == 0, result.output
    assert "nothing to purge" in result.output.lower()


def test_purge_no_archived_dir_ok(
    runner: CliRunner,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    home = tmp_path / "home"
    home.mkdir()
    monkeypatch.setenv("APP_EMPIRE_WORKTREES_HOME", str(home))

    result = runner.invoke(app, ["purge"])
    assert result.exit_code == 0, result.output
    assert "nothing to purge" in result.output.lower()


def test_purge_never_touches_active_workspaces(
    runner: CliRunner,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    home = tmp_path / "home"
    home.mkdir()
    # Active workspace sitting at the root — purge must NEVER see it
    active = home / "Active-issue-100"
    active.mkdir()
    (active / "DevKit").mkdir()
    old = _make_archived(home, "Old-issue-1", marker_text=_iso(40))
    monkeypatch.setenv("APP_EMPIRE_WORKTREES_HOME", str(home))

    result = runner.invoke(app, ["purge", "--yes"])
    assert result.exit_code == 0, result.output
    assert active.exists()
    assert (active / "DevKit").exists()
    assert not old.exists()


def test_purge_missing_devkit_setup_exits_dep_missing(
    runner: CliRunner,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """DevKit#37: purge fails with E_DEP_MISSING when .devkit/ unreachable."""
    monkeypatch.delenv("APP_EMPIRE_WORKTREES_HOME", raising=False)
    monkeypatch.delenv("PROJECTS_HOME", raising=False)
    result = runner.invoke(app, ["purge"])
    assert result.exit_code == E_DEP_MISSING
