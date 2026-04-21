"""T034 [US2]: `parse_trunk_file` grammar coverage."""

from __future__ import annotations

from aidevkit import sync as _sync


def test_valid_single_line(tmp_path):
    p = tmp_path / "TRUNK.md"
    p.write_text("develop\n")
    assert _sync.parse_trunk_file(p) == "develop"


def test_leading_comment_and_blank_lines(tmp_path):
    p = tmp_path / "TRUNK.md"
    p.write_text("# pick non-main trunk for this repo\n\n\nmaster\n")
    assert _sync.parse_trunk_file(p) == "master"


def test_whitespace_inside_value_returns_none(tmp_path):
    p = tmp_path / "TRUNK.md"
    p.write_text("main # the default\n")
    assert _sync.parse_trunk_file(p) is None


def test_value_exceeding_255_chars_returns_none(tmp_path):
    p = tmp_path / "TRUNK.md"
    p.write_text("x" * 300 + "\n")
    assert _sync.parse_trunk_file(p) is None


def test_non_utf8_returns_none(tmp_path):
    p = tmp_path / "TRUNK.md"
    p.write_bytes(b"\xff\xfe\x00bad")
    assert _sync.parse_trunk_file(p) is None


def test_missing_file_returns_none(tmp_path):
    p = tmp_path / "NONEXISTENT.md"
    assert _sync.parse_trunk_file(p) is None


def test_trim_leading_trailing_whitespace(tmp_path):
    p = tmp_path / "TRUNK.md"
    p.write_text("   develop   \n")
    assert _sync.parse_trunk_file(p) == "develop"
