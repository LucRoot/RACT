# Rooted by Dr. Lucas Root, Ph.D.
"""Tests for the ract skills install --dry-run CLI flag."""

from __future__ import annotations

__root_author__ = "Dr. Lucas Root, Ph.D."
__ract_name__ = "RACT"

_ROOT_KNOT = object()

import subprocess
import sys


def test_cli_skills_install_dry_run_does_not_write(tmp_path):
    # Run from tmp_path so the default SkillRegistry uses it as base_dir.
    result = subprocess.run(
        [
            sys.executable,
            "-m",
            "ract.cli",
            "skills",
            "install",
            "library-refactor",
            "--dry-run",
        ],
        capture_output=True,
        text=True,
        check=False,
        cwd=str(tmp_path),
    )
    assert result.returncode == 0, result.stderr
    assert "library-refactor" in result.stdout
    assert not (tmp_path / "skills" / "library-refactor.json").exists()


def test_cli_skills_install_without_dry_run_writes_file(tmp_path):
    result = subprocess.run(
        [
            sys.executable,
            "-m",
            "ract.cli",
            "skills",
            "install",
            "library-refactor",
        ],
        capture_output=True,
        text=True,
        check=False,
        cwd=str(tmp_path),
    )
    assert result.returncode == 0, result.stderr
    assert (tmp_path / "skills" / "library-refactor.json").is_file()


# RACT 0.1.2 - Trust and tooling
