"""Tests for ``aidevkit.refresh_issue_meta`` (DevKit#39).

Spec: ``specs/001-refresh-issue-meta/spec.md`` in the per-issue workspace.
All shell I/O is captured through the ``subprocess_capture`` fixture from
``conftest.py`` (the hermeticity-guarded ``aidevkit.util.run`` seam).
"""
from __future__ import annotations

import json
import os
import shutil
from pathlib import Path

import pytest

from aidevkit import refresh_issue_meta as rim
from aidevkit.util import RunResult

_FIXTURES = Path(__file__).parent / "fixtures" / "workspace_md"
_VALID = _FIXTURES / "valid.md"
_MALFORMED_NO_CLOSE = _FIXTURES / "malformed_no_close.md"
_MALFORMED_MISSING_FIELD = _FIXTURES / "malformed_missing_field.md"

# Title and URL as they appear in valid.md — kept here as constants so a
# fixture rename doesn't silently desync the tests.
_FIXTURE_TITLE = (
    "devkit refresh-issue-meta — re-fetch issue title into WORKSPACE.md"
)
_FIXTURE_URL = "https://github.com/App-Empire-LLC/DevKit/issues/39"


def _queue_gh(subprocess_capture, *, title: str, url: str) -> None:
    """Convenience: queue a single fake `gh issue view --json title,url` response."""
    subprocess_capture.queue(
        RunResult(code=0, stdout=json.dumps({"title": title, "url": url}), stderr="")
    )


def _stage_workspace(tmp_workspace: Path, fixture: Path = _VALID) -> Path:
    """Copy a fixture into ``tmp_workspace/WORKSPACE.md`` and return the workspace path."""
    shutil.copy(fixture, tmp_workspace / "WORKSPACE.md")
    return tmp_workspace


# ---------------------------------------------------------------------------
# T011 — _parse_workspace_md
# ---------------------------------------------------------------------------


class TestParseWorkspaceMd:
    def test_parses_valid_fixture(self) -> None:
        text = _VALID.read_text(encoding="utf-8")
        owner_repo, number, title, url = rim._parse_workspace_md(text)
        assert owner_repo == "App-Empire-LLC/DevKit"
        assert number == 39
        assert title == _FIXTURE_TITLE
        assert url == _FIXTURE_URL

    def test_raises_on_missing_close_delimiter(self) -> None:
        text = _MALFORMED_NO_CLOSE.read_text(encoding="utf-8")
        with pytest.raises(
            rim.WorkspaceMalformedError, match=r"(?i)delimiter|frontmatter"
        ):
            rim._parse_workspace_md(text)

    def test_raises_on_missing_field(self) -> None:
        text = _MALFORMED_MISSING_FIELD.read_text(encoding="utf-8")
        with pytest.raises(rim.WorkspaceMalformedError, match=r"issue_number"):
            rim._parse_workspace_md(text)


# ---------------------------------------------------------------------------
# T012, T017, T018, T020, T021 — refresh() behavior matrix
# ---------------------------------------------------------------------------


class TestRefresh:
    def test_title_drift_updates_only_title_line(
        self, tmp_workspace: Path, subprocess_capture
    ) -> None:
        """T012 (US1) — title-only drift rewrites exactly one line."""
        _stage_workspace(tmp_workspace)
        original_bytes = (tmp_workspace / "WORKSPACE.md").read_bytes()
        listing_before = sorted(os.listdir(tmp_workspace))

        _queue_gh(subprocess_capture, title="UPDATED TITLE", url=_FIXTURE_URL)

        result = rim.refresh(tmp_workspace)

        assert result.title_changed is True
        assert result.url_changed is False
        assert result.old_title == _FIXTURE_TITLE
        assert result.new_title == "UPDATED TITLE"
        assert result.old_url == _FIXTURE_URL
        assert result.new_url == _FIXTURE_URL

        new_bytes = (tmp_workspace / "WORKSPACE.md").read_bytes()
        old_lines = original_bytes.decode("utf-8").splitlines()
        new_lines = new_bytes.decode("utf-8").splitlines()
        assert len(old_lines) == len(new_lines), "line count must be preserved"
        diff_lines = [
            (idx, a, b)
            for idx, (a, b) in enumerate(zip(old_lines, new_lines))
            if a != b
        ]
        assert len(diff_lines) == 1, f"expected one changed line, got: {diff_lines}"
        idx, _old, new = diff_lines[0]
        assert new.startswith("issue_title:")

        # Parse the new file to confirm it round-trips and reports the new title.
        _, _, parsed_title, parsed_url = rim._parse_workspace_md(
            new_bytes.decode("utf-8")
        )
        assert parsed_title == "UPDATED TITLE"
        assert parsed_url == _FIXTURE_URL

        # FR-007: no other file was created or modified in the workspace.
        assert sorted(os.listdir(tmp_workspace)) == listing_before

    def test_no_op_when_in_sync(
        self, tmp_workspace: Path, subprocess_capture
    ) -> None:
        """T017 (US2) — byte-identical when nothing drifted (SC-002)."""
        _stage_workspace(tmp_workspace)
        workspace_md = tmp_workspace / "WORKSPACE.md"
        original_bytes = workspace_md.read_bytes()
        original_mtime = workspace_md.stat().st_mtime_ns

        _queue_gh(subprocess_capture, title=_FIXTURE_TITLE, url=_FIXTURE_URL)

        result = rim.refresh(tmp_workspace)

        assert result.any_changed is False
        assert workspace_md.read_bytes() == original_bytes
        assert workspace_md.stat().st_mtime_ns == original_mtime

    def test_round_trip_stability(
        self, tmp_workspace: Path, subprocess_capture
    ) -> None:
        """T018 (US2) — second invocation is a true no-op (FR-012, SC-004)."""
        _stage_workspace(tmp_workspace)
        workspace_md = tmp_workspace / "WORKSPACE.md"

        _queue_gh(subprocess_capture, title="REFRESHED TITLE", url=_FIXTURE_URL)
        first = rim.refresh(tmp_workspace)
        assert first.title_changed is True
        first_bytes = workspace_md.read_bytes()
        first_mtime = workspace_md.stat().st_mtime_ns

        _queue_gh(subprocess_capture, title="REFRESHED TITLE", url=_FIXTURE_URL)
        second = rim.refresh(tmp_workspace)

        assert second.any_changed is False
        assert workspace_md.read_bytes() == first_bytes
        assert workspace_md.stat().st_mtime_ns == first_mtime

    def test_url_drift_updates_only_url_line(
        self, tmp_workspace: Path, subprocess_capture
    ) -> None:
        """T020 (US3) — URL-only drift rewrites exactly one line."""
        _stage_workspace(tmp_workspace)
        original_bytes = (tmp_workspace / "WORKSPACE.md").read_bytes()

        new_url = "https://github.com/App-Empire-LLC/devkit-renamed/issues/39"
        _queue_gh(subprocess_capture, title=_FIXTURE_TITLE, url=new_url)

        result = rim.refresh(tmp_workspace)

        assert result.title_changed is False
        assert result.url_changed is True
        assert result.new_url == new_url

        new_bytes = (tmp_workspace / "WORKSPACE.md").read_bytes()
        old_lines = original_bytes.decode("utf-8").splitlines()
        new_lines = new_bytes.decode("utf-8").splitlines()
        diff_lines = [
            (idx, a, b)
            for idx, (a, b) in enumerate(zip(old_lines, new_lines))
            if a != b
        ]
        assert len(diff_lines) == 1
        assert diff_lines[0][2].startswith("issue_url:")

    def test_both_fields_drift_updates_both_lines(
        self, tmp_workspace: Path, subprocess_capture
    ) -> None:
        """T021 (US3) — both fields drift updates exactly two lines (SC-003)."""
        _stage_workspace(tmp_workspace)
        original_bytes = (tmp_workspace / "WORKSPACE.md").read_bytes()

        new_url = "https://github.com/App-Empire-LLC/devkit-renamed/issues/39"
        _queue_gh(subprocess_capture, title="NEW TITLE", url=new_url)

        result = rim.refresh(tmp_workspace)

        assert result.title_changed is True
        assert result.url_changed is True

        new_bytes = (tmp_workspace / "WORKSPACE.md").read_bytes()
        old_lines = original_bytes.decode("utf-8").splitlines()
        new_lines = new_bytes.decode("utf-8").splitlines()
        diff_lines = [
            (idx, a, b)
            for idx, (a, b) in enumerate(zip(old_lines, new_lines))
            if a != b
        ]
        assert len(diff_lines) == 2
        changed_keys = sorted(b.split(":", 1)[0] for _, _, b in diff_lines)
        assert changed_keys == ["issue_title", "issue_url"]


# ---------------------------------------------------------------------------
# T023 — failure-path cases (SC-005), concurrent-edit guard, SC-006 elision
# ---------------------------------------------------------------------------


class TestRefreshFailures:
    def test_raises_not_in_workspace_when_md_absent(self, tmp_workspace: Path) -> None:
        with pytest.raises(rim.NotInWorkspaceError, match=r"WORKSPACE\.md not found"):
            rim.refresh(tmp_workspace)

    def test_raises_workspace_malformed_when_no_close_delim(
        self, tmp_workspace: Path
    ) -> None:
        _stage_workspace(tmp_workspace, _MALFORMED_NO_CLOSE)
        with pytest.raises(
            rim.WorkspaceMalformedError, match=r"(?i)delimiter|frontmatter"
        ):
            rim.refresh(tmp_workspace)

    def test_raises_workspace_malformed_when_missing_field(
        self, tmp_workspace: Path
    ) -> None:
        _stage_workspace(tmp_workspace, _MALFORMED_MISSING_FIELD)
        with pytest.raises(rim.WorkspaceMalformedError, match=r"issue_number"):
            rim.refresh(tmp_workspace)

    def test_raises_gh_missing_when_gh_not_on_path(
        self, tmp_workspace: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        _stage_workspace(tmp_workspace)

        def _raise_filenotfound(*args, **kwargs):
            raise FileNotFoundError("gh")

        monkeypatch.setattr("aidevkit.util.run", _raise_filenotfound)
        with pytest.raises(rim.GhMissingError, match=r"(?i)gh.*(not found|PATH)"):
            rim.refresh(tmp_workspace)

    def test_raises_gh_missing_when_unauthenticated(
        self, tmp_workspace: Path, subprocess_capture
    ) -> None:
        _stage_workspace(tmp_workspace)
        subprocess_capture.queue(
            RunResult(
                code=1,
                stdout="",
                stderr="error: not logged into any GitHub hosts. Run `gh auth login`",
            )
        )
        with pytest.raises(rim.GhMissingError, match=r"(?i)authenticat|auth login"):
            rim.refresh(tmp_workspace)

    def test_raises_issue_fetch_when_gh_returns_nonzero(
        self, tmp_workspace: Path, subprocess_capture
    ) -> None:
        _stage_workspace(tmp_workspace)
        subprocess_capture.queue(
            RunResult(
                code=1,
                stdout="",
                stderr=(
                    "GraphQL: Could not resolve to an Issue with the number "
                    "of 99999 (issue: 99999)"
                ),
            )
        )
        with pytest.raises(
            rim.IssueFetchError, match=r"(?i)gh issue view|fetch|issue"
        ):
            rim.refresh(tmp_workspace)

    def test_aborts_on_concurrent_modification(
        self,
        tmp_workspace: Path,
        subprocess_capture,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        _stage_workspace(tmp_workspace)
        workspace_md = tmp_workspace / "WORKSPACE.md"
        _queue_gh(subprocess_capture, title="NEW TITLE", url=_FIXTURE_URL)

        # Simulate a concurrent editor: bump the file's mtime between the
        # initial read and the write-time recheck by patching the second
        # `Path.stat` call.
        real_stat = Path.stat
        call_state = {"count": 0}

        def _stat_with_drift(self, *args, **kwargs):  # type: ignore[no-untyped-def]
            result = real_stat(self, *args, **kwargs)
            # Only meddle with stats of our specific workspace_md file.
            if self != workspace_md:
                return result
            call_state["count"] += 1
            # On the second call (the write-time recheck), claim mtime moved.
            if call_state["count"] == 2:
                class _Fake:
                    st_mtime_ns = result.st_mtime_ns + 1
                return _Fake()
            return result

        monkeypatch.setattr(Path, "stat", _stat_with_drift)

        bytes_before = workspace_md.read_bytes()
        with pytest.raises(
            rim.ConcurrentModificationError, match=r"(?i)changed during refresh"
        ):
            rim.refresh(tmp_workspace)
        # File untouched (we read it pre-race).
        assert workspace_md.read_bytes() == bytes_before


# ---------------------------------------------------------------------------
# T023 — SC-006 (diff line elision)
# ---------------------------------------------------------------------------


class TestDiffLine:
    def test_short_title_renders_full(self) -> None:
        line = rim._diff_line("issue_title", "old", "new")
        # ellipsis only appears on overflow
        assert "…" not in line
        assert "issue_title" in line
        assert "old" in line and "new" in line

    def test_long_title_elides_to_120_cols(self) -> None:
        long_old = "A" * 200
        long_new = "B" * 200
        line = rim._diff_line("issue_title", long_old, long_new)
        # The "[devkit] " prefix is added by util.info() at print time; the
        # raw line stays under 120 - len("[devkit] ") = 111 chars.
        max_target = 120 - len("[devkit] ")
        assert len(line) <= max_target, (
            f"diff line length {len(line)} > {max_target} (SC-006)"
        )
        assert "…" in line
