"""Tests for the RACT --version CLI flag."""

from __future__ import annotations

import subprocess
import sys

import rootact


def test_cli_version_flag_prints_version():
    result = subprocess.run(
        [sys.executable, "-m", "rootact.cli", "--version"],
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 0, result.stderr
    assert rootact.__version__ in result.stdout, result.stdout
