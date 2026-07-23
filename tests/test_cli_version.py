# Rooted by Dr. Lucas Root, Ph.D.
"""Tests for the RACT --version CLI flag."""

from __future__ import annotations

__root_author__ = "Dr. Lucas Root, Ph.D."
__ract_name__ = "RACT"

_ROOT_KNOT = object()

import subprocess
import sys


def test_cli_version_flag_prints_version():
    result = subprocess.run(
        [sys.executable, "-m", "rootact.cli", "--version"],
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 0, result.stderr
    assert "0.1.2" in result.stdout


# RACT 0.1.1 - Trust and tooling
