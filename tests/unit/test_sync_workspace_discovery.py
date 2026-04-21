"""T011 [US1]: `find_workspace_root` ancestor-walk logic."""

from __future__ import annotations

import pytest
import typer

from aidevkit import sync as _sync


def _make_workspace(tmp_path, name: str = "AuthService-issue-7"):
    ws = tmp_path / name
    ws.mkdir()
    wt = ws / "AuthService"
    wt.mkdir()
    (wt / ".git").write_text("gitdir: ../\n")
    return ws, wt


def test_cwd_at_workspace_root_returns_root(tmp_path, monkeypatch):
    ws, _ = _make_workspace(tmp_path)
    monkeypatch.setenv("APP_EMPIRE_WORKTREES_HOME", str(tmp_path))
    assert _sync.find_workspace_root(ws).resolve() == ws.resolve()


def test_cwd_inside_worktree_returns_root(tmp_path, monkeypatch):
    ws, wt = _make_workspace(tmp_path)
    monkeypatch.setenv("APP_EMPIRE_WORKTREES_HOME", str(tmp_path))
    assert _sync.find_workspace_root(wt).resolve() == ws.resolve()


def test_cwd_in_nested_subdir_returns_root(tmp_path, monkeypatch):
    ws, wt = _make_workspace(tmp_path)
    nested = wt / "src" / "deeply" / "nested"
    nested.mkdir(parents=True)
    monkeypatch.setenv("APP_EMPIRE_WORKTREES_HOME", str(tmp_path))
    assert _sync.find_workspace_root(nested).resolve() == ws.resolve()


def test_no_matching_ancestor_exits_not_in_workspace(tmp_path, monkeypatch):
    monkeypatch.delenv("APP_EMPIRE_WORKTREES_HOME", raising=False)
    bare = tmp_path / "not-a-workspace"
    bare.mkdir()
    with pytest.raises(typer.Exit) as exc:
        _sync.find_workspace_root(bare)
    from aidevkit.util import E_NOT_IN_WORKSPACE

    assert exc.value.exit_code == E_NOT_IN_WORKSPACE


def test_worktree_home_upper_bound_honored(tmp_path, monkeypatch):
    # Create an impostor "parent" that matches the pattern above the home dir;
    # the walk must stop at APP_EMPIRE_WORKTREES_HOME.
    impostor = tmp_path / "Other-issue-99"
    impostor.mkdir()
    (impostor / "FakeRepo").mkdir()
    (impostor / "FakeRepo" / ".git").write_text("gitdir: ../\n")

    home = tmp_path / "home"
    home.mkdir()
    bare = home / "plain"
    bare.mkdir()
    monkeypatch.setenv("APP_EMPIRE_WORKTREES_HOME", str(home))
    with pytest.raises(typer.Exit):
        _sync.find_workspace_root(bare)


def test_name_pattern_without_worktree_child_is_rejected(tmp_path, monkeypatch):
    ws = tmp_path / "RepoX-issue-3"
    ws.mkdir()
    # No worktree subdirectory at all.
    monkeypatch.setenv("APP_EMPIRE_WORKTREES_HOME", str(tmp_path))
    with pytest.raises(typer.Exit):
        _sync.find_workspace_root(ws)
