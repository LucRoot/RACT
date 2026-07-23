"""Tests for the ract manifest CLI verb."""

from __future__ import annotations


import subprocess
import sys


def test_cli_manifest_appears_in_help():
    result = subprocess.run(
        [sys.executable, "-m", "ract.cli", "manifest", "--help"],
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 0, result.stderr
    assert "manifest" in result.stdout
