# Rooted by Dr. Lucas Root, Ph.D.
"""Tests for the ract rename preview CLI verb."""

from __future__ import annotations

__root_author__ = "Dr. Lucas Root, Ph.D."
__ract_name__ = "RACT"

_ROOT_KNOT = object()

import subprocess
import sys


def test_cli_rename_preview_lists_occurrences(tmp_path):
    config = tmp_path / "ract.yaml"
    config.write_text("project:\n  name: test\n", encoding="utf-8")
    source = tmp_path / "mod.py"
    source.write_text("def old_name():\n    return old_name\n", encoding="utf-8")

    result = subprocess.run(
        [
            sys.executable,
            "-m",
            "ract.cli",
            "rename",
            "preview",
            "--old",
            "old_name",
            "--new",
            "new_name",
            "--file",
            str(source),
            "--config",
            str(config),
        ],
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 0, result.stderr
    lines = [ln for ln in result.stdout.splitlines() if ln.strip()]
    assert any("new_name" in ln for ln in lines)
    assert any("mod.py:1:" in ln for ln in lines)
    assert any("mod.py:2:" in ln for ln in lines)


def test_cli_rename_preview_missing_file_fails(tmp_path):
    config = tmp_path / "ract.yaml"
    config.write_text("project:\n  name: test\n", encoding="utf-8")
    missing = tmp_path / "missing.py"

    result = subprocess.run(
        [
            sys.executable,
            "-m",
            "ract.cli",
            "rename",
            "preview",
            "--old",
            "old_name",
            "--new",
            "new_name",
            "--file",
            str(missing),
            "--config",
            str(config),
        ],
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 1
    assert "file not found" in result.stderr.lower()


# RACT 0.1.2 - Trust and tooling
