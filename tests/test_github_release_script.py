"""Tests for the GitHub release helper script."""

from __future__ import annotations


import sys
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent / "scripts"))

from github_release import (  # type: ignore[import-not-found]
    _bump_version,
    _read_version,
    _update_changelog,
    _working_tree_is_clean,
    _write_version,
    main,
)


def test_bump_version_patch():
    assert _bump_version("0.1.0", "patch") == "0.1.1"


def test_bump_version_minor():
    assert _bump_version("0.1.0", "minor") == "0.2.0"


def test_bump_version_major():
    assert _bump_version("1.2.3", "major") == "2.0.0"


def test_bump_version_rejects_non_semver():
    with pytest.raises(SystemExit):
        _bump_version("0.1.0-alpha", "patch")


def test_read_version(tmp_path):
    pyproject = tmp_path / "pyproject.toml"
    pyproject.write_text('version = "0.2.0"\n', encoding="utf-8")
    assert _read_version(tmp_path) == "0.2.0"


def test_read_version_missing_file(tmp_path):
    with pytest.raises(SystemExit):
        _read_version(tmp_path)


def test_write_version(tmp_path):
    pyproject = tmp_path / "pyproject.toml"
    pyproject.write_text('[project]\nversion = "0.1.0"\n', encoding="utf-8")
    _write_version(tmp_path, "0.1.1")
    assert 'version = "0.1.1"' in pyproject.read_text(encoding="utf-8")


def test_update_changelog_prepends_section(tmp_path):
    changelog = tmp_path / "CHANGELOG.md"
    changelog.write_text("# Changelog\n\n## [0.1.0]\n- init\n", encoding="utf-8")
    _update_changelog(tmp_path, "0.1.1", "Bug fixes")
    text = changelog.read_text(encoding="utf-8")
    assert "## [0.1.1]" in text
    assert "Bug fixes" in text
    assert "## [0.1.0]" in text


def test_working_tree_is_clean(tmp_path):
    with patch("github_release._run") as mock_run:
        mock_run.return_value = MagicMock(returncode=0, stdout="")
        assert _working_tree_is_clean(tmp_path) is True


def test_working_tree_is_dirty(tmp_path):
    with patch("github_release._run") as mock_run:
        mock_run.return_value = MagicMock(returncode=0, stdout=" M file.py\n")
        assert _working_tree_is_clean(tmp_path) is False


def test_main_dry_run_prints_and_exits(tmp_path, capsys):
    pyproject = tmp_path / "pyproject.toml"
    pyproject.write_text('version = "0.1.0"\n', encoding="utf-8")
    assert main(["--project-dir", str(tmp_path), "--dry-run"]) == 0
    captured = capsys.readouterr()
    assert "current version: 0.1.0" in captured.out
    assert "dry run" in captured.out


def test_main_refuses_version_and_bump_together(tmp_path):
    pyproject = tmp_path / "pyproject.toml"
    pyproject.write_text('version = "0.1.0"\n', encoding="utf-8")
    with pytest.raises(SystemExit):
        main(["--project-dir", str(tmp_path), "--version", "0.2.0", "--bump", "minor"])


# RACT 0.1.1 - Trust and Tooling
