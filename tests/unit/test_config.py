"""Unit tests for `aidevkit.config` — projects-home resolution and merged-config schema."""
from __future__ import annotations

from pathlib import Path

import pytest
import typer

from aidevkit import config as _config
from aidevkit.config import Config, load_merged_config, resolve_projects_home


def _write_yaml(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content)


def _make_projects_home(tmp_path: Path, **overrides) -> Path:
    """Create a minimal valid projects-home with .devkit/config.yaml."""
    tmp_path.mkdir(parents=True, exist_ok=True)
    ph = tmp_path / "projects"
    ph.mkdir(parents=True, exist_ok=True)
    workspaces_home = overrides.pop("workspaces_home", tmp_path / "worktrees")
    workspaces_home.mkdir(parents=True, exist_ok=True)
    fields = {
        "version": 1,
        "org": "test-org",
        "workspaces_home": str(workspaces_home),
        **overrides,
    }
    lines = ["version: {version}".format(**fields)]
    if fields.get("org"):
        lines.append("org: {org}".format(**fields))
    if fields.get("workspaces_home"):
        lines.append("workspaces_home: {workspaces_home}".format(**fields))
    if "always_include_repos" in fields and fields["always_include_repos"] is not None:
        lines.append("always_include_repos:")
        for entry in fields["always_include_repos"]:
            lines.append(f"  - {entry}")
    _write_yaml(ph / ".devkit" / "config.yaml", "\n".join(lines) + "\n")
    return ph


# ----- resolve_projects_home --------------------------------------------------

def test_resolve_via_env_var(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    ph = _make_projects_home(tmp_path)
    monkeypatch.setenv("PROJECTS_HOME", str(ph))
    monkeypatch.setattr(_config, "_GLOBAL_CONFIG_PATH", tmp_path / "no-such-global.yaml")
    assert resolve_projects_home() == ph.resolve()


def test_resolve_via_global_field(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    ph = _make_projects_home(tmp_path)
    fake_global = tmp_path / "fake-home" / ".devkit" / "config.yaml"
    _write_yaml(fake_global, f"version: 1\nprojects_home: {ph}\n")
    monkeypatch.delenv("PROJECTS_HOME", raising=False)
    monkeypatch.setattr(_config, "_GLOBAL_CONFIG_PATH", fake_global)
    assert resolve_projects_home() == ph.resolve()


def test_resolve_env_var_wins_over_global(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    ph_env = _make_projects_home(tmp_path / "from_env_subdir")
    ph_global = _make_projects_home(tmp_path / "from_global_subdir")
    fake_global = tmp_path / "fake-home" / ".devkit" / "config.yaml"
    _write_yaml(fake_global, f"version: 1\nprojects_home: {ph_global}\n")
    monkeypatch.setenv("PROJECTS_HOME", str(ph_env))
    monkeypatch.setattr(_config, "_GLOBAL_CONFIG_PATH", fake_global)
    assert resolve_projects_home() == ph_env.resolve()


def test_resolve_failure_names_both_paths(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture
) -> None:
    monkeypatch.delenv("PROJECTS_HOME", raising=False)
    monkeypatch.setattr(_config, "_GLOBAL_CONFIG_PATH", tmp_path / "no-such-global.yaml")
    with pytest.raises(typer.Exit) as exc_info:
        resolve_projects_home()
    assert exc_info.value.exit_code == 12  # E_DEP_MISSING
    captured = capsys.readouterr()
    assert "$PROJECTS_HOME" in captured.err
    assert "~/.devkit/config.yaml#projects_home" in captured.err


def test_resolve_env_var_set_but_no_devkit(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture
) -> None:
    monkeypatch.setenv("PROJECTS_HOME", str(tmp_path / "missing"))
    monkeypatch.setattr(_config, "_GLOBAL_CONFIG_PATH", tmp_path / "no-global.yaml")
    with pytest.raises(typer.Exit):
        resolve_projects_home()
    captured = capsys.readouterr()
    assert "no .devkit/config.yaml found there" in captured.err


# ----- schema validation ------------------------------------------------------

def test_minimal_valid_config(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    ph = _make_projects_home(tmp_path)
    monkeypatch.setattr(_config, "_GLOBAL_CONFIG_PATH", tmp_path / "no-global.yaml")
    cfg = load_merged_config(ph)
    assert cfg.version == 1
    assert cfg.org == "test-org"
    assert cfg.workspaces_home == tmp_path / "worktrees"
    assert cfg.always_include_repos == ()


def test_unknown_version_refused(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    ph = _make_projects_home(tmp_path, version=99)
    monkeypatch.setattr(_config, "_GLOBAL_CONFIG_PATH", tmp_path / "no-global.yaml")
    with pytest.raises(typer.Exit) as exc_info:
        load_merged_config(ph)
    assert exc_info.value.exit_code == 70  # E_CONFIG_INVALID


def test_invalid_org_refused(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    ph = _make_projects_home(tmp_path, org="bad/slash")
    monkeypatch.setattr(_config, "_GLOBAL_CONFIG_PATH", tmp_path / "no-global.yaml")
    with pytest.raises(typer.Exit):
        load_merged_config(ph)


def test_workspaces_home_must_exist(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture
) -> None:
    nonexistent = tmp_path / "no-such-dir"
    ph = tmp_path / "projects"
    ph.mkdir()
    _write_yaml(
        ph / ".devkit" / "config.yaml",
        f"version: 1\norg: x\nworkspaces_home: {nonexistent}\n",
    )
    monkeypatch.setattr(_config, "_GLOBAL_CONFIG_PATH", tmp_path / "no-global.yaml")
    with pytest.raises(typer.Exit):
        load_merged_config(ph)
    captured = capsys.readouterr()
    assert "workspaces_home" in captured.err
    assert "does not exist" in captured.err


def test_always_include_repos_must_be_owner_repo_form(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    ph = _make_projects_home(tmp_path, always_include_repos=["bare-name"])
    monkeypatch.setattr(_config, "_GLOBAL_CONFIG_PATH", tmp_path / "no-global.yaml")
    with pytest.raises(typer.Exit):
        load_merged_config(ph)


def test_unknown_field_refused(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    ph = tmp_path / "projects"
    ph.mkdir()
    _write_yaml(
        ph / ".devkit" / "config.yaml",
        "version: 1\norg: x\nworkspaces_home: {ws}\nunknown_field: oops\n".format(
            ws=tmp_path
        ),
    )
    monkeypatch.setattr(_config, "_GLOBAL_CONFIG_PATH", tmp_path / "no-global.yaml")
    with pytest.raises(typer.Exit) as exc_info:
        load_merged_config(ph)
    assert exc_info.value.exit_code == 70


def test_required_field_missing(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture
) -> None:
    ph = tmp_path / "projects"
    ph.mkdir()
    _write_yaml(
        ph / ".devkit" / "config.yaml",
        f"version: 1\nworkspaces_home: {tmp_path}\n",
    )
    monkeypatch.setattr(_config, "_GLOBAL_CONFIG_PATH", tmp_path / "no-global.yaml")
    with pytest.raises(typer.Exit):
        load_merged_config(ph)
    captured = capsys.readouterr()
    assert "org" in captured.err


# ----- merge semantics --------------------------------------------------------

def test_projects_home_overrides_global_scalar(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    ph = _make_projects_home(tmp_path, org="from-projects-home")
    fake_global = tmp_path / "fake-home" / ".devkit" / "config.yaml"
    _write_yaml(fake_global, "version: 1\norg: from-global\n")
    monkeypatch.setattr(_config, "_GLOBAL_CONFIG_PATH", fake_global)
    cfg = load_merged_config(ph)
    assert cfg.org == "from-projects-home"


def test_global_provides_field_when_projects_home_omits_it(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    ph = tmp_path / "projects"
    ph.mkdir()
    workspaces = tmp_path / "worktrees"
    workspaces.mkdir()
    # projects-home omits org
    _write_yaml(
        ph / ".devkit" / "config.yaml",
        f"version: 1\nworkspaces_home: {workspaces}\n",
    )
    fake_global = tmp_path / "fake-home" / ".devkit" / "config.yaml"
    _write_yaml(fake_global, "version: 1\norg: from-global\n")
    monkeypatch.setattr(_config, "_GLOBAL_CONFIG_PATH", fake_global)
    cfg = load_merged_config(ph)
    assert cfg.org == "from-global"


def test_always_include_replace_semantics(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """When projects-home sets always_include_repos, global is ignored entirely."""
    ph = _make_projects_home(tmp_path, always_include_repos=["org/from-ph"])
    fake_global = tmp_path / "fake-home" / ".devkit" / "config.yaml"
    _write_yaml(
        fake_global,
        "version: 1\nalways_include_repos:\n  - org/from-global\n",
    )
    monkeypatch.setattr(_config, "_GLOBAL_CONFIG_PATH", fake_global)
    cfg = load_merged_config(ph)
    assert cfg.always_include_repos == ("org/from-ph",)


def test_always_include_falls_back_to_global_when_projects_home_omits(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    ph = _make_projects_home(tmp_path)
    fake_global = tmp_path / "fake-home" / ".devkit" / "config.yaml"
    _write_yaml(
        fake_global,
        "version: 1\nalways_include_repos:\n  - org/from-global\n",
    )
    monkeypatch.setattr(_config, "_GLOBAL_CONFIG_PATH", fake_global)
    cfg = load_merged_config(ph)
    assert cfg.always_include_repos == ("org/from-global",)


def test_projects_home_only_field_rejected_at_projects_home_tier(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """`projects_home` is a global-only field; rejecting it at the projects-home tier
    catches a circular config bug before it confuses the resolver."""
    ph = tmp_path / "projects"
    ph.mkdir()
    workspaces = tmp_path / "worktrees"
    workspaces.mkdir()
    _write_yaml(
        ph / ".devkit" / "config.yaml",
        f"version: 1\norg: x\nworkspaces_home: {workspaces}\nprojects_home: /elsewhere\n",
    )
    monkeypatch.setattr(_config, "_GLOBAL_CONFIG_PATH", tmp_path / "no-global.yaml")
    with pytest.raises(typer.Exit):
        load_merged_config(ph)


def test_yaml_parse_error_surfaced(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    ph = tmp_path / "projects"
    ph.mkdir()
    (ph / ".devkit").mkdir()
    (ph / ".devkit" / "config.yaml").write_text("version: 1\n  bad: : indent\n")
    monkeypatch.setattr(_config, "_GLOBAL_CONFIG_PATH", tmp_path / "no-global.yaml")
    with pytest.raises(typer.Exit):
        load_merged_config(ph)


def test_config_dataclass_is_frozen() -> None:
    cfg = Config(
        version=1,
        org="x",
        workspaces_home=Path("/"),
        source_projects_home_path=Path("/x.yaml"),
    )
    with pytest.raises((AttributeError, TypeError)):
        cfg.org = "y"  # type: ignore[misc]
